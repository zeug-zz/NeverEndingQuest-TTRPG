# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.

"""Provider-free exact Amphail regression coverage for adaptation finalization."""

from __future__ import annotations

import json
import copy
import hashlib
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils.toolkit_adaptation_failure_classifier import classify_adaptation_failure
from utils.toolkit_adaptation_failure_packet import (
    build_adaptation_monster_failure_packet,
    validate_adaptation_monster_failure_packet,
)
from utils.toolkit_adaptation_monster_guardrail import (
    build_adaptation_canonical_monster_registry,
    materialize_adaptation_monsters,
    normalize_adaptation_location_monsters,
)
from utils.toolkit_adaptation_publication_convergence import (
    FINALIZATION_CONTRACT_VERSION,
    FINALIZATION_OPERATION_DESTINATION_ALIAS,
    FINALIZATION_OPERATION_MONSTER_REFERENCE,
    run_adaptation_publication_convergence,
    validate_adaptation_publication_continuation,
)
from utils.toolkit_adaptation_staging import create_adaptation_staging_target
from utils.toolkit_homebrew_upload_contract import (
    build_review_snapshot,
    ensure_workspace_placeholders,
    get_workspace_files,
)
import utils.toolkit_adaptation_gate_composer as adaptation_gate_composer
import web.extensions.toolkit_homebrew_packet_builder as packet_builder
import web.extensions.toolkit_module_finisher as module_finisher
from utils.toolkit_adaptation_dossier import ADAPTATION_MODE_LLM
from web.extensions.toolkit_homebrew_packet_builder import (
    _finalize_adaptation_continuity,
    _route_adaptation_monster_revision,
)
from web.extensions.toolkit_homebrew_readiness_gate import (
    _build_validation_signature,
    _extract_failure_categories,
    _extract_module_validation_report,
    _resolve_adaptation_module_path,
    _run_validator,
)


ROOT = Path("tmp") / "toolkit_adaptation_amphail_finalization"


def _artifact(root: Path) -> None:
    path = root / "monsters" / "cave_guardian.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "name": "Cave Guardian",
                "size": "Medium",
                "alignment": "unaligned",
                "armorClass": 14,
            }
        ),
        encoding="utf-8",
    )


def _fixture() -> tuple[dict, list[dict]]:
    dossier = {
        "adaptation_mode": "llm_adaptation",
        "encounter_seeds": [
            {"id": "K06", "adversaries": ["Cave guardians"]},
            {"id": "K08", "adversaries": ["Cave Guardian"]},
            {"id": "K10", "adversaries": ["2 Cave guardians"]},
        ],
    }
    areas = [
        {
            "areaId": "K",
            "locations": [
                {
                    "locationId": "K06",
                    "monsters": [{"name": "Cave guardians", "quantity": {"min": 1, "max": 1}}],
                },
                {
                    "locationId": "K08",
                    "monsters": [{
                        "name": "Cave Guardian",
                        "quantity": {"min": 1, "max": 1},
                        "description": "Two slime-coated guardians crowd the chamber.",
                    }],
                },
                {
                    "locationId": "RTR001",
                    "monsters": [{"name": "2 Cave guardians", "quantity": {"min": 2, "max": 2}}],
                },
            ],
        }
    ]
    return dossier, areas


