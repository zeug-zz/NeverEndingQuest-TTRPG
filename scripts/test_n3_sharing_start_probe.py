# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Offline tests for the provider-free N3 sharing-start probe (fakes only)."""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import socket
import stat
import tempfile
import threading
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

import scripts.n3_live_lifecycle_gate as gate
import scripts.n3_sharing_start_probe as probe

SCRATCH_ROOT = probe.REPO_ROOT / "tmp" / "n3-sharing-start-probe-tests"
FROZEN_DIGEST = "b754bb6fe3fdd206fb96d68ea972c741fc524f0477db71a523792459772b8ee4"
PLANTED_VALUE = "planted-value-0042-planted-value-0042"
PLANTED_HOSTNAME = "planted-evidence-host.opentunnel.xyz"
PLANTED_TUNNEL_ID = "planted-tunnel-9876"
PLANTED_URL = "https://planted-evidence-host.opentunnel.xyz"
PLANTED_ASSET_ID = "planted-asset-01.js"


def _process(pid: int, parent: int, command: str) -> gate.ProcessRecord:
    return gate.ProcessRecord(
        pid, parent, os.getuid(), datetime.now(), "process-value-%d" % pid, command
    )


class ProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        SCRATCH_ROOT.mkdir(parents=True, exist_ok=True)

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(dir=SCRATCH_ROOT)
        self.addCleanup(self._cleanup_temp)
        self.contexts: list[probe.FakeContext] = []
        self.addCleanup(self._close_contexts)

    def _cleanup_temp(self) -> None:
        self.temp.cleanup()

    def _close_contexts(self) -> None:
        for context in self.contexts:
            context.close()

    def build(self, **kwargs: object) -> probe.FakeContext:
        scratch = Path(tempfile.mkdtemp(dir=self.temp.name))
        context = probe.build_fake_dependencies(scratch, **kwargs)
        self.contexts.append(context)
        return context

    def evidence_dir(self, context: probe.FakeContext) -> Path:
        return context.deps.root / probe.PROBE_BASE / context.arguments.probe_id

    def evidence_text(self, context: probe.FakeContext) -> bytes:
        directory = self.evidence_dir(context)
        return b"".join(
            path.read_bytes() for path in sorted(directory.iterdir()) if path.is_file()
        )

    # -- preconditions -----------------------------------------------------

    def assert_refused(self, context: probe.FakeContext, reason: str) -> None:
        verdict, code = probe.run_probe(context.arguments, context.deps)
        self.assertEqual(("REFUSED", reason), (verdict["verdict"], verdict["reason"]))
        self.assertEqual(probe.EXIT_CODES["REFUSED"], code)
        self.assertEqual([], context.services)
        self.assertFalse(self.evidence_dir(context).exists())

    def test_manifest_digest_is_unchanged(self) -> None:
        self.assertEqual(FROZEN_DIGEST, gate.calculate_manifest_digest())
        self.assertTrue(gate.verify_frozen_manifest())

    def test_wrong_sha_is_refused(self) -> None:
        context = self.build(identity_sha="b" * 40)
        self.assert_refused(context, "sha_mismatch")

    def test_invalid_probe_id_is_refused(self) -> None:
        context = self.build(probe_id="n3-not-a-probe")
        self.assert_refused(context, "probe_id_invalid")

    def test_held_ports_are_refused(self) -> None:
        for port in (gate.HOST_PORT, gate.PLAYER_PORT):
            with self.subTest(port=port):
                context = self.build()
                context.ports.busy.add(port)
                self.assert_refused(context, "port_not_free")

    def test_existing_opentunnel_process_is_refused(self) -> None:
        context = self.build()
        context.processes.records = (
            _process(5000, 1, "/x/runtime/opentunnel/v0.6.2/opentunnel serve --profile a"),
        )
        self.assert_refused(context, "opentunnel_process_exists")

    def test_unrelated_process_with_similar_text_is_not_refused(self) -> None:
        context = self.build()
        context.processes.records = (
            _process(5001, 1, "python scripts/test_opentunnel_companion.py"),
        )
        verdict, _code = probe.run_probe(context.arguments, context.deps)
        self.assertEqual("PASS", verdict["verdict"])

    def test_missing_lock_is_refused_and_not_created(self) -> None:
        context = self.build(write_lock=False)
        self.assert_refused(context, "lock_missing")
        common = context.deps.root / ".git"
        self.assertFalse((common / "neq-coordination").exists())

    def test_mismatched_lock_booking_is_refused(self) -> None:
        context = self.build(lock_booking_id="some-other-booking")
        self.assert_refused(context, "lock_booking_mismatch")

    def test_load_gate_is_refused(self) -> None:
        for load in ((10.0, 1.0, 1.0), (1.0, 20.0, 1.0)):
            with self.subTest(load=load):
                context = self.build()
                context.deps.getloadavg = lambda value=load: value
                self.assert_refused(context, "load_gate_failed")

    def test_long_state_root_is_refused(self) -> None:
        context = self.build()
        long_base = context.state_base / ("l" * 80)
        long_base.mkdir(mode=0o700)
        context.deps.state_base_provider = lambda: long_base
        self.assert_refused(context, "state_root_too_long")

    # -- happy and failure paths ------------------------------------------

    def test_happy_path_reaches_ready_with_clean_census(self) -> None:
        context = self.build(service_kwargs={"issued_value": PLANTED_VALUE})
        verdict, code = probe.run_probe(context.arguments, context.deps)
        self.assertEqual(0, code)
        self.assertEqual("PASS", verdict["verdict"])
        self.assertIs(True, verdict["diagnosis_only"])
        self.assertIs(True, verdict["reached_sharing_ready"])
        self.assertEqual("ready", verdict["final_sharing_state"])
        self.assertEqual("ready", verdict["final_sharing_reason"])
        self.assertEqual("b", verdict["design"])
        self.assertEqual("injected_true", verdict["local_runtime"])
        self.assertEqual(0, verdict["provider_dispatch_attempts"])
        self.assertLessEqual(verdict["relay_creations_max"], 1)
        names = [item["name"] for item in verdict["steps"]]
        self.assertEqual(
            [
                "create_owned_state_root",
                "initialize_identity",
                "issue_access",
                "start_sharing",
                "poll_status",
                "copy_invitation",
                "public_shell_get",
                "public_asset_get",
                "stop_sharing",
                "identity_teardown",
            ],
            names,
        )
        census = verdict["census"]
        self.assertIs(True, census["clean"])
        self.assertEqual("verified_absent", census["identity"])
        self.assertIs(True, census["state_root_removed"])
        self.assertIs(True, census["booking_lock_unchanged"])
        directory = self.evidence_dir(context)
        self.assertEqual(
            {"verdict.json", "SHA256SUMS"}, {path.name for path in directory.iterdir()}
        )
        self.assertEqual(
            [
                "initialize_identity",
                "issue_access",
                "start",
                "copy_invitation",
                "stop",
                "shutdown",
            ],
            context.services[0].calls,
        )
        self.assertEqual(
            {
                "shell_status": 200,
                "asset_status": 200,
                "shell_references_asset": True,
                "origin_header_sent": False,
            },
            verdict["public_get_without_origin"],
        )
        shell_step = next(
            step for step in verdict["steps"] if step["name"] == "public_shell_get"
        )
        asset_step = next(
            step for step in verdict["steps"] if step["name"] == "public_asset_get"
        )
        self.assertEqual("html", shell_step["content_type_class"])
        self.assertGreater(shell_step["body_bytes"], 0)
        self.assertEqual(len(PLANTED_ASSET_ID), shell_step["asset_id_length"])
        self.assertIs(True, shell_step["shell_references_asset"])
        self.assertEqual("javascript", asset_step["content_type_class"])
        self.assertGreater(asset_step["body_bytes"], 0)
        self.assertEqual(len(PLANTED_ASSET_ID), asset_step["asset_id_length"])
        self.assertEqual(2, len(context.public_requester.calls))
        for index, request in enumerate(context.public_requester.calls):
            hostname, port, method, path, headers, body, timeout = request
            self.assertEqual("probe-relay.example.invalid", hostname)
            self.assertEqual(443, port)
            self.assertEqual("GET", method)
            self.assertEqual(
                "/" if index == 0 else "/static/player/" + PLANTED_ASSET_ID,
                path,
            )
            self.assertEqual({"Host": "probe-relay.example.invalid"}, headers)
            self.assertNotIn("Origin", headers)
            self.assertNotIn("Cookie", headers)
            self.assertIsNone(body)
            self.assertLessEqual(timeout, 15)
        self.assertFalse(
            (
                context.state_base
                / "neq-n3g"
                / gate._state_root_id8(context.arguments.state_run_id)
            ).exists()
        )

    def test_public_shell_403_records_safe_error_and_stops(self) -> None:
        context = self.build()
        context.public_requester.responses = [
            gate.PublicHttpResponse(
                403,
                (("Content-Type", "application/json; charset=utf-8"),),
                b'{"error":"request_rejected"}',
            )
        ]
        verdict, code = probe.run_probe(context.arguments, context.deps)
        self.assertEqual(("FAIL", 1), (verdict["verdict"], code))
        self.assertEqual("public_shell_get_failed", verdict["reason"])
        self.assertEqual(403, verdict["public_get_without_origin"]["shell_status"])
        self.assertEqual(
            "request_rejected",
            next(
                step["error_code"]
                for step in verdict["steps"]
                if step["name"] == "public_shell_get"
            ),
        )
        self.assertIn("stop", context.services[0].calls)
        self.assertIs(True, verdict["census"]["clean"])
        self.assertEqual(1, len(context.public_requester.calls))

    def test_public_asset_404_records_status_and_stops(self) -> None:
        context = self.build()
        context.public_requester.responses[1] = gate.PublicHttpResponse(
            404,
            (("Content-Type", "application/json"),),
            b'{"error":"not_found"}',
        )
        verdict, code = probe.run_probe(context.arguments, context.deps)
        self.assertEqual(("FAIL", 1), (verdict["verdict"], code))
        self.assertEqual("public_asset_get_failed", verdict["reason"])
        self.assertEqual(404, verdict["public_get_without_origin"]["asset_status"])
        asset_step = next(
            step for step in verdict["steps"] if step["name"] == "public_asset_get"
        )
        self.assertEqual("not_found", asset_step["error_code"])
        self.assertIn("stop", context.services[0].calls)
        self.assertIs(True, verdict["census"]["clean"])

    def test_public_shell_without_asset_reference_fails(self) -> None:
        context = self.build()
        context.public_requester.responses = [
            gate.PublicHttpResponse(
                200,
                (("Content-Type", "text/html; charset=utf-8"),),
                (
                    b'<!doctype html><html><body><input name="csrf_token" '
                    b'value="planted-value-0042-planted-value-0042"></body></html>'
                ),
            )
        ]
        verdict, code = probe.run_probe(context.arguments, context.deps)
        self.assertEqual(("FAIL", 1), (verdict["verdict"], code))
        self.assertEqual("public_shell_asset_missing", verdict["reason"])
        self.assertEqual(200, verdict["public_get_without_origin"]["shell_status"])
        self.assertIs(False, verdict["public_get_without_origin"]["shell_references_asset"])
        self.assertEqual(1, len(context.public_requester.calls))

    def test_public_shell_transport_error_fails_and_stops(self) -> None:
        context = self.build()
        context.public_requester.responses = [RuntimeError("offline fake")]
        verdict, code = probe.run_probe(context.arguments, context.deps)
        self.assertEqual(("FAIL", 1), (verdict["verdict"], code))
        self.assertEqual("public_shell_get_failed", verdict["reason"])
        self.assertIsNone(verdict["public_get_without_origin"]["shell_status"])
        shell_step = next(
            step for step in verdict["steps"] if step["name"] == "public_shell_get"
        )
        self.assertIsNone(shell_step["status"])
        self.assertIn("stop", context.services[0].calls)

    def test_non_https_invitation_and_redirect_are_refused(self) -> None:
        context = self.build(
            service_kwargs={"invitation": "http://probe-relay.example.invalid"}
        )
        verdict, code = probe.run_probe(context.arguments, context.deps)
        self.assertEqual(("FAIL", 1), (verdict["verdict"], code))
        self.assertEqual("public_shell_get_failed", verdict["reason"])
        self.assertEqual([], context.public_requester.calls)

        redirected = self.build()
        redirected.public_requester.responses = [
            gate.PublicHttpResponse(
                302,
                (("Location", "https://other.invalid/"),),
                b"",
            )
        ]
        verdict, code = probe.run_probe(redirected.arguments, redirected.deps)
        self.assertEqual(("FAIL", 1), (verdict["verdict"], code))
        self.assertEqual("public_shell_get_failed", verdict["reason"])
        self.assertEqual(302, verdict["public_get_without_origin"]["shell_status"])
        self.assertEqual(1, len(redirected.public_requester.calls))

    def test_failure_path_writes_private_diagnostics_before_teardown(self) -> None:
        diagnostics = {
            "summary": {"reason": "companion_failed", "serve_output_lines": 2},
            "detail": {
                "serve_output": [
                    "listening at %s" % PLANTED_URL,
                    "Hostname: %s" % PLANTED_HOSTNAME,
                    "Tunnel ID: %s" % PLANTED_TUNNEL_ID,
                    "issued value %s" % PLANTED_VALUE,
                ]
            },
        }
        context = self.build(
            service_kwargs={
                "fail_start": True,
                "issued_value": PLANTED_VALUE,
                "diagnostics": diagnostics,
            }
        )
        directory = self.evidence_dir(context)
        observed: dict[str, bool] = {}
        original_stop = probe.FakeSharingService.stop
        original_teardown = probe._identity_teardown

        def stop_probe(service: probe.FakeSharingService) -> object:
            observed["at_stop"] = (directory / gate.START_FAILURE_EVIDENCE_NAME).is_file()
            return original_stop(service)

        def teardown_probe(*args: object) -> str:
            observed["at_teardown"] = (
                directory / gate.START_FAILURE_EVIDENCE_NAME
            ).is_file()
            return original_teardown(*args)

        with mock.patch.object(probe.FakeSharingService, "stop", stop_probe), mock.patch.object(
            probe, "_identity_teardown", teardown_probe
        ):
            verdict, code = probe.run_probe(context.arguments, context.deps)
        self.assertEqual(("FAIL", 1), (verdict["verdict"], code))
        self.assertEqual("sharing_start_not_ready", verdict["reason"])
        self.assertEqual({"at_stop": True, "at_teardown": True}, observed)
        diag_path = directory / gate.START_FAILURE_EVIDENCE_NAME
        self.assertEqual(0o600, stat.S_IMODE(diag_path.lstat().st_mode))
        payload = json.loads(diag_path.read_text(encoding="ascii"))
        self.assertIs(True, payload["diagnosis_only"])
        self.assertIs(True, verdict["start_failure_diagnostics"]["written"])
        self.assertIs(True, verdict["census"]["clean"])

    def test_diagnostics_file_absent_when_start_succeeds(self) -> None:
        context = self.build()
        probe.run_probe(context.arguments, context.deps)
        self.assertFalse(
            (self.evidence_dir(context) / gate.START_FAILURE_EVIDENCE_NAME).exists()
        )

    def test_evidence_never_contains_planted_values(self) -> None:
        diagnostics = {
            "summary": {"reason": "companion_failed"},
            "detail": {
                "lines": [
                    PLANTED_URL,
                    "Hostname: %s" % PLANTED_HOSTNAME,
                    "Tunnel ID: %s" % PLANTED_TUNNEL_ID,
                    PLANTED_VALUE,
                ]
            },
        }
        for fail in (False, True):
            with self.subTest(fail=fail):
                context = self.build(
                    probe_id="n3p-scan-%s" % ("fail" if fail else "ok"),
                    service_kwargs={
                        "fail_start": fail,
                        "issued_value": PLANTED_VALUE,
                        "invitation": PLANTED_URL,
                        "diagnostics": diagnostics,
                    },
                )
                probe.run_probe(context.arguments, context.deps)
                text = self.evidence_text(context).decode("ascii")
                for planted in (
                    PLANTED_VALUE,
                    PLANTED_HOSTNAME,
                    PLANTED_TUNNEL_ID,
                    PLANTED_URL,
                    "planted-host.opentunnel.xyz",
                    "planted-tunnel-0001",
                    PLANTED_ASSET_ID,
                ):
                    self.assertNotIn(planted, text)

    def test_every_artifact_marks_diagnosis_only(self) -> None:
        context = self.build(
            service_kwargs={
                "fail_start": True,
                "diagnostics": {"summary": {}, "detail": {"a": 1}},
            }
        )
        probe.run_probe(context.arguments, context.deps)
        directory = self.evidence_dir(context)
        json_files = sorted(directory.glob("*.json"))
        self.assertEqual(2, len(json_files))
        for path in json_files:
            self.assertIs(True, json.loads(path.read_text(encoding="ascii"))["diagnosis_only"])
        sums = (directory / "SHA256SUMS").read_text(encoding="ascii")
        for path in json_files:
            self.assertIn(path.name, sums)

    def test_provider_dispatch_attempt_fails_the_run(self) -> None:
        def dispatch() -> None:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as attempt:
                try:
                    attempt.connect(("203.0.113.7", 443))
                except OSError:
                    pass

        context = self.build(service_kwargs={"provider_hook": dispatch})
        original = socket.socket.connect
        verdict, code = probe.run_probe(context.arguments, context.deps)
        self.assertIs(original, socket.socket.connect)
        self.assertEqual(("FAIL", 1), (verdict["verdict"], code))
        self.assertEqual("provider_dispatch_attempts_nonzero", verdict["reason"])
        self.assertEqual(1, verdict["provider_dispatch_attempts"])
        self.assertEqual(1, verdict["provider_attempt_ledger"]["egress_refusals"])

    def test_loopback_connect_is_not_a_provider_attempt(self) -> None:
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        self.addCleanup(listener.close)

        def loopback() -> None:
            client = socket.create_connection(listener.getsockname(), timeout=2)
            client.close()

        context = self.build(service_kwargs={"provider_hook": loopback})
        verdict, _code = probe.run_probe(context.arguments, context.deps)
        self.assertEqual(0, verdict["provider_dispatch_attempts"])
        self.assertEqual("PASS", verdict["verdict"])

    def test_more_than_one_identity_creation_fails(self) -> None:
        context = self.build(service_kwargs={"identity_up": 2})
        verdict, code = probe.run_probe(context.arguments, context.deps)
        self.assertEqual(("FAIL", 1), (verdict["verdict"], code))
        self.assertEqual("relay_tunnel_creation_bound_exceeded", verdict["reason"])

    def test_start_deadline_exceeded_is_a_failure_with_cleanup(self) -> None:
        release = threading.Event()
        context = self.build(
            service_kwargs={"provider_hook": lambda: release.wait(1.5)}
        )
        context.deps.ready_deadline_seconds = 0.2
        verdict, code = probe.run_probe(context.arguments, context.deps)
        release.set()
        self.assertEqual(("FAIL", 1), (verdict["verdict"], code))
        self.assertEqual("start_deadline_exceeded", verdict["reason"])
        self.assertIs(True, verdict["census"]["clean"])

    # -- census ------------------------------------------------------------

    def test_identity_not_removed_is_blocked_dirty(self) -> None:
        context = self.build(runner=probe._FakeCompanionRunner(delete_removes=False))
        verdict, code = probe.run_probe(context.arguments, context.deps)
        self.assertEqual(("BLOCKED_DIRTY", 2), (verdict["verdict"], code))
        self.assertEqual("not_verified", verdict["census"]["identity"])
        self.assertIs(False, verdict["census"]["clean"])

    def test_identity_observation_present_is_blocked_dirty(self) -> None:
        context = self.build(observer_state="present")
        verdict, code = probe.run_probe(context.arguments, context.deps)
        self.assertEqual(("BLOCKED_DIRTY", 2), (verdict["verdict"], code))

    def test_listener_left_behind_is_blocked_dirty(self) -> None:
        context = self.build()
        original_stop = probe.FakeSharingService.stop

        def leaky_stop(service: probe.FakeSharingService) -> object:
            context.ports.busy.add(gate.PLAYER_PORT)
            return original_stop(service)

        with mock.patch.object(probe.FakeSharingService, "stop", leaky_stop):
            verdict, code = probe.run_probe(context.arguments, context.deps)
        self.assertEqual(("BLOCKED_DIRTY", 2), (verdict["verdict"], code))
        self.assertIs(False, verdict["census"]["ports_free"])

    def test_residual_opentunnel_or_descendant_is_blocked_dirty(self) -> None:
        for command in (
            "/x/runtime/opentunnel/v0.6.2/opentunnel serve --profile a",
            "sleep 100",
        ):
            with self.subTest(command=command):
                context = self.build()
                original_stop = probe.FakeSharingService.stop
                parent = os.getpid() if command == "sleep 100" else 1

                def leaky_stop(service: probe.FakeSharingService, c=context, cmd=command, p=parent) -> object:
                    c.processes.records = (_process(7777, p, cmd),)
                    return original_stop(service)

                with mock.patch.object(probe.FakeSharingService, "stop", leaky_stop):
                    verdict, code = probe.run_probe(context.arguments, context.deps)
                self.assertEqual(("BLOCKED_DIRTY", 2), (verdict["verdict"], code))

    # -- boundaries --------------------------------------------------------

    def test_never_writes_gate_evidence_tree_and_never_touches_lock(self) -> None:
        context = self.build()
        lock_dir = context.deps.root / ".git" / "neq-coordination" / "live-window.lock"
        before = sorted(path.name for path in lock_dir.iterdir())
        holder_before = (lock_dir / "holder.json").read_bytes()
        probe.run_probe(context.arguments, context.deps)
        self.assertEqual(before, sorted(path.name for path in lock_dir.iterdir()))
        self.assertEqual(holder_before, (lock_dir / "holder.json").read_bytes())
        base = context.deps.root / gate.EVIDENCE_BASE
        self.assertEqual(["probe"], sorted(path.name for path in base.iterdir()))
        self.assertEqual(
            [context.arguments.probe_id],
            sorted(path.name for path in (base / "probe").iterdir()),
        )
        self.assertEqual(base / "probe", self.evidence_dir(context).parent)

    def test_existing_probe_evidence_is_refused(self) -> None:
        context = self.build()
        self.evidence_dir(context).mkdir(parents=True)
        verdict, _code = probe.run_probe(context.arguments, context.deps)
        self.assertEqual("probe_evidence_exists", verdict["reason"])

    # -- production composition seams -------------------------------------

    def test_production_service_injects_only_local_runtime_true(self) -> None:
        config = probe.ProbeConfig(
            sandbox_root=Path("/sandbox"),
            state_root=Path("/state"),
            player_build_root=Path("/sandbox/web/frontend/dist"),
        )
        captured: dict[str, object] = {}

        def fake_create(*args: object, **kwargs: object) -> object:
            captured["args"] = args
            captured["kwargs"] = kwargs
            return object()

        import web.extensions.opentunnel_sharing.service as service_module

        with mock.patch.object(
            service_module, "create_production_player_sharing_service", fake_create
        ):
            probe.build_production_service(config)
        args = captured["args"]
        kwargs = captured["kwargs"]
        self.assertIs(True, args[1]())
        self.assertEqual(
            {"install_root", "state_root", "player_build_root", "web_port"},
            set(kwargs),
        )
        self.assertEqual(gate.HOST_PORT, kwargs["web_port"])
        self.assertEqual(Path("/sandbox"), kwargs["install_root"])

    def test_status_parse_counter_counts_and_restores(self) -> None:
        import web.extensions.opentunnel_sharing.service as service_module

        original_parse = service_module._parse_companion_status
        original_run = service_module._ProductionComposition._run_route_status
        with probe._StatusParseCounter() as counter:
            self.assertIsNone(
                service_module._parse_companion_status("garbage", "neq-share")
            )
        self.assertIs(original_parse, service_module._parse_companion_status)
        self.assertIs(
            original_run, service_module._ProductionComposition._run_route_status
        )
        self.assertEqual(
            {"status_commands": 0, "parse_calls": 1, "parse_ok": 0, "parse_rejected": 1},
            counter.as_counts(),
        )

    # -- CLI ----------------------------------------------------------------

    def test_cli_run_prints_verdict_and_returns_exit_code(self) -> None:
        context = self.build()
        buffer = io.StringIO()
        with mock.patch.object(
            probe, "default_dependencies", lambda: context.deps
        ), contextlib.redirect_stdout(buffer):
            code = probe.main(
                [
                    "run",
                    "--probe-id",
                    context.arguments.probe_id,
                    "--sha",
                    context.arguments.sha,
                    "--booking-id",
                    context.arguments.booking_id,
                ]
            )
        self.assertEqual(0, code)
        self.assertEqual("PASS", json.loads(buffer.getvalue())["verdict"])

    def test_selftest_subcommand_passes_offline(self) -> None:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = probe.main(["selftest"])
        self.assertEqual(0, code)
        self.assertIn("[PASS] selftest happy", buffer.getvalue())

    def test_probe_module_does_not_import_provider_clients(self) -> None:
        import sys

        for name in sys.modules:
            self.assertNotIn(name.split(".", 1)[0], probe.PROVIDER_MODULE_ROOTS)


if __name__ == "__main__":
    unittest.main()
