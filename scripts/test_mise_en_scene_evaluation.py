# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free tests for the proposed R8 holdout-manifest tooling."""

from __future__ import annotations

import builtins
import copy
import hashlib
import importlib
import json
import socket
import unittest
from unittest.mock import patch


_FORBIDDEN_IMPORT_ROOTS = {
    "anthropic",
    "config",
    "core",
    "firelight",
    "http",
    "httpx",
    "model_config",
    "openai",
    "requests",
    "socket",
    "titan",
    "urllib",
    "utils",
    "web",
}
_PROTOCOL_HASHES = {
    "test_sha256": "1" * 64,
    "rubric_sha256": "2" * 64,
    "assessor_sha256": "3" * 64,
}
_SOURCE_TEXTS = (
    "A quartz astrolabe rests beside a basalt plinth.",
    "A copper orrery hangs above a velvet dais.",
    "A silver censer rests within a cedar alcove.",
    "A glass reliquary sits beside a lacquered lectern.",
    "A porcelain sextant lies upon a mahogany cabinet.",
    "An obsidian sundial crowns a marble pedestal.",
)


def _replace_string_values(value: object, old: str, new: str) -> object:
    if type(value) is str:
        return value.replace(old, new)
    if type(value) is list:
        return [_replace_string_values(item, old, new) for item in value]
    if type(value) is dict:
        return {
            _replace_string_values(key, old, new): _replace_string_values(item, old, new)
            for key, item in value.items()
        }
    return value


class MiseEnSceneEvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        original_import = builtins.__import__

        def guarded_import(name: str, *args: object, **kwargs: object) -> object:
            if name.split(".", 1)[0] in _FORBIDDEN_IMPORT_ROOTS:
                raise AssertionError("forbidden provider/runtime import: " + name)
            return original_import(name, *args, **kwargs)

        with patch.object(builtins, "__import__", side_effect=guarded_import):
            cls.fixtures = importlib.import_module("mise_en_scene.fixtures")
            cls.evaluation = importlib.import_module("mise_en_scene.evaluation")
            cls.calibration = importlib.import_module("mise_en_scene.calibration")

        cls.catalog = cls.evaluation.load_known_examples()
        cls.scenes = cls._make_scenes()
        cls.manifest = cls.evaluation.build_proposed_holdout_manifest(
            cls.scenes,
            "synthetic-seed-task-1.8",
            **_PROTOCOL_HASHES,
        )

    @classmethod
    def _make_scenes(cls) -> list[dict[str, object]]:
        scenes: list[dict[str, object]] = []
        for index, source_text in enumerate(_SOURCE_TEXTS):
            bundle = copy.deepcopy(
                cls.fixtures.make_linked_two_scene_knowledge_fixture()
            )
            bundle = _replace_string_values(
                bundle, "mapping_fixture", "holdout%d" % index
            )
            bundle = _replace_string_values(
                bundle, "source:fixture", "source:holdout-%d" % index
            )
            candidate = bundle["candidate"]
            reference = bundle["reference"]
            reference["fact_digests"] = {
                fact["id"]: hashlib.sha256(
                    json.dumps(
                        fact,
                        ensure_ascii=True,
                        allow_nan=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("ascii")
                ).hexdigest()
                for fact in candidate["facts"]
            }
            fingerprints = cls.evaluation.fingerprint_source_text(source_text)
            scene_id = "holdout%d:scene:linked_arrival" % index
            scenes.append(
                {
                    "scene_id": scene_id,
                    "source_identity": "new-source:scene-%d" % index,
                    "source_ref": "fixture:holdout-%d.md#scene-%d" % (index, index),
                    "source_text": source_text,
                    "lineage_status": "independent",
                    "adaptation_lineage": [],
                    "layout_tokens": fingerprints["layout_tokens"],
                    "feature_tokens": fingerprints["feature_tokens"],
                    "projection_candidate": candidate,
                    "projection_reference": reference,
                }
            )
        return scenes

    def _build_manifest(
        self,
        scenes: list[dict[str, object]] | None = None,
        seed: str = "synthetic-seed-task-1.8",
    ) -> dict[str, object]:
        return self.evaluation.build_proposed_holdout_manifest(
            copy.deepcopy(self.scenes if scenes is None else scenes),
            seed,
            **_PROTOCOL_HASHES,
        )

    def _approval(self, manifest: dict[str, object] | None = None) -> dict[str, object]:
        selected = self.manifest if manifest is None else manifest
        assignment = selected["assignment"]
        return {
            "approval_reference": "synthetic-test-only:task-1.8-seed-order",
            "candidate_sha256": selected["candidate_sha256"],
            "assignment_seed_sha256": assignment["seed_sha256"],
            "order_sha256": assignment["order_sha256"],
            "test_only": True,
        }

    def test_bundled_catalog_is_pinned_and_ratings_free(self) -> None:
        catalog_hash = self.evaluation.validate_known_examples(self.catalog)
        self.assertEqual(catalog_hash, self.manifest["catalog"]["sha256"])
        self.assertEqual(len(self.catalog["records"]), 25)
        self.assertEqual(
            sum(record["kind"] == "original_m1" for record in self.catalog["records"]),
            16,
        )
        self.assertEqual(
            sum(
                record["kind"] == "expanded_owner_example"
                for record in self.catalog["records"]
            ),
            9,
        )
        rating_terms = {
            "assessment",
            "assistant",
            "legibility",
            "rating",
            "ratings",
            "score",
            "scores",
            "usefulness",
        }
        for record in self.catalog["records"]:
            if record["kind"] == "expanded_owner_example":
                self.assertIn("source_section_sha256", record)
                self.assertFalse(
                    rating_terms
                    & set(record["layout_tokens"] + record["feature_tokens"])
                )

        def assert_no_rating_keys(value: object) -> None:
            if type(value) is dict:
                for key, child in value.items():
                    self.assertNotIn(str(key).lower(), {"score", "scores", "rating", "ratings"})
                    assert_no_rating_keys(child)
            elif type(value) is list:
                for child in value:
                    assert_no_rating_keys(child)

        assert_no_rating_keys(self.catalog)

    def test_owner_section_hash_is_an_exact_leakage_rejection_input(self) -> None:
        owner_record = next(
            record
            for record in self.catalog["records"]
            if record["record_id"] == "owner:I"
        )
        pair = self.evaluation._make_pair_check(
            {
                "scene_id": "newscene:scene:probe",
                "source": {
                    "identity": "new-source:probe",
                    "reference": "fixture:probe.md#scene",
                    "source_text_sha256": owner_record["source_section_sha256"],
                    "lineage_status": "independent",
                    "adaptation_lineage": [],
                    "text_tokens": [],
                    "layout_tokens": [],
                    "feature_tokens": [],
                },
                "artifacts": [],
            },
            owner_record,
        )
        self.assertTrue(pair["source_section_sha256_match"])
        self.assertIn("EXACT_SOURCE_SECTION_SHA256", pair["flags"])
        self.assertEqual(pair["verdict"], "REJECT")

    def test_builds_exact_matrix_with_150_known_example_pairs(self) -> None:
        manifest = self.manifest
        self.assertEqual(manifest["status"], "PROPOSED")
        self.assertEqual(manifest["authorization_status"], "NOT_AUTHORIZED")
        self.assertEqual(manifest["scoring_status"], "NOT_STARTED")
        self.assertEqual(
            manifest["counts"],
            {
                "scenes": 6,
                "artifacts": 24,
                "conditions": ["A", "B", "C", "D"],
                "episodes": 48,
                "party_shapes": ["P1", "P4"],
            },
        )
        self.assertEqual(manifest["leakage_summary"]["pair_checks"], 150)
        self.assertEqual(manifest["leakage_summary"]["status"], "NO_KNOWN_MATCH")
        self.assertEqual(
            manifest["leakage_summary"]["policy"]["source_text_overlap"],
            {
                "minimum_shared_tokens": 3,
                "minimum_jaccard_ppm": 200_000,
                "exact_token_set_overlap": "review_required",
            },
        )
        self.assertTrue(
            all(len(scene["artifacts"]) == 4 for scene in manifest["scenes"])
        )
        self.assertEqual(
            len(manifest["assignment"]["artifact_order"]), 24
        )
        self.assertEqual(
            len(manifest["assignment"]["episode_order"]), 48
        )
        report = self.evaluation.verify_proposed_manifest(manifest)
        self.assertEqual(report["pair_checks"], 150)
        self.assertEqual(report["artifact_count"], 24)
        self.assertEqual(report["episode_count"], 48)

    def test_assignment_and_manifest_are_deterministic_for_same_inputs(self) -> None:
        repeated = self._build_manifest()
        self.assertEqual(repeated, self.manifest)
        self.assertEqual(
            self.manifest["assignment"]["algorithm"], "sha256-rank-v1"
        )

    def test_rejects_non_six_scene_inputs(self) -> None:
        cases = {
            5: self.scenes[:5],
            7: self.scenes + [copy.deepcopy(self.scenes[0])],
        }
        for count, scenes in cases.items():
            with self.subTest(count=count):
                with self.assertRaises(self.evaluation.EvaluationManifestError) as caught:
                    self._build_manifest(scenes)
                self.assertEqual(caught.exception.code, "SCENE_COUNT_EXACTLY_SIX")

    def test_rejects_duplicate_scene_ids_and_source_identities(self) -> None:
        duplicate_scene = copy.deepcopy(self.scenes)
        duplicate_scene[1]["scene_id"] = duplicate_scene[0]["scene_id"]
        duplicate_scene[1]["projection_candidate"]["fixture_id"] = duplicate_scene[0]["scene_id"]
        duplicate_scene[1]["projection_reference"]["fixture_id"] = duplicate_scene[0]["scene_id"]
        with self.assertRaises(self.evaluation.EvaluationManifestError) as caught_scene:
            self._build_manifest(duplicate_scene)
        self.assertEqual(caught_scene.exception.code, "DUPLICATE_SCENE_ID")

        duplicate_source = copy.deepcopy(self.scenes)
        duplicate_source[1]["source_identity"] = duplicate_source[0]["source_identity"]
        with self.assertRaises(self.evaluation.EvaluationManifestError) as caught_source:
            self._build_manifest(duplicate_source)
        self.assertEqual(caught_source.exception.code, "DUPLICATE_SOURCE_IDENTITY")

    def test_source_fingerprint_vectors_must_match_source_text(self) -> None:
        altered = copy.deepcopy(self.scenes)
        altered[0]["feature_tokens"] = ["invented_feature"]
        with self.assertRaises(self.evaluation.EvaluationManifestError) as caught:
            self._build_manifest(altered)
        self.assertEqual(
            caught.exception.code, "SOURCE_FEATURE_FINGERPRINT_MISMATCH"
        )

    def test_missing_or_duplicate_known_examples_fail_closed(self) -> None:
        missing = copy.deepcopy(self.catalog)
        missing["records"].pop()
        with self.assertRaises(self.evaluation.EvaluationManifestError) as caught_missing:
            self.evaluation.validate_known_examples(missing)
        self.assertEqual(caught_missing.exception.code, "CATALOG_RECORD_COUNT")

        duplicate = copy.deepcopy(self.catalog)
        duplicate["records"][-1] = copy.deepcopy(duplicate["records"][0])
        with self.assertRaises(self.evaluation.EvaluationManifestError) as caught_duplicate:
            self.evaluation.validate_known_examples(duplicate)
        self.assertEqual(caught_duplicate.exception.code, "CATALOG_DUPLICATE_RECORD")

    def test_exact_known_source_identity_is_rejected(self) -> None:
        altered = copy.deepcopy(self.scenes)
        known = self.catalog["records"][0]
        altered[0]["source_identity"] = known["source_identity"]
        manifest = self._build_manifest(altered)
        pair = next(
            check
            for check in manifest["leakage_checks"]
            if check["scene_id"] == altered[0]["scene_id"]
            and check["known_record_id"] == known["record_id"]
        )
        self.assertEqual(pair["verdict"], "REJECT")
        self.assertIn("EXACT_SOURCE_IDENTITY", pair["flags"])
        self.assertEqual(manifest["leakage_status"], "REJECTED")
        with self.assertRaises(self.evaluation.EvaluationManifestError) as caught:
            self.evaluation.freeze_manifest_binding(manifest, self._approval(manifest))
        self.assertEqual(caught.exception.code, "KNOWN_LEAKAGE_REJECTED")

    def test_declared_known_derivative_is_rejected(self) -> None:
        altered = copy.deepcopy(self.scenes)
        known = self.catalog["records"][0]
        altered[0]["lineage_status"] = "derived"
        altered[0]["adaptation_lineage"] = [known["record_id"]]
        manifest = self._build_manifest(altered)
        pair = next(
            check
            for check in manifest["leakage_checks"]
            if check["scene_id"] == altered[0]["scene_id"]
            and check["known_record_id"] == known["record_id"]
        )
        self.assertIn("DECLARED_KNOWN_ANCESTOR", pair["flags"])
        self.assertEqual(pair["verdict"], "REJECT")
        self.assertEqual(manifest["leakage_status"], "REJECTED")

    def test_bounded_text_overlap_requires_review_not_semantic_rejection(self) -> None:
        altered = copy.deepcopy(self.scenes)
        known = self.catalog["records"][0]
        altered[0]["source_text"] = " ".join(
            self.evaluation._known_text_tokens(known)
        )
        fingerprints = self.evaluation.fingerprint_source_text(
            altered[0]["source_text"]
        )
        altered[0]["layout_tokens"] = fingerprints["layout_tokens"]
        altered[0]["feature_tokens"] = fingerprints["feature_tokens"]
        manifest = self._build_manifest(altered)
        pair = next(
            check
            for check in manifest["leakage_checks"]
            if check["scene_id"] == altered[0]["scene_id"]
            and check["known_record_id"] == known["record_id"]
        )
        self.assertEqual(pair["verdict"], "REVIEW_REQUIRED")
        self.assertIn("TEXT_TOKEN_OVERLAP_REVIEW", pair["review_flags"])
        self.assertEqual(manifest["leakage_status"], "REVIEW_REQUIRED")
        with self.assertRaises(self.evaluation.EvaluationManifestError) as caught:
            self.evaluation.freeze_manifest_binding(manifest, self._approval(manifest))
        self.assertEqual(caught.exception.code, "LEAKAGE_REVIEW_REQUIRED")

    def test_tampered_artifact_and_assignment_are_detected(self) -> None:
        artifact_tamper = copy.deepcopy(self.manifest)
        artifact_tamper["scenes"][0]["artifacts"][0]["content"] += " changed"
        with self.assertRaises(self.evaluation.EvaluationManifestError) as caught_artifact:
            self.evaluation.verify_proposed_manifest(artifact_tamper)
        self.assertEqual(caught_artifact.exception.code, "PROJECTION_ARTIFACT_STALE")

        order_tamper = copy.deepcopy(self.manifest)
        order_tamper["assignment"]["episode_order"].reverse()
        with self.assertRaises(self.evaluation.EvaluationManifestError) as caught_order:
            self.evaluation.verify_proposed_manifest(order_tamper)
        self.assertEqual(caught_order.exception.code, "ASSIGNMENT_ORDER_STALE")

    def test_malformed_manifest_source_records_fail_with_stable_errors(self) -> None:
        malformed_identity = copy.deepcopy(self.manifest)
        malformed_identity["scenes"][0]["source"]["identity"] = ["not-hashable"]
        with self.assertRaises(self.evaluation.EvaluationManifestError) as caught_identity:
            self.evaluation.verify_proposed_manifest(malformed_identity)
        self.assertEqual(caught_identity.exception.code, "SOURCE_IDENTITY")

        malformed_lineage = copy.deepcopy(self.manifest)
        malformed_lineage["scenes"][0]["source"]["adaptation_lineage"] = [["bad"]]
        malformed_lineage["scenes"][0]["source"]["lineage_status"] = "derived"
        with self.assertRaises(self.evaluation.EvaluationManifestError) as caught_lineage:
            self.evaluation.verify_proposed_manifest(malformed_lineage)
        self.assertEqual(caught_lineage.exception.code, "LINEAGE_ENTRY")

        malformed_fingerprint = copy.deepcopy(self.manifest)
        malformed_fingerprint["scenes"][0]["source"]["feature_tokens"] = ["unrelated"]
        with self.assertRaises(self.evaluation.EvaluationManifestError) as caught_fingerprint:
            self.evaluation.verify_proposed_manifest(malformed_fingerprint)
        self.assertEqual(
            caught_fingerprint.exception.code, "SOURCE_FINGERPRINT_PARTITION"
        )

    def test_synthetic_binding_is_explicit_and_never_authorizes_scoring(self) -> None:
        binding = self.evaluation.freeze_manifest_binding(
            self.manifest, self._approval()
        )
        self.assertEqual(binding["status"], "TEST_ONLY_BINDING_VERIFIED")
        self.assertEqual(binding["authorization_status"], "NOT_AUTHORIZED")
        self.assertEqual(binding["scoring_status"], "NOT_STARTED")
        self.assertFalse(binding["human_identity_authenticated"])
        self.assertFalse(binding["scoring_authorized"])
        self.assertEqual(
            binding["candidate_sha256"], self.manifest["candidate_sha256"]
        )
        self.assertEqual(
            binding["freeze_hashes"], self.manifest["hashes"]
        )

    def test_unverified_external_reference_does_not_claim_authentication(self) -> None:
        approval = self._approval()
        approval["approval_reference"] = "unverified-record:synthetic-test"
        approval["test_only"] = False
        binding = self.evaluation.freeze_manifest_binding(self.manifest, approval)
        self.assertEqual(
            binding["status"], "BINDING_VERIFIED_NOT_AUTHENTICATED"
        )
        self.assertFalse(binding["human_identity_authenticated"])
        self.assertFalse(binding["scoring_authorized"])

    def test_synthetic_approval_must_be_labeled_test_only(self) -> None:
        approval = self._approval()
        approval["test_only"] = False
        with self.assertRaises(self.evaluation.EvaluationManifestError) as caught:
            self.evaluation.freeze_manifest_binding(self.manifest, approval)
        self.assertEqual(caught.exception.code, "SYNTHETIC_APPROVAL_LABEL")

    def test_changed_assignment_seed_requires_reapproval(self) -> None:
        changed = self._build_manifest(seed="synthetic-seed-task-1.8-revised")
        self.assertNotEqual(
            changed["assignment"]["order_sha256"],
            self.manifest["assignment"]["order_sha256"],
        )
        with self.assertRaises(self.evaluation.EvaluationManifestError) as caught:
            self.evaluation.freeze_manifest_binding(changed, self._approval())
        self.assertEqual(caught.exception.code, "REAPPROVAL_REQUIRED")

    def test_missing_approval_binding_is_rejected(self) -> None:
        with self.assertRaises(self.evaluation.EvaluationManifestError) as caught:
            self.evaluation.freeze_manifest_binding(self.manifest, {})
        self.assertEqual(caught.exception.code, "RECORD_FIELDS")

    def test_network_socket_is_not_used(self) -> None:
        with patch.object(socket, "socket", side_effect=AssertionError("network forbidden")):
            report = self.evaluation.verify_proposed_manifest(self.manifest)
        self.assertTrue(report["is_valid"])

    @staticmethod
    def _score_records(count: int = 6) -> list[dict[str, object]]:
        records: list[dict[str, object]] = []
        owner_scores = (3, 2, 1, 3, 2, 1)
        for index in range(count):
            scene_id = "calibration:scene:item-%d" % index
            digest = ("%x" % (index + 1)) * 64
            for axis in ("legibility", "usefulness"):
                base = {
                    "artifact_sha256": digest,
                    "scene_id": scene_id,
                    "condition": "A",
                    "axis": axis,
                    "phase": "calibration",
                }
                records.append({**base, "role": "owner", "rater": "owner", "score": owner_scores[index]})
                records.append({**base, "role": "independent_advisory", "rater": "advisory", "score": 3})
        return records

    def test_supplied_calibration_pair_arithmetic_and_axis_separation(self) -> None:
        records = self._score_records()
        before = copy.deepcopy(records)
        report = self.calibration.summarize_supplied_scores(records)
        self.assertEqual(records, before)
        self.assertFalse(report["scoring_authorized"])
        for axis in ("legibility", "usefulness"):
            metric = report["paired_metrics"]["calibration"]["A"][axis]
            self.assertEqual(metric["paired_n"], 6)
            self.assertEqual(metric["exact_count"], 2)
            self.assertEqual(metric["within_one_count"], 4)
            self.assertEqual(metric["sum_absolute_error"], 6)
            self.assertEqual(metric["mae"], 1)
            self.assertEqual(metric["status"], "CALIBRATED_SUPPLIED_PAIRS_ONLY")
            self.assertEqual(report["calibration_by_axis"][axis]["paired_n"], 6)
            zero_unpaired = {
                (row["role"], row["axis"]): row["count"]
                for row in report["unpaired_counts"]
            }
            self.assertEqual(zero_unpaired, {
                ("owner", "legibility"): 0,
                ("owner", "usefulness"): 0,
                ("independent_advisory", "legibility"): 0,
                ("independent_advisory", "usefulness"): 0,
            })

    def test_fewer_than_six_pairs_and_empty_input_are_not_estimable(self) -> None:
        five = self.calibration.summarize_supplied_scores(self._score_records(5))
        metric = five["paired_metrics"]["calibration"]["A"]["legibility"]
        self.assertEqual(metric["paired_n"], 5)
        self.assertEqual(metric["exact_count"], 2)
        self.assertIsNone(metric["exact_agreement"])
        self.assertIsNone(metric["mae"])
        self.assertEqual(metric["status"], "UNCALIBRATED_NOT_ESTIMABLE")
        empty = self.calibration.summarize_supplied_scores([])
        self.assertEqual(empty["paired_metrics"]["holdout"]["D"]["usefulness"]["paired_n"], 0)
        self.assertEqual(empty["paired_metrics"]["holdout"]["D"]["usefulness"]["status"], "UNCALIBRATED_NOT_ESTIMABLE")

    def test_pairs_require_exact_artifact_hash_and_separate_self_review(self) -> None:
        records = self._score_records(1)
        records[1]["artifact_sha256"] = "f" * 64
        records.append({**records[0], "role": "author_self_review", "rater": "author", "score": 5})
        report = self.calibration.summarize_supplied_scores(records)
        self.assertEqual(report["paired_metrics"]["calibration"]["A"]["legibility"]["paired_n"], 0)
        self.assertEqual(len(report["author_self_reviews"]), 1)
        remaining = {(row["role"], row["axis"]): row["count"] for row in report["unpaired_counts"]}
        self.assertEqual(remaining[("owner", "legibility")], 1)
        self.assertEqual(remaining[("independent_advisory", "legibility")], 1)
        self.assertEqual(remaining[("owner", "usefulness")], 0)
        self.assertEqual(remaining[("independent_advisory", "usefulness")], 0)
        self.assertEqual(remaining[("author_self_review", "legibility")], 1)
        self.assertEqual(report["unpaired_counts"], sorted(report["unpaired_counts"], key=lambda row: (row["role"], row["phase"], row["axis"])))

    def test_validation_rejects_invalid_score_boolean_duplicates_and_hash_metadata(self) -> None:
        cases = []
        invalid_score = self._score_records(1)
        invalid_score[0]["score"] = True
        cases.append((invalid_score, "SCORE"))
        out_of_range = self._score_records(1)
        out_of_range[0]["score"] = 6
        cases.append((out_of_range, "SCORE"))
        duplicate = self._score_records(1)
        duplicate.append(copy.deepcopy(duplicate[0]))
        cases.append((duplicate, "DUPLICATE_SCORE"))
        conflicting = self._score_records(1)
        conflicting[-1]["scene_id"] = "calibration:scene:wrong"
        cases.append((conflicting, "ARTIFACT_METADATA_CONFLICT"))
        for records, code in cases:
            with self.subTest(code=code):
                with self.assertRaises(self.calibration.CalibrationError) as caught:
                    self.calibration.summarize_supplied_scores(records)
                self.assertEqual(caught.exception.code, code)

    def test_holdout_conditions_are_not_pooled(self) -> None:
        records = self._score_records(6)
        holdout = []
        for item in records:
            changed = dict(item)
            changed["phase"] = "holdout"
            holdout.append(changed)
        report = self.calibration.summarize_supplied_scores(records + holdout)
        self.assertEqual(report["paired_metrics"]["calibration"]["A"]["legibility"]["paired_n"], 6)
        self.assertEqual(report["paired_metrics"]["holdout"]["A"]["legibility"]["paired_n"], 6)
        self.assertEqual(report["paired_metrics"]["holdout"]["B"]["legibility"]["paired_n"], 0)

    def test_calibration_aggregate_can_span_conditions_but_holdout_remains_stratified(self) -> None:
        records = self._score_records(6)
        for item in records:
            index = int(item["scene_id"].rsplit("-", 1)[1])
            item["condition"] = "ABCD"[index % 4]
        report = self.calibration.summarize_supplied_scores(records)
        for axis in ("legibility", "usefulness"):
            self.assertEqual(report["calibration_by_axis"][axis]["paired_n"], 6)
            self.assertEqual(report["calibration_by_axis"][axis]["status"], "CALIBRATED_SUPPLIED_PAIRS_ONLY")
            self.assertEqual(report["paired_metrics"]["calibration"]["A"][axis]["paired_n"], 2)
            self.assertEqual(report["paired_metrics"]["calibration"]["B"][axis]["paired_n"], 2)
        self.assertEqual(report["paired_metrics"]["holdout"]["A"]["legibility"]["paired_n"], 0)


if __name__ == "__main__":
    unittest.main()