class AmphailCanonicalContentTest(unittest.TestCase):
    def setUp(self) -> None:
        shutil.rmtree(ROOT, ignore_errors=True)
        ROOT.mkdir(parents=True)
        _artifact(ROOT)
        self.dossier, self.areas = _fixture()
        self.registry = build_adaptation_canonical_monster_registry(
            self.dossier,
            areas=self.areas,
            staging_root=ROOT,
            approved_canonical_identities=["Cave Guardian"],
        )

    def tearDown(self) -> None:
        shutil.rmtree(ROOT, ignore_errors=True)

    def test_cave_guardians_reuses_one_canonical_artifact_and_preserves_quantities(self) -> None:
        quantities = {}
        contradiction = None
        for area in self.areas:
            for location in area["locations"]:
                result = normalize_adaptation_location_monsters(
                    location["monsters"],
                    [],
                    canonical_registry=self.registry,
                    source_location=location["locationId"],
                )
                quantities[location["locationId"]] = result["normalized_monsters"][0]["quantity"]
                if location["locationId"] == "K08":
                    contradiction = result["contradiction_diagnostics"]

        self.assertEqual(quantities, {
            "K06": {"min": 1, "max": 1},
            "K08": {"min": 1, "max": 1},
            "RTR001": {"min": 2, "max": 2},
        })
        self.assertEqual(contradiction[0]["code"], "quantity_prose_contradiction")
        self.assertIn("multiple manifestations", contradiction[0]["message"])

        result = materialize_adaptation_monsters(
            ROOT,
            ["Cave guardians", "Cave Guardian", "2 Cave guardians"],
            self.dossier["encounter_seeds"],
            canonical_registry=self.registry,
            reusable_module_dirs=[ROOT],
        )
        self.assertEqual(result["monsters_reused"], 1)
        self.assertEqual(result["monsters_generated"], 0)
        self.assertTrue((ROOT / "monsters" / "cave_guardian.json").is_file())
        self.assertFalse((ROOT / "monsters" / "cave_guardians.json").exists())
        self.assertEqual(sorted(path.name for path in (ROOT / "monsters").glob("*.json")), ["cave_guardian.json"])

    def test_failure_packet_and_revision_zero_are_content_eligible_with_bounded_k08_evidence(self) -> None:
        classification = classify_adaptation_failure(
            {"failure_class": "semantic", "code": "monster_closure_unresolved"},
            attempt_metadata={"attempt_id": "adapt-amphail", "revision_number": 0, "stage": "monster_closure"},
            revision_eligible=True,
            max_revisions=1,
        )
        self.assertTrue(classification["revision_eligible"])
        self.assertTrue(classification["next_revision_eligible"])
        self.assertFalse(classification["terminal"])

        packet = build_adaptation_monster_failure_packet(
            attempt_metadata={"attempt_id": "adapt-amphail", "revision_number": 0},
            revision_budget={"current_revision": 0, "max_revisions": 1, "remaining_before_failure": 1},
            canonical_registry=self.registry,
            normalized_reference="cave_guardians",
            raw_reference="Cave guardians",
            guardrail_report={"contradiction_diagnostics": [{
                "source_location": "K08",
                "code": "quantity_prose_contradiction",
                "message": "Two slime-coated guardians crowd the chamber.",
            }]},
            failure_code="monster_closure_unresolved",
        )
        self.assertEqual(packet["canonical_identities"]["approved"], ["Cave Guardian"])
        self.assertEqual({item["location_id"] for item in packet["quantity_records"]}, {"K06", "K08", "RTR001"})
        self.assertEqual(packet["revision_budget"]["current_revision"], 0)
        self.assertEqual(packet["scene_evidence"][0]["location_id"], "K08")
        self.assertTrue(validate_adaptation_monster_failure_packet(packet, expected_attempt_id="adapt-amphail", expected_revision_number=0)["valid"])

    def test_accepted_resolution_is_candidate_only_until_hard_gates_pass(self) -> None:
        source_hash = "a" * 64
        target = create_adaptation_staging_target(
            source_hash,
            attempt_id="adapt-amphail",
            attempt_number=1,
            revision_number=1,
            module_slug="Amphail",
            repo_root=ROOT,
            staging_root="staging",
        )
        stage = ROOT / target["path"]
        identity = {"attempt_id": "adapt-amphail", "attempt_number": 1, "revision_number": 1, "source_hash": source_hash}
        proposal = {
            "contract_version": FINALIZATION_CONTRACT_VERSION,
            "operation": FINALIZATION_OPERATION_MONSTER_REFERENCE,
            "identity": identity,
            "target": {"reference_key": "cave_guardians", "canonical_identity": "Cave Guardian"},
            "source_references": ["K08"],
            "confidence": 0.95,
            "resolution_code": "plural_group_label",
        }
        result = run_adaptation_publication_convergence(
            staged_module_path=str(stage),
            mode="llm_adaptation",
            attempt_id="adapt-amphail",
            attempt_number=1,
            revision_number=1,
            source_hash=source_hash,
            repo_root=ROOT,
            provider_callback=lambda context: {
                "status": "success",
                "proposal": proposal,
                "attempt_id": context["attempt_id"],
                "attempt_number": context["attempt_number"],
                "revision_number": context["revision_number"],
                "source_hash": context["source_hash"],
                "staging_identity": context["staging_identity"],
            },
            validation_context={
                "approved_monster_identities": ["Cave Guardian"],
                "source_reference_ids": ["K08"],
                "approved_monster_ids": ["Cave Guardian"],
                "monster_reference_keys": ["cave_guardians"],
                "source_reference_ids": ["K08"],
                "quantity_bounds": {},
                "canonical_location_ids": ["K06", "K08", "RTR001"],
                "topology": {"location_ids": ["K06", "K08", "RTR001"], "edges": []},
            },
        )
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["accepted_operation"]["target"]["canonical_identity"], "Cave Guardian")
        self.assertFalse(result.get("publication_attempted", False))


