# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free tests for authored-source extraction and prompt building."""

from __future__ import annotations

import hashlib
import json
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.mapping_pilot.cartographer import (
    AUDIT_SHEET_FILENAME,
    ATTEMPT_LEDGER_FILENAME,
    MAX_D1_CALLS,
    PROJECT_ROOT,
    build_location_prompts,
    extract_sources,
    invoke_location,
    run_cartographer,
    validate_location_proposal,
)


class CartographerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(dir="tmp")
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        self.slugs = ["Module_A", "Module_B", "Module_C"]
        (self.root / "published_modules.json").write_text(json.dumps({"modules": {slug: {} for slug in self.slugs}}), encoding="utf-8")
        self.selected: dict[str, list[str]] = {}
        self.before: dict[pathlib.Path, bytes] = {}
        for slug in self.slugs:
            module = self.root / slug
            (module / "areas").mkdir(parents=True)
            ids = ["LOC%02d" % i for i in range(1, 8)] if slug != self.slugs[-1] else ["LOC01", "LOC02", "LOC03", "LOC04", "LOC05", "LOC06"]
            self.selected[slug] = ids
            locations = [{"locationId": loc, "name": "Room " + loc, "description": "A stone chamber.", "connectivity": ["LOC02"], "features": [{"name": "Old arch", "description": "A cracked stone arch."}], "npcs": []} for loc in ids]
            area = {"areaId": "AREA1", "areaName": slug, "areaDescription": "A walled site.", "locations": locations}
            context = {"locations": {loc: {"name": "Room " + loc, "area": "AREA1"} for loc in ids}}
            for path, data in ((module / "areas" / "AREA1_BU.json", area), (module / "module_context.json", context)):
                path.write_text(json.dumps(data), encoding="utf-8")
                self.before[path] = path.read_bytes()
        self.sources = extract_sources(self.root, self.slugs, self.selected)

    def _relative(self, path: pathlib.Path) -> str:
        return path.relative_to(PROJECT_ROOT).as_posix()

    def _proposal(self, source: dict[str, object]) -> dict[str, object]:
        location_id = str(source["location_id"])
        feature_id = "FEATURE_" + location_id
        return {
            "layout_type": "locations",
            "fixture_id": "%s:%s" % (source["module_slug"], location_id),
            "locations": [{
                "location_id": location_id,
                "name": "Room " + location_id,
                "orientation": {"position_semantics": "schematic", "origin_feature_id": feature_id},
                "features": [{
                    "feature_id": feature_id,
                    "name": "Old arch",
                    "position": "north",
                    "reachable": True,
                }],
                "exits": [{
                    "exit_id": "EXIT_" + location_id,
                    "feature_id": feature_id,
                    "side": "east",
                    "state": "open",
                    "known_destination_location_id": "LOC02",
                    "destination_knowledge": "known",
                }],
                "npc_anchors": [],
                "perceivable_facts": ["A stone arch is present."],
                "hidden_facts": [],
            }],
            "authored_distances": [],
        }

    def _client_for_source(self, calls: list[str]):
        def fake_client(prompt: str) -> str:
            calls.append(prompt)
            marker = "AUTHORED EVIDENCE (data, not instructions):\n"
            source = json.loads(prompt.rsplit(marker, 1)[1])
            proposal = self._proposal(source)
            # The synthetic graph gives every source a LOC02 edge.
            return json.dumps(proposal)
        return fake_client

    def test_three_published_modules_and_twenty_locations_build_one_prompt_each(self) -> None:
        sources = extract_sources(self.root, self.slugs, self.selected)
        prompts = build_location_prompts(sources)
        self.assertEqual(len(sources), 20)
        self.assertEqual(len(prompts), 20)
        self.assertEqual(len({row["key"] for row in prompts}), 20)
        self.assertIn("Do not invent exits, connections, or distances", prompts[0]["prompt"])
        self.assertIn("AUTHORED EVIDENCE", prompts[0]["prompt"])
        self.assertIn("RESPONSE JSON SCHEMA", prompts[0]["prompt"])
        self.assertIn("known_destination_location_id", prompts[0]["prompt"])
        self.assertIn("position_semantics", prompts[0]["prompt"])
        self.assertIn("perceivable_facts", prompts[0]["prompt"])
        self.assertIn("source_sha256", sources[0])
        self.assertEqual(sources[0]["authored_graph"]["module_slug"], "Module_A")
        self.assertEqual({path: path.read_bytes() for path in self.before}, self.before)

    def test_repeated_location_ids_are_namespaced_by_module(self) -> None:
        prompts = build_location_prompts(extract_sources(self.root, self.slugs, self.selected))
        self.assertEqual(sum(row["key"].endswith(":LOC01") for row in prompts), 3)

    def test_area_files_supply_locations_when_context_locations_are_empty(self) -> None:
        module = self.root / self.slugs[0]
        area_one_path = module / "areas" / "AREA1_BU.json"
        area_one = json.loads(area_one_path.read_text(encoding="utf-8"))
        moved_row = next(row for row in area_one["locations"] if row["locationId"] == "LOC02")
        location_one = next(row for row in area_one["locations"] if row["locationId"] == "LOC01")
        location_one["areaConnectivityId"] = ["LOC02"]
        area_one["locations"] = [row for row in area_one["locations"] if row["locationId"] != "LOC02"]
        area_one_path.write_text(json.dumps(area_one), encoding="utf-8")
        area_two_path = module / "areas" / "AREA2_BU.json"
        area_two_path.write_text(json.dumps({
            "areaId": "AREA2",
            "areaName": "Far Courtyard",
            "areaDescription": "A separate authored area.",
            "locations": [moved_row],
        }), encoding="utf-8")
        (module / "module_context.json").write_text(
            json.dumps({"locations": {}}), encoding="utf-8"
        )

        sources = extract_sources(self.root, self.slugs, self.selected)
        source = next(row for row in sources if row["module_slug"] == self.slugs[0] and row["location_id"] == "LOC01")

        self.assertEqual(source["context"], {})
        self.assertEqual(source["area"]["area_id"], "AREA1")
        self.assertEqual(set(source["authored_graph"]["location_ids"]), set(self.selected[self.slugs[0]]))
        self.assertIn("LOC02", source["authored_graph"]["location_ids"])
        self.assertIn(
            {
                "from_location_id": "LOC01",
                "to_location_id": "LOC02",
                "source_field": "area.areaConnectivityId",
            },
            source["authored_graph"]["outgoing_edges"],
        )
        self.assertIn("Module_A/areas/AREA1_BU.json", source["source_references"])
        self.assertIn("Module_A/module_context.json", source["source_references"])

    def test_duplicate_location_across_area_files_is_refused(self) -> None:
        module = self.root / self.slugs[0]
        source_area_path = module / "areas" / "AREA1_BU.json"
        source_area = json.loads(source_area_path.read_text(encoding="utf-8"))
        duplicate = next(row for row in source_area["locations"] if row["locationId"] == "LOC01")
        (module / "areas" / "AREA2_BU.json").write_text(json.dumps({
            "areaId": "AREA2",
            "areaName": "Second Area",
            "areaDescription": "Duplicate fixture location.",
            "locations": [duplicate],
        }), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "duplicate authored location ID LOC01"):
            extract_sources(self.root, self.slugs, self.selected)

    def test_context_area_disagreement_and_missing_context_are_handled(self) -> None:
        module = self.root / self.slugs[0]
        context_path = module / "module_context.json"
        context_path.write_text(json.dumps({"locations": {"LOC01": {"area": "OTHER"}}}), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "context area disagrees"):
            extract_sources(self.root, self.slugs, self.selected)

        context_path.unlink()
        sources = extract_sources(self.root, self.slugs, self.selected)
        source = next(row for row in sources if row["module_slug"] == self.slugs[0] and row["location_id"] == "LOC01")
        self.assertEqual(source["context"], {})
        self.assertEqual(source["source_references"], ["Module_A/areas/AREA1_BU.json"])
        self.assertEqual(set(source["source_sha256"]), set(source["source_references"]))

    def test_extracts_owner_selected_real_locations_read_only(self) -> None:
        module_slugs = ["Keep_of_Doom", "The_Thornwood_Watch", "The_Pumpkin_Kings_Curse"]
        modules_root = PROJECT_ROOT / "modules"
        missing = [slug for slug in module_slugs if not (modules_root / slug).is_dir()]
        if missing:
            self.skipTest("owner-selected module is absent: %s" % ", ".join(missing))
        selected = {
            "Keep_of_Doom": ["AN01", "AA01", "AG01", "AE01", "AL01", "AN02", "AA02"],
            "The_Thornwood_Watch": ["NC01", "NC02", "NC03", "NC04", "NC05", "RO01"],
            "The_Pumpkin_Kings_Curse": ["AD01", "AB01", "V01", "AB02", "V02", "AB03", "V03"],
        }

        def module_hashes() -> dict[str, str]:
            return {
                path.relative_to(modules_root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted(modules_root.rglob("*"))
                if path.is_file()
            }

        before = module_hashes()
        sources = extract_sources(modules_root, module_slugs, selected)
        after = module_hashes()

        self.assertEqual(len(sources), 20)
        self.assertEqual(
            {(row["module_slug"], row["location_id"]) for row in sources},
            {(slug, location_id) for slug, location_ids in selected.items() for location_id in location_ids},
        )
        for source in sources:
            outgoing_edges = source["authored_graph"]["outgoing_edges"]
            self.assertIsInstance(outgoing_edges, list)
            if not outgoing_edges:
                self.assertEqual(outgoing_edges, [])
        self.assertEqual(after, before)

    def test_rejects_duplicate_or_nonpublished_slugs_and_bad_paths(self) -> None:
        with self.assertRaisesRegex(ValueError, "three unique"):
            extract_sources(self.root, [self.slugs[0]] * 3, self.selected)
        with self.assertRaisesRegex(ValueError, "invalid module slug"):
            extract_sources(self.root, ["../escape", *self.slugs[1:]], self.selected)
        with self.assertRaisesRegex(ValueError, "not published"):
            extract_sources(self.root, ["Unknown", *self.slugs[1:]], self.selected)

    def test_rejects_unknown_location_and_symlink_escape(self) -> None:
        bad = {key: list(value) for key, value in self.selected.items()}
        bad[self.slugs[0]][0] = "MISSING"
        with self.assertRaisesRegex(ValueError, "unknown authored location"):
            extract_sources(self.root, self.slugs, bad)
        outside = self.root.parent / "outside-cartographer"
        outside.mkdir(exist_ok=True)
        self.addCleanup(lambda: outside.rmdir() if outside.exists() else None)
        (self.root / "Link_Module").symlink_to(outside, target_is_directory=True)
        catalog = json.loads((self.root / "published_modules.json").read_text(encoding="utf-8"))
        catalog["modules"]["Link_Module"] = {}
        (self.root / "published_modules.json").write_text(json.dumps(catalog), encoding="utf-8")
        selected = dict(self.selected)
        selected["Link_Module"] = ["LOC01"]
        with self.assertRaisesRegex(ValueError, "escapes"):
            extract_sources(self.root, ["Link_Module", *self.slugs[1:]], selected)

    def test_valid_layout_run_writes_audit_and_attempt_ledger_only_under_tmp(self) -> None:
        sources = self.sources
        output_root = self._relative(self.root / "d1-output")
        calls: list[str] = []
        from utils.file_operations import safe_write_json as real_safe_write_json

        written: list[pathlib.Path] = []

        def guarded_write(path: str, data: object, **kwargs: object) -> bool:
            target = pathlib.Path(path).resolve()
            self.assertTrue(target.is_relative_to(PROJECT_ROOT / "tmp"))
            self.assertFalse(target.is_relative_to(PROJECT_ROOT / "modules"))
            written.append(target)
            return real_safe_write_json(path, data, **kwargs)

        with mock.patch("utils.file_operations.safe_write_json", side_effect=guarded_write):
            audit = run_cartographer(sources, self._client_for_source(calls), output_root)
            audit_path = self.root / "d1-output" / AUDIT_SHEET_FILENAME
            editable_audit = json.loads(audit_path.read_text(encoding="utf-8"))
            editable_audit["owner_precision"] = {
                "numerator": 17,
                "denominator": 20,
                "percent": 85,
                "notes": "owner reviewed",
            }
            editable_audit["proposals"][0]["propositions"][0]["owner_rating"] = "supported"
            audit_path.write_text(json.dumps(editable_audit), encoding="utf-8")
            resumed = run_cartographer(sources, self._client_for_source(calls), output_root)

        self.assertEqual(len(calls), 20)
        self.assertEqual(resumed["attempt_count"], 20)
        self.assertEqual(audit["invented_exit_count"], 0)
        self.assertTrue(resumed["invented_exit_count_evaluable"])
        self.assertEqual(resumed["decision_threshold"]["precision_minimum_percent"], 85)
        self.assertEqual(resumed["decision_threshold"]["invented_exits_maximum"], 0)
        self.assertEqual(resumed["owner_precision"]["numerator"], 17)
        self.assertEqual(resumed["owner_precision"]["denominator"], 20)
        first = audit["proposals"][0]
        self.assertEqual(first["status"], "validated")
        self.assertEqual(first["proposal"], self._proposal(sources[0]))
        self.assertIn("source_references", first["source_evidence"])
        self.assertIn("source_sha256", first["source_evidence"])
        self.assertNotIn("source_evidence", first["proposal"])
        self.assertTrue(first["propositions"])
        self.assertTrue(all(row["owner_rating"] is None for row in first["propositions"]))
        self.assertTrue(any(row["field"] == "side" for row in first["propositions"]))
        self.assertEqual(resumed["proposals"][0]["propositions"][0]["owner_rating"], "supported")
        self.assertEqual({path: path.read_bytes() for path in self.before}, self.before)
        self.assertTrue((self.root / "d1-output" / ATTEMPT_LEDGER_FILENAME).is_file())
        self.assertTrue((self.root / "d1-output" / AUDIT_SHEET_FILENAME).is_file())
        self.assertTrue(all(path.is_relative_to(PROJECT_ROOT / "tmp") for path in written))

    def test_layout_validation_rejects_shape_duplicates_unknown_and_cross_module_exits(self) -> None:
        source = self.sources[0]
        valid = self._proposal(source)
        result = validate_location_proposal(source, valid)
        self.assertTrue(result["valid"])
        self.assertEqual(result["graph_check"]["invented_exit_count"], 0)

        duplicate = self._proposal(source)
        duplicate["locations"][0]["features"].append(dict(duplicate["locations"][0]["features"][0]))
        duplicate_result = validate_location_proposal(source, duplicate)
        self.assertFalse(duplicate_result["valid"])
        self.assertTrue(any("duplicate feature ID" in issue for issue in duplicate_result["validation_issues"]))

        unknown = self._proposal(source)
        unknown["locations"][0]["location_id"] = "NOT_AUTHORED"
        unknown_result = validate_location_proposal(source, unknown)
        self.assertFalse(unknown_result["valid"])
        self.assertTrue(any("unknown or mismatched authored location ID" in issue for issue in unknown_result["validation_issues"]))

        bad_shape = self._proposal(source)
        del bad_shape["locations"][0]["orientation"]
        shape_result = validate_location_proposal(source, bad_shape)
        self.assertFalse(shape_result["valid"])
        self.assertTrue(any("orientation" in issue for issue in shape_result["validation_issues"]))

        # Module_B has an edge to LOC03; Module_A does not. Repeated IDs must
        # never let the other module's graph authorize this exit.
        module_b_area = self.root / "Module_B" / "areas" / "AREA1_BU.json"
        area = json.loads(module_b_area.read_text(encoding="utf-8"))
        area["locations"][0]["connectivity"] = ["LOC03"]
        module_b_area.write_text(json.dumps(area), encoding="utf-8")
        self.before[module_b_area] = module_b_area.read_bytes()
        module_b_source = extract_sources(self.root, self.slugs, self.selected)[7]
        self.assertEqual(module_b_source["location_id"], "LOC01")
        self.assertIn("LOC03", [edge["to_location_id"] for edge in module_b_source["authored_graph"]["outgoing_edges"]])

        cross_module = self._proposal(source)
        cross_module["locations"][0]["exits"][0]["known_destination_location_id"] = "LOC03"
        cross_module_result = validate_location_proposal(source, cross_module)
        self.assertFalse(cross_module_result["valid"])
        self.assertEqual(cross_module_result["graph_check"]["invented_exit_count"], 1)
        self.assertTrue(any("absent from the authored graph" in issue for issue in cross_module_result["validation_issues"]))

        wrong_namespace = self._proposal(source)
        wrong_namespace["fixture_id"] = "Module_B:LOC01"
        namespace_result = validate_location_proposal(source, wrong_namespace)
        self.assertFalse(namespace_result["valid"])
        self.assertTrue(any("module-namespaced source key" in issue for issue in namespace_result["validation_issues"]))

    def test_non_json_and_client_exceptions_are_recorded_as_counted_attempts(self) -> None:
        source = self.sources[0]
        output_root = self._relative(self.root / "invalid-output")
        bad_response = invoke_location(source, lambda _prompt: "not JSON", output_root, selection=self.sources)
        self.assertEqual(bad_response["status"], "invalid_response")
        nonstandard_json = invoke_location(
            source,
            lambda _prompt: '{"layout_type":"locations","nonfinite":NaN}',
            output_root,
            selection=self.sources,
        )
        self.assertEqual(nonstandard_json["status"], "invalid_response")
        failed = invoke_location(
            source,
            lambda _prompt: (_ for _ in ()).throw(RuntimeError("provider detail is not persisted")),
            output_root,
            selection=self.sources,
        )
        self.assertEqual(failed["status"], "client_error")
        ledger = json.loads((self.root / "invalid-output" / ATTEMPT_LEDGER_FILENAME).read_text(encoding="utf-8"))
        audit = json.loads((self.root / "invalid-output" / AUDIT_SHEET_FILENAME).read_text(encoding="utf-8"))
        self.assertEqual(len(ledger["attempts"]), 3)
        self.assertEqual(audit["attempt_count"], 3)
        self.assertNotIn("provider detail", json.dumps(audit))
        self.assertIsNone(audit["invented_exit_count"])

    def test_call_cap_is_persistent_across_retries_and_preserves_partial_audit(self) -> None:
        source, second_source = self.sources[:2]
        selection = self.sources
        output_root = self._relative(self.root / "cap-output")
        call_count = 0

        def failing_client(_prompt: str) -> str:
            nonlocal call_count
            ledger_path = self.root / "cap-output" / ATTEMPT_LEDGER_FILENAME
            self.assertTrue(ledger_path.is_file())
            reserved = json.loads(ledger_path.read_text(encoding="utf-8"))
            self.assertEqual(len(reserved["attempts"]), call_count + 1)
            self.assertEqual(reserved["attempts"][-1]["status"], "reserved")
            call_count += 1
            raise RuntimeError("injected failure")

        successful_calls = 0

        def successful_client(_prompt: str) -> str:
            nonlocal successful_calls
            successful_calls += 1
            return json.dumps(self._proposal(second_source))

        for _ in range(MAX_D1_CALLS - 1):
            result = invoke_location(source, failing_client, output_root, selection=selection)
            self.assertEqual(result["status"], "client_error")

        final_result = invoke_location(
            second_source,
            successful_client,
            output_root,
            selection=selection,
        )
        self.assertEqual(final_result["attempt_number"], MAX_D1_CALLS)
        self.assertEqual(call_count, MAX_D1_CALLS - 1)
        self.assertEqual(successful_calls, 1)

        blocked = invoke_location(
            source,
            lambda _prompt: self.fail("client must not run after the cap"),
            output_root,
            selection=selection,
        )
        self.assertFalse(blocked["attempted"])
        self.assertEqual(blocked["status"], "call_cap_reached")
        resumed = run_cartographer(
            selection,
            lambda _prompt: self.fail("resume must not retry prior locations"),
            output_root,
        )
        self.assertEqual(resumed["attempt_count"], MAX_D1_CALLS)
        self.assertTrue(resumed["call_cap_reached"])
        self.assertEqual(len(resumed["proposals"]), MAX_D1_CALLS)
        self.assertTrue((self.root / "cap-output" / AUDIT_SHEET_FILENAME).is_file())
        ledger = json.loads((self.root / "cap-output" / ATTEMPT_LEDGER_FILENAME).read_text(encoding="utf-8"))
        self.assertEqual(len(ledger["attempts"]), MAX_D1_CALLS)

    def test_credential_fields_in_a_proposal_are_not_persisted(self) -> None:
        source = self.sources[0]
        proposal = self._proposal(source)
        proposal["api_key"] = "must-not-be-written"
        output_root = self._relative(self.root / "credential-output")
        result = invoke_location(
            source,
            lambda _prompt: json.dumps(proposal),
            output_root,
            selection=self.sources,
        )
        self.assertEqual(result["status"], "invalid_layout")
        ledger_text = (self.root / "credential-output" / ATTEMPT_LEDGER_FILENAME).read_text(encoding="utf-8")
        audit_text = (self.root / "credential-output" / AUDIT_SHEET_FILENAME).read_text(encoding="utf-8")
        self.assertNotIn("api_key", ledger_text)
        self.assertNotIn("must-not-be-written", ledger_text)
        self.assertNotIn("api_key", audit_text)
        self.assertNotIn("must-not-be-written", audit_text)

    def test_output_paths_reject_absolute_traversal_and_symlink_before_client_or_write(self) -> None:
        source = self.sources[0]
        calls: list[str] = []
        client = lambda prompt: calls.append(prompt) or json.dumps(self._proposal(source))
        with self.assertRaisesRegex(ValueError, "project-relative tmp"):
            invoke_location(source, client, pathlib.Path("/outside-cartographer"))
        with self.assertRaisesRegex(ValueError, "project-relative tmp"):
            invoke_location(source, client, "tmp/../modules/should-not-exist")

        outside = self.root.parent / "cartographer-output-target"
        outside.mkdir()
        self.addCleanup(lambda: outside.rmdir() if outside.exists() else None)
        link = self.root / "linked-output"
        link.symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlinks"):
            invoke_location(source, client, self._relative(link / "nested"))
        self.assertEqual(calls, [])
        self.assertEqual(list(outside.iterdir()), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
