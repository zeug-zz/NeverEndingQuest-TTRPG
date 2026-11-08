# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free tests for the six-scene mise-en-scene holdout draft."""

from __future__ import annotations

import builtins
import hashlib
import importlib
import json
from pathlib import Path
import re
import socket
import sys
import unittest
from unittest.mock import patch


_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


class MiseEnSceneHoldoutDraftTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        original_import = builtins.__import__
        forbidden = {
            "anthropic", "config", "core", "firelight", "http", "httpx",
            "model_config", "openai", "requests", "socket", "titan",
            "urllib", "utils", "web",
        }

        def guarded_import(name: str, *args: object, **kwargs: object) -> object:
            if name.split(".", 1)[0] in forbidden:
                raise AssertionError("forbidden provider/runtime import: " + name)
            return original_import(name, *args, **kwargs)

        with patch.object(builtins, "__import__", side_effect=guarded_import):
            cls.specs = importlib.import_module("mise_en_scene.holdout_draft_specs")
            cls.builder = importlib.import_module("mise_en_scene.build_holdout_draft")
            cls.evaluation = importlib.import_module("mise_en_scene.evaluation")

    def test_selected_sources_and_specs_are_pinned_and_independent(self) -> None:
        scenes = self.specs.build_scene_inputs()
        self.assertEqual(len(scenes), 6)
        hashes = self.specs.selected_source_hashes()
        self.assertEqual(len(hashes), 7)
        self.assertEqual(
            {scene["lineage_status"] for scene in scenes}, {"independent"}
        )
        self.assertTrue(all(scene["adaptation_lineage"] == [] for scene in scenes))
        self.assertEqual(
            len({scene["source_identity"] for scene in scenes}), 6
        )

        for record in self.specs.SCENE_SPECS:
            facts = record["spec"]["facts"]
            for fact in facts:
                if fact["status"] == "unknown":
                    self.assertIsNone(fact["value"])
                    self.assertEqual(fact["provenance"]["class"], "unknown")
                    self.assertEqual(fact["provenance"]["source_refs"], [])
                    self.assertNotIn("authorship", fact)
                elif fact["authorship"] == "builder":
                    self.assertEqual(
                        fact["provenance"]["class"], "builder_authored"
                    )
                else:
                    self.assertEqual(fact["authorship"], "source")
                    self.assertEqual(
                        fact["provenance"]["class"], "source_extracted"
                    )
                    self.assertTrue(fact["provenance"]["source_refs"])

    def test_d_arrival_segments_are_fact_bound_prose_without_meta_terms(self) -> None:
        forbidden_meta_terms = re.compile(
            r"\b(?:staged|authored|selected|anchor|marker)\b", re.IGNORECASE
        )
        for record in self.specs.SCENE_SPECS:
            facts = {
                fact["id"]: fact for fact in record["spec"]["facts"]
            }
            segments = record["spec"]["arrival_segments"]
            self.assertEqual(
                [segment["role"] for segment in segments],
                ["approach", "threshold", "focal"],
            )
            for segment in segments:
                self.assertIsNone(forbidden_meta_terms.search(segment["text"]))
                sentence_count = len(re.findall(r"[.!?](?=\s|$)", segment["text"]))
                self.assertGreaterEqual(sentence_count, 1)
                self.assertLessEqual(sentence_count, 2)
                for fact_id in segment["fact_ids"]:
                    self.assertIn(fact_id, facts)
                    self.assertEqual(facts[fact_id]["status"], "known")
                    self.assertEqual(facts[fact_id]["audience"], "public")

    def test_numillian_fact_sources_name_the_supporting_a01_and_plot_fields(self) -> None:
        record = next(
            item
            for item in self.specs.SCENE_SPECS
            if item["scene_id"].endswith(":scene:trial-at-the-door")
        )
        facts = {fact["id"].rsplit(":", 1)[-1]: fact for fact in record["spec"]["facts"]}
        area_source = "source:modules/The_Hidden_City_of_Numillian/areas/A000_BU.json"
        plot_source = "source:modules/The_Hidden_City_of_Numillian/module_plot_BU.json"
        self.assertEqual(record["source_spans"][0][1], "map.rooms")
        self.assertIn("#map.rooms[id=A01]", record["source_ref"])
        self.assertEqual(facts["location_identity"]["provenance"]["source_refs"], [area_source])
        self.assertEqual(facts["source_connection_a02"]["provenance"]["source_refs"], [area_source])
        for fact_id in (
            "source_visible_rubble_vegetation",
            "source_watchtower",
            "source_shuluth_meets_party",
            "source_shuluth_leads_party",
            "stage_approach",
            "stage_threshold",
            "stage_focal",
            "guarded_illusory_wall",
        ):
            self.assertEqual(
                facts[fact_id]["provenance"]["source_refs"], [plot_source]
            )
        field_refs = record["source_field_refs"]
        self.assertIn(
            {
                "fact_id": facts["location_identity"]["id"],
                "path": "modules/The_Hidden_City_of_Numillian/areas/A000_BU.json",
                "field": "map.rooms[id=A01].name",
            },
            field_refs,
        )
        self.assertIn(
            {
                "fact_id": None,
                "path": "modules/The_Hidden_City_of_Numillian/areas/A000_BU.json",
                "field": "locations[locationId=A01].description (empty; no scene fact extracted)",
            },
            field_refs,
        )
        self.assertIn(
            {
                "fact_id": facts["source_visible_rubble_vegetation"]["id"],
                "path": "modules/The_Hidden_City_of_Numillian/module_plot_BU.json",
                "field": "plotPoints[id=TRIAL000].description",
            },
            field_refs,
        )

    def test_manifest_has_six_scenes_24_artifacts_and_pending_order(self) -> None:
        with patch.object(socket, "socket", side_effect=AssertionError("network forbidden")):
            files, manifest = self.builder._render_files()
        self.assertEqual(manifest["status"], "DRAFT_UNFROZEN")
        self.assertEqual(manifest["authorization_status"], "NOT_OWNER_APPROVED")
        self.assertEqual(manifest["scoring_status"], "NOT_STARTED")
        self.assertEqual(manifest["counts"]["scenes"], 6)
        self.assertEqual(manifest["counts"]["artifacts"], 24)
        self.assertEqual(manifest["leakage_summary"]["pair_checks"], 150)
        self.assertEqual(manifest["assignment"]["status"], "PENDING_OWNER_SEED")
        self.assertIsNone(manifest["assignment"]["seed"])
        self.assertIsNone(manifest["assignment"]["artifact_order"])
        self.assertIsNone(manifest["assignment"]["episode_order"])
        self.assertEqual(
            sum(name.startswith("artifacts/") for name in files), 24
        )
        self.assertEqual(
            sum(name.startswith("scene-specs/") for name in files), 6
        )
        self.assertIn("manifest.draft.json", files)
        self.assertIn("leakage-review.draft.md", files)
        numillian_scene = json.loads(files["scene-specs/trial-at-the-door.json"])
        self.assertTrue(numillian_scene["source"]["source_field_refs"])
        output_root = self.builder._output_directory()
        protocol_hashes = manifest["protocol_hashes"]
        self.assertEqual(
            protocol_hashes["test_sha256"],
            hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        )
        self.assertEqual(
            protocol_hashes["rubric_sha256"],
            hashlib.sha256((output_root / "rubric.md").read_bytes()).hexdigest(),
        )
        self.assertEqual(
            protocol_hashes["assessor_sha256"],
            hashlib.sha256(
                (output_root / "assessor-config.draft.md").read_bytes()
            ).hexdigest(),
        )
        for content in files.values():
            self.assertTrue(content.isascii())
            for line in content.decode("ascii").splitlines():
                self.assertEqual(line, line.rstrip())
        self.assertIsNone(manifest["hashes"]["assignment_seed_sha256"])

        def assert_no_rating_records(value: object) -> None:
            if type(value) is dict:
                for key, child in value.items():
                    self.assertNotIn(
                        str(key).lower(), {"score", "scores", "rating", "ratings"}
                    )
                    assert_no_rating_records(child)
            elif type(value) is list:
                for child in value:
                    assert_no_rating_records(child)

        assert_no_rating_records(manifest)
        self.assertTrue(
            self.evaluation.verify_draft_holdout_manifest(manifest)["is_valid"]
        )

    def test_public_artifacts_exclude_guarded_fact_values(self) -> None:
        files, _manifest = self.builder._render_files()
        artifacts = {
            name: content.decode("ascii")
            for name, content in files.items()
            if name.startswith("artifacts/")
        }
        protected_markers = {
            "shrouded-lantern-encampment": (
                "hidden compartment beneath a loose flagstone",
                "Red Maw token",
            ),
            "abyssal-fracture": (
                "concealed sharp brambles",
                "additional_guarded_effect",
            ),
            "shattered-anvil-crossing": (
                "2d6 fire",
                "concealed compartment beneath the shattered anvil",
            ),
            "sanctum-of-fractured-truths": (
                "hidden locked vestry door",
                "concealing information about the altar",
            ),
            "fogroot-barrow-stalls": (
                "hidden cache beneath the barrow",
                "faint silver trail behind the barrow",
            ),
            "trial-at-the-door": (
                "illusory wall hiding a 20-foot stone wall",
                "anti-flight wards",
                "shared mindscape",
            ),
        }
        for scene_slug, markers in protected_markers.items():
            scene_artifacts = [
                text
                for path, text in artifacts.items()
                if path.startswith("artifacts/" + scene_slug + "/")
            ]
            self.assertEqual(len(scene_artifacts), 4)
            scene_record = next(
                record
                for record in self.specs.SCENE_SPECS
                if record["scene_id"].endswith(":scene:" + scene_slug)
            )
            gm_only_ids = {
                fact["id"]
                for fact in scene_record["spec"]["facts"]
                if fact["audience"] == "gm_only"
            }
            for text in scene_artifacts:
                for fact_id in gm_only_ids:
                    self.assertNotIn(fact_id, text)
                for marker in markers:
                    self.assertNotIn(marker.lower(), text.lower())

    def test_reproducible_generator_output_matches_draft_files(self) -> None:
        files, _manifest = self.builder._render_files()
        self.assertEqual(self.builder._check_files(files), [])
        manifest_path = (
            self.builder._output_directory() / "manifest.draft.json"
        )
        self.assertTrue(manifest_path.is_file())
        digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        self.assertRegex(digest, r"^[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()