class AmphailFreshRevisionTest(unittest.TestCase):
    def setUp(self) -> None:
        shutil.rmtree(ROOT, ignore_errors=True)
        ROOT.mkdir(parents=True)

    def tearDown(self) -> None:
        shutil.rmtree(ROOT, ignore_errors=True)

    def test_revision_zero_reaches_llm_context_and_uses_fresh_staging(self) -> None:
        source_hash = "b" * 64
        old_target = {"path": "tmp/old/revision_000", "attempt_id": "adapt-amphail", "attempt_number": 1, "revision_number": 0, "source_hash": source_hash}
        calls = []

        def revision_callback(context):
            calls.append(context)
            self.assertEqual(context["failure_packet"]["monster_content_failure"]["unresolved_reference"]["normalized"], "cave_guardians")
            self.assertEqual(context["failure_packet"]["monster_content_failure"]["scene_evidence"][0]["location_id"], "K08")
            proposal = {
                "contract_version": FINALIZATION_CONTRACT_VERSION,
                "operation": FINALIZATION_OPERATION_MONSTER_REFERENCE,
                "identity": {key: context["convergence_context"][key] for key in ("attempt_id", "attempt_number", "revision_number", "source_hash")},
                "target": {"reference_key": "cave_guardians", "canonical_identity": "Cave Guardian"},
                "source_references": ["K08"],
                "confidence": 0.95,
                "resolution_code": "plural_group_label",
            }
            return {
                "status": "success",
                "proposal": proposal,
                "attempt_id": context["convergence_context"]["attempt_id"],
                "attempt_number": context["convergence_context"]["attempt_number"],
                "revision_number": context["convergence_context"]["revision_number"],
                "source_hash": context["convergence_context"]["source_hash"],
                "staging_identity": context["convergence_context"].get("staging_identity"),
            }

        def rerun(target, operation):
            self.assertEqual(target["revision_number"], 1)
            self.assertNotEqual(target["path"], old_target["path"])
            self.assertEqual(operation["target"]["canonical_identity"], "Cave Guardian")
            return {"status": "success", "publication_attempted": False, "hard_gates_passed": False}

        result = _route_adaptation_monster_revision(
            build_result={"status": "blocked"},
            guardrail_report={
                "unresolved_refs": ["cave_guardians"],
                "approved_monster_identities": ["Cave Guardian"],
                "quantity_evidence": [
                    {"location_id": "K06", "encounter_reference": "K06", "quantity": {"min": 1, "max": 1}},
                    {"location_id": "K08", "encounter_reference": "K08", "quantity": {"min": 1, "max": 1}},
                    {"location_id": "RTR001", "encounter_reference": "K10", "quantity": {"min": 2, "max": 2}},
                ],
                "contradiction_diagnostics": [{"source_location": "K08", "code": "quantity_prose_contradiction", "message": "Two guardians crowd the chamber."}],
            },
            classification={
                "failure_class": "semantic", "code": "monster_closure_unresolved", "revision_eligible": True,
                "semantic_revision_eligible": True,
                "revision_budget": {"current_revision": 0, "max_revisions": 1, "remaining_before_failure": 1},
            },
            adaptation_handoff={"provenance": {"attempt_id": "adapt-amphail", "attempt_number": 1, "revision_number": 0, "source_hash": source_hash, "source_path": "scripts/fixtures/amphail.md"}},
            staging_target=old_target,
            workspace=ROOT,
            job_id="amphail-job",
            staging_root="tmp/toolkit_adaptation_amphail_finalization/staging",
            module_slug="Amphail",
            revision_callback=revision_callback,
            rerun_callback=rerun,
        )
        self.assertEqual(len(calls), 1)
        self.assertEqual(result["status"], "success", result)
        self.assertFalse(result["publication_attempted"])
        self.assertFalse(result["hard_gates_passed"])
        self.assertTrue(result["adaptation_revision"]["normalization_reentered"])

    def test_missing_continuity_keys_are_repaired_on_staging_only(self) -> None:
        (ROOT / "module_context.json").write_text(
            json.dumps({"name": "Amphail"}), encoding="utf-8"
        )
        (ROOT / "module_plot.json").write_text(json.dumps({}), encoding="utf-8")

        result = _finalize_adaptation_continuity(ROOT, "Amphail")

        self.assertEqual(result["status"], "success")
        context = json.loads((ROOT / "module_context.json").read_text())
        continuity = context["continuity"]
        self.assertEqual(continuity["continuity_version"], "v1")
        self.assertEqual(continuity["cross_module_refs"], [])
        self.assertTrue(continuity["standalone_fallback"]["enabled"])
        self.assertEqual(
            set(continuity["entry_state_variants"]),
            {"cold_start", "partial_context", "late_arc"},
        )

    def test_continuity_write_failure_is_bounded_and_not_revision_eligible(self) -> None:
        (ROOT / "module_context.json").write_text(
            json.dumps({"name": "Amphail"}), encoding="utf-8"
        )
        (ROOT / "module_plot.json").write_text(json.dumps({}), encoding="utf-8")

        with patch(
            "web.extensions.toolkit_homebrew_packet_builder.safe_write_json",
            return_value=False,
        ):
            result = _finalize_adaptation_continuity(ROOT, "Amphail")

        self.assertEqual(result["status"], "failed")
        self.assertEqual(
            result["reason_code"], "adaptation_continuity_finalization_failed"
        )
        self.assertIn("continuity_context_atomic_write_failed", result["errors"])


