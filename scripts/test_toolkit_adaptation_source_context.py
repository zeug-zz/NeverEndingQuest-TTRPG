# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-free tests for bounded adaptation source-context assembly."""

import inspect
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.toolkit_adaptation_source_context import (
    ASSEMBLY_STATUS_INVALID,
    MAX_CONTEXT_SERIALIZED_CHARS,
    MAX_RAW_SOURCE_CHARS,
    MAX_SOURCE_SUMMARY_CHARS,
    build_adaptation_source_context,
    serialize_adaptation_source_context,
)
from utils.toolkit_source_manifest import build_source_manifest


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = REPO_ROOT / "scripts" / "fixtures"
CATALOGUE_PATH = FIXTURE_DIR / "toolkit_adaptation_catalogue.md"
ROOMS_PATH = FIXTURE_DIR / "toolkit_adaptation_rooms.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TestAdaptationSourceContext(unittest.TestCase):
    """Source evidence is bounded, typed, and advisory."""

    def test_catalogue_and_room_fixtures_select_distinct_profiles(self) -> None:
        catalogue = _read(CATALOGUE_PATH)
        rooms = _read(ROOMS_PATH)

        catalogue_context = build_adaptation_source_context(
            catalogue,
            source_path="scripts/fixtures/toolkit_adaptation_catalogue.md",
        )
        room_context = build_adaptation_source_context(
            rooms,
            source_path="scripts/fixtures/toolkit_adaptation_rooms.md",
        )

        self.assertEqual(catalogue_context["source_profile"], "catalogue")
        self.assertEqual(room_context["source_profile"], "adventure")
        self.assertNotEqual(
            catalogue_context["source_profile"], room_context["source_profile"]
        )
        self.assertIn("do not promote item headings", catalogue_context["profile_guidance"])
        self.assertIn("room or scene progression", room_context["profile_guidance"].lower())
        self.assertEqual(catalogue_context["assembly_status"], "ready")
        self.assertEqual(room_context["assembly_status"], "ready")
        self.assertEqual(
            catalogue_context,
            build_adaptation_source_context(
                catalogue,
                source_path="scripts/fixtures/toolkit_adaptation_catalogue.md",
            ),
        )

    def test_valid_override_is_preserved_and_invalid_override_fails_safely(self) -> None:
        catalogue = _read(CATALOGUE_PATH)
        overridden = build_adaptation_source_context(
            catalogue,
            source_path="scripts/fixtures/toolkit_adaptation_catalogue.md",
            profile_override="location",
        )
        self.assertEqual(overridden["source_profile"], "location")
        self.assertEqual(overridden["source_profile_source"], "explicit_override")

        invalid = build_adaptation_source_context(
            catalogue,
            source_path="scripts/fixtures/toolkit_adaptation_catalogue.md",
            profile_override="catalog",
        )
        self.assertEqual(invalid["assembly_status"], ASSEMBLY_STATUS_INVALID)
        self.assertIsNone(invalid["source_profile"])
        self.assertIn(
            "source_profile_override_invalid",
            {item["code"] for item in invalid["diagnostics"]},
        )

    def test_summary_precedes_raw_excerpt_and_merges_manifest_and_packet(self) -> None:
        raw = "# Source Title\nA raw source body that is intentionally different."
        manifest = build_source_manifest(raw, "scripts/fixtures/source.md")
        packet = {
            "title": "Packet Title",
            "adventure_summary": "Packet summary should not replace the explicit summary.",
            "module_tone": "Mysterious market fantasy",
            "locations": [{"name": "Packet Place", "purpose": "Optional evidence."}],
            "item_seeds": [{"name": "Packet Item", "purpose": "Optional evidence."}],
        }
        context = build_adaptation_source_context(
            raw,
            source_summary={
                "source_title": "Summary Title",
                "summary": "Explicit bounded summary wins over packet summary.",
                "section_summaries": [
                    {"heading": "Overview", "summary": "A compact section summary."}
                ],
            },
            source_manifest=manifest,
            normalized_packet=packet,
            source_path="scripts/fixtures/source.md",
        )

        kinds = [item["kind"] for item in context["source_inputs"]]
        self.assertEqual(context["source_title"], "Summary Title")
        self.assertIn("source_summary", kinds)
        self.assertIn("raw_source_excerpt", kinds)
        self.assertIn("source_manifest", kinds)
        self.assertIn("normalized_packet", kinds)
        summary_record = next(
            item for item in context["source_inputs"] if item["kind"] == "source_summary"
        )
        self.assertIn("Explicit bounded summary", summary_record["text"])
        self.assertNotIn("Packet summary should", summary_record["text"])
        self.assertEqual(context["source_ref"]["path"], "scripts/fixtures/source.md")
        self.assertTrue(context["source_ref"]["sha256"])

    def test_per_input_and_total_bounds_are_deterministic(self) -> None:
        raw = "Room 1: " + ("raw source " * 20_000)
        summary = "summary " * 10_000
        manifest = {
            "manifest_version": "fixture-manifest.v1",
            "source_hash": "a" * 64,
            "headings": [
                {"text": f"Heading {index}", "line_start": index + 1}
                for index in range(200)
            ],
            "item_candidates": [
                {
                    "cue": f"Item {index}",
                    "context": "item context " * 40,
                    "line_start": index + 1,
                }
                for index in range(200)
            ],
        }
        context = build_adaptation_source_context(
            raw,
            source_summary=summary,
            source_manifest=manifest,
            source_hash="a" * 64,
            source_path="scripts/fixtures/large_source.md",
        )
        encoded = serialize_adaptation_source_context(context)
        self.assertLessEqual(len(encoded), MAX_CONTEXT_SERIALIZED_CHARS)
        self.assertTrue(context["truncation"]["truncated"])
        self.assertEqual(len(encoded), context["truncation"]["serialized_chars"])
        self.assertLessEqual(
            next(
                item["included_chars"]
                for item in context["source_inputs"]
                if item["kind"] == "raw_source_excerpt"
            ),
            MAX_RAW_SOURCE_CHARS,
        )
        self.assertLessEqual(
            next(
                item["included_chars"]
                for item in context["source_inputs"]
                if item["kind"] == "source_summary"
            ),
            MAX_SOURCE_SUMMARY_CHARS,
        )

    def test_invalid_references_and_sensitive_prompt_fields_are_not_embedded(self) -> None:
        context = build_adaptation_source_context(
            "# Safe Source\napi_key=super-secret-value",
            source_summary={
                "summary": "Safe summary",
                "system_prompt": "Do not include this uncontrolled prompt.",
                "source_path": "/private/secret/source.md",
            },
            source_path="/private/secret/source.md",
        )
        encoded = serialize_adaptation_source_context(context)
        self.assertNotIn("super-secret-value", encoded)
        self.assertNotIn("uncontrolled prompt", encoded)
        self.assertNotIn("/private/secret", encoded)
        self.assertNotIn("path", context["source_ref"] or {})
        self.assertIn(
            "source_reference_omitted",
            {item["code"] for item in context["diagnostics"]},
        )

    def test_atoms_are_advisory_and_never_promoted_to_required_output(self) -> None:
        source_graph = {
            "graph_version": "fixture-graph.v1",
            "source_hash": "b" * 64,
            "atoms": [
                {
                    "type": "item",
                    "name": "Heading Item",
                    "summary": "An optional item clue.",
                    "criticality": "required",
                },
                {
                    "type": "location",
                    "name": "Optional Room",
                    "summary": "An optional place clue.",
                },
            ],
        }
        context = build_adaptation_source_context(
            "# Catalogue\n## Heading Item\nA listing.",
            source_graph=source_graph,
            source_hash="b" * 64,
            source_path="scripts/fixtures/catalogue.md",
        )
        policy = context["atom_policy"]
        self.assertTrue(policy["source_atoms_are_advisory"])
        self.assertEqual(policy["required_output_fields"], [])
        self.assertTrue(policy["may_omit"])
        self.assertTrue(policy["may_reinterpret"])
        graph = next(
            item for item in context["source_inputs"] if item["kind"] == "source_graph"
        )
        self.assertTrue(all(item["advisory"] for item in graph["evidence"]))
        self.assertNotIn('"criticality":"required"', json.dumps(context, sort_keys=True))

    def test_context_assembler_is_provider_free(self) -> None:
        source = inspect.getsource(sys.modules["utils.toolkit_adaptation_source_context"])
        self.assertNotIn("create_chat_client", source)
        self.assertNotIn("requests.", source)
        self.assertNotIn("OPENAI_API_KEY", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
