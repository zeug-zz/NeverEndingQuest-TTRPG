# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free contract tests for proposed mise-en-scene fixtures."""

from __future__ import annotations

import builtins
import copy
import importlib
import socket
import unittest
from dataclasses import FrozenInstanceError
from unittest.mock import patch


_FORBIDDEN_IMPORT_ROOTS = {
    "anthropic",
    "config",
    "core",
    "httpx",
    "main",
    "model_config",
    "openai",
    "requests",
    "socket",
    "utils",
    "web",
}
_MODULE_ID = "frontier"
_SCENE_ID = "frontier:scene:yard"
_SCOPE_ID = "frontier:scope:yard"
_TOPOLOGY_ID = "frontier:topology:yard-v1"
_FIXED_ID = "frontier:entity:oak"
_MOBILE_ID = "frontier:entity:guide"
_SOURCE_REF = "source:chapter-1"
_TEST_CONTRACT: object | None = None


def _make_topology(**overrides: object) -> object:
    values = {
        "topology_id": _TOPOLOGY_ID,
        "module_id": _MODULE_ID,
        "scene_id": _SCENE_ID,
        "scope_id": _SCOPE_ID,
        "compass_frames": ("north_up",),
        "fixed_anchor_ids": (_FIXED_ID,),
    }
    values.update(overrides)
    return _TEST_CONTRACT.ApprovedTopology(**values)


def _make_fixture() -> dict[str, object]:
    return {
        "schema_version": 1,
        "module_id": _MODULE_ID,
        "topology_id": _TOPOLOGY_ID,
        "scene": {
            "id": _SCENE_ID,
            "scope": {"id": _SCOPE_ID, "kind": "exterior"},
            "orientation": {
                "status": "unknown",
                "frame": None,
                "provenance": {"class": "unknown", "source_refs": [_SOURCE_REF]},
            },
        },
        "fixed_anchors": [{"id": _FIXED_ID, "kind": "landmark"}],
        "initial_mobile_occupants": [{"id": _MOBILE_ID, "kind": "npc"}],
        "facts": [
            {
                "id": "frontier:fact:oak-bearing",
                "subject_id": _FIXED_ID,
                "predicate": "bearing",
                "object_id": _MOBILE_ID,
                "status": "unknown",
                "value": None,
                "provenance": {"class": "unknown", "source_refs": [_SOURCE_REF]},
            }
        ],
        "extension_seams": {
            "multi_cell_extents": [],
            "stage_relations": [],
            "unknown_metrics": [],
            "audience_knowledge": [],
            "arrival_claims": [],
        },
    }


def _make_coverage_case() -> tuple[dict[str, object], dict[str, object], object]:
    entity_ids = {
        "approach": "frontier:entity:approach",
        "threshold": "frontier:entity:threshold",
        "focal_anchor": "frontier:entity:focal",
        "path": "frontier:entity:causeway",
        "terrain": "frontier:entity:ridge",
        "boundary": "frontier:entity:hedge",
        "usable_space": "frontier:entity:yard-space",
    }
    topology = _make_topology(fixed_anchor_ids=tuple(entity_ids.values()))
    fixture = _make_fixture()
    fixture["fixed_anchors"] = [
        {"id": entity_id, "kind": role} for role, entity_id in entity_ids.items()
    ]
    fixture["facts"] = [
        {
            "id": "frontier:fact:approach-threshold",
            "subject_id": entity_ids["approach"],
            "predicate": "approach_to_threshold",
            "object_id": entity_ids["threshold"],
            "status": "known",
            "value": "authored-stage-relation",
            "provenance": {"class": "builder_authored", "source_refs": []},
        },
        {
            "id": "frontier:fact:threshold-focal",
            "subject_id": entity_ids["threshold"],
            "predicate": "threshold_to_focal",
            "object_id": entity_ids["focal_anchor"],
            "status": "known",
            "value": "authored-stage-relation",
            "provenance": {"class": "builder_authored", "source_refs": []},
        },
    ]
    extent_cells = {
        "path": [[0, 0], [1, 0], [2, 0]],
        "terrain": [[2, 0], [2, 1]],
        "boundary": [[-1, -1], [-1, 0], [-1, 1]],
        "usable_space": [[1, 0], [1, 1]],
    }
    fixture["extension_seams"]["multi_cell_extents"] = [
        {
            "entity_id": entity_ids[role],
            "status": "known",
            "schematic_cells": cells,
            "reason": None,
        }
        for role, cells in extent_cells.items()
    ]
    expected = {
        "schema_version": 1,
        "stage_relations": {
            "approach_to_threshold": {
                "status": "required",
                "from_id": entity_ids["approach"],
                "to_id": entity_ids["threshold"],
            },
            "threshold_to_focal": {
                "status": "required",
                "from_id": entity_ids["threshold"],
                "to_id": entity_ids["focal_anchor"],
            },
        },
        "extents": {
            "path": [
                {
                    "id": "causeway_span",
                    "entity_id": entity_ids["path"],
                    "status": "required",
                    "schematic_cells": copy.deepcopy(extent_cells["path"]),
                }
            ],
            "terrain": [
                {
                    "id": "ridge_extent",
                    "entity_id": entity_ids["terrain"],
                    "status": "required",
                    "schematic_cells": copy.deepcopy(extent_cells["terrain"]),
                }
            ],
            "boundary": [
                {
                    "id": "hedge_extent",
                    "entity_id": entity_ids["boundary"],
                    "status": "required",
                    "schematic_cells": copy.deepcopy(extent_cells["boundary"]),
                }
            ],
        },
        "usable_spaces": [
            {
                "id": "yard_open_space",
                "entity_id": entity_ids["usable_space"],
                "status": "required",
                "schematic_cells": copy.deepcopy(extent_cells["usable_space"]),
            }
        ],
    }
    return fixture, expected, topology


class MiseEnSceneAuthoringContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        original_import = builtins.__import__

        def guarded_import(name: str, *args: object, **kwargs: object) -> object:
            import_root = name.split(".", 1)[0]
            if import_root in _FORBIDDEN_IMPORT_ROOTS:
                raise AssertionError("forbidden runtime/provider import: " + name)
            return original_import(name, *args, **kwargs)

        with patch.object(builtins, "__import__", side_effect=guarded_import):
            cls.contract = importlib.import_module("mise_en_scene.contract")
            cls.coverage = importlib.import_module("mise_en_scene.coverage")
            cls.fixtures = importlib.import_module("mise_en_scene.fixtures")
            cls.identity = importlib.import_module("mise_en_scene.identity")
            cls.diagnostics = importlib.import_module("mise_en_scene.diagnostics")
            cls.arrival = importlib.import_module("mise_en_scene.arrival")
            cls.arrival_fixtures = importlib.import_module(
                "mise_en_scene.arrival_fixtures"
            )
        global _TEST_CONTRACT
        _TEST_CONTRACT = cls.contract

    def _validate(
        self,
        fixture: object,
        topology: object | None = None,
        consulted_source_refs: object = (_SOURCE_REF,),
    ) -> object:
        return self.contract.validate_fixture(
            fixture,
            topology if topology is not None else _make_topology(),
            consulted_source_refs,
        )

    def _diagnostics(self, result: object) -> set[tuple[str, str]]:
        return {(item.code, item.path) for item in result.diagnostics}

    def test_extraction_unknown_scope_orientation_and_relationship_are_explicit(self) -> None:
        fixture = _make_fixture()

        result = self._validate(fixture)

        self.assertTrue(result.is_valid, result.diagnostics)
        self.assertEqual(fixture["scene"]["scope"]["kind"], "exterior")
        self.assertEqual(fixture["scene"]["orientation"]["status"], "unknown")
        self.assertIsNone(fixture["scene"]["orientation"]["frame"])
        self.assertEqual(fixture["facts"][0]["status"], "unknown")
        self.assertIsNone(fixture["facts"][0]["value"])

    def test_extraction_and_builder_fixtures_preserve_unknowns_and_authorship(self) -> None:
        extracted = self.fixtures.make_extraction_fixture()
        builder = self.fixtures.make_builder_fixture()
        for bundle in (extracted, builder):
            fixture = bundle["fixture"]
            result = self.contract.validate_fixture(
                fixture, bundle["approved_topology"], bundle["consulted_source_refs"]
            )
            self.assertTrue(result.is_valid, result.diagnostics)
            unknowns = {fact["predicate"]: fact for fact in fixture["facts"] if fact["status"] == "unknown"}
            self.assertEqual(set(unknowns), {"route", "bearing", "distance", "visibility", "access", "sensory_reach"})
            self.assertTrue(all(fact["value"] is None and fact["provenance"]["class"] == "unknown" for fact in unknowns.values()))
            self.assertEqual(bundle["provenance_metadata"]["source_refs"], {"source:fixture-landmark": "development fixture text establishing a landmark only"})
            self.assertFalse(bundle["provenance_metadata"]["held_out"])
            self.assertFalse(bundle["provenance_metadata"]["legacy_fact_verified"])
        authored = [fact for fact in builder["fixture"]["facts"] if fact["provenance"]["class"] == "builder_authored"]
        self.assertEqual({fact["predicate"] for fact in authored}, {"approach_to_threshold", "threshold_to_focal"})
        self.assertTrue(all(not fact["provenance"]["source_refs"] for fact in authored))
        owner_kinds = {item["id"]: item["kind"] for item in builder["fixture"]["fixed_anchors"]}
        self.assertEqual(owner_kinds["mapping_fixture:entity:approach"], "approach")
        self.assertEqual(owner_kinds["mapping_fixture:entity:threshold"], "threshold")
        self.assertEqual(owner_kinds["mapping_fixture:entity:focal"], "focal_anchor")

    def test_fixture_constructors_return_fresh_bundle_and_scene_containers(self) -> None:
        first = self.fixtures.make_builder_fixture()
        second = self.fixtures.make_builder_fixture()
        self.assertIsNot(first, second)
        self.assertIsNot(first["fixture"], second["fixture"])
        first["fixture"]["facts"].clear()
        self.assertTrue(second["fixture"]["facts"])

    def test_initial_scene_excludes_prior_runtime_pcs_and_pc_kinds(self) -> None:
        fixture = _make_fixture()
        pc_id = "frontier:entity:prior-player"
        fixture["initial_mobile_occupants"][0]["id"] = pc_id
        for prior_ids in ((pc_id,), (pc_id, "frontier:entity:second-player", "frontier:entity:third-player", "frontier:entity:fourth-player")):
            result = self.contract.validate_fixture(fixture, _make_topology(), (_SOURCE_REF,), prior_pc_ids=prior_ids)
            self.assertIn(("PRIOR_PC_INITIAL_OCCUPANT", "$.initial_mobile_occupants[0].id"), self._diagnostics(result))

        fixture["initial_mobile_occupants"][0]["id"] = _MOBILE_ID
        fixture["initial_mobile_occupants"][0]["kind"] = "player_character"
        result = self.contract.validate_fixture(fixture, _make_topology(), (_SOURCE_REF,))
        self.assertIn(("PC_INITIAL_OCCUPANT", "$.initial_mobile_occupants[0].kind"), self._diagnostics(result))

    def test_invalid_prior_pc_ids_have_stable_diagnostics(self) -> None:
        result = self.contract.validate_fixture(_make_fixture(), _make_topology(), (_SOURCE_REF,), prior_pc_ids="frontier:entity:pc")
        self.assertIn(("PRIOR_PC_IDS_TYPE", "$prior_pc_ids"), self._diagnostics(result))
        result = self.contract.validate_fixture(_make_fixture(), _make_topology(), (_SOURCE_REF,), prior_pc_ids=("not-qualified",))
        self.assertIn(("PRIOR_PC_ID", "$prior_pc_ids[0]"), self._diagnostics(result))
        result = self.contract.validate_fixture(
            _make_fixture(), _make_topology(), (_SOURCE_REF,),
            prior_pc_ids=tuple("frontier:entity:pc-%d" % index for index in range(257)),
        )
        self.assertIn(("COLLECTION_LIMIT", "$prior_pc_ids"), self._diagnostics(result))

    def test_explicit_builder_authored_orientation_is_accepted_in_approved_frame(self) -> None:
        fixture = _make_fixture()
        fixture["scene"]["orientation"] = {
            "status": "known",
            "frame": "north_up",
            "provenance": {
                "class": "builder_authored",
                "source_refs": [_SOURCE_REF],
            },
        }

        result = self._validate(fixture)

        self.assertTrue(result.is_valid, result.diagnostics)

    def test_source_builder_and_unknown_provenance_classes_are_distinct(self) -> None:
        fixture = _make_fixture()
        fixture["scene"]["orientation"] = {
            "status": "known",
            "frame": "north_up",
            "provenance": {
                "class": "builder_authored",
                "source_refs": [_SOURCE_REF],
            },
        }
        fixture["facts"].extend(
            [
                {
                    "id": "frontier:fact:source-landmark",
                    "subject_id": _SCENE_ID,
                    "predicate": "contains",
                    "object_id": _FIXED_ID,
                    "status": "known",
                    "value": "present",
                    "provenance": {
                        "class": "source_extracted",
                        "source_refs": [_SOURCE_REF],
                    },
                },
                {
                    "id": "frontier:fact:authored-approach",
                    "subject_id": _MOBILE_ID,
                    "predicate": "approaches",
                    "object_id": _FIXED_ID,
                    "status": "known",
                    "value": "initial staging",
                    "provenance": {
                        "class": "builder_authored",
                        "source_refs": [],
                    },
                },
            ]
        )

        result = self._validate(fixture)

        self.assertTrue(result.is_valid, result.diagnostics)
        self.assertEqual(
            {fact["provenance"]["class"] for fact in fixture["facts"]},
            {"source_extracted", "builder_authored", "unknown"},
        )

    def test_orientation_conflict_fails_with_stable_code_and_path(self) -> None:
        fixture = _make_fixture()
        fixture["scene"]["orientation"] = {
            "status": "known",
            "frame": "east_up",
            "provenance": {"class": "builder_authored", "source_refs": []},
        }

        first = self._validate(fixture)
        second = self._validate(fixture)

        expected = ("ORIENTATION_CONFLICT", "$.scene.orientation.frame")
        self.assertIn(expected, self._diagnostics(first))
        self.assertEqual(first.diagnostics, second.diagnostics)

    def test_fixture_must_match_the_approved_topology_binding(self) -> None:
        fixture = _make_fixture()
        fixture["scene"]["scope"]["id"] = "frontier:scope:other"
        fixture["topology_id"] = "frontier:topology:other"

        diagnostics = self._diagnostics(self._validate(fixture))

        self.assertIn(("TOPOLOGY_SCOPE_MISMATCH", "$.scene.scope.id"), diagnostics)
        self.assertIn(("TOPOLOGY_ID_MISMATCH", "$.topology_id"), diagnostics)

    def test_duplicate_fact_identity_is_rejected(self) -> None:
        fixture = _make_fixture()
        fixture["facts"].append(copy.deepcopy(fixture["facts"][0]))

        diagnostics = self._diagnostics(self._validate(fixture))

        self.assertIn(("DUPLICATE_ID", "$.facts[1].id"), diagnostics)

    def test_fixed_anchor_and_mobile_occupant_cannot_share_identity(self) -> None:
        fixture = _make_fixture()
        fixture["initial_mobile_occupants"][0]["id"] = _FIXED_ID

        diagnostics = self._diagnostics(self._validate(fixture))

        self.assertIn(
            ("FIXED_MOBILE_ID_COLLISION", "$.initial_mobile_occupants[0].id"),
            diagnostics,
        )

    def test_relationship_references_must_resolve_to_scene_or_entity_ids(self) -> None:
        fixture = _make_fixture()
        fixture["facts"][0]["object_id"] = "frontier:entity:missing"

        diagnostics = self._diagnostics(self._validate(fixture))

        self.assertIn(("UNKNOWN_REFERENCE", "$.facts[0].object_id"), diagnostics)

    def test_source_refs_must_be_consulted_and_are_not_authority_by_string(self) -> None:
        fixture = _make_fixture()
        fixture["facts"][0]["provenance"] = {
            "class": "source_extracted",
            "source_refs": ["source:not-consulted"],
        }

        diagnostics = self._diagnostics(self._validate(fixture))

        self.assertIn(
            (
                "UNSUPPORTED_SOURCE_REF",
                "$.facts[0].provenance.source_refs[0]",
            ),
            diagnostics,
        )

    def test_source_extracted_fact_requires_a_consulted_source_ref(self) -> None:
        fixture = _make_fixture()
        fixture["facts"][0]["status"] = "known"
        fixture["facts"][0]["value"] = "east"
        fixture["facts"][0]["provenance"] = {
            "class": "source_extracted",
            "source_refs": [],
        }

        diagnostics = self._diagnostics(self._validate(fixture))

        self.assertIn(
            ("MISSING_SOURCE_REF", "$.facts[0].provenance.source_refs"),
            diagnostics,
        )

    def test_malformed_source_reference_and_wrong_source_refs_type_fail_closed(self) -> None:
        fixture = _make_fixture()
        fixture["facts"][0]["provenance"]["source_refs"] = "source:chapter-1"
        diagnostics = self._diagnostics(self._validate(fixture))
        self.assertIn(
            ("SOURCE_REFS_TYPE", "$.facts[0].provenance.source_refs"),
            diagnostics,
        )

        fixture["facts"][0]["provenance"]["source_refs"] = ["not-a-source-ref"]
        diagnostics = self._diagnostics(self._validate(fixture))
        self.assertIn(
            (
                "INVALID_SOURCE_REF",
                "$.facts[0].provenance.source_refs[0]",
            ),
            diagnostics,
        )

    def test_consulted_source_reference_input_must_be_a_sequence(self) -> None:
        result = self._validate(_make_fixture(), consulted_source_refs="source:chapter-1")

        self.assertIn(
            ("CONSULTED_SOURCE_REFS_TYPE", "$consulted_source_refs"),
            self._diagnostics(result),
        )

    def test_missing_fields_wrong_types_and_malformed_items_have_stable_paths(self) -> None:
        missing_scene = _make_fixture()
        del missing_scene["scene"]
        diagnostics = self._diagnostics(self._validate(missing_scene))
        self.assertIn(("MISSING_FIELD", "$.scene"), diagnostics)
        self.assertIn(("OBJECT_TYPE", "$.scene"), diagnostics)

        wrong_facts = _make_fixture()
        wrong_facts["facts"] = "not-an-array"
        diagnostics = self._diagnostics(self._validate(wrong_facts))
        self.assertIn(("ARRAY_TYPE", "$.facts"), diagnostics)

        malformed_item = _make_fixture()
        malformed_item["fixed_anchors"].append(None)
        diagnostics = self._diagnostics(self._validate(malformed_item))
        self.assertIn(("ITEM_TYPE", "$.fixed_anchors[1]"), diagnostics)

    def test_wrong_approved_topology_type_fails_closed(self) -> None:
        result = self._validate(_make_fixture(), topology={"id": _TOPOLOGY_ID})

        self.assertIn(
            ("APPROVED_TOPOLOGY_TYPE", "$approved_topology"),
            self._diagnostics(result),
        )

    def test_approved_topology_is_frozen_and_validation_does_not_mutate_inputs(self) -> None:
        topology = _make_topology()
        fixture = _make_fixture()
        fixture_before = copy.deepcopy(fixture)
        topology_before = copy.deepcopy(topology)

        result = self._validate(fixture, topology=topology)

        self.assertTrue(result.is_valid, result.diagnostics)
        self.assertEqual(fixture, fixture_before)
        self.assertEqual(topology, topology_before)
        self.assertIs(type(topology.compass_frames), tuple)
        with self.assertRaises(FrozenInstanceError):
            topology.scene_id = "frontier:scene:changed"

    def test_extension_seams_are_data_only_and_do_not_add_derived_facts(self) -> None:
        fixture = _make_fixture()
        fixture["extension_seams"]["multi_cell_extents"] = [
            {"entity_id": _FIXED_ID, "schematic_cells": [[0, 0], [1, 0]]}
        ]
        fact_ids_before = [fact["id"] for fact in fixture["facts"]]

        result = self._validate(fixture)

        self.assertTrue(result.is_valid, result.diagnostics)
        self.assertEqual([fact["id"] for fact in fixture["facts"]], fact_ids_before)

    def test_complete_positional_coverage_preserves_multicell_extents_and_overlap(self) -> None:
        fixture, expected, topology = _make_coverage_case()
        fixture_before = copy.deepcopy(fixture)
        expected_before = copy.deepcopy(expected)

        report = self.coverage.validate_positional_coverage(
            fixture, expected, topology, (_SOURCE_REF,)
        )

        self.assertTrue(report.schema_valid, report.schema_diagnostics)
        self.assertTrue(report.coverage_evaluated)
        self.assertTrue(report.coverage_valid, report.coverage_diagnostics)
        self.assertTrue(report.is_valid, report.diagnostics)
        self.assertEqual(fixture, fixture_before)
        self.assertEqual(expected, expected_before)
        extents = fixture["extension_seams"]["multi_cell_extents"]
        path_cells = extents[0]["schematic_cells"]
        open_space_cells = extents[3]["schematic_cells"]
        self.assertEqual(path_cells, [[0, 0], [1, 0], [2, 0]])
        self.assertTrue(set(map(tuple, path_cells)) & set(map(tuple, open_space_cells)))

    def test_schema_valid_candidate_reports_both_missing_stage_relations(self) -> None:
        fixture, expected, topology = _make_coverage_case()
        fixture["facts"] = []
        fixture["extension_seams"]["stage_relations"] = [
            {
                "relation": "approach_to_threshold",
                "status": "not_applicable",
                "reason": "candidate-side claim cannot waive reference coverage",
            }
        ]
        self.assertTrue(
            self.contract.validate_fixture(fixture, topology, (_SOURCE_REF,)).is_valid
        )

        report = self.coverage.validate_positional_coverage(
            fixture, expected, topology, (_SOURCE_REF,)
        )

        self.assertTrue(report.schema_valid, report.schema_diagnostics)
        self.assertFalse(report.coverage_valid)
        missing = {
            dict(item.details)["relationship"]
            for item in report.coverage_diagnostics
            if item.code == "MISSING_RELATION"
        }
        self.assertEqual(missing, {"approach_to_threshold", "threshold_to_focal"})
        for item in report.coverage_diagnostics:
            if item.code == "MISSING_RELATION":
                self.assertEqual(item.path, "$.facts")
                self.assertEqual(item.layer, "relationship_coverage")
                self.assertEqual(dict(item.details)["stage"], "candidate_authoring")
                self.assertIn("from_id", dict(item.details))
                self.assertIn("to_id", dict(item.details))

    def test_unknown_relation_and_wrong_resolved_reference_do_not_count_as_coverage(self) -> None:
        fixture, expected, topology = _make_coverage_case()
        fixture["facts"][0]["status"] = "unknown"
        fixture["facts"][0]["value"] = None
        fixture["facts"][0]["provenance"] = {
            "class": "unknown",
            "source_refs": [],
        }
        report = self.coverage.validate_positional_coverage(
            fixture, expected, topology, (_SOURCE_REF,)
        )
        self.assertTrue(report.schema_valid, report.schema_diagnostics)
        self.assertIn(
            ("RELATION_UNKNOWN", "$.facts[0]", "relationship_coverage"),
            {(item.code, item.path, item.layer) for item in report.coverage_diagnostics},
        )

        fixture, expected, topology = _make_coverage_case()
        fixture["facts"][0]["object_id"] = "frontier:entity:focal"
        report = self.coverage.validate_positional_coverage(
            fixture, expected, topology, (_SOURCE_REF,)
        )
        self.assertTrue(report.schema_valid, report.schema_diagnostics)
        mismatch = [
            item
            for item in report.coverage_diagnostics
            if item.code == "RELATION_REFERENCE_MISMATCH"
        ]
        self.assertEqual(len(mismatch), 1)
        self.assertEqual(mismatch[0].path, "$.facts[0]")
        self.assertEqual(dict(mismatch[0].details)["observed_to_id"], "frontier:entity:focal")

    def test_required_role_identity_must_match_fact_endpoints(self) -> None:
        fixture, expected, topology = _make_coverage_case()
        fixture["fixed_anchors"][0]["kind"] = "threshold"

        report = self.coverage.validate_positional_coverage(
            fixture, expected, topology, (_SOURCE_REF,)
        )

        self.assertTrue(report.schema_valid, report.schema_diagnostics)
        self.assertIn(
            ("ROLE_MISMATCH", "$.fixed_anchors[0].kind", "relationship_coverage"),
            {(item.code, item.path, item.layer) for item in report.coverage_diagnostics},
        )

    def test_mobile_occupant_cannot_satisfy_a_fixed_stage_role(self) -> None:
        fixture, expected, _topology = _make_coverage_case()
        approach = fixture["fixed_anchors"].pop(0)
        fixture["initial_mobile_occupants"].append(approach)
        topology = _make_topology(
            fixed_anchor_ids=tuple(item["id"] for item in fixture["fixed_anchors"])
        )

        report = self.coverage.validate_positional_coverage(
            fixture, expected, topology, (_SOURCE_REF,)
        )

        self.assertTrue(report.schema_valid, report.schema_diagnostics)
        mismatch = next(
            item for item in report.coverage_diagnostics if item.code == "ROLE_MISMATCH"
        )
        self.assertEqual(mismatch.path, "$.initial_mobile_occupants[1].kind")
        self.assertEqual(dict(mismatch.details)["observed_collection"], "initial_mobile_occupants")

    def test_missing_and_truncated_extents_are_reported_with_expected_cells(self) -> None:
        fixture, expected, topology = _make_coverage_case()
        fixture["extension_seams"]["multi_cell_extents"].pop(0)
        report = self.coverage.validate_positional_coverage(
            fixture, expected, topology, (_SOURCE_REF,)
        )
        self.assertTrue(report.schema_valid, report.schema_diagnostics)
        missing = next(
            item for item in report.coverage_diagnostics if item.code == "MISSING_EXTENT"
        )
        self.assertEqual(missing.layer, "relationship_coverage")
        self.assertEqual(dict(missing.details)["entity_id"], "frontier:entity:causeway")

        fixture, expected, topology = _make_coverage_case()
        fixture["extension_seams"]["multi_cell_extents"][0]["schematic_cells"] = [
            [0, 0],
            [1, 0],
        ]
        report = self.coverage.validate_positional_coverage(
            fixture, expected, topology, (_SOURCE_REF,)
        )
        truncated = next(
            item for item in report.coverage_diagnostics if item.code == "EXTENT_TRUNCATED"
        )
        self.assertEqual(truncated.path, "$.extension_seams.multi_cell_extents[0].schematic_cells")
        self.assertEqual(dict(truncated.details)["missing_cells"], "[[2,0]]")

        fixture, expected, topology = _make_coverage_case()
        fixture["extension_seams"]["multi_cell_extents"][0]["schematic_cells"].append(
            [3, 0]
        )
        report = self.coverage.validate_positional_coverage(
            fixture, expected, topology, (_SOURCE_REF,)
        )
        extra = next(
            item for item in report.coverage_diagnostics if item.code == "EXTENT_EXTRA_CELLS"
        )
        self.assertEqual(dict(extra.details)["extra_cells"], "[[3,0]]")

        fixture, expected, topology = _make_coverage_case()
        fixture["extension_seams"]["multi_cell_extents"].pop()
        report = self.coverage.validate_positional_coverage(
            fixture, expected, topology, (_SOURCE_REF,)
        )
        missing_space = next(
            item
            for item in report.coverage_diagnostics
            if item.code == "MISSING_USABLE_SPACE"
        )
        self.assertEqual(dict(missing_space.details)["role"], "usable_space")

    def test_wrong_extent_role_and_candidate_nonapplicability_fail_required_coverage(self) -> None:
        fixture, expected, topology = _make_coverage_case()
        fixture["fixed_anchors"][3]["kind"] = "terrain"
        report = self.coverage.validate_positional_coverage(
            fixture, expected, topology, (_SOURCE_REF,)
        )
        self.assertIn(
            ("ROLE_MISMATCH", "$.fixed_anchors[3].kind", "relationship_coverage"),
            {(item.code, item.path, item.layer) for item in report.coverage_diagnostics},
        )

        fixture, expected, topology = _make_coverage_case()
        fixture["extension_seams"]["multi_cell_extents"][0]["status"] = "not_applicable"
        fixture["extension_seams"]["multi_cell_extents"][0]["schematic_cells"] = None
        fixture["extension_seams"]["multi_cell_extents"][0]["reason"] = "claimed by candidate"
        report = self.coverage.validate_positional_coverage(
            fixture, expected, topology, (_SOURCE_REF,)
        )
        self.assertTrue(report.schema_valid, report.schema_diagnostics)
        self.assertIn(
            "NOT_APPLICABLE_REQUIRED",
            {item.code for item in report.coverage_diagnostics},
        )

        fixture, expected, topology = _make_coverage_case()
        fixture["extension_seams"]["multi_cell_extents"][0]["status"] = "unknown"
        fixture["extension_seams"]["multi_cell_extents"][0]["schematic_cells"] = None
        fixture["extension_seams"]["multi_cell_extents"][0]["reason"] = "extent not established"
        report = self.coverage.validate_positional_coverage(
            fixture, expected, topology, (_SOURCE_REF,)
        )
        self.assertTrue(report.schema_valid, report.schema_diagnostics)
        unknown = next(
            item for item in report.coverage_diagnostics if item.code == "EXTENT_UNKNOWN"
        )
        self.assertEqual(dict(unknown.details)["reason"], "extent not established")

    def test_reference_nonapplicability_requires_reason_and_is_reported_separately(self) -> None:
        fixture, expected, topology = _make_coverage_case()
        expected["extents"]["terrain"] = [
            {"id": "terrain_not_applicable", "status": "not_applicable"}
        ]
        report = self.coverage.validate_positional_coverage(
            fixture, expected, topology, (_SOURCE_REF,)
        )
        self.assertFalse(report.schema_valid)
        self.assertFalse(report.coverage_evaluated)
        self.assertIn(
            ("NON_APPLICABLE_REASON", "$expected.extents.terrain[0].reason", "schema"),
            {(item.code, item.path, item.layer) for item in report.schema_diagnostics},
        )

        fixture, expected, topology = _make_coverage_case()
        expected["extents"]["terrain"] = [
            {
                "id": "terrain_not_applicable",
                "status": "not_applicable",
                "reason": "No terrain feature applies to this scene.",
            }
        ]
        report = self.coverage.validate_positional_coverage(
            fixture, expected, topology, (_SOURCE_REF,)
        )
        self.assertTrue(report.schema_valid, report.schema_diagnostics)
        self.assertTrue(report.coverage_valid, report.coverage_diagnostics)
        self.assertEqual(len(report.not_applicable), 1)
        self.assertEqual(report.not_applicable[0].code, "NOT_APPLICABLE")
        self.assertIn("No terrain feature", dict(report.not_applicable[0].details)["reason"])

    def test_malformed_positional_cells_are_schema_errors_not_coverage_passes(self) -> None:
        fixture, expected, topology = _make_coverage_case()
        fixture["extension_seams"]["multi_cell_extents"][0]["schematic_cells"] = [
            ["0", 0]
        ]

        report = self.coverage.validate_positional_coverage(
            fixture, expected, topology, (_SOURCE_REF,)
        )

        self.assertFalse(report.schema_valid)
        self.assertFalse(report.coverage_evaluated)
        self.assertFalse(report.coverage_valid)
        self.assertIn(
            ("CELL_COORDINATE", "$.extension_seams.multi_cell_extents[0].schematic_cells[0]", "schema"),
            {(item.code, item.path, item.layer) for item in report.schema_diagnostics},
        )

    def test_coverage_is_deterministic_read_only_and_provider_free(self) -> None:
        fixture, expected, topology = _make_coverage_case()
        fixture_before = copy.deepcopy(fixture)
        expected_before = copy.deepcopy(expected)
        first = self.coverage.validate_positional_coverage(
            fixture, expected, topology, (_SOURCE_REF,)
        )
        second = self.coverage.validate_positional_coverage(
            fixture, expected, topology, (_SOURCE_REF,)
        )

        self.assertEqual(first, second)
        self.assertEqual(fixture, fixture_before)
        self.assertEqual(expected, expected_before)
        self.assertEqual(
            [item.layer for item in first.diagnostics],
            sorted(item.layer for item in first.diagnostics),
        )

        original_import = builtins.__import__

        def guarded_import(name: str, *args: object, **kwargs: object) -> object:
            import_root = name.split(".", 1)[0]
            if import_root in _FORBIDDEN_IMPORT_ROOTS:
                raise AssertionError("forbidden runtime/provider import: " + name)
            return original_import(name, *args, **kwargs)

        def blocked_network(*args: object, **kwargs: object) -> None:
            raise AssertionError("network access is prohibited in fixture validation")

        with patch.object(builtins, "__import__", side_effect=guarded_import):
            importlib.reload(self.coverage)
            with patch.object(socket, "socket", side_effect=blocked_network):
                with patch.object(socket, "create_connection", side_effect=blocked_network):
                    report = self.coverage.validate_positional_coverage(
                        fixture, expected, topology, (_SOURCE_REF,)
                    )
        self.assertTrue(report.is_valid, report.diagnostics)

    def test_import_and_validation_tripwires_block_runtime_and_network_access(self) -> None:
        original_import = builtins.__import__

        def guarded_import(name: str, *args: object, **kwargs: object) -> object:
            import_root = name.split(".", 1)[0]
            if import_root in _FORBIDDEN_IMPORT_ROOTS:
                raise AssertionError("forbidden runtime/provider import: " + name)
            return original_import(name, *args, **kwargs)

        def blocked_network(*args: object, **kwargs: object) -> None:
            raise AssertionError("network access is prohibited in fixture validation")

        with patch.object(builtins, "__import__", side_effect=guarded_import):
            importlib.reload(self.contract)
            importlib.reload(self.identity)
            linked_bundle = self.fixtures.make_linked_tavern_fixture()
            with patch.object(socket, "socket", side_effect=blocked_network):
                with patch.object(socket, "create_connection", side_effect=blocked_network):
                    result = self._validate(_make_fixture())
                    linked_result = self.identity.validate_linked_views(linked_bundle)
        self.assertTrue(result.is_valid, result.diagnostics)
        self.assertTrue(linked_result.is_valid, linked_result.diagnostics)

    def test_linked_tavern_identity_frontages_and_synthetic_reciprocal_bearings(self) -> None:
        p1 = self.fixtures.make_linked_tavern_fixture("P1")
        p4 = self.fixtures.make_linked_tavern_fixture("P4")
        p1_before = copy.deepcopy(p1)
        first = self.identity.validate_linked_views(p1)
        second = self.identity.validate_linked_views(p1)
        p4_result = self.identity.validate_linked_views(p4)

        self.assertTrue(first.is_valid, first.diagnostics)
        self.assertEqual(first, second)
        self.assertTrue(p4_result.is_valid, p4_result.diagnostics)
        self.assertEqual(p1["identity_links"], p4["identity_links"])
        self.assertEqual(p1["reference"], p4["reference"])
        self.assertEqual(p1, p1_before)
        self.assertFalse(p1["metadata"]["source_verified"])
        self.assertEqual(
            [p1["metadata"]["synthetic_party_metadata"]["party_shape"],
             p4["metadata"]["synthetic_party_metadata"]["party_shape"]],
            ["P1", "P4"],
        )

        tavern_ids = {
            item["canonical_entity_id"]
            for item in p1["identity_links"]
            if item["canonical_entity_id"].endswith(":shared_tavern")
        }
        tavern_views = {
            item["view_id"]
            for item in p1["identity_links"]
            if item["canonical_entity_id"] == "mapping_fixture:entity:shared_tavern"
        }
        self.assertEqual(tavern_ids, {"mapping_fixture:entity:shared_tavern"})
        self.assertEqual(tavern_views, {"market", "square"})
        frontage_ids = {item["frontage_entity_id"] for item in p1["frontages"]}
        self.assertEqual(len(frontage_ids), 2)
        self.assertEqual(
            {item["building_entity_id"] for item in p1["frontages"]},
            {"mapping_fixture:entity:shared_tavern"},
        )
        self.assertEqual(
            [item["direction"] for item in p1["bearings"]], ["east", "west"]
        )
        self.assertTrue(
            all(
                item["verification_basis"] == "synthetic_approved_compass_frame"
                for item in p1["bearings"]
            )
        )
        self.assertTrue(
            all(not view["fixture"]["initial_mobile_occupants"] for view in p1["views"])
        )
        self.assertNotIn("position", p1["metadata"]["synthetic_party_metadata"])

    def test_linked_identity_rejects_duplicate_canonical_ids_and_split_tavern_aliases(self) -> None:
        duplicate = self.fixtures.make_linked_tavern_fixture()
        duplicate["reference"]["canonical_entities"][1]["id"] = (
            "mapping_fixture:entity:shared_tavern"
        )
        diagnostics = {item.code for item in self.identity.validate_linked_views(duplicate).diagnostics}
        self.assertIn("DUPLICATE_CANONICAL_ID", diagnostics)

        split = self.fixtures.make_linked_tavern_fixture()
        split["identity_links"][2]["canonical_entity_id"] = (
            "mapping_fixture:entity:square_tavern_alias"
        )
        diagnostics = {item.code for item in self.identity.validate_linked_views(split).diagnostics}
        self.assertIn("IDENTITY_REFERENCE_MISMATCH", diagnostics)
        self.assertIn("UNKNOWN_CANONICAL_REFERENCE", diagnostics)

        duplicate_assignment = self.fixtures.make_linked_tavern_fixture()
        duplicate_assignment["identity_links"][1]["canonical_entity_id"] = (
            "mapping_fixture:entity:shared_tavern"
        )
        diagnostics = {
            item.code
            for item in self.identity.validate_linked_views(duplicate_assignment).diagnostics
        }
        self.assertIn("DUPLICATE_CANONICAL_ASSIGNMENT", diagnostics)

    def test_linked_frontages_remain_distinct_relationships(self) -> None:
        bundle = self.fixtures.make_linked_tavern_fixture()
        bundle["frontages"][1]["frontage_entity_id"] = bundle["frontages"][0][
            "frontage_entity_id"
        ]

        diagnostics = {
            item.code for item in self.identity.validate_linked_views(bundle).diagnostics
        }

        self.assertIn("FRONTAGE_REFERENCE_MISMATCH", diagnostics)
        self.assertIn("FRONTAGE_IDENTITY_COLLAPSED", diagnostics)

    def test_bearings_require_explicit_reciprocity_and_approved_frames(self) -> None:
        wrong = self.fixtures.make_linked_tavern_fixture()
        wrong["bearings"][1]["direction"] = "east"
        diagnostics = {
            item.code for item in self.identity.validate_linked_views(wrong).diagnostics
        }
        self.assertIn("BEARING_REFERENCE_MISMATCH", diagnostics)
        self.assertIn("NONRECIPROCAL_BEARING", diagnostics)

        missing = self.fixtures.make_linked_tavern_fixture()
        missing["bearings"].pop()
        diagnostics = {
            item.code for item in self.identity.validate_linked_views(missing).diagnostics
        }
        self.assertIn("BEARING_REFERENCE_MISSING", diagnostics)
        self.assertIn("MISSING_RECIPROCAL_BEARING", diagnostics)

        unknown = self.fixtures.make_linked_tavern_fixture()
        unknown["bearings"][0]["direction"] = "unknown"
        diagnostics = {
            item.code for item in self.identity.validate_linked_views(unknown).diagnostics
        }
        self.assertIn("BEARING_DIRECTION", diagnostics)
        self.assertIn("BEARING_REFERENCE_MISMATCH", diagnostics)

        no_frame = self.fixtures.make_linked_tavern_fixture()
        del no_frame["bearings"][0]["compass_frame"]
        diagnostics = {
            item.code for item in self.identity.validate_linked_views(no_frame).diagnostics
        }
        self.assertIn("MISSING_FIELD", diagnostics)
        self.assertIn("BEARING_COMPASS_FRAME", diagnostics)

        unknown_orientation = self.fixtures.make_linked_tavern_fixture()
        unknown_orientation["views"][0]["fixture"]["scene"]["orientation"] = {
            "status": "unknown",
            "frame": None,
            "provenance": {"class": "unknown", "source_refs": []},
        }
        diagnostics = {
            item.code
            for item in self.identity.validate_linked_views(unknown_orientation).diagnostics
        }
        self.assertIn("BEARING_FRAME_UNKNOWN", diagnostics)

        conflicting_frame = self.fixtures.make_linked_tavern_fixture()
        conflicting_frame["bearings"][0]["compass_frame"] = "unapproved_frame"
        diagnostics = {
            item.code
            for item in self.identity.validate_linked_views(conflicting_frame).diagnostics
        }
        self.assertIn("UNAPPROVED_COMPASS_FRAME", diagnostics)

    def test_linked_views_reject_unsupported_door_traversal_and_sensory_facts(self) -> None:
        for predicate in ("door", "traversal", "access", "visibility", "audibility"):
            with self.subTest(predicate=predicate):
                bundle = self.fixtures.make_linked_tavern_fixture()
                fixture = bundle["views"][0]["fixture"]
                fixture["facts"].append(
                    {
                        "id": "mapping_fixture:fact:unsupported_" + predicate,
                        "subject_id": fixture["scene"]["id"],
                        "predicate": predicate,
                        "object_id": fixture["fixed_anchors"][0]["id"],
                        "status": "known",
                        "value": True,
                        "provenance": {"class": "builder_authored", "source_refs": []},
                    }
                )

                diagnostics = {
                    item.code
                    for item in self.identity.validate_linked_views(bundle).diagnostics
                }

                self.assertIn("UNSUPPORTED_SCENE_FACT", diagnostics)

    def test_linked_view_malformed_references_have_stable_diagnostics(self) -> None:
        bundle = self.fixtures.make_linked_tavern_fixture()
        bundle["identity_links"][0]["view_id"] = "missing_view"
        bundle["bearings"][0]["direction"] = []

        first = self.identity.validate_linked_views(bundle)
        second = self.identity.validate_linked_views(bundle)

        self.assertEqual(first, second)
        self.assertIn(
            "UNKNOWN_VIEW_REFERENCE", {item.code for item in first.diagnostics}
        )
        self.assertIn("BEARING_DIRECTION", {item.code for item in first.diagnostics})

        bounded = self.fixtures.make_linked_tavern_fixture()
        bounded["identity_links"] = bounded["identity_links"] * 17
        bounded_first = self.identity.validate_linked_views(bounded)
        bounded_second = self.identity.validate_linked_views(bounded)
        self.assertEqual(bounded_first, bounded_second)
        self.assertIn(
            "COLLECTION_LIMIT", {item.code for item in bounded_first.diagnostics}
        )

    def test_mobile_occupant_move_keeps_fixed_anchor_identity_and_placement(self) -> None:
        movement = self.fixtures.make_fixed_anchor_mobile_occupant_fixture()
        before = copy.deepcopy(movement["before"])
        after = copy.deepcopy(movement["after"])

        first = self.identity.validate_occupant_movement(
            movement["before"], movement["after"]
        )
        second = self.identity.validate_occupant_movement(
            movement["before"], movement["after"]
        )

        self.assertTrue(first.is_valid, first.diagnostics)
        self.assertEqual(first, second)
        self.assertEqual(movement["before"], before)
        self.assertEqual(movement["after"], after)
        self.assertEqual(
            movement["before"]["mobile_occupants"][0]["id"],
            movement["after"]["mobile_occupants"][0]["id"],
        )
        self.assertNotEqual(
            movement["before"]["mobile_occupants"][0]["position"],
            movement["after"]["mobile_occupants"][0]["position"],
        )
        self.assertEqual(
            movement["before"]["fixed_anchors"], movement["after"]["fixed_anchors"]
        )

        moved_anchor = copy.deepcopy(movement)
        moved_anchor["after"]["fixed_anchors"][0]["position"] = [9, 9]
        diagnostics = {
            item.code
            for item in self.identity.validate_occupant_movement(
                moved_anchor["before"], moved_anchor["after"]
            ).diagnostics
        }
        self.assertIn("FIXED_ANCHOR_RELOCATED", diagnostics)

        deleted_anchor = copy.deepcopy(movement)
        deleted_anchor["after"]["fixed_anchors"].pop()
        diagnostics = {
            item.code
            for item in self.identity.validate_occupant_movement(
                deleted_anchor["before"], deleted_anchor["after"]
            ).diagnostics
        }
        self.assertIn("FIXED_ANCHOR_MISSING", diagnostics)

        identity_swap = copy.deepcopy(movement)
        identity_swap["after"]["mobile_occupants"][0]["id"] = (
            "mapping_fixture:entity:replacement_innkeeper"
        )
        diagnostics = {
            item.code
            for item in self.identity.validate_occupant_movement(
                identity_swap["before"], identity_swap["after"]
            ).diagnostics
        }
        self.assertIn("MOBILE_OCCUPANT_IDENTITY_CHANGED", diagnostics)

    def test_movement_validation_rejects_malformed_positions_without_mutation(self) -> None:
        movement = self.fixtures.make_fixed_anchor_mobile_occupant_fixture()
        before = copy.deepcopy(movement["before"])
        after = copy.deepcopy(movement["after"])
        movement["after"]["fixed_anchors"][0]["position"] = [True, 0]
        after_before_validation = copy.deepcopy(movement["after"])

        result = self.identity.validate_occupant_movement(
            movement["before"], movement["after"]
        )

        self.assertIn("POSITION_COORDINATE", {item.code for item in result.diagnostics})
        self.assertEqual(movement["before"], before)
        self.assertEqual(movement["after"], after_before_validation)
        self.assertNotEqual(movement["after"], after)

    def test_negative_companion_fixtures_have_stable_normalized_diagnostics(self) -> None:
        def orientation_conflict() -> object:
            bundle = self.fixtures.make_extraction_fixture()
            bundle["fixture"]["scene"]["orientation"] = {
                "status": "known",
                "frame": "south_up",
                "provenance": {"class": "builder_authored", "source_refs": []},
            }
            result = self.contract.validate_fixture(
                bundle["fixture"],
                bundle["approved_topology"],
                bundle["consulted_source_refs"],
            )
            return self.diagnostics.normalize_diagnostics(
                result.diagnostics,
                default_layer="authoring",
                relation="orientation",
            )

        def reciprocal_bearing_conflict() -> object:
            bundle = self.fixtures.make_linked_tavern_fixture()
            bundle["bearings"][1]["direction"] = "east"
            result = self.identity.validate_linked_views(bundle)
            return self.diagnostics.normalize_diagnostics(
                result.diagnostics,
                default_layer="identity",
                relation="reciprocal_bearing",
            )

        def duplicate_fact_id() -> object:
            fixture = _make_fixture()
            fixture["facts"].append(copy.deepcopy(fixture["facts"][0]))
            result = self.contract.validate_fixture(
                fixture, _make_topology(), (_SOURCE_REF,)
            )
            return self.diagnostics.normalize_diagnostics(
                result.diagnostics,
                default_layer="authoring",
                relation="oak-bearing",
            )

        def missing_stage_relation() -> object:
            fixture, expected, topology = _make_coverage_case()
            fixture["facts"] = []
            report = self.coverage.validate_positional_coverage(
                fixture, expected, topology, (_SOURCE_REF,)
            )
            return self.diagnostics.normalize_diagnostics(
                report.coverage_diagnostics,
                default_layer="relationship_coverage",
            )

        def truncated_path_extent() -> object:
            fixture, expected, topology = _make_coverage_case()
            fixture["extension_seams"]["multi_cell_extents"][0][
                "schematic_cells"
            ] = [[0, 0], [1, 0]]
            report = self.coverage.validate_positional_coverage(
                fixture, expected, topology, (_SOURCE_REF,)
            )
            return self.diagnostics.normalize_diagnostics(
                report.coverage_diagnostics,
                default_layer="relationship_coverage",
                relation="path_extent",
            )

        def inferred_door() -> object:
            bundle = self.fixtures.make_linked_tavern_fixture()
            fixture = bundle["views"][0]["fixture"]
            fixture["facts"].append(
                {
                    "id": "mapping_fixture:fact:inferred-door",
                    "subject_id": fixture["scene"]["id"],
                    "predicate": "door",
                    "object_id": fixture["fixed_anchors"][0]["id"],
                    "status": "known",
                    "value": True,
                    "provenance": {"class": "builder_authored", "source_refs": []},
                }
            )
            result = self.identity.validate_linked_views(bundle)
            return self.diagnostics.normalize_diagnostics(
                result.diagnostics, default_layer="identity", relation="door"
            )

        def moved_fixed_anchor() -> object:
            movement = self.fixtures.make_fixed_anchor_mobile_occupant_fixture()
            movement["after"]["fixed_anchors"][0]["position"] = [9, 9]
            result = self.identity.validate_occupant_movement(
                movement["before"], movement["after"]
            )
            return self.diagnostics.normalize_diagnostics(
                result.diagnostics,
                default_layer="identity",
                relation="fixed_anchor_position",
            )

        def pc_contamination() -> object:
            fixture = _make_fixture()
            fixture["initial_mobile_occupants"][0]["kind"] = "player_character"
            result = self.contract.validate_fixture(
                fixture, _make_topology(), (_SOURCE_REF,)
            )
            return self.diagnostics.normalize_diagnostics(
                result.diagnostics,
                default_layer="authoring",
                relation="initial_occupant",
            )

        cases = (
            (
                "compass_orientation",
                orientation_conflict,
                self.diagnostics.StableDiagnostic(
                    "ORIENTATION_CONFLICT",
                    "authoring",
                    "orientation",
                    "$.scene.orientation.frame",
                ),
            ),
            (
                "reciprocal_bearing",
                reciprocal_bearing_conflict,
                self.diagnostics.StableDiagnostic(
                    "NONRECIPROCAL_BEARING",
                    "identity",
                    "reciprocal_bearing",
                    "$.bearings",
                ),
            ),
            (
                "duplicate_id",
                duplicate_fact_id,
                self.diagnostics.StableDiagnostic(
                    "DUPLICATE_ID",
                    "authoring",
                    "oak-bearing",
                    "$.facts[1].id",
                ),
            ),
            (
                "missing_relationship",
                missing_stage_relation,
                self.diagnostics.StableDiagnostic(
                    "MISSING_RELATION",
                    "relationship_coverage",
                    "approach_to_threshold",
                    "$.facts",
                ),
            ),
            (
                "truncated_extent",
                truncated_path_extent,
                self.diagnostics.StableDiagnostic(
                    "EXTENT_TRUNCATED",
                    "relationship_coverage",
                    "path_extent",
                    "$.extension_seams.multi_cell_extents[0].schematic_cells",
                ),
            ),
            (
                "frontage_door_inference",
                inferred_door,
                self.diagnostics.StableDiagnostic(
                    "UNSUPPORTED_SCENE_FACT",
                    "identity",
                    "door",
                    "$.views[market].fixture.facts[0].predicate",
                ),
            ),
            (
                "moved_anchor",
                moved_fixed_anchor,
                self.diagnostics.StableDiagnostic(
                    "FIXED_ANCHOR_RELOCATED",
                    "identity",
                    "fixed_anchor_position",
                    "$.after.fixed_anchors[mapping_fixture:entity:shared_tavern].position",
                ),
            ),
            (
                "pc_contamination",
                pc_contamination,
                self.diagnostics.StableDiagnostic(
                    "PC_INITIAL_OCCUPANT",
                    "authoring",
                    "initial_occupant",
                    "$.initial_mobile_occupants[0].kind",
                ),
            ),
        )
        for name, run_case, expected in cases:
            with self.subTest(family=name):
                first = run_case()
                second = run_case()
                self.assertEqual(first, second)
                self.assertIn(expected, first)

    def test_builder_staged_arrival_fixtures_bind_authorship_and_preserve_unknown_cues(self) -> None:
        fixtures = self.arrival_fixtures.make_staged_arrival_fixtures()
        self.assertEqual(set(fixtures), {"G", "H", "I"})
        before = copy.deepcopy(fixtures)

        for fixture_id, bundle in fixtures.items():
            with self.subTest(fixture=fixture_id):
                first = self.arrival.validate_staged_arrival(bundle)
                second = self.arrival.validate_staged_arrival(bundle)

                self.assertTrue(first.is_valid, first.diagnostics)
                self.assertEqual(first, second)
                self.assertEqual(bundle, before[fixture_id])
                metadata = bundle["arrival_candidate"]["metadata"]
                self.assertFalse(metadata["held_out"])
                self.assertFalse(metadata["legacy_truth_verified"])
                self.assertFalse(metadata["llm_builder_tested"])
                self.assertEqual(
                    bundle["arrival_candidate"]["orientation"],
                    {
                        "status": "known",
                        "frame": "north_up",
                        "provenance": {
                            "class": "builder_authored",
                            "source_refs": [
                                bundle["arrival_candidate"]["source_provenance"]["source_ref"]
                            ],
                        },
                    },
                )
                self.assertEqual(
                    [segment["role"] for segment in bundle["candidate"]["arrival_segments"]],
                    ["approach", "threshold", "focal"],
                )
                self.assertEqual(
                    {
                        fact["predicate"]
                        for fact in bundle["arrival_reference"]["facts"]
                    }
                    & {"approach_to_threshold", "threshold_to_focal"},
                    {"approach_to_threshold", "threshold_to_focal"},
                )

        for fixture_id in ("H", "I"):
            with self.subTest(non_cue_fixture=fixture_id):
                cues = fixtures[fixture_id]["arrival_candidate"]["cue_states"]
                self.assertEqual(
                    [(item["cue"], item["status"]) for item in cues],
                    [
                        ("light", "not_applicable"),
                        ("sound", "not_applicable"),
                        ("weather", "unknown"),
                    ],
                )
        self.assertEqual(
            fixtures["H"]["arrival_candidate"]["next_section"]["status"],
            "not_applicable",
        )

    def test_staged_arrival_rejects_unapproved_builder_orientation_and_tampered_text(self) -> None:
        orientation = self.arrival_fixtures.make_staged_arrival_fixtures()["H"]
        orientation["arrival_candidate"]["orientation"]["frame"] = "south_up"
        orientation_result = self.arrival.validate_staged_arrival(orientation)
        self.assertIn(
            ("ARRIVAL_ORIENTATION_FRAME_UNAPPROVED", "$.arrival_candidate.orientation.frame"),
            {(item.code, item.path) for item in orientation_result.diagnostics},
        )

        prose = self.arrival_fixtures.make_staged_arrival_fixtures()["G"]
        prose["candidate"]["arrival_segments"][1]["text"] += " A hidden exit opens east."
        prose_result = self.arrival.validate_staged_arrival(prose)
        self.assertIn(
            ("ARRIVAL_TEXT_BINDING_MISMATCH", "$.candidate.arrival_segments[1].text"),
            {(item.code, item.path) for item in prose_result.diagnostics},
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
