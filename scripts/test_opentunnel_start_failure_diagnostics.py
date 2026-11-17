# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-free tests for bounded, redacted start-failure evidence."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import stat
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import scripts.n3_live_lifecycle_gate as gate
from scripts.test_opentunnel_supervisor import FakeFactory, FakeProcess
from scripts.test_opentunnel_supervisor import OpenTunnelSupervisorTests
from scripts.test_player_sharing_controls import (
    FakeSharingService,
    _build_host_app,
    _dispatch_player_asgi,
)
from scripts.test_player_sharing_lifecycle import LifecycleFixture
from web.extensions.opentunnel_sharing import failure_diagnostics as fd
from web.extensions.opentunnel_sharing.controller import (
    SharingController,
    SharingState,
)
from web.extensions.opentunnel_sharing.supervisor import OwnedCompanion
from web.extensions.player import create_app
from web.extensions.player.auth import PlayerSecurity

HEX_TOKEN = "deadbeef" * 6
LONG_TOKEN = "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789+/AbCd"
SESSION = "sessionCookieValue-XYZ"
PASSWORD = "hunter2-access-pass"
PLANTED = (
    "token=%s host=abcd1234.neq.opentunnel.xyz url=https://abcd.opentunnel.xyz/x "
    "tunnel_id=tun-777 password=%s b64=%s cookie=%s"
    % (HEX_TOKEN, PASSWORD, LONG_TOKEN, SESSION)
)
FORBIDDEN = (
    HEX_TOKEN,
    LONG_TOKEN,
    SESSION,
    PASSWORD,
    "tun-777",
    "abcd1234.neq",
    "https://abcd",
)


def assert_clean(test: unittest.TestCase, payload: object) -> None:
    text = json.dumps(payload)
    for item in FORBIDDEN:
        test.assertNotIn(item, text)


class RingAndRedactionTests(unittest.TestCase):
    def test_ring_keeps_last_200_lines_and_bounded_bytes(self) -> None:
        ring = fd.OutputTailRing()
        for index in range(1000):
            ring.feed(b"line-%04d " % index + b"x" * 400 + b"\n")
        lines, dropped = ring.snapshot()
        self.assertLessEqual(len(lines), fd.MAX_TAIL_LINES)
        self.assertTrue(lines[-1].startswith(b"line-0999"))
        self.assertGreater(dropped, 0)
        self.assertLessEqual(sum(len(item) + 1 for item in lines), fd.MAX_TAIL_BYTES)

    def test_stream_caps_lines_bytes_and_per_line_length(self) -> None:
        raw = [(str(i) + " " + "word " * 200).encode() for i in range(500)]
        stream = fd.build_stream(raw, [])
        self.assertLessEqual(stream["line_count"], 200)
        self.assertTrue(stream["truncated"])
        self.assertTrue(stream["lines"][-1].startswith("499 "))
        self.assertLessEqual(max(len(x) for x in stream["lines"]), fd.MAX_LINE_CHARS)
        self.assertLessEqual(
            sum(len(x) + 1 for x in stream["lines"]), fd.MAX_TAIL_BYTES
        )

    def test_planted_values_are_redacted_per_line(self) -> None:
        stream = fd.build_stream([PLANTED.encode()] * 3, [SESSION, PASSWORD])
        assert_clean(self, stream)
        self.assertEqual(stream["line_count"], 3)
        self.assertEqual(stream["reason"], "ok")

    def test_known_secret_scrub_works_without_regex_match(self) -> None:
        line = fd.sanitize_line(b"value is zq9 and S3cr3t!", ["S3cr3t!"])
        self.assertNotIn("S3cr3t", line)

    def test_redaction_failure_drops_stream(self) -> None:
        with mock.patch.object(fd, "redact", side_effect=RuntimeError("boom")):
            stream = fd.build_stream([b"abc"], [])
        self.assertEqual(stream["reason"], "redaction_failed")
        self.assertEqual(stream["lines"], [])


