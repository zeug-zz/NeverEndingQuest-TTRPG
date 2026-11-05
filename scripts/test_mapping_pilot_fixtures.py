# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free integrity and deterministic-generation tests for pilot fixtures."""

from __future__ import annotations

import hashlib
import json
import pathlib
import shutil
import sys
import unittest
import uuid
from typing import Dict

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Arm process-wide guards before importing helpers that can write files.
from scripts.core_chat_test_safety import arm_process_tripwires

_PROCESS_TRIPWIRES = arm_process_tripwires()

from scripts.mapping_pilot.fixtures import (
    AREA_ID,
    DEFAULT_MODULE_ROOT,
    FIXTURE_FILES,
    LOCATION_ID_MAP,
    TOWER_AREA_ID,
    build_fixture_payloads,
    load_verified_fixtures,
    write_fixture_outputs,
)
from scripts.mapping_pilot.manifest import (
    ManifestVerificationError,
    verify_manifest,
)


PREREG_ROOT = ROOT / "plans" / "v2-mapping-pilot-prereg"
CAPTURE_AREA = ROOT / "modules" / "Capture_Arena" / "areas" / "CTR001_BU.json"
CAPTURE_MAP = ROOT / "modules" / "Capture_Arena" / "map_CTR001.json"
CAPTURE_CONTEXT = ROOT / "modules" / "Capture_Arena" / "module_context.json"


def _read_json(path: pathlib.Path) -> Dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _tree_bytes(root: pathlib.Path) -> Dict[str, bytes]:
    if not root.exists():
        return {}
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


class MappingPilotFixtureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scratch = pathlib.Path("tmp") / ("mapping_pilot_fixtures_" + uuid.uuid4().hex)
        (ROOT / self.scratch).mkdir(parents=True)

    def tearDown(self) -> None:
        scratch_path = ROOT / self.scratch
        if scratch_path.exists():
            shutil.rmtree(scratch_path)

    def test_every_manifest_entry_verifies_and_canonical_fixtures_are_listed(self) -> None:
        records = verify_manifest(PREREG_ROOT)
        self.assertEqual(len(records), 10)
        self.assertEqual(set(FIXTURE_FILES.values()).issubset(records), True)
        for relative_path, expected_hash in records.items():
            actual_hash = hashlib.sha256((PREREG_ROOT / relative_path).read_bytes()).hexdigest()
            self.assertEqual(actual_hash, expected_hash, relative_path)

    def test_payload_builder_is_in_memory_and_maps_runtime_location_ids(self) -> None:
        fixtures, records = load_verified_fixtures(PREREG_ROOT)
        module_payloads, expected_payloads = build_fixture_payloads(fixtures, records)
        self.assertIn("areas/MPA001_BU.json", module_payloads)
        self.assertIn("areas/MPA002_BU.json", module_payloads)
        self.assertEqual(len(expected_payloads), 4)
        self.assertEqual(
            module_payloads["location_id_map.json"]["runtime_location_ids"],
            LOCATION_ID_MAP,
        )
        self.assertEqual(
            [row["locationId"] for row in module_payloads["areas/MPA001_BU.json"]["locations"]],
            ["MP01", "MP02"],
        )
        self.assertEqual(
            [row["locationId"] for row in module_payloads["areas/MPA002_BU.json"]["locations"]],
            ["MP03"],
        )
        self.assertEqual(
            module_payloads["location_id_map.json"]["runtime_location_ids"],
            LOCATION_ID_MAP,
        )

    def test_generation_is_byte_deterministic_across_two_runs(self) -> None:
        target = self.scratch / "modules" / "Mapping_Pilot_Arena"
        hashes_first = write_fixture_outputs(target)
        capture_root = ROOT / self.scratch
        bytes_first = _tree_bytes(capture_root)
        hashes_second = write_fixture_outputs(target)
        bytes_second = _tree_bytes(capture_root)
        self.assertEqual(hashes_first, hashes_second)
        self.assertEqual(bytes_first, bytes_second)
        self.assertEqual(len(hashes_first), 15)

    def test_tower_approach_is_a_reciprocally_linked_second_area(self) -> None:
        fixtures, records = load_verified_fixtures(PREREG_ROOT)
        module_payloads, _expected_payloads = build_fixture_payloads(fixtures, records)
        primary = module_payloads["areas/%s_BU.json" % AREA_ID]
        tower = module_payloads["areas/%s_BU.json" % TOWER_AREA_ID]
        by_id = {
            location["locationId"]: location
            for area in (primary, tower)
            for location in area["locations"]
        }
        context = module_payloads["module_context.json"]

        self.assertEqual(context["areas"][AREA_ID]["locations"], ["MP01", "MP02"])
        self.assertEqual(context["areas"][TOWER_AREA_ID]["locations"], ["MP03"])
        self.assertEqual(by_id["MP02"]["areaConnectivity"], ["Old Watchtower Approach"])
        self.assertEqual(by_id["MP03"]["areaConnectivity"], ["Mapping Pilot Arena"])

        village_targets = {
            LOCATION_ID_MAP[exit_row["known_destination_location_id"]]
            for exit_row in fixtures["landscape_village"]["locations"][0]["exits"]
            if exit_row.get("known_destination_location_id")
        }
        tower_targets = {
            LOCATION_ID_MAP[exit_row["known_destination_location_id"]]
            for exit_row in fixtures["transition_tower_approach"]["locations"][0]["exits"]
            if exit_row.get("known_destination_location_id")
        }
        self.assertEqual(set(by_id["MP02"]["areaConnectivityId"]), village_targets)
        self.assertEqual(set(by_id["MP03"]["areaConnectivityId"]), tower_targets)
        self.assertIn("MP03", by_id["MP02"]["areaConnectivityId"])
        self.assertIn("MP02", by_id["MP03"]["areaConnectivityId"])

        village_map = module_payloads["map_MPA001.json"]
        tower_map = module_payloads["map_MPA002.json"]
        self.assertEqual([room["id"] for room in village_map["rooms"]], ["MP01", "MP02"])
        self.assertEqual([room["id"] for room in tower_map["rooms"]], ["MP03"])

    def test_runtime_text_uses_module_prose_without_source_ids_or_packet_guidance(self) -> None:
        fixtures, records = load_verified_fixtures(PREREG_ROOT)
        module_payloads, _expected_payloads = build_fixture_payloads(fixtures, records)
        runtime_payloads = {
            path: payload
            for path, payload in module_payloads.items()
            if path != "location_id_map.json"
        }
        runtime_text = json.dumps(runtime_payloads, ensure_ascii=True).lower()
        instructions = {
            location["locationId"]: location["dmInstructions"]
            for area in (
                module_payloads["areas/MPA001_BU.json"],
                module_payloads["areas/MPA002_BU.json"],
            )
            for location in area["locations"]
        }

        self.assertNotIn("mpv2_", runtime_text)
        self.assertIn("Let conversation", instructions["MP01"])
        self.assertIn("Use the well", instructions["MP02"])
        self.assertIn("Let the closed gate", instructions["MP03"])
        for packet_guidance in (
            "required x/y fields",
            "schematic serialization",
            "schematic",
            "infer no distance",
            "authored distances",
            "spatial packet",
            "fixture-authored",
        ):
            self.assertNotIn(packet_guidance, runtime_text)
        self.assertIn("MPV2_", json.dumps(module_payloads["location_id_map.json"]))

    def test_manifest_mismatch_names_path_and_leaves_existing_output_untouched(self) -> None:
        prereg_copy = self.scratch / "tampered_prereg"
        shutil.copytree(PREREG_ROOT, ROOT / prereg_copy)
        tampered_relative = "fixtures/interior_tavern.json"
        tampered_path = ROOT / prereg_copy / tampered_relative
        original = tampered_path.read_bytes()
        tampered_path.write_bytes(original + b" ")

        output_capture_root = ROOT / self.scratch / "sandbox"
        module_root = output_capture_root / "modules" / "Mapping_Pilot_Arena"
        expected_root = output_capture_root / "mapping_pilot" / "expected"
        module_root.mkdir(parents=True)
        expected_root.mkdir(parents=True)
        (module_root / "sentinel.txt").write_bytes(b"module-preserved")
        (expected_root / "stale.json").write_bytes(b"expected-preserved")
        before = _tree_bytes(output_capture_root)

        with self.assertRaises(ManifestVerificationError) as caught:
            write_fixture_outputs(
                self.scratch / "sandbox" / "modules" / "Mapping_Pilot_Arena",
                prereg_copy,
            )
        self.assertIn(tampered_relative, str(caught.exception))
        self.assertEqual(_tree_bytes(output_capture_root), before)

    def test_writer_refuses_repository_modules_tree(self) -> None:
        with self.assertRaises(ValueError):
            write_fixture_outputs(pathlib.Path("modules") / "Mapping_Pilot_Arena")
        self.assertFalse((ROOT / "modules" / "Mapping_Pilot_Arena").exists())

    def test_area_files_include_perceivable_anchors_and_exclude_hidden_fact_text(self) -> None:
        target = self.scratch / "modules" / "Mapping_Pilot_Arena"
        write_fixture_outputs(target)
        area_text_parts = []
        by_id = {}
        for area_id in (AREA_ID, TOWER_AREA_ID):
            area_path = ROOT / target / "areas" / (area_id + ".json")
            area_data = _read_json(area_path)
            area_text_parts.append(area_path.read_text(encoding="utf-8"))
            by_id.update(
                {location["locationId"]: location for location in area_data["locations"]}
            )
        area_text = "\n".join(area_text_parts)

        fixtures, _records = load_verified_fixtures(PREREG_ROOT)
        for fixture in fixtures.values():
            hidden = list(fixture.get("hidden_facts", []))
            source_locations = fixture.get("locations", [])
            for source_location in source_locations:
                hidden.extend(source_location.get("hidden_facts", []))
                runtime_id = LOCATION_ID_MAP.get(source_location.get("location_id"))
                if runtime_id is None:
                    continue
                generated_location = by_id[runtime_id]
                visible_text = json.dumps(generated_location, ensure_ascii=True, sort_keys=True)
                for feature in source_location.get("features", []):
                    if feature.get("perceivable") is True:
                        self.assertIn(feature["name"], visible_text)
                for anchor in source_location.get("npc_anchors", []):
                    if anchor.get("perceivable", True):
                        self.assertIn(anchor["name"], visible_text)
            for fact in hidden:
                if fact:
                    self.assertNotIn(fact, area_text)

        for landmark_fixture in fixtures.values():
            for landmark in landmark_fixture.get("visible_but_unreachable_landmarks", []):
                source_location_id = landmark.get("visible_from_location_id")
                runtime_id = LOCATION_ID_MAP.get(source_location_id)
                if runtime_id:
                    visible_text = json.dumps(by_id[runtime_id], ensure_ascii=True, sort_keys=True)
                    source_features = list(landmark_fixture.get("feature_anchors", []))
                    source_features.extend(
                        feature
                        for source_location in landmark_fixture.get("locations", [])
                        if source_location.get("location_id") == source_location_id
                        for feature in source_location.get("features", [])
                    )
                    feature = next(
                        feature
                        for feature in source_features
                        if feature.get("feature_id") == landmark.get("feature_id")
                    )
                    self.assertIn(feature["name"], visible_text)

        tavern_text = json.dumps(by_id["MP01"], ensure_ascii=True, sort_keys=True)
        combat_fixture = fixtures["combat_stage_tavern_zones"]
        for feature in combat_fixture["feature_anchors"]:
            self.assertIn(feature["name"], tavern_text)
        for occupant in combat_fixture["occupant_roles"]:
            self.assertIn(occupant["name"], tavern_text)

    def test_generated_module_matches_capture_arena_file_key_shapes(self) -> None:
        target = self.scratch / "modules" / "Mapping_Pilot_Arena"
        write_fixture_outputs(target)
        module_root = ROOT / target
        area = _read_json(module_root / "areas" / "MPA001_BU.json")
        map_payload = _read_json(module_root / "map_MPA001.json")
        tower_map_payload = _read_json(module_root / "map_MPA002.json")
        context = _read_json(module_root / "module_context.json")
        capture_area = _read_json(CAPTURE_AREA)
        capture_map = _read_json(CAPTURE_MAP)
        capture_context = _read_json(CAPTURE_CONTEXT)

        self.assertEqual(set(area), set(capture_area))
        self.assertEqual(set(area["locations"][0]), set(capture_area["locations"][0]))
        self.assertEqual(set(map_payload), set(capture_map))
        self.assertEqual(set(map_payload["rooms"][0]), set(capture_map["rooms"][0]))
        self.assertEqual(set(tower_map_payload), set(capture_map))
        self.assertEqual(set(tower_map_payload["rooms"][0]), set(capture_map["rooms"][0]))
        self.assertEqual(set(context), set(capture_context))
        self.assertEqual(
            set(context["areas"][AREA_ID]),
            set(capture_context["areas"]["CTR001"]),
        )
        self.assertEqual(
            set(context["areas"][TOWER_AREA_ID]),
            set(capture_context["areas"]["CTR001"]),
        )
        self.assertEqual(
            set(next(iter(context["npcs"].values()))),
            set(next(iter(capture_context["npcs"].values()))),
        )
        self.assertEqual(
            set(next(iter(context["locations"].values()))),
            set(next(iter(capture_context["locations"].values()))),
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