class AmphailSoftstoneProductionResolutionTest(unittest.TestCase):
    """Exercise the provider-free destination repair seam with Amphail data."""

    def setUp(self) -> None:
        shutil.rmtree(ROOT, ignore_errors=True)
        ROOT.mkdir(parents=True)
        self.source_hash = "c" * 64
        self.identity = {
            "attempt_id": "amphail-softstone",
            "attempt_number": 1,
            "revision_number": 1,
            "source_hash": self.source_hash,
        }
        target = create_adaptation_staging_target(
            self.source_hash,
            attempt_id=self.identity["attempt_id"],
            attempt_number=1,
            revision_number=1,
            module_slug="Amphail",
            repo_root=ROOT,
            staging_root="staging",
        )
        self.stage = ROOT / target["path"]
        authority = {
            "location_index": {
                "EV001:K02": {"area_id": "EV001", "location_id": "K02"},
                "RO001:K03": {"area_id": "RO001", "location_id": "K03"},
            },
            "location_aliases": {
                "softstone inn": {
                    "status": "ambiguous",
                    "candidate_internal_location_ids": ["EV001:K02", "RO001:K03"],
                }
            },
            "destination_phrases": {
                "softstone inn": {
                    "status": "ambiguous",
                    "candidate_location_ids": ["EV001:K02", "RO001:K03"],
                }
            },
            "diagnostics": {
                "ambiguous_destination_phrases": [{"phrase": "softstone inn"}],
                "unresolved_destination_phrases": [],
            },
            "summary": {"ambiguous_destination_count": 1},
            "attempt": dict(self.identity),
            "adaptation_provenance": dict(self.identity),
        }
        (self.stage / "module_context.json").write_text(
            json.dumps({"name": "Amphail", "semantic_authority": authority}), encoding="utf-8"
        )
        (self.stage / "module_plot.json").write_text(json.dumps({"plotPoints": []}), encoding="utf-8")

    def tearDown(self) -> None:
        shutil.rmtree(ROOT, ignore_errors=True)

    def test_softstone_inn_resolves_one_area_scoped_candidate_and_persists_hashes(self) -> None:
        calls = []

        def callback(context):
            calls.append(context)
            proposal = {
                "contract_version": FINALIZATION_CONTRACT_VERSION,
                "operation": FINALIZATION_OPERATION_DESTINATION_ALIAS,
                "identity": dict(self.identity),
                "target": {
                    "phrase": "softstone inn",
                    "location_id": "EV001:K02",
                    "origin_location_id": "EV001:K01",
                },
                "replacement": "EV001:K02",
                "source_references": ["source.locations.softstone_inn"],
                "confidence": 0.99,
            }
            return {
                "status": "success",
                "proposal": proposal,
                "attempt_id": self.identity["attempt_id"],
                "attempt_number": 1,
                "revision_number": 1,
                "source_hash": self.source_hash,
                "staging_identity": context.get("staging_identity"),
            }

        result = run_adaptation_publication_convergence(
            staged_module_path=str(self.stage),
            mode="llm_adaptation",
            attempt_id=self.identity["attempt_id"],
            attempt_number=1,
            revision_number=1,
            source_hash=self.source_hash,
            repo_root=ROOT,
            provider_callback=callback,
            validation_context={
                "source_reference_ids": ["source.locations.softstone_inn"],
                "canonical_location_ids": ["EV001:K02", "RO001:K03"],
                "topology": {
                    "location_ids": ["EV001:K01", "EV001:K02", "RO001:K03"],
                    "edges": [["EV001:K01", "EV001:K02"]],
                },
                "destination_phrases": ["softstone inn"],
                "ambiguous_destination_phrases": ["softstone inn"],
            },
        )

        self.assertEqual(len(calls), 1)
        self.assertEqual(result["status"], "ready", result)
        self.assertEqual(result["accepted_operation"]["target"]["location_id"], "EV001:K02")
        self.assertTrue(result["accepted_output_hash"])
        self.assertTrue(result["provenance_hash"])
        updated = json.loads((self.stage / "module_context.json").read_text())
        repaired = updated["semantic_authority"]["destination_phrases"]["softstone inn"]
        self.assertEqual(repaired["status"], "resolved")
        self.assertEqual(repaired["location_id"], "EV001:K02")
        self.assertEqual(
            updated["semantic_authority"]["diagnostics"]["ambiguous_destination_phrases"], []
        )

    def test_continuation_requires_all_six_hard_domains_and_current_identity(self) -> None:
        reports = {name: {"status": "pass"} for name in (
            "schema", "readiness", "gameplay", "semantic_authority", "semantic_probe", "publication"
        )}
        accepted = {"status": "ready", **self.identity, "report_path": "convergence_report.json"}
        staging_target = dict(self.identity)
        staging_target.update({"stage_id": "stage-1", "path": "staging/attempt_1/revision_1"})
        attempt_report = dict(self.identity)
        semantic_authority = {
            "attempt": dict(self.identity),
            "adaptation_provenance": {"source_hash": self.source_hash},
        }
        gate_result = {
            "status": "pass", "playable_status": "pass", "publishable_status": "pass",
            "provenance": dict(self.identity),
            "candidate_eligible": True,
            "gates": {
                "schema": {"status": "pass"},
                "readiness": {"status": "pass"},
                "mechanical_closure": {"status": "pass"},
                "semantic_authority": {"status": "pass"},
                "semantic_probes": {"status": "pass"},
                "report_agreement": {"status": "pass"},
            },
        }
        result = validate_adaptation_publication_continuation(
            staging_target=staging_target,
            build_result={"status": "success"},
            attempt_report=attempt_report,
            semantic_authority=semantic_authority,
            convergence_result=accepted,
            gate_result=gate_result,
        )
        self.assertTrue(result["allowed"], result)
        gate_result["gates"]["semantic_authority"] = {"status": "failed"}
        blocked = validate_adaptation_publication_continuation(
            staging_target=staging_target,
            build_result={"status": "success"},
            attempt_report=attempt_report,
            semantic_authority=semantic_authority,
            convergence_result=accepted,
            gate_result=gate_result,
        )
        self.assertFalse(blocked["allowed"])

    def test_production_packet_builder_runs_resolution_refresh_gates_and_finisher(self) -> None:
        """Exercise the real adaptation packet-build and publication boundaries."""
        root = Path(tempfile.mkdtemp(dir="tmp", prefix="amphail-production-"))
        workspace = root / "workspace"
        ensure_workspace_placeholders(workspace)
        files = get_workspace_files(workspace)
        source_hash = hashlib.sha256(b"amphail softstone source").hexdigest()
        dossier = json.loads(
            Path("scripts/fixtures/toolkit_adaptation_dossier_valid.json").read_text(
                encoding="utf-8"
            )
        )
        dossier.update(
            {
                "source_title": "Amphail",
                "adapted_title": "Amphail",
                "source_hash": source_hash,
                "adaptation_mode": ADAPTATION_MODE_LLM,
                "source_profile": "adventure",
            }
        )
        provenance = {
            "attempt_id": "amphail-production",
            "attempt_number": 1,
            "revision_number": 0,
            "source_hash": source_hash,
            "source_path": "scripts/fixtures/amphail.md",
            "source_format": "markdown",
            "source_title": "Amphail",
            "model_metadata": {"provider": "fixture", "model": "provider-free"},
        }
        packet = {
            "packet_version": "v1",
            "normalization_state": "normalized",
            "source_hash": source_hash,
            "source_path": "scripts/fixtures/amphail.md",
            "title": "Amphail",
            "author": "fixture",
            "description": "A bounded Amphail adaptation fixture.",
            "adventure_summary": "Resolve the disputed inn route.",
            "module_tone": "grounded fantasy mystery",
            "acts": [{"name": "The Inn Road"}],
            "locations": [{"name": "softstone inn", "source_ref": "source.locations.softstone_inn"}],
            "destination_phrases": [{"phrase": "softstone inn", "source_ref": "source.locations.softstone_inn"}],
            "connectivity_hints": ["EV001:K01 -> EV001:K02", "RO001:K03"],
            "encounter_seeds": [],
            "npc_seeds": [],
            "monster_refs": [],
            "plot_progression": ["Travel to the softstone inn."],
            "continuity_hints": [],
            "media_hints": [],
            "assumptions": [],
            "warnings": [],
        }
        source_manifest = {
            "source_hash": source_hash,
            "location_candidates": [
                {"name": "softstone inn", "source_ref": "source.locations.softstone_inn"}
            ],
        }
        source_graph = {
            "source_hash": source_hash,
            "atoms": [
                {"atom_id": "source.locations.softstone_inn", "excerpt": "The softstone inn stands near the road."}
            ],
        }
        files["source_original"].write_text(
            "The softstone inn stands near the road.", encoding="utf-8"
        )
        for path, payload in (
            (files["normalized_packet"], packet),
            (files["ui_review_snapshot"], build_review_snapshot("amphail-production", "approve", packet, "user_authored")),
            (files["source_manifest"], source_manifest),
            (files["source_graph"], source_graph),
        ):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload), encoding="utf-8")

        def builder_executor(builder_input, progress_callback=None):
            target = Path(builder_input["derived_builder_parameters"]["output_directory"])
            target.mkdir(parents=True, exist_ok=True)
            (target / "areas").mkdir()
            (target / "module_context.json").write_text(
                json.dumps({"module_id": "Amphail", "module_name": "Amphail", "npcs": []}),
                encoding="utf-8",
            )
            (target / "module_plot.json").write_text(
                json.dumps({"plotPoints": [{"description": "The party follows the softstone inn road."}]}),
                encoding="utf-8",
            )
            for area_id, location in (
                ("EV001", {"locationId": "EV001:K01", "name": "Road Approach", "connectivity": ["K02"]}),
                ("EV001", {"locationId": "EV001:K02", "name": "Softstone Inn", "aliases": ["softstone inn"], "connectivity": ["K01"]}),
                ("RO001", {"locationId": "RO001:K03", "name": "Softstone Inn", "aliases": ["softstone inn"], "connectivity": []}),
            ):
                area_path = target / "areas" / f"{area_id}_{location['locationId']}.json"
                area_path.write_text(
                    json.dumps({"areaId": area_id, "areaName": area_id, "locations": [location]}),
                    encoding="utf-8",
                )
            if progress_callback:
                progress_callback("build", "provider-free Amphail staging fixture")

        def resolution_callback(context):
            calls.append(copy.deepcopy(context))
            request = context["request"]
            self.assertEqual(request["operation"], "resolve_destination_alias")
            bounded = request["validation_context"]
            self.assertEqual(bounded["ambiguous_phrase"], "softstone inn")
            self.assertEqual({row["id"] for row in bounded["candidates"]}, {"EV001:K02", "RO001:K03"})
            self.assertEqual(bounded["source_reference_ids"], ["source.locations.softstone_inn"])
            self.assertEqual(bounded["allowed_operations"], ["resolve_destination_alias"])
            self.assertEqual(bounded["operation_budget"], 1)
            self.assertEqual(bounded["timeout_seconds"], 30)
            payload = json.dumps(context, ensure_ascii=True)
            for forbidden in ("raw_provider_history", "chat_history", "module_source", "arbitrary_path"):
                self.assertNotIn(forbidden, payload)
            return {
                "status": "success",
                "attempt_id": context["attempt_id"],
                "attempt_number": context["attempt_number"],
                "revision_number": context["revision_number"],
                "source_hash": context["source_hash"],
                "staging_identity": copy.deepcopy(context["staging_identity"]),
                "proposal": {
                    "contract_version": FINALIZATION_CONTRACT_VERSION,
                    "operation": FINALIZATION_OPERATION_DESTINATION_ALIAS,
                    "identity": {
                        key: context[key]
                        for key in ("attempt_id", "attempt_number", "revision_number", "source_hash")
                    },
                    "target": {"phrase": "softstone inn", "location_id": "EV001:K02"},
                    "replacement": "EV001:K02",
                    "source_references": ["source.locations.softstone_inn"],
                    "confidence": 0.99,
                },
            }

        calls = []
        gate_calls = []

        def passing_report(*args, **kwargs):
            return {"status": "pass", "effective_status": "pass", "blockers": [], "warnings": [], "errors": []}

        def semantic_report(module_slug, module_dir, **kwargs):
            authority = json.loads((Path(module_dir) / "module_context.json").read_text())[
                "semantic_authority"
            ]
            self.assertEqual(authority["destination_phrases"]["softstone inn"]["status"], "resolved")
            return passing_report()

        try:
            with patch.object(packet_builder, "ENABLE_LLM_ADAPTATION", True), \
                patch.object(packet_builder, "_run_adaptation_monster_guardrail", return_value={"status": "success", "unresolved_refs": []}), \
                patch.object(adaptation_gate_composer, "_run_schema_gate", side_effect=passing_report), \
                patch.object(adaptation_gate_composer, "_run_gameplay_gate", side_effect=passing_report), \
                patch.object(adaptation_gate_composer, "_run_continuity_gate", side_effect=passing_report), \
                patch.object(adaptation_gate_composer, "_run_mechanical_closure_gate", side_effect=passing_report), \
                patch.object(adaptation_gate_composer, "_run_semantic_authority_gate", side_effect=semantic_report), \
                 patch.object(adaptation_gate_composer, "_run_semantic_probe_gate", side_effect=passing_report), \
                 patch.object(adaptation_gate_composer, "_run_report_agreement_gate", side_effect=lambda *a, **k: {"status": "pass", "effective_status": "pass", "playable_publication_status": "pass", "blockers": [], "warnings": [], "errors": [], "adaptation_report_agreement": {"status": "pass"}}), \
                 patch.object(adaptation_gate_composer, "compose_adaptation_report_agreement", return_value={"status": "pass", "blockers": [], "diagnostics": []}), \
                patch.object(adaptation_gate_composer, "run_adaptation_gate_composer", wraps=adaptation_gate_composer.run_adaptation_gate_composer) as real_gate, \
                patch.object(module_finisher, "_run_module_summary_stage", return_value={"status": "success"}), \
                patch.object(module_finisher, "_run_registry_stage", return_value={"status": "success", "verified": True, "verification": {"verified": True}}), \
                patch.object(module_finisher, "_run_adaptation_campaign_sync_stage", return_value={"status": "deferred", "campaign_visibility_verified": False}):
                result = packet_builder.run_toolkit_homebrew_packet_build(
                    workspace=workspace,
                    job_id="amphail-production",
                    builder_executor=builder_executor,
                    adaptation_route=ADAPTATION_MODE_LLM,
                    adaptation_dossier=dossier,
                    adaptation_provenance=provenance,
                    adaptation_staging_root=f"tmp/{root.name}/staging",
                    adaptation_convergence_callback=resolution_callback,
                )
                self.assertEqual(len(calls), 1, result)
                self.assertTrue(real_gate.called, result)
                self.assertEqual(result["adaptation_convergence"]["status"], "ready")
                self.assertEqual(result["adaptation_gates"]["playable_status"], "pass")
                self.assertTrue(result["adaptation_publication_continuation"]["allowed"], result)
                self.assertTrue(result["adaptation_convergence"].get("source_hash"))
                stage = Path(result["output_directory"])
                authority = json.loads((stage / "module_context.json").read_text())["semantic_authority"]
                self.assertEqual(authority["destination_phrases"]["softstone inn"]["location_id"], "EV001:K02")
                report = json.loads((stage / "adaptation_convergence_report.json").read_text())
                self.assertTrue(report["proposal_input_hash"])
                self.assertTrue(report["accepted_output_hash"])
                self.assertTrue(report["provenance_hash"])
                finishing = module_finisher.run_toolkit_module_postbuild_finishing(
                    "Amphail",
                    adaptation_mode=ADAPTATION_MODE_LLM,
                    adaptation_gates=result["adaptation_gates"],
                    adaptation_staging_target=result["staging_target"],
                    adaptation_module_dir=str(stage),
                    adaptation_provenance=result["adaptation_provenance"],
                    adaptation_artifact_workspace=str(workspace),
                )
                self.assertEqual(finishing["status"], "success", finishing)
                self.assertEqual(finishing["stages"]["registry"]["status"], "success")
        finally:
            shutil.rmtree(root, ignore_errors=True)
            shutil.rmtree(Path("tmp") / root.name, ignore_errors=True)

    def test_legacy_packet_entrypoint_bypasses_adaptation_seam(self) -> None:
        """Legacy packet builds retain their shape and never call convergence."""
        root = Path(tempfile.mkdtemp(dir="tmp", prefix="amphail-legacy-"))
        workspace = root / "workspace"
        ensure_workspace_placeholders(workspace)
        files = get_workspace_files(workspace)
        packet = {"packet_version": "v1", "normalization_state": "normalized", "source_hash": "d" * 64, "source_path": "legacy.md", "title": "Legacy Amphail", "author": "fixture", "description": "legacy", "adventure_summary": "legacy", "module_tone": "fantasy", "acts": [], "locations": [], "connectivity_hints": [], "encounter_seeds": [], "npc_seeds": [], "monster_refs": [], "plot_progression": [], "continuity_hints": [], "media_hints": [], "assumptions": [], "warnings": []}
        files["normalized_packet"].write_text(json.dumps(packet), encoding="utf-8")
        files["ui_review_snapshot"].write_text(json.dumps(build_review_snapshot("legacy", "approve", packet, "user_authored")), encoding="utf-8")
        seen = []
        with patch.object(packet_builder, "_execute_module_builder", side_effect=lambda builder_input, **_: seen.append(builder_input)), patch.object(packet_builder, "ENABLE_LLM_ADAPTATION", False), patch.object(packet_builder, "_adaptation_finalization_round", side_effect=AssertionError("legacy convergence invoked")):
            result = packet_builder.run_toolkit_homebrew_packet_build(workspace=workspace, job_id="legacy")
        self.assertEqual(result["status"], "success")
        self.assertNotIn("adaptation_convergence", result)
        self.assertEqual(len(seen), 1)
        self.assertNotIn("llm_adaptation", json.dumps(seen[0]))
        self.assertNotIn("adaptation_route_resolution", result)
        shutil.rmtree(root, ignore_errors=True)


