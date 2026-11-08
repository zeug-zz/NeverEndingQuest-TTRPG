# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free guarded-camp and unknown-mechanics fixture tests."""

from __future__ import annotations

import builtins
import copy
import hashlib
import http.client
import importlib
import json
from pathlib import Path
import socket
import urllib.request
import unittest
from unittest.mock import patch


_FORBIDDEN_IMPORT_ROOTS = {
    "anthropic",
    "config",
    "core",
    "firelight",
    "http",
    "httpx",
    "main",
    "model_config",
    "openai",
    "requests",
    "socket",
    "titan",
    "urllib",
    "utils",
    "web",
}
_ACTIONS = (
    "arrival",
    "look",
    "investigate_tent",
    "investigate_research_tent",
    "investigate_sleeping_tent",
    "investigate_supply_tent",
    "attempt_fire_lighting",
)
_UNKNOWN_MECHANICS = (
    "access",
    "audibility",
    "distance",
    "legality",
    "line_of_sight",
    "movement_cost",
    "scale",
    "travel_time",
)
_TEST_FIXTURES: object | None = None
_TEST_KNOWLEDGE: object | None = None
_TEST_PROJECTIONS: object | None = None


class MiseEnSceneProjectionFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        original_import = builtins.__import__

        def guarded_import(name: str, *args: object, **kwargs: object) -> object:
            import_root = name.split(".", 1)[0]
            if import_root in _FORBIDDEN_IMPORT_ROOTS:
                raise AssertionError("forbidden runtime/provider import: " + name)
            return original_import(name, *args, **kwargs)

        with patch.object(builtins, "__import__", side_effect=guarded_import):
            cls.fixtures = importlib.import_module("mise_en_scene.fixtures")
            cls.knowledge = importlib.import_module("mise_en_scene.knowledge")
            cls.projections = importlib.import_module("mise_en_scene.projections")
            cls.diagnostics = importlib.import_module("mise_en_scene.diagnostics")
            cls.arrival = importlib.import_module("mise_en_scene.arrival")
            cls.arrival_fixtures = importlib.import_module(
                "mise_en_scene.arrival_fixtures"
            )
        global _TEST_FIXTURES, _TEST_KNOWLEDGE, _TEST_PROJECTIONS
        _TEST_FIXTURES = cls.fixtures
        _TEST_KNOWLEDGE = cls.knowledge
        _TEST_PROJECTIONS = cls.projections

    def _bundle(self) -> dict[str, object]:
        return self.fixtures.make_guarded_camp_fixture()

    def _linked_bundle(self) -> dict[str, object]:
        return self.fixtures.make_linked_two_scene_knowledge_fixture()

    def _projections(
        self, bundle: dict[str, object], audience: str = "public"
    ) -> dict[str, dict[str, object]]:
        return self.projections.build_matched_projections(
            bundle["candidate"], bundle["reference"], audience=audience
        )

    def _view(
        self, bundle: dict[str, object], audience: str, action: str
    ) -> dict[str, object]:
        return self.knowledge.build_knowledge_view(
            bundle["candidate"],
            bundle["guard_reference"],
            audience=audience,
            action=action,
        )

    def _lineage_case(self) -> dict[str, object]:
        bundle = self._linked_bundle()
        outputs = self._projections(bundle)
        facts = {
            item["id"]: item for item in bundle["candidate"]["facts"]
        }
        source_fact = copy.deepcopy(facts["mapping_fixture:fact:forest-edge-visited"])
        builder_fact = copy.deepcopy(facts["mapping_fixture:fact:approach-threshold"])
        unknown_fact = copy.deepcopy(
            facts["mapping_fixture:fact:weather-gradient-unknown"]
        )
        return {
            "expectations": [
                {
                    "fact_id": source_fact["id"],
                    "relation": source_fact["predicate"],
                    "source_status": "supported",
                    "origin_class": "source_extracted",
                },
                {
                    "fact_id": builder_fact["id"],
                    "relation": builder_fact["predicate"],
                    "source_status": "absent",
                    "origin_class": "builder_authored",
                },
                {
                    "fact_id": unknown_fact["id"],
                    "relation": unknown_fact["predicate"],
                    "source_status": "absent",
                    "origin_class": "unknown",
                },
            ],
            "source": [copy.deepcopy(source_fact)],
            "extraction": [
                copy.deepcopy(source_fact),
                copy.deepcopy(unknown_fact),
            ],
            "authoring": [
                copy.deepcopy(source_fact),
                copy.deepcopy(builder_fact),
                copy.deepcopy(unknown_fact),
            ],
            "outputs": outputs,
            "approved_hashes": {
                condition: hashlib.sha256(
                    output["content"].encode("utf-8")
                ).hexdigest()
                for condition, output in outputs.items()
            },
        }

    def _trace_lineage(self, case: dict[str, object]) -> object:
        return self.diagnostics.trace_fact_lineage(
            case["expectations"],
            case["source"],
            case["extraction"],
            case["authoring"],
            case["outputs"],
            case["approved_hashes"],
        )

    def _assert_public_view_hides_guard(self, view: dict[str, object]) -> None:
        bundle = self._bundle()
        candidate = bundle["candidate"]
        guarded = candidate["guarded_fact"]
        serialized = json.dumps(view, sort_keys=True, separators=(",", ":"))
        for secret in (
            guarded["id"],
            guarded["payload"],
            guarded["trigger_action"],
            candidate["source_provenance"]["source_ref"],
            candidate["source_provenance"]["path"],
            candidate["source_provenance"]["sha256"],
            "gm_only",
        ):
            self.assertNotIn(secret, serialized)
        self.assertNotIn("guarded_fact", view)
        self.assertNotIn("unknown_mechanics", view)
        self.assertNotIn("metadata", view)
        self.assertNotIn("provenance", serialized)

    def _all_keys(self, value: object) -> set[str]:
        if type(value) is dict:
            keys = {key for key in value if type(key) is str}
            for item in value.values():
                keys.update(self._all_keys(item))
            return keys
        if type(value) is list:
            keys: set[str] = set()
            for item in value:
                keys.update(self._all_keys(item))
            return keys
        return set()

    def test_guarded_camp_provenance_and_authorship_are_bounded(self) -> None:
        bundle = self._bundle()
        second = self._bundle()
        candidate = bundle["candidate"]
        reference = bundle["guard_reference"]
        self.assertEqual(bundle, second)
        self.assertIsNot(candidate, reference)
        self.assertIsNot(candidate["public_facts"], second["candidate"]["public_facts"])
        self.assertNotIn("guard_reference", candidate)
        self.assertEqual(candidate["initial_mobile_occupants"], [])
        self.assertTrue(
            all(
                item["authorship"] == "builder_authored_example"
                and item["legacy_truth_verified"] is False
                for item in candidate["public_facts"]
            )
        )
        self.assertEqual(candidate["guarded_fact"]["provenance_class"], "source_extracted")
        self.assertIs(candidate["guarded_fact"]["legacy_truth_verified"], False)

        source_path = Path(__file__).resolve().parents[1] / candidate[
            "source_provenance"
        ]["path"]
        source_text = source_path.read_text(encoding="utf-8")
        start_marker = "### Appendix H. Abandoned research camp: investigation mise-en-scene\n"
        start = source_text.index(start_marker)
        end = source_text.index("### Appendix I.", start)
        section_hash = hashlib.sha256(source_text[start:end].encode("utf-8")).hexdigest()
        self.assertEqual(candidate["source_provenance"]["sha256"], section_hash)
        self.assertEqual(candidate["source_provenance"]["source_ref"], "source:owner-feedback-appendix-h")
        self.assertEqual(reference["source_provenance"], candidate["source_provenance"])
        self.assertEqual(
            {item["name"] for item in candidate["unknown_mechanics"]},
            set(_UNKNOWN_MECHANICS),
        )

    def test_public_arrival_map_and_gm_views_keep_all_actions_separate(self) -> None:
        bundle = self._bundle()
        for action in _ACTIONS:
            with self.subTest(action=action):
                arrival = self._view(bundle, "public_arrival", action)
                public_map = self._view(bundle, "public_map", action)
                gm = self._view(bundle, "gm", action)
                self._assert_public_view_hides_guard(arrival)
                self._assert_public_view_hides_guard(public_map)
                self.assertEqual(arrival["surface"], "arrival")
                self.assertEqual(public_map["surface"], "map")
                self.assertEqual(arrival["facts"], public_map["facts"])
                self.assertIn("schematic_positions", public_map)

                guard = gm["guarded_fact"]
                expected_met = action == "attempt_fire_lighting"
                self.assertIs(guard["trigger_condition_met"], expected_met)
                self.assertEqual(guard["trigger_action"], "attempt_fire_lighting")
                self.assertEqual(guard["effect"], {"status": "unknown", "value": None})
                self.assertEqual(guard["visibility"], "gm_only")
                gm_keys = self._all_keys(gm)
                self.assertNotIn("effects", gm_keys)
                self.assertNotIn("damage", gm_keys)
                self.assertNotIn("encounter", gm_keys)
                self.assertNotIn("narrative", gm_keys)
                self.assertNotIn("state_changes", gm_keys)

    def test_public_views_are_identical_after_fire_attempt(self) -> None:
        bundle = self._bundle()
        for audience in ("public_arrival", "public_map"):
            before = self._view(bundle, audience, "arrival")
            after = self._view(bundle, audience, "attempt_fire_lighting")
            self.assertEqual(before, after)
            self._assert_public_view_hides_guard(after)

    def test_unknown_audience_and_action_fail_closed(self) -> None:
        bundle = self._bundle()
        with self.assertRaises(self.knowledge.KnowledgeFixtureError) as audience_error:
            self._view(bundle, "public_gm", "attempt_fire_lighting")
        self.assertEqual(audience_error.exception.code, "AUDIENCE_NOT_ALLOWLISTED")

        with self.assertRaises(self.knowledge.KnowledgeFixtureError) as action_error:
            self._view(bundle, "public_arrival", "investigate_unknown_object")
        self.assertEqual(action_error.exception.code, "ACTION_NOT_ALLOWLISTED")

        with self.assertRaises(self.knowledge.KnowledgeFixtureError) as gm_action_error:
            self._view(bundle, "gm", "fire_lighting_success")
        self.assertEqual(gm_action_error.exception.code, "ACTION_NOT_ALLOWLISTED")

    def test_candidate_cannot_promote_guarded_fact_to_public(self) -> None:
        bundle = self._bundle()
        reference_before = copy.deepcopy(bundle["guard_reference"])
        bundle["candidate"]["guarded_fact"]["audience"] = "public"
        self.assertEqual(bundle["guard_reference"], reference_before)
        self.assertNotIn("guard_reference", bundle["candidate"])
        with self.assertRaises(self.knowledge.KnowledgeFixtureError) as error:
            self._view(bundle, "public_arrival", "look")
        self.assertEqual(error.exception.code, "GUARDED_VISIBILITY_MISMATCH")

    def test_malformed_guard_and_concrete_unknown_effect_fail_closed(self) -> None:
        bundle = self._bundle()
        bundle["candidate"]["guarded_fact"] = None
        with self.assertRaises(self.knowledge.KnowledgeFixtureError) as malformed:
            self._view(bundle, "gm", "arrival")
        self.assertEqual(malformed.exception.code, "OBJECT_TYPE")

        bundle = self._bundle()
        bundle["candidate"]["guarded_fact"]["effect"] = {
            "status": "known",
            "value": "a summoned creature",
        }
        with self.assertRaises(self.knowledge.KnowledgeFixtureError) as concrete:
            self._view(bundle, "gm", "attempt_fire_lighting")
        self.assertEqual(concrete.exception.code, "PROTECTED_EFFECT_NOT_UNKNOWN")

        bundle = self._bundle()
        bundle["candidate"]["guarded_fact"]["effect"]["value"] = "a flare"
        with self.assertRaises(self.knowledge.KnowledgeFixtureError) as non_null:
            self._view(bundle, "gm", "attempt_fire_lighting")
        self.assertEqual(non_null.exception.code, "PROTECTED_EFFECT_NOT_UNKNOWN")

    def test_each_concrete_schematic_metric_or_rule_is_rejected(self) -> None:
        for metric in _UNKNOWN_MECHANICS:
            with self.subTest(metric=metric):
                bundle = self._bundle()
                item = next(
                    row
                    for row in bundle["candidate"]["unknown_mechanics"]
                    if row["name"] == metric
                )
                item["status"] = "known"
                item["value"] = 5
                with self.assertRaises(self.knowledge.KnowledgeFixtureError) as error:
                    self._view(bundle, "gm", "look")
                self.assertEqual(error.exception.code, "PROTECTED_MECHANIC_NOT_UNKNOWN")

    def test_only_separately_approved_migrated_families_are_firelight_owned(self) -> None:
        classify = self.knowledge.classify_mechanics_authority
        self.assertEqual(
            classify(
                "sample_migrated_family",
                ("sample_migrated_family",),
                runtime_contract_approved=True,
            ),
            "firelight_python_bridge",
        )
        self.assertEqual(
            classify(
                "sample_unmigrated_family",
                ("sample_migrated_family",),
                runtime_contract_approved=True,
            ),
            "python_guard",
        )
        self.assertEqual(
            classify(
                "sample_migrated_family",
                ("sample_migrated_family",),
                runtime_contract_approved=False,
            ),
            "python_guard",
        )
        self.assertEqual(
            classify("future_family", (), runtime_contract_approved=True),
            "python_guard",
        )
        with self.assertRaises(self.knowledge.KnowledgeFixtureError) as approval_error:
            classify(
                "sample_migrated_family",
                ("sample_migrated_family",),
                runtime_contract_approved=1,
            )
        self.assertEqual(approval_error.exception.code, "RUNTIME_APPROVAL_TYPE")
        with self.assertRaises(self.knowledge.KnowledgeFixtureError) as registry_error:
            classify(
                "sample_migrated_family",
                ["sample_migrated_family"],
                runtime_contract_approved=True,
            )
        self.assertEqual(registry_error.exception.code, "MIGRATED_FAMILY_REGISTRY_TYPE")

    def test_fixture_views_are_deterministic_read_only_and_fresh(self) -> None:
        bundle = self._bundle()
        candidate_before = copy.deepcopy(bundle["candidate"])
        reference_before = copy.deepcopy(bundle["guard_reference"])
        for audience in ("public_arrival", "public_map", "gm"):
            first = self._view(bundle, audience, "attempt_fire_lighting")
            second = self._view(bundle, audience, "attempt_fire_lighting")
            self.assertEqual(first, second)
            self.assertIsNot(first, second)
        self.assertEqual(bundle["candidate"], candidate_before)
        self.assertEqual(bundle["guard_reference"], reference_before)

    def test_matched_a_to_d_share_normalized_facts_topology_ids_and_provenance(self) -> None:
        bundle = self._linked_bundle()
        before = copy.deepcopy(bundle)

        outputs = self._projections(bundle)

        self.assertEqual(tuple(outputs), ("A", "B", "C", "D"))
        baseline = outputs["A"]["binding"]
        for condition, output in outputs.items():
            with self.subTest(condition=condition):
                self.assertEqual(output["binding"], baseline)
                self.assertEqual(output["binding"]["fact_ids"], sorted(output["binding"]["fact_ids"]))
                self.assertEqual(output["hashes"]["fact_set_sha256"], baseline["fact_set_sha256"])
                self.assertEqual(output["hashes"]["topology_sha256"], baseline["topology_sha256"])
                self.assertEqual(output["hashes"]["provenance_sha256"], baseline["provenance_sha256"])
        predicates = {fact["predicate"] for fact in baseline["facts"]}
        self.assertTrue({"sound_gradient", "light_gradient", "visible_affordance"} <= predicates)
        unknown_weather = next(
            fact for fact in baseline["facts"] if fact["predicate"] == "weather_gradient"
        )
        self.assertEqual(unknown_weather["status"], "unknown")
        self.assertIsNone(unknown_weather["value"])
        self.assertEqual(bundle, before)

        structured = json.loads(outputs["A"]["content"])
        self.assertEqual(structured["facts"], baseline["facts"])
        self.assertEqual(structured["topology"], baseline["topology"])
        prose = outputs["B"]["content"]
        self.assertEqual(outputs["B"]["content_type"], "text/plain")
        with self.assertRaises(json.JSONDecodeError):
            json.loads(prose)
        self.assertNotIn("Sparse schematic addresses only;", prose)
        self.assertNotIn("Builder-authored staged arrival", prose)
        for fact in baseline["facts"]:
            if fact["status"] == "known":
                self.assertIn(fact["value"], prose)
        self.assertIn(
            "Its fact status is unknown; its knowledge status is known; and its audience is public.",
            prose,
        )
        self.assertIn("Its exact recorded value text is null.", prose)

        self.assertTrue(
            outputs["C"]["content"].startswith(
                outputs["A"]["content"] + "\n\nSparse schematic addresses only;"
            )
        )
        expected_grid = self.projections._render_grid(baseline["topology"])
        self.assertEqual(
            outputs["C"]["content"], outputs["A"]["content"] + "\n\n" + expected_grid
        )
        grid_lines = outputs["C"]["content"].split("Sparse schematic addresses only;", 1)[1]
        self.assertIn("approach", grid_lines)
        self.assertIn("threshold", grid_lines)
        self.assertIn("focal", grid_lines)
        self.assertTrue(
            outputs["D"]["content"].startswith(
                outputs["C"]["content"]
                + "\n\nBuilder-authored staged arrival (approved fixture fragments):\n"
            )
        )
        expected_arrival = "\n".join(
            segment["text"] for segment in bundle["candidate"]["arrival_segments"]
        )
        self.assertEqual(
            outputs["D"]["content"],
            outputs["C"]["content"]
            + "\n\nBuilder-authored staged arrival (approved fixture fragments):\n"
            + expected_arrival,
        )
        self.assertEqual(
            [binding["role"] for binding in outputs["D"]["staging_claim_bindings"]],
            ["approach", "threshold", "focal"],
        )
        facts_by_id = {fact["id"]: fact for fact in baseline["facts"]}
        for claim in outputs["D"]["staging_claim_bindings"]:
            for fact_id in claim["fact_ids"]:
                self.assertEqual(
                    next(item["provenance"] for item in claim["provenance"] if item["fact_id"] == fact_id),
                    facts_by_id[fact_id]["provenance"],
                )

    def test_b_prose_control_contains_every_fact_and_topology_field(self) -> None:
        bundle = self._linked_bundle()
        for audience in ("public", "gm_narrator"):
            with self.subTest(audience=audience):
                outputs = self._projections(bundle, audience)
                prose = outputs["B"]["content"]
                self.assertEqual(outputs["B"]["content_type"], "text/plain")
                with self.assertRaises(json.JSONDecodeError):
                    json.loads(prose)
                self.assertNotIn("Sparse schematic addresses only;", prose)
                self.assertNotIn(
                    "Builder-authored staged arrival (approved fixture fragments)",
                    prose,
                )
                for segment in bundle["candidate"]["arrival_segments"]:
                    self.assertNotIn(segment["text"], prose)

                binding = outputs["B"]["binding"]
                for fact in binding["facts"]:
                    value = (
                        "null"
                        if fact["value"] is None
                        else '"' + fact["value"] + '"'
                    )
                    source_refs = ", ".join(fact["provenance"]["source_refs"]) or "none"
                    expected = (
                        "The fact record "
                        + fact["id"]
                        + " belongs to scene "
                        + fact["scene_id"]
                        + ". Its subject is "
                        + fact["subject_id"]
                        + ", its predicate is "
                        + fact["predicate"]
                        + ", and its object is "
                        + fact["object_id"]
                        + ". Its fact status is "
                        + fact["status"]
                        + "; its knowledge status is "
                        + fact["knowledge_status"]
                        + "; and its audience is "
                        + fact["audience"]
                        + ". Its exact recorded value text is "
                        + value
                        + ". Its provenance class is "
                        + fact["provenance"]["class"]
                        + "; its source references are "
                        + source_refs
                        + "."
                    )
                    self.assertIn(expected, prose)

                for node in binding["topology"]["scene_nodes"]:
                    expected = (
                        "Scene node "
                        + node["id"]
                        + ' is labeled "'
                        + node["label"]
                        + '" and has knowledge status '
                        + node["knowledge_status"]
                        + "."
                    )
                    self.assertIn(expected, prose)
                for link in binding["topology"]["links"]:
                    expected = (
                        "Topology link record "
                        + link["id"]
                        + " lists source scene endpoint "
                        + link["from_scene_id"]
                        + " and destination scene endpoint "
                        + link["to_scene_id"]
                        + ", with relation label "
                        + link["relation"]
                        + "."
                    )
                    self.assertIn(expected, prose)
                for item in binding["topology"]["schematic_layout"]:
                    expected = (
                        "Schematic position record for anchor "
                        + item["anchor_id"]
                        + " in scene "
                        + item["scene_id"]
                        + ' is labeled "'
                        + item["label"]
                        + '" at schematic row '
                        + str(item["row"])
                        + " and schematic column "
                        + str(item["column"])
                        + "."
                    )
                    self.assertIn(expected, prose)

                rumour = next(
                    fact
                    for fact in binding["facts"]
                    if fact["knowledge_status"] == "rumoured"
                )
                rumour_clause = (
                    "Its fact status is "
                    + rumour["status"]
                    + "; its knowledge status is rumoured; and its audience is "
                    + rumour["audience"]
                    + ". Its exact recorded value text is \""
                    + rumour["value"]
                    + "\"."
                )
                self.assertIn(rumour_clause, prose)

    def test_sparse_grid_preserves_signed_scene_row_column_addresses(self) -> None:
        topology = {
            "schematic_layout": [
                {
                    "scene_id": "mapping_fixture:scene:alpha",
                    "anchor_id": "mapping_fixture:entity:threshold",
                    "label": "threshold",
                    "row": -2,
                    "column": -10000,
                },
                {
                    "scene_id": "mapping_fixture:scene:alpha",
                    "anchor_id": "mapping_fixture:entity:focal",
                    "label": "focal",
                    "row": -2,
                    "column": 10000,
                },
                {
                    "scene_id": "mapping_fixture:scene:alpha",
                    "anchor_id": "mapping_fixture:entity:approach",
                    "label": "approach",
                    "row": 1,
                    "column": -10000,
                },
                {
                    "scene_id": "mapping_fixture:scene:beta",
                    "anchor_id": "mapping_fixture:entity:gate",
                    "label": "gate",
                    "row": -2,
                    "column": 0,
                },
                {
                    "scene_id": "mapping_fixture:scene:beta",
                    "anchor_id": "mapping_fixture:entity:marker",
                    "label": "marker",
                    "row": -2,
                    "column": 0,
                },
                {
                    "scene_id": "mapping_fixture:scene:beta",
                    "anchor_id": "mapping_fixture:entity:summit",
                    "label": "summit",
                    "row": 5,
                    "column": 3,
                },
            ]
        }

        rendered_lines = self.projections._render_grid(topology).splitlines()

        self.assertEqual(
            rendered_lines[0],
            "Sparse schematic addresses only; omitted coordinates carry no implication, and collocated anchors share an address. Rows and columns imply no adjacency, connection, compass, metric, access, doors, traversal, perception, or mechanics.",
        )
        self.assertEqual(
            rendered_lines[1:6],
            [
                "Scene mapping_fixture:scene:alpha, schematic row -2, column -10000: anchors threshold (anchor mapping_fixture:entity:threshold).",
                "Scene mapping_fixture:scene:alpha, schematic row -2, column 10000: anchors focal (anchor mapping_fixture:entity:focal).",
                "Scene mapping_fixture:scene:alpha, schematic row 1, column -10000: anchors approach (anchor mapping_fixture:entity:approach).",
                "Scene mapping_fixture:scene:beta, schematic row -2, column 0: anchors gate (anchor mapping_fixture:entity:gate) and marker (anchor mapping_fixture:entity:marker).",
                "Scene mapping_fixture:scene:beta, schematic row 5, column 3: anchors summit (anchor mapping_fixture:entity:summit).",
            ],
        )
        self.assertIn("not blocked, and says nothing about connection", rendered_lines[6])
        self.assertIn(
            "imply no adjacency, connection, compass, metric, access, doors, traversal, perception, or mechanics",
            rendered_lines[0],
        )

        def table_rows(scene_id: str) -> tuple[list[str], list[list[str]], list[str]]:
            heading = "ASCII cell table for scene " + scene_id + ":"
            heading_index = rendered_lines.index(heading)
            header = [part.strip() for part in rendered_lines[heading_index + 1].split("|")]
            rows: list[list[str]] = []
            row_index = heading_index + 3
            while not rendered_lines[row_index].startswith("Legend for "):
                rows.append([part.strip() for part in rendered_lines[row_index].split("|")])
                row_index += 1
            legend: list[str] = []
            row_index += 1
            while row_index < len(rendered_lines) and rendered_lines[row_index].startswith("  "):
                legend.append(rendered_lines[row_index].strip())
                row_index += 1
            return header, rows, legend

        alpha_header, alpha_rows, alpha_legend = table_rows("mapping_fixture:scene:alpha")
        self.assertEqual(alpha_header, ["row/col", "-10000", "10000"])
        self.assertEqual(
            alpha_rows,
            [
                ["-2", "threshold[03]", "focal[02]"],
                ["+1", "approach[01]", "."],
            ],
        )
        self.assertEqual(len(alpha_legend), 3)
        self.assertIn("01 = mapping_fixture:entity:approach (approach)", alpha_legend)

        beta_header, beta_rows, beta_legend = table_rows("mapping_fixture:scene:beta")
        self.assertEqual(beta_header, ["row/col", "0", "3"])
        self.assertEqual(
            beta_rows,
            [
                ["-2", "gate[01], marker[02]", "."],
                ["+5", ".", "summit[03]"],
            ],
        )
        self.assertEqual(len(beta_legend), 3)

        too_many_records = {
            "schematic_layout": [topology["schematic_layout"][0]] * 65,
        }
        with self.assertRaises(self.projections.ProjectionError) as error:
            self.projections._render_grid(too_many_records)
        self.assertEqual(error.exception.code, "GRID_RECORD_LIMIT")

    def test_projection_order_is_canonical_and_repeated_calls_are_identical(self) -> None:
        bundle = self._linked_bundle()
        first = self._projections(bundle)
        second = self._projections(bundle)
        shuffled = copy.deepcopy(bundle)
        shuffled["candidate"]["facts"].reverse()
        shuffled["candidate"]["topology"]["scene_nodes"].reverse()
        shuffled["candidate"]["topology"]["links"].reverse()
        shuffled["candidate"]["topology"]["schematic_layout"].reverse()
        third = self._projections(shuffled)

        self.assertEqual(first, second)
        self.assertEqual(first, third)
        self.assertEqual(bundle["candidate"]["facts"], self._linked_bundle()["candidate"]["facts"])

    def test_content_and_artifact_hashes_bind_the_actual_rendered_text(self) -> None:
        outputs = self._projections(self._linked_bundle())
        for condition, output in outputs.items():
            with self.subTest(condition=condition):
                content_digest = hashlib.sha256(output["content"].encode("utf-8")).hexdigest()
                self.assertEqual(output["hashes"]["content_sha256"], content_digest)
                artifact_payload = {
                    "condition": condition,
                    "audience": "public",
                    "content": output["content"],
                    "fact_set_sha256": output["binding"]["fact_set_sha256"],
                    "topology_sha256": output["binding"]["topology_sha256"],
                    "provenance_sha256": output["binding"]["provenance_sha256"],
                }
                canonical_artifact = json.dumps(
                    artifact_payload,
                    ensure_ascii=True,
                    allow_nan=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                self.assertEqual(
                    output["hashes"]["artifact_sha256"],
                    hashlib.sha256(canonical_artifact.encode("ascii")).hexdigest(),
                )
                tampered = copy.deepcopy(output)
                tampered["content"] += " An unsupported claim."
                self.assertNotEqual(
                    tampered["hashes"]["content_sha256"],
                    hashlib.sha256(tampered["content"].encode("utf-8")).hexdigest(),
                )

    def test_scoped_two_scene_views_preserve_rumour_and_hide_secret_hash_inputs(self) -> None:
        bundle = self._linked_bundle()
        public_outputs = self._projections(bundle, "public")
        gm_outputs = self._projections(bundle, "gm_narrator")
        candidate = bundle["candidate"]
        secret_ids = {
            "mapping_fixture:fact:camp-route-secret",
            "mapping_fixture:fact:camp-trigger-secret",
            "mapping_fixture:fact:camp-effect-unknown",
        }
        hidden_scene_id = "mapping_fixture:scene:camp_clearing"
        hidden_sources = {"source:fixture-gm-route", "source:fixture-gm-trigger"}
        public_serialized = json.dumps(public_outputs, sort_keys=True, separators=(",", ":"))
        gm_serialized = json.dumps(gm_outputs, sort_keys=True, separators=(",", ":"))

        public_facts = public_outputs["A"]["binding"]["facts"]
        self.assertEqual(
            {fact["knowledge_status"] for fact in public_facts},
            {"known", "discovered", "visited", "rumoured"},
        )
        rumour = next(fact for fact in public_facts if fact["knowledge_status"] == "rumoured")
        self.assertEqual(rumour["id"], "mapping_fixture:fact:camp-rumour")
        self.assertNotIn(hidden_scene_id, public_serialized)
        for secret_id in secret_ids:
            self.assertNotIn(secret_id, public_serialized)
        for source_ref in hidden_sources:
            self.assertNotIn(source_ref, public_serialized)
        for secret_id in secret_ids:
            self.assertNotIn(bundle["reference"]["fact_digests"][secret_id], public_serialized)
        self.assertIn(hidden_scene_id, gm_serialized)
        self.assertTrue(secret_ids <= set(gm_outputs["A"]["binding"]["fact_ids"]))
        self.assertTrue(hidden_sources <= {
            source_ref
            for item in gm_outputs["A"]["binding"]["provenance"]
            for source_ref in item["provenance"]["source_refs"]
        })
        gm_effect = next(
            fact for fact in gm_outputs["A"]["binding"]["facts"]
            if fact["id"] == "mapping_fixture:fact:camp-effect-unknown"
        )
        self.assertEqual(gm_effect["status"], "unknown")
        self.assertIsNone(gm_effect["value"])
        self.assertEqual(candidate["topology"]["scene_nodes"][0]["knowledge_status"], "visited")

        changed_secret = copy.deepcopy(bundle)
        route_fact = next(
            fact for fact in changed_secret["candidate"]["facts"]
            if fact["id"] == "mapping_fixture:fact:camp-route-secret"
        )
        route_fact["value"] = "A different concealed route reaches the camp clearing."
        route_fact["provenance"]["source_refs"] = ["source:fixture-gm-route-revised"]
        with self.assertRaises(self.projections.ProjectionError) as public_integrity_error:
            self._projections(changed_secret, "public")
        self.assertEqual(public_integrity_error.exception.code, "FACT_BINDING_MISMATCH")
        with self.assertRaises(self.projections.ProjectionError) as gm_integrity_error:
            self._projections(changed_secret, "gm_narrator")
        self.assertEqual(gm_integrity_error.exception.code, "FACT_BINDING_MISMATCH")

    def test_tampered_arrival_grid_unknown_and_fact_references_fail_closed(self) -> None:
        changed_text = self._linked_bundle()
        changed_text["candidate"]["arrival_segments"][0]["text"] += " The gate is open."
        with self.assertRaises(self.projections.ProjectionError) as prose_error:
            self._projections(changed_text)
        self.assertEqual(prose_error.exception.code, "ARRIVAL_TEXT_BINDING_MISMATCH")

        changed_role = self._linked_bundle()
        changed_role["candidate"]["arrival_segments"][0]["role"] = "threshold"
        with self.assertRaises(self.projections.ProjectionError) as role_error:
            self._projections(changed_role)
        self.assertEqual(role_error.exception.code, "ARRIVAL_ROLE_ORDER")

        changed_fact_ref = self._linked_bundle()
        changed_fact_ref["candidate"]["facts"][1]["object_id"] = "mapping_fixture:entity:unknown"
        with self.assertRaises(self.projections.ProjectionError) as fact_ref_error:
            self._projections(changed_fact_ref)
        self.assertEqual(fact_ref_error.exception.code, "UNKNOWN_FACT_REFERENCE")

        changed_grid = self._linked_bundle()
        changed_grid["candidate"]["topology"]["schematic_layout"][0]["column"] = 9
        with self.assertRaises(self.projections.ProjectionError) as grid_error:
            self._projections(changed_grid)
        self.assertEqual(grid_error.exception.code, "TOPOLOGY_BINDING_MISMATCH")

        known_weather = self._linked_bundle()
        unknown = next(
            fact for fact in known_weather["candidate"]["facts"]
            if fact["id"] == "mapping_fixture:fact:weather-gradient-unknown"
        )
        unknown["status"] = "known"
        unknown["value"] = "Rain grows heavier beyond the threshold."
        unknown["provenance"] = {"class": "builder_authored", "source_refs": []}
        with self.assertRaises(self.projections.ProjectionError) as unknown_error:
            self._projections(known_weather)
        self.assertEqual(unknown_error.exception.code, "FACT_BINDING_MISMATCH")

        self_approved = self._linked_bundle()
        secret = next(
            fact for fact in self_approved["candidate"]["facts"]
            if fact["id"] == "mapping_fixture:fact:camp-route-secret"
        )
        secret["audience"] = "public"
        with self.assertRaises(self.projections.ProjectionError) as audience_error:
            self._projections(self_approved)
        self.assertEqual(audience_error.exception.code, "FACT_AUDIENCE_MISMATCH")

    def test_audience_condition_and_arrival_fact_allowlists_are_strict(self) -> None:
        bundle = self._linked_bundle()
        with self.assertRaises(self.projections.ProjectionError) as audience_error:
            self._projections(bundle, "gm")
        self.assertEqual(audience_error.exception.code, "AUDIENCE_NOT_ALLOWLISTED")
        with self.assertRaises(self.projections.ProjectionError) as audience_type_error:
            self.projections.build_matched_projections(
                bundle["candidate"], bundle["reference"], audience=[]
            )
        self.assertEqual(audience_type_error.exception.code, "AUDIENCE_NOT_ALLOWLISTED")

        outputs = self._projections(bundle)
        self.assertEqual(set(outputs), {"A", "B", "C", "D"})
        secret_claim = self._linked_bundle()
        secret_claim["candidate"]["arrival_segments"][0]["fact_ids"] = [
            "mapping_fixture:fact:camp-route-secret"
        ]
        with self.assertRaises(self.projections.ProjectionError) as claim_error:
            self._projections(secret_claim)
        self.assertEqual(claim_error.exception.code, "ARRIVAL_FACT_BINDING_MISMATCH")

        invalid_condition = self._linked_bundle()
        invalid_condition["candidate"]["condition"] = "E"
        with self.assertRaises(self.projections.ProjectionError) as condition_error:
            self._projections(invalid_condition)
        self.assertEqual(condition_error.exception.code, "UNKNOWN_FIELD")

    def test_unhashable_status_audience_and_long_labels_fail_with_stable_errors(self) -> None:
        expected_codes = {
            "status": "FACT_STATUS",
            "knowledge_status": "KNOWLEDGE_STATUS",
            "audience": "FACT_AUDIENCE",
        }
        for field, expected_code in expected_codes.items():
            for malformed in ([], {}):
                with self.subTest(field=field, malformed=type(malformed).__name__):
                    bundle = self._linked_bundle()
                    bundle["candidate"]["facts"][1][field] = malformed
                    with self.assertRaises(self.projections.ProjectionError) as error:
                        self._projections(bundle)
                    self.assertEqual(error.exception.code, expected_code)

        for group, record_index, label_field in (
            ("scene_nodes", 0, "label"),
            ("schematic_layout", 0, "label"),
        ):
            bundle = self._linked_bundle()
            bundle["candidate"]["topology"][group][record_index][label_field] = (
                "x" * 2049
            )
            with self.subTest(group=group):
                with self.assertRaises(self.projections.ProjectionError) as error:
                    self._projections(bundle)
                self.assertEqual(
                    error.exception.code,
                    "TOPOLOGY_SCENE_LABEL" if group == "scene_nodes" else "LAYOUT_LABEL",
                )

    def test_import_and_execution_tripwires_block_runtime_and_network_access(self) -> None:
        original_import = builtins.__import__

        def guarded_import(name: str, *args: object, **kwargs: object) -> object:
            import_root = name.split(".", 1)[0]
            if import_root in _FORBIDDEN_IMPORT_ROOTS:
                raise AssertionError("forbidden runtime/provider import: " + name)
            return original_import(name, *args, **kwargs)

        def blocked_network(*args: object, **kwargs: object) -> None:
            raise AssertionError("network access is prohibited in fixture validation")

        lineage_case = self._lineage_case()
        with patch.object(builtins, "__import__", side_effect=guarded_import):
            importlib.reload(self.fixtures)
            importlib.reload(self.knowledge)
            importlib.reload(self.projections)
            importlib.reload(self.diagnostics)
            importlib.reload(self.arrival_fixtures)
            importlib.reload(self.arrival)
            bundle = self.fixtures.make_guarded_camp_fixture()
            linked_bundle = self.fixtures.make_linked_two_scene_knowledge_fixture()
            arrival_bundle = self.arrival_fixtures.make_staged_arrival_fixtures()["G"]
            with patch.object(socket, "socket", side_effect=blocked_network):
                with patch.object(socket, "create_connection", side_effect=blocked_network):
                    with patch.object(urllib.request, "urlopen", side_effect=blocked_network):
                        with patch.object(
                            http.client.HTTPConnection,
                            "connect",
                            side_effect=blocked_network,
                        ):
                            public = self.knowledge.build_knowledge_view(
                                bundle["candidate"],
                                bundle["guard_reference"],
                                audience="public_map",
                                action="attempt_fire_lighting",
                            )
                            owner = self.knowledge.classify_mechanics_authority(
                                "sample_migrated_family",
                                ("sample_migrated_family",),
                                runtime_contract_approved=True,
                            )
                            projections = self.projections.build_matched_projections(
                                linked_bundle["candidate"],
                                linked_bundle["reference"],
                                audience="public",
                            )
                            staged_projections = self.arrival.build_staged_arrival_projections(
                                arrival_bundle, audience="public"
                            )
                            lineage = self.diagnostics.trace_fact_lineage(
                                lineage_case["expectations"],
                                lineage_case["source"],
                                lineage_case["extraction"],
                                lineage_case["authoring"],
                                lineage_case["outputs"],
                                lineage_case["approved_hashes"],
                            )
                            guarded = self.diagnostics.diagnose_guarded_content(
                                projections["D"]["content"],
                                ("mapping_fixture:fact:private",),
                            )
        self._assert_public_view_hides_guard(public)
        self.assertEqual(owner, "firelight_python_bridge")
        self.assertEqual(tuple(projections), ("A", "B", "C", "D"))
        self.assertEqual(tuple(staged_projections), ("A", "B", "C", "D"))
        self.assertTrue(lineage.is_valid, lineage.diagnostics)
        self.assertEqual(guarded, ())

    def test_four_stage_lineage_keeps_source_unknown_and_builder_authorship_distinct(self) -> None:
        case = self._lineage_case()
        before = copy.deepcopy(case)

        first = self._trace_lineage(case)
        second = self._trace_lineage(case)

        self.assertTrue(first.is_valid, first.diagnostics)
        self.assertEqual(first, second)
        self.assertEqual(case, before)
        self.assertEqual(
            first.unknowns,
            (
                self.diagnostics.StableDiagnostic(
                    "SOURCE_ABSENCE_UNKNOWN",
                    "source",
                    "weather_gradient",
                    "$.source.facts[mapping_fixture:fact:weather-gradient-unknown]",
                    "info",
                ),
            ),
        )

    def test_lineage_localizes_first_missing_stage_and_compares_fact_content(self) -> None:
        source_fact_id = "mapping_fixture:fact:forest-edge-visited"
        expected_path = {
            "extraction_loss": (
                "EXTRACTION_FACT_MISSING",
                "extraction",
                "$.extraction.facts[%s]" % source_fact_id,
            ),
            "authoring_loss": (
                "AUTHORING_FACT_MISSING",
                "authoring",
                "$.authoring.facts[%s]" % source_fact_id,
            ),
            "projection_loss": (
                "PROJECTION_FACT_MISSING",
                "projection",
                "$.projection.A.binding.facts[%s]" % source_fact_id,
            ),
            "extraction_value_change": (
                "FACT_CONTENT_MISMATCH",
                "extraction",
                "$.extraction.facts[0].value",
            ),
            "authoring_value_change": (
                "FACT_CONTENT_MISMATCH",
                "authoring",
                "$.authoring.facts[0].value",
            ),
            "projection_value_change": (
                "FACT_CONTENT_MISMATCH",
                "projection",
                "$.projection.A.binding.facts[2].value",
            ),
            "source_fact_missing": (
                "SOURCE_FACT_MISSING",
                "source",
                "$.source.facts[%s]" % source_fact_id,
            ),
        }

        def remove_extraction(case: dict[str, object]) -> None:
            case["extraction"].pop(0)

        def remove_authoring(case: dict[str, object]) -> None:
            case["authoring"].pop(0)

        def remove_projection_fact(case: dict[str, object]) -> None:
            case["outputs"]["A"]["binding"]["facts"] = [
                fact
                for fact in case["outputs"]["A"]["binding"]["facts"]
                if fact["id"] != source_fact_id
            ]
            # A fact-ID list cannot stand in for the actual bound fact record.
            self.assertIn(source_fact_id, case["outputs"]["A"]["binding"]["fact_ids"])

        def change_extraction_value(case: dict[str, object]) -> None:
            case["extraction"][0]["value"] = "Changed source-backed value."

        def change_authoring_value(case: dict[str, object]) -> None:
            case["authoring"][0]["value"] = "Changed after extraction."

        def change_projection_value(case: dict[str, object]) -> None:
            fact = next(
                item
                for item in case["outputs"]["A"]["binding"]["facts"]
                if item["id"] == source_fact_id
            )
            fact["value"] = "Changed only in the rendered projection binding."

        def remove_source_fact(case: dict[str, object]) -> None:
            case["source"].clear()

        cases = (
            ("extraction_loss", remove_extraction),
            ("authoring_loss", remove_authoring),
            ("projection_loss", remove_projection_fact),
            ("extraction_value_change", change_extraction_value),
            ("authoring_value_change", change_authoring_value),
            ("projection_value_change", change_projection_value),
            ("source_fact_missing", remove_source_fact),
        )
        for name, mutate in cases:
            with self.subTest(family=name):
                case = self._lineage_case()
                mutate(case)
                first = self._trace_lineage(case)
                second = self._trace_lineage(case)
                self.assertEqual(first, second)
                code, layer, path = expected_path[name]
                self.assertIn(
                    self.diagnostics.StableDiagnostic(
                        code,
                        layer,
                        "scene_status" if name != "projection_loss" else "scene_status",
                        path,
                    ),
                    first.diagnostics,
                )
                if name.endswith("loss") or name == "source_fact_missing":
                    self.assertFalse(first.is_valid)

    def test_unknown_facts_cannot_be_promoted_and_new_builder_facts_need_builder_provenance(self) -> None:
        unknown_id = "mapping_fixture:fact:weather-gradient-unknown"
        cases = (
            ("extraction", "extraction", "$.extraction.facts[1]"),
            ("authoring", "authoring", "$.authoring.facts[2]"),
            ("projection", "projection", "$.projection.B.binding.facts[6]"),
        )
        for name, layer, _path in cases:
            with self.subTest(stage=name):
                case = self._lineage_case()
                if name == "extraction":
                    fact = case["extraction"][1]
                elif name == "authoring":
                    fact = case["authoring"][2]
                else:
                    fact = next(
                        item
                        for item in case["outputs"]["B"]["binding"]["facts"]
                        if item["id"] == unknown_id
                    )
                fact["status"] = "known"
                fact["value"] = "A warm wind rises beyond the threshold."
                report = self._trace_lineage(case)
                found = [item for item in report.diagnostics if item.code == "UNKNOWN_PROMOTED"]
                self.assertEqual(len(found), 1)
                self.assertEqual(found[0].layer, layer)
                self.assertEqual(found[0].relation, "weather_gradient")
                if name == "projection":
                    self.assertIn("$.projection.B.binding.facts", found[0].path)

        bad_builder = self._lineage_case()
        bad_builder["authoring"][1]["provenance"] = {
            "class": "source_extracted",
            "source_refs": ["source:invented"],
        }
        report = self._trace_lineage(bad_builder)
        self.assertIn(
            self.diagnostics.StableDiagnostic(
                "BUILDER_AUTHORING_PROVENANCE",
                "authoring",
                "approach_to_threshold",
                "$.authoring.facts[1].provenance",
            ),
            report.diagnostics,
        )

        promoted_source = self._lineage_case()
        source_unknown = copy.deepcopy(promoted_source["extraction"][1])
        source_unknown["status"] = "known"
        source_unknown["value"] = "A rain front approaches."
        source_unknown["provenance"] = {
            "class": "source_extracted",
            "source_refs": ["source:unverified"],
        }
        promoted_source["source"].append(source_unknown)
        report = self._trace_lineage(promoted_source)
        self.assertIn(
            self.diagnostics.StableDiagnostic(
                "SOURCE_SUPPORT_CONTRADICTION",
                "source",
                "weather_gradient",
                "$.source.facts[1]",
            ),
            report.diagnostics,
        )

    def test_absent_source_unknown_rejects_wrong_relations_at_each_downstream_stage(self) -> None:
        unknown_id = "mapping_fixture:fact:weather-gradient-unknown"
        projection_facts = self._lineage_case()["outputs"]["B"]["binding"]["facts"]
        projection_index = next(
            index
            for index, fact in enumerate(projection_facts)
            if fact["id"] == unknown_id
        )
        cases = (
            (
                "extraction",
                "extraction",
                lambda case: case["extraction"][1],
                "$.extraction.facts[1].predicate",
            ),
            (
                "authoring",
                "authoring",
                lambda case: case["authoring"][2],
                "$.authoring.facts[2].predicate",
            ),
            (
                "projection",
                "projection",
                lambda case: next(
                    fact
                    for fact in case["outputs"]["B"]["binding"]["facts"]
                    if fact["id"] == unknown_id
                ),
                "$.projection.B.binding.facts[%d].predicate" % projection_index,
            ),
        )
        for stage, layer, get_fact, expected_path in cases:
            with self.subTest(stage=stage):
                case = self._lineage_case()
                get_fact(case)["predicate"] = "fabricated_weather"

                first = self._trace_lineage(case)
                second = self._trace_lineage(case)

                self.assertEqual(first, second)
                self.assertIn(
                    self.diagnostics.StableDiagnostic(
                        "FACT_RELATION_MISMATCH",
                        layer,
                        "weather_gradient",
                        expected_path,
                    ),
                    first.diagnostics,
                )
                self.assertFalse(first.is_valid)

    def test_absent_source_unknown_must_remain_explicit_after_source(self) -> None:
        unknown_id = "mapping_fixture:fact:weather-gradient-unknown"

        def remove_extraction(case: dict[str, object]) -> None:
            case["extraction"] = [
                fact for fact in case["extraction"] if fact["id"] != unknown_id
            ]

        def remove_authoring(case: dict[str, object]) -> None:
            case["authoring"] = [
                fact for fact in case["authoring"] if fact["id"] != unknown_id
            ]

        def remove_projection(case: dict[str, object]) -> None:
            binding = case["outputs"]["B"]["binding"]
            binding["facts"] = [
                fact for fact in binding["facts"] if fact["id"] != unknown_id
            ]
            self.assertIn(unknown_id, binding["fact_ids"])

        cases = (
            (
                "extraction",
                remove_extraction,
                self.diagnostics.StableDiagnostic(
                    "EXTRACTION_UNKNOWN_MISSING",
                    "extraction",
                    "weather_gradient",
                    "$.extraction.facts[%s]" % unknown_id,
                ),
            ),
            (
                "authoring",
                remove_authoring,
                self.diagnostics.StableDiagnostic(
                    "AUTHORING_UNKNOWN_MISSING",
                    "authoring",
                    "weather_gradient",
                    "$.authoring.facts[%s]" % unknown_id,
                ),
            ),
            (
                "projection",
                remove_projection,
                self.diagnostics.StableDiagnostic(
                    "PROJECTION_UNKNOWN_MISSING",
                    "projection",
                    "weather_gradient",
                    "$.projection.B.binding.facts[%s]" % unknown_id,
                ),
            ),
        )
        for stage, mutate, expected in cases:
            with self.subTest(stage=stage):
                case = self._lineage_case()
                mutate(case)

                first = self._trace_lineage(case)
                second = self._trace_lineage(case)

                self.assertEqual(first, second)
                self.assertIn(expected, first.diagnostics)
                self.assertIn(
                    self.diagnostics.StableDiagnostic(
                        "SOURCE_ABSENCE_UNKNOWN",
                        "source",
                        "weather_gradient",
                        "$.source.facts[%s]" % unknown_id,
                        "info",
                    ),
                    first.diagnostics,
                )
                self.assertFalse(first.is_valid)

    def test_render_hash_is_independent_and_catches_prose_only_actionable_claims(self) -> None:
        case = self._lineage_case()
        case["outputs"]["D"]["content"] += (
            " The locked door opens and reveals a route into the next room."
        )
        case["outputs"]["D"]["hashes"]["content_sha256"] = hashlib.sha256(
            case["outputs"]["D"]["content"].encode("utf-8")
        ).hexdigest()

        report = self._trace_lineage(case)

        self.assertIn(
            self.diagnostics.StableDiagnostic(
                "PROJECTION_RENDER_MISMATCH",
                "projection",
                "rendered_content",
                "$.projection.D.content",
            ),
            report.diagnostics,
        )
        self.assertNotIn(
            "PROJECTION_CONTENT_HASH_MISMATCH",
            {item.code for item in report.diagnostics},
        )

        bundle = self._linked_bundle()
        bundle["candidate"]["arrival_segments"][0]["text"] += (
            " The locked door opens to the northern road."
        )
        with self.assertRaises(self.projections.ProjectionError) as arrival_error:
            self._projections(bundle)
        normalized = self.diagnostics.normalize_diagnostics(
            (arrival_error.exception,),
            default_layer="projection",
            relation="arrival_claim",
        )
        self.assertIn(
            self.diagnostics.StableDiagnostic(
                "ARRIVAL_TEXT_BINDING_MISMATCH",
                "projection",
                "arrival_claim",
                "$.candidate.arrival_segments[0].text",
            ),
            normalized,
        )

    def test_public_guarded_content_and_schematic_mechanics_have_negative_diagnostics(self) -> None:
        camp = self._bundle()
        outputs = self._projections(self._linked_bundle())
        protected = (
            camp["candidate"]["guarded_fact"]["id"],
            camp["candidate"]["guarded_fact"]["payload"],
            camp["candidate"]["guarded_fact"]["trigger_action"],
        )
        clean = self.diagnostics.diagnose_guarded_content(
            outputs["D"]["content"], protected
        )
        self.assertEqual(clean, ())
        leaked = self.diagnostics.diagnose_guarded_content(
            outputs["D"]["content"] + " " + protected[1], protected
        )
        self.assertEqual(
            leaked,
            (
                self.diagnostics.StableDiagnostic(
                    "GUARDED_CONTENT_LEAK",
                    "projection",
                    "guarded_knowledge",
                    "$.projection.content",
                ),
            ),
        )

        leak_candidate = self._linked_bundle()
        secret = next(
            fact
            for fact in leak_candidate["candidate"]["facts"]
            if fact["id"] == "mapping_fixture:fact:camp-route-secret"
        )
        secret["audience"] = "public"
        with self.assertRaises(self.projections.ProjectionError) as leak_error:
            self._projections(leak_candidate)
        normalized_leak = self.diagnostics.normalize_diagnostics(
            (leak_error.exception,), default_layer="projection"
        )
        self.assertIn(
            self.diagnostics.StableDiagnostic(
                "FACT_AUDIENCE_MISMATCH",
                "projection",
                "",
                "$.candidate.facts[mapping_fixture:fact:camp-route-secret].audience",
            ),
            normalized_leak,
        )

        for metric in ("distance", "legality"):
            with self.subTest(metric=metric):
                candidate = self._bundle()
                item = next(
                    row
                    for row in candidate["candidate"]["unknown_mechanics"]
                    if row["name"] == metric
                )
                item["status"] = "known"
                item["value"] = 5
                with self.assertRaises(self.knowledge.KnowledgeFixtureError) as error:
                    self._view(candidate, "gm", "look")
                normalized = self.diagnostics.normalize_diagnostics(
                    (error.exception,), default_layer="knowledge", relation=metric
                )
                self.assertEqual(
                    normalized,
                    (
                        self.diagnostics.StableDiagnostic(
                            "PROTECTED_MECHANIC_NOT_UNKNOWN",
                            "knowledge",
                            metric,
                            "$.candidate.unknown_mechanics[%d]"
                            % _UNKNOWN_MECHANICS.index(metric),
                        ),
                    ),
                )

    def test_r10_staged_arrival_projection_preserves_matched_facts_and_unknowns(self) -> None:
        fixtures = self.arrival_fixtures.make_staged_arrival_fixtures()
        for fixture_id, bundle in fixtures.items():
            with self.subTest(fixture=fixture_id):
                before = copy.deepcopy(bundle)
                outputs = self.arrival.build_staged_arrival_projections(bundle)
                self.assertEqual(bundle, before)
                self.assertEqual(tuple(outputs), ("A", "B", "C", "D"))
                baseline_binding = outputs["A"]["binding"]
                for condition in ("B", "C", "D"):
                    self.assertEqual(outputs[condition]["binding"], baseline_binding)
                self.assertEqual(
                    outputs["A"]["arrival_binding"],
                    outputs["B"]["arrival_binding"],
                )
                self.assertEqual(
                    outputs["A"]["arrival_binding"],
                    outputs["C"]["arrival_binding"],
                )
                self.assertNotIn("claims", outputs["A"]["arrival_binding"])
                self.assertIn("claims", outputs["D"]["arrival_binding"])
                self.assertEqual(
                    outputs["D"]["arrival_binding"]["orientation"]["frame"],
                    "north_up",
                )
                self.assertEqual(
                    outputs["D"]["arrival_binding"]["source_provenance"],
                    bundle["arrival_candidate"]["source_provenance"],
                )
                self.assertEqual(
                    outputs["D"]["arrival_binding"]["cue_states"],
                    bundle["arrival_candidate"]["cue_states"],
                )
                self.assertEqual(
                    outputs["D"]["arrival_binding"]["next_section"],
                    bundle["arrival_candidate"]["next_section"],
                )
                fact_map = {
                    fact["id"]: fact
                    for fact in outputs["D"]["binding"]["facts"]
                }
                for claim in outputs["D"]["arrival_binding"]["claims"]:
                    with self.subTest(fixture=fixture_id, fact_id=claim["fact_id"]):
                        self.assertIn(claim["fact_id"], fact_map)
                        self.assertEqual(claim["predicate"], fact_map[claim["fact_id"]]["predicate"])
                        self.assertEqual(claim["provenance"], fact_map[claim["fact_id"]]["provenance"])
                for segment in bundle["candidate"]["arrival_segments"]:
                    self.assertIn(segment["text"], outputs["D"]["content"])
                    for condition in ("A", "B", "C"):
                        self.assertNotIn(segment["text"], outputs[condition]["content"])
                self.assertNotIn("The cold fire pit has an unspecified surprise.", outputs["D"]["content"])

        camp = fixtures["H"]
        public_ids = {
            fact["id"]
            for fact in self.arrival.build_staged_arrival_projections(
                camp, audience="public"
            )["D"]["binding"]["facts"]
        }
        gm_ids = {
            fact["id"]
            for fact in self.arrival.build_staged_arrival_projections(
                camp, audience="gm_narrator"
            )["D"]["binding"]["facts"]
        }
        self.assertNotIn("mapping_fixture:fact:h-guard-trigger", public_ids)
        self.assertIn("mapping_fixture:fact:h-guard-trigger", gm_ids)

        cave = fixtures["G"]["arrival_candidate"]
        self.assertEqual(
            [(item["cue"], item["status"]) for item in cave["cue_states"]],
            [("light", "known"), ("sound", "known"), ("weather", "known")],
        )
        self.assertEqual(cave["next_section"]["perception_status"], "partially_visible")

    def test_r10_checkable_arrival_details_are_present_in_facts_and_bound_to_d_spans(self) -> None:
        fixtures = self.arrival_fixtures.make_staged_arrival_fixtures()
        cases = (
            (
                "G",
                "mapping_fixture:fact:g-approach-surface",
                "rain-black limestone",
            ),
            (
                "I",
                "mapping_fixture:fact:i-distortion",
                "settles when the gaze shifts",
            ),
        )
        for fixture_id, fact_id, required_text in cases:
            with self.subTest(fixture=fixture_id):
                bundle = fixtures[fixture_id]
                outputs = self.arrival.build_staged_arrival_projections(bundle)
                baseline_facts = {
                    fact["id"]: fact for fact in outputs["A"]["binding"]["facts"]
                }
                fact = baseline_facts[fact_id]
                self.assertIn(required_text, fact["value"])
                for condition in ("B", "C"):
                    condition_facts = {
                        item["id"]: item
                        for item in outputs[condition]["binding"]["facts"]
                    }
                    self.assertEqual(condition_facts[fact_id], fact)

                claim = next(
                    item
                    for item in outputs["D"]["arrival_binding"]["claims"]
                    if item["fact_id"] == fact_id
                )
                segment = next(
                    item
                    for item in bundle["candidate"]["arrival_segments"]
                    if item["id"] == claim["segment_id"]
                )
                self.assertIn(required_text, claim["span"])
                self.assertIn(claim["span"], segment["text"])
                self.assertEqual(claim["value"], fact["value"])
                self.assertEqual(claim["provenance"], fact["provenance"])

    def test_r10_negative_topology_anchor_and_transition_changes_are_localized(self) -> None:
        anchor = self.arrival_fixtures.make_staged_arrival_fixtures()["H"]
        anchor_record = next(
            item
            for item in anchor["candidate"]["topology"]["schematic_layout"]
            if item["anchor_id"] == "mapping_fixture:entity:research_tent"
        )
        anchor_record["column"] += 1
        anchor_report = self.arrival.validate_staged_arrival(anchor)
        anchor_diagnostics = {
            (item.code, item.path, item.fact_id)
            for item in anchor_report.diagnostics
        }
        self.assertIn(
            (
                "ARRIVAL_ANCHOR_RELOCATED",
                "$.candidate.topology.schematic_layout[mapping_fixture:entity:research_tent]",
                "mapping_fixture:fact:position-research_tent",
            ),
            anchor_diagnostics,
        )

        topology = self.arrival_fixtures.make_staged_arrival_fixtures()["G"]
        topology["candidate"]["topology"]["links"][0]["to_scene_id"] = (
            "mapping_fixture:scene:camp_clearing"
        )
        topology_report = self.arrival.validate_staged_arrival(topology)
        self.assertIn(
            "ARRIVAL_TOPOLOGY_MISMATCH",
            {item.code for item in topology_report.diagnostics},
        )

        transition = self.arrival_fixtures.make_staged_arrival_fixtures()["G"]
        transition["arrival_candidate"]["next_section"]["to_scene_id"] = (
            "mapping_fixture:scene:camp_clearing"
        )
        transition_report = self.arrival.validate_staged_arrival(transition)
        self.assertIn(
            "ARRIVAL_TRANSITION_REFERENCE_MISMATCH",
            {item.code for item in transition_report.diagnostics},
        )

    def test_r10_negative_cue_leak_and_agency_claims_fail_closed(self) -> None:
        cue = self.arrival_fixtures.make_staged_arrival_fixtures()["G"]
        light = next(
            fact
            for fact in cue["candidate"]["facts"]
            if fact["predicate"] == "light_gradient"
        )
        light["value"] = "A blazing sun floods the cave passage."
        cue_report = self.arrival.validate_staged_arrival(cue)
        self.assertIn(
            "FABRICATED_CUE_GRADIENT",
            {item.code for item in cue_report.diagnostics},
        )

        leak = self.arrival_fixtures.make_staged_arrival_fixtures()["H"]
        leak["candidate"]["arrival_segments"][2]["text"] += (
            " " + "The cold fire pit has an unspecified surprise."
        )
        leak_report = self.arrival.validate_staged_arrival(leak)
        self.assertIn(
            "GUARDED_CONTENT_LEAK",
            {item.code for item in leak_report.diagnostics},
        )

        prescriptive = self.arrival_fixtures.make_staged_arrival_fixtures()["I"]
        invitation = next(
            claim
            for group in prescriptive["arrival_candidate"]["claims"]
            for claim in group["claims"]
            if claim["kind"] == "invitation"
        )
        invitation["choice"] = "touch the altar"
        invitation["success"] = "the party succeeds"
        agency_report = self.arrival.validate_staged_arrival(prescriptive)
        self.assertIn(
            "ARRIVAL_AGENCY_VIOLATION",
            {item.code for item in agency_report.diagnostics},
        )


if __name__ == "__main__":
    unittest.main()