class DaemonLogTests(unittest.TestCase):
    def setUp(self) -> None:
        Path("tmp").mkdir(exist_ok=True)
        holder = tempfile.TemporaryDirectory(dir="tmp")
        self.addCleanup(holder.cleanup)
        self.state = Path(holder.name) / "state"
        (self.state / "opentunnel" / "neq").mkdir(parents=True)
        self.log = self.state / "opentunnel" / "neq" / "daemon.log"

    def test_reads_last_lines_only(self) -> None:
        self.log.write_text("\n".join("l%d %s" % (i, PLANTED) for i in range(900)))
        lines, reason = fd.read_daemon_log_tail(self.state, "neq")
        self.assertEqual(reason, "ok")
        stream = fd.build_stream(lines, [SESSION])
        self.assertEqual(stream["line_count"], 200)
        self.assertTrue(stream["lines"][-1].startswith("l899"))
        assert_clean(self, stream)

    def test_missing_symlink_oversized_not_owned_not_regular(self) -> None:
        self.assertEqual(fd.read_daemon_log_tail(self.state, "neq"), ([], "missing"))
        self.assertEqual(
            fd.read_daemon_log_tail(self.state / "nope", "neq")[1], "no_state_home"
        )
        target = self.state / "secret.txt"
        target.write_text("TOP-SECRET")
        os.symlink(target, self.log)
        self.assertEqual(fd.read_daemon_log_tail(self.state, "neq"), ([], "symlink"))
        self.log.unlink()
        self.log.write_text("x" * 100)
        with mock.patch.object(fd, "MAX_DAEMON_LOG_FILE_BYTES", 10):
            self.assertEqual(
                fd.read_daemon_log_tail(self.state, "neq"), ([], "oversized")
            )
        with mock.patch.object(fd.os, "getuid", return_value=os.getuid() + 1):
            self.assertEqual(
                fd.read_daemon_log_tail(self.state, "neq"), ([], "not_owned")
            )
        self.log.unlink()
        os.mkfifo(self.log)
        self.assertEqual(
            fd.read_daemon_log_tail(self.state, "neq")[1], "not_regular"
        )

    def test_symlinked_profile_directory_is_not_followed(self) -> None:
        outside = self.state / "outside"
        outside.mkdir()
        (outside / "daemon.log").write_text("LEAK")
        (self.state / "opentunnel" / "neq").rmdir()
        os.symlink(outside, self.state / "opentunnel" / "neq")
        lines, reason = fd.read_daemon_log_tail(self.state, "neq")
        self.assertEqual(lines, [])
        self.assertNotEqual(reason, "ok")


