# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free tests for the safe adaptation rebuild directive contract."""

from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.test_toolkit_adaptation_auditor import (  # noqa: E402
    _base_response,
    _dossier,
    _packet,
)
from utils.toolkit_adaptation_auditor import (  # noqa: E402
    AUDITOR_DECISION_REVISE,
    parse_adaptation_auditor_response,
)
from utils.toolkit_adaptation_rebuild_directive import (  # noqa: E402
    ADAPTATION_REBUILD_DIRECTIVE_CONTRACT_VERSION,
    DIAGNOSTIC_CODE_DOSSIER_INVALID,
    DIAGNOSTIC_CODE_FORBIDDEN_FIELD,
    DIAGNOSTIC_CODE_TARGET_INVALID,
    DIRECTIVE_STATUS_INVALID,
    DIRECTIVE_STATUS_VALID,
    parse_adaptation_rebuild_directive,
    validate_adaptation_rebuild_directive,
)
from utils.toolkit_adaptation_staging import (  # noqa: E402
    create_adaptation_staging_target,
)
from utils.toolkit_llm_final_reconciliation import (  # noqa: E402
    FINAL_RECONCILIATION_PATCH_VERSION,
    validate_final_reconciliation_patch_contract,
)


SOURCE_HASH = "c" * 64


