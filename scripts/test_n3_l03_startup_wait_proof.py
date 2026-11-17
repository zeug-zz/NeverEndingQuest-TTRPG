# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Tests for scripts/n3_l03_startup_wait_proof.py's import isolation and its
real-host worker result re-validation."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

import scripts.n3_l03_startup_wait_proof as wrapper

REPO_ROOT = Path(__file__).resolve().parents[1]


class N3L03StartupWaitProofImportIsolationTests(unittest.TestCase):
    def test_importing_module_does_not_import_repo_web_package(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import sys\n"
                    "import scripts.n3_l03_startup_wait_proof\n"
                    "web_modules = sorted(\n"
                    "    name for name in sys.modules\n"
                    "    if name == 'web' or name.startswith('web.')\n"
                    ")\n"
                    "print(len(web_modules))\n"
                ),
            ],
            cwd=str(REPO_ROOT),
            env={"PATH": "", "PYTHONPATH": str(REPO_ROOT), "PYTHONDONTWRITEBYTECODE": "1"},
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        self.assertEqual(completed.stdout.strip(), "0", completed.stderr)


class N3L03StartupWaitProofWorkerResultValidationTests(unittest.TestCase):
    def _valid_result(self) -> dict[str, object]:
        return {
            "verdict": "PASS",
            "reason": "real status_response.game_started was true and real local_runtime stayed false",
            "diagnostic_verdict": "PASS",
            "observation_failure": None,
            "status_response_game_started": True,
            "sharing_local_runtime_false": True,
            "sharing_local_runtime_reason": None,
            "no_network_attempts": True,
            "network_attempt_count": 0,
            "diagnostic_report_path": "tmp/router-rollout/v2-network/n3/l03-startup-wait-proof/x/startup_diagnostic.json",
        }

    def test_valid_result_accepted(self) -> None:
        validated = wrapper._validate_worker_result(self._valid_result())
        self.assertEqual(validated["verdict"], "PASS")
        self.assertIsNone(validated["observation_failure"])

    def test_non_dict_rejected(self) -> None:
        with self.assertRaises(ValueError):
            wrapper._validate_worker_result(["not", "a", "mapping"])

    def test_extra_key_rejected(self) -> None:
        payload = self._valid_result()
        payload["unexpected_extra_field"] = "nope"
        with self.assertRaises(ValueError):
            wrapper._validate_worker_result(payload)

    def test_missing_key_rejected(self) -> None:
        payload = self._valid_result()
        del payload["network_attempt_count"]
        with self.assertRaises(ValueError):
            wrapper._validate_worker_result(payload)

    def test_non_bool_field_rejected(self) -> None:
        payload = self._valid_result()
        payload["status_response_game_started"] = "true"
        with self.assertRaises(ValueError):
            wrapper._validate_worker_result(payload)

    def test_bool_rejected_for_network_attempt_count(self) -> None:
        payload = self._valid_result()
        payload["network_attempt_count"] = True
        with self.assertRaises(ValueError):
            wrapper._validate_worker_result(payload)

    def test_invalid_verdict_rejected(self) -> None:
        payload = self._valid_result()
        payload["verdict"] = "MAYBE"
        with self.assertRaises(ValueError):
            wrapper._validate_worker_result(payload)

    def test_oversized_reason_rejected(self) -> None:
        payload = self._valid_result()
        payload["reason"] = "x" * (wrapper.MAX_WORKER_RESULT_STRING_LENGTH + 1)
        with self.assertRaises(ValueError):
            wrapper._validate_worker_result(payload)

    def test_empty_required_string_rejected(self) -> None:
        payload = self._valid_result()
        payload["diagnostic_report_path"] = ""
        with self.assertRaises(ValueError):
            wrapper._validate_worker_result(payload)


class _FakeSharingStatusFlaskClient:
    def __init__(self, status_code: int, payload: object) -> None:
        self._status_code = status_code
        self._body = json.dumps(payload, ensure_ascii=True).encode("ascii") if payload is not None else b"{not json"

    def get(self, path: str, *, headers: dict[str, str] | None = None) -> "_FakeSharingStatusFlaskClient._Response":
        del path, headers
        return self._Response(self._status_code, self._body)

    class _Response:
        def __init__(self, status_code: int, body: bytes) -> None:
            self.status_code = status_code
            self._body = body

        def get_data(self) -> bytes:
            return self._body


