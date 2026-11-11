# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-free ownership, cleanup, and orphan-reconciliation tests."""

from __future__ import annotations

import ast
import builtins
import json
import os
import signal
import stat
import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from web.extensions.opentunnel_sharing import profile_state
from web.extensions.opentunnel_sharing.cleanup import (
    OWNER_RECORD_FILENAME,
    OWNER_RECORD_SCHEMA,
    CleanupDependencies,
    OwnedProcessRecord,
    ProcessIdentity,
    ProcessObservation,
    RouteObservation,
    clear_owner_record,
    load_owner_record,
    reconcile_orphans,
    write_owner_record,
)
from web.extensions.opentunnel_sharing.companion import CompanionResolution
from web.extensions.opentunnel_sharing.controller import (
    RouteStatus,
    SharingController,
    SharingDependencies,
    SharingState,
)
from web.extensions.opentunnel_sharing.origin_binding import PublicOriginBinder
from web.extensions.opentunnel_sharing.profile_state import (
    DEFAULT_PROFILE,
    ProfileLayout,
    prepare_profile,
)

TEST_ORIGIN = "https://cleanup-sentinel.example"
TEST_ROUTE_ID = "neq-player-route"
TEST_SECRET = "CLEANUP_SENTINEL_SECRET"
TEST_TIMESTAMP = "2026-11-11T12:00:00Z"


class FakeRouteTable:
    """A profile-scoped route table which records all lookup/removal calls."""

    def __init__(self, profile: str = DEFAULT_PROFILE) -> None:
        self.profile = profile
        self.state = "absent"
        self.route_id: str | None = None
        self.lookups: list[tuple[str, str | None]] = []
        self.removals: list[tuple[str, str]] = []
        self.remove_fails = False

    def lookup(self, profile: str, route_id: str | None) -> RouteObservation:
        self.lookups.append((profile, route_id))
        if profile != self.profile:
            return RouteObservation("foreign", "another-profile", self.route_id)
        if self.state == "absent":
            return RouteObservation("absent", profile)
        if self.state == "unknown":
            return RouteObservation("unknown")
        if self.state == "foreign":
            return RouteObservation("foreign", "another-profile", self.route_id)
        if route_id is not None and route_id != self.route_id:
            return RouteObservation("unknown")
        return RouteObservation("owned", profile, self.route_id)

    def remove(self, profile: str, route_id: str) -> bool:
        self.removals.append((profile, route_id))
        if (
            self.remove_fails
            or profile != self.profile
            or self.state != "owned"
            or route_id != self.route_id
        ):
            return False
        self.state = "absent"
        self.route_id = None
        return True


class FakeProcessTable:
    def __init__(self, result: ProcessIdentity | ProcessObservation | None) -> None:
        self.result = result
        self.calls: list[int] = []

    def __call__(self, pid: int) -> ProcessIdentity | ProcessObservation | None:
        self.calls.append(pid)
        return self.result


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0
        self.delays: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, delay: float) -> None:
        self.delays.append(delay)
        self.now += delay


class FakeOwnedHandle:
    """OwnedCompanion-shaped handle with no access to a real OS process."""

    def __init__(self, layout: ProfileLayout, executable: Path, pid: int) -> None:
        self._layout = layout
        self._binary_path = executable.resolve()
        self._pid = pid
        self._identity_token = "creation-token-%d" % pid
        self._state = "stopped"
        self._reaped = True
        self.start_calls = 0
        self.stop_calls = 0

    @property
    def state(self) -> str:
        return self._state

    @property
    def reaped(self) -> bool:
        return self._reaped

    def start(self, _deadline: float) -> str:
        self.start_calls += 1
        self._state = "running"
        self._reaped = False
        return "running"

    def stop(self, _deadline: float) -> bool:
        self.stop_calls += 1
        if self._state == "running":
            self._state = "stopped"
            self._reaped = True
        return self._reaped

    def diagnostics(self) -> dict[str, object]:
        return {"state": self._state}


