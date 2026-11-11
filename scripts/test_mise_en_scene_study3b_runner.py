# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free Study 3b protocol, identity, and request-envelope tests."""

from __future__ import annotations

from contextlib import ExitStack
from copy import deepcopy
import builtins
import hashlib
import http.client
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.request

_SCRIPT_PATH = os.path.abspath(__file__)
sys.path.insert(0, os.path.dirname(_SCRIPT_PATH))

from scripts.mise_en_scene.llm_staging_study3b import newrequest, protocol
from scripts.mise_en_scene.llm_staging_study3b import inventory as inventory_module
from scripts.mise_en_scene.llm_staging_study3b import ledger as study3b_ledger
from scripts.mise_en_scene.llm_staging_study3b import runner as study3b_runner
from scripts.mise_en_scene.llm_staging_study3b.isolation import (
    PREP_ROOT_RELATIVE,
    build_prior_study_baseline,
)


REPO_ROOT = Path(os.path.dirname(os.path.dirname(_SCRIPT_PATH)))


class Study3bProtocolAndRequestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.calls = {
            "network": 0,
            "credential": 0,
            "provider_import": 0,
        }
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)

        def block_network(*_args: object, **_kwargs: object) -> None:
            self.calls["network"] += 1
            raise AssertionError("Study 3b protocol tests must not use network")

        original_import = builtins.__import__

        def guarded_import(name: str, *args: object, **kwargs: object):
            if name.split(".", 1)[0] in {"openai", "requests", "httpx", "anthropic"}:
                self.calls["provider_import"] += 1
                raise AssertionError("provider imports are forbidden")
            return original_import(name, *args, **kwargs)

        original_getenv = os.getenv

        def guarded_getenv(key: str, default: object = None):
            if key in {"OPENAI_API_KEY", "OPENROUTER_API_KEY"}:
                self.calls["credential"] += 1
                raise AssertionError("credential access is forbidden")
            return original_getenv(key, default)

        environ_type = type(os.environ)
        original_env_get = environ_type.get
        original_env_getitem = environ_type.__getitem__

        def guarded_env_get(env: object, key: object, default: object = None):
            if key in {"OPENAI_API_KEY", "OPENROUTER_API_KEY"}:
                self.calls["credential"] += 1
                raise AssertionError("credential access is forbidden")
            return original_env_get(env, key, default)

        def guarded_env_getitem(env: object, key: object):
            if key in {"OPENAI_API_KEY", "OPENROUTER_API_KEY"}:
                self.calls["credential"] += 1
                raise AssertionError("credential access is forbidden")
            return original_env_getitem(env, key)

        for target, attribute in (
            (socket, "create_connection"),
            (socket, "getaddrinfo"),
            (socket.socket, "connect"),
            (http.client.HTTPConnection, "request"),
            (http.client.HTTPSConnection, "request"),
            (urllib.request, "urlopen"),
        ):
            self.stack.enter_context(
                patch.object(target, attribute, side_effect=block_network)
            )
        self.stack.enter_context(
            patch.object(builtins, "__import__", guarded_import)
        )
        self.stack.enter_context(patch.object(os, "getenv", guarded_getenv))
        self.stack.enter_context(
            patch.object(environ_type, "get", guarded_env_get)
        )
        self.stack.enter_context(
            patch.object(environ_type, "__getitem__", guarded_env_getitem)
        )

    def tearDown(self) -> None:
        self.assertEqual(
            self.calls,
            {"network": 0, "credential": 0, "provider_import": 0},
        )

    def test_protocol_manifest_and_configuration_are_hash_bound(self) -> None:
        manifest = protocol.load_manifest()
        config = protocol.load_generation_config()
        protocol_text = protocol.load_protocol_text()

        self.assertEqual(manifest["study_id"], protocol.STUDY_ID)
        self.assertEqual(tuple(manifest["scene_order"]), protocol.SCENE_ORDER)
        self.assertEqual(manifest["attempt_cap"]["identity"], protocol.STUDY_ID)
        self.assertEqual(config["study_id"], protocol.STUDY_ID)
        self.assertEqual(config["model_id"], "openai/gpt-6-luna")
        self.assertEqual(config["max_tokens"], 16384)
        self.assertEqual(config["timeout_seconds"], 720)
        self.assertIs(config["dispatch_authorized"], False)
        self.assertIn("manifest hash is pinned", protocol_text)
        self.assertEqual(
            config["transport_constraints"],
            {
                "retries": 0,
                "reruns": 0,
                "fallback": False,
                "availability_get": False,
                "redirects": False,
                "continuation": False,
            },
        )

    def test_request_builder_uses_study3b_identity_and_envelope(self) -> None:
        config = protocol.load_generation_config()
        expected_payload = {
            "model": config["model_id"],
            "temperature": config["temperature"],
            "top_p": config["top_p"],
            "frequency_penalty": config["frequency_penalty"],
            "presence_penalty": config["presence_penalty"],
            "max_tokens": config["max_tokens"],
            "stream": config["stream"],
            "response_format": config["response_format"],
            "tools": config["tools"],
            "tool_choice": config["tool_choice"],
            "provider": config["provider_options"],
        }

        for scene_id in protocol.SCENE_ORDER:
            with self.subTest(scene_id=scene_id):
                request = newrequest.build_request(scene_id)
                metadata = newrequest.request_transport_metadata(scene_id)
                newrequest.audit_request_parity(scene_id, request)
                self.assertEqual(
                    {key: request[key] for key in expected_payload},
                    expected_payload,
                )
                self.assertEqual(metadata["study_id"], protocol.STUDY_ID)
                self.assertEqual(metadata["scene_id"], scene_id)
                self.assertEqual(metadata["model_id"], protocol.MODEL_ID)
                self.assertEqual(metadata["timeout_seconds"], 720)
                self.assertIs(metadata["dispatch_authorized"], False)
                self.assertEqual(metadata["scene_order"], protocol.SCENE_ORDER)
                self.assertEqual(
                    metadata["attempt_cap_identity"], protocol.STUDY_ID
                )
                self.assertEqual(metadata["attempt_cap"], 3)
                self.assertEqual(metadata["attempts_per_scene"], 1)
                self.assertEqual(
                    metadata["manifest_sha256"], protocol.MANIFEST_SHA256
                )
                self.assertEqual(
                    metadata["generation_config_sha256"],
                    protocol.GENERATION_CONFIG_SHA256,
                )

    def test_manifest_rejects_identity_order_and_attempt_drift(self) -> None:
        original = protocol.load_manifest()
        mutations = []

        changed_identity = deepcopy(original)
        changed_identity["study_id"] = "mise-en-scene-study3-20261110"
        mutations.append(changed_identity)

        changed_order = deepcopy(original)
        changed_order["scene_order"][0], changed_order["scene_order"][1] = (
            changed_order["scene_order"][1],
            changed_order["scene_order"][0],
        )
        mutations.append(changed_order)

        changed_cap_identity = deepcopy(original)
        changed_cap_identity["attempt_cap"]["identity"] = "other-study"
        mutations.append(changed_cap_identity)

        changed_cap_order = deepcopy(original)
        changed_cap_order["attempt_cap"]["scene_order"].reverse()
        mutations.append(changed_cap_order)

        for candidate in mutations:
            with self.subTest(candidate=candidate):
                with self.assertRaises(protocol.Study3bProtocolError):
                    protocol.validate_manifest(candidate)

    def test_protocol_manifest_and_config_byte_drift_fail_closed(self) -> None:
        original_reader = protocol._safe_project_read
        for path in (
            protocol.MANIFEST_RELATIVE,
            protocol.PROTOCOL_RELATIVE,
            protocol.GENERATION_CONFIG_RELATIVE,
        ):
            def drift_reader(relative_path: str, *, target: str = path) -> bytes:
                raw = original_reader(relative_path)
                return raw + b"\n" if relative_path == target else raw

            with self.subTest(path=path):
                with patch.object(
                    protocol,
                    "_safe_project_read",
                    side_effect=drift_reader,
                ):
                    with self.assertRaises(protocol.Study3bProtocolError):
                        protocol.load_generation_config()

    def test_generation_config_rejects_identity_order_and_envelope_drift(self) -> None:
        original = protocol.load_generation_config()
        mutations = []

        changed_identity = deepcopy(original)
        changed_identity["study_id"] = "mise-en-scene-study3-20261110"
        mutations.append(changed_identity)

        changed_attempt_identity = deepcopy(original)
        changed_attempt_identity["attempt_cap"]["identity"] = "other-study"
        mutations.append(changed_attempt_identity)

        changed_order = deepcopy(original)
        changed_order["attempt_cap"]["scene_order"].reverse()
        mutations.append(changed_order)

        for field, value in (
            ("model_id", "openai/other-model"),
            ("max_tokens", 16383),
            ("timeout_seconds", 719),
            ("temperature", 0.0),
        ):
            changed = deepcopy(original)
            changed[field] = value
            mutations.append(changed)

        for field, value in (
            ("retries", 1),
            ("fallback", True),
            ("availability_get", True),
        ):
            changed = deepcopy(original)
            changed["transport_constraints"][field] = value
            mutations.append(changed)

        for candidate in mutations:
            with self.subTest(candidate=candidate):
                with self.assertRaises(protocol.Study3bProtocolError):
                    protocol.validate_generation_config(candidate)

    def test_request_audit_rejects_identity_scene_and_envelope_drift(self) -> None:
        scene_id = protocol.SCENE_ORDER[0]
        request = newrequest.build_request(scene_id)
        with self.assertRaises(newrequest.RequestParityError):
            newrequest.build_request("into_the_deepvault:scene:unapproved")

        for field, value in (
            ("model", "openai/other-model"),
            ("max_tokens", 16383),
            ("temperature", 0.0),
            ("timeout_seconds", 719),
        ):
            with self.subTest(field=field):
                changed = deepcopy(request)
                changed[field] = value
                with self.assertRaises(newrequest.RequestParityError):
                    newrequest.audit_request_parity(scene_id, changed)

        with self.assertRaises(newrequest.RequestParityError):
            newrequest.audit_request_parity(
                "into_the_deepvault:scene:unapproved", request
            )

    def _new_ledger(self, prefix: str = "study3b-runner-test-"):
        temporary_directory = tempfile.TemporaryDirectory(
            prefix=prefix,
            dir=REPO_ROOT / PREP_ROOT_RELATIVE,
        )
        self.addCleanup(temporary_directory.cleanup)
        ledger = study3b_ledger.Study3bLedger._for_synthetic_test(
            Path(temporary_directory.name) / "synthetic-ledger"
        )
        ledger.initialize()
        return ledger

    def _request_section(self, request: dict[str, object], name: str) -> object:
        from scripts.mise_en_scene.llm_staging_study3b.study3_compat import (
            newrequest as study3_request,
        )

        user_message = request["messages"][1]["content"]  # type: ignore[index]
        begin, end, _rule_id = study3_request._SECTION_MARKERS[name]
        if user_message.count(begin) != 1 or user_message.count(end) != 1:
            raise AssertionError("request section markers are not unique")
        start = user_message.index(begin) + len(begin)
        finish = user_message.index(end)
        return json.loads(user_message[start:finish].strip("\n"))

    def _valid_delta(self, scene_id: str) -> dict[str, object]:
        request = newrequest.build_request(scene_id)
        inventory = inventory_module.load_scene_inventory(scene_id)
        input_refs = self._request_section(request, "input_refs")
        topology = self._request_section(request, "topology_binding")
        roles = topology["stage_role_candidates"]
        segments = (
            ("approach", "A bright glint crosses the stone."),
            ("threshold", "A narrow arch frames the room."),
            ("focal", "The central anchor is visible."),
        )
        arrivals = [
            {"id": scene_id + ":arrival:" + role, "role": role, "text": text}
            for role, text in segments
        ]
        claims = [
            {"segment_id": scene_id + ":arrival:" + role, "items": []}
            for role, _text in segments
        ]
        claims[0]["items"].append(
            {
                "id": scene_id + ":claim:synthetic-public-source",
                "fact_id": inventory.claim_reference_ids[0],
                "kind": "factual",
                "span": "bright glint",
                "choice": None,
                "success": None,
            }
        )
        module_id = topology["module_id"]
        return {
            "schema": "neq.llm_staging_study3_delta.v1",
            "input_refs": input_refs,
            "fixture_deltas": {
                "facts": [
                    {
                        "fact_id": module_id + ":fact:study3-authored:edge-a",
                        "subject_id": roles["approach"][0],
                        "predicate": "approach_to_threshold",
                        "object_id": roles["threshold"][0],
                        "value": True,
                    },
                    {
                        "fact_id": module_id + ":fact:study3-authored:edge-b",
                        "subject_id": roles["threshold"][0],
                        "predicate": "threshold_to_focal",
                        "object_id": roles["focal_anchor"][0],
                        "value": True,
                    },
                ]
            },
            "stage_role_bindings": {
                "approach": [roles["approach"][0]],
                "threshold": [roles["threshold"][0]],
                "focal_anchor": [roles["focal_anchor"][0]],
                "usable_space": [roles["usable_space"][0]],
            },
            "claims": claims,
            "arrival_prose": arrivals,
        }

    def _provider_response(
        self,
        scene_id: str,
        *,
        model: str = "openai/gpt-6-luna",
        provider: str = "synthetic-provider",
        generation_id: str | None = None,
        content: str | None = None,
        include_cost: bool = True,
    ) -> bytes:
        scene_index = protocol.SCENE_ORDER.index(scene_id) + 1
        if content is None:
            content = json.dumps(
                self._valid_delta(scene_id),
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        usage: dict[str, object] = {
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "reasoning_tokens": 3,
        }
        if include_cost:
            usage["cost"] = 0.001
        payload = {
            "id": generation_id or "synthetic-gen-" + str(scene_index),
            "model": model,
            "provider": provider,
            "usage": usage,
            "choices": [{"message": {"content": content}}],
        }
        return json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    def test_synthetic_runner_reuses_reserved_transport_once_with_720_timeout(self) -> None:
        baseline_before = build_prior_study_baseline(REPO_ROOT)["files"]
        ledger = self._new_ledger()
        fake = study3b_runner.Study3bSyntheticHTTP(
            ledger,
            [
                (200, self._provider_response(scene_id))
                for scene_id in protocol.SCENE_ORDER
            ],
        )

        result = study3b_runner.Study3bRunner().run_synthetic(ledger, fake)

        self.assertEqual(result.status, "COMPLETE")
        self.assertTrue(result.synthetic_only)
        self.assertEqual(len(result.attempts), len(protocol.SCENE_ORDER))
        self.assertEqual(len(fake.calls), len(protocol.SCENE_ORDER))
        self.assertEqual(fake.credential_reads, len(protocol.SCENE_ORDER))
        self.assertEqual(
            fake.reservation_visible_at_credential_read,
            [True] * len(protocol.SCENE_ORDER),
        )
        self.assertFalse(hasattr(fake, "get"))
        records = [
            json.loads(line)
            for line in ledger.path.read_text(encoding="ascii").splitlines()
        ]
        reservations = [row for row in records if row.get("event") == "reservation"]
        self.assertEqual(len(reservations), len(fake.calls))
        for index, (attempt, call) in enumerate(zip(result.attempts, fake.calls)):
            with self.subTest(scene_id=attempt.scene_id):
                self.assertEqual(attempt.scene_id, protocol.SCENE_ORDER[index])
                self.assertEqual(attempt.outcome, "ACCEPTED")
                self.assertEqual(attempt.actual_cost_status, "RECONCILED")
                self.assertEqual(attempt.actual_cost_usd, "0.001")
                self.assertEqual(
                    call["url"],
                    "https://openrouter.ai/api/v1/chat/completions",
                )
                self.assertEqual(call["timeout"], 720.0)
                self.assertIs(call["allow_redirects"], False)
                self.assertIs(call["synthetic_bearer_present"], True)
                self.assertEqual(
                    call["request_sha256"], attempt.transport_request_sha256
                )
                self.assertEqual(
                    reservations[index]["request_sha256"], attempt.request_sha256
                )
                self.assertTrue(
                    attempt.response_relative_path.startswith(
                        PREP_ROOT_RELATIVE + "/"
                    )
                )
        self.assertEqual(
            baseline_before,
            build_prior_study_baseline(REPO_ROOT)["files"],
        )
        self.assertEqual(
            self.calls,
            {"network": 0, "credential": 0, "provider_import": 0},
        )

    def test_failures_stop_without_retry_or_fallback(self) -> None:
        scene_id = protocol.SCENE_ORDER[0]
        valid = self._provider_response(scene_id)
        cases = (
            ("timeout", [None], "TRANSPORT_FAILED", "UNRESOLVED"),
            ("quota", [(429, valid)], "HTTP_STATUS_NOT_200", "UNRESOLVED"),
            ("invalid_http", [(600, valid)], "TRANSPORT_FAILED", "UNRESOLVED"),
            (
                "model_identity",
                [(200, self._provider_response(scene_id, model="openai/wrong"))],
                "PROVIDER_IDENTITY_MISMATCH",
                "UNRESOLVED",
            ),
            (
                "provider_identity",
                [(200, self._provider_response(scene_id, provider="unknown"))],
                "PROVIDER_IDENTITY_MISMATCH",
                "UNRESOLVED",
            ),
            (
                "missing_cost",
                [(200, self._provider_response(scene_id, include_cost=False))],
                "COST_RECEIPT_MISSING_OR_INCONSISTENT",
                "UNRESOLVED",
            ),
            (
                "protocol_defect",
                [(200, self._provider_response(scene_id, content="not-json"))],
                "STUDY3B_OUTPUT_PROTOCOL_DEFECT",
                "RECONCILED",
            ),
        )
        for label, responses, reason_code, cost_status in cases:
            with self.subTest(case=label):
                ledger = self._new_ledger("study3b-runner-failure-test-")
                fake = study3b_runner.Study3bSyntheticHTTP(ledger, responses)
                result = study3b_runner.Study3bRunner().run_synthetic(ledger, fake)
                self.assertEqual(result.status, "STOPPED")
                self.assertEqual(len(result.attempts), 1)
                self.assertEqual(len(fake.calls), 1)
                self.assertEqual(fake.credential_reads, 1)
                self.assertEqual(fake.reservation_visible_at_credential_read, [True])
                self.assertEqual(result.attempts[0].reason_code, reason_code)
                self.assertEqual(result.attempts[0].actual_cost_status, cost_status)
                self.assertEqual(result.remaining_scenes, protocol.SCENE_ORDER[1:])
                records = [
                    json.loads(line)
                    for line in ledger.path.read_text(encoding="ascii").splitlines()
                ]
                self.assertEqual(
                    sum(row.get("event") == "reservation" for row in records), 1
                )
                self.assertEqual(
                    sum(row.get("event") == "result" for row in records), 1
                )
        self.assertEqual(
            self.calls,
            {"network": 0, "credential": 0, "provider_import": 0},
        )

    def test_credential_echo_is_redacted_and_response_is_private(self) -> None:
        ledger = self._new_ledger("study3b-runner-echo-test-")
        scene_id = protocol.SCENE_ORDER[0]
        response = self._provider_response(
            scene_id,
            content=study3b_runner.SYNTHETIC_CREDENTIAL,
        )
        fake = study3b_runner.Study3bSyntheticHTTP(ledger, [(200, response)])

        result = study3b_runner.Study3bRunner().run_synthetic(ledger, fake)

        attempt = result.attempts[0]
        self.assertTrue(attempt.stop_study)
        self.assertEqual(attempt.actual_cost_status, "UNRESOLVED")
        self.assertEqual(attempt.reason_code, "PROVIDER_IDENTITY_MISMATCH")
        self.assertIsNotNone(attempt.response_relative_path)
        self.assertFalse(Path(attempt.response_relative_path).is_absolute())
        persisted = (REPO_ROOT / attempt.response_relative_path).read_bytes()
        self.assertNotIn(
            study3b_runner.SYNTHETIC_CREDENTIAL.encode("ascii"), persisted
        )
        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(fake.credential_reads, 1)
        self.assertEqual(
            self.calls,
            {"network": 0, "credential": 0, "provider_import": 0},
        )

    def test_restart_and_private_response_path_fail_closed(self) -> None:
        ledger = self._new_ledger("study3b-runner-restart-test-")
        scene_id = protocol.SCENE_ORDER[0]
        reservation = ledger.reserve(
            scene_id=scene_id,
            request_sha256=study3b_ledger.request_sha256_for_scene(scene_id),
        )
        restarted = study3b_ledger.Study3bLedger._for_synthetic_test(ledger.root)
        fake = study3b_runner.Study3bSyntheticHTTP(
            restarted,
            [(200, self._provider_response(scene_id))],
        )
        with self.assertRaises(study3b_runner.Study3bRunnerBlocked) as blocked:
            study3b_runner.Study3bRunner().run_synthetic(restarted, fake)
        self.assertEqual(blocked.exception.code, "SYNTHETIC_EXECUTION_SEAM_REQUIRED")
        self.assertEqual(fake.calls, [])
        self.assertEqual(fake.credential_reads, 0)

        forbidden_root = REPO_ROOT / (
            "tmp/router-rollout/mapping-pilot/mise-en-scene-offline/"
            "llm-staging-study3-prep/durable-ledger"
        )
        with self.assertRaises(study3b_runner.Study3bRunnerBlocked):
            study3b_runner._write_private_response(
                ledger,
                forbidden_root,
                reservation,
                b"SYNTHETIC_PRIVATE_RESPONSE",
            )
        self.assertFalse((forbidden_root / "01_fake.response.json").exists())
        self.assertEqual(
            self.calls,
            {"network": 0, "credential": 0, "provider_import": 0},
        )

    def test_live_runner_requires_explicit_pins_before_preflight_or_ledger(self) -> None:
        with patch.object(
            study3b_runner.preflight,
            "verify_live_readiness",
            side_effect=AssertionError("default live readiness is forbidden"),
        ), patch.object(
            study3b_runner,
            "Study3bLedger",
            side_effect=AssertionError("default real ledger is forbidden"),
        ), patch.object(
            study3b_runner,
            "_Study3bPolicyAdapter",
            side_effect=AssertionError("default live adapter construction is forbidden"),
        ):
            with self.assertRaises(study3b_runner.Study3bRunnerBlocked) as blocked:
                study3b_runner.Study3bRunner().run()
        self.assertEqual(
            blocked.exception.code,
            "STUDY3B_EXPLICIT_EXACT_HEAD_OPT_IN_REQUIRED",
        )
        self.assertEqual(
            self.calls,
            {"network": 0, "credential": 0, "provider_import": 0},
        )

    def test_failed_preflight_stops_before_real_ledger_credentials_or_dispatch(self) -> None:
        with patch.object(
            study3b_runner.preflight,
            "verify_live_readiness",
            side_effect=study3b_runner.preflight.ReadinessBlocked(
                "CI_REQUIRED_CHECK_SET_INCOMPLETE"
            ),
        ), patch.object(
            study3b_runner,
            "Study3bLedger",
            side_effect=AssertionError("real ledger initialization is forbidden"),
        ), patch.object(
            study3b_runner,
            "_Study3bPolicyAdapter",
            side_effect=AssertionError("transport construction is forbidden"),
        ):
            with self.assertRaises(study3b_runner.Study3bRunnerBlocked) as blocked:
                study3b_runner.Study3bRunner().run(
                    expected_head_sha="a" * 40,
                    ci_evidence_path=(
                        PREP_ROOT_RELATIVE + "/ci-check-runs-" + "a" * 40 + ".json"
                    ),
                    ci_evidence_sha256="b" * 64,
                    dispatch_ruling_id=(
                        study3b_runner.preflight.DISPATCH_RULING_ID
                    ),
                )
        self.assertEqual(blocked.exception.code, "CI_REQUIRED_CHECK_SET_INCOMPLETE")
        self.assertEqual(
            self.calls,
            {"network": 0, "credential": 0, "provider_import": 0},
        )

    def test_forged_ready_object_cannot_bypass_preflight_proof(self) -> None:
        forged = study3b_runner.preflight.ReadinessVerification(
            status="READY",
            reason_codes=(),
            study_id=protocol.STUDY_ID,
            expected_head_sha="a" * 40,
            current_head_sha="a" * 40,
            ci_check_count=11,
            preflight_gate_count=len(
                study3b_runner.preflight.REQUIRED_PREFLIGHT_COMMANDS
            ),
            external_provenance_verified=True,
            live_dispatch_permitted=True,
            ruling_id=study3b_runner.preflight.DISPATCH_RULING_ID,
            ruling_section_sha256=(
                study3b_runner.preflight.PINNED_RULING_SECTION_SHA256
            ),
            ci_evidence_path=PREP_ROOT_RELATIVE + "/ci.json",
            ci_evidence_sha256="b" * 64,
            evidence_relative_path=PREP_ROOT_RELATIVE + "/readiness/fake.json",
            evidence_sha256="c" * 64,
        )
        with patch.object(
            study3b_runner.preflight,
            "verify_live_readiness",
            return_value=forged,
        ), patch.object(
            study3b_runner,
            "Study3bLedger",
            side_effect=AssertionError("real ledger initialization is forbidden"),
        ):
            with self.assertRaises(study3b_runner.Study3bRunnerBlocked) as blocked:
                study3b_runner.Study3bRunner().run(
                    expected_head_sha="a" * 40,
                    ci_evidence_path=forged.ci_evidence_path,
                    ci_evidence_sha256=forged.ci_evidence_sha256,
                    dispatch_ruling_id=forged.ruling_id,
                )
        self.assertEqual(blocked.exception.code, "LIVE_PREFLIGHT_NOT_READY")
        self.assertEqual(
            self.calls,
            {"network": 0, "credential": 0, "provider_import": 0},
        )

    def test_changed_persisted_readiness_fails_before_ledger_initialization(self) -> None:
        verified = study3b_runner.preflight.ReadinessVerification(
            status="READY",
            reason_codes=(),
            study_id=protocol.STUDY_ID,
            expected_head_sha="a" * 40,
            current_head_sha="a" * 40,
            ci_check_count=11,
            preflight_gate_count=len(
                study3b_runner.preflight.REQUIRED_PREFLIGHT_COMMANDS
            ),
            external_provenance_verified=True,
            live_dispatch_permitted=True,
            ruling_id=study3b_runner.preflight.DISPATCH_RULING_ID,
            ruling_section_sha256=(
                study3b_runner.preflight.PINNED_RULING_SECTION_SHA256
            ),
            ci_evidence_path=PREP_ROOT_RELATIVE + "/ci.json",
            ci_evidence_sha256="b" * 64,
            evidence_relative_path=PREP_ROOT_RELATIVE + "/readiness/ready.json",
            evidence_sha256="c" * 64,
            _proof=study3b_runner.preflight._READY_PROOF,
        )
        with patch.object(
            study3b_runner.preflight,
            "verify_live_readiness",
            return_value=verified,
        ), patch.object(
            study3b_runner.preflight,
            "assert_dispatch_readiness_current",
            side_effect=study3b_runner.preflight.ReadinessBlocked(
                "READINESS_EVIDENCE_SHA256_MISMATCH"
            ),
        ), patch.object(
            study3b_runner,
            "Study3bLedger",
            side_effect=AssertionError("real ledger initialization is forbidden"),
        ), patch.object(
            study3b_runner,
            "_Study3bPolicyAdapter",
            side_effect=AssertionError("transport construction is forbidden"),
        ):
            with self.assertRaises(study3b_runner.Study3bRunnerBlocked) as blocked:
                study3b_runner.Study3bRunner().run(
                    expected_head_sha=verified.expected_head_sha,
                    ci_evidence_path=verified.ci_evidence_path,
                    ci_evidence_sha256=verified.ci_evidence_sha256,
                    dispatch_ruling_id=verified.ruling_id,
                )
        self.assertEqual(
            blocked.exception.code,
            "READINESS_EVIDENCE_SHA256_MISMATCH",
        )
        self.assertEqual(
            self.calls,
            {"network": 0, "credential": 0, "provider_import": 0},
        )


if __name__ == "__main__":
    unittest.main()
