"""Provider-free tests for accurate-ingest source monster materialization
and encounter seed binding.

Step 1.x contract tests for `materialize_source_monsters()`.
Step 2.1 contract tests for `bind_encounter_monsters()`.
"""

import json
import os
import sys
import tempfile
import unittest
from typing import Any, Dict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils import accurate_ingest_monster_materialization as materialization_module
from utils.accurate_ingest_monster_materialization import (
    materialize_source_monsters,
    bind_encounter_monsters,
)

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

REUSABLE_MONSTER_REFS = ["skeleton", "goblin", "bandit", "wight"]

ODD_MONSTER_REFS = ["were-possum", "were-trout"]

NPC_LIKE_REFS = ["Archivus Primus", "Kobe", "Dog-Growl"]

NUMILLIAN_ENCOUNTER_SEEDS = [
    "Rookery: Kenku ambush",
    "Gatepact Vault: Wight guardian",
    "Hidden Archive: Alhoon encounter",
]

MIN_SCHEMA_MONSTER = {
    "size": "Medium",
    "alignment": "neutral",
    "armorClass": 12,
    "name": "skeleton",
    "hitPoints": 10,
    "type": "monster",
    "strength": 10,
    "dexterity": 10,
    "constitution": 10,
    "intelligence": 10,
    "wisdom": 10,
    "charisma": 10,
}


def _make_temp_module_dir(base: str, slug: str) -> str:
    target = os.path.join(base, slug)
    os.makedirs(os.path.join(target, "monsters"), exist_ok=True)
    return target


def _write_monster_file(module_dir: str, slug: str, data: Dict[str, Any]) -> str:
    path = os.path.join(module_dir, "monsters", f"{slug}.json")
    with open(path, "w") as f:
        json.dump(data, f)
    return path


# ---------------------------------------------------------------------------
# Report shape contract
# ---------------------------------------------------------------------------


class TestMonsterMaterializationReportContract(unittest.TestCase):
    """Lock the report shape returned by materialize_source_monsters()."""

    def test_helper_stays_provider_free(self):
        with open(materialization_module.__file__, "r") as f:
            source = f.read()
        self.assertNotIn("updates.update_character_info", source)
        self.assertNotIn("normalize_character_name", source)

    def test_report_contains_required_keys(self):
        result = materialize_source_monsters("/tmp/test", [], [])
        required = {
            "status",
            "monsters_planned",
            "monsters_reused",
            "monsters_generated",
            "monsters_skipped",
            "monsters_unresolved",
            "encounters_planned",
            "encounters_bound",
            "encounters_unresolved",
            "encounters_unbound",
            "encounter_bindings",
            "unresolved_refs",
            "artifact_paths",
            "resolution_log",
        }
        self.assertTrue(
            required.issubset(result.keys()),
            f"Missing keys: {required - set(result.keys())}",
        )

    def test_status_is_str(self):
        result = materialize_source_monsters("/tmp/test", [], [])
        self.assertIsInstance(result["status"], str)

    def test_count_fields_are_ints(self):
        result = materialize_source_monsters("/tmp/test", [], [])
        for key in (
            "monsters_planned",
            "monsters_reused",
            "monsters_generated",
            "monsters_skipped",
            "monsters_unresolved",
            "encounters_planned",
            "encounters_bound",
            "encounters_unresolved",
            "encounters_unbound",
        ):
            with self.subTest(key=key):
                self.assertIsInstance(result[key], int)

    def test_list_fields_are_lists(self):
        result = materialize_source_monsters("/tmp/test", [], [])
        self.assertIsInstance(result["unresolved_refs"], list)
        self.assertIsInstance(result["artifact_paths"], list)

    def test_resolution_log_is_list(self):
        result = materialize_source_monsters("/tmp/test", [], [])
        self.assertIsInstance(result["resolution_log"], list)

    def test_deterministic_empty_input(self):
        r1 = materialize_source_monsters("/tmp/test", [], [])
        r2 = materialize_source_monsters("/tmp/test", [], [])
        self.assertEqual(r1, r2)

    def test_deterministic_with_refs(self):
        refs = ["skeleton", "goblin"]
        seeds = ["Tomb: skeleton ambush"]
        r1 = materialize_source_monsters("/tmp/test", refs, seeds)
        r2 = materialize_source_monsters("/tmp/test", refs, seeds)
        self.assertEqual(r1, r2)