class TestSafeAdaptationRebuildDirective(unittest.TestCase):
    def setUp(self) -> None:
        self.packet = _packet()
        self.temp_dir = tempfile.TemporaryDirectory(
            dir=str(Path(__file__).resolve().parents[1] / "tmp")
        )
        self.repo_root = Path(self.temp_dir.name)
        self.target = create_adaptation_staging_target(
            SOURCE_HASH,
            attempt_id=self.packet["attempt_id"],
            attempt_number=self.packet["attempt_number"],
            revision_number=1,
            source_path="",
            staging_root="tmp/adaptation-staging",
            repo_root=self.repo_root,
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _identity(self) -> dict:
        return {
            "target_kind": "staging",
            "stage_id": self.target["stage_id"],
            "attempt_id": self.target["attempt_id"],
            "attempt_number": self.target["attempt_number"],
            "revision_number": self.target["revision_number"],
            "source_hash": self.target["source_hash"],
        }

    def _directive(self) -> dict:
        return {
            "version": ADAPTATION_REBUILD_DIRECTIVE_CONTRACT_VERSION,
            "action": "fresh_build",
            "target": self._identity(),
            "basis": "revised_dossier",
            "scope": "semantic_adaptation",
            "reason": "Repair the canonical destination framing before a fresh build.",
            "constraints": [
                "Keep one playable destination identity.",
                "Preserve the adapted source provenance.",
            ],
        }

    def _validate(self, directive: dict, **kwargs: object) -> dict:
        return validate_adaptation_rebuild_directive(
            directive,
            failure_packet=self.packet,
            staging_target=self.target,
            repo_root=self.repo_root,
            **kwargs,
        )

    def test_valid_identity_resolves_to_reserved_stage_without_building(self) -> None:
        result = self._validate(self._directive())
        self.assertTrue(result["valid"], result["diagnostics"])
        self.assertEqual(result["status"], DIRECTIVE_STATUS_VALID)
        self.assertEqual(result["plan"]["stage_id"], self.target["stage_id"])
        self.assertEqual(result["plan"]["revision_number"], 1)
        self.assertEqual(result["writes"], [])
        self.assertFalse(result["side_effects"])
        self.assertFalse(result["write_performed"])

    def test_task_52_logical_staging_target_uses_python_identity(self) -> None:
        directive = self._directive()
        directive.pop("version")
        directive["target"] = "staging"
        directive.pop("scope")
        directive.pop("reason")
        directive["guidance"] = ["Keep the destination canonical and playable."]
        result = self._validate(directive)
        self.assertTrue(result["valid"], result["diagnostics"])
        self.assertEqual(result["plan"]["stage_id"], self.target["stage_id"])

    def test_invalid_target_forms_are_rejected_before_writes(self) -> None:
        invalid_targets = (
            "/absolute/module",
            "../escape",
            "modules/Unsafe_Module",
            "world_registry.json",
            "campaign.json",
            "characters/vitreol.json",
            "data/runtime/scene_followers.json",
            "https://example.invalid/module",
            "rm -rf modules/Unsafe_Module",
        )
        target_path = self.repo_root / self.target["path"]
        sentinel = target_path / "sentinel.txt"
        sentinel.write_text("unchanged", encoding="utf-8")
        for invalid_target in invalid_targets:
            with self.subTest(invalid_target=invalid_target):
                directive = self._directive()
                directive["target"] = invalid_target
                result = self._validate(directive)
                self.assertFalse(result["valid"])
                self.assertEqual(result["status"], DIRECTIVE_STATUS_INVALID)
                self.assertEqual(result["writes"], [])
                self.assertFalse(result["side_effects"])
                self.assertEqual(sentinel.read_text(encoding="utf-8"), "unchanged")

    def test_unknown_fields_and_operations_are_rejected(self) -> None:
        for field, payload in (
            ("ops", []),
            ("file_patches", []),
            ("target_path", "modules/Unsafe_Module"),
            ("module_dir", "modules/Unsafe_Module"),
        ):
            with self.subTest(field=field):
                directive = self._directive()
                directive[field] = payload
                result = self._validate(directive)
                self.assertFalse(result["valid"])
                self.assertIn(
                    DIAGNOSTIC_CODE_FORBIDDEN_FIELD,
                    {item["code"] for item in result["diagnostics"]},
                )

    def test_nested_target_paths_are_rejected_as_unknown_fields(self) -> None:
        directive = self._directive()
        directive["target"]["path"] = "/absolute/module"
        result = self._validate(directive)
        self.assertFalse(result["valid"])
        self.assertIn(
            DIAGNOSTIC_CODE_FORBIDDEN_FIELD,
            {item["code"] for item in result["diagnostics"]},
        )

    def test_raw_parser_rejects_malformed_and_fenced_json(self) -> None:
        for raw in ("not json", "```json\n{}\n```"):
            with self.subTest(raw=raw[:8]):
                result = parse_adaptation_rebuild_directive(raw)
                self.assertFalse(result["valid"])
                self.assertEqual(result["writes"], [])

    def test_invalid_dossier_is_rejected_without_a_write(self) -> None:
        dossier = _dossier()
        dossier.pop("areas")
        result = self._validate(self._directive(), revised_dossier=dossier)
        self.assertFalse(result["valid"])
        self.assertIn(
            DIAGNOSTIC_CODE_DOSSIER_INVALID,
            {item["code"] for item in result["diagnostics"]},
        )
        self.assertEqual(result["writes"], [])

    def test_oversized_or_unsafe_dossier_is_rejected(self) -> None:
        dossier = _dossier()
        dossier["module_tone"] = "x" * 50_000
        result = self._validate(self._directive(), revised_dossier=dossier)
        self.assertFalse(result["valid"])
        self.assertEqual(result["writes"], [])

        dossier = _dossier()
        dossier["module_tone"] = "https://example.invalid/raw-source"
        result = self._validate(self._directive(), revised_dossier=dossier)
        self.assertFalse(result["valid"])
        self.assertTrue(result["diagnostics"])

    def test_provenance_linkage_is_preserved(self) -> None:
        dossier = _dossier()
        dossier["source_hash"] = "d" * 64
        result = self._validate(self._directive(), revised_dossier=dossier)
        self.assertFalse(result["valid"])
        self.assertIn(
            "revision_provenance_mismatch",
            {item["code"] for item in result["diagnostics"]},
        )

    def test_symlink_or_escape_target_is_rejected_when_supported(self) -> None:
        target_path = self.repo_root / self.target["path"]
        outside = self.repo_root / "outside"
        outside.mkdir()
        moved = self.repo_root / "moved_target"
        target_path.rename(moved)
        try:
            os.symlink(moved, target_path)
        except (AttributeError, OSError):
            moved.rename(target_path)
            self.skipTest("symlink creation is unavailable")
        result = self._validate(self._directive())
        self.assertFalse(result["valid"])
        self.assertTrue(
            any(
                item["code"] in {"staging_target_not_reserved", "rebuild_target_invalid"}
                for item in result["diagnostics"]
            )
        )

    def test_target_identity_mismatch_is_rejected(self) -> None:
        directive = self._directive()
        directive["target"]["revision_number"] = 2
        directive["target"]["stage_id"] = directive["target"]["stage_id"].replace(
            "revision_001", "revision_002"
        )
        result = self._validate(directive)
        self.assertFalse(result["valid"])
        self.assertIn(
            "staging_target_not_reserved",
            {item["code"] for item in result["diagnostics"]},
        )

    def test_deterministic_output_and_no_mutation(self) -> None:
        directive = self._directive()
        original = copy.deepcopy(directive)
        first = self._validate(directive)
        second = self._validate(directive)
        self.assertEqual(
            json.dumps(first, sort_keys=True, separators=(",", ":")),
            json.dumps(second, sort_keys=True, separators=(",", ":")),
        )
        self.assertEqual(directive, original)


class TestAdaptationAuditorIntegration(unittest.TestCase):
    def test_response_parser_can_attach_strict_rebuild_plan(self) -> None:
        packet = _packet()
        with tempfile.TemporaryDirectory(
            dir=str(Path(__file__).resolve().parents[1] / "tmp")
        ) as directory:
            repo_root = Path(directory)
            target = create_adaptation_staging_target(
                SOURCE_HASH,
                attempt_id=packet["attempt_id"],
                attempt_number=packet["attempt_number"],
                revision_number=1,
                staging_root="tmp/adaptation-staging",
                repo_root=repo_root,
            )
            response = _base_response(packet, AUDITOR_DECISION_REVISE)
            response["rebuild_directive"] = {
                "action": "fresh_build",
                "target": {
                    "target_kind": "staging",
                    "stage_id": target["stage_id"],
                    "attempt_id": target["attempt_id"],
                    "attempt_number": target["attempt_number"],
                    "revision_number": target["revision_number"],
                    "source_hash": target["source_hash"],
                },
                "basis": "revised_dossier",
                "scope": "semantic",
                "reason": "Keep the canonical playable destination.",
                "constraints": ["Use only bounded adaptation guidance."],
            }
            result = parse_adaptation_auditor_response(
                json.dumps(response, sort_keys=True, separators=(",", ":")),
                packet,
                staging_target=target,
                repo_root=repo_root,
            )
            self.assertTrue(result["valid"], result["diagnostics"])
            self.assertEqual(result["rebuild_plan"]["revision_number"], 1)

    def test_legacy_final_reconciliation_patch_contract_remains_separate(self) -> None:
        self.assertEqual(
            FINAL_RECONCILIATION_PATCH_VERSION,
            "accurate_ingest_final_reconciliation_patch.v1",
        )
        valid, diagnostics = validate_final_reconciliation_patch_contract(
            {
                "version": FINAL_RECONCILIATION_PATCH_VERSION,
                "status": "ready",
                "source_fidelity_claim": "reconciled_degraded",
                "publication_intent": "reconciliation_only",
                "decisions": [],
                "file_patches": [],
            }
        )
        self.assertTrue(valid, diagnostics)
        self.assertNotEqual(
            ADAPTATION_REBUILD_DIRECTIVE_CONTRACT_VERSION,
            FINAL_RECONCILIATION_PATCH_VERSION,
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
