# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.

"""Provider-free adaptation semantic-authority regression tests."""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from utils.toolkit_adaptation_semantic_authority import (
    build_adaptation_semantic_authority,
    persist_adaptation_semantic_authority,
)
from utils.toolkit_adaptation_staging import create_adaptation_staging_target


class AdaptationSemanticAuthorityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(dir="tmp", prefix="adapt_semantic_")
        self.root = Path(self.temp.name)
        self.module = self.root / "Adapted_Module"
        (self.module / "areas").mkdir(parents=True)
        self._write("module_context.json", {"module_name": "Adapted_Module", "npcs": {}})
        self._write("module_plot.json", {"plotPoints": []})

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write(self, name: str, payload: dict) -> None:
        path = self.module / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    def _area(self, locations: list, area_id: str = "A001", filename: str = "A001.json") -> None:
        self._write(f"areas/{filename}", {"areaId": area_id, "locations": locations})

    def _attempt(self, source_hash: str = "a" * 64) -> dict:
        return {"attempt_id": "attempt-1", "attempt_number": 1, "revision_number": 3, "source_hash": source_hash}

    def test_complete_current_authority_and_unique_moonlit_alias(self) -> None:
        self._area([{"locationId": "LOC01", "name": "Moonlit Shrine", "aliases": []}])
        manifest = {"source_hash": "a" * 64, "location_candidates": []}
        packet = {"source_hash": "a" * 64, "destination_phrases": ["moonlit-shrine"]}
        result = build_adaptation_semantic_authority("Adapted_Module", self.module, attempt=self._attempt(), source_manifest=manifest, normalized_packet=packet)
        self.assertEqual(result["status"], "success")
        authority = result["semantic_authority"]
        self.assertEqual(authority["destination_phrases"]["moonlit shrine"]["location_id"], "LOC01")
        self.assertEqual(authority["location_index"]["LOC01"]["location_id"], "LOC01")
        self.assertEqual(authority["attempt"]["revision_number"], 3)
        self.assertEqual(authority["adaptation_provenance"]["mode"], "llm_adaptation")
        self.assertIn("normalized_packet", authority["adaptation_provenance"]["normalized_packet_evidence"][0])
        persisted = persist_adaptation_semantic_authority(self.module, result)
        self.assertEqual(persisted["status"], "persisted")
        saved = json.loads((self.module / "module_context.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["semantic_authority"]["attempt"]["attempt_id"], "attempt-1")

    def test_unresolved_and_ambiguous_phrases_are_blockers(self) -> None:
        self._area([
            {"locationId": "LOC01", "name": "North Hall", "aliases": ["shared hall"]},
            {"locationId": "LOC02", "name": "South Hall", "aliases": ["shared hall"]},
        ])
        self._write("module_plot.json", {"plotPoints": [{"id": "P1", "title": "Go to unknown shrine", "description": "Return to the shared hall."}]})
        result = build_adaptation_semantic_authority("Adapted_Module", self.module, attempt=self._attempt(), source_manifest={"source_hash": "a" * 64}, normalized_packet={"source_hash": "a" * 64})
        codes = {row["code"] for row in result["blockers"]}
        self.assertIn("ambiguous_destination_phrase", codes)
        self.assertIn("unresolved_destination_phrase", codes)

    def test_alias_seed_does_not_create_token_window_blockers(self) -> None:
        self._area([
            {
                "locationId": "LOC01",
                "name": "Central Square",
                "aliases": ["The Empty Village Road Square"],
            }
        ])
        result = build_adaptation_semantic_authority(
            "Adapted_Module",
            self.module,
            attempt=self._attempt(),
            source_manifest={"source_hash": "a" * 64},
            normalized_packet={"source_hash": "a" * 64},
        )
        authority = result["semantic_authority"]
        aliases = authority["location_aliases"]
        self.assertEqual(
            aliases["the empty village road square"]["location_id"], "LOC01"
        )
        self.assertTrue(
            any(".aliases" in source for source in aliases["the empty village road square"]["sources"])
        )
        self.assertEqual(
            aliases["the empty village road square"]["candidate_location_ids"],
            ["LOC01"],
        )
        self.assertEqual(
            aliases["the empty village road square"]["candidate_internal_location_ids"],
            ["LOC01"],
        )
        unresolved = {
            row["phrase"]
            for row in authority["diagnostics"]["unresolved_destination_phrases"]
        }
        self.assertNotIn("empty village road", unresolved)
        self.assertNotIn("village road", unresolved)

    def test_independent_prose_window_remains_unresolved(self) -> None:
        self._area([
            {
                "locationId": "LOC01",
                "name": "Central Square",
                "aliases": ["The Empty Village Road Square"],
            }
        ])
        self._write(
            "module_plot.json",
            {"plotPoints": [{"id": "P1", "title": "Travel to the village road"}]},
        )
        result = build_adaptation_semantic_authority(
            "Adapted_Module",
            self.module,
            attempt=self._attempt(),
            source_manifest={"source_hash": "a" * 64},
            normalized_packet={"source_hash": "a" * 64},
        )
        unresolved = {
            row["phrase"]
            for row in result["semantic_authority"]["diagnostics"]["unresolved_destination_phrases"]
        }
        self.assertIn("village road", unresolved)
        authority = result["semantic_authority"]
        village_road = authority["destination_phrases"]["village road"]
        self.assertEqual(village_road["status"], "unresolved")
        self.assertTrue(village_road["player_facing"])
        self.assertIn(
            "module_plot.json#plotPoints[P1].title",
            village_road["sources"],
        )

    def test_duplicate_raw_ids_use_area_scoped_identity_and_provenance(self) -> None:
        self._area(
            [{
                "locationId": "K01",
                "name": "Evergreen Keep",
                "aliases": ["Evergreen Gate"],
                "npcs": ["Keeper Evra"],
            }],
            area_id="EVR001",
            filename="EVR001.json",
        )
        self._area(
            [{
                "locationId": "K01",
                "name": "Frost Cathedral",
                "description": "Keeper Evra watches the frozen nave.",
                "aliases": ["Frost Gate"],
                "npcs": ["Keeper Fara"],
            }],
            area_id="FC001",
            filename="FC001.json",
        )
        self._write(
            "module_context.json",
            {
                "module_name": "Adapted_Module",
                "npcs": {"keeper_evra": {}, "keeper_fara": {}},
            },
        )
        self._write(
            "module_plot.json",
            {
                "plotPoints": [
                    {"id": "P-EVR", "title": "Travel to EVR001:K01"},
                    {"id": "P-FC", "title": "Travel to FC001:K01"},
                    {"id": "P-RAW", "title": "Travel to K01"},
                ]
            },
        )
        result = build_adaptation_semantic_authority(
            "Adapted_Module",
            self.module,
            attempt=self._attempt(),
            source_manifest={"source_hash": "a" * 64},
            normalized_packet={"source_hash": "a" * 64},
        )
        authority = result["semantic_authority"]
        aliases = authority["location_aliases"]

        self.assertEqual(aliases["evergreen keep"]["location_id"], "K01")
        self.assertEqual(aliases["evergreen keep"]["scoped_location_id"], "EVR001:K01")
        self.assertEqual(aliases["evergreen keep"]["raw_location_id"], "K01")
        self.assertEqual(aliases["frost gate"]["location_id"], "K01")
        self.assertEqual(aliases["frost gate"]["scoped_location_id"], "FC001:K01")
        self.assertEqual(aliases["evr001 k01"]["location_id"], "K01")
        self.assertEqual(aliases["evr001 k01"]["scoped_location_id"], "EVR001:K01")
        self.assertEqual(aliases["fc001 k01"]["location_id"], "K01")
        self.assertEqual(aliases["fc001 k01"]["scoped_location_id"], "FC001:K01")
        self.assertEqual(
            aliases["k01"]["status"],
            "ambiguous",
        )
        self.assertEqual(
            aliases["k01"]["candidate_location_ids"],
            ["K01"],
        )
        self.assertEqual(
            aliases["k01"]["candidate_internal_location_ids"],
            ["EVR001:K01", "FC001:K01"],
        )
        destinations = authority["destination_phrases"]
        for phrase, scoped_id in (
            ("evr001 k01", "EVR001:K01"),
            ("fc001 k01", "FC001:K01"),
        ):
            self.assertEqual(destinations[phrase]["status"], "resolved")
            self.assertEqual(destinations[phrase]["location_id"], "K01")
            self.assertEqual(destinations[phrase]["scoped_location_id"], scoped_id)
            self.assertEqual(destinations[phrase]["candidate_location_ids"], ["K01"])
            self.assertEqual(
                destinations[phrase]["candidate_internal_location_ids"], [scoped_id]
            )
            self.assertTrue(
                any(scoped_id in source for source in destinations[phrase]["sources"])
            )
        self.assertEqual(destinations["k01"]["status"], "ambiguous")
        self.assertEqual(destinations["k01"]["candidate_location_ids"], ["K01"])
        self.assertEqual(
            destinations["k01"]["candidate_internal_location_ids"],
            ["EVR001:K01", "FC001:K01"],
        )
        self.assertTrue(
            any(
                row.get("phrase") == "k01"
                for row in authority["diagnostics"]["ambiguous_destination_phrases"]
            )
        )
        self.assertEqual(
            authority["location_index"]["EVR001:K01"]["location_id"], "K01"
        )
        self.assertEqual(
            authority["location_index"]["FC001:K01"]["area_id"], "FC001"
        )
        npc_authority = authority["npc_scene_authority"]
        self.assertEqual(
            npc_authority["keeper evra"]["visible_location_ids"], ["K01"]
        )
        self.assertEqual(
            npc_authority["keeper evra"]["visible_scoped_location_ids"], ["EVR001:K01"]
        )
        self.assertEqual(
            npc_authority["keeper fara"]["visible_location_ids"], ["K01"]
        )
        self.assertEqual(
            npc_authority["keeper fara"]["visible_scoped_location_ids"], ["FC001:K01"]
        )
        self.assertTrue(
            any(
                binding["location_id"] == "K01"
                and binding["scoped_location_id"] == "FC001:K01"
                and "FC001.json#locations[FC001:K01].description" in binding["source"]
                for binding in npc_authority["keeper evra"]["reveal_bindings"]
            )
        )

    def test_shortform_anchor_preserves_raw_scoped_and_source_provenance(self) -> None:
        self._area(
            [{
                "locationId": "K01",
                "name": "Serpents Remnant Sanctuary",
                "aliases": ["Serpents Remnant Sanctuary"],
                "npcs": [],
            }],
            area_id="EVR001",
            filename="EVR001.json",
        )
        self._area(
            [{
                "locationId": "K01",
                "name": "Frozen Archive",
                "aliases": ["Frozen Archive"],
                "npcs": [],
            }],
            area_id="FC001",
            filename="FC001.json",
        )
        self._write(
            "module_plot.json",
            {"plotPoints": [{"id": "P1", "title": "Travel to the remnant sanctuary"}]},
        )
        result = build_adaptation_semantic_authority(
            "Adapted_Module",
            self.module,
            attempt=self._attempt(),
            source_manifest={"source_hash": "a" * 64},
            normalized_packet={"source_hash": "a" * 64},
        )
        authority = result["semantic_authority"]
        shortform = authority["destination_phrases"]["remnant sanctuary"]
        self.assertEqual(shortform["status"], "resolved")
        self.assertEqual(shortform["location_id"], "K01")
        self.assertEqual(shortform["scoped_location_id"], "EVR001:K01")
        self.assertEqual(shortform["candidate_location_ids"], ["K01"])
        self.assertEqual(shortform["candidate_internal_location_ids"], ["EVR001:K01"])
        self.assertEqual(
            shortform["normalization"]["anchor_phrase"],
            "serpents remnant sanctuary",
        )
        self.assertEqual(
            shortform["normalization"]["anchor_scoped_location_id"],
            "EVR001:K01",
        )
        self.assertIn(
            "module_plot.json#plotPoints[P1].title",
            shortform["sources"],
        )

    def test_globally_unique_raw_ids_retain_legacy_outputs(self) -> None:
        self._area(
            [{"locationId": "A01", "name": "Moonlit Shrine", "aliases": ["Moonlit Shrine"]}],
            area_id="EVR001",
            filename="EVR001.json",
        )
        self._area(
            [{"locationId": "B01", "name": "Frost Cathedral", "aliases": ["Frost Cathedral"]}],
            area_id="FC001",
            filename="FC001.json",
        )
        result = build_adaptation_semantic_authority(
            "Adapted_Module",
            self.module,
            attempt=self._attempt(),
            source_manifest={"source_hash": "a" * 64},
            normalized_packet={"source_hash": "a" * 64},
        )
        authority = result["semantic_authority"]
        for raw_id in ("A01", "B01"):
            self.assertIn(raw_id, authority["location_index"])
            self.assertEqual(authority["location_index"][raw_id]["location_id"], raw_id)
            self.assertEqual(authority["location_index"][raw_id]["scoped_location_id"], raw_id)
        for phrase, raw_id in (("moonlit shrine", "A01"), ("frost cathedral", "B01")):
            row = authority["location_aliases"][phrase]
            self.assertEqual(row["location_id"], raw_id)
            self.assertEqual(row["scoped_location_id"], raw_id)
            self.assertEqual(row["candidate_location_ids"], [raw_id])
            self.assertEqual(row["candidate_internal_location_ids"], [raw_id])

    def test_missing_authority_and_stale_identity_rejected(self) -> None:
        result = build_adaptation_semantic_authority("Adapted_Module", self.module, attempt=self._attempt(), source_manifest={"source_hash": "b" * 64}, normalized_packet={"source_hash": "a" * 64})
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["blockers"][0]["code"], "stale_or_missing_authority_input")
        self.assertEqual(persist_adaptation_semantic_authority(self.module, result)["status"], "blocked")

    def test_legacy_mode_is_not_applicable_and_does_not_write(self) -> None:
        self.assertFalse((self.root / "modules").exists())
        self._area([{"locationId": "LOC01", "name": "Moonlit Shrine"}])
        result = build_adaptation_semantic_authority("Adapted_Module", self.module, attempt=self._attempt(), source_manifest={"source_hash": "a" * 64}, normalized_packet={"source_hash": "a" * 64})
        self.assertNotIn("semantic_authority", json.loads((self.module / "module_context.json").read_text(encoding="utf-8")))
        legacy = build_adaptation_semantic_authority("Adapted_Module", self.module, attempt=self._attempt(), source_manifest={"source_hash": "a" * 64}, normalized_packet={"source_hash": "a" * 64}, mode="legacy_modulebuilder")
        self.assertEqual(legacy["status"], "not_applicable")
        self.assertEqual(persist_adaptation_semantic_authority(self.module, legacy)["status"], "not_applicable")
        self.assertNotIn("semantic_authority", json.loads((self.module / "module_context.json").read_text(encoding="utf-8")))

    def test_staging_only_write_is_explicit(self) -> None:
        self._area([{"locationId": "LOC01", "name": "Moonlit Shrine"}])
        result = build_adaptation_semantic_authority("Adapted_Module", self.module, attempt=self._attempt(), source_manifest={"source_hash": "a" * 64}, normalized_packet={"source_hash": "a" * 64})
        self.assertEqual(persist_adaptation_semantic_authority(self.module, result)["status"], "persisted")
        self.assertFalse((self.root / "modules").exists())

    def test_current_staging_recompute_is_identity_bound_and_live_safe(self) -> None:
        """Recompute the current staging report without touching publication state."""
        source_hash = "c" * 64
        target = create_adaptation_staging_target(
            source_hash,
            attempt_id="adapt-7-4",
            attempt_number=7,
            revision_number=2,
            module_slug="Adapted_Module",
            repo_root=self.root,
            staging_root="staging",
        )
        staging_module = self.root / target["path"]
        (staging_module / "areas").mkdir(parents=True, exist_ok=True)
        (staging_module / "module_context.json").write_text(
            json.dumps({
                "module_name": "Adapted_Module",
                "npcs": {},
            }),
            encoding="utf-8",
        )
        (staging_module / "module_plot.json").write_text(
            json.dumps({
                "plotPoints": [
                    {"id": "P1", "title": "Travel to the village road"},
                ],
            }),
            encoding="utf-8",
        )
        (staging_module / "areas" / "EVR001.json").write_text(
            json.dumps({
                "areaId": "EVR001",
                "locations": [{
                    "locationId": "K01",
                    "name": "Central Square",
                    "aliases": ["The Empty Village Road Square"],
                }],
            }),
            encoding="utf-8",
        )

        protected = {
            self.root / "modules" / "Live_Module" / "module_context.json": b"live-module-sentinel",
            self.root / "modules" / "world_registry.json": b"registry-sentinel",
            self.root / "modules" / "campaign.json": b"campaign-sentinel",
            self.root / "data" / "runtime" / "runtime-sentinel.json": b"runtime-sentinel",
        }
        for path, content in protected.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        before = {path: path.read_bytes() for path in protected}

        attempt = {
            "attempt_id": target["attempt_id"],
            "attempt_number": target["attempt_number"],
            "revision_number": target["revision_number"],
            "source_hash": target["source_hash"],
        }
        manifest = {
            **attempt,
            "module_slug": "Adapted_Module",
            "location_candidates": [],
        }
        packet = {
            **attempt,
            "module_slug": "Adapted_Module",
            "destination_phrases": ["The Empty Village Road Square"],
        }
        result = build_adaptation_semantic_authority(
            "Adapted_Module",
            staging_module,
            attempt=attempt,
            source_manifest=manifest,
            normalized_packet=packet,
        )
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["identity"], attempt)
        authority = result["semantic_authority"]
        self.assertEqual(authority["attempt"], attempt)
        self.assertEqual(authority["adaptation_provenance"]["source_hash"], source_hash)
        unresolved = {
            row["phrase"]
            for row in authority["diagnostics"]["unresolved_destination_phrases"]
        }
        self.assertNotIn("empty village road", unresolved)
        self.assertIn("village road", unresolved)
        self.assertFalse(
            any(
                row.get("code") == "unresolved_destination_phrase"
                and row.get("phrase") == "empty village road"
                for row in result["blockers"]
            )
        )
        persisted = persist_adaptation_semantic_authority(staging_module, result)
        self.assertEqual(persisted["status"], "persisted")
        self.assertEqual(persisted["identity"], attempt)
        saved = json.loads(
            (staging_module / "module_context.json").read_text(encoding="utf-8")
        )
        self.assertEqual(saved["semantic_authority"]["attempt"], attempt)
        self.assertEqual(
            saved["semantic_authority"]["adaptation_provenance"]["source_hash"],
            source_hash,
        )
        self.assertEqual(
            saved["semantic_authority"]["destination_phrases"][
                "the empty village road square"
            ]["status"],
            "resolved",
        )
        self.assertEqual(
            {path: path.read_bytes() for path in protected},
            before,
        )
        self.assertFalse((self.root / "modules" / "Adapted_Module").exists())


if __name__ == "__main__":
    unittest.main()