# ---------------------------------------------------------------------------
# Source monster ref contract
# ---------------------------------------------------------------------------


class TestUnambiguousSourceMonsterRef(unittest.TestCase):
    """An unambiguous reusable source monster ref should be materializable."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.module_dir = _make_temp_module_dir(self.tmpdir.name, "TestModule")

    def test_reusable_srd_monster_can_materialize(self):
        """A source ref matching a known SRD/bestiary monster should
        produce a schema-valid monster file or report reuse."""
        _write_monster_file(self.module_dir, "skeleton", MIN_SCHEMA_MONSTER)
        result = materialize_source_monsters(
            self.module_dir, ["skeleton"], [],
        )
        if result["status"] == "not_implemented":
            self.skipTest("Step 1.2 implements reusable monster materialization")
        self.assertEqual(result["monsters_planned"], 1)
        self.assertGreaterEqual(result["monsters_reused"] + result["monsters_generated"], 1)
        self.assertNotIn("skeleton", [ref.lower() for ref in result["unresolved_refs"]])
        self.assertTrue(
            any(path.endswith("skeleton.json") for path in result["artifact_paths"]),
            "Expected skeleton artifact path in materialization report",
        )
        self.assertIsInstance(result["unresolved_refs"], list)

    def test_multiple_reusable_refs_report_separate_counts(self):
        for name in ["skeleton", "goblin", "bandit"]:
            monster = dict(MIN_SCHEMA_MONSTER, name=name)
            _write_monster_file(self.module_dir, name, monster)
        result = materialize_source_monsters(
            self.module_dir, ["skeleton", "goblin", "bandit"], [],
        )
        if result["status"] == "not_implemented":
            self.skipTest("Step 1.2 implements reusable monster materialization")
        self.assertEqual(result["monsters_planned"], 3)
        self.assertGreaterEqual(result["monsters_reused"] + result["monsters_generated"], 3)
        self.assertGreaterEqual(result["monsters_unresolved"], 0)


class TestSchemaInsufficientMonsterFiles(unittest.TestCase):
    """Files missing required runtime fields should remain unresolved."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.module_dir = _make_temp_module_dir(self.tmpdir.name, "TestModule")

    def _assert_unresolved(self, result, ref="skeleton"):
        self.assertEqual(result["monsters_planned"], 1)
        self.assertEqual(result["monsters_reused"], 0)
        self.assertEqual(result["monsters_generated"], 0)
        self.assertGreaterEqual(result["monsters_unresolved"], 1)
        self.assertIn(ref.lower(), [r.lower() for r in result.get("unresolved_refs", [])])
        self.assertFalse(
            any(path.endswith(f"{ref}.json") for path in result.get("artifact_paths", [])),
            f"Expected no artifact path for {ref}",
        )

    def test_valid_schema_monster_is_reused(self):
        _write_monster_file(self.module_dir, "skeleton", MIN_SCHEMA_MONSTER)
        result = materialize_source_monsters(self.module_dir, ["skeleton"], [])
        self.assertEqual(result["monsters_planned"], 1)
        self.assertEqual(result["monsters_reused"], 1)
        self.assertEqual(result["monsters_generated"], 0)
        self.assertEqual(result["monsters_unresolved"], 0)
        self.assertTrue(
            any(path.endswith("skeleton.json") for path in result["artifact_paths"]),
        )

    def test_invalid_json_file_remains_unresolved(self):
        path = os.path.join(self.module_dir, "monsters", "skeleton.json")
        with open(path, "w") as f:
            f.write("{broken")
        result = materialize_source_monsters(self.module_dir, ["skeleton"], [])
        self._assert_unresolved(result)

    def test_missing_armorClass_remains_unresolved(self):
        data = dict(MIN_SCHEMA_MONSTER)
        del data["armorClass"]
        _write_monster_file(self.module_dir, "skeleton", data)
        result = materialize_source_monsters(self.module_dir, ["skeleton"], [])
        self._assert_unresolved(result)

    def test_missing_size_remains_unresolved(self):
        data = dict(MIN_SCHEMA_MONSTER)
        del data["size"]
        _write_monster_file(self.module_dir, "skeleton", data)
        result = materialize_source_monsters(self.module_dir, ["skeleton"], [])
        self._assert_unresolved(result)

    def test_missing_alignment_remains_unresolved(self):
        data = dict(MIN_SCHEMA_MONSTER)
        del data["alignment"]
        _write_monster_file(self.module_dir, "skeleton", data)
        result = materialize_source_monsters(self.module_dir, ["skeleton"], [])
        self._assert_unresolved(result)


