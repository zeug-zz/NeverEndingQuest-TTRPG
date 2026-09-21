#!/usr/bin/env python3
"""Unit tests for semantic publication probe harness."""

import json
import tempfile
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from scripts.module_semantic_probe_harness import (
    _expected_locations_from_sources,
    _normalize_hidden_reveal_location,
    run_module_semantic_probes,
)


class TestModuleSemanticProbeHarness(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _write_module(self, slug: str, module_context: dict, module_plot: dict) -> Path:
        module_dir = self.temp_dir / slug
        (module_dir / "areas").mkdir(parents=True, exist_ok=True)
        with open(module_dir / "module_context.json", "w", encoding="utf-8") as handle:
            json.dump(module_context, handle, indent=2)
        with open(module_dir / "module_plot.json", "w", encoding="utf-8") as handle:
            json.dump(module_plot, handle, indent=2)
        return module_dir

    def test_travel_probe_fails_for_unresolved_player_facing_phrase(self):
        module_dir = self._write_module(
            "Probe_A",
            {
                "module_name": "Probe_A",
                "semantic_authority": {
                    "version": "v1",
                    "destination_phrases": {
                        "lintars place": {
                            "status": "unresolved",
                            "sources": ["areas/TST001.json#locations[LOC08].aliases"],
                            "player_facing": True,
                            "observed": True,
                            "observation_count": 1,
                            "candidate_location_ids": [],
                        }
                    },
                    "npc_scene_authority": {},
                },
                "continuity": {"cross_module_refs": []},
            },
            {
                "plotPoints": [
                    {
                        "id": "PP001",
                        "location": "LOC08",
                        "description": "The party heads to Lintar's place.",
                    }
                ]
            },
        )

        result = run_module_semantic_probes(module_dir)
        self.assertEqual(result["status"], "fail")
        self.assertTrue(
            any(
                probe.get("failure_class") == "travel_unresolved_destination_phrase"
                for probe in result["probes"]
            )
        )

    def test_travel_probe_fails_for_misrouted_resolved_phrase(self):
        module_dir = self._write_module(
            "Probe_B",
            {
                "module_name": "Probe_B",
                "semantic_authority": {
                    "version": "v1",
                    "destination_phrases": {
                        "main hall": {
                            "status": "resolved",
                            "location_id": "LOC02",
                            "sources": ["areas/TST001.json#locations[LOC01].aliases"],
                            "player_facing": True,
                            "observed": True,
                            "observation_count": 1,
                            "candidate_location_ids": ["LOC02"],
                        }
                    },
                    "npc_scene_authority": {},
                },
                "continuity": {"cross_module_refs": []},
            },
            {
                "plotPoints": [
                    {
                        "id": "PP002",
                        "location": "LOC01",
                        "description": "Return to the main hall.",
                    }
                ]
            },
        )

        result = run_module_semantic_probes(module_dir)
        self.assertEqual(result["status"], "fail")
        self.assertTrue(
            any(
                probe.get("failure_class") == "travel_misrouted_destination_phrase"
                for probe in result["probes"]
            )
        )

    def _scoped_authority(self, destination_row):
        return {
            "version": "v1",
            "location_index": {
                "HV001:K04": {
                    "location_id": "K04",
                    "raw_location_id": "K04",
                    "scoped_location_id": "HV001:K04",
                    "area_id": "HV001",
                },
                "HV001:K05": {
                    "location_id": "K05",
                    "raw_location_id": "K05",
                    "scoped_location_id": "HV001:K05",
                    "area_id": "HV001",
                },
            },
            "destination_phrases": {"softstone": destination_row},
            "npc_scene_authority": {},
        }

    def test_scoped_location_source_reference_passes(self):
        module_dir = self._write_module(
            "Probe_Scoped",
            {
                "module_name": "Probe_Scoped",
                "semantic_authority": self._scoped_authority(
                    {
                        "status": "resolved",
                        "location_id": "K04",
                        "scoped_location_id": "HV001:K04",
                        "candidate_location_ids": ["K04"],
                        "candidate_internal_location_ids": ["HV001:K04"],
                        "sources": [
                            "areas/HV001.json#locations[HV001:K04].aliases"
                        ],
                        "player_facing": True,
                    }
                ),
                "continuity": {"cross_module_refs": []},
            },
            {"plotPoints": []},
        )

        result = run_module_semantic_probes(module_dir)
        travel = next(probe for probe in result["probes"] if probe["type"] == "travel")
        self.assertEqual(travel["status"], "pass")
        self.assertEqual(travel["expected_location_ids"], ["HV001:K04"])
        self.assertEqual(travel["resolved_location_id"], "HV001:K04")

    def test_raw_source_id_maps_to_scoped_resolved_id(self):
        module_dir = self._write_module(
            "Probe_RawScoped",
            {
                "module_name": "Probe_RawScoped",
                "semantic_authority": self._scoped_authority(
                    {
                        "status": "resolved",
                        "location_id": "K04",
                        "scoped_location_id": "HV001:K04",
                        "candidate_location_ids": ["K04"],
                        "candidate_internal_location_ids": ["HV001:K04"],
                        "sources": ["areas/HV001.json#locations[K04].aliases"],
                        "player_facing": True,
                    }
                ),
                "continuity": {"cross_module_refs": []},
            },
            {"plotPoints": []},
        )

        result = run_module_semantic_probes(module_dir)
        travel = next(probe for probe in result["probes"] if probe["type"] == "travel")
        self.assertEqual(travel["status"], "pass")

    def test_area_level_plot_location_is_not_a_room_target(self):
        authority = self._scoped_authority({})
        expected = _expected_locations_from_sources(
            ["module_plot.json#plotPoints[PP001].title"],
            {"plotPoints": [{"id": "PP001", "location": "HV001"}]},
            authority,
        )
        self.assertEqual(expected, [])

    def test_scoped_mismatch_remains_blocking(self):
        module_dir = self._write_module(
            "Probe_ScopedMismatch",
            {
                "module_name": "Probe_ScopedMismatch",
                "semantic_authority": self._scoped_authority(
                    {
                        "status": "resolved",
                        "location_id": "K05",
                        "scoped_location_id": "HV001:K05",
                        "candidate_location_ids": ["K05"],
                        "candidate_internal_location_ids": ["HV001:K05"],
                        "sources": [
                            "areas/HV001.json#locations[HV001:K04].aliases"
                        ],
                        "player_facing": True,
                    }
                ),
                "continuity": {"cross_module_refs": []},
            },
            {"plotPoints": []},
        )

        result = run_module_semantic_probes(module_dir)
        self.assertEqual(result["status"], "fail")
        self.assertTrue(
            any(
                probe.get("failure_class") == "travel_misrouted_destination_phrase"
                for probe in result["probes"]
            )
        )

    def _hidden_authority(self, reveal_binding):
        return {
            "version": "v1",
            "location_index": {
                "DO001:K01": {
                    "raw_location_id": "K01",
                    "scoped_location_id": "DO001:K01",
                    "area_id": "DO001",
                },
                "FC001:K01": {
                    "raw_location_id": "K01",
                    "scoped_location_id": "FC001:K01",
                    "area_id": "FC001",
                },
            },
            "destination_phrases": {},
            "npc_scene_authority": {
                "Mayor Corven's Imitation": {
                    "name_slug": "mayor corvens imitation",
                    "visible_location_ids": [],
                    "reveal_bindings": [reveal_binding],
                    "authored_mentions_count": 1,
                    "authored_mention_sources": [
                        "areas/DO001.json#locations[DO001:K01].description"
                    ],
                }
            },
        }

    def test_hidden_npc_reveal_prefers_scoped_binding_namespace(self):
        authority = self._hidden_authority(
            {"location_id": "K01", "scoped_location_id": "DO001:K01", "source": "fixture"}
        )
        self.assertEqual(_normalize_hidden_reveal_location("DO001", authority), [])
        module_dir = self._write_module(
            "Probe_HiddenScoped",
            {
                "module_name": "Probe_HiddenScoped",
                "semantic_authority": authority,
                "continuity": {"cross_module_refs": []},
            },
            {"plotPoints": []},
        )
        result = run_module_semantic_probes(module_dir)
        probe = next(item for item in result["probes"] if item["type"] == "hidden_npc")
        self.assertEqual(probe["reveal_location_ids"], ["DO001:K01"])
        self.assertEqual(probe["status"], "pass")

    def test_hidden_npc_scoped_reveal_mismatch_remains_blocking(self):
        module_dir = self._write_module(
            "Probe_HiddenMismatch",
            {
                "module_name": "Probe_HiddenMismatch",
                "semantic_authority": self._hidden_authority(
                    {"location_id": "K01", "scoped_location_id": "FC001:K01", "source": "fixture"}
                ),
                "continuity": {"cross_module_refs": []},
            },
            {"plotPoints": []},
        )
        result = run_module_semantic_probes(module_dir)
        self.assertTrue(
            any(item.get("failure_class") == "hidden_npc_target_mismatch" for item in result["probes"])
        )

    def test_hidden_npc_area_only_reveal_is_degraded_not_blocking(self):
        authority = self._hidden_authority(
            {"location_id": "DO001", "source": "area-only fixture"}
        )
        authority["npc_scene_authority"]["Mayor Corven's Imitation"][
            "authored_mention_sources"
        ] = ["module_plot.json#plotPoints[PP001].description"]
        module_dir = self._write_module(
            "Probe_HiddenAreaOnly",
            {
                "module_name": "Probe_HiddenAreaOnly",
                "semantic_authority": authority,
                "continuity": {"cross_module_refs": []},
            },
            {
                "plotPoints": [
                    {"id": "PP001", "location": "DO001", "description": "A hidden figure waits."}
                ]
            },
        )

        result = run_module_semantic_probes(module_dir)
        probe = next(item for item in result["probes"] if item["type"] == "hidden_npc")
        self.assertEqual(probe["reveal_location_ids"], [])
        self.assertEqual(probe["status"], "degraded")
        self.assertEqual(probe["failure_class"], "hidden_npc_fixture_missing_expected_target")
        self.assertEqual(result["blocking_errors"], [])
        self.assertEqual(result["exit_code"], 0)

    def test_raw_only_source_fixture_remains_raw(self):
        expected = _expected_locations_from_sources(
            ["areas/TST001.json#locations[LOC08].aliases"],
            {"plotPoints": []},
            {},
        )
        self.assertEqual(expected, ["LOC08"])

    def test_handoff_probe_catches_missing_target_module(self):
        module_dir = self._write_module(
            "Probe_C",
            {
                "module_name": "Probe_C",
                "semantic_authority": {
                    "version": "v1",
                    "destination_phrases": {},
                    "npc_scene_authority": {},
                },
                "continuity": {
                    "cross_module_refs": [
                        {
                            "target_module": "Missing_Module",
                            "entity_id": "scout_elen_handoff",
                            "relation": "reference",
                            "notes": "Scout Elen handoff thread links modules.",
                        }
                    ]
                },
            },
            {"plotPoints": []},
        )

        result = run_module_semantic_probes(module_dir)
        self.assertEqual(result["status"], "fail")
        self.assertTrue(
            any(
                probe.get("failure_class") == "handoff_target_module_absent"
                for probe in result["probes"]
            )
        )

    def test_hidden_npc_probe_catches_missing_authority(self):
        module_dir = self._write_module(
            "Probe_D",
            {
                "module_name": "Probe_D",
                "semantic_authority": {
                    "version": "v1",
                    "destination_phrases": {},
                    "npc_scene_authority": {
                        "Father Aldric": {
                            "name_slug": "father aldric",
                            "visible_location_ids": [],
                            "reveal_bindings": [],
                            "sources": ["module_context.json#npcs.father_aldric"],
                            "authored_mentions_count": 1,
                            "authored_mention_sources": [
                                "module_plot.json#plotPoints[PP003].description"
                            ],
                        }
                    },
                },
                "continuity": {"cross_module_refs": []},
            },
            {
                "plotPoints": [
                    {
                        "id": "PP003",
                        "location": "LOC03",
                        "description": "Father Aldric is said to be hiding nearby.",
                    }
                ]
            },
        )

        result = run_module_semantic_probes(module_dir)
        self.assertEqual(result["status"], "fail")
        self.assertTrue(
            any(
                probe.get("failure_class") == "hidden_npc_missing_authority"
                for probe in result["probes"]
            )
        )

    def test_visible_npc_without_reveal_binding_is_not_hidden_probe_failure(self):
        module_dir = self._write_module(
            "Probe_F",
            {
                "module_name": "Probe_F",
                "semantic_authority": {
                    "version": "v1",
                    "destination_phrases": {},
                    "npc_scene_authority": {
                        "Archivist Quill": {
                            "name_slug": "archivist quill",
                            "visible_location_ids": ["LOC09"],
                            "reveal_bindings": [],
                            "sources": ["areas/TST001.json#locations[LOC09].npcs"],
                            "authored_mentions_count": 2,
                            "authored_mention_sources": [
                                "areas/TST001.json#locations[LOC09].description"
                            ],
                        }
                    },
                },
                "continuity": {"cross_module_refs": []},
            },
            {"plotPoints": []},
        )

        result = run_module_semantic_probes(module_dir)
        self.assertNotEqual(result["status"], "fail")
        self.assertFalse(
            any(
                probe.get("failure_class") == "hidden_npc_missing_authority"
                for probe in result["probes"]
            )
        )

    def test_noncritical_fixture_gap_is_degraded_not_fail(self):
        existing_target = self.temp_dir / "Keep_of_Doom"
        existing_target.mkdir(parents=True, exist_ok=True)
        module_dir = self._write_module(
            "Probe_E",
            {
                "module_name": "Probe_E",
                "semantic_authority": {
                    "version": "v1",
                    "destination_phrases": {},
                    "npc_scene_authority": {},
                },
                "continuity": {
                    "cross_module_refs": [
                        {
                            "target_module": "Keep_of_Doom",
                            "entity_id": "scout_elen_handoff",
                            "relation": "reference",
                            "notes": "Scout Elen handoff thread links modules.",
                        }
                    ]
                },
            },
            {"plotPoints": []},
        )

        result = run_module_semantic_probes(module_dir)
        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["summary"]["fail_count"], 0)
        self.assertGreaterEqual(result["summary"]["degraded_count"], 0)
        self.assertTrue(
            any(
                "travel_probe_fixture_missing" in warning
                or "hidden_npc_probe_fixture_missing" in warning
                or "semantic_authority" in warning
                or "handoff_probe_fixture_missing" in warning
                for warning in result["warnings"]
            )
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