class FakeSecurity:
    def __init__(self) -> None:
        self.origin: str | None = None
        self.generation: int | None = None
        self.active_generation: int | None = None
        self.highest_generation = 0

    @property
    def public_origin_status(self) -> tuple[bool, int | None]:
        return self.origin is not None, self.generation

    def bind_public_origin(self, generation: int, origin: object) -> bool:
        if not isinstance(origin, str) or self.active_generation != generation:
            return False
        if self.origin is not None:
            return self.origin == origin and self.generation == generation
        self.origin = origin
        self.generation = generation
        return True

    def set_active_origin_generation(self, generation: int | None) -> bool:
        if generation is None:
            self.active_generation = None
            self.origin = None
            self.generation = None
            return True
        if type(generation) is not int or generation < self.highest_generation:
            return False
        if generation == self.active_generation:
            return True
        self.active_generation = generation
        self.highest_generation = max(self.highest_generation, generation)
        self.origin = None
        self.generation = None
        return True

    def clear_public_origin(self, _reason: str | None = None) -> None:
        self.origin = None
        self.generation = None
        self.active_generation = None


class CleanupControllerFixture:
    def __init__(self, test: unittest.TestCase) -> None:
        self.test = test
        self.layout, self.binary = test.make_layout()
        self.resolution = CompanionResolution(
            "resolved", "resolved", self.binary
        )
        self.routes = FakeRouteTable()
        self.processes = FakeProcessTable(ProcessObservation("gone"))
        self.signals: list[tuple[int, int]] = []
        self.clock = FakeClock()
        self.listener_running = False
        self.listener_start_calls = 0
        self.listener_stop_calls = 0
        self.session_revocations = 0
        self.handles: list[FakeOwnedHandle] = []
        self.security = FakeSecurity()
        self.binder = PublicOriginBinder(self.security)  # type: ignore[arg-type]
        self.route_failure = False

        cleanup = CleanupDependencies(
            layout=self.layout,
            process_table=self.processes,
            route_table=self.routes,
            signaller=self._signal,
            term_wait_seconds=0.1,
            kill_wait_seconds=0.1,
            poll_interval_seconds=0.05,
            clock=self.clock.clock,
            sleeper=self.clock.sleep,
        )
        deps = SharingDependencies(
            local_runtime_ok=lambda: True,
            assets_ok=lambda: True,
            start_player_listener=self._start_listener,
            stop_player_listener=self._stop_listener,
            listener_authenticated_probe=lambda: self.listener_running,
            load_verifier=lambda: type("Verifier", (), {"state": "present", "verifier": object()})(),
            resolve_companion=lambda: self.resolution,
            identity_initialized=lambda: True,
            start_companion=self._start_companion,
            route_status=self._route_status,
            origin_binder=self.binder,
            companion_start_deadline_seconds=1.0,
            companion_stop_deadline_seconds=1.0,
            route_wait_seconds=0.0,
            cleanup=cleanup,
        )
        self.controller = SharingController(deps)

    def _signal(self, pid: int, signal_number: int) -> None:
        self.signals.append((pid, signal_number))

    def _start_listener(self) -> bool:
        self.listener_start_calls += 1
        self.listener_running = True
        return True

    def _stop_listener(self) -> None:
        self.listener_stop_calls += 1
        self.session_revocations += 1
        self.listener_running = False

    def _start_companion(self, _generation: int) -> FakeOwnedHandle:
        handle = FakeOwnedHandle(self.layout, self.binary, 5100 + len(self.handles))
        self.handles.append(handle)
        return handle

    def _route_status(self, _handle: object, generation: int) -> RouteStatus:
        self.routes.state = "owned"
        self.routes.route_id = TEST_ROUTE_ID
        return RouteStatus(not self.route_failure, TEST_ORIGIN, generation)


