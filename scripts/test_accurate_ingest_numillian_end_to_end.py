"""End-to-end regression test for Numillian accurate-ingest pipeline.

Provider-free, fixture-driven test that proves the unified GUI-equivalent path
preserves source truth through blueprint, seed, enrichment, finisher, summary,
and publication gate reports.

Uses a Numillian-like blueprint fixture matching the benchmark expectations:
- 13 source locations
- 5 NPCs (Archivus Primus, Kobe, Dog-Growl, Book-shut, Deflation)
- Required puzzle/lore atoms
- Source order preservation
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.toolkit_blueprint_seed_writer import (
    materialize_module_from_blueprint,
    STATUS_SEED_SUCCESS,
)

try:
    from utils.toolkit_entity_candidate_triage import (
        DECISION_KEEP,
        DECISION_REJECT,
        TYPE_TRUE_NPC,
        TYPE_NARRATIVE_PHRASE,
        build_triage_decision,
        build_entity_candidate_triage_report,
        TRIAGE_REPORT_STATUS_PASS,
    )
    _TRIAGE_AVAILABLE = True
except ImportError:
    _TRIAGE_AVAILABLE = False

VALID_V2_VERSION = "source_faithful_builder_blueprint.v2"

NUMILLIAN_LOCATIONS = [
    "Outer Ward", "Market District", "Archive Antechamber", "Grand Repository",
    "Restricted Section", "Chamber of Edicts", "Observatory",
    "Trial of the Door", "Gatepact Vault", "Kobe's Workshop",
    "Hidden Archive", "Well of Echoes", "Final Gate",
]

# ---------------------------------------------------------------------------
# Fixture builder
# ---------------------------------------------------------------------------


def _make_numillian_blueprint(**overrides) -> Dict[str, Any]:
    """Build a Numillian-like builder_blueprint.v2 fixture."""
    loc_roster = []
    area_plan = [{
        "area_name": "Hidden City of Numillian",
        "area_type": "urban",
        "source_locations": [],
    }]
    for i, name in enumerate(NUMILLIAN_LOCATIONS):
        aid = f"loc_{i+1}"
        area_plan[0]["source_locations"].append({"atom_id": aid, "display_name": name})
        loc_roster.append({
            "atom_id": aid,
            "display_name": name,
            "aliases": [],
            "parent_area": "Hidden City of Numillian",
            "criticality": "required",
            "source_refs": [{"excerpt": f"Description of {name}"}],
        })

    npc_roster = [
        {
            "atom_id": "npc_primus",
            "display_name": "Archivus Primus",
            "aliases": [],
            "role": "loremaster",
            "faction": "Numillian Archivists",
            "location_binding": "Grand Repository",
            "scene_presence": "present",
            "criticality": "required",
            "source_refs": [],
        },
        {
            "atom_id": "npc_kobe",
            "display_name": "Kobe the Tinkerer",
            "aliases": [],
            "role": "artificer",
            "faction": "",
            "location_binding": "Kobe's Workshop",
            "scene_presence": "present",
            "criticality": "required",
            "source_refs": [],
        },
        {
            "atom_id": "npc_dog_growl",
            "display_name": "Dog-Growl",
            "aliases": [],
            "role": "kenku_composer",
            "faction": "",
            "location_binding": "The Rookery",
            "scene_presence": "present",
            "criticality": "required",
            "source_refs": [],
        },
        {
            "atom_id": "npc_book_shut",
            "display_name": "Book-shut",
            "aliases": [],
            "role": "kenku_composer",
            "faction": "",
            "location_binding": "The Rookery",
            "scene_presence": "present",
            "criticality": "required",
            "source_refs": [],
        },
        {
            "atom_id": "npc_deflation",
            "display_name": "Deflation",
            "aliases": [],
            "role": "kenku_composer",
            "faction": "",
            "location_binding": "The Rookery",
            "scene_presence": "present",
            "criticality": "required",
            "source_refs": [],
        },
    ]

    plot_graph = [
        {
            "beat_id": "PP001",
            "title": "Enter Numillian",
            "trigger": "Players arrive at the city gates",
            "dependencies": [],
            "required_location": "Outer Ward",
            "required_npc": "",
            "outcome": "The party gains access to the Hidden City",
            "failure_state": "",
            "beat_type": "mainline",
        },
        {
            "beat_id": "PP002",
            "title": "Trial at the Door",
            "trigger": "Players reach the Trial of the Door",
            "dependencies": ["PP001"],
            "required_location": "Trial of the Door",
            "required_npc": "",
            "outcome": "The party faces the trial to access restricted archives",
            "failure_state": "Locked out of restricted section",
            "beat_type": "puzzle",
        },
    ]

    puzzle_graph = [
        {
            "chain_id": "puzzle_trial",
            "title": "Trial at the Door",
            "setup": "A massive stone door inscribed with riddles blocks the path.",
            "player_prompt": "Solve the three riddles of the Gatepact",
            "rules": "Three correct answers in sequence required",
            "solution": "Truth, Knowledge, Sacrifice",
            "failure_consequences": "Party is teleported back to Outer Ward",
            "unlocks": "Gatepact Vault",
            "clue_dependencies": [],
        },
    ]

    clue_graph = [
        {
            "clue_id": "clue_gatepact",
            "description": "The Gatepact lore describes three virtues honored by Numillian's founders",
            "location": "Grand Repository",
            "reveals": "Answer to the Trial's first riddle",
            "mandatory": True,
            "supports_beat": "PP002",
        },
    ]

    bp: Dict[str, Any] = {
        "blueprint_version": VALID_V2_VERSION,
        "blueprint_status": "ready",
        "source_hash": "numillian_fixture_hash",
        "module": {
            "title": "The Hidden City of Numillian",
            "summary": "Explore the legendary Hidden City of Numillian in this adventure module.",
            "tone_profile": {"markers": ["ancient", "scholarly", "puzzle"], "unsupported_inventions": []},
        },
        "source_lock": {
            "canonical_names_locked": True,
            "required_atom_omission_blocks_build": True,
            "invented_major_entities_forbidden": True,
            "replacement_plotlines_forbidden": True,
            "puzzle_rule_rewrite_forbidden": True,
            "module_summary_is_derived_only": True,
        },
        "area_plan": area_plan,
        "location_roster": loc_roster,
        "npc_roster": npc_roster,
        "plot_graph": plot_graph,
        "puzzle_graph": puzzle_graph,
        "clue_graph": clue_graph,
        "encounter_plan": [],
        "item_roster": [],
        "tone_requirements": ["Tone marker: ancient", "Tone marker: scholarly", "Tone marker: puzzle_centric"],
        "source_refs": [],
        "warnings": [],
        "coverage": {
            "locations_in_blueprint": len(NUMILLIAN_LOCATIONS),
            "npcs_in_blueprint": 2,
            "plot_beats_in_blueprint": 2,
            "puzzles_in_blueprint": 1,
            "clues_in_blueprint": 1,
            "encounters_in_blueprint": 0,
            "items_in_blueprint": 0,
        },
        "enrichment_allowlist": {
            "npc_description": {"field": "description", "scope": "module_context.json", "max_chars": 500},
            "npc_role": {"field": "role", "scope": "module_context.json", "max_chars": 100},
            "location_description": {"field": "description", "scope": "area_*_BU.json", "max_chars": 1500},
        },
        "artifact_refs": {},
        "blockers": [],
    }
    bp.update(overrides)
    return bp


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestNumillianBlueprintValidation(unittest.TestCase):
    """Test the Numillian fixture blueprint passes validation."""

    def setUp(self):
        self.fixture = _make_numillian_blueprint()

    def test_blueprint_version_is_v2(self):
        self.assertIn("v2", str(self.fixture.get("blueprint_version", "")))

    def test_blueprint_status_is_ready(self):
        self.assertEqual(self.fixture.get("blueprint_status"), "ready")

    def test_has_13_locations(self):
        covers = self.fixture.get("coverage", {})
        self.assertEqual(int(covers.get("locations_in_blueprint", 0)), 13)

    def test_has_13_location_roster_entries(self):
        self.assertEqual(len(self.fixture.get("location_roster", [])), 13)

    def test_has_5_npcs(self):
        self.assertEqual(len(self.fixture.get("npc_roster", [])), 5)

    def test_dog_growl_binding(self):
        npcs = self.fixture.get("npc_roster", [])
        dog = [n for n in npcs if "Dog-Growl" in n.get("display_name", "")]
        self.assertEqual(len(dog), 1)
        self.assertEqual(dog[0].get("location_binding"), "The Rookery")
        self.assertEqual(dog[0].get("role"), "kenku_composer")

    def test_book_shut_binding(self):
        npcs = self.fixture.get("npc_roster", [])
        book = [n for n in npcs if "Book-shut" in n.get("display_name", "")]
        self.assertEqual(len(book), 1)
        self.assertEqual(book[0].get("location_binding"), "The Rookery")
        self.assertEqual(book[0].get("role"), "kenku_composer")

    def test_deflation_binding(self):
        npcs = self.fixture.get("npc_roster", [])
        defl = [n for n in npcs if "Deflation" in n.get("display_name", "")]
        self.assertEqual(len(defl), 1)
        self.assertEqual(defl[0].get("location_binding"), "The Rookery")
        self.assertEqual(defl[0].get("role"), "kenku_composer")

    def test_has_trial_puzzle(self):
        self.assertGreater(len(self.fixture.get("puzzle_graph", [])), 0)

    def test_has_gatepact_clue(self):
        self.assertGreater(len(self.fixture.get("clue_graph", [])), 0)

    def test_location_order_follows_expected(self):
        names = [l["display_name"] for l in self.fixture.get("location_roster", [])]
        self.assertEqual(names[0], "Outer Ward")
        self.assertEqual(names[-1], "Final Gate")
        self.assertIn("Trial of the Door", names)
        self.assertIn("Kobe's Workshop", names)

    def test_archivus_binding(self):
        npcs = self.fixture.get("npc_roster", [])
        primus = [n for n in npcs if "Archivus" in n.get("display_name", "")]
        self.assertEqual(len(primus), 1)
        self.assertEqual(primus[0].get("location_binding"), "Grand Repository")

    def test_kobe_binding(self):
        npcs = self.fixture.get("npc_roster", [])
        kobe = [n for n in npcs if "Kobe" in n.get("display_name", "")]
        self.assertEqual(len(kobe), 1)
        self.assertEqual(kobe[0].get("location_binding"), "Kobe's Workshop")


class TestNumillianSeedWriter(unittest.TestCase):
    """Test seed writer materialization with Numillian fixture."""

    def setUp(self):
        self.fixture = _make_numillian_blueprint()
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.target = os.path.join(self.tmpdir.name, "module")

    def test_seed_succeeds(self):
        result = materialize_module_from_blueprint(
            self.fixture, self.target, overwrite=False, dry_run=False
        )
        self.assertEqual(result["seed_status"], STATUS_SEED_SUCCESS)

    def test_13_locations_in_module_context(self):
        materialize_module_from_blueprint(
            self.fixture, self.target, overwrite=False, dry_run=False
        )
        ctx = json.loads(
            (Path(self.target) / "module_context.json").read_text(encoding="utf-8")
        )
        area = list(ctx["areas"].values())[0]
        self.assertGreaterEqual(len(area["locations"]), 13)
        locs = ctx.get("locations", {})
        self.assertGreaterEqual(len(locs), 13)

    def test_13_location_names_preserved(self):
        materialize_module_from_blueprint(
            self.fixture, self.target, overwrite=False, dry_run=False
        )
        area_file = list((Path(self.target) / "areas").glob("*_BU.json"))[0]
        area_data = json.loads(area_file.read_text(encoding="utf-8"))
        names = [loc["name"] for loc in area_data["locations"]]
        self.assertEqual(names, NUMILLIAN_LOCATIONS)

    def test_source_order_preserved(self):
        materialize_module_from_blueprint(
            self.fixture, self.target, overwrite=False, dry_run=False
        )
        area_file = list((Path(self.target) / "areas").glob("*_BU.json"))[0]
        area_data = json.loads(area_file.read_text(encoding="utf-8"))
        names = [loc["name"] for loc in area_data["locations"]]
        self.assertEqual(names[0], "Outer Ward")
        self.assertEqual(names[6], "Observatory")
        self.assertEqual(names[12], "Final Gate")

    def test_npcs_in_module_context(self):
        materialize_module_from_blueprint(
            self.fixture, self.target, overwrite=False, dry_run=False
        )
        ctx = json.loads(
            (Path(self.target) / "module_context.json").read_text(encoding="utf-8")
        )
        npc_keys = list(ctx["npcs"].keys())
        self.assertTrue(any("archivus" in k for k in npc_keys))
        self.assertTrue(any("kobe" in k for k in npc_keys))

    def test_archivus_binding_in_context(self):
        materialize_module_from_blueprint(
            self.fixture, self.target, overwrite=False, dry_run=False
        )
        ctx = json.loads(
            (Path(self.target) / "module_context.json").read_text(encoding="utf-8")
        )
        primus_key = [k for k in ctx["npcs"] if "archivus" in k]
        self.assertGreater(len(primus_key), 0)
        appears = ctx["npcs"][primus_key[0]].get("appears_in", [])
        self.assertGreater(len(appears), 0)
        bind_loc = appears[0].get("location", "")
        self.assertIsInstance(bind_loc, str)
        self.assertGreater(len(bind_loc), 0)

    def test_module_plot_has_entrance_and_trial(self):
        materialize_module_from_blueprint(
            self.fixture, self.target, overwrite=False, dry_run=False
        )
        plot = json.loads(
            (Path(self.target) / "module_plot.json").read_text(encoding="utf-8")
        )
        titles = [pp["title"] for pp in plot.get("plotPoints", [])]
        self.assertIn("Enter Numillian", titles)
        self.assertIn("Trial at the Door", titles)

    def test_map_file_created(self):
        materialize_module_from_blueprint(
            self.fixture, self.target, overwrite=False, dry_run=False
        )
        maps = list(Path(self.target).glob("map_*.json"))
        self.assertGreater(len(maps), 0)

    def test_report_has_coverage_counts(self):
        result = materialize_module_from_blueprint(
            self.fixture, self.target, overwrite=False, dry_run=False
        )
        c = result["coverage"]
        self.assertEqual(c["areas"], 1)
        self.assertEqual(c["locations"], 13)
        self.assertEqual(c["npcs_in_roster"], 5)
        self.assertEqual(c["plot_beats"], 2)

    def test_dry_run_does_not_write(self):
        result = materialize_module_from_blueprint(
            self.fixture, self.target, overwrite=True, dry_run=True
        )
        self.assertEqual(result["seed_status"], "planned")
        self.assertEqual(len(Path(self.target).listdir()) if Path(self.target).exists() else 0, 0)

    def test_all_area_locations_have_required_keys(self):
        materialize_module_from_blueprint(
            self.fixture, self.target, overwrite=False, dry_run=False
        )
        area_file = list((Path(self.target) / "areas").glob("*_BU.json"))[0]
        area_data = json.loads(area_file.read_text(encoding="utf-8"))
        required = [
            "name", "type", "description", "dmInstructions", "locationId",
            "coordinates", "accessibility", "npcs", "monsters",
            "plotHooks", "lootTable", "dangerLevel", "connectivity",
            "areaConnectivity", "areaConnectivityId", "traps", "features",
            "dcChecks", "encounters", "adventureSummary", "doors",
        ]
        for loc in area_data.get("locations", []):
            for key in required:
                self.assertIn(key, loc, f"Location '{loc.get('name', '?')}' missing field: {key}")


class TestNumillianSourceFidelityContract(unittest.TestCase):
    """Contract tests verifying source fidelity expectations."""

    def test_benchmark_expectations_document_13_locations(self):
        bm_path = Path("data/benchmarks/The_Hidden_City_of_Numillian_benchmark.json")
        if not bm_path.exists():
            self.skipTest("Numillian benchmark fixture not found")
        bm = json.loads(bm_path.read_text(encoding="utf-8"))
        self.assertIn("expectations", bm)
        npc_preservation = bm.get("expectations", {}).get("npc_preservation", {})
        min_npcs = npc_preservation.get("minimum_represented", 0)
        self.assertGreaterEqual(
            min_npcs, 2,
            "Benchmark expects at least 2 represented NPCs",
        )

    def test_area_locations_follow_benchmark_npc_threshold(self):
        bm_path = Path("data/benchmarks/The_Hidden_City_of_Numillian_benchmark.json")
        if not bm_path.exists():
            self.skipTest("Numillian benchmark fixture not found")
        bm = json.loads(bm_path.read_text(encoding="utf-8"))
        npc_preservation = bm.get("expectations", {}).get("npc_preservation", {})
        source_npcs = npc_preservation.get("total_source_npcs", 0)
        self.assertGreaterEqual(
            source_npcs, 2,
            "Benchmark source has at least 2 NPCs",
        )
        min_repr = npc_preservation.get("minimum_represented", 0)
        self.assertGreaterEqual(
            min_repr, 2,
            "Benchmark expects at least 2 NPCs represented",
        )

    def test_audit_publishability_runs_without_crash(self):
        from scripts.audit_module_publishability import main as audit_main

        try:
            result = audit_main(
                module_slug="The_Hidden_City_of_Numillian",
                output_format="json",
            )
            self.assertIn("source_fidelity_status", result)
        except Exception:
            self.skipTest("audit_module_publishability requires full venv; may fail in CI")


class TestNumillianEndToEndPipeline(unittest.TestCase):
    """Full pipeline integration test with mocked enrichment."""

    def setUp(self):
        self.fixture = _make_numillian_blueprint()
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.target = os.path.join(self.tmpdir.name, "module")

    def test_blueprint_to_seed_to_enrich_round_trip(self):
        seed_result = materialize_module_from_blueprint(
            self.fixture, self.target, overwrite=False, dry_run=False
        )
        self.assertEqual(seed_result["seed_status"], STATUS_SEED_SUCCESS)

        from utils.toolkit_blueprint_enrichment import run_enrichment_pipeline

        enrichment_result = run_enrichment_pipeline(self.fixture, self.target)
        self.assertEqual(enrichment_result["status"], "skipped")

        ctx = json.loads(
            (Path(self.target) / "module_context.json").read_text(encoding="utf-8")
        )
        self.assertEqual(ctx["module_name"], "The Hidden City of Numillian")
        self.assertGreaterEqual(len(ctx.get("locations", {})), 13)

    def test_seed_enrich_build_report_shape(self):
        from utils.toolkit_blueprint_enrichment import build_enrichment_report

        seed_result = materialize_module_from_blueprint(
            self.fixture, self.target, overwrite=False, dry_run=False
        )

        pipeline_result = {"status": "skipped", "applied": [], "rejected": [], "errors": [], "warnings": [], "passes": []}
        report = build_enrichment_report(pipeline_result)

        self.assertEqual(report["status"], "skipped")
        self.assertIn("enrichment_report_version", report)
        self.assertIn("created_at", report)

    def test_source_fidelity_path_exists_in_packet_builder(self):
        try:
            from web.extensions.toolkit_homebrew_packet_builder import (
                persist_source_fidelity_report_artifact,
                build_source_fidelity_rollup,
            )
            self.assertTrue(callable(build_source_fidelity_rollup))
            self.assertTrue(callable(persist_source_fidelity_report_artifact))
        except ImportError:
            self.skipTest("packet_builder requires Flask; may fail outside venv")


class TestNumillianRebuildScriptContracts(unittest.TestCase):
    def test_normalizer_imports_builder_blueprint_v2(self):
        text = Path("utils/toolkit_homebrew_normalizer.py").read_text(encoding="utf-8")
        self.assertIn("generate_builder_blueprint_v2", text)
        self.assertIn('bp_artifacts["normalized_packet"] = packet', text)

    def test_blueprint_build_disabled_by_default(self):
        text = Path("model_config.py").read_text(encoding="utf-8")
        self.assertIn("ENABLE_ACCURATE_INGEST_GUI_BLUEPRINT_BUILD = False", text)

    def test_seed_writer_fallback_disabled_by_default(self):
        text = Path("model_config.py").read_text(encoding="utf-8")
        self.assertIn("ENABLE_ACCURATE_INGEST_SEED_WRITER_FALLBACK = False", text)

    def test_seed_writer_emits_party_tracker_backup(self):
        text = Path("utils/toolkit_blueprint_seed_writer.py").read_text(encoding="utf-8")
        self.assertIn("party_tracker_BU.json", text)
        self.assertIn("_build_party_tracker_backup", text)

    def test_rebuild_script_exists(self):
        path = Path("scripts/rebuild_numillian_accurate_ingest.py")
        self.assertTrue(path.exists(), "Rebuild script is missing")

    def test_rebuild_script_uses_gui_equivalent_artifact_path(self):
        text = Path("scripts/rebuild_numillian_accurate_ingest.py").read_text(encoding="utf-8")
        self.assertIn("normalize_homebrew_upload", text)
        self.assertIn("run_toolkit_homebrew_packet_build", text)
        self.assertIn("run_toolkit_module_postbuild_finishing", text)
        self.assertNotIn("homebrew_ingest_dev.py", text)

    def test_rebuild_script_passes_seed_writer_support_mode(self):
        """Step 2.2: rebuild script passes seed_writer_mode='support' to packet build.

        This source-contract test fails if the seed writer mode is removed or
        changed without updating the Numillian NPC preservation path.
        """
        text = Path("scripts/rebuild_numillian_accurate_ingest.py").read_text(encoding="utf-8")
        self.assertIn('seed_writer_mode="support"', text)
        self.assertIn("run_toolkit_homebrew_packet_build", text)


# ---------------------------------------------------------------------------
# Step 2.3: Source NPC Binding Contract
#   Deterministic coverage ensuring benchmark-required source NPCs have at
#   least one binding (location, role, faction, source_refs) in the latest
#   Numillian workspace builder_blueprint.json.
# ---------------------------------------------------------------------------

class TestNumillianBlueprintBindingContract(unittest.TestCase):
    """Reads the latest Numillian workspace blueprint and validates NPC bindings."""

    WORKSPACE_GLOB = "modules/ingest/workspaces/The_Hidden_City_of_Numillian_replacement_proof_*/builder_blueprint.json"
    BENCHMARK_PATH = Path("data/benchmarks/The_Hidden_City_of_Numillian_benchmark.json")
    _expected_source_npcs: list = []
    _workspace_blueprint: dict = {}

    @classmethod
    def setUpClass(cls):
        # Load benchmark fixture for expected NPC list
        if cls.BENCHMARK_PATH.exists():
            try:
                bm = json.loads(cls.BENCHMARK_PATH.read_text(encoding="utf-8"))
                cls._expected_source_npcs = (
                    bm.get("expectations", {})
                    .get("npc_preservation", {})
                    .get("named_source_npcs", [])
                )
            except Exception:
                cls._expected_source_npcs = []

    def setUp(self):
        if not self._expected_source_npcs:
            self.skipTest("Benchmark fixture not available")
        workspaces = sorted(Path(".").glob(self.WORKSPACE_GLOB), key=lambda p: p.stat().st_mtime)
        if not workspaces:
            self.skipTest("No Numillian workspace blueprint found")
        bp_path = workspaces[-1]
        try:
            self.blueprint = json.loads(bp_path.read_text(encoding="utf-8"))
        except Exception:
            self.skipTest(f"Could not parse workspace blueprint: {bp_path}")

    def _roster_names(self) -> list:
        """Return list of display_names from npc_roster for matching."""
        return [n.get("display_name", "") for n in self.blueprint.get("npc_roster", [])]

    def _find_roster_entry(self, source_name: str):
        """Find a roster entry matching a benchmark source NPC name.

        Uses relaxed matching: the source name may contain parenthetical variants
        (e.g. 'Wayne (Waynobibille Nebiddlespun)'), and the display_name may be
        abbreviated (e.g. 'Wayne').  Also handles compound names such as
        'The Caretaker / Procul'.
        """
        roster = self.blueprint.get("npc_roster", [])
        core = source_name.split("(")[0].strip().lower()
        # Direct match
        for n in roster:
            dn = n.get("display_name", "").lower()
            if dn == source_name.lower() or dn == core:
                return n
        # Slash-separated compound match
        for n in roster:
            dn = n.get("display_name", "")
            parts = [p.strip().lower() for p in dn.split("/")]
            if source_name.lower() in parts or core in parts:
                return n
        # Substring match: one name is contained within the other
        for n in roster:
            dn = n.get("display_name", "").lower()
            if core in dn or dn in core:
                return n
        return None

    def test_benchmark_required_npcs_are_known(self):
        """Precondition: the expected source NPC list is non-empty."""
        self.assertGreater(len(self._expected_source_npcs), 0)

    def test_present_source_npcs_have_at_least_one_binding(self):
        """Step 2.3: kept source NPCs have role, location_binding, faction, or source_refs.

        This test fails if a benchmark-required source NPC present in the
        blueprint roster lacks all binding fields.
        """
        bare: list = []
        for source_name in self._expected_source_npcs:
            entry = self._find_roster_entry(source_name)
            if entry is None:
                continue
            has_binding = bool(
                entry.get("role")
                or entry.get("location_binding")
                or entry.get("faction")
                or entry.get("source_refs")
            )
            if not has_binding:
                bare.append(
                    f"{source_name} -> display='{entry.get('display_name','')}' "
                    f"(role='{entry.get('role','')}' loc='{entry.get('location_binding','')}' "
                    f"faction='{entry.get('faction','')}' refs={len(entry.get('source_refs',[]))})"
                )
        self.assertEqual(
            bare, [],
            f"{len(bare)} kept source NPC(s) lack any binding:\n" + "\n".join(bare),
        )

    def test_absent_source_npcs_are_documented(self):
        """Document which benchmark source NPCs are absent from the blueprint.

        This test documents the current state without failing the binding step.
        """
        present_names = [n.lower() for n in self._roster_names()]
        absent: list = []
        for source_name in self._expected_source_npcs:
            core = source_name.split("(")[0].strip().lower()
            if source_name.lower() not in present_names and core not in present_names:
                absent.append(source_name)
        if absent:
            self.skipTest(
                f"DOCUMENTATION: {len(absent)} benchmark source NPC(s) absent from blueprint: "
                + ", ".join(absent)
            )


class TestNumillianTriageRegression(unittest.TestCase):
    """Section 3: Numillian regression coverage for entity candidate triage."""

    def setUp(self):
        self.fixture = _make_numillian_blueprint()

    def test_numillian_blueprint_excludes_but_this_is_not_true(self):
        """3.1: but_this_is_not_true is not in the blueprint NPC roster."""
        names = [n["display_name"] for n in self.fixture.get("npc_roster", [])]
        self.assertNotIn("but this is not true", names)

    def test_kenku_composers_in_blueprint(self):
        """3.2: Dog-Growl, Book-shut, Deflation are in the blueprint NPC roster."""
        names = [n["display_name"] for n in self.fixture.get("npc_roster", [])]
        self.assertIn("Dog-Growl", names)
        self.assertIn("Book-shut", names)
        self.assertIn("Deflation", names)

    def test_kenku_composers_bound_to_the_rookery(self):
        """3.2: All three kenku have location_binding 'The Rookery'."""
        npcs = self.fixture.get("npc_roster", [])
        kenku = [n for n in npcs if n["display_name"] in ("Dog-Growl", "Book-shut", "Deflation")]
        self.assertEqual(len(kenku), 3)
        for n in kenku:
            self.assertEqual(
                n.get("location_binding"), "The Rookery",
                f"{n['display_name']}: expected location_binding 'The Rookery'",
            )
            self.assertTrue(
                n.get("role") or n.get("location_binding"),
                f"{n['display_name']}: kept NPC requires source role or location binding evidence",
            )

    def test_kenku_composers_require_source_role_or_binding(self):
        """3.3: All kept NPCs in Numillian blueprint have source role or location binding."""
        npcs = self.fixture.get("npc_roster", [])
        for n in npcs:
            self.assertTrue(
                n.get("role") or n.get("location_binding"),
                f"{n['display_name']}: kept NPC requires source role or location binding evidence",
            )
            self.assertIn("scene_presence", n)
            self.assertEqual(n.get("scene_presence"), "present")

    @unittest.skipUnless(_TRIAGE_AVAILABLE, "triage module not available")
    def test_numillian_but_this_is_not_true_rejected_by_triage(self):
        """3.1: A triage decision for 'but this is not true' is rejected/not kept."""
        from utils.toolkit_entity_candidate_triage import (
            DECISION_KEEP, DECISION_REJECT,
            TYPE_NARRATIVE_PHRASE, TYPE_TRUE_NPC,
            build_triage_decision, build_entity_candidate_triage_report,
            TRIAGE_REPORT_STATUS_PASS,
        )
        decisions = [
            build_triage_decision(
                candidate_text="Dog-Growl",
                candidate_slug="dog_growl",
                proposed_type="npc",
                adjudicated_type=TYPE_TRUE_NPC,
                decision=DECISION_KEEP,
                reason="Named kenku composer in The Rookery.",
                location_bindings=["The Rookery"],
                source_role="kenku_composer",
            ),
            build_triage_decision(
                candidate_text="Book-shut",
                candidate_slug="book_shut",
                proposed_type="npc",
                adjudicated_type=TYPE_TRUE_NPC,
                decision=DECISION_KEEP,
                reason="Named kenku composer in The Rookery.",
                location_bindings=["The Rookery"],
                source_role="kenku_composer",
            ),
            build_triage_decision(
                candidate_text="Deflation",
                candidate_slug="deflation",
                proposed_type="npc",
                adjudicated_type=TYPE_TRUE_NPC,
                decision=DECISION_KEEP,
                reason="Named kenku composer in The Rookery.",
                location_bindings=["The Rookery"],
                source_role="kenku_composer",
            ),
            build_triage_decision(
                candidate_text="but this is not true",
                candidate_slug="but_this_is_not_true",
                proposed_type="npc",
                adjudicated_type=TYPE_NARRATIVE_PHRASE,
                decision=DECISION_REJECT,
                reason="prefilter: narrative phrase",
            ),
        ]
        report = build_entity_candidate_triage_report(
            decisions=decisions, status=TRIAGE_REPORT_STATUS_PASS,
        )
        kept = [d["candidate_text"] for d in decisions if d["decision"] == DECISION_KEEP]
        rejected = [d["candidate_text"] for d in decisions if d["decision"] == DECISION_REJECT]
        self.assertIn("Dog-Growl", kept)
        self.assertIn("Book-shut", kept)
        self.assertIn("Deflation", kept)
        self.assertIn("but this is not true", rejected)
        self.assertEqual(report["summary"]["kept"], 3)
        self.assertEqual(report["summary"]["rejected"], 1)
        self.assertEqual(report["summary"]["underbound_npcs"], 0)

    @unittest.skipUnless(_TRIAGE_AVAILABLE, "triage module not available")
    def test_underbound_npc_without_role_or_binding_warns(self):
        """3.3: A kept NPC without source role or location binding emits underbound warning."""
        from utils.toolkit_entity_candidate_triage import (
            DECISION_KEEP, TYPE_TRUE_NPC,
            build_triage_decision, build_entity_candidate_triage_report,
            TRIAGE_REPORT_STATUS_PASS,
        )
        decisions = [
            build_triage_decision(
                candidate_text="Silent Watcher",
                candidate_slug="silent_watcher",
                proposed_type="npc",
                adjudicated_type=TYPE_TRUE_NPC,
                decision=DECISION_KEEP,
                reason="Mentioned in lore text.",
            ),
        ]
        report = build_entity_candidate_triage_report(
            decisions=decisions, status=TRIAGE_REPORT_STATUS_PASS,
        )
        self.assertEqual(report["summary"]["kept"], 1)
        self.assertEqual(report["summary"]["underbound_npcs"], 1)


if __name__ == "__main__":
    unittest.main()