class TestUnresolvedOddSourceRef(unittest.TestCase):
    """An odd/unknown source monster ref should be reported as unresolved."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.module_dir = _make_temp_module_dir(self.tmpdir.name, "TestModule")

    def test_odd_ref_is_not_silently_dropped(self):
        result = materialize_source_monsters(
            self.module_dir, ["were-possum"], [],
        )
        self.assertIn("were-possum", result.get("unresolved_refs", []))
        self.assertGreaterEqual(result.get("monsters_unresolved", 0), 1)

    def test_multiple_odd_refs_all_survive(self):
        result = materialize_source_monsters(
            self.module_dir, ODD_MONSTER_REFS, [],
        )
        for ref in ODD_MONSTER_REFS:
            with self.subTest(ref=ref):
                self.assertIn(
                    ref,
                    result.get("unresolved_refs", []),
                    f"Unresolved ref {ref} missing from report",
                )

    def test_mixed_reusable_and_odd_refs_keeps_odd_refs(self):
        result = materialize_source_monsters(
            self.module_dir, ["skeleton"] + ODD_MONSTER_REFS, [],
        )
        for ref in ODD_MONSTER_REFS:
            self.assertIn(ref, result.get("unresolved_refs", []))


class TestNpcLikeRefIsNotPromoted(unittest.TestCase):
    """NPC-like names should not be materialized as monster artifacts."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.module_dir = _make_temp_module_dir(self.tmpdir.name, "TestModule")

    def test_character_name_not_in_artifact_paths(self):
        result = materialize_source_monsters(
            self.module_dir, NPC_LIKE_REFS, [],
        )
        for path in result.get("artifact_paths", []):
            with self.subTest(path=path):
                self.assertNotIn("archivus_primu", path.lower())
                self.assertNotIn("kobe", path.lower())

    def test_npc_like_refs_appear_as_unresolved(self):
        result = materialize_source_monsters(
            self.module_dir, NPC_LIKE_REFS, [],
        )
        for ref in NPC_LIKE_REFS:
            self.assertIn(ref.lower(), [r.lower() for r in result.get("unresolved_refs", [])])

    def test_npc_like_refs_do_not_inflate_generated_count(self):
        result = materialize_source_monsters(
            self.module_dir, NPC_LIKE_REFS, [],
        )
        self.assertEqual(result.get("monsters_generated", 0), 0)


# ---------------------------------------------------------------------------
# No-source compatibility
# ---------------------------------------------------------------------------


