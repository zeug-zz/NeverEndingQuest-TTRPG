# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free tests for immutable mapping-pilot SP4 decision reports."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import shutil
import sys
import unittest
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.mapping_pilot.decision_report import (
    DecisionReportError,
    REPORT_FILENAME,
    create_decision_report,
)
from scripts.mapping_pilot.manifest import DEFAULT_PREREG_ROOT
from scripts.mapping_pilot.review import (
    CONDITION_KEY_FILENAME,
    RATINGS_FILENAME,
    REVIEW_MANIFEST_FILENAME,
    RATING_LOCK_FILENAME,
)
from scripts.mapping_pilot.scoring import REGRESSION_GUARDS


class MappingPilotDecisionReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture_root = Path("tmp/mapping-pilot-decision-report-tests") / uuid.uuid4().hex
        self.fixture_directory = ROOT / self.fixture_root
        self.fixture_directory.mkdir(parents=True)
        self.rollout_snapshot = self._rollout_snapshot()
        self.output_root = self.fixture_root / "reports"

    def tearDown(self) -> None:
        shutil.rmtree(self.fixture_directory, ignore_errors=True)
        try:
            (ROOT / self.fixture_root.parent).rmdir()
        except OSError:
            pass
        self.assertEqual(self._rollout_snapshot(), self.rollout_snapshot)

    def test_absent_inputs_are_explicit_and_all_frozen_slots_are_missing(self) -> None:
        report_directory = create_decision_report(
            "sp4-absent",
            output_root=self.output_root,
        )
        report = self._read_report(report_directory)

        self.assertEqual(report["stage_1"], {"status": "waived", "ratings": "not scored"})
        self.assertEqual([item["id"] for item in report["questions"]], ["Q1", "Q2", "Q3", "Q4", "Q5", "Q6"])
        self.assertEqual(len(report["recommendations"]), 5)
        self.assertTrue(
            all(
                item["recommendation"] == "inconclusive"
                for item in report["recommendations"]
            )
        )
        self.assertEqual(len(report["sp3_slots"]["slots"]), 30)
        self.assertEqual(
            report["sp3_slots"]["status_counts"],
            {"PASS": 0, "FAIL": 0, "BLOCKED": 0, "missing": 30},
        )
        self.assertTrue(all(slot["status"] == "missing" for slot in report["sp3_slots"]["slots"]))
        self.assertEqual(report["input_status"]["live_transcript_ratings"], "pending/not provided")
        self.assertEqual(report["input_status"]["m1"], "pending/not provided")
        self.assertEqual(report["input_status"]["m1_owner_ratings"], "pending/not provided")
        self.assertEqual(report["input_status"]["d1_owner_audit"], "pending/not provided")
        self.assertEqual(report["d1"]["owner_precision"]["status"], "pending/not provided")
        self.assertEqual(report["d1"]["automated_validator_invented_exit_count"], None)
        self.assertIn("not owner-audited", report["d1"]["automated_validator_count_label"])
        self.assertEqual(report["owner_gate"]["format_choice"], "pending/not provided")
        self.assertIn("authored_presence_missing_and_ambiguous_counts_with_denominators", report["module_builder_handoff"]["columns"])
        self.assertTrue(report["module_builder_handoff"]["rows"])

        manifest = json.loads(
            (ROOT / report_directory / "manifest.json").read_text(encoding="ascii")
        )
        self.assertEqual(manifest["report_sha256"], self._sha256(ROOT / report_directory / REPORT_FILENAME))
        self.assertEqual(manifest["input_hashes"], report["input_hashes"])
        for record in report["input_hashes"]:
            self.assertRegex(record["sha256"], r"^[0-9a-f]{64}$")
            self.assertEqual(record["sha256"], self._sha256(ROOT / record["path"]))
            self.assertFalse(record["path"].startswith("tmp/router-rollout/"))

        with self.assertRaises(FileExistsError):
            create_decision_report("sp4-absent", output_root=self.output_root)

    def test_populated_inputs_are_hashed_linked_and_scored_with_frozen_rules(self) -> None:
        score_rows_path = self._create_score_rows()
        sp3_run_id = "sp3-fixture"
        self._create_sp3_ledger(sp3_run_id)
        d1_run_id = "d1-fixture"
        self._create_d1_fixture(d1_run_id, owner_rated=True, precision=100, automated_count=1)
        m1_run_id = "m1-fixture"
        self._create_m1_fixture(m1_run_id)
        review_run_id = "review-fixture"
        self._create_locked_review(review_run_id)

        report_directory = create_decision_report(
            "sp4-populated",
            score_rows_path=score_rows_path,
            sp3_run_id=sp3_run_id,
            d1_run_id=d1_run_id,
            m1_run_id=m1_run_id,
            review_run_id=review_run_id,
            execution_root=self.fixture_root / "sp3",
            d1_root=self.fixture_root / "d1",
            m1_root=self.fixture_root / "m1",
            review_root=self.fixture_root / "review",
            review_key_root=self.fixture_root / "review-key",
            output_root=self.output_root,
        )
        report = self._read_report(report_directory)

        self.assertEqual(report["sp3_slots"]["status_counts"]["PASS"], 5)
        self.assertEqual(report["sp3_slots"]["status_counts"]["missing"], 25)
        self.assertEqual(report["input_status"]["live_transcript_ratings"], "complete")
        self.assertEqual(report["input_status"]["d1_owner_audit"], "complete")
        self.assertEqual(report["input_status"]["m1_owner_ratings"], "complete")
        self.assertEqual(report["human_ratings"]["live_transcripts"]["reviewer_label"], "fixture-owner")
        self.assertEqual(
            report["scoring"]["decision_rules_with_locked_live_ratings"]["s2_spatial_packet"]["outcome"],
            "adopt",
        )
        self.assertEqual(report["recommendations"][0]["recommendation"], "retain")
        self.assertEqual(report["recommendations"][1]["choice"], "D")
        self.assertEqual(report["recommendations"][2]["rule_outcome"], "pass")
        self.assertEqual(report["recommendations"][2]["recommendation"], "retain")
        self.assertEqual(report["recommendations"][3]["recommendation"], "retain")
        self.assertEqual(report["recommendations"][3]["automated_validator_count"]["value"], 1)
        self.assertIn("not owner-audited", report["recommendations"][3]["automated_validator_count"]["label"])
        self.assertEqual(report["recommendations"][4]["recommendation"], "retain")
        self.assertEqual(report["human_ratings"]["m1_sketches"]["legibility_mean"], 4.0)
        self.assertEqual(report["d1"]["owner_precision"]["percent"], 100)
        self.assertEqual(report["d1"]["owner_invented_exit_count"], 0)

        q1 = report["questions"][0]
        self.assertEqual(q1["human_evidence"]["D"]["mean"], 4.0)
        q6 = report["questions"][5]["result"]
        self.assertIn("route_confounds", q6)
        self.assertEqual(len(q6["rows"]), 5)

        handoff = report["module_builder_handoff"]
        self.assertEqual(handoff["status"], "provided")
        orientation = next(
            row for row in handoff["rows"] if row["spatial_fact_or_field"] == "location.orientation"
        )
        self.assertEqual(
            orientation["authored_presence_missing_and_ambiguous_counts_with_denominators"]["sample_location_denominator"],
            3,
        )
        self.assertEqual(orientation["authored_presence_missing_and_ambiguous_counts_with_denominators"]["authored_presence_count"], "not assessed")
        self.assertFalse(orientation["d1_source_proposal_validation_evidence"]["claims"][0]["proposal_is_authored_fact"])
        self.assertEqual(orientation["d1_source_proposal_validation_evidence"]["claims"][0]["proposal_value"], "north")
        self.assertEqual(orientation["d1_source_proposal_validation_evidence"]["claims"][0]["owner_judgment"]["status"], "provided")
        self.assertTrue(orientation["d1_source_proposal_validation_evidence"]["claims"][0]["source_sha256"])
        sample_version = handoff["sample_scope"]["sampled_module_location_versions"][0]
        self.assertEqual(
            sample_version["d1_source_references"],
            ["Module_One/areas/area1_BU.json", "Module_One/module_context.json"],
        )
        self.assertIn("Module_One/module_context.json", sample_version["d1_source_sha256"])
        self.assertEqual(report["owner_gate"]["data_pipeline_choice"], "pending/not provided")

        input_paths = {item["path"] for item in report["input_hashes"]}
        self.assertIn((self.fixture_root / "sp3" / sp3_run_id / "matrix_ledger.json").as_posix(), input_paths)
        self.assertIn((self.fixture_root / "d1" / d1_run_id / "d1_owner_audit.csv").as_posix(), input_paths)
        self.assertIn((self.fixture_root / "m1" / m1_run_id / "ratings.csv").as_posix(), input_paths)
        self.assertIn((self.fixture_root / "review" / review_run_id / "rating_lock.json").as_posix(), input_paths)
        for record in report["input_hashes"]:
            self.assertEqual(record["sha256"], self._sha256(ROOT / record["path"]))

    def test_automated_d1_validator_count_does_not_fill_owner_audit(self) -> None:
        d1_run_id = "d1-pending-owner"
        self._create_d1_fixture(d1_run_id, owner_rated=False, precision=None, automated_count=7)
        report_directory = create_decision_report(
            "sp4-d1-pending",
            d1_run_id=d1_run_id,
            d1_root=self.fixture_root / "d1",
            output_root=self.output_root,
        )
        report = self._read_report(report_directory)
        d1 = report["d1"]
        self.assertEqual(d1["automated_validator_invented_exit_count"], 7)
        self.assertEqual(d1["automated_validator_count_label"], "automated graph-validator count; not owner-audited")
        self.assertEqual(d1["owner_precision"]["status"], "pending/not provided")
        self.assertEqual(d1["owner_invented_exit_count"], None)
        self.assertEqual(report["recommendations"][3]["recommendation"], "inconclusive")

    def test_score_rows_without_a_provided_sp3_ledger_are_rejected(self) -> None:
        score_rows_path = self._create_score_rows()
        with self.assertRaisesRegex(DecisionReportError, "without an SP3 ledger"):
            create_decision_report(
                "sp4-score-without-ledger",
                score_rows_path=score_rows_path,
                output_root=self.output_root,
            )
        self.assertFalse((ROOT / self.output_root / "sp4-score-without-ledger").exists())

    def test_d1_selection_must_bind_to_compact_ledger_source_hashes(self) -> None:
        d1_run_id = "d1-selection-mismatch"
        self._create_d1_fixture(d1_run_id, owner_rated=False, precision=None, automated_count=0)
        selection_path = ROOT / self.fixture_root / "d1" / d1_run_id / "selection.json"
        selection = json.loads(selection_path.read_text(encoding="ascii"))
        source_path = selection["locations"][0]["source_paths"][0]
        selection["locations"][0]["source_sha256"][source_path] = "0" * 64
        selection_path.write_text(
            json.dumps(selection, ensure_ascii=True, sort_keys=True, indent=2) + "\n",
            encoding="ascii",
        )

        with self.assertRaisesRegex(DecisionReportError, "selected area hash differs"):
            create_decision_report(
                "sp4-d1-selection-mismatch",
                d1_run_id=d1_run_id,
                d1_root=self.fixture_root / "d1",
                output_root=self.output_root,
            )
        self.assertFalse(
            (ROOT / self.output_root / "sp4-d1-selection-mismatch").exists()
        )

    def _create_sp3_ledger(self, run_id: str) -> None:
        rows = json.loads(
            (DEFAULT_PREREG_ROOT / "counterbalance.json").read_text(encoding="utf-8")
        )["rows"]
        attempted = {"E01", "E02", "E03", "C01", "C02"}
        slots = []
        for row in rows:
            slot = {
                **row,
                "status": "PASS" if row["row_id"] in attempted else "missing",
                "reason": "provider-free fixture" if row["row_id"] in attempted else "not_started",
                "evidence_path": None,
                "replacement": None,
            }
            slots.append(slot)
        ledger = {"schema_version": 1, "run_id": run_id, "slots": slots}
        self._write_json(self.fixture_root / "sp3" / run_id / "matrix_ledger.json", ledger)

    def _create_score_rows(self) -> Path:
        rows = []
        for row_id, arm, contradictions, rubric, input_tokens, latency in (
            ("E01", "A", 4, 3, 100, 10),
            ("E02", "B", 3, 3, 105, 10),
            ("E03", "D", 1, 4, 110, 11),
        ):
            rows.append(
                self._score_row(
                    row_id,
                    arm,
                    "exploration",
                    contradictions=contradictions,
                    model_tokens=input_tokens,
                    latency=latency,
                    rubric_seed=rubric,
                )
            )
        for row_id, arm in (("C01", "A"), ("C02", "D")):
            rows.append(
                self._score_row(
                    row_id,
                    arm,
                    "combat",
                    contradictions=0,
                    model_tokens=100,
                    latency=10,
                    rubric_seed=4,
                )
            )
        path = self.fixture_root / "score_rows.json"
        self._write_json(path, {"rows": rows})
        return path

    def _score_row(
        self,
        row_id: str,
        arm: str,
        block: str,
        *,
        contradictions: int,
        model_tokens: int,
        latency: float,
        rubric_seed: int,
    ) -> dict[str, Any]:
        observations = [
            {
                "kind": "contradiction_claim",
                "category": "false_elevation_cover_or_engagement_relation",
                "contradiction": False,
            },
            *[
                {"kind": "movement_parse_outcome", "classification": "exact"}
                for _ in range(4)
            ],
        ]
        return {
            "row_id": row_id,
            "arm": arm,
            "block": block,
            "party": "P1",
            "script": "interior",
            "repeat": 1,
            "completed": True,
            "attempt_count": 1,
            "elapsed_seconds": 10,
            "spatial_references": 10,
            "spatial_contradictions": contradictions,
            "knowledge_leakage_count": 0,
            "assistant_turns": 4,
            "continuity_assertions": {
                "return_journey": [True],
                "changed_back_door": [True],
                "viewpoint_switch": [True],
            },
            "observed_combat_rounds": 10 if block == "combat" else None,
            "zone_ledger_observations": json.dumps(observations),
            "regression_guards": {name: 0 for name in REGRESSION_GUARDS},
            "model_turns": [
                {
                    "input_tokens": model_tokens,
                    "output_tokens": 50,
                    "latency_seconds": latency,
                    "cost_usd": 0.01,
                    "classifier_calls": [],
                }
            ],
            "provider_calls": [],
            "test_only_rubric_seed": rubric_seed,
        }

    def _create_d1_fixture(
        self,
        run_id: str,
        *,
        owner_rated: bool,
        precision: int | None,
        automated_count: int,
    ) -> None:
        selected = []
        descriptors = []
        attempts = []
        audit_rows = []
        for index, (slug, location_id) in enumerate(
            (("Module_One", "L01"), ("Module_Two", "L02"), ("Module_Three", "L03")),
            start=1,
        ):
            area_path = "modules/%s/areas/area%d_BU.json" % (slug, index)
            area_reference = "%s/areas/area%d_BU.json" % (slug, index)
            context_reference = "%s/module_context.json" % slug
            area_hash = (str(index) * 64)[:64]
            hashes = {
                area_reference: area_hash,
                context_reference: (str(index + 3) * 64)[:64],
            }
            references = [area_reference, context_reference]
            selected.append(
                {
                    "module_slug": slug,
                    "location_id": location_id,
                    "area_type": "fixture",
                    "source_paths": [area_path],
                    "source_sha256": {area_path: area_hash},
                }
            )
            descriptors.append(
                {
                    "location_key": slug + ":" + location_id,
                    "source_references": references,
                    "source_sha256": hashes,
                }
            )
            attempt = {
                "attempt_number": index,
                "location_key": slug + ":" + location_id,
                "module_slug": slug,
                "location_id": location_id,
                "source_references": references,
                "source_sha256": hashes,
                "status": "validated",
                "validation_issues": [],
                "graph_check": {"evaluable": True, "invented_exit_count": 0, "issues": []},
                "proposal": {"locations": []},
            }
            attempts.append(attempt)
            audit_rows.append(
                {
                    "attempt_number": index,
                    "location_key": slug + ":" + location_id,
                    "module_slug": slug,
                    "location_id": location_id,
                    "source_evidence": {"source_references": references, "source_sha256": hashes},
                    "status": "validated",
                    "validation_issues": [],
                    "graph_check": {"evaluable": True, "invented_exit_count": 0, "issues": []},
                    "proposal": {"locations": []},
                    "propositions": [],
                }
            )
        descriptors.sort(key=lambda row: row["location_key"])
        descriptors_by_key = {row["location_key"]: row for row in descriptors}
        selection = {
            "schema_version": 1,
            "run_id": run_id,
            "commit": "f" * 40,
            "module_quotas": {"Module_One": 1, "Module_Two": 1, "Module_Three": 1},
            "selected_counts_by_area_type": {},
            "locations": selected,
        }
        owner_claims = [
            (1, "location", "L01", "/locations/0/name", "L01"),
            (1, "orientation", "L01", "/locations/0/orientation/facing", '"north"'),
            (1, "exit", "L01_exit_01", "/locations/0/exits/0/exists", "true"),
            (2, "exit_side", "L02_exit_01", "/locations/0/exits/0/side", '"north"'),
            (3, "feature", "L03_feature_01", "/locations/0/features/0/position", '"center"'),
        ]
        owner_rows = []
        for number, category, entity_id, field, proposed in owner_claims:
            source = selected[number - 1]
            descriptor = descriptors_by_key[
                source["module_slug"] + ":" + source["location_id"]
            ]
            claim = {
                "claim_id": "claim-%02d" % len(owner_rows),
                "attempt_number": str(number),
                "location_key": source["module_slug"] + ":" + source["location_id"],
                "module_slug": source["module_slug"],
                "location_id": source["location_id"],
                "claim_category": category,
                "entity_id": entity_id,
                "claim_field": field,
                "proposed_claim": proposed,
                "authored_source_reference": json.dumps(descriptor["source_references"]),
                "authored_source_sha256": json.dumps(descriptor["source_sha256"], sort_keys=True),
                "owner_correct": "correct" if owner_rated else "",
                "owner_incorrect": "",
                "owner_invented": "",
                "owner_notes": "",
            }
            owner_rows.append(claim)
        audit = {
            "schema_version": 1,
            "audit_type": "D1 cartographer owner review",
            "attempt_count": len(attempts),
            "call_cap": 60,
            "call_cap_reached": False,
            "selection_fingerprint": "a" * 64,
            "selection": descriptors,
            "decision_threshold": {
                "precision_minimum_percent": 85,
                "invented_exits_maximum": 0,
                "precision_is_owner_rated": True,
            },
            "owner_precision": {
                "numerator": precision,
                "denominator": precision if precision is not None else None,
                "percent": precision,
                "notes": "fixture owner input" if precision is not None else "",
            },
            "invented_exit_count": automated_count,
            "invented_exit_count_evaluable": True,
            "invented_exit_count_known_lower_bound": automated_count,
            "unresolved_graph_checks": 0,
            "proposals": audit_rows,
        }
        ledger = {
            "schema_version": 1,
            "selection_fingerprint": "a" * 64,
            "selection": descriptors,
            "owner_precision": audit["owner_precision"],
            "attempts": attempts,
        }
        directory = self.fixture_root / "d1" / run_id
        self._write_json(directory / "selection.json", selection)
        self._write_json(directory / "d1_attempt_ledger.json", ledger)
        self._write_json(directory / "d1_audit_sheet.json", audit)
        output = io.StringIO(newline="")
        output.write("# Threshold: precision >= 85% with zero invented exits\n")
        fields = list(owner_rows[0])
        writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(owner_rows)
        path = ROOT / self.fixture_root / "d1" / run_id / "d1_owner_audit.csv"
        path.write_text(output.getvalue(), encoding="ascii")

    def _create_m1_fixture(self, run_id: str) -> None:
        directory = self.fixture_root / "m1" / run_id
        directory_absolute = ROOT / directory
        directory_absolute.mkdir(parents=True)
        sketches = []
        artifact_hashes = {}
        rating_rows = []
        for index in range(2):
            sketch_id = "fixture-sketch-%d" % (index + 1)
            filename = sketch_id + ".txt"
            payload = ("Schematic fixture sketch %d\n" % index).encode("ascii")
            (directory_absolute / filename).write_bytes(payload)
            digest = hashlib.sha256(payload).hexdigest()
            artifact_hashes[filename] = digest
            sketches.append({"sketch_id": sketch_id, "file": filename, "sha256": digest})
            rating_rows.append(
                {
                    "sketch_id": sketch_id,
                    "sketch_file": filename,
                    "legibility_1_5": "4",
                    "usefulness_1_5": "4",
                }
            )
        sheet = io.StringIO(newline="")
        sheet.write("# Threshold: mean >= 3.5 for legibility and usefulness\n")
        writer = csv.DictWriter(
            sheet,
            fieldnames=("sketch_id", "sketch_file", "legibility_1_5", "usefulness_1_5"),
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rating_rows)
        ratings_payload = sheet.getvalue().encode("ascii")
        (directory_absolute / "ratings.csv").write_bytes(ratings_payload)
        artifact_hashes["ratings.csv"] = hashlib.sha256(ratings_payload).hexdigest()
        self._write_json(
            directory / "manifest.json",
            {
                "schema_version": 1,
                "run_id": run_id,
                "completion": "complete",
                "d1_run_id": None,
                "sketches": sketches,
                "artifact_sha256": artifact_hashes,
            },
        )

    def _create_locked_review(self, review_run_id: str) -> None:
        review_dir = self.fixture_root / "review" / review_run_id
        key_dir = self.fixture_root / "review-key" / review_run_id
        review_absolute = ROOT / review_dir
        key_absolute = ROOT / key_dir
        review_absolute.mkdir(parents=True)
        key_absolute.mkdir(parents=True)
        ids_by_row = {
            row_id: ("%032x" % index)
            for index, row_id in enumerate(("E01", "E02", "E03", "C01", "C02"), start=1)
        }
        headers = ["response_id"]
        for name in (
            "sense_of_place",
            "imaginability",
            "natural_use",
            "actionability",
            "continuity",
            "combat_clarity_and_flow",
        ):
            headers.extend((name + "_1_5", name + "_evidence"))
        headers.extend(("not_rateable", "not_rateable_reason"))
        ratings = io.StringIO(newline="")
        writer = csv.DictWriter(ratings, fieldnames=headers, lineterminator="\n")
        writer.writeheader()
        values_by_row = {"E01": 3, "E02": 3, "E03": 4, "C01": 4, "C02": 4}
        for row_id, response_id in ids_by_row.items():
            value = values_by_row[row_id]
            item = {"response_id": response_id, "not_rateable": "", "not_rateable_reason": ""}
            for _index, name in enumerate(
                (
                    "sense_of_place",
                    "imaginability",
                    "natural_use",
                    "actionability",
                    "continuity",
                    "combat_clarity_and_flow",
                ),
                start=1,
            ):
                item[name + "_1_5"] = "" if row_id.startswith("E") and name == "combat_clarity_and_flow" else str(value)
                item[name + "_evidence"] = "fixture rating evidence"
            writer.writerow(item)
        ratings_payload = ratings.getvalue().encode("ascii")
        packet_files = {
            response_id + ".txt": ("Response ID: %s\n\nFixture transcript.\n" % response_id).encode("ascii")
            for response_id in ids_by_row.values()
        }
        packet_files["disclosure.txt"] = b"Blinding is partial.\n"
        packet_files[RATINGS_FILENAME] = ratings_payload
        for filename, payload in packet_files.items():
            (review_absolute / filename).write_bytes(payload)
        packet_manifest = {
            "schema_version": 1,
            "complete": True,
            "review_run_id": review_run_id,
            "response_count": len(ids_by_row),
            "packet_order": list(ids_by_row.values()),
            "files": {
                name: hashlib.sha256(payload).hexdigest()
                for name, payload in sorted(packet_files.items())
            },
        }
        self._write_json(review_dir / REVIEW_MANIFEST_FILENAME, packet_manifest)
        self._write_json(
            review_dir / RATING_LOCK_FILENAME,
            {
                "schema_version": 1,
                "review_run_id": review_run_id,
                "reviewer_label": "fixture-owner",
                "locked_at": "2026-11-06T12:00:00Z",
                "ratings_sha256": hashlib.sha256(ratings_payload).hexdigest(),
            },
        )
        frozen_rows = json.loads(
            (DEFAULT_PREREG_ROOT / "counterbalance.json").read_text(encoding="utf-8")
        )["rows"]
        frozen_by_id = {row["row_id"]: row for row in frozen_rows}
        condition_units = []
        for row_id, response_id in ids_by_row.items():
            row = frozen_by_id[row_id]
            condition_units.append(
                {
                    "response_id": response_id,
                    "row": row_id,
                    "arm": row["arm"],
                    "party": row["party"],
                    "seed": row["fixed_seed"],
                    "row_order": row["run_order"],
                    "evidence_run_id": "evidence-" + row_id,
                    "turn": {"expected_ordinals": [1], "observed_ordinals": [1]},
                }
            )
        key_payload = {
            "schema_version": 1,
            "review_run_id": review_run_id,
            "response_units": condition_units,
        }
        key_bytes = json.dumps(key_payload, ensure_ascii=True, sort_keys=True, indent=2).encode("ascii") + b"\n"
        (key_absolute / CONDITION_KEY_FILENAME).write_bytes(key_bytes)
        self._write_json(
            key_dir / REVIEW_MANIFEST_FILENAME,
            {
                "schema_version": 1,
                "complete": True,
                "review_run_id": review_run_id,
                "files": {CONDITION_KEY_FILENAME: hashlib.sha256(key_bytes).hexdigest()},
            },
        )

    def _read_report(self, relative_directory: Path) -> dict[str, Any]:
        return json.loads(
            (ROOT / relative_directory / REPORT_FILENAME).read_text(encoding="ascii")
        )

    def _write_json(self, relative_path: Path, payload: Any) -> None:
        path = ROOT / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=True, sort_keys=True, indent=2) + "\n",
            encoding="ascii",
        )

    def _sha256(self, path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _rollout_snapshot(self) -> dict[str, str]:
        root = ROOT / "tmp/router-rollout/mapping-pilot"
        if not root.exists():
            return {}
        snapshot = {}
        for path in sorted(root.rglob("*")):
            relative = path.relative_to(root).as_posix()
            if path.is_file():
                snapshot[relative] = self._sha256(path)
            elif path.is_dir():
                snapshot[relative + "/"] = "directory"
        return snapshot


if __name__ == "__main__":
    unittest.main()