class PlayerSharingCleanupTests(unittest.TestCase):
    def setUp(self) -> None:
        Path("tmp").mkdir(exist_ok=True)
        self.tempdir = tempfile.TemporaryDirectory(dir="tmp")
        self.addCleanup(self.tempdir.cleanup)
        self.scratch = Path(self.tempdir.name)
        self.install_root = self.scratch / "install-root"
        self.install_root.mkdir(mode=0o700)
        self.state_root = self.scratch / "state"

    def make_layout(
        self, profile: str = DEFAULT_PROFILE
    ) -> tuple[ProfileLayout, Path]:
        binary = (
            self.install_root
            / "runtime/opentunnel/v0.6.2/opentunnel-linux-arm64/opentunnel"
        )
        binary.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not binary.exists():
            binary.write_bytes(b"inert companion")
            binary.chmod(0o700)
        with (
            mock.patch.object(
                profile_state, "_REPOSITORY_ROOT", self.install_root
            ),
            mock.patch.object(profile_state, "_INSTALL_ROOT", self.install_root),
        ):
            state = prepare_profile(
                self.state_root,
                install_marker="cleanup-test-install",
                profile=profile,
                create=True,
            )
        self.assertEqual(state.state, "ready")
        assert state.layout is not None
        return state.layout, binary.resolve()

    def make_record(
        self,
        layout: ProfileLayout,
        binary: Path,
        *,
        pid: int = 4242,
        profile: str | None = None,
        uid: int | None = None,
        creation_token: str = "creation-token-1",
        route_id: str | None = None,
    ) -> OwnedProcessRecord:
        return OwnedProcessRecord(
            profile=layout.profile if profile is None else profile,
            uid=os.getuid() if uid is None else uid,
            pid=pid,
            creation_token=creation_token,
            exe_path=str(binary),
            started_at=TEST_TIMESTAMP,
            generation=1,
            route_id=route_id,
        )

    def matching_identity(
        self,
        record: OwnedProcessRecord,
        *,
        exe_path: str | None = None,
        profile: str | None = None,
        uid: int | None = None,
        creation_token: str | None = None,
    ) -> ProcessIdentity:
        return ProcessIdentity(
            pid=record.pid,
            creation_token=(
                record.creation_token if creation_token is None else creation_token
            ),
            exe_path=record.exe_path if exe_path is None else exe_path,
            uid=record.uid if uid is None else uid,
            profile_marker=record.profile if profile is None else profile,
        )

    def test_owner_record_is_atomic_private_and_strictly_loaded(self) -> None:
        layout, binary = self.make_layout()
        record = self.make_record(layout, binary, route_id=TEST_ROUTE_ID)

        self.assertTrue(write_owner_record(layout, record))
        loaded = load_owner_record(layout)

        self.assertEqual((loaded.state, loaded.record), ("valid", record))
        metadata = (layout.state_home / OWNER_RECORD_FILENAME).lstat()
        self.assertEqual(stat.S_IMODE(metadata.st_mode), 0o600)
        self.assertEqual(metadata.st_uid, os.getuid())
        raw = json.loads((layout.state_home / OWNER_RECORD_FILENAME).read_text())
        self.assertEqual(raw["schema"], OWNER_RECORD_SCHEMA)
        self.assertEqual(raw["profile"], DEFAULT_PROFILE)
        self.assertNotIn("url", raw)
        self.assertNotIn("hostname", raw)
        self.assertNotIn("tunnel_id", raw)
        self.assertNotIn(TEST_SECRET, repr(loaded))
        self.assertTrue(clear_owner_record(layout, record))
        self.assertFalse((layout.state_home / OWNER_RECORD_FILENAME).exists())

    def test_owner_writer_never_overwrites_foreign_or_invalid_record(self) -> None:
        layout, binary = self.make_layout()
        owner_path = layout.state_home / OWNER_RECORD_FILENAME
        owner_path.write_text("{bad-json", encoding="ascii")
        owner_path.chmod(0o600)
        before = owner_path.read_bytes()

        self.assertFalse(write_owner_record(layout, self.make_record(layout, binary)))
        self.assertFalse(clear_owner_record(layout))
        self.assertEqual(owner_path.read_bytes(), before)
        self.assertEqual(load_owner_record(layout).state, "ambiguous")

    def test_normal_stop_clears_record_route_listener_and_reaps_once(self) -> None:
        fixture = CleanupControllerFixture(self)
        ready = fixture.controller.start()
        self.assertEqual(ready.state, SharingState.READY)
        owner_path = fixture.layout.state_home / OWNER_RECORD_FILENAME
        self.assertTrue(owner_path.exists())
        self.assertEqual(fixture.routes.state, "owned")

        stopped = fixture.controller.stop()
        stopped_again = fixture.controller.stop()

        self.assertEqual(stopped.reason, "stopped")
        self.assertEqual(stopped_again.state, SharingState.OFF)
        self.assertEqual(fixture.handles[0].stop_calls, 1)
        self.assertTrue(fixture.handles[0].reaped)
        self.assertFalse(owner_path.exists())
        self.assertEqual(fixture.routes.state, "absent")
        self.assertEqual(fixture.routes.removals, [(DEFAULT_PROFILE, TEST_ROUTE_ID)])
        self.assertFalse(fixture.listener_running)
        self.assertEqual(fixture.listener_stop_calls, 1)
        self.assertEqual(fixture.session_revocations, 1)
        self.assertEqual(fixture.signals, [])

    def test_launcher_shutdown_during_ready_cleans_all_owned_resources(self) -> None:
        fixture = CleanupControllerFixture(self)
        self.assertEqual(fixture.controller.start().state, SharingState.READY)

        shutdown = fixture.controller.shutdown()

        self.assertEqual(shutdown.state, SharingState.OFF)
        self.assertEqual(shutdown.reason, "shutting_down")
        self.assertEqual(fixture.handles[0].stop_calls, 1)
        self.assertTrue(fixture.handles[0].reaped)
        self.assertEqual(fixture.routes.state, "absent")
        self.assertFalse((fixture.layout.state_home / OWNER_RECORD_FILENAME).exists())
        self.assertFalse(fixture.listener_running)
        self.assertEqual(fixture.session_revocations, 1)
        self.assertEqual(fixture.controller.start().reason, "shutting_down")

    def test_failed_startup_removes_record_route_and_started_process(self) -> None:
        fixture = CleanupControllerFixture(self)
        fixture.route_failure = True

        failed = fixture.controller.start()

        self.assertEqual(failed.state, SharingState.FAILED)
        self.assertEqual(failed.reason, "route_unhealthy")
        self.assertEqual(fixture.handles[0].stop_calls, 1)
        self.assertTrue(fixture.handles[0].reaped)
        self.assertEqual(fixture.routes.state, "absent")
        self.assertEqual(fixture.routes.removals, [(DEFAULT_PROFILE, TEST_ROUTE_ID)])
        self.assertFalse((fixture.layout.state_home / OWNER_RECORD_FILENAME).exists())
        self.assertFalse(fixture.listener_running)
        self.assertEqual(fixture.session_revocations, 1)

    def test_matching_stale_owned_orphan_uses_term_then_kill_and_stays_off(self) -> None:
        layout, binary = self.make_layout()
        record = self.make_record(layout, binary, route_id=TEST_ROUTE_ID)
        self.assertTrue(write_owner_record(layout, record))
        routes = FakeRouteTable()
        routes.state = "owned"
        routes.route_id = TEST_ROUTE_ID
        processes = FakeProcessTable(self.matching_identity(record))
        clock = FakeClock()
        signals: list[tuple[int, int]] = []

        def signal_fake(pid: int, signal_number: int) -> None:
            signals.append((pid, signal_number))
            if signal_number == signal.SIGKILL:
                processes.result = ProcessObservation("gone")

        result = reconcile_orphans(
            layout,
            CompanionResolution("resolved", "resolved", binary),
            process_table=processes,
            route_table=routes,
            signaller=signal_fake,
            term_wait_seconds=0.1,
            kill_wait_seconds=0.1,
            poll_interval_seconds=0.05,
            clock=clock.clock,
            sleeper=clock.sleep,
        )

        self.assertEqual(result.state, "reconciled")
        self.assertTrue(result.sharing_available)
        self.assertEqual(signals, [(record.pid, signal.SIGTERM), (record.pid, signal.SIGKILL)])
        self.assertEqual(routes.removals, [(DEFAULT_PROFILE, TEST_ROUTE_ID)])
        self.assertEqual(routes.state, "absent")
        self.assertEqual(load_owner_record(layout).state, "absent")
        self.assertTrue(clock.delays)
        self.assertFalse(any("start" in fact for fact in result.facts))

    def test_stale_owner_record_with_dead_pid_removes_only_its_route(self) -> None:
        layout, binary = self.make_layout()
        record = self.make_record(layout, binary, route_id=TEST_ROUTE_ID)
        self.assertTrue(write_owner_record(layout, record))
        routes = FakeRouteTable()
        routes.state = "owned"
        routes.route_id = TEST_ROUTE_ID
        processes = FakeProcessTable(ProcessObservation("gone"))
        signals: list[tuple[int, int]] = []

        result = reconcile_orphans(
            layout,
            CompanionResolution("resolved", "resolved", binary),
            process_table=processes,
            route_table=routes,
            signaller=lambda pid, sig: signals.append((pid, sig)),
        )

        self.assertEqual(result.state, "stale_record_cleared")
        self.assertTrue(result.sharing_available)
        self.assertEqual(signals, [])
        self.assertEqual(routes.removals, [(DEFAULT_PROFILE, TEST_ROUTE_ID)])
        self.assertEqual(load_owner_record(layout).state, "absent")

    def test_pid_reuse_other_profile_uid_and_token_mismatches_are_untouched(self) -> None:
        layout, binary = self.make_layout()
        record = self.make_record(layout, binary, route_id=TEST_ROUTE_ID)
        other_binary = self.install_root / "unrelated-opentunnel"
        other_binary.write_bytes(b"unrelated process fixture")
        other_binary.chmod(0o700)
        cases = (
            ("unrelated_executable", {"exe_path": str(other_binary)}),
            ("different_profile", {"profile": "another-profile"}),
            ("different_uid", {"uid": os.getuid() + 1}),
            ("different_creation_token", {"creation_token": "reused-pid-token"}),
            ("identity_probe_unknown", None),
        )
        for name, override in cases:
            with self.subTest(case=name):
                owner_path = layout.state_home / OWNER_RECORD_FILENAME
                if owner_path.exists():
                    owner_path.unlink()
                self.assertTrue(write_owner_record(layout, record))
                routes = FakeRouteTable()
                routes.state = "owned"
                routes.route_id = TEST_ROUTE_ID
                identity = (
                    None
                    if override is None
                    else self.matching_identity(record, **override)
                )
                processes = FakeProcessTable(identity)
                signals: list[tuple[int, int]] = []
                before = owner_path.read_bytes()

                result = reconcile_orphans(
                    layout,
                    CompanionResolution("resolved", "resolved", binary),
                    process_table=processes,
                    route_table=routes,
                    signaller=lambda pid, sig: signals.append((pid, sig)),
                )

                self.assertEqual(result.state, "ambiguous")
                self.assertFalse(result.sharing_available)
                self.assertEqual(signals, [])
                self.assertEqual(routes.removals, [])
                self.assertEqual(routes.state, "owned")
                self.assertEqual(owner_path.read_bytes(), before)

    def test_ambiguous_route_prevents_process_signal_and_route_removal(self) -> None:
        layout, binary = self.make_layout()
        record = self.make_record(layout, binary)
        self.assertTrue(write_owner_record(layout, record))
        routes = FakeRouteTable()
        routes.state = "unknown"
        processes = FakeProcessTable(self.matching_identity(record))
        signals: list[tuple[int, int]] = []

        result = reconcile_orphans(
            layout,
            CompanionResolution("resolved", "resolved", binary),
            process_table=processes,
            route_table=routes,
            signaller=lambda pid, sig: signals.append((pid, sig)),
        )

        self.assertEqual(result.state, "ambiguous")
        self.assertFalse(result.sharing_available)
        self.assertEqual(signals, [])
        self.assertEqual(routes.removals, [])
        self.assertEqual(load_owner_record(layout).state, "valid")

    def test_invalid_foreign_symlink_and_wrong_mode_records_are_untouched(self) -> None:
        layout, binary = self.make_layout()
        record = self.make_record(layout, binary, route_id=TEST_ROUTE_ID)
        owner_path = layout.state_home / OWNER_RECORD_FILENAME
        external = self.scratch / "external-owner.json"
        cases = ("corrupt", "foreign", "duplicate_key", "symlink", "wrong_mode")
        for name in cases:
            with self.subTest(case=name):
                if owner_path.exists() or owner_path.is_symlink():
                    owner_path.unlink()
                if not external.exists():
                    external.write_text("external sentinel", encoding="ascii")
                    external.chmod(0o600)
                if name == "corrupt":
                    owner_path.write_bytes(b"{not-json")
                    owner_path.chmod(0o600)
                elif name == "foreign":
                    value = {
                        "schema": OWNER_RECORD_SCHEMA,
                        "profile": "another-profile",
                        "uid": os.getuid(),
                        "pid": record.pid,
                        "creation_token": record.creation_token,
                        "exe_path": record.exe_path,
                        "started_at": record.started_at,
                        "generation": record.generation,
                        "route_id": record.route_id,
                    }
                    owner_path.write_text(json.dumps(value), encoding="ascii")
                    owner_path.chmod(0o600)
                elif name == "duplicate_key":
                    owner_path.write_text(
                        '{"schema":"%s","schema":"%s"}'
                        % (OWNER_RECORD_SCHEMA, OWNER_RECORD_SCHEMA),
                        encoding="ascii",
                    )
                    owner_path.chmod(0o600)
                elif name == "symlink":
                    owner_path.symlink_to(external)
                else:
                    self.assertTrue(write_owner_record(layout, record))
                    owner_path.chmod(0o644)

                before_link = os.readlink(owner_path) if owner_path.is_symlink() else None
                before_bytes = owner_path.read_bytes() if not owner_path.is_symlink() else None
                before_external = external.read_bytes()
                routes = FakeRouteTable()
                routes.state = "owned"
                routes.route_id = TEST_ROUTE_ID
                processes = FakeProcessTable(self.matching_identity(record))
                signals: list[tuple[int, int]] = []

                result = reconcile_orphans(
                    layout,
                    CompanionResolution("resolved", "resolved", binary),
                    process_table=processes,
                    route_table=routes,
                    signaller=lambda pid, sig: signals.append((pid, sig)),
                )

                self.assertEqual(result.state, "ambiguous")
                self.assertFalse(result.sharing_available)
                self.assertEqual(signals, [])
                self.assertEqual(routes.removals, [])
                self.assertTrue(owner_path.is_symlink() if name == "symlink" else True)
                if name == "symlink":
                    self.assertEqual(os.readlink(owner_path), before_link)
                else:
                    self.assertEqual(owner_path.read_bytes(), before_bytes)
                self.assertEqual(external.read_bytes(), before_external)

    def test_unrelated_profile_directory_is_never_opened_or_enumerated(self) -> None:
        layout, binary = self.make_layout()
        record = self.make_record(layout, binary)
        self.assertTrue(write_owner_record(layout, record))
        unrelated = layout.state_root / "neq/opentunnel/unrelated-profile"
        unrelated.mkdir(mode=0o700)
        sentinel = unrelated / "private-sentinel"
        sentinel.write_text(TEST_SECRET, encoding="ascii")
        sentinel.chmod(0o600)
        watched = {os.path.abspath(str(unrelated)), os.path.abspath(str(sentinel))}
        accesses: list[tuple[str, str]] = []
        original_open = builtins.open
        original_os_open = os.open
        original_stat = os.stat
        original_lstat = os.lstat
        original_scandir = os.scandir

        def path_text(path: object) -> str:
            try:
                return os.path.abspath(os.fspath(path))  # type: ignore[arg-type]
            except TypeError:
                return "<non-path>"

        def tracked_open(file: object, *args: object, **kwargs: object) -> object:
            accesses.append(("open", path_text(file)))
            return original_open(file, *args, **kwargs)  # type: ignore[arg-type]

        def tracked_os_open(file: object, *args: object, **kwargs: object) -> int:
            accesses.append(("os.open", path_text(file)))
            return original_os_open(file, *args, **kwargs)  # type: ignore[arg-type]

        def tracked_stat(path: object, *args: object, **kwargs: object) -> os.stat_result:
            accesses.append(("stat", path_text(path)))
            return original_stat(path, *args, **kwargs)  # type: ignore[arg-type]

        def tracked_lstat(path: object, *args: object, **kwargs: object) -> os.stat_result:
            accesses.append(("lstat", path_text(path)))
            return original_lstat(path, *args, **kwargs)  # type: ignore[arg-type]

        def tracked_scandir(path: object = ".") -> object:
            accesses.append(("scandir", path_text(path)))
            return original_scandir(path)  # type: ignore[arg-type,return-value]

        with (
            mock.patch.object(builtins, "open", tracked_open),
            mock.patch.object(os, "open", tracked_os_open),
            mock.patch.object(os, "stat", tracked_stat),
            mock.patch.object(os, "lstat", tracked_lstat),
            mock.patch.object(os, "scandir", tracked_scandir),
        ):
            result = reconcile_orphans(
                layout,
                CompanionResolution("resolved", "resolved", binary),
                process_table=FakeProcessTable(ProcessObservation("gone")),
                route_table=FakeRouteTable(),
                signaller=lambda _pid, _sig: self.fail("unexpected signal"),
            )

        self.assertEqual(result.state, "stale_record_cleared")
        touched = [
            (operation, path)
            for operation, path in accesses
            if path in watched or path.startswith(os.path.abspath(str(unrelated)) + os.sep)
        ]
        self.assertEqual(touched, [])
        self.assertFalse(any(operation == "scandir" for operation, _path in accesses))
        self.assertEqual(sentinel.read_text(encoding="ascii"), TEST_SECRET)

    def test_start_queued_behind_ambiguous_reconciliation_remains_unavailable(self) -> None:
        fixture = CleanupControllerFixture(self)
        record = self.make_record(fixture.layout, fixture.binary)
        self.assertTrue(write_owner_record(fixture.layout, record))
        entered_process_probe = threading.Event()
        release_process_probe = threading.Event()

        def blocking_process_table(
            _pid: int,
        ) -> ProcessIdentity | ProcessObservation | None:
            entered_process_probe.set()
            if not release_process_probe.wait(timeout=2.0):
                return None
            return None

        cleanup = fixture.controller._deps.cleanup
        assert cleanup is not None
        fixture.controller._deps = replace(
            fixture.controller._deps,
            cleanup=replace(cleanup, process_table=blocking_process_table),
        )
        reconcile_results: list[object] = []
        start_results: list[object] = []
        reconcile_thread = threading.Thread(
            target=lambda: reconcile_results.append(
                fixture.controller.reconcile_cleanup()
            )
        )
        start_thread = threading.Thread(
            target=lambda: start_results.append(fixture.controller.start())
        )

        reconcile_thread.start()
        self.assertTrue(entered_process_probe.wait(timeout=2.0))
        start_thread.start()
        with fixture.controller._condition:
            self.assertTrue(
                fixture.controller._condition.wait_for(
                    lambda: fixture.controller._pending_start_ticket is not None,
                    timeout=2.0,
                )
            )
        release_process_probe.set()
        reconcile_thread.join(timeout=2.0)
        start_thread.join(timeout=2.0)

        self.assertFalse(reconcile_thread.is_alive())
        self.assertFalse(start_thread.is_alive())
        self.assertEqual(len(reconcile_results), 1)
        self.assertEqual(len(start_results), 1)
        self.assertEqual(fixture.controller.state, SharingState.FAILED)
        self.assertEqual(fixture.controller.reason, "cleanup_ambiguous")
        self.assertEqual(fixture.listener_start_calls, 0)
        self.assertEqual(fixture.handles, [])

    def test_expected_pid_without_owner_record_must_be_confirmed_gone(self) -> None:
        layout, binary = self.make_layout()
        routes = FakeRouteTable()
        identity = ProcessIdentity(
            pid=4242,
            creation_token="unowned-token",
            exe_path=str(binary),
            uid=os.getuid(),
            profile_marker=DEFAULT_PROFILE,
        )
        processes = FakeProcessTable(identity)

        result = reconcile_orphans(
            layout,
            CompanionResolution("resolved", "resolved", binary),
            process_table=processes,
            route_table=routes,
            expected_pid=4242,
        )

        self.assertEqual(result.state, "ambiguous")
        self.assertEqual(result.reason, "process_remains_unverified")
        self.assertFalse(result.sharing_available)
        self.assertEqual(routes.lookups, [])
        self.assertEqual(routes.removals, [])

    def test_reconcile_does_not_auto_start_and_ambiguity_requires_acknowledged_rerun(self) -> None:
        fixture = CleanupControllerFixture(self)
        record = self.make_record(fixture.layout, fixture.binary)
        self.assertTrue(write_owner_record(fixture.layout, record))
        fixture.processes.result = None

        ambiguous = fixture.controller.reconcile_cleanup()

        self.assertEqual(ambiguous.state, "ambiguous")
        self.assertEqual(fixture.controller.state, SharingState.FAILED)
        self.assertEqual(fixture.controller.reason, "cleanup_ambiguous")
        self.assertEqual(fixture.listener_start_calls, 0)
        self.assertEqual(fixture.handles, [])
        self.assertEqual(fixture.controller.start().reason, "cleanup_ambiguous")
        self.assertEqual(fixture.listener_start_calls, 0)
        no_ack = fixture.controller.clear_ambiguity(facilitator_acknowledged=False)
        self.assertEqual(no_ack.reason, "facilitator_acknowledgement_required")

        (fixture.layout.state_home / OWNER_RECORD_FILENAME).unlink()
        fixture.routes.state = "absent"
        fixture.processes.result = ProcessObservation("gone")
        cleared = fixture.controller.clear_ambiguity(facilitator_acknowledged=True)

        self.assertEqual(cleared.state, "clean")
        self.assertEqual(fixture.controller.state, SharingState.OFF)
        self.assertEqual(fixture.listener_start_calls, 0)
        self.assertEqual(fixture.handles, [])
        self.assertEqual(fixture.controller.start().state, SharingState.READY)
        self.assertEqual(fixture.listener_start_calls, 1)

    def test_diagnostics_are_bounded_and_redact_adversarial_route_errors(self) -> None:
        layout, binary = self.make_layout()
        record = self.make_record(layout, binary)
        self.assertTrue(write_owner_record(layout, record))

        class SecretRouteTable(FakeRouteTable):
            def lookup(self, _profile: str, _route_id: str | None) -> RouteObservation:
                raise RuntimeError(TEST_SECRET + " https://private-host.example")

        result = reconcile_orphans(
            layout,
            CompanionResolution("resolved", "resolved", binary),
            process_table=FakeProcessTable(self.matching_identity(record)),
            route_table=SecretRouteTable(),
            signaller=lambda _pid, _sig: self.fail("must not signal"),
        )
        diagnostic = result.diagnostic + repr(result)
        self.assertEqual(result.state, "ambiguous")
        self.assertLessEqual(len(result.reason), 40)
        self.assertLessEqual(len(result.diagnostic), 200)
        self.assertNotIn(TEST_SECRET, diagnostic)
        self.assertNotIn("private-host", diagnostic)
        self.assertNotIn("https://", diagnostic)

    def test_cleanup_source_has_no_shell_and_default_signal_has_verified_only_call_path(self) -> None:
        source_path = (
            Path(__file__).resolve().parents[1]
            / "web/extensions/opentunnel_sharing/cleanup.py"
        )
        source = source_path.read_text(encoding="ascii")
        tree = ast.parse(source)
        kill_functions: list[str] = []
        functions = {
            node.name: node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute) and node.func.attr in {"kill", "killpg"}:
                    parent = next(
                        (
                            name
                            for name, function in functions.items()
                            if node in ast.walk(function)
                        ),
                        "",
                    )
                    kill_functions.append(parent)
                for keyword in node.keywords:
                    if keyword.arg == "shell":
                        self.assertFalse(
                            isinstance(keyword.value, ast.Constant)
                            and keyword.value.value is True
                        )
        self.assertEqual(kill_functions, ["_default_signaller"])
        sender = functions["_send_verified_signal"]
        sender_text = ast.unparse(sender)
        self.assertIn("_identity_matches_record", sender_text)
        self.assertIn("_default_signaller", sender_text)
        self.assertNotIn("os.killpg", source)


if __name__ == "__main__":
    unittest.main()