class N3L03StartupWaitProofSharingStatusPathTests(unittest.TestCase):
    def test_production_shape_checks_local_runtime_read_correctly(self) -> None:
        client = _FakeSharingStatusFlaskClient(
            200, {"ok": True, "status": {"state": "off", "checks": {"local_runtime": False}}}
        )
        projection = wrapper._sharing_status_projection(client)
        self.assertIs(projection["local_runtime"], False)
        self.assertTrue(projection["checks_present"])
        self.assertTrue(projection["status_present"])
        self.assertTrue(projection["json_decoded"])
        self.assertEqual(projection["http_status"], 200)

    def test_old_top_level_shape_reports_fixed_non_bool_reason(self) -> None:
        client = _FakeSharingStatusFlaskClient(
            200, {"ok": True, "status": {"state": "off", "local_runtime": False}}
        )
        projection = wrapper._sharing_status_projection(client)
        self.assertEqual(projection["local_runtime"], "checks_missing")
        self.assertFalse(projection["checks_present"])
        self.assertTrue(projection["status_present"])

    def test_service_unavailable_reports_http_error_not_false(self) -> None:
        client = _FakeSharingStatusFlaskClient(503, {"ok": False, "reason": "service_unavailable"})
        projection = wrapper._sharing_status_projection(client)
        self.assertEqual(projection["local_runtime"], "http_error")
        self.assertEqual(projection["http_status"], 503)
        self.assertFalse(projection["status_present"])

    def test_malformed_json_reports_json_invalid(self) -> None:
        client = _FakeSharingStatusFlaskClient(200, None)
        projection = wrapper._sharing_status_projection(client)
        self.assertEqual(projection["local_runtime"], "json_invalid")
        self.assertFalse(projection["json_decoded"])

    def test_observe_real_host_surfaces_bounded_attribution_for_old_shape(self) -> None:
        class _FakeSocketClient:
            def emit(self, name: str, *args: object) -> None:
                del name, args

            def get_received(self) -> list[dict[str, object]]:
                return [{"name": "status_response", "args": [{"game_started": True}]}]

        class _FakeApp:
            def test_client(self) -> _FakeSharingStatusFlaskClient:
                return _FakeSharingStatusFlaskClient(
                    200, {"ok": True, "status": {"state": "off", "local_runtime": False}}
                )

        class _FakeWebModule:
            app = _FakeApp()

        observation = wrapper.observe_real_host(_FakeSocketClient(), _FakeWebModule())
        self.assertTrue(observation["status_response_game_started"])
        self.assertEqual(observation["sharing_status_local_runtime"], "checks_missing")
        self.assertFalse(observation["sharing_status_checks_present"])
        self.assertTrue(observation["sharing_status_status_present"])

    def test_compose_worker_result_attributes_checks_missing_reason(self) -> None:
        diagnostic_report = {
            "verdict": "PASS",
            "observation_failure": None,
            "network_attempt_count": 0,
            "observation": {
                "status_response_received": True,
                "status_response_game_started": True,
                "sharing_status_observed": True,
                "sharing_status_local_runtime": "checks_missing",
            },
        }
        result = wrapper._compose_worker_result(
            diagnostic_report, REPO_ROOT / "tmp" / "example" / "startup_diagnostic.json"
        )
        self.assertEqual(result["verdict"], "FAIL")
        self.assertFalse(result["sharing_local_runtime_false"])
        self.assertEqual(result["sharing_local_runtime_reason"], "checks_missing")
        self.assertIn("checks_missing", result["reason"])
        wrapper._validate_worker_result(result)


class N3L03StartupWaitProofWorkerResultFileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scratch = REPO_ROOT / "tmp" / "n3-l03-startup-wait-proof-result-file-test"
        self.scratch.mkdir(parents=True, exist_ok=True)
        self.addCleanup(self._cleanup_scratch)

    def _cleanup_scratch(self) -> None:
        for child in self.scratch.glob("*"):
            child.unlink()
        self.scratch.rmdir()

    def test_oversized_result_file_rejected(self) -> None:
        oversized_path = self.scratch / "oversized.json"
        oversized_path.write_text(
            "x" * (wrapper.MAX_PROOF_RESULT_BYTES + 1), encoding="ascii"
        )
        with self.assertRaises(ValueError):
            wrapper._read_worker_result(oversized_path)

    def test_malformed_json_result_file_rejected(self) -> None:
        malformed_path = self.scratch / "malformed.json"
        malformed_path.write_text("{not valid json", encoding="ascii")
        with self.assertRaises(json.JSONDecodeError):
            wrapper._read_worker_result(malformed_path)

    def test_valid_result_file_accepted(self) -> None:
        valid_path = self.scratch / "valid.json"
        payload = {
            "verdict": "BLOCKED",
            "reason": "underlying startup diagnostic did not PASS",
            "diagnostic_verdict": "BLOCKED",
            "observation_failure": None,
            "status_response_game_started": False,
            "sharing_local_runtime_false": False,
            "sharing_local_runtime_reason": "http_error",
            "no_network_attempts": True,
            "network_attempt_count": 0,
            "diagnostic_report_path": "tmp/example/startup_diagnostic.json",
        }
        valid_path.write_text(
            json.dumps(payload, ensure_ascii=True, sort_keys=True), encoding="ascii"
        )
        validated = wrapper._read_worker_result(valid_path)
        self.assertEqual(validated["verdict"], "BLOCKED")


if __name__ == "__main__":
    unittest.main()
