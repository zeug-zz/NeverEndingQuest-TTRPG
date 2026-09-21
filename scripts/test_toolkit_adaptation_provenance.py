# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair Source 1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free regression tests for adaptation provenance surfaces."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.homebrewery_adventure_writer import _build_credits
from utils.toolkit_adaptation_dossier import ADAPTATION_NOTICE
from utils.toolkit_adaptation_provenance import (
    SOURCE_FIDELITY_NON_LITERAL,
    SOURCE_FIDELITY_NOT_APPLICABLE,
    build_adaptation_provenance,
    persist_adaptation_module_provenance,
    render_adaptation_provenance_markdown,
    validate_adaptation_provenance,
)
from web.extensions.toolkit_module_finisher import (
    _build_adaptation_finishing_report,
    _run_adaptation_provenance_stage,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = REPO_ROOT / "scripts" / "fixtures" / "toolkit_adaptation_dossier_valid.json"
SOURCE_HASH = "a" * 64
WORLD_SEED_HASH = "b" * 64
WORLD_CONTEXT_HASH = "c" * 64


def _dossier() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _world_context() -> dict:
    return {
        "context_status": "available",
        "context_version": "world-context.v1",
        "context_hash": WORLD_CONTEXT_HASH,
        "world_seed_status": "available",
        "world_seed_version": "seed.v7",
        "world_seed_hash": WORLD_SEED_HASH,
        "selected_module": "The_Ancients_Lab",
    }


def _provenance_input() -> dict:
    return {
        "source_hash": SOURCE_HASH,
        "source_path": "scripts/fixtures/toolkit_adaptation_catalogue.md",
        "attempt_id": "adaptation-provenance-1",
        "attempt_number": 1,
        "revision_number": 0,
        "model_metadata": {
            "provider": "fixture",
            "model": "gpt-5.6-luna",
            "reasoning_effort": "medium",
            "prompt_contract": "toolkit_adaptation_dossier.v1",
        },
    }


class TestAdaptationProvenanceContract(unittest.TestCase):
    """The canonical envelope is bounded and honest about fidelity."""

    def test_canonical_envelope_contains_required_surface_fields(self) -> None:
        dossier = _dossier()
        dossier["source_hash"] = SOURCE_HASH
        provenance = build_adaptation_provenance(
            dossier=dossier,
            provenance=_provenance_input(),
            world_context=_world_context(),
            module_slug="Lantern_Market",
        )

        self.assertEqual(provenance["adaptation_notice"], ADAPTATION_NOTICE)
        self.assertEqual(provenance["source_hash"], SOURCE_HASH)
        self.assertEqual(provenance["rights_classification"], "user_authored")
        self.assertEqual(provenance["adaptation_status"], "adapted")
        self.assertEqual(provenance["model_metadata"]["model"], "gpt-5.6-luna")
        self.assertEqual(provenance["world_seed_version"], "seed.v7")
        self.assertEqual(provenance["world_seed_hash"], WORLD_SEED_HASH)
        self.assertEqual(provenance["world_context_hash"], WORLD_CONTEXT_HASH)
        self.assertEqual(provenance["source_fidelity_status"], SOURCE_FIDELITY_NOT_APPLICABLE)
        self.assertEqual(provenance["literal_source_fidelity"], SOURCE_FIDELITY_NOT_APPLICABLE)
        self.assertEqual(provenance["fidelity_claim"], SOURCE_FIDELITY_NON_LITERAL)

        validation = validate_adaptation_provenance(
            provenance,
            require_source_identity=True,
        )
        self.assertTrue(validation["valid"], validation["diagnostics"])

        try:
            from jsonschema import Draft7Validator

            schema = json.loads(
                (REPO_ROOT / "schemas" / "toolkit_adaptation_provenance_schema.json").read_text(
                    encoding="utf-8"
                )
            )
        except ImportError:
            self.skipTest("jsonschema is unavailable")
        errors = list(Draft7Validator(schema).iter_errors(provenance))
        self.assertEqual(errors, [])

    def test_canonical_generation_provenance_requires_exact_operator_true(self) -> None:
        dossier = _dossier()
        dossier["source_hash"] = SOURCE_HASH
        for value in (False, None, "true", 1, 0, 1.5, [], {}):
            with self.subTest(value=repr(value)), patch(
                "model_config.ENABLE_LLM_ADAPTATION_CANONICAL_MONSTER_GENERATION",
                value,
            ):
                provenance = build_adaptation_provenance(dossier=dossier)
                self.assertNotIn(
                    "allow_canonical_monster_generation",
                    provenance,
                )
        with patch(
            "model_config.ENABLE_LLM_ADAPTATION_CANONICAL_MONSTER_GENERATION",
            True,
        ):
            provenance = build_adaptation_provenance(dossier=dossier)
        self.assertIs(provenance["allow_canonical_monster_generation"], True)

    def test_canonical_generation_values_validate_as_optional_boolean(self) -> None:
        try:
            from jsonschema import Draft7Validator

            schema = json.loads(
                (REPO_ROOT / "schemas" / "toolkit_adaptation_provenance_schema.json").read_text(
                    encoding="utf-8"
                )
            )
        except ImportError:
            self.skipTest("jsonschema is unavailable")

        dossier = _dossier()
        dossier["source_hash"] = SOURCE_HASH
        with patch(
            "model_config.ENABLE_LLM_ADAPTATION_CANONICAL_MONSTER_GENERATION",
            True,
        ):
            enabled = build_adaptation_provenance(dossier=dossier)
        disabled = dict(enabled)
        disabled["allow_canonical_monster_generation"] = False
        omitted = dict(enabled)
        omitted.pop("allow_canonical_monster_generation")

        for value, payload in (
            (True, enabled),
            (False, disabled),
            ("omitted", omitted),
        ):
            with self.subTest(value=value):
                errors = list(Draft7Validator(schema).iter_errors(payload))
                self.assertEqual(errors, [])

    def test_markdown_provenance_is_explicit_without_raw_json_or_literal_claim(self) -> None:
        dossier = _dossier()
        dossier["source_hash"] = SOURCE_HASH
        provenance = build_adaptation_provenance(
            dossier=dossier,
            provenance=_provenance_input(),
            world_context=_world_context(),
        )

        markdown = render_adaptation_provenance_markdown(provenance)

        self.assertIn("**Adapted for NEQ-TTRPG**", markdown)
        self.assertIn(SOURCE_HASH, markdown)
        self.assertIn("user_authored", markdown)
        self.assertIn("adapted", markdown)
        self.assertIn("gpt-5.6-luna", markdown)
        self.assertIn("seed.v7 / " + WORLD_SEED_HASH, markdown)
        self.assertIn("not applicable", markdown.lower())
        self.assertNotIn('"source_hash"', markdown)
        self.assertNotIn("literal source fidelity: pass", markdown.lower())

    def test_credits_use_the_same_provenance_renderer(self) -> None:
        dossier = _dossier()
        dossier["source_hash"] = SOURCE_HASH
        provenance = build_adaptation_provenance(
            dossier=dossier,
            provenance=_provenance_input(),
            world_context=_world_context(),
        )
        data = {
            "author": "",
            "license": "",
            "adaptation_provenance": provenance,
        }

        credits = _build_credits(data, adaptation_notice=True)

        self.assertIn(ADAPTATION_NOTICE, credits)
        self.assertIn(SOURCE_HASH, credits)
        self.assertIn(WORLD_SEED_HASH, credits)
        self.assertIn("non-literal adaptation", credits)


class TestAdaptationProvenancePersistence(unittest.TestCase):
    """Module and report surfaces receive identical bounded metadata."""

    def test_module_context_and_finishing_report_receive_provenance(self) -> None:
        with tempfile.TemporaryDirectory(
            dir=str(REPO_ROOT / "tmp"), prefix="toolkit_adaptation_provenance_"
        ) as temp_dir:
            module_dir = Path(temp_dir) / "Lantern_Market"
            module_dir.mkdir(parents=True, exist_ok=True)
            context = {"moduleName": "Lantern Market", "npcs": {}}
            (module_dir / "module_context.json").write_text(
                json.dumps(context), encoding="utf-8"
            )
            (module_dir / "module_context_BU.json").write_text(
                json.dumps(context), encoding="utf-8"
            )

            dossier = _dossier()
            dossier["source_hash"] = SOURCE_HASH
            provenance = build_adaptation_provenance(
                dossier=dossier,
                provenance=_provenance_input(),
                world_context=_world_context(),
                module_slug="Lantern_Market",
            )
            stage = _run_adaptation_provenance_stage(
                module_slug="Lantern_Market",
                module_dir=module_dir,
                adaptation_provenance=provenance,
                adaptation_gates={
                    "source_fidelity_report": {
                        "source_fidelity_status": "not_applicable",
                        "adaptation_mode": "llm_adaptation",
                    }
                },
            )

            self.assertEqual(stage["status"], "success")
            for filename in ("module_context.json", "module_context_BU.json"):
                payload = json.loads((module_dir / filename).read_text(encoding="utf-8"))
                self.assertEqual(payload["adaptation_provenance"], provenance)
                self.assertEqual(payload["source_hash"], SOURCE_HASH)
                self.assertEqual(payload["rights_classification"], "user_authored")
                self.assertEqual(payload["world_seed_hash"], WORLD_SEED_HASH)

            source_report = json.loads(
                (module_dir / "source_fidelity_report.json").read_text(encoding="utf-8")
            )
            self.assertEqual(source_report["adaptation_provenance"], provenance)
            self.assertEqual(source_report["source_fidelity_status"], "not_applicable")
            self.assertEqual(source_report["fidelity_claim"], SOURCE_FIDELITY_NON_LITERAL)

            report = _build_adaptation_finishing_report(
                module_slug="Lantern_Market",
                module_dir=module_dir,
                stages={"adaptation_provenance": stage},
                status="success",
                adaptation_provenance=provenance,
            )
            self.assertEqual(report["adaptation_provenance"], provenance)
            self.assertEqual(report["adaptation_notice"], ADAPTATION_NOTICE)
            self.assertEqual(report["source_hash"], SOURCE_HASH)
            self.assertEqual(report["adaptation_status"], "adapted")
            self.assertEqual(report["world_seed_version"], "seed.v7")
            self.assertEqual(report["source_fidelity_status"], "not_applicable")
            self.assertEqual(report["fidelity_claim"], SOURCE_FIDELITY_NON_LITERAL)


if __name__ == "__main__":
    unittest.main(verbosity=2)