class OwnedCompanionEvidenceTests(OpenTunnelSupervisorTests):
    """Reuse the supervisor fixtures; only the tests below run new checks."""

    def _write_daemon_log(self) -> None:
        directory = self.layout.state_home / "opentunnel" / self.layout.profile
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "daemon.log").write_text(PLANTED + "\nlast daemon line\n")

    def _snapshot(self, owner: OwnedCompanion) -> dict:
        snapshot = owner.failure_snapshot([SESSION, PASSWORD])
        assert_clean(self, snapshot)
        return snapshot

    def test_startup_timeout_snapshot(self) -> None:
        self._write_daemon_log()
        process = FakeProcess(output=(PLANTED + "\nserve line\n").encode())
        owner, _factory, _process = self._owner(
            process=process, readiness=lambda: "pending"
        )
        self.assertEqual(owner.start(0.2), "failed")
        self.assertEqual(owner.reason_code, "startup_timeout")
        snap = self._snapshot(owner)
        companion = snap["companion"]
        self.assertEqual(companion["reason_code"], "startup_timeout")
        self.assertEqual(companion["deadline_seconds"], 0.2)
        self.assertGreaterEqual(companion["elapsed_seconds"], 0.2)
        self.assertTrue(companion["supervisor_signalled"])
        self.assertGreaterEqual(len(snap["poll_timeline"]["entries"]), 1)
        self.assertEqual(snap["poll_timeline"]["entries"][0]["readiness"], "pending")
        self.assertEqual(snap["daemon_log_tail"]["reason"], "ok")
        self.assertIn("last daemon line", snap["daemon_log_tail"]["lines"])
        owner._join_drain(1.0)
        snap = self._snapshot(owner)
        self.assertIn("serve line", snap["serve_output_tail"]["lines"])

    def test_early_exit_with_code_and_with_signal(self) -> None:
        owner, _f, _p = self._owner(process=FakeProcess(exit_code=3))
        self.assertEqual(owner.start(1.0), "failed")
        companion = self._snapshot(owner)["companion"]
        self.assertEqual(companion["reason_code"], "early_exit")
        self.assertEqual(companion["exit_code"], 3)
        self.assertIsNone(companion["signal"])
        self.assertFalse(companion["supervisor_signalled"])

        owner, _f, _p = self._owner(process=FakeProcess(exit_code=-11))
        owner.start(1.0)
        companion = self._snapshot(owner)["companion"]
        self.assertEqual(companion["signal"], 11)
        self.assertIsNone(companion["exit_code"])
        self.assertEqual(companion["exit_code_bucket"], "signal")

    def test_not_ready_snapshot_and_status_note(self) -> None:
        owner, _f, _p = self._owner(readiness=lambda: "not_ready")
        self.assertEqual(owner.start(1.0), "failed")
        owner.note_status_poll(
            returncode=0,
            timed_out=False,
            truncated=False,
            parsed_ok=False,
            output=PLANTED + "\nService: connecting\n",
        )
        snap = self._snapshot(owner)
        self.assertEqual(snap["companion"]["reason_code"], "not_ready")
        status = snap["route_status"]
        self.assertTrue(status["observed"])
        self.assertFalse(status["parsed_ok"])
        self.assertEqual(status["note"], "parse_failed")
        self.assertEqual(len(status["lines"]), 2)

    def test_timeline_cap(self) -> None:
        owner, _f, _p = self._owner()
        for _ in range(1000):
            owner._record_poll("pending", True, "none")
        timeline = owner.failure_snapshot()["poll_timeline"]
        self.assertEqual(len(timeline["entries"]), fd.MAX_TIMELINE_ENTRIES)
        self.assertEqual(timeline["total"], 1000)
        self.assertTrue(timeline["truncated"])

    def test_success_path_reads_nothing(self) -> None:
        owner, _f, _p = self._owner(readiness=lambda: "ready")
        with (
            mock.patch.object(fd, "read_daemon_log_tail") as read,
            mock.patch.object(
                OwnedCompanion, "failure_snapshot", side_effect=AssertionError
            ),
        ):
            self.assertEqual(owner.start(1.0), "running")
            read.assert_not_called()


class ControllerRetentionTests(unittest.TestCase):
    def _fixture(self, handle_factory, **overrides):
        fixture = LifecycleFixture()
        deps = dataclasses.replace(
            fixture.deps, start_companion=handle_factory, **overrides
        )
        fixture.controller = SharingController(deps)
        return fixture

    def _handle(self, fixture, *, result="failed", snapshot=None, raises=False):
        events = fixture.events
        from scripts.test_player_sharing_lifecycle import FakeCompanion

        class Handle(FakeCompanion):
            snapshot_calls = 0

            def failure_snapshot(self, secrets):
                Handle.snapshot_calls += 1
                events.append("snapshot")
                if raises:
                    raise RuntimeError("boom")
                return snapshot or {"companion": {"reason_code": "startup_timeout"}}

        handle = Handle(events, start_result=result)
        handle.cls = Handle
        return handle

    def test_failed_start_retains_before_cleanup_and_keeps_counters(self) -> None:
        holder = {}

        def factory(_generation):
            holder["h"] = self._handle(fixture)
            return holder["h"]

        fixture = self._fixture(factory, diagnostic_secrets=lambda: [SESSION])
        result = fixture.controller.start()
        self.assertEqual(result.state, SharingState.FAILED)
        self.assertEqual(result.reason, "companion_failed")
        self.assertEqual(result.counters.companion_launches, 1)
        self.assertEqual(result.counters.failed_starts, 1)
        diagnostics = fixture.controller.start_failure_diagnostics()
        self.assertEqual(diagnostics["summary"]["reason"], "companion_failed")
        self.assertEqual(diagnostics["detail"]["companion_launches"], 1)
        self.assertIn("snapshot", fixture.events)
        self.assertLess(
            fixture.events.index("snapshot"), fixture.events.index("listener_stop")
        )
        fixture.controller.stop()
        self.assertIsNone(fixture.controller.start_failure_diagnostics())

    def test_snapshot_exception_and_secret_provider_failure_never_raise(self) -> None:
        def boom() -> list[str]:
            raise RuntimeError("secrets")

        def factory(_generation):
            return self._handle(fixture, raises=True)

        fixture = self._fixture(factory, diagnostic_secrets=boom)
        result = fixture.controller.start()
        self.assertEqual(result.reason, "companion_failed")
        detail = fixture.controller.start_failure_diagnostics()["detail"]
        self.assertEqual(detail["known_secret_scrub"], "known_secrets_unavailable")
        self.assertEqual(detail["companion"]["reason"], "snapshot_failed")

    def test_no_companion_still_records_summary(self) -> None:
        fixture = self._fixture(lambda _g: None)
        fixture.controller.start()
        detail = fixture.controller.start_failure_diagnostics()["detail"]
        self.assertEqual(detail["companion"]["reason"], "no_companion")

    def test_success_path_retains_nothing(self) -> None:
        handle_holder = {}

        def factory(_generation):
            handle_holder["h"] = self._handle(fixture, result="running")
            return handle_holder["h"]

        fixture = self._fixture(factory)
        fixture.route_results.extend([])
        from web.extensions.opentunnel_sharing.controller import RouteStatus

        fixture.route_callback = lambda _h, g: RouteStatus(
            True, "https://sharing-route.example", g
        )
        result = fixture.controller.start()
        self.assertEqual(result.state, SharingState.READY)
        self.assertIsNone(fixture.controller.start_failure_diagnostics())
        self.assertEqual(handle_holder["h"].cls.snapshot_calls, 0)
        self.assertNotIn("snapshot", fixture.events)


