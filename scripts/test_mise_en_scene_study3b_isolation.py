# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free isolation and synthetic-ledger boundary tests.

These tests never initialize the real Study 3b allocation, access credentials,
or dispatch; transport-result fixtures are synthetic.
"""

from __future__ import annotations

import builtins
from contextlib import ExitStack
from dataclasses import replace
from decimal import Decimal
import hashlib
import http.client
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import urllib.request
import unittest
from unittest.mock import patch

_SCRIPT_PATH = os.path.abspath(__file__)
sys.path.insert(0, os.path.dirname(os.path.dirname(_SCRIPT_PATH)))

from scripts.mise_en_scene.llm_staging_study3b.isolation import (
    BASELINE_PATH_RELATIVE,
    PREP_ROOT_RELATIVE,
    BaselineScopeError,
    PriorStudyMutationDenied,
    assert_study3b_write_target,
    build_prior_study_baseline,
    read_baseline_metadata,
)
from scripts.mise_en_scene.llm_staging_study3b import ledger as study3b_ledger
from scripts.mise_en_scene.llm_staging_study3b import preflight as study3b_preflight
from scripts.mise_en_scene.llm_staging.client import TransportResult


REPO_ROOT = Path(os.path.dirname(os.path.dirname(_SCRIPT_PATH)))
BASELINE_PATH = REPO_ROOT / BASELINE_PATH_RELATIVE
OFFLINE_ROOT = "tmp/router-rollout/mapping-pilot/mise-en-scene-offline"


def _attempt_synthetic_operation(
    repository_root: Path,
    target_path: Path,
    action: str,
    rename_source: Path | None = None,
) -> None:
    target = target_path
    assert_study3b_write_target(target, repository_root=repository_root, action=action)
    if action == "reset":
        target.write_bytes(b"SYNTHETIC_RESET_SENTINEL")
    elif action == "replay":
        target.write_bytes(b"SYNTHETIC_REPLAY_SENTINEL")
    elif action == "append":
        with target.open("ab") as stream:
            stream.write(b"SYNTHETIC_APPEND_SENTINEL")
    elif action == "delete":
        target.unlink()
    elif action == "rename":
        if rename_source is None:
            raise AssertionError("Synthetic rename source is required")
        rename_source.replace(target)
    elif action == "truncate":
        with target.open("wb") as stream:
            stream.truncate(0)
    else:
        target.write_bytes(b"SYNTHETIC_WRITE_SENTINEL")


class Study3bBaselineTests(unittest.TestCase):
    def test_baseline_contains_sorted_metadata_and_hashes_only(self) -> None:
        payload = read_baseline_metadata(BASELINE_PATH, repository_root=REPO_ROOT)
        self.assertEqual(payload["file_count"], len(payload["files"]))
        self.assertGreater(payload["file_count"], 0)
        self.assertEqual(
            [entry["path"] for entry in payload["files"]],
            sorted(entry["path"] for entry in payload["files"]),
        )

        file_keys = {"path", "size_bytes", "sha256", "scope", "opaque_bytes"}
        paths = set()
        for entry in payload["files"]:
            self.assertEqual(set(entry), file_keys)
            self.assertNotIn("content", entry)
            self.assertNotIn("bytes", entry)
            self.assertNotIn("text", entry)
            self.assertFalse(Path(entry["path"]).is_absolute())
            self.assertNotIn("..", Path(entry["path"]).parts)
            self.assertIs(type(entry["size_bytes"]), int)
            self.assertGreaterEqual(entry["size_bytes"], 0)
            self.assertRegex(entry["sha256"], r"^[0-9a-f]{64}$")
            self.assertIn(entry["scope"], {"source", "protocol", "evidence"})
            self.assertIs(type(entry["opaque_bytes"]), bool)
            self.assertNotIn(entry["path"], paths)
            paths.add(entry["path"])

        self.assertEqual(
            payload["opaque_bytes_count"],
            sum(1 for entry in payload["files"] if entry["opaque_bytes"]),
        )
        self.assertGreater(payload["opaque_bytes_count"], 0)
        by_path = {entry["path"]: entry for entry in payload["files"]}
        required_paths = {
            "scripts/mise_en_scene/llm_staging/materialize.py",
            "scripts/mise_en_scene/llm_staging_study2/hydration.py",
            "scripts/mise_en_scene/llm_staging_study3/newrequest.py",
            "openspec/changes/v2-mise-en-scene-authoring-projection-evaluation/llm-staging-protocol/protocol.md",
            "openspec/changes/v2-mise-en-scene-authoring-projection-evaluation/llm-staging-study2/protocol/protocol.md",
            "openspec/changes/v2-mise-en-scene-study3-contract-parity/protocol/protocol.md",
            OFFLINE_ROOT + "/llm-staging/runs/staging-20261109T072504Z/attempt-ledger.jsonl",
            OFFLINE_ROOT + "/llm-staging-study2/runs/study2-20261109T210130Z/attempt-ledger.jsonl",
            OFFLINE_ROOT + "/llm-staging-study3-prep/durable-ledger/study3-attempt-ledger.jsonl",
            OFFLINE_ROOT + "/llm-staging-study3-prep/study3-private-evidence/responses/01_into_the_deepvault__scene__ha003-i02.response.json",
            OFFLINE_ROOT + "/llm-staging-study2/clean-checkout-primary/scripts/__pycache__/test_mise_en_scene_llm_staging_study2.cpython-313.pyc",
        }
        self.assertTrue(required_paths.issubset(by_path))
        self.assertTrue(
            by_path[
                OFFLINE_ROOT
                + "/llm-staging-study3-prep/study3-private-evidence/responses/01_into_the_deepvault__scene__ha003-i02.response.json"
            ]["opaque_bytes"]
        )

        baseline_bytes = BASELINE_PATH.read_bytes()
        decoded_baseline = json.loads(baseline_bytes.decode("ascii"))
        self.assertEqual(decoded_baseline, payload)
        self.assertEqual(len(hashlib.sha256(baseline_bytes).hexdigest()), 64)


class Study3bWriteBoundaryTests(unittest.TestCase):
    def test_synthetic_mutations_are_rejected_for_every_prior_root_category(self) -> None:
        prep_root = REPO_ROOT / PREP_ROOT_RELATIVE
        protected_paths = (
            "scripts/mise_en_scene/llm_staging/legacy_source.py",
            "scripts/mise_en_scene/llm_staging_study2/legacy_hydration.py",
            "scripts/mise_en_scene/llm_staging_study3/legacy_request.py",
            "scripts/test_mise_en_scene_llm_staging.py",
            "openspec/changes/v2-mise-en-scene-authoring-projection-evaluation/llm-staging-protocol/protocol.md",
            "openspec/changes/v2-mise-en-scene-study3-contract-parity/protocol/protocol.md",
            "modules/Into_the_Deepvault/areas/HA003_BU.json",
            "modules/Into_the_Deepvault/areas/SD005_BU.json",
            "modules/Xhalruuns_Masquerade/areas/TSU001_BU.json",
            "plans/v2-mapping-pilot.md",
            OFFLINE_ROOT + "/llm-staging/runs/synthetic-run/attempt-ledger.jsonl",
            OFFLINE_ROOT + "/llm-staging-study2/runs/synthetic-run/attempt-ledger.jsonl",
            OFFLINE_ROOT + "/llm-staging-study3-prep/durable-ledger/study3-attempt-ledger.jsonl",
        )
        actions = (
            "write",
            "reset",
            "replay",
            "append",
            "delete",
            "rename",
            "truncate",
        )

        with tempfile.TemporaryDirectory(
            prefix="study3b-isolation-test-", dir=prep_root
        ) as temporary_directory:
            test_root = Path(temporary_directory)
            synthetic_root = test_root / "synthetic-repository"
            sentinels: dict[Path, bytes] = {}
            for index, relative_path in enumerate(protected_paths):
                target = synthetic_root / relative_path
                target.parent.mkdir(parents=True, exist_ok=True)
                sentinel = f"SYNTHETIC_PRIOR_SENTINEL_{index}".encode("ascii")
                target.write_bytes(sentinel)
                sentinels[target] = sentinel

            rename_source = (
                synthetic_root
                / OFFLINE_ROOT
                / "llm-staging-study3b-prep"
                / "synthetic-rename-source.json"
            )
            rename_source.parent.mkdir(parents=True, exist_ok=True)
            rename_sentinel = b"SYNTHETIC_RENAME_SOURCE_SENTINEL"
            rename_source.write_bytes(rename_sentinel)

            for target in sentinels:
                for action in actions:
                    with self.subTest(path=target.relative_to(synthetic_root), action=action):
                        with self.assertRaises(PriorStudyMutationDenied):
                            _attempt_synthetic_operation(
                                synthetic_root,
                                target,
                                action,
                                rename_source=rename_source,
                            )

            for target, sentinel in sentinels.items():
                self.assertEqual(target.read_bytes(), sentinel)
            self.assertEqual(rename_source.read_bytes(), rename_sentinel)

            traversal_target = (
                synthetic_root
                / OFFLINE_ROOT
                / "llm-staging-study3b-prep"
                / ".."
                / "llm-staging-study2"
                / "runs"
                / "synthetic-run"
                / "attempt-ledger.jsonl"
            )
            traversal_sentinel = sentinels[
                synthetic_root
                / OFFLINE_ROOT
                / "llm-staging-study2"
                / "runs"
                / "synthetic-run"
                / "attempt-ledger.jsonl"
            ]
            with self.assertRaises(PriorStudyMutationDenied):
                _attempt_synthetic_operation(
                    synthetic_root, traversal_target, "append"
                )
            self.assertEqual(
                traversal_target.read_bytes(), traversal_sentinel
            )

            outside_target = test_root / "outside-synthetic-repository.json"
            outside_sentinel = b"SYNTHETIC_OUTSIDE_REPOSITORY_SENTINEL"
            outside_target.write_bytes(outside_sentinel)
            with self.assertRaises(PriorStudyMutationDenied):
                _attempt_synthetic_operation(
                    synthetic_root, outside_target, "write"
                )
            self.assertEqual(outside_target.read_bytes(), outside_sentinel)

            alias_root = (
                synthetic_root
                / OFFLINE_ROOT
                / "llm-staging-study3b-prep"
                / "synthetic-aliases"
            )
            alias_root.mkdir(parents=True, exist_ok=True)
            file_alias = alias_root / "prior-ledger-alias.jsonl"
            prior_ledger = (
                synthetic_root
                / OFFLINE_ROOT
                / "llm-staging-study2"
                / "runs"
                / "synthetic-run"
                / "attempt-ledger.jsonl"
            )
            file_alias.symlink_to(prior_ledger)
            with self.assertRaises(PriorStudyMutationDenied):
                _attempt_synthetic_operation(synthetic_root, file_alias, "append")
            self.assertEqual(prior_ledger.read_bytes(), traversal_sentinel)

            directory_alias = alias_root / "prior-study3-alias"
            prior_ledger_root = (
                synthetic_root
                / OFFLINE_ROOT
                / "llm-staging-study3-prep"
                / "durable-ledger"
            )
            directory_alias.symlink_to(prior_ledger_root, target_is_directory=True)
            aliased_ledger = directory_alias / "study3-attempt-ledger.jsonl"
            prior_study3_ledger = prior_ledger_root / "study3-attempt-ledger.jsonl"
            with self.assertRaises(PriorStudyMutationDenied):
                _attempt_synthetic_operation(
                    synthetic_root, aliased_ledger, "truncate"
                )
            self.assertEqual(
                prior_study3_ledger.read_bytes(),
                sentinels[prior_study3_ledger],
            )

            study3b_target = (
                synthetic_root
                / OFFLINE_ROOT
                / "llm-staging-study3b-prep"
                / "synthetic-owned-output.json"
            )
            self.assertIsNone(
                assert_study3b_write_target(
                    study3b_target,
                    repository_root=synthetic_root,
                    action="write",
                )
            )

    def test_inventory_rejects_symlink_roots_and_files(self) -> None:
        prep_root = REPO_ROOT / PREP_ROOT_RELATIVE
        with tempfile.TemporaryDirectory(
            prefix="study3b-inventory-symlink-test-", dir=prep_root
        ) as temporary_directory:
            test_root = Path(temporary_directory)

            symlink_root_repo = test_root / "symlink-root-repository"
            symlink_root_repo.mkdir()
            (symlink_root_repo / "scripts").mkdir()
            synthetic_source_target = symlink_root_repo / "synthetic-source-target"
            synthetic_source_target.mkdir()
            (symlink_root_repo / "scripts" / "mise_en_scene").symlink_to(
                synthetic_source_target, target_is_directory=True
            )
            with self.assertRaises(BaselineScopeError):
                build_prior_study_baseline(symlink_root_repo)

            symlink_file_repo = test_root / "symlink-file-repository"
            source_root = symlink_file_repo / "scripts" / "mise_en_scene"
            source_root.mkdir(parents=True)
            source_file = source_root / "synthetic-source.py"
            source_file.write_bytes(b"SYNTHETIC_SOURCE_FILE_SENTINEL")
            (source_root / "synthetic-source-alias.py").symlink_to(source_file)
            with self.assertRaises(BaselineScopeError):
                build_prior_study_baseline(symlink_file_repo)


class Study3bLedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.calls = {"network": 0, "credential": 0, "provider_import": 0}
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)

        def block_network(*_args: object, **_kwargs: object) -> None:
            self.calls["network"] += 1
            raise AssertionError("Study 3b ledger tests must not use network")

        original_import = builtins.__import__

        def guarded_import(name: str, *args: object, **kwargs: object):
            if name.split(".", 1)[0] in {"openai", "requests", "httpx", "anthropic"}:
                self.calls["provider_import"] += 1
                raise AssertionError("provider imports are forbidden")
            return original_import(name, *args, **kwargs)

        original_getenv = os.getenv
        environ_type = type(os.environ)
        original_env_get = environ_type.get
        original_env_getitem = environ_type.__getitem__

        def guarded_getenv(key: str, default: object = None):
            if key in {"OPENAI_API_KEY", "OPENROUTER_API_KEY"}:
                self.calls["credential"] += 1
                raise AssertionError("credential access is forbidden")
            return original_getenv(key, default)

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
        self.stack.enter_context(patch.object(environ_type, "get", guarded_env_get))
        self.stack.enter_context(
            patch.object(environ_type, "__getitem__", guarded_env_getitem)
        )
        self.addCleanup(self._assert_no_external_access)

    def _assert_no_external_access(self) -> None:
        self.assertEqual(
            self.calls,
            {"network": 0, "credential": 0, "provider_import": 0},
        )

    def _new_ledger(self) -> tuple[tempfile.TemporaryDirectory[str], study3b_ledger.Study3bLedger]:
        prep_root = REPO_ROOT / PREP_ROOT_RELATIVE
        temporary_directory = tempfile.TemporaryDirectory(
            prefix="study3b-ledger-test-", dir=prep_root
        )
        self.addCleanup(temporary_directory.cleanup)
        ledger_root = Path(temporary_directory.name) / "synthetic-ledger"
        ledger = study3b_ledger.Study3bLedger._for_synthetic_test(ledger_root)
        ledger.initialize()
        return temporary_directory, ledger

    def _receipt(
        self,
        reservation: study3b_ledger.Study3bReservation,
        *,
        cost_usd: str = "0.001",
        generation_id: str | None = None,
    ) -> dict[str, object]:
        receipt_id = generation_id or "synthetic-gen-" + str(reservation.attempt_number)
        return {
            "receipt_id": receipt_id,
            "study_id": reservation.study_id,
            "manifest_sha256": reservation.manifest_sha256,
            "scene_id": reservation.scene_id,
            "attempt_number": reservation.attempt_number,
            "http_status": 200,
            "request_sha256": reservation.request_sha256,
            "response_sha256": format(reservation.attempt_number, "064x"),
            "returned_model_id": "openai/gpt-6-luna",
            "upstream_provider": "synthetic-provider",
            "generation_id": receipt_id,
            "cost_usd": cost_usd,
            "prompt_tokens": 12,
            "completion_tokens": 10,
            "reasoning_tokens": 2,
        }

    def _synthetic_transport_result(
        self,
        reservation: study3b_ledger.Study3bReservation,
        *,
        cost_usd: str = "0.001",
        generation_id: str | None = None,
    ) -> TransportResult:
        receipt = self._receipt(
            reservation,
            cost_usd=cost_usd,
            generation_id=generation_id,
        )
        cost = receipt["cost_usd"]
        if type(cost) is not str:
            raise AssertionError("synthetic cost must be text before wire encoding")
        response_body = (
            '{"id":"'
            + str(receipt["generation_id"])
            + '","model":"openai/gpt-6-luna","provider":"synthetic-provider",'
            + '"usage":{"completion_tokens":10,"cost":'
            + cost
            + ',"prompt_tokens":12,"reasoning_tokens":2}}'
        ).encode("ascii")
        transport_result = TransportResult(
            http_status=200,
            body=response_body,
            returned_model_id="openai/gpt-6-luna",
            upstream_provider="synthetic-provider",
            generation_id=str(receipt["generation_id"]),
            usage={
                "completion_tokens": 10,
                "prompt_tokens": 12,
                "reasoning_tokens": 2,
            },
        )
        return transport_result

    def _verified_receipt(
        self,
        reservation: study3b_ledger.Study3bReservation,
        *,
        cost_usd: str = "0.001",
        generation_id: str | None = None,
    ) -> object:
        return study3b_ledger._make_verified_cost_receipt(
            reservation,
            self._synthetic_transport_result(
                reservation,
                cost_usd=cost_usd,
                generation_id=generation_id,
            ),
        )

    def _reserve_scene(
        self, ledger: study3b_ledger.Study3bLedger, index: int
    ) -> study3b_ledger.Study3bReservation:
        scene_id = study3b_ledger.protocol.SCENE_ORDER[index]
        return ledger.reserve(
            scene_id=scene_id,
            request_sha256=study3b_ledger.request_sha256_for_scene(scene_id),
        )

    def _stopped_prefix_fixture(
        self,
        *,
        outcome: str = "CONTRACT_FAILURE",
        cost_usd: str = study3b_ledger.ORIGINAL_HA003_COST_USD,
    ) -> tuple[tempfile.TemporaryDirectory[str], study3b_ledger.Study3bLedger, bytes]:
        temporary_directory, ledger = self._new_ledger()
        reservation = self._reserve_scene(ledger, 0)
        ledger.complete(
            reservation,
            outcome=outcome,
            cost_receipt=self._verified_receipt(
                reservation, cost_usd=cost_usd
            ),
            validator_metadata=(
                {
                    "code": study3b_ledger.ORIGINAL_HA003_VALIDATOR_CODE,
                    "rule_id": study3b_ledger.ORIGINAL_HA003_VALIDATOR_RULE_ID,
                }
                if outcome == "CONTRACT_FAILURE"
                else None
            ),
        )
        records = [
            json.loads(line)
            for line in ledger.path.read_bytes().splitlines()
        ]
        if outcome == "CONTRACT_FAILURE":
            records[-1].pop("validator_metadata", None)
            records[-1]["stop_study"] = True
        previous_sha256: str | None = None
        encoded_lines: list[bytes] = []
        for record in records:
            record.pop("record_sha256", None)
            record["previous_sha256"] = previous_sha256
            record_sha256 = hashlib.sha256(
                study3b_ledger._canonical_bytes(record)
            ).hexdigest()
            record["record_sha256"] = record_sha256
            encoded_lines.append(study3b_ledger._canonical_bytes(record) + b"\n")
            previous_sha256 = record_sha256
        prefix = b"".join(encoded_lines)
        assert_study3b_write_target(
            ledger.path,
            repository_root=REPO_ROOT,
            action="write",
        )
        ledger.path.write_bytes(prefix)
        return temporary_directory, ledger, prefix

    def _readiness_fixture(self) -> study3b_preflight.ReadinessVerification:
        return study3b_preflight.ReadinessVerification(
            status="READY",
            reason_codes=(),
            study_id=study3b_ledger.protocol.STUDY_ID,
            expected_head_sha="a" * 40,
            current_head_sha="a" * 40,
            ci_check_count=len(study3b_preflight.REQUIRED_CI_CHECK_NAMES),
            preflight_gate_count=len(
                study3b_preflight.REQUIRED_PREFLIGHT_COMMANDS
            ),
            external_provenance_verified=True,
            live_dispatch_permitted=True,
            ruling_id=study3b_preflight.DISPATCH_RULING_ID,
            ruling_section_sha256=study3b_preflight.PINNED_RULING_SECTION_SHA256,
            ci_evidence_path=PREP_ROOT_RELATIVE + "/synthetic-ci.json",
            ci_evidence_sha256="b" * 64,
            evidence_relative_path=PREP_ROOT_RELATIVE + "/readiness/synthetic.json",
            evidence_sha256="c" * 64,
            _proof=study3b_preflight._CONTINUATION_READY_PROOF,
        )

    def _synthetic_continuation_authority(self) -> dict[str, str]:
        return {
            "ruling_id": study3b_preflight.CONTINUATION_RULING_ID,
            "section_sha256": study3b_preflight.PINNED_CONTINUATION_RULING_SECTION_SHA256,
        }

    def test_fixed_root_identity_and_no_caller_selected_runtime_root(self) -> None:
        ledger = study3b_ledger.Study3bLedger()
        self.assertEqual(
            ledger.root,
            REPO_ROOT / (
                "tmp/router-rollout/mapping-pilot/mise-en-scene-offline/"
                "llm-staging-study3b"
            ),
        )
        self.assertEqual(
            study3b_ledger.LOCK_IDENTITY, "llm-staging-study3b-20261111"
        )
        self.assertEqual(
            study3b_ledger.LOCK_NAME,
            ".llm-staging-study3b-20261111.lock",
        )
        with self.assertRaises(TypeError):
            study3b_ledger.Study3bLedger(root=REPO_ROOT / "tmp")
        _temporary, synthetic_ledger = self._new_ledger()
        scene_id = study3b_ledger.protocol.SCENE_ORDER[0]
        with self.assertRaises(TypeError):
            synthetic_ledger.reserve(
                scene_id=scene_id,
                request_sha256=study3b_ledger.request_sha256_for_scene(scene_id),
                budget_usd="0",
            )
        with self.assertRaises(TypeError):
            synthetic_ledger.reserve(
                scene_id=scene_id,
                request_sha256=study3b_ledger.request_sha256_for_scene(scene_id),
                conservative_cost_usd_estimate="0",
            )

        old_study3_root = (
            REPO_ROOT
            / "tmp/router-rollout/mapping-pilot/mise-en-scene-offline/"
            / "llm-staging-study3-prep/durable-ledger"
        )
        with self.assertRaises(study3b_ledger.Study3bLedgerError):
            study3b_ledger.Study3bLedger._for_synthetic_test(old_study3_root)
        with self.assertRaises(study3b_ledger.Study3bLedgerError):
            study3b_ledger.Study3bLedger._for_synthetic_test(
                str(old_study3_root.parent / "synthetic-alias" / ".." / "durable-ledger")
            )

    def test_continuation_pins_are_exact_and_metadata_allowlist_is_fixed(self) -> None:
        self.assertEqual(study3b_ledger.ORIGINAL_PREFIX_BYTES, 7495)
        self.assertEqual(
            study3b_ledger.ORIGINAL_PREFIX_SHA256,
            "a522e60692c4aa2c7f622998f2ac6cb165ef02211043abf949c319858fa7fd5e",
        )
        self.assertEqual(
            study3b_ledger.ORIGINAL_HA003_COST_USD, "0.004085175"
        )
        self.assertEqual(
            study3b_ledger.ORIGINAL_HA003_VALIDATOR_CODE,
            "GUARDED_MARKER_IN_PUBLIC_DELTA",
        )
        self.assertEqual(
            study3b_ledger.ORIGINAL_HA003_VALIDATOR_RULE_ID,
            "S3-GUARDED-CONTENT-MARKERS",
        )
        self.assertEqual(
            study3b_ledger.protocol.SCENE_ORDER[1],
            "into_the_deepvault:scene:sd005-i03",
        )
        self.assertEqual(
            study3b_preflight.CONTINUATION_RULING_ID,
            "neq-s-study3b-adjudication-20261111",
        )

    def test_valid_continuation_appends_once_without_changing_synthetic_prefix(self) -> None:
        _temporary, source_ledger, prefix = self._stopped_prefix_fixture()
        prefix_sha256 = hashlib.sha256(prefix).hexdigest()
        readiness = self._readiness_fixture()
        authorization = self._synthetic_continuation_authority()
        continuation = study3b_ledger.Study3bLedger._for_synthetic_test(
            source_ledger.root
        )
        with patch.object(
            study3b_ledger, "ORIGINAL_PREFIX_BYTES", len(prefix)
        ), patch.object(
            study3b_ledger, "ORIGINAL_PREFIX_SHA256", prefix_sha256
        ), patch.object(
            study3b_preflight,
            "assert_study3b_continuation_readiness_current",
            return_value=authorization,
        ) as authorize, patch.object(
            study3b_ledger.fcntl,
            "flock",
            wraps=study3b_ledger.fcntl.flock,
        ) as flock:
            continuation.continue_from_stopped(readiness=readiness)
            authorize.assert_called_once_with(readiness)
            appended = source_ledger.path.read_bytes()
            self.assertEqual(appended[: len(prefix)], prefix)
            event = json.loads(appended[len(prefix) :].decode("ascii"))
            self.assertEqual(event["event"], "continuation_transition")
            self.assertEqual(event["original_prefix_bytes"], len(prefix))
            self.assertEqual(event["original_prefix_sha256"], prefix_sha256)
            self.assertEqual(
                event["next_scene_id"], "into_the_deepvault:scene:sd005-i03"
            )
            self.assertEqual(
                event["remaining_scene_order"],
                list(study3b_ledger.protocol.SCENE_ORDER[1:]),
            )
            self.assertEqual(
                event["ha003_adjudication_supplement"],
                {
                    "code": "GUARDED_MARKER_IN_PUBLIC_DELTA",
                    "rule_id": "S3-GUARDED-CONTENT-MARKERS",
                },
            )
            self.assertEqual(
                set(event["ha003_adjudication_supplement"]),
                {"code", "rule_id"},
            )
            self.assertEqual(event["ruling_id"], authorization["ruling_id"])
            self.assertEqual(
                event["ruling_section_sha256"], authorization["section_sha256"]
            )

            with self.assertRaisesRegex(
                study3b_ledger.Study3bLedgerError,
                "LEDGER_CONTINUATION_ALREADY_USED",
            ):
                continuation.continue_from_stopped(readiness=readiness)
            with self.assertRaisesRegex(
                study3b_ledger.Study3bLedgerError,
                "LEDGER_ALREADY_INITIALIZED",
            ):
                continuation.initialize()

            restarted = study3b_ledger.Study3bLedger._for_synthetic_test(
                source_ledger.root
            )
            with self.assertRaisesRegex(
                study3b_ledger.Study3bLedgerError,
                "LEDGER_ALREADY_INITIALIZED",
            ):
                restarted.initialize()
            replay = study3b_ledger.Study3bLedger._for_synthetic_test(
                source_ledger.root
            )
            with self.assertRaisesRegex(
                study3b_ledger.Study3bLedgerError,
                "LEDGER_ORIGINAL_PREFIX_MISMATCH",
            ):
                replay.continue_from_stopped(readiness=readiness)

            next_scene = study3b_ledger.protocol.SCENE_ORDER[1]
            reservation = continuation.reserve(
                scene_id=next_scene,
                request_sha256=study3b_ledger.request_sha256_for_scene(next_scene),
            )
            self.assertEqual(reservation.attempt_number, 2)
            self.assertEqual(reservation.scene_id, next_scene)
            self.assertEqual(
                reservation.pre_dispatch_estimated_total_usd,
                "0.025685875",
            )
            self.assertTrue(source_ledger.path.read_bytes().startswith(prefix))
            self.assertTrue(
                any(
                    len(args) >= 2 and args[1] == study3b_ledger.fcntl.LOCK_EX
                    for args, _kwargs in flock.call_args_list
                )
            )

    def test_continuation_rejects_unverified_authority_and_prefix_mismatch(self) -> None:
        _temporary, source_ledger, prefix = self._stopped_prefix_fixture()
        original = source_ledger.path.read_bytes()
        continuation = study3b_ledger.Study3bLedger._for_synthetic_test(
            source_ledger.root
        )
        with patch.object(
            study3b_preflight,
            "assert_study3b_continuation_readiness_current",
            side_effect=AssertionError("invalid readiness reached authority check"),
        ) as authorize:
            for invalid_readiness in (
                True,
                replace(
                    self._readiness_fixture(),
                    _proof=study3b_preflight._READY_PROOF,
                ),
            ):
                with self.subTest(readiness_type=type(invalid_readiness).__name__):
                    with self.assertRaisesRegex(
                        study3b_ledger.Study3bLedgerError,
                        "LIVE_CONTINUATION_READINESS_PROOF_REQUIRED",
                    ):
                        continuation.continue_from_stopped(
                            readiness=invalid_readiness
                        )
            authorize.assert_not_called()

        readiness = self._readiness_fixture()
        expected_authority = self._synthetic_continuation_authority()
        invalid_authorities = (
            {
                "ruling_id": "neq-s-study3-adjudication-20261111",
                "section_sha256": expected_authority["section_sha256"],
            },
            {
                "ruling_id": expected_authority["ruling_id"],
                "section_sha256": "0" * 64,
            },
            {**expected_authority, "unexpected": "value"},
        )
        for invalid_authority in invalid_authorities:
            with self.subTest(authority=invalid_authority):
                with patch.object(
                    study3b_preflight,
                    "assert_study3b_continuation_readiness_current",
                    return_value=invalid_authority,
                ):
                    with self.assertRaisesRegex(
                        study3b_ledger.Study3bLedgerError,
                        "STUDY3B_CONTINUATION_RULING_INVALID",
                    ):
                        continuation.continue_from_stopped(readiness=readiness)
                self.assertEqual(source_ledger.path.read_bytes(), original)

        with patch.object(
            study3b_preflight,
            "assert_study3b_continuation_readiness_current",
            return_value=self._synthetic_continuation_authority(),
        ):
            with self.assertRaisesRegex(
                study3b_ledger.Study3bLedgerError,
                "LEDGER_ORIGINAL_PREFIX_MISMATCH",
            ):
                continuation.continue_from_stopped(readiness=readiness)
        self.assertEqual(source_ledger.path.read_bytes(), original)

    def test_continuation_rejects_nonstopped_or_wrong_cost_prior_result(self) -> None:
        readiness = self._readiness_fixture()
        authority = self._synthetic_continuation_authority()
        for outcome, cost_usd in (
            ("ACCEPTED", study3b_ledger.ORIGINAL_HA003_COST_USD),
            ("CONTRACT_FAILURE", "0.004085176"),
        ):
            with self.subTest(outcome=outcome, cost_usd=cost_usd):
                _temporary, source_ledger, prefix = self._stopped_prefix_fixture(
                    outcome=outcome, cost_usd=cost_usd
                )
                before = source_ledger.path.read_bytes()
                continuation = study3b_ledger.Study3bLedger._for_synthetic_test(
                    source_ledger.root
                )
                with patch.object(
                    study3b_ledger, "ORIGINAL_PREFIX_BYTES", len(prefix)
                ), patch.object(
                    study3b_ledger,
                    "ORIGINAL_PREFIX_SHA256",
                    hashlib.sha256(prefix).hexdigest(),
                ), patch.object(
                    study3b_preflight,
                    "assert_study3b_continuation_readiness_current",
                    return_value=authority,
                ):
                    with self.assertRaises(study3b_ledger.Study3bLedgerError):
                        continuation.continue_from_stopped(readiness=readiness)
                self.assertEqual(source_ledger.path.read_bytes(), before)

    def test_continuation_rejects_exact_pin_mismatch_without_mutation(self) -> None:
        _temporary, source_ledger, prefix = self._stopped_prefix_fixture()
        before = source_ledger.path.read_bytes()
        continuation = study3b_ledger.Study3bLedger._for_synthetic_test(
            source_ledger.root
        )
        readiness = self._readiness_fixture()
        with patch.object(
            study3b_preflight,
            "assert_study3b_continuation_readiness_current",
            return_value=self._synthetic_continuation_authority(),
        ):
            with self.assertRaisesRegex(
                study3b_ledger.Study3bLedgerError,
                "LEDGER_ORIGINAL_PREFIX_MISMATCH",
            ):
                continuation.continue_from_stopped(readiness=readiness)
        self.assertEqual(len(prefix), len(before))
        self.assertEqual(hashlib.sha256(prefix).hexdigest(), hashlib.sha256(before).hexdigest())
        self.assertEqual(source_ledger.path.read_bytes(), before)

    def test_competing_continuations_allow_exactly_one_atomic_transition(self) -> None:
        _temporary, source_ledger, prefix = self._stopped_prefix_fixture()
        readiness = self._readiness_fixture()
        contenders = [
            study3b_ledger.Study3bLedger._for_synthetic_test(source_ledger.root)
            for _ in range(2)
        ]
        self.assertEqual(contenders[0].root, source_ledger.root)
        self.assertEqual(contenders[1].root, source_ledger.root)
        self.assertEqual(contenders[0].path, source_ledger.path)
        self.assertEqual(contenders[1].path, source_ledger.path)
        barrier = threading.Barrier(2)
        outcomes: list[tuple[str, str | None]] = []
        outcome_lock = threading.Lock()

        def compete(ledger: study3b_ledger.Study3bLedger) -> None:
            barrier.wait()
            try:
                ledger.continue_from_stopped(readiness=readiness)
            except study3b_ledger.Study3bLedgerError as error:
                result = ("rejected", error.code)
            else:
                result = ("accepted", None)
            with outcome_lock:
                outcomes.append(result)

        with patch.object(
            study3b_ledger, "ORIGINAL_PREFIX_BYTES", len(prefix)
        ), patch.object(
            study3b_ledger,
            "ORIGINAL_PREFIX_SHA256",
            hashlib.sha256(prefix).hexdigest(),
        ), patch.object(
            study3b_preflight,
            "assert_study3b_continuation_readiness_current",
            return_value=self._synthetic_continuation_authority(),
        ):
            threads = [threading.Thread(target=compete, args=(ledger,)) for ledger in contenders]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=10)
            self.assertTrue(all(not thread.is_alive() for thread in threads))

        self.assertCountEqual(
            outcomes,
            [
                ("accepted", None),
                ("rejected", "LEDGER_ORIGINAL_PREFIX_MISMATCH"),
            ],
        )
        appended = source_ledger.path.read_bytes()
        self.assertEqual(appended[: len(prefix)], prefix)
        events = [
            json.loads(line)
            for line in appended[len(prefix) :].splitlines()
        ]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event"], "continuation_transition")
        self.assertEqual(
            sum(event.get("event") == "reservation" for event in events), 0
        )
        self.assertEqual(appended[: len(prefix)], prefix)

    def test_future_validator_metadata_is_codes_only_without_prose(self) -> None:
        allowed = study3b_ledger._normalize_validator_metadata(
            {
                "code": study3b_ledger.ORIGINAL_HA003_VALIDATOR_CODE,
                "rule_id": study3b_ledger.ORIGINAL_HA003_VALIDATOR_RULE_ID,
            },
            outcome="CONTRACT_FAILURE",
            required=True,
        )
        self.assertEqual(
            allowed,
            {
                "code": "GUARDED_MARKER_IN_PUBLIC_DELTA",
                "rule_id": "S3-GUARDED-CONTENT-MARKERS",
            },
        )
        for metadata in (
            {"code": "GUARDED_MARKER_IN_PUBLIC_DELTA", "rule_id": "S3-GUARDED-CONTENT-MARKERS", "message": "synthetic prose"},
            {"code": "GUARDED_MARKER_IN_PUBLIC_DELTA prose", "rule_id": "S3-GUARDED-CONTENT-MARKERS"},
            {"code": "GUARDED_MARKER_IN_PUBLIC_DELTA", "rule_id": "S3-GUARDED-CONTENT-MARKERS prose"},
        ):
            with self.subTest(metadata=metadata):
                with self.assertRaises(study3b_ledger.Study3bLedgerError):
                    study3b_ledger._normalize_validator_metadata(
                        metadata, outcome="CONTRACT_FAILURE", required=True
                    )

    def test_continuation_fsync_failure_poisoned_without_prefix_rewrite(self) -> None:
        _temporary, source_ledger, prefix = self._stopped_prefix_fixture()
        readiness = self._readiness_fixture()
        continuation = study3b_ledger.Study3bLedger._for_synthetic_test(
            source_ledger.root
        )
        with patch.object(
            study3b_ledger, "ORIGINAL_PREFIX_BYTES", len(prefix)
        ), patch.object(
            study3b_ledger,
            "ORIGINAL_PREFIX_SHA256",
            hashlib.sha256(prefix).hexdigest(),
        ), patch.object(
            study3b_preflight,
            "assert_study3b_continuation_readiness_current",
            return_value=self._synthetic_continuation_authority(),
        ), patch.object(study3b_ledger.os, "fsync", side_effect=OSError):
            with self.assertRaisesRegex(
                study3b_ledger.Study3bLedgerError,
                "LEDGER_CONTINUATION_DURABILITY_UNCERTAIN",
            ):
                continuation.continue_from_stopped(readiness=readiness)
        self.assertTrue(source_ledger.path.read_bytes().startswith(prefix))
        with self.assertRaisesRegex(
            study3b_ledger.Study3bLedgerError,
            "LEDGER_INSTANCE_POISONED",
        ):
            continuation.reserve(
                scene_id=study3b_ledger.protocol.SCENE_ORDER[1],
                request_sha256=study3b_ledger.request_sha256_for_scene(
                    study3b_ledger.protocol.SCENE_ORDER[1]
                ),
            )

    def test_reservation_binds_exact_hash_order_and_fsyncs_before_return(self) -> None:
        _temporary, ledger = self._new_ledger()
        scene_order = study3b_ledger.protocol.SCENE_ORDER
        expected_hash = study3b_ledger.request_sha256_for_scene(scene_order[0])
        binding = study3b_ledger._load_binding()

        with self.assertRaisesRegex(
            study3b_ledger.Study3bLedgerError,
            "SCENE_ORDER_OR_REQUEST_MISMATCH",
        ):
            ledger.reserve(
                scene_id=scene_order[0], request_sha256="0" * 64
            )
        with self.assertRaisesRegex(
            study3b_ledger.Study3bLedgerError,
            "SCENE_ORDER_OR_REQUEST_MISMATCH",
        ):
            ledger.reserve(
                scene_id=scene_order[1],
                request_sha256=study3b_ledger.request_sha256_for_scene(scene_order[1]),
            )

        with patch.object(
            study3b_ledger.os, "fsync", wraps=os.fsync
        ) as fsync_call:
            reservation = ledger.reserve(
                scene_id=scene_order[0], request_sha256=expected_hash
            )
        self.assertGreaterEqual(fsync_call.call_count, 1)
        self.assertEqual(reservation.study_id, "mise-en-scene-study3b-20261111")
        self.assertEqual(reservation.scene_id, scene_order[0])
        self.assertEqual(reservation.request_sha256, expected_hash)
        records = [
            json.loads(line)
            for line in ledger.path.read_text(encoding="ascii").splitlines()
        ]
        self.assertEqual(records[0]["lock_identity"], study3b_ledger.LOCK_IDENTITY)
        self.assertEqual(records[0]["scene_order"], list(scene_order))
        self.assertEqual(
            records[0]["manifest_sha256"],
            study3b_ledger.protocol.MANIFEST_SHA256,
        )
        self.assertEqual(
            records[0]["protocol_sha256"],
            study3b_ledger.protocol.PROTOCOL_SHA256,
        )
        self.assertEqual(
            records[0]["generation_config_sha256"],
            study3b_ledger.protocol.GENERATION_CONFIG_SHA256,
        )
        self.assertEqual(
            records[0]["request_bindings"],
            [
                {
                    "scene_id": scene,
                    "request_sha256": study3b_ledger.request_sha256_for_scene(scene),
                }
                for scene in scene_order
            ],
        )
        estimate_policy = records[0]["cost_estimate_policy"]
        self.assertEqual(
            estimate_policy["classification"],
            "ESTIMATE_NOT_PROVIDER_COST_GUARANTEE",
        )
        self.assertEqual(
            estimate_policy["pricing_provenance"],
            {
                "classification": "HISTORICAL_RATE_LISTING_NOT_CURRENT_QUOTE",
                "model_id": "openai/gpt-6-luna",
                "source_path": study3b_ledger.RATE_LISTING_RELATIVE,
                "source_bytes": study3b_ledger.RATE_LISTING_BYTES,
                "source_sha256": study3b_ledger.RATE_LISTING_SHA256,
                "attested_utc": study3b_ledger.RATE_ATTESTED_UTC,
                "prompt_usd_per_token_historical": "0.0000001",
                "completion_usd_per_token_historical": "0.0000005",
            },
        )
        estimate_rows = estimate_policy["scene_estimates"]
        self.assertEqual(
            [item["scene_id"] for item in estimate_rows], list(scene_order)
        )
        self.assertEqual(
            [item["request_sha256"] for item in estimate_rows],
            list(binding.request_hashes),
        )
        self.assertEqual(
            [item["canonical_request_wire_utf8_bytes"] for item in estimate_rows],
            [78646, 77399, 79100],
        )
        self.assertEqual(
            [item["conservative_cost_usd_estimate"] for item in estimate_rows],
            ["0.0108136", "0.0107720", "0.0108287"],
        )
        self.assertEqual(
            estimate_policy["conservative_total_usd_estimate"], "0.0324143"
        )
        self.assertEqual(
            estimate_policy["scene_estimates_sha256"],
            binding.scene_estimates_sha256,
        )
        self.assertEqual(records[1]["event"], "reservation")
        self.assertEqual(records[1]["request_sha256"], expected_hash)
        self.assertEqual(
            records[1]["conservative_cost_usd_estimate"], "0.0108136"
        )
        self.assertEqual(
            records[1]["pricing_provenance_sha256"],
            estimate_policy["pricing_provenance_sha256"],
        )
        self.assertEqual(records[1]["estimate_sha256"], reservation.estimate_sha256)
        expected_allocated_budget = Decimal("0.05") - Decimal("0.0107720") - Decimal("0.0108287")
        self.assertEqual(
            records[1]["reservation_budget_usd"], format(expected_allocated_budget, "f")
        )
        self.assertEqual(
            records[1]["pre_dispatch_estimated_total_usd"], "0.0324143"
        )
        self.assertEqual(
            reservation.reservation_budget_usd, format(expected_allocated_budget, "f")
        )
        self.assertEqual(
            reservation.pre_dispatch_estimated_total_usd, "0.0324143"
        )
        completion = ledger.complete(
            reservation,
            outcome="ACCEPTED",
            cost_receipt=self._verified_receipt(reservation),
        )
        self.assertEqual(completion.actual_cost_status, "RECONCILED")
        result_record = json.loads(
            ledger.path.read_text(encoding="ascii").splitlines()[-1]
        )
        self.assertEqual(result_record["study_id"], reservation.study_id)
        self.assertEqual(result_record["scene_order_sha256"], records[0]["scene_order_sha256"])
        self.assertEqual(result_record["request_sha256"], expected_hash)
        self.assertEqual(result_record["estimate_sha256"], reservation.estimate_sha256)
        self.assertEqual(
            result_record["cost_receipt"]["request_sha256"], expected_hash
        )

    def test_legacy_result_prefix_is_readable_from_synthetic_copy(self) -> None:
        temporary_directory, source_ledger = self._new_ledger()
        reservation = self._reserve_scene(source_ledger, 0)
        source_ledger.complete(
            reservation,
            outcome="ACCEPTED",
            cost_receipt=self._verified_receipt(reservation),
        )
        synthetic_records = [
            json.loads(line)
            for line in source_ledger.path.read_bytes().splitlines()
        ]
        self.assertEqual(synthetic_records[-1]["event"], "result")
        legacy_result = synthetic_records[-1]
        legacy_result.pop("validator_metadata", None)
        legacy_result["outcome"] = "CONTRACT_FAILURE"
        legacy_result["stop_study"] = True
        legacy_result["reason_code"] = None

        previous_sha256: str | None = None
        legacy_lines: list[bytes] = []
        for record in synthetic_records:
            record.pop("record_sha256", None)
            record["previous_sha256"] = previous_sha256
            record_sha256 = hashlib.sha256(
                study3b_ledger._canonical_bytes(record)
            ).hexdigest()
            record["record_sha256"] = record_sha256
            legacy_lines.append(study3b_ledger._canonical_bytes(record))
            previous_sha256 = record_sha256
        legacy_bytes = b"\n".join(legacy_lines) + b"\n"

        legacy_root = Path(temporary_directory.name) / "synthetic-legacy-prefix-copy"
        legacy_ledger = study3b_ledger.Study3bLedger._for_synthetic_test(
            legacy_root
        )
        legacy_ledger.initialize()
        assert_study3b_write_target(
            legacy_ledger.path,
            repository_root=REPO_ROOT,
            action="write",
        )
        legacy_ledger.path.write_bytes(legacy_bytes)

        with legacy_ledger._locked_existing() as (_root_fd, ledger_fd):
            state = study3b_ledger._read_state(
                ledger_fd, study3b_ledger._load_binding()
            )
        self.assertTrue(state.stopped)
        self.assertEqual(len(state.results), 1)
        self.assertEqual(state.results[0]["outcome"], "CONTRACT_FAILURE")
        self.assertNotIn("validator_metadata", state.results[0])
        self.assertEqual(state.actual_total, Decimal("0.001"))
        with self.assertRaises(study3b_ledger.Study3bLedgerError) as blocked:
            legacy_ledger.reserve(
                scene_id=study3b_ledger.protocol.SCENE_ORDER[1],
                request_sha256=study3b_ledger.request_sha256_for_scene(
                    study3b_ledger.protocol.SCENE_ORDER[1]
                ),
            )
        self.assertEqual(blocked.exception.code, "LEDGER_STUDY_STOPPED")
        self.assertEqual(legacy_ledger.path.read_bytes(), legacy_bytes)

    def test_every_ledger_mutation_uses_the_prior_study_write_guard(self) -> None:
        prep_root = REPO_ROOT / PREP_ROOT_RELATIVE
        temporary_directory = tempfile.TemporaryDirectory(
            prefix="study3b-ledger-write-guard-test-", dir=prep_root
        )
        self.addCleanup(temporary_directory.cleanup)
        ledger_root = Path(temporary_directory.name) / "synthetic-ledger"
        ledger = study3b_ledger.Study3bLedger._for_synthetic_test(ledger_root)
        original_guard = study3b_ledger.assert_study3b_write_target
        guarded_paths: list[Path] = []

        def record_guard(
            path: object,
            *,
            repository_root: Path | str | None = None,
            action: str = "write",
        ) -> None:
            guarded_paths.append(Path(path))
            original_guard(
                path,
                repository_root=repository_root,
                action=action,
            )

        with patch.object(
            study3b_ledger,
            "assert_study3b_write_target",
            side_effect=record_guard,
        ):
            ledger.initialize()
            reservation = self._reserve_scene(ledger, 0)
            ledger.complete(
                reservation,
                outcome="ACCEPTED",
                cost_receipt=self._verified_receipt(reservation),
            )

        self.assertGreaterEqual(len(guarded_paths), 10)
        self.assertTrue(
            all(path == ledger.root or ledger.root in path.parents for path in guarded_paths)
        )

    def test_conservative_budget_equality_overage_and_unknowns_fail_closed(self) -> None:
        require_total = study3b_ledger._require_conservative_budget_total
        error = study3b_ledger.Study3bLedgerError
        strict_failure = "LEDGER_CONSERVATIVE_BUDGET_NOT_STRICTLY_BELOW_CEILING"
        for actual_spent, estimates in (
            (Decimal("0"), (Decimal("0.05"),)),
            (Decimal("0.01"), (Decimal("0.04"),)),
            (Decimal("0"), (Decimal("0.0500001"),)),
            (Decimal("0.0100001"), (Decimal("0.04"),)),
        ):
            with self.subTest(actual_spent=actual_spent, estimates=estimates):
                with self.assertRaisesRegex(error, strict_failure):
                    require_total(actual_spent, estimates)

        for estimates, expected_code in (
            (None, "LEDGER_ESTIMATE_UNAVAILABLE"),
            ((), "LEDGER_ESTIMATE_UNAVAILABLE"),
            ((Decimal("NaN"),), "LEDGER_ESTIMATE_INVALID"),
            ((Decimal("Infinity"),), "LEDGER_ESTIMATE_INVALID"),
            ((Decimal("-0.0001"),), "LEDGER_ESTIMATE_INVALID"),
            (("0.01",), "LEDGER_ESTIMATE_INVALID"),
        ):
            with self.subTest(estimates=estimates):
                with self.assertRaisesRegex(error, expected_code):
                    require_total(Decimal("0"), estimates)

        for actual_spent in (Decimal("NaN"), Decimal("Infinity"), Decimal("-0.01")):
            with self.subTest(actual_spent=actual_spent):
                with self.assertRaisesRegex(error, "LEDGER_ACTUAL_COST_INVALID"):
                    require_total(actual_spent, (Decimal("0.01"),))

    def test_estimate_hashes_reject_missing_forged_and_mismatched_bindings(self) -> None:
        binding = study3b_ledger._load_binding()
        validate = study3b_ledger._validate_scene_estimate_binding
        with self.assertRaisesRegex(
            study3b_ledger.Study3bLedgerError, "LEDGER_ESTIMATE_UNAVAILABLE"
        ):
            validate(replace(binding, scene_estimates=()), 16384)

        forged_request = replace(
            binding.scene_estimates[0], request_sha256="f" * 64
        )
        with self.assertRaisesRegex(
            study3b_ledger.Study3bLedgerError, "LEDGER_ESTIMATE_BINDING_INVALID"
        ):
            validate(
                replace(
                    binding,
                    scene_estimates=(forged_request,) + binding.scene_estimates[1:],
                ),
                16384,
            )

        forged_provenance = replace(
            binding.scene_estimates[0], pricing_provenance_sha256="e" * 64
        )
        with self.assertRaisesRegex(
            study3b_ledger.Study3bLedgerError, "LEDGER_ESTIMATE_BINDING_INVALID"
        ):
            validate(
                replace(
                    binding,
                    scene_estimates=(forged_provenance,)
                    + binding.scene_estimates[1:],
                ),
                16384,
            )

        forged_amount = replace(
            binding.scene_estimates[0], conservative_cost_usd=Decimal("0.04")
        )
        with self.assertRaisesRegex(
            study3b_ledger.Study3bLedgerError, "LEDGER_ESTIMATE_INVALID"
        ):
            validate(
                replace(
                    binding,
                    scene_estimates=(forged_amount,) + binding.scene_estimates[1:],
                ),
                16384,
            )

    def test_missing_historical_pricing_stops_before_synthetic_ledger_creation(self) -> None:
        prep_root = REPO_ROOT / PREP_ROOT_RELATIVE
        with tempfile.TemporaryDirectory(
            prefix="study3b-ledger-missing-pricing-test-", dir=prep_root
        ) as temporary_directory:
            ledger_root = Path(temporary_directory) / "synthetic-ledger"
            ledger = study3b_ledger.Study3bLedger._for_synthetic_test(ledger_root)
            with patch.object(
                study3b_ledger,
                "_load_historical_rate_provenance",
                return_value={"model_id": "openai/gpt-6-luna"},
            ):
                with self.assertRaises(study3b_ledger.Study3bLedgerError):
                    ledger.initialize()
            self.assertFalse(ledger_root.exists())

    def test_pending_restart_duplicate_and_replay_are_rejected(self) -> None:
        _temporary, ledger = self._new_ledger()
        first = self._reserve_scene(ledger, 0)
        with self.assertRaisesRegex(
            study3b_ledger.Study3bLedgerError,
            "LEDGER_PENDING_RESERVATION",
        ):
            self._reserve_scene(ledger, 1)

        restarted = study3b_ledger.Study3bLedger._for_synthetic_test(ledger.root)
        with self.assertRaisesRegex(
            study3b_ledger.Study3bLedgerError,
            "LEDGER_INSTANCE_NOT_INITIALIZED",
        ):
            self._reserve_scene(restarted, 0)
        with self.assertRaisesRegex(
            study3b_ledger.Study3bLedgerError,
            "LEDGER_ALREADY_INITIALIZED",
        ):
            restarted.initialize()

        completion = ledger.complete(
            first, outcome="ACCEPTED", cost_receipt=self._verified_receipt(first)
        )
        self.assertEqual(completion.actual_cost_status, "RECONCILED")
        with self.assertRaisesRegex(
            study3b_ledger.Study3bLedgerError,
            "SCENE_ORDER_OR_REQUEST_MISMATCH",
        ):
            self._reserve_scene(ledger, 0)
        second = self._reserve_scene(ledger, 1)
        self.assertEqual(second.attempt_number, 2)

    def test_missing_and_inconsistent_cost_receipts_stop_future_reservations(self) -> None:
        for invalid_mode in ("missing", "inconsistent", "fabricated"):
            with self.subTest(invalid_mode=invalid_mode):
                _temporary, ledger = self._new_ledger()
                reservation = self._reserve_scene(ledger, 0)
                receipt = (
                    None
                    if invalid_mode == "missing"
                    else self._receipt(reservation)
                )
                if invalid_mode == "inconsistent" and receipt is not None:
                    receipt["request_sha256"] = "f" * 64
                completion = ledger.complete(
                    reservation, outcome="ACCEPTED", cost_receipt=receipt
                )
                self.assertEqual(completion.actual_cost_status, "UNRESOLVED")
                self.assertTrue(completion.stop_study)
                with self.assertRaisesRegex(
                    study3b_ledger.Study3bLedgerError,
                    "LEDGER_ACTUAL_COST_UNRESOLVED",
                ):
                    self._reserve_scene(ledger, 1)

    def test_cost_receipt_derives_from_verified_transport_response(self) -> None:
        _temporary, ledger = self._new_ledger()
        reservation = self._reserve_scene(ledger, 0)
        transport_result = self._synthetic_transport_result(reservation)

        with self.assertRaisesRegex(
            study3b_ledger.Study3bLedgerError,
            "COST_RECEIPT_RESPONSE_IDENTITY_MISMATCH",
        ):
            study3b_ledger._make_verified_cost_receipt(
                reservation,
                replace(transport_result, returned_model_id="openai/forged-model"),
            )
        with self.assertRaisesRegex(
            study3b_ledger.Study3bLedgerError,
            "COST_RECEIPT_BINDING_MISMATCH",
        ):
            study3b_ledger._make_verified_cost_receipt(
                reservation,
                replace(transport_result, http_status=429),
            )

        completion = ledger.complete(
            reservation,
            outcome="ACCEPTED",
            cost_receipt=study3b_ledger._make_verified_cost_receipt(
                reservation, transport_result
            ),
        )
        self.assertEqual(completion.actual_cost_status, "RECONCILED")

    def test_actual_cost_over_allocation_stops_and_estimate_equality_blocks_next(self) -> None:
        _temporary, ledger = self._new_ledger()
        reservation = self._reserve_scene(ledger, 0)
        completion = ledger.complete(
            reservation,
            outcome="ACCEPTED",
            cost_receipt=self._verified_receipt(
                reservation, cost_usd="0.0500001"
            ),
        )
        self.assertEqual(completion.actual_cost_status, "OVER_CAP")
        self.assertEqual(completion.actual_cost_usd, "0.0500001")
        self.assertTrue(completion.stop_study)
        with self.assertRaisesRegex(
            study3b_ledger.Study3bLedgerError,
            "LEDGER_STUDY_STOPPED",
        ):
            self._reserve_scene(ledger, 1)

        _temporary_at_cap, at_cap_ledger = self._new_ledger()
        at_cap_reservation = self._reserve_scene(at_cap_ledger, 0)
        allocated_budget = at_cap_reservation.reservation_budget_usd
        at_cap_completion = at_cap_ledger.complete(
            at_cap_reservation,
            outcome="ACCEPTED",
            cost_receipt=self._verified_receipt(
                at_cap_reservation, cost_usd=allocated_budget
            ),
        )
        self.assertEqual(at_cap_completion.actual_cost_status, "RECONCILED")
        with self.assertRaisesRegex(
            study3b_ledger.Study3bLedgerError,
            "LEDGER_CONSERVATIVE_BUDGET_NOT_STRICTLY_BELOW_CEILING",
        ):
            self._reserve_scene(at_cap_ledger, 1)

    def test_over_attempt_cap_corruption_and_prior_root_alias_fail_closed(self) -> None:
        _temporary, ledger = self._new_ledger()
        for index in range(3):
                reservation = self._reserve_scene(ledger, index)
                ledger.complete(
                    reservation,
                    outcome="ACCEPTED",
                    cost_receipt=self._verified_receipt(
                        reservation, cost_usd="0.001", generation_id=f"gen-{index}"
                    ),
            )
        with self.assertRaisesRegex(
            study3b_ledger.Study3bLedgerError,
            "LEDGER_ATTEMPT_CAP_EXHAUSTED",
        ):
            self._reserve_scene(ledger, 0)

        _corrupt_temp, corrupt_ledger = self._new_ledger()
        with corrupt_ledger.path.open("ab") as stream:
            stream.write(b"{corrupt-ledger-record}\n")
        with self.assertRaisesRegex(
            study3b_ledger.Study3bLedgerError, "LEDGER_CORRUPT"
        ):
            self._reserve_scene(corrupt_ledger, 0)

        prep_root = REPO_ROOT / PREP_ROOT_RELATIVE
        with tempfile.TemporaryDirectory(
            prefix="study3b-prior-ledger-alias-test-", dir=prep_root
        ) as temporary_directory:
            alias_path = Path(temporary_directory) / "synthetic-ledger"
            old_study3_root = (
                REPO_ROOT
                / "tmp/router-rollout/mapping-pilot/mise-en-scene-offline/"
                / "llm-staging-study3-prep/durable-ledger"
            )
            alias_path.symlink_to(old_study3_root, target_is_directory=True)
            aliased = study3b_ledger.Study3bLedger._for_synthetic_test(alias_path)
            with self.assertRaises(study3b_ledger.Study3bLedgerError):
                aliased.initialize()

    def test_write_and_fsync_failure_poison_instance_without_replay(self) -> None:
        _temporary, ledger = self._new_ledger()

        def fail_fsync(_descriptor: int) -> None:
            raise OSError("synthetic fsync failure")

        with patch.object(study3b_ledger.os, "fsync", side_effect=fail_fsync):
            with self.assertRaisesRegex(
                study3b_ledger.Study3bLedgerError,
                "LEDGER_DURABILITY_UNCERTAIN",
            ):
                self._reserve_scene(ledger, 0)
        with self.assertRaisesRegex(
            study3b_ledger.Study3bLedgerError, "LEDGER_INSTANCE_POISONED"
        ):
            self._reserve_scene(ledger, 0)

        _write_temp, write_ledger = self._new_ledger()
        reservation = self._reserve_scene(write_ledger, 0)
        with patch.object(
            study3b_ledger,
            "_write_all",
            side_effect=OSError("synthetic disk write failure"),
        ):
            with self.assertRaisesRegex(
                study3b_ledger.Study3bLedgerError,
                "LEDGER_COMPLETION_DURABILITY_UNCERTAIN",
            ):
                write_ledger.complete(
                    reservation,
                    outcome="ACCEPTED",
                    cost_receipt=self._verified_receipt(reservation),
                )

if __name__ == "__main__":
    unittest.main()