class TestNoSourceInput(unittest.TestCase):
    """No-source input should return a pass/skipped no-op status."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.module_dir = _make_temp_module_dir(self.tmpdir.name, "TestModule")

    def test_empty_refs_no_false_blockers(self):
        result = materialize_source_monsters(self.module_dir, [], [])
        self.assertIn(result["status"], {"pass", "skipped"})
        self.assertEqual(result["monsters_planned"], 0)
        self.assertEqual(result["monsters_unresolved"], 0)
        self.assertEqual(result["unresolved_refs"], [])

    def test_empty_refs_no_artifact_creations(self):
        result = materialize_source_monsters(self.module_dir, [], [])
        self.assertEqual(result["artifact_paths"], [])


# ---------------------------------------------------------------------------
# Encounter seed binding contract
# ---------------------------------------------------------------------------


class TestEncounterSeedBinding(unittest.TestCase):
    """Encounter seeds should retain monster bindings when refs are present."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.module_dir = _make_temp_module_dir(self.tmpdir.name, "TestModule")

    def test_encounter_seeds_preserved_in_report(self):
        result = materialize_source_monsters(
            self.module_dir, REUSABLE_MONSTER_REFS, NUMILLIAN_ENCOUNTER_SEEDS,
        )
        self.assertGreaterEqual(result["encounters_planned"], len(NUMILLIAN_ENCOUNTER_SEEDS))

    def test_encounter_seeds_with_unresolved_refs_not_dropped(self):
        result = materialize_source_monsters(
            self.module_dir, [], NUMILLIAN_ENCOUNTER_SEEDS,
        )
        self.assertGreaterEqual(result["encounters_planned"], 1)

    def test_encounter_binding_counts_propagate(self):
        for name in ["kenku", "wight"]:
            _write_monster_file(self.module_dir, name, dict(MIN_SCHEMA_MONSTER, name=name))
        seeds = ["Rookery: Kenku ambush", "Tomb of the Unknown"]
        result = materialize_source_monsters(
            self.module_dir, ["kenku", "wight"], seeds,
        )
        self.assertEqual(result["encounters_planned"], 2)
        self.assertEqual(result["encounters_bound"], 1)
        self.assertEqual(result["encounters_unbound"], 1)
        self.assertEqual(result["encounters_unresolved"], 0)
        self.assertIsInstance(result["encounter_bindings"], list)

    def test_encounter_binding_list_matches_seeds(self):
        for name in ["kenku", "wight"]:
            _write_monster_file(self.module_dir, name, dict(MIN_SCHEMA_MONSTER, name=name))
        seeds = ["Rookery: Kenku ambush", "Hidden Archive: Alhoon encounter"]
        result = materialize_source_monsters(
            self.module_dir, ["kenku", "wight", "alhoon"], seeds,
        )
        self.assertGreaterEqual(len(result["encounter_bindings"]), 2)
        statuses = {b["status"] for b in result["encounter_bindings"]}
        self.assertIn("bound", statuses)
        self.assertIn("unresolved", statuses)


# ---------------------------------------------------------------------------
# Determinism / stability
# ---------------------------------------------------------------------------


class TestDeterministicBehavior(unittest.TestCase):
    """Repeated calls with same inputs produce identical results."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.module_dir = _make_temp_module_dir(self.tmpdir.name, "TestModule")

    def test_repeated_call_identical(self):
        _write_monster_file(self.module_dir, "skeleton", MIN_SCHEMA_MONSTER)
        refs = ["skeleton", "were-possum"]
        seeds = ["Tomb: skeleton ambush"]
        r1 = materialize_source_monsters(self.module_dir, refs, seeds)
        r2 = materialize_source_monsters(self.module_dir, refs, seeds)
        self.assertEqual(r1, r2)


# ---------------------------------------------------------------------------
# Resolution log contract
# ---------------------------------------------------------------------------


class TestResolutionLog(unittest.TestCase):
    """resolution_log provides per-ref deterministic diagnostics."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.module_dir = _make_temp_module_dir(self.tmpdir.name, "TestModule")

    def test_one_entry_per_ref(self):
        _write_monster_file(self.module_dir, "skeleton", MIN_SCHEMA_MONSTER)
        result = materialize_source_monsters(
            self.module_dir, ["skeleton", "were-possum"], [],
        )
        self.assertEqual(len(result["resolution_log"]), 2)

    def test_reused_entry_has_correct_fields(self):
        _write_monster_file(self.module_dir, "skeleton", MIN_SCHEMA_MONSTER)
        result = materialize_source_monsters(self.module_dir, ["skeleton"], [])
        entry = result["resolution_log"][0]
        self.assertEqual(entry["ref"], "skeleton")
        self.assertEqual(entry["status"], "reused")
        self.assertEqual(entry["reason"], "reused")
        self.assertIsNotNone(entry["artifact_path"])
        self.assertTrue(entry["artifact_path"].endswith("skeleton.json"))

    def test_file_not_found_entry_has_correct_fields(self):
        result = materialize_source_monsters(self.module_dir, ["were-possum"], [])
        entry = result["resolution_log"][0]
        self.assertEqual(entry["ref"], "were-possum")
        self.assertEqual(entry["status"], "unresolved")
        self.assertEqual(entry["reason"], "file_not_found")
        self.assertIsNotNone(entry["artifact_path"])
        self.assertTrue(entry["artifact_path"].endswith("were_possum.json"))

    def test_invalid_json_entry_has_correct_fields(self):
        path = os.path.join(self.module_dir, "monsters", "skeleton.json")
        with open(path, "w") as f:
            f.write("{broken")
        result = materialize_source_monsters(self.module_dir, ["skeleton"], [])
        entry = result["resolution_log"][0]
        self.assertEqual(entry["ref"], "skeleton")
        self.assertEqual(entry["status"], "unresolved")
        self.assertEqual(entry["reason"], "invalid_json")
        self.assertEqual(entry["artifact_path"], path)

    def test_missing_fields_entry_has_correct_fields(self):
        data = dict(MIN_SCHEMA_MONSTER)
        del data["size"]
        _write_monster_file(self.module_dir, "skeleton", data)
        result = materialize_source_monsters(self.module_dir, ["skeleton"], [])
        entry = result["resolution_log"][0]
        self.assertEqual(entry["ref"], "skeleton")
        self.assertEqual(entry["status"], "unresolved")
        self.assertEqual(entry["reason"], "missing_required_fields")
        self.assertIsNotNone(entry["artifact_path"])
        self.assertTrue(entry["artifact_path"].endswith("skeleton.json"))

    def test_empty_refs_empty_log(self):
        result = materialize_source_monsters(self.module_dir, [], [])
        self.assertEqual(result["resolution_log"], [])

    def test_deterministic_log_identical(self):
        _write_monster_file(self.module_dir, "skeleton", MIN_SCHEMA_MONSTER)
        refs = ["skeleton", "were-possum"]
        r1 = materialize_source_monsters(self.module_dir, refs, [])
        r2 = materialize_source_monsters(self.module_dir, refs, [])
        self.assertEqual(r1["resolution_log"], r2["resolution_log"])


