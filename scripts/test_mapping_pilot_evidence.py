# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free tests for mapping-pilot row evidence bundles."""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import subprocess
import sys
import unittest
import uuid
from pathlib import Path
from typing import Any
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.mapping_pilot import evidence
from scripts.mapping_pilot.evidence import (
    DEFAULT_EVIDENCE_ROOT,
    EvidenceBundleError,
    create_evidence_bundle,
    load_turn_packet_evidence,
)
from scripts.mapping_pilot.manifest import verify_manifest
from scripts.mapping_pilot.scoring import (
    MATRIX_ATTEMPT_CAP,
    MATRIX_WALL_TIME_CAP_SECONDS,
    ROW_ATTEMPT_CAP,
    ROW_WALL_TIME_CAP_SECONDS,
)
from utils.file_operations import safe_write_json

logging.getLogger("utils.file_operations").setLevel(logging.WARNING)


class MappingPilotEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.scratch_root = Path("tmp") / (
            "mapping-pilot-evidence-tests-" + uuid.uuid4().hex
        )
        cls.scratch_root.mkdir(parents=True, exist_ok=False)

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.scratch_root, ignore_errors=True)

    def setUp(self) -> None:
        self.test_root = self.scratch_root / self._testMethodName
        self.test_root.mkdir(parents=True, exist_ok=False)
        self.base_root = self.test_root / "bundles"

    def _row(self, row_id: str = "E01") -> dict[str, Any]:
        return {
            "row_id": row_id,
            "fixture_id": "interior_tavern",
            "script_id": "interior_e1_e4",
            "scenario_id": "E1",
            "arm": "A",
            "party": "P1",
            "seed": 5101,
        }

    def _provenance(self) -> dict[str, Any]:
        return {
            "source_identity": {
                "git_head_sha": "a" * 40,
                "branch": "feature/mapping-pilot",
                "dirty": False,
                "worktree": "repo-root",
            },
            "input_paths": {
                "fixture": "fixtures/interior_tavern.json",
                "script": "scripts/interior.json",
                "scenario": "scripts/interior.json",
            },
            "route_identity": {
                "requested": [
                    {
                        "call_id": "turn-01",
                        "model": "openrouter/auto",
                        "provider": "openrouter",
                        "fallback": False,
                    }
                ],
                "resolved": [
                    {
                        "call_id": "turn-01",
                        "model": "openai/example-model",
                        "provider": "openai",
                        "fallback": False,
                    }
                ],
            },
            "evidence_kind": "live",
        }

    def _packet_record(self, status: str = "recorded") -> dict[str, Any]:
        packet = "Place: tavern entrance; route: village green."
        return {
            "format_version": 1,
            "lifecycle_id": "lifecycle-01",
            "sequence": 2,
            "context_id": "context-01",
            "turn_id": "lifecycle-01:context-01:1",
            "turn_number": 1,
            "turn_kind": "normal",
            "event_type": "packet_use",
            "surface": "dm_note",
            "use_index": 1,
            "packet_status": "present",
            "packet_ascii": packet,
            "packet_sha256": hashlib.sha256(packet.encode("ascii")).hexdigest(),
            "evidence_status": status,
        }

    def _artifacts(self, exact_packets: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "exact_packets": exact_packets
            if exact_packets is not None
            else {"evidence_status": "recorded", "records": [self._packet_record()]},
            "transcript": "The party enters the tavern.\n",
            "state_snapshots": {"before": {"location": "village_green"}, "after": {"location": "tavern"}},
            "zone_trace": {"status": "not_applicable", "reason": "exploration row"},
            "expected_observed_checks": [
                {
                    "check_id": "E1-01-landmarks",
                    "expected": "Stable tavern landmarks are reported.",
                    "observed": "The entrance and hearth are described.",
                    "passed": True,
                }
            ],
            "cap_counts": {
                "row_attempts": 8,
                "row_elapsed_seconds": 300,
                "matrix_attempts": 48,
                "matrix_elapsed_seconds": 2400,
                "caps": {
                    "row_attempts": ROW_ATTEMPT_CAP,
                    "row_wall_time_seconds": ROW_WALL_TIME_CAP_SECONDS,
                    "matrix_attempts": MATRIX_ATTEMPT_CAP,
                    "matrix_wall_time_seconds": MATRIX_WALL_TIME_CAP_SECONDS,
                },
            },
            "logs": "Capture row completed without server errors.\n",
        }

    def _write_turn_record(self, record: dict[str, Any]) -> Path:
        relative = (
            self.test_root
            / "runtime"
            / "mapping_pilot"
            / "turn_packet_evidence"
            / "lifecycle-01"
            / "record-00000002.json"
        )
        relative.parent.mkdir(parents=True, exist_ok=False)
        wrote = safe_write_json(
            str(relative),
            record,
            create_backup=False,
            acquire_lock=True,
            json_kwargs={"ensure_ascii": True, "sort_keys": True},
        )
        self.assertTrue(wrote)
        return relative

    def _create(
        self,
        run_id: str = "run-01",
        *,
        row: dict[str, Any] | None = None,
        provenance: dict[str, Any] | None = None,
        artifacts: dict[str, Any] | None = None,
        verdict: str = "PASS",
        base_root: Path | None = None,
    ) -> Path:
        return create_evidence_bundle(
            "SP3",
            run_id,
            row=row if row is not None else self._row(),
            provenance=provenance if provenance is not None else self._provenance(),
            artifacts=artifacts if artifacts is not None else self._artifacts(),
            verdict=verdict,
            base_root=base_root if base_root is not None else self.base_root,
        )

    def test_complete_bundle_records_required_provenance_and_file_hashes(self) -> None:
        bundle = self._create()
        self.assertEqual(
            bundle,
            self.base_root / "SP3" / "run-01",
        )
        absolute_bundle = ROOT / bundle
        manifest = json.loads((absolute_bundle / "manifest.json").read_text(encoding="ascii"))
        self.assertTrue(manifest["complete"])
        self.assertEqual(manifest["verdict"], "PASS")
        self.assertEqual(manifest["row_id"], "E01")
        self.assertEqual(manifest["turn_evidence_status"], "recorded")
        expected_files = {
            "row.json",
            "provenance.json",
            "exact_packets.json",
            "transcript.txt",
            "state_snapshots.json",
            "zone_trace.json",
            "checks.json",
            "cap_counts.json",
            "server_logs.txt",
            "verdict.json",
        }
        self.assertEqual(set(manifest["files"]), expected_files)
        for name, expected_hash in manifest["files"].items():
            content = (absolute_bundle / name).read_bytes()
            self.assertEqual(hashlib.sha256(content).hexdigest(), expected_hash)
            self.assertTrue(content.isascii(), name)
        provenance = json.loads(
            (absolute_bundle / "provenance.json").read_text(encoding="ascii")
        )
        verified = verify_manifest()
        for category, path in (
            ("fixture", "fixtures/interior_tavern.json"),
            ("script", "scripts/interior.json"),
            ("scenario", "scripts/interior.json"),
        ):
            self.assertEqual(provenance["input_hashes"][category]["path"], path)
            self.assertEqual(provenance["input_hashes"][category]["sha256"], verified[path])
        self.assertEqual(provenance["source_identity"]["git_head_sha"], "a" * 40)
        self.assertEqual(provenance["route_identity"]["resolved"][0]["provider"], "openai")
        self.assertEqual(json.loads((absolute_bundle / "row.json").read_text())["seed"], 5101)
        self.assertNotIn("manifest.json", manifest["files"])
        self.assertEqual(DEFAULT_EVIDENCE_ROOT, Path("tmp/router-rollout/mapping-pilot"))

    def test_text_artifacts_are_written_as_ascii_safe_escapes(self) -> None:
        artifacts = self._artifacts()
        artifacts["transcript"] = "The cafe has a cafe\u0301 sign.\n"
        bundle = self._create(artifacts=artifacts)
        transcript = (ROOT / bundle / "transcript.txt").read_bytes()
        self.assertTrue(transcript.isascii())
        self.assertIn(b"\\u0301", transcript)

    def test_ingests_adapter_turn_records_as_exact_packet_bytes_and_hashes(self) -> None:
        record = self._packet_record()
        source_directory = self._write_turn_record(record).parent
        exact_packets = load_turn_packet_evidence(source_directory)
        self.assertEqual(exact_packets["evidence_status"], "recorded")
        self.assertEqual(exact_packets["records"][0]["packet_ascii"], record["packet_ascii"])
        self.assertEqual(exact_packets["records"][0]["packet_sha256"], record["packet_sha256"])
        bundle = self._create(artifacts=self._artifacts(exact_packets))
        stored = json.loads((ROOT / bundle / "exact_packets.json").read_text(encoding="ascii"))
        self.assertEqual(stored["records"][0]["packet_ascii"], record["packet_ascii"])
        self.assertEqual(stored["records"][0]["packet_sha256"], record["packet_sha256"])

    def test_turn_packet_loader_marks_an_empty_record_directory_missing(self) -> None:
        source_directory = self.test_root / "empty-turn-evidence"
        source_directory.mkdir()
        loaded = load_turn_packet_evidence(source_directory)
        self.assertEqual(loaded, {"evidence_status": "missing", "records": []})

    def test_rejects_existing_run_id_without_overwrite_or_merge(self) -> None:
        first = self._create()
        with self.assertRaisesRegex(EvidenceBundleError, "already exists"):
            self._create(row=self._row("E02"))
        self.assertTrue((ROOT / first / "manifest.json").is_file())
        self.assertFalse((ROOT / self.base_root / "SP3" / "run-01" / "row.json.bak").exists())

    def test_rejects_reuse_of_row_id_under_a_different_run_id(self) -> None:
        self._create()
        with self.assertRaisesRegex(EvidenceBundleError, "row_id already has a bundle"):
            self._create("run-02")
        self.assertFalse((ROOT / self.base_root / "SP3" / "run-02").exists())

    def test_partial_bundle_has_no_final_manifest_and_cannot_be_reused(self) -> None:
        original_write = evidence._write_json

        def fail_on_provenance(relative_path: Path, payload: Any) -> None:
            if relative_path.name == "provenance.json":
                raise EvidenceBundleError("injected write failure")
            original_write(relative_path, payload)

        with mock.patch.object(evidence, "_write_json", side_effect=fail_on_provenance):
            with self.assertRaisesRegex(EvidenceBundleError, "injected write failure"):
                self._create()
        partial = ROOT / self.base_root / "SP3" / "run-01"
        self.assertTrue(partial.is_dir())
        self.assertTrue((partial / "row.json").is_file())
        self.assertFalse((partial / "manifest.json").exists())
        with self.assertRaisesRegex(EvidenceBundleError, "row_id already has a bundle"):
            self._create("run-02")

    def test_rejects_nested_secret_fields_before_writing(self) -> None:
        for key in ("api_key", "authorization", "access_token", "password", "secret", "token"):
            with self.subTest(key=key):
                artifacts = self._artifacts()
                artifacts["state_snapshots"] = {"nested": {key: "opaque-value"}}
                with self.assertRaisesRegex(EvidenceBundleError, "secret-like fields"):
                    self._create(artifacts=artifacts)
        self.assertFalse((ROOT / self.base_root).exists())

    def test_rejects_secret_values_in_text_and_config_py_content(self) -> None:
        for text in (
            "Authorization: Bearer opaque-value",
            "token=opaque-value",
            "config.py contents: API_KEY = 'opaque-value'",
        ):
            with self.subTest(text=text):
                artifacts = self._artifacts()
                artifacts["logs"] = text
                with self.assertRaisesRegex(EvidenceBundleError, "secret-like text"):
                    self._create(artifacts=artifacts)
                self.assertFalse((ROOT / self.base_root).exists())

    def test_rejects_degraded_or_missing_turn_evidence_for_pass(self) -> None:
        degraded = {"evidence_status": "recorded", "records": [self._packet_record("degraded")]}
        missing = {"evidence_status": "missing", "records": []}
        for exact_packets in (degraded, missing):
            with self.subTest(status=exact_packets["evidence_status"]):
                with self.assertRaisesRegex(EvidenceBundleError, "PASS is forbidden"):
                    self._create(artifacts=self._artifacts(exact_packets))
        self.assertFalse((ROOT / self.base_root).exists())

    def test_allows_degraded_turn_evidence_only_with_non_pass_verdict(self) -> None:
        exact_packets = {
            "evidence_status": "degraded",
            "records": [self._packet_record("degraded")],
        }
        bundle = self._create(artifacts=self._artifacts(exact_packets), verdict="BLOCKED")
        manifest = json.loads((ROOT / bundle / "manifest.json").read_text(encoding="ascii"))
        self.assertEqual(manifest["verdict"], "BLOCKED")
        self.assertEqual(manifest["turn_evidence_status"], "degraded")

    def test_rejects_missing_required_artifacts_and_bad_manifest_paths(self) -> None:
        artifacts = self._artifacts()
        del artifacts["logs"]
        with self.assertRaisesRegex(EvidenceBundleError, "artifacts are missing"):
            self._create(artifacts=artifacts)

        provenance = self._provenance()
        provenance["input_paths"]["fixture"] = "fixtures/unlisted.json"
        with self.assertRaisesRegex(EvidenceBundleError, "not in MANIFEST"):
            self._create(provenance=provenance)
        self.assertFalse((ROOT / self.base_root).exists())

    def test_rejects_incomplete_checks_and_unknown_or_exhausted_caps_for_pass(self) -> None:
        artifacts = self._artifacts()
        artifacts["expected_observed_checks"][0]["passed"] = False
        with self.assertRaisesRegex(EvidenceBundleError, "every expected/observed check"):
            self._create(artifacts=artifacts)

        artifacts = self._artifacts()
        artifacts["cap_counts"]["row_attempts"] = ROW_ATTEMPT_CAP
        with self.assertRaisesRegex(EvidenceBundleError, "below every cap"):
            self._create(artifacts=artifacts)

        artifacts = self._artifacts()
        artifacts["cap_counts"]["matrix_attempts"] = "unknown"
        with self.assertRaisesRegex(EvidenceBundleError, "below every cap"):
            self._create(artifacts=artifacts)
        self.assertFalse((ROOT / self.base_root).exists())

    def test_rejects_packet_hash_tampering(self) -> None:
        packets = self._artifacts()["exact_packets"]
        packets["records"][0]["packet_ascii"] += " tampered"
        with self.assertRaisesRegex(EvidenceBundleError, "hash does not match"):
            self._create(artifacts=self._artifacts(packets))
        self.assertFalse((ROOT / self.base_root).exists())

    def test_rejects_unsafe_tokens_and_symlinked_bundle_root(self) -> None:
        with self.assertRaisesRegex(EvidenceBundleError, "safe path token"):
            create_evidence_bundle(
                "../SP3",
                "run-01",
                row=self._row(),
                provenance=self._provenance(),
                artifacts=self._artifacts(),
                verdict="PASS",
                base_root=self.base_root,
            )

        target = self.test_root / "real-root"
        target.mkdir()
        link = self.test_root / "linked-root"
        link.symlink_to(target, target_is_directory=True)
        with self.assertRaisesRegex(EvidenceBundleError, "must not traverse symlinks"):
            self._create(base_root=link)
        self.assertEqual(list(target.iterdir()), [])

    def test_module_does_not_import_runtime_entry_points(self) -> None:
        code = (
            "import importlib, sys; "
            "importlib.import_module('scripts.mapping_pilot.evidence'); "
            "forbidden = ('core', 'main', 'web', 'model_config'); "
            "bad = sorted(name for name in sys.modules if any("
            "name == item or name.startswith(item + '.') for item in forbidden)); "
            "print(bad)"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip(), "[]", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