class AmphailStagedReadinessRoutingTest(unittest.TestCase):
    def setUp(self) -> None:
        shutil.rmtree(ROOT, ignore_errors=True)
        (ROOT / "Amphail" / "areas").mkdir(parents=True)
        for name in ("module_context.json", "module_plot.json"):
            (ROOT / "Amphail" / name).write_text("{}", encoding="utf-8")

    def tearDown(self) -> None:
        shutil.rmtree(ROOT, ignore_errors=True)

    def test_isolated_amphail_candidate_uses_module_path_validator_contract(self) -> None:
        candidate = ROOT / "Amphail"
        with patch(
            "web.extensions.toolkit_homebrew_readiness_gate.subprocess.run"
        ) as run:
            run.return_value.returncode = 0
            run.return_value.stdout = json.dumps(
                {"modules": {"Amphail": {"total_failed": 0, "files": {}}}}
            )
            run.return_value.stderr = ""
            report = _run_validator("Amphail", candidate)

        command = run.call_args.args[0]
        self.assertIn("--module-path", command)
        self.assertNotIn("--module", command)
        self.assertEqual(command[command.index("--module-path") + 1], str(candidate))
        self.assertEqual(report["status"], "pass")

    def test_missing_or_unsafe_adaptation_candidate_fails_closed(self) -> None:
        missing, missing_info = _resolve_adaptation_module_path(
            {"adaptation_mode": "llm_adaptation"}, "Amphail"
        )
        self.assertIsNone(missing)
        self.assertEqual(missing_info["reason"], "adaptation_staging_path_missing")

        unsafe, unsafe_info = _resolve_adaptation_module_path(
            {
                "adaptation_mode": "llm_adaptation",
                "output_directory": "../outside/Amphail",
            },
            "Amphail",
        )
        self.assertIsNone(unsafe)
        self.assertEqual(unsafe_info["reason"], "adaptation_staging_path_outside_project")

    def test_legacy_validator_retains_module_slug_command(self) -> None:
        with patch(
            "web.extensions.toolkit_homebrew_readiness_gate.subprocess.run"
        ) as run:
            run.return_value.returncode = 0
            run.return_value.stdout = json.dumps(
                {"modules": {"Amphail": {"total_failed": 0, "files": {}}}}
            )
            run.return_value.stderr = ""
            report = _run_validator("Amphail")

        command = run.call_args.args[0]
        self.assertIn("--module", command)
        self.assertNotIn("--module-path", command)
        self.assertEqual(command[command.index("--module") + 1], "Amphail")
        self.assertEqual(report["status"], "pass")

    def test_staged_basename_namespace_is_used_for_validation_consumers(self) -> None:
        payload = {
            "modules": {
                "revision_000": {
                    "files": {},
                    "total_failed": 0,
                }
            },
            "summary": {"total_failed": 0, "any_failed": False},
        }
        report = {
            "module": "Amphail",
            "module_path": "tmp/adaptation-staging/adapt/revision_000",
            "report": payload,
        }
        self.assertEqual(
            _extract_module_validation_report(
                payload, "Amphail", report["module_path"]
            )["total_failed"],
            0,
        )
        self.assertEqual(_build_validation_signature(report), "")
        self.assertEqual(_extract_failure_categories(report), {})

    def test_staged_failure_namespace_preserves_categories_and_signature(self) -> None:
        payload = {
            "modules": {
                "revision_000": {
                    "files": {
                        "reference_integrity": {
                            "failed": 2,
                            "errors": [
                                "expected monsters/cave_guardian.json",
                                "expected monsters/wight.json",
                            ],
                        }
                    },
                    "total_failed": 2,
                }
            },
            "summary": {"total_failed": 2, "any_failed": True},
        }
        report = {
            "module": "Amphail",
            "module_path": "tmp/adaptation-staging/adapt/revision_000",
            "report": payload,
        }
        self.assertEqual(_extract_failure_categories(report), {"reference_integrity": 2})
        signature = _build_validation_signature(report)
        self.assertIn('"category": "reference_integrity"', signature)
        self.assertIn('"failed": 2', signature)


if __name__ == "__main__":
    unittest.main(verbosity=2)