# ---------------------------------------------------------------------------
# Encounter binding contract
# ---------------------------------------------------------------------------


class TestEncounterBindingContract(unittest.TestCase):
    """Define the contract for bind_encounter_monsters()."""

    RESOLVED_LOG = [
        {"ref": "Kenku", "status": "reused", "reason": "reused", "artifact_path": "/tmp/monsters/kenku.json"},
        {"ref": "Alhoon", "status": "reused", "reason": "reused", "artifact_path": "/tmp/monsters/alhoon.json"},
    ]
    UNRESOLVED_LOG = [
        {"ref": "Alhoon", "status": "unresolved", "reason": "file_not_found", "artifact_path": "/tmp/monsters/alhoon.json"},
        {"ref": "Charion", "status": "unresolved", "reason": "file_not_found", "artifact_path": "/tmp/monsters/charion.json"},
    ]
    MIXED_LOG = [
        {"ref": "Kenku", "status": "reused", "reason": "reused", "artifact_path": "/tmp/monsters/kenku.json"},
        {"ref": "Alhoon", "status": "unresolved", "reason": "file_not_found", "artifact_path": "/tmp/monsters/alhoon.json"},
        {"ref": "Charion", "status": "unresolved", "reason": "file_not_found", "artifact_path": "/tmp/monsters/charion.json"},
    ]

    def test_binding_report_contains_required_keys(self):
        result = bind_encounter_monsters([], [])
        required = {"status", "seeds_planned", "seeds_bound", "seeds_unresolved", "seeds_unbound", "bindings"}
        self.assertTrue(required.issubset(result.keys()), f"Missing keys: {required - set(result.keys())}")

    def test_status_is_str(self):
        result = bind_encounter_monsters([], [])
        self.assertIsInstance(result["status"], str)

    def test_count_fields_are_ints(self):
        result = bind_encounter_monsters([], [])
        for key in ("seeds_planned", "seeds_bound", "seeds_unresolved", "seeds_unbound"):
            with self.subTest(key=key):
                self.assertIsInstance(result[key], int)

    def test_bindings_is_list(self):
        result = bind_encounter_monsters([], [])
        self.assertIsInstance(result["bindings"], list)

    def test_empty_input_skipped(self):
        result = bind_encounter_monsters([], [])
        self.assertIn(result["status"], {"skipped"})
        self.assertEqual(result["seeds_planned"], 0)
        self.assertEqual(result["bindings"], [])

    def test_resolvable_refs_produce_bindings(self):
        seeds = ["Rookery: Kenku ambush"]
        result = bind_encounter_monsters(seeds, self.RESOLVED_LOG)
        self.assertGreaterEqual(result["seeds_planned"], 1)
        self.assertGreaterEqual(result["seeds_bound"], 1)
        self.assertGreaterEqual(len(result["bindings"]), 1)
        for b in result["bindings"]:
            self.assertIn("seed", b)
            self.assertIn("monster_ref", b)

    def test_unresolvable_refs_produce_diagnostics(self):
        seeds = ["Hidden Archive: Alhoon encounter"]
        result = bind_encounter_monsters(seeds, self.UNRESOLVED_LOG)
        self.assertGreaterEqual(result["seeds_planned"], 1)
        self.assertGreaterEqual(result["seeds_unresolved"], 1)

    def test_mixed_bindings_and_diagnostics(self):
        seeds = [
            "Rookery: Kenku ambush",
            "Hidden Archive: Alhoon encounter",
        ]
        result = bind_encounter_monsters(seeds, self.MIXED_LOG)
        self.assertEqual(result["seeds_planned"], 2)
        self.assertGreaterEqual(result["seeds_bound"], 1)
        self.assertGreaterEqual(result["seeds_unresolved"], 1)
        self.assertGreaterEqual(len(result["bindings"]), 1)

    def test_no_ref_match_pass_through(self):
        seeds = ["Unknown lair: mystery monster"]
        result = bind_encounter_monsters(seeds, self.RESOLVED_LOG)
        self.assertGreaterEqual(result["seeds_planned"], 1)
        self.assertGreaterEqual(result["seeds_unresolved"], 0)

    def test_unbound_seeds_report_count(self):
        seeds = ["Unknown lair: mystery monster"]
        result = bind_encounter_monsters(seeds, self.RESOLVED_LOG)
        self.assertEqual(result["seeds_unbound"], 1)
        self.assertEqual(result["seeds_bound"], 0)
        self.assertEqual(result["seeds_unresolved"], 0)
        self.assertEqual(result["seeds_planned"], 1)

    def test_deterministic_binding(self):
        seeds = ["Rookery: Kenku ambush"]
        r1 = bind_encounter_monsters(seeds, self.RESOLVED_LOG)
        r2 = bind_encounter_monsters(seeds, self.RESOLVED_LOG)
        self.assertEqual(r1, r2)

    def test_unresolved_ref_attached_to_seed(self):
        seeds = ["Hidden Archive: Alhoon encounter"]
        result = bind_encounter_monsters(seeds, self.UNRESOLVED_LOG)
        self.assertEqual(len(result["bindings"]), 1)
        b = result["bindings"][0]
        self.assertEqual(b["status"], "unresolved")
        self.assertIn("Alhoon", b["unresolved_refs"])
        self.assertIsNone(b["monster_ref"])

    def test_all_seeds_represented_in_bindings(self):
        seeds = [
            "Rookery: Kenku ambush",
            "Hidden Archive: Alhoon encounter",
            "Tomb of the Unknown",
        ]
        result = bind_encounter_monsters(seeds, self.MIXED_LOG)
        self.assertEqual(len(result["bindings"]), 3)
        seed_texts = {b["seed"] for b in result["bindings"]}
        for s in seeds:
            self.assertIn(s, seed_texts)

    def test_bound_seed_matches_correct_ref(self):
        seeds = ["Rookery: Kenku ambush"]
        result = bind_encounter_monsters(seeds, self.MIXED_LOG)
        self.assertEqual(len(result["bindings"]), 1)
        b = result["bindings"][0]
        self.assertEqual(b["status"], "bound")
        self.assertEqual(b["monster_ref"], "Kenku")
        self.assertIsNotNone(b["artifact_path"])
        self.assertEqual(b["unresolved_refs"], [])

    def test_unresolved_ref_does_not_leak_into_bound_fields(self):
        seeds = ["Hidden Archive: Alhoon encounter"]
        result = bind_encounter_monsters(seeds, self.UNRESOLVED_LOG)
        b = result["bindings"][0]
        self.assertEqual(b["status"], "unresolved")
        self.assertIsNone(b["monster_ref"], "unresolved must not present a fake monster_ref")
        self.assertIsNone(b["artifact_path"], "unresolved must not present a fake artifact_path")
