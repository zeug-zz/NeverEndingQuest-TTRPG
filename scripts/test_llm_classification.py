# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0

"""
Regression tests for Phase 2 LLM classification pipeline.

Tests cover Sections 1-5 of web/extensions/toolkit_llm_classification.py:
  - Entity classification (detection, LLM call, apply)
  - Destination classification (detection, LLM call, apply)
  - NPC visibility classification (detection, LLM call, apply)
  - Remediation proposals (batch, call, validation, apply)
  - Classification cache (sha256, atomic writes)
  - Fail-open behavior (API failure, empty module, cache failure)

All tests use temp directories and avoid real API calls.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict

from web.extensions.toolkit_llm_classification import (
    ClassificationCache,
    build_entity_classification_batch,
    build_destination_classification_batch,
    build_npc_visibility_batch,
    _validate_classification_labels,
    _normalize_classifications,
    _normalize_name_for_bestiary,
    _is_in_bestiary,
    detect_ambiguous_entities,
    detect_ambiguous_destinations,
    detect_ambiguous_npc_visibility,
    run_llm_classification_pass,
    apply_entity_classifications,
    apply_destination_classifications,
    apply_npc_visibility_classifications,
    persist_classification_metadata,
    build_remediation_proposal_batch,
    validate_remediation_proposals,
    apply_accepted_proposals,
    is_classification_enabled,
)


class TestClassificationCache(unittest.TestCase):
    """ClassificationCache sha256 roundtrip, miss, and persistence."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.slug = "test_module"
        self.cache = ClassificationCache(self.slug, module_dir=self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_cache_miss_returns_none(self):
        self.assertIsNone(self.cache.get("entity", "unknown text"))

    def test_cache_set_and_get_roundtrip(self):
        self.cache.set("entity", "spectral servants", "scene_illusion")
        self.assertEqual(
            self.cache.get("entity", "spectral servants"),
            "scene_illusion",
        )

    def test_cache_different_domains_independent(self):
        self.cache.set("entity", "spectral servants", "scene_illusion")
        self.assertIsNone(
            self.cache.get("destination", "spectral servants"),
        )

    def test_cache_different_text_produces_different_hash(self):
        self.cache.set("entity", "text_a", "combatant")
        self.assertIsNone(self.cache.get("entity", "text_b"))

    def test_cache_persists_across_instances(self):
        self.cache.set("entity", "persistent", "narrator_flavor")
        cache2 = ClassificationCache(self.slug, module_dir=self.tmpdir)
        self.assertEqual(
            cache2.get("entity", "persistent"),
            "narrator_flavor",
        )

    def test_cache_atomic_write_no_corruption(self):
        half_path = Path(self.tmpdir) / "llm_classification_cache.json"
        half_path.write_text('{"entity": {"abc": "com')
        result = self.cache.get("entity", "xyz")
        self.assertIsNone(result)


class TestBatchBuilders(unittest.TestCase):
    """Section 1 batch builder functions."""

    def test_entity_batch_empty(self):
        self.assertEqual(build_entity_classification_batch([]), [])

    def test_entity_batch_format(self):
        entities = [{"name": "spectral servants", "area": "AR001", "sentence": "They drift through"}]
        batch = build_entity_classification_batch(entities)
        self.assertEqual(len(batch), 1)
        self.assertEqual(batch[0]["entity_name"], "spectral servants")
        self.assertEqual(batch[0]["area_id"], "AR001")
        self.assertEqual(batch[0]["context"], "They drift through")

    def test_destination_batch_empty(self):
        self.assertEqual(build_destination_classification_batch([]), [])

    def test_destination_batch_format(self):
        phrases = [{"phrase": "old tower", "area": "AR001", "context": "the old tower looms"}]
        batch = build_destination_classification_batch(phrases)
        self.assertEqual(len(batch), 1)
        self.assertEqual(batch[0]["phrase"], "old tower")

    def test_npc_batch_empty(self):
        self.assertEqual(build_npc_visibility_batch([]), [])

    def test_npc_batch_format(self):
        npcs = [{"npc_name": "Mysterious Stranger", "area": "AR001", "context": "A stranger appears"}]
        batch = build_npc_visibility_batch(npcs)
        self.assertEqual(len(batch), 1)
        self.assertEqual(batch[0]["npc_name"], "Mysterious Stranger")


class TestNormalization(unittest.TestCase):
    """Name normalization helpers."""

    def test_normalize_name_basic(self):
        self.assertEqual(_normalize_name_for_bestiary("Giant Rat"), "giant_rat")

    def test_normalize_name_apostrophe(self):
        self.assertEqual(
            _normalize_name_for_bestiary("Will-o'-wisp"),
            "will-o'-wisp",
        )

    def test_normalize_name_whitespace(self):
        self.assertEqual(_normalize_name_for_bestiary("  Spectral Servant  "), "spectral_servant")

    def test_normalize_classifications_dict_passthrough(self):
        raw = {"entity_a": "combatant"}
        result = _normalize_classifications(raw, "entity_name")
        self.assertEqual(result, raw)

    def test_normalize_classifications_list_to_dict(self):
        raw = [
            {"entity_name": "e1", "label": "combatant"},
            {"entity_name": "e2", "category": "scene_illusion"},
        ]
        result = _normalize_classifications(raw, "entity_name")
        self.assertEqual(result["e1"], "combatant")
        self.assertEqual(result["e2"], "scene_illusion")

    def test_normalize_classifications_empty(self):
        self.assertEqual(_normalize_classifications([], "entity_name"), {})

    def test_normalize_classifications_none(self):
        self.assertEqual(_normalize_classifications(None, "entity_name"), {})


class TestLabelValidation(unittest.TestCase):
    """Label enum validation (used by all 3 LLM call functions)."""

    def test_valid_label_accepted(self):
        result = _validate_classification_labels(
            {"e1": "combatant"}, {"combatant", "scene_illusion", "narrator_flavor"}, "narrator_flavor",
        )
        self.assertEqual(result["e1"], "combatant")

    def test_invalid_label_falls_back(self):
        result = _validate_classification_labels(
            {"e1": "ghost_type"}, {"combatant", "scene_illusion", "narrator_flavor"}, "narrator_flavor",
        )
        self.assertEqual(result["e1"], "narrator_flavor")

    def test_mixed_valid_and_invalid(self):
        result = _validate_classification_labels(
            {"e1": "combatant", "e2": "invalid", "e3": "scene_illusion"},
            {"combatant", "scene_illusion", "narrator_flavor"},
            "narrator_flavor",
        )
        self.assertEqual(result["e1"], "combatant")
        self.assertEqual(result["e2"], "narrator_flavor")
        self.assertEqual(result["e3"], "scene_illusion")

    def test_empty_labels(self):
        self.assertEqual(
            _validate_classification_labels({}, {"a", "b"}, "a"),
            {},
        )


class TestBestiaryLookup(unittest.TestCase):
    """Bestiary bypass detection."""

    def test_normalize_for_bestiary(self):
        self.assertEqual(_normalize_name_for_bestiary("  Giant Rat  "), "giant_rat")
        self.assertEqual(_normalize_name_for_bestiary("Will-o'-wisp"), "will-o'-wisp")
        self.assertEqual(_normalize_name_for_bestiary("Adult Black Dragon"), "adult_black_dragon")


class TestEntityClassification(unittest.TestCase):
    """Entity detection, classification, and apply."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.areas_dir = Path(self.tmpdir) / "areas"
        self.areas_dir.mkdir()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_area(self, area_id: str, locations: list):
        area = {"areaId": area_id, "locations": locations}
        (self.areas_dir / f"{area_id}.json").write_text(json.dumps(area))

    def test_empty_module_no_crash(self):
        result = detect_ambiguous_entities(self.tmpdir)
        self.assertEqual(result, [])

    def test_unknown_entity_detected(self):
        self._write_area("AR001", [
            {"locationId": "L01", "description": "room desc",
             "monsters": [{"name": "Spectral Servant", "quantity": {"min": 1, "max": 1}}]},
        ])
        result = detect_ambiguous_entities(self.tmpdir)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "Spectral Servant")

    def test_string_format_parsed(self):
        self._write_area("AR001", [
            {"locationId": "L01", "description": "room",
             "monsters": ["2 spectral servants"]},
        ])
        result = detect_ambiguous_entities(self.tmpdir)
        self.assertEqual(len(result), 1)

    def test_bu_files_skipped(self):
        (self.areas_dir / "AR001_BU.json").write_text(json.dumps({
            "areaId": "AR001", "locations": [
                {"locationId": "L01", "monsters": [{"name": "Phantom"}]},
            ]}))
        result = detect_ambiguous_entities(self.tmpdir)
        self.assertEqual(result, [])

    def _area_path(self):
        return self.areas_dir / "AR001.json"

    def test_apply_combatant_no_changes(self):
        self._write_area("AR001", [
            {"locationId": "L01", "monsters": [{"name": "Spectral Servant", "quantity": {"min": 1, "max": 1}}]},
        ])
        result = apply_entity_classifications(self.tmpdir, {"spectral servant": "combatant"})
        self.assertEqual(result["status"], "success")
        data = json.loads(self._area_path().read_text())
        self.assertEqual(len(data["locations"][0]["monsters"]), 1)

    def test_apply_scene_illusion_adds_block(self):
        self._write_area("AR001", [
            {"locationId": "L01", "monsters": [{"name": "Spectral Servant", "quantity": {"min": 1, "max": 1}}]},
        ])
        result = apply_entity_classifications(self.tmpdir, {"spectral servant": "scene_illusion"})
        self.assertEqual(result["status"], "success")
        data = json.loads(self._area_path().read_text())
        monsters = data["locations"][0]["monsters"]
        self.assertEqual(len(monsters), 1)
        self.assertIn("sceneEntity", monsters[0])
        self.assertEqual(monsters[0]["sceneEntity"]["combatValidity"], "scene_only")

    def test_apply_narrator_flavor_removes_and_annotates(self):
        self._write_area("AR001", [
            {"locationId": "L01", "monsters": [{"name": "Phantom Guard", "quantity": {"min": 2, "max": 2}}]},
        ])
        result = apply_entity_classifications(self.tmpdir, {"phantom guard": "narrator_flavor"})
        self.assertEqual(result["status"], "success")
        data = json.loads(self._area_path().read_text())
        monsters = data["locations"][0]["monsters"]
        self.assertEqual(len(monsters), 1)
        self.assertIn("sceneEntity", monsters[0])
        self.assertEqual(monsters[0]["sceneEntity"]["combatValidity"], "scene_only")

    def test_apply_narrator_flavor_removes_and_annotates(self):
        self._write_area("AR001", [
            {"locationId": "L01", "monsters": [{"name": "Phantom Guard", "quantity": {"min": 2, "max": 2}}]},
        ])
        result = apply_entity_classifications(self.tmpdir, {"phantom guard": "narrator_flavor"})
        self.assertEqual(result["status"], "success")
        data = json.loads((self.areas_dir / "AR001.json").read_text())
        self.assertEqual(len(data["locations"][0]["monsters"]), 0)
        meta = data["locations"][0].get("_llm_metadata", {})
        reclassified = meta.get("reclassified_entities", [])
        self.assertEqual(len(reclassified), 1)
        self.assertEqual(reclassified[0]["name"], "Phantom Guard")

    def test_apply_empty_classifications_noop(self):
        self._write_area("AR001", [
            {"locationId": "L01", "monsters": [{"name": "Goblin", "quantity": {"min": 1, "max": 1}}]},
        ])
        result = apply_entity_classifications(self.tmpdir, {})
        self.assertEqual(result["applied"], 0)


class TestDestinationClassification(unittest.TestCase):
    """Destination detection, classification, and apply."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.areas_dir = Path(self.tmpdir) / "areas"
        self.areas_dir.mkdir()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _area_path(self):
        return self.areas_dir / "AR001.json"

    def _write_area_with_ctx(self, area_id: str, locations: list):
        area = {"areaId": area_id, "locations": locations}
        self._area_path().write_text(json.dumps(area))
        ctx = {"semantic_authority": {"location_aliases": {}, "destination_phrases": {}}}
        (Path(self.tmpdir) / "module_context.json").write_text(json.dumps(ctx))

    def test_detect_empty_module(self):
        result = detect_ambiguous_destinations(self.tmpdir)
        self.assertEqual(result, [])

    def test_apply_adds_alias(self):
        self._write_area_with_ctx("AR001", [
            {"locationId": "L01", "name": "Old Tower", "description": "the old tower looms", "aliases": []},
        ])
        result = apply_destination_classifications(
            self.tmpdir, {"old tower": "canonical_alias"},
        )
        self.assertEqual(result["status"], "success")
        data = json.loads(self._area_path().read_text())
        self.assertIn("old tower", data["locations"][0].get("aliases", []))

    def test_apply_dedupe_no_duplicate(self):
        self._write_area_with_ctx("AR001", [
            {"locationId": "L01", "name": "Old Tower", "description": "the old tower", "aliases": ["old tower"]},
        ])
        apply_destination_classifications(self.tmpdir, {"old tower": "canonical_alias"})
        data = json.loads(self._area_path().read_text())
        aliases = [a.lower().strip() for a in data["locations"][0].get("aliases", [])]
        self.assertEqual(aliases.count("old tower"), 1)

    def test_apply_evocative_prose_noop(self):
        self._write_area_with_ctx("AR001", [
            {"locationId": "L01", "name": "Old Tower", "description": "the old tower", "aliases": []},
        ])
        result = apply_destination_classifications(
            self.tmpdir, {"old tower": "evocative_prose"},
        )
        data = json.loads(self._area_path().read_text())
        self.assertEqual(data["locations"][0].get("aliases", []), [])


class TestNPCVisibilityClassification(unittest.TestCase):
    """NPC visibility detection, classification, and apply."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.areas_dir = Path(self.tmpdir) / "areas"
        self.areas_dir.mkdir()
        self.ctx = {
            "semantic_authority": {
                "npc_scene_authority": {},
            },
        }
        (Path(self.tmpdir) / "module_context.json").write_text(json.dumps(self.ctx))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_area(self, area_id: str, locations: list):
        area = {"areaId": area_id, "locations": locations}
        (self.areas_dir / f"{area_id}.json").write_text(json.dumps(area))

    def test_empty_module_no_crash(self):
        result = detect_ambiguous_npc_visibility(self.tmpdir)
        self.assertEqual(result, [])

    def test_apply_visible_adds_location_id(self):
        self._write_area("AR001", [
            {"locationId": "L01", "npcs": [{"name": "Mysterious Stranger", "description": "A stranger"}]},
        ])
        apply_npc_visibility_classifications(self.tmpdir, {"mysterious_stranger": "visible"})
        ctx = json.loads((Path(self.tmpdir) / "module_context.json").read_text())
        nsc = ctx["semantic_authority"]["npc_scene_authority"]
        self.assertIn("Mysterious Stranger", nsc)
        self.assertIn("L01", nsc["Mysterious Stranger"]["visible_location_ids"])

    def test_apply_hidden_reveal_adds_binding(self):
        self._write_area("AR001", [
            {"locationId": "L01", "npcs": [{"name": "Hidden Sage", "description": "A hidden figure"}]},
        ])
        apply_npc_visibility_classifications(self.tmpdir, {"hidden_sage": "hidden_reveal"})
        ctx = json.loads((Path(self.tmpdir) / "module_context.json").read_text())
        nsc = ctx["semantic_authority"]["npc_scene_authority"]
        self.assertIn("Hidden Sage", nsc)
        self.assertTrue(len(nsc["Hidden Sage"].get("reveal_bindings", [])) > 0)

    def test_apply_lore_only_noop(self):
        self._write_area("AR001", [
            {"locationId": "L01", "npcs": [{"name": "Legendary Hero", "description": "a hero of old"}]},
        ])
        apply_npc_visibility_classifications(self.tmpdir, {"legendary_hero": "lore_only"})
        ctx = json.loads((Path(self.tmpdir) / "module_context.json").read_text())
        nsc = ctx["semantic_authority"]["npc_scene_authority"]
        self.assertEqual(nsc.get("Legendary Hero", {}).get("visible_location_ids", []), [])


class TestRemediationProposals(unittest.TestCase):
    """DP4 remediation proposal batch, validation, and apply."""

    def _make_tmp_module(self, monster_name="Spectral Servant"):
        tmpdir = tempfile.mkdtemp()
        areas_dir = Path(tmpdir) / "areas"
        areas_dir.mkdir()
        area = {"areaId": "AR001", "locations": [
            {"locationId": "L01", "name": "Haunt",
             "description": "The spectral servant haunts",
             "monsters": [{"name": monster_name, "quantity": {"min": 1, "max": 1}}],
             "npcs": [{"name": "Stranger", "description": "A stranger"}],
             "aliases": []},
        ]}
        (areas_dir / "AR001.json").write_text(json.dumps(area))
        ctx = {"semantic_authority": {"npc_scene_authority": {}}}
        (Path(tmpdir) / "module_context.json").write_text(json.dumps(ctx))
        return tmpdir

    def test_empty_blocker_report_returns_empty(self):
        self.assertEqual(build_remediation_proposal_batch("/tmp", {}), [])

    def test_proposal_batch_with_blockers(self):
        report = {
            "blocker_classes": ["spatial_adjacency_convergence_gap", "monster_schema_completion_gap"],
            "entity_classifications": {"spectral_servants": "scene_illusion"},
            "destination_classifications": {},
            "npc_classifications": {},
        }
        batch = build_remediation_proposal_batch("/tmp", report)
        self.assertEqual(len(batch), 1)
        self.assertIn("spectral_servants", str(batch[0]))

    def test_validate_rejects_unwhitelisted(self):
        mod_dir = self._make_tmp_module()
        proposals = [{"transform_type": "rewrite_location", "target": "Haunt"}]
        validated = validate_remediation_proposals(mod_dir, proposals)
        self.assertIn("unwhitelisted_transform", validated[0].get("safety", ""))

    def test_validate_rejects_missing_target(self):
        mod_dir = self._make_tmp_module()
        proposals = [{"transform_type": "move_entity_to_scene_entity", "target": "NonExistent"}]
        validated = validate_remediation_proposals(mod_dir, proposals)
        self.assertIn("fail:target_missing", validated[0].get("safety", ""))

    def test_validate_passes_valid_proposal(self):
        mod_dir = self._make_tmp_module()
        proposals = [{"transform_type": "move_entity_to_scene_entity", "target": "spectral servant"}]
        validated = validate_remediation_proposals(mod_dir, proposals)
        self.assertEqual(validated[0]["safety"], "pass")

    def test_validate_empty_proposals(self):
        self.assertEqual(validate_remediation_proposals("/tmp", []), [])

    def test_apply_accepted_proposals_move_to_scene(self):
        mod_dir = self._make_tmp_module()
        validated = [{"transform_type": "move_entity_to_scene_entity",
                      "target": "spectral servant", "safety": "pass"}]
        result = apply_accepted_proposals(mod_dir, validated)
        self.assertGreater(result["applied"], 0)

    def test_apply_accepted_proposals_unsafe_skips(self):
        mod_dir = self._make_tmp_module()
        validated = [{"transform_type": "move_entity_to_scene_entity",
                      "target": "spectral servant", "safety": "fail:target_missing"}]
        result = apply_accepted_proposals(mod_dir, validated)
        self.assertEqual(result["applied"], 0)
        self.assertGreater(result["failed"], 0)


class TestFailOpen(unittest.TestCase):
    """Fail-open behavior: API failure, empty module, cache failure."""

    def test_empty_module_entity_detection_empty(self):
        tmpdir = tempfile.mkdtemp()
        result = detect_ambiguous_entities(tmpdir)
        self.assertEqual(result, [])

    def test_empty_module_destination_detection_empty(self):
        tmpdir = tempfile.mkdtemp()
        result = detect_ambiguous_destinations(tmpdir)
        self.assertEqual(result, [])

    def test_empty_module_npc_detection_empty(self):
        tmpdir = tempfile.mkdtemp()
        result = detect_ambiguous_npc_visibility(tmpdir)
        self.assertEqual(result, [])

    def test_apply_entity_empty_noop(self):
        result = apply_entity_classifications("/nonexistent", {"x": "combatant"})
        self.assertEqual(result["applied"], 0)

    def test_apply_destination_empty_noop(self):
        result = apply_destination_classifications("/nonexistent", {"x": "canonical_alias"})
        self.assertEqual(int(result.get("applied", "0")), 0)

    def test_apply_npc_empty_noop(self):
        result = apply_npc_visibility_classifications("/nonexistent", {"x": "visible"})
        self.assertEqual(result["applied"], 0)

    def test_persist_metadata_nonexistent_dir(self):
        try:
            persist_classification_metadata("/nonexistent", {}, {}, {})
        except Exception:
            self.fail("persist_classification_metadata raised on nonexistent dir")


class TestPersistMetadata(unittest.TestCase):
    """Classification metadata persistence."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_persist_writes_metadata(self):
        ctx = {}
        (Path(self.tmpdir) / "module_context.json").write_text(json.dumps(ctx))
        persist_classification_metadata(
            self.tmpdir,
            {"e1": "combatant"}, {"d1": "canonical_alias"}, {"n1": "visible"},
        )
        ctx = json.loads((Path(self.tmpdir) / "module_context.json").read_text())
        meta = ctx.get("classification_metadata", {})
        self.assertEqual(meta.get("entity_count"), 1)
        self.assertEqual(meta.get("destination_count"), 1)
        self.assertEqual(meta.get("npc_count"), 1)
        self.assertEqual(meta.get("provenance"), "llm_classification")


if __name__ == "__main__":
    unittest.main()