class RoutePlayerSurfaceTests(unittest.TestCase):
    def _service(self, retained):
        service = FakeSharingService()
        service.start_failure_diagnostics = lambda: retained
        return service

    def test_status_field_present_only_after_failure(self) -> None:
        retained = {
            "summary": {"reason": "companion_failed"},
            "detail": {"serve_output_tail": {"lines": ["a"]}},
        }
        client = _build_host_app(lambda: self._service(retained)).test_client()
        headers = {"Host": "127.0.0.1:8357"}
        plain = client.get("/api/player-sharing/status", headers=headers).json
        field = plain["status"]["start_failure_diagnostics"]
        self.assertEqual(field, {"summary": retained["summary"]})
        full = client.get(
            "/api/player-sharing/status?include=start_failure_diagnostics",
            headers=headers,
        ).json
        self.assertEqual(full["status"]["start_failure_diagnostics"]["detail"],
                         retained["detail"])
        none_client = _build_host_app(lambda: self._service(None)).test_client()
        absent = none_client.get("/api/player-sharing/status", headers=headers).json
        self.assertNotIn("start_failure_diagnostics", absent["status"])
        legacy = _build_host_app(FakeSharingService).test_client()
        self.assertNotIn(
            "start_failure_diagnostics",
            legacy.get("/api/player-sharing/status", headers=headers).json["status"],
        )

    def test_player_surface_cannot_return_it(self) -> None:
        player_app = create_app(security=PlayerSecurity(lambda: None))
        status = asyncio.run(
            _dispatch_player_asgi(player_app, "/api/player-sharing/status")
        )
        self.assertEqual(status, 404)
        root = Path(__file__).resolve().parents[1] / "web" / "extensions" / "player"
        for path in root.rglob("*.py"):
            self.assertNotIn(
                "start_failure_diagnostics", path.read_text(encoding="utf-8"), path
            )


class GateEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        Path("tmp").mkdir(exist_ok=True)
        holder = tempfile.TemporaryDirectory(dir="tmp")
        self.addCleanup(holder.cleanup)
        self.capture = Path(holder.name)

    def _context(self, host_api):
        return types.SimpleNamespace(
            run_id="n3-test",
            capture_dir=self.capture,
            host_api=host_api,
            secrets=[SESSION],
            row_deadline_at=None,
            monotonic=lambda: 0.0,
            start_failure_diagnostics_observation=None,
            companion_post_recovery_observation=None,
        )

    def _api(self, status_payload, start_response):
        class Api:
            def __init__(self):
                self.calls = []

            def post(self, action, payload, timeout_seconds=None):
                self.calls.append(("POST", action))
                return start_response

            def get_status(self, *, timeout_seconds=None,
                           include_start_failure_diagnostics=False):
                self.calls.append(("GET", include_start_failure_diagnostics))
                if isinstance(status_payload, Exception):
                    raise status_payload
                return gate.HostApiResponse(200, {"ok": True, "status": status_payload})

        return Api()

    def test_manifest_digest_unchanged(self) -> None:
        self.assertEqual(
            gate.FROZEN_MANIFEST_SHA256,
            "b754bb6fe3fdd206fb96d68ea972c741fc524f0477db71a523792459772b8ee4",
        )
        self.assertEqual(gate.calculate_manifest_digest(), gate.FROZEN_MANIFEST_SHA256)

    def test_failed_start_writes_private_redacted_evidence(self) -> None:
        detail = {
            "daemon_log_tail": {"lines": [PLANTED, "more"], "line_count": 2},
            "serve_output_tail": {"lines": [PLANTED], "line_count": 1},
        }
        summary = {
            "reason": "companion_failed",
            "serve_output_lines": 1,
            "daemon_log_lines": 2,
            "daemon_log_reason": "ok",
        }
        api = self._api(
            {"state": "failed", "start_failure_diagnostics":
             {"summary": summary, "detail": detail}},
            gate.HostApiResponse(
                409, {"ok": False, "reason": "companion_failed"}
            ),
        )
        context = self._context(api)
        response, recovery, failure = gate._post_companion_starting_action(
            context, "start", {}
        )
        self.assertEqual(response.status, 409)
        self.assertIsNone(failure)
        self.assertEqual(
            response.payload, {"ok": False, "reason": "companion_failed"}
        )
        path = self.capture / gate.START_FAILURE_EVIDENCE_NAME
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        text = path.read_text()
        for item in FORBIDDEN:
            self.assertNotIn(item, text)
        written = json.loads(text)
        self.assertEqual(written["summary"]["reason"], "companion_failed")
        observation = context.start_failure_diagnostics_observation
        self.assertEqual(observation["status"], "written")
        self.assertEqual(observation["serve_output_lines"], 1)
        merged = gate._include_companion_post_observation(
            context, gate.RowExecutionResult("FAIL", "sharing_start_not_ready", {})
        )
        self.assertEqual(merged.reason, "sharing_start_not_ready")
        self.assertEqual(merged.verdict, "FAIL")
        self.assertEqual(
            merged.observed["start_failure_diagnostics"]["artifact"],
            gate.START_FAILURE_EVIDENCE_NAME,
        )
        self.assertTrue(gate._write_sha256sums(self.capture))
        self.assertIn(
            gate.START_FAILURE_EVIDENCE_NAME,
            (self.capture / "SHA256SUMS").read_text(),
        )

    def test_unavailable_host_status_is_recorded_not_raised(self) -> None:
        for payload, reason in (
            (gate.HostApiError("host_api_timeout"), "host_api_timeout"),
            ({"state": "failed"}, "not_retained"),
        ):
            api = self._api(
                payload,
                gate.HostApiResponse(409, {"ok": False, "reason": "companion_failed"}),
            )
            context = self._context(api)
            gate._post_companion_starting_action(context, "start", {})
            observation = context.start_failure_diagnostics_observation
            self.assertEqual(observation["status"], "diagnostics_unavailable")
            self.assertEqual(observation["reason"], reason)
        self.assertFalse((self.capture / gate.START_FAILURE_EVIDENCE_NAME).exists())

    def test_ready_start_never_fetches_diagnostics(self) -> None:
        api = self._api(
            {"state": "ready"},
            gate.HostApiResponse(
                200, {"ok": True, "reason": "ready", "status": {"state": "ready"}}
            ),
        )
        context = self._context(api)
        gate._post_companion_starting_action(context, "start", {})
        self.assertEqual(api.calls, [("POST", "start")])
        self.assertIsNone(context.start_failure_diagnostics_observation)


if __name__ == "__main__":
    unittest.main()
