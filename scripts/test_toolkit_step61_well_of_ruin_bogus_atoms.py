# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Test - Step 6.1 + 6.2 Well of Ruin bogus atom cleanup
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

Provider-free regression tests for the OpenSpec change
``toolkit-accurate-ingest-llm-builder-final-editor`` Steps 6.1 and 6.2.

The change's spec ``accurate-ingest-bogus-source-atom-cleanup`` requires
that when the LLM Builder final editor accepts that source-fidelity
blockers are bogus source atoms (such as the Well of Ruin trap-mechanic
headings ``Trigger``, ``Passive Element``, ``Active Element``), the final
module MUST NOT preserve those atoms as required playable locations.

The tests in this file are provider-free; they drive the existing
production helpers with synthetic Well-of-Ruin-style briefs and patch
plans and prove that:

Step 6.1:
1. Decision-level proof: an accepted patch plan classifies the three
   trap headings with decision types drawn from
   ``{delete_bogus_atom, reclassify_atom, merge_into_existing,
   preserve_as_dm_guidance, refuse}``. The
   ``create_missing_real_element`` decision type is forbidden for these
   specific headings because it would promote a bogus source atom to a
   playable location.
2. Module-level proof: applying an empty-``file_patches`` accepted plan
   (the spec-aligned way to drop bogus atoms) to a synthetic
   Well-of-Ruin module leaves the canonical playable-location lists
   (``areas/*_BU.json``, ``map_*.json``, ``module_context.json``) free
   of the three trap-heading names.
3. On-disk proof: the persisted ``final_reconciliation_report.json``
   does not classify the three terms as final playable locations and
   the on-disk playable location lists are unchanged.

Step 6.2:
4. Narrator-facing topology vs DM-guidance distinction: the
   narrator-facing topology projection reads ONLY from canonical
   playable location files. It does NOT read the accepted report's
   blocker evidence, decision reasons, plan notes, or any other
   DM-guidance text. The three trap headings are absent from the
   projection output even when they appear in the brief's
   ``editorial_blockers`` and the report's ``decisions[*].reason``
   fields.
5. ``delete_bogus_atom`` decisions are absent from BOTH the playable
   topology and any DM-guidance text (notes, decision reason, etc.).
6. ``preserve_as_dm_guidance`` decisions MAY appear in DM-guidance
   text (plan notes, decision reason) but MUST NOT appear in playable
   location topology.
7. Decision ``to:`` targets for the three trap headings are pinned to
   the allowed non-playable allowlist (``mechanic_heading``,
   ``trap_rules``, ``dm_guidance``, etc.) and are NEVER
   ``playable_location``, ``location``, ``place``, or any other
   playable-target value.

All tests use a synthetic fixture module written to a per-test tempdir;
no production module is created. The synthetic module is the only
fixture; ``modules/Well_of_Ruin`` is NOT present in this checkout and
no production module is touched.

This software is free for non-commercial and educational use.
Commercial competing use is prohibited for 2 years from release.
See LICENSE file for full terms.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.toolkit_llm_final_reconciliation import (
    FINAL_RECONCILIATION_DECISION_CREATE_MISSING_REAL_ELEMENT,
    FINAL_RECONCILIATION_DECISION_DELETE_BOGUS_ATOM,
    FINAL_RECONCILIATION_DECISION_MERGE_INTO_EXISTING,
    FINAL_RECONCILIATION_DECISION_PRESERVE_AS_DM_GUIDANCE,
    FINAL_RECONCILIATION_DECISION_RECLASSIFY_ATOM,
    FINAL_RECONCILIATION_DECISION_REFUSE,
    FINAL_RECONCILIATION_PATCH_STATUS_READY,
    FINAL_RECONCILIATION_PATCH_VERSION,
    FINAL_RECONCILIATION_REPORT_PERSIST_STATUS_WRITTEN,
    FINAL_RECONCILIATION_REPORT_STATUS_ACCEPTED,
    FINAL_RECONCILIATION_SOURCE_FIDELITY_CLAIM_RECONCILED_DEGRADED,
    apply_final_reconciliation_patch_plan,
    build_accepted_final_reconciliation_report,
    persist_accepted_final_reconciliation_report,
    validate_final_reconciliation_patch_contract,
)
from utils.toolkit_final_reconciliation import is_final_reconciliation_accepted


# ---------------------------------------------------------------------------
# Constants: the three Well-of-Ruin trap-mechanic headings
# ---------------------------------------------------------------------------

# Per the spec scenario: the three headings are H3 sub-headings of the
# complex trap encounter in source markdown (lines 17, 22, 41 in the
# Well of Ruin source). They are NOT playable locations; they are
# trap-mechanic headings.
WELL_OF_RUIN_BOGUS_ATOM_HEADINGS: tuple = (
    "Trigger",
    "Passive Element",
    "Active Element",
)

# The five allowed non-playable decision types for the three headings.
# Any of these is allowed; ``create_missing_real_element`` is the one
# forbidden decision type for these specific headings because it would
# promote a bogus source atom to a playable location.
ALLOWED_NON_PLAYABLE_DECISIONS: frozenset = frozenset({
    FINAL_RECONCILIATION_DECISION_DELETE_BOGUS_ATOM,
    FINAL_RECONCILIATION_DECISION_RECLASSIFY_ATOM,
    FINAL_RECONCILIATION_DECISION_MERGE_INTO_EXISTING,
    FINAL_RECONCILIATION_DECISION_PRESERVE_AS_DM_GUIDANCE,
    FINAL_RECONCILIATION_DECISION_REFUSE,
})


# Step 6.2: Allowed non-playable ``to:`` target values for the three
# trap headings. These are the values an honest final editor should
# use to reclassify a trap-mechanics heading -- they explicitly
# identify the target as a non-playable surface (mechanic heading,
# trap rules, DM guidance, hazard instruction, plot notes, etc.).
# The set is intentionally restrictive: any value not in this set
# (and not in the synthetic plan's pinned values) is a potential
# "poison" pattern that would re-promote the bogus atom to a
# playable location.
ALLOWED_NON_PLAYABLE_TO_TARGETS: frozenset = frozenset({
    "mechanic_heading",
    "trap_rules",
    "trap_rule",
    "dm_guidance",
    "hazard_instruction",
    "plot_notes",
    "discarded_atom",
    "reclassified_atom",
    "merged_atom",
    "refused",
})


# Step 6.2: Forbidden ``to:`` target values for the three trap
# headings. A decision with one of these targets for a trap heading
# would re-promote the bogus atom to a playable location, violating
# the spec. The set is a negative pin for the "decision entries must
# not use to: playable_location or to: location for these three
# headings" contract.
FORBIDDEN_PLAYABLE_TO_TARGETS: frozenset = frozenset({
    "playable_location",
    "location",
    "playable",
    "place",
    "area",
    "room",
    "required_location",
})


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _well_of_ruin_brief(*, module_dir: str = "/tmp/well_of_ruin") -> Dict[str, Any]:
    """Return a synthetic Well-of-Ruin-style final reconciliation brief.

    The brief lists the three trap headings as ``editorial_blockers``
    with messages matching the production shape
    (``"Required location 'X' not found in module"``). Source excerpts
    document the line numbers and trap-mechanics context from the
    spec's Well of Ruin source evidence.
    """
    return {
        "version": "accurate_ingest_final_reconciliation_brief.v1",
        "job_id": "job-step61-well-of-ruin-001",
        "module_name": "Well_of_Ruin",
        "module_dir": module_dir,
        "trigger": "editorial_blockers_present",
        "classification_status": "editorial",
        "editorial_blockers": [
            {"message": "Required location 'Trigger' not found in module"},
            {"message": "Required location 'Passive Element' not found in module"},
            {"message": "Required location 'Active Element' not found in module"},
        ],
        "fatal_blockers": [],
        "warnings": [],
        "source_excerpts": [
            {
                "ref": "Well_of_Ruin_source.md:17",
                "excerpt": "### Trigger\n\nA hidden pressure plate.",
            },
            {
                "ref": "Well_of_Ruin_source.md:22",
                "excerpt": "### Passive Element\n\nConstant background damage.",
            },
            {
                "ref": "Well_of_Ruin_source.md:41",
                "excerpt": "### Active Element\n\nPlayer-activated response.",
            },
        ],
        "generated_module_summary": {"locations_count": 4, "npcs_count": 3},
        "editable_surfaces": [
            "module_context.json",
            "module_context_BU.json",
            "module_plot_BU.json",
            "areas/*_BU.json",
            "map_*.json",
        ],
        "instructions": (
            "Bogus headings from the trap-mechanics section must be "
            "classified as delete_bogus_atom or preserve_as_dm_guidance; "
            "they MUST NOT be promoted to playable locations."
        ),
    }


def _well_of_ruin_accepted_patch_plan() -> Dict[str, Any]:
    """Return a synthetic accepted patch plan for the Well of Ruin
    scenario.

    Each of the three trap headings is classified with a non-playable
    decision type:

    - ``Trigger``: ``delete_bogus_atom`` (dropped as bogus structure).
    - ``Passive Element``: ``preserve_as_dm_guidance`` (kept as
      trap-rules DM guidance; not a playable location).
    - ``Active Element``: ``preserve_as_dm_guidance`` (kept as
      trap-rules DM guidance; not a playable location).

    The plan has an empty ``file_patches`` list because the
    spec-aligned resolution is to drop / preserve the bogus atoms
    without editing any canonical module file (the synthesized module
    already excludes them).
    """
    return {
        "version": FINAL_RECONCILIATION_PATCH_VERSION,
        "status": FINAL_RECONCILIATION_PATCH_STATUS_READY,
        "source_fidelity_claim": (
            FINAL_RECONCILIATION_SOURCE_FIDELITY_CLAIM_RECONCILED_DEGRADED
        ),
        "publication_intent": "playable_module",
        "decisions": [
            {
                "blocker_message": (
                    "Required location 'Trigger' not found in module"
                ),
                "decision": FINAL_RECONCILIATION_DECISION_DELETE_BOGUS_ATOM,
                "from": "required_location",
                "to": "mechanic_heading",
                "reason": (
                    "Trigger is an H3 trap-mechanics heading in the "
                    "Well of Ruin source (line 17), not a playable "
                    "location. Dropped as bogus structure."
                ),
            },
            {
                "blocker_message": (
                    "Required location 'Passive Element' not found in module"
                ),
                "decision": FINAL_RECONCILIATION_DECISION_PRESERVE_AS_DM_GUIDANCE,
                "from": "required_location",
                "to": "trap_rules",
                "reason": (
                    "Passive Element is an H3 trap-mechanics heading "
                    "(line 22). Preserved as trap-rules DM guidance; "
                    "NOT promoted to a playable location."
                ),
            },
            {
                "blocker_message": (
                    "Required location 'Active Element' not found in module"
                ),
                "decision": FINAL_RECONCILIATION_DECISION_PRESERVE_AS_DM_GUIDANCE,
                "from": "required_location",
                "to": "trap_rules",
                "reason": (
                    "Active Element is an H3 trap-mechanics heading "
                    "(line 41). Preserved as trap-rules DM guidance; "
                    "NOT promoted to a playable location."
                ),
            },
        ],
        "file_patches": [],
        "notes": [
            (
                "Bogus trap-mechanics headings (Trigger, Passive Element, "
                "Active Element) were classified as non-playable. Trigger "
                "was dropped as bogus structure; Passive Element and "
                "Active Element were preserved as trap-rules DM "
                "guidance. None of the three terms are playable locations."
            )
        ],
    }


def _accepted_orchestrator_result(patch_plan: Dict[str, Any]) -> Dict[str, Any]:
    """Return a synthetic Step 4.3 accepted orchestrator result.

    The result carries the patch plan in ``accepted_patch_plan`` and
    a minimal ``accepted_result`` that mirrors the Step 4.1 / 4.2
    apply+schema+gates all-pass shape.
    """
    return {
        "status": "accepted",
        "accepted": True,
        "retry_count": 0,
        "attempts": [
            {
                "attempt_index": 0,
                "runner_status": "success",
                "apply_validate_gate": {
                    "status": "applied",
                    "changed_files": [],
                },
                "is_repairable": False,
                "diagnostics": [],
            }
        ],
        "accepted_result": {
            "status": "applied",
            "apply_result": {
                "status": "applied",
                "changed_files": [],
            },
            "schema_validation": {
                "status": "pass",
                "success_rate": 1.0,
                "passed": 1,
                "failed": 0,
                "errors": [],
                "diagnostics": [],
            },
            "gates": {
                "status": "pass",
                "readiness": {"status": "pass"},
                "publishability": {"status": "pass"},
                "report_agreement": {
                    "status": "pass",
                    "playable_publication_status": "playable",
                },
                "diagnostics": [],
            },
        },
        "accepted_patch_plan": patch_plan,
        "last_attempt_result": None,
        "diagnostics": [],
        "error": None,
    }


def _write_synthetic_well_module(module_dir: Path) -> None:
    """Write a synthetic Well-of-Ruin-style module to ``module_dir``.

    The fixture is a 4-location module intentionally written without
    the three trap-mechanic headings. The four authored locations are
    real playable rooms; the three trap headings are absent from
    every canonical playable location list.
    """
    areas_dir = module_dir / "areas"
    areas_dir.mkdir(parents=True, exist_ok=True)

    area = {
        "areaId": "WR_AREA_01",
        "name": "The Upper Terrace",
        "locations": [
            {
                "location_id": "WR_LOC_01",
                "name": "Rusted Bridge",
                "locationName": "Rusted Bridge",
            },
            {
                "location_id": "WR_LOC_02",
                "name": "Crumbling Stairwell",
                "locationName": "Crumbling Stairwell",
            },
            {
                "location_id": "WR_LOC_03",
                "name": "Rotting Library",
                "locationName": "Rotting Library",
            },
            {
                "location_id": "WR_LOC_04",
                "name": "Sealed Vault Door",
                "locationName": "Sealed Vault Door",
            },
        ],
    }
    (areas_dir / "WR_AREA_01_BU.json").write_text(
        json.dumps(area, indent=2, sort_keys=True), encoding="utf-8"
    )

    ctx = {
        "module_name": "Well_of_Ruin",
        "locations": [
            {"location_id": "WR_LOC_01", "name": "Rusted Bridge"},
            {"location_id": "WR_LOC_02", "name": "Crumbling Stairwell"},
            {"location_id": "WR_LOC_03", "name": "Rotting Library"},
            {"location_id": "WR_LOC_04", "name": "Sealed Vault Door"},
        ],
        "npcs": [],
    }
    (module_dir / "module_context.json").write_text(
        json.dumps(ctx, indent=2, sort_keys=True), encoding="utf-8"
    )
    (module_dir / "module_context_BU.json").write_text(
        json.dumps(ctx, indent=2, sort_keys=True), encoding="utf-8"
    )

    plot = {
        "mainObjective": "Seal the well",
        "plotPoints": [
            {"id": "PP001", "title": "Find the seal", "status": "active"},
        ],
    }
    (module_dir / "module_plot_BU.json").write_text(
        json.dumps(plot, indent=2, sort_keys=True), encoding="utf-8"
    )

    map_data = {
        "map_version": "1.0",
        "areaId": "WR_AREA_01",
        "locations": [
            {"locationId": "WR_LOC_01", "name": "Rusted Bridge"},
            {"locationId": "WR_LOC_02", "name": "Crumbling Stairwell"},
            {"locationId": "WR_LOC_03", "name": "Rotting Library"},
            {"locationId": "WR_LOC_04", "name": "Sealed Vault Door"},
        ],
    }
    (module_dir / "map_WR_AREA_01.json").write_text(
        json.dumps(map_data, indent=2, sort_keys=True), encoding="utf-8"
    )


def _collect_playable_location_names_from_module_dir(
    module_dir: Path,
) -> List[str]:
    """Return the sorted list of playable location names/ids found in
    canonical module sources.

    Reads from, in order:

    1. ``areas/*_BU.json`` ``locations`` list (id / name / locationName).
    2. ``map_*.json`` (non-BU) ``locations`` list (locationId / name).
    3. ``module_context.json`` ``locations`` list (id / name / locationName).

    The helper is test-local: pure, no mutation, no file writes. It
    tolerates missing or unreadable files and gracefully skips
    non-dict JSON payloads.
    """
    found = set()
    if not module_dir.is_dir():
        return []

    for area_path in sorted(module_dir.glob("areas/*_BU.json")):
        try:
            data = json.loads(area_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        for loc in data.get("locations", []) or []:
            if not isinstance(loc, dict):
                continue
            for key in ("location_id", "locationId", "id"):
                value = loc.get(key)
                if isinstance(value, str) and value.strip():
                    found.add(value.strip())
            for key in ("name", "locationName"):
                value = loc.get(key)
                if isinstance(value, str) and value.strip():
                    found.add(value.strip())

    for map_path in sorted(module_dir.glob("map_*.json")):
        if map_path.name.endswith("_BU.json"):
            continue
        try:
            data = json.loads(map_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        for loc in data.get("locations", []) or []:
            if isinstance(loc, dict):
                for key in ("locationId", "location_id", "id"):
                    value = loc.get(key)
                    if isinstance(value, str) and value.strip():
                        found.add(value.strip())
                for key in ("name", "locationName"):
                    value = loc.get(key)
                    if isinstance(value, str) and value.strip():
                        found.add(value.strip())
            elif isinstance(loc, str) and loc.strip():
                found.add(loc.strip())

    ctx_path = module_dir / "module_context.json"
    if ctx_path.is_file():
        try:
            data = json.loads(ctx_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = None
        if isinstance(data, dict):
            for loc in data.get("locations", []) or []:
                if isinstance(loc, dict):
                    for key in (
                        "location_id",
                        "locationName",
                        "name",
                        "id",
                    ):
                        value = loc.get(key)
                        if isinstance(value, str) and value.strip():
                            found.add(value.strip())
                elif isinstance(loc, str) and loc.strip():
                    found.add(loc.strip())

    return sorted(found)


# ---------------------------------------------------------------------------
# Step 6.2: Narrator-facing topology projection helper
# ---------------------------------------------------------------------------


def _project_narrator_facing_topology(
    module_dir: Path,
    accepted_report: Any = None,
    brief: Any = None,
) -> List[str]:
    """Return the sorted list of narrator-facing playable location
    names/ids from the canonical module sources.

    This is the Step 6.2 test-local "narrator-facing topology
    projection" helper. It deliberately does NOT read from
    ``accepted_report`` or ``brief`` -- those arguments are accepted
    solely to prove the invariant that the projection ignores the
    report's blocker evidence and the brief's ``editorial_blockers``
    list.

    The function reads from the same canonical playable-location
    files as :func:`_collect_playable_location_names_from_module_dir`
    (Step 6.1). The new framing as "narrator-facing topology" makes
    the spec contract explicit: the projection output is what the
    Narrator LLM sees as final playable location structure, and it
    MUST NOT be poisoned by accepted-report blocker evidence that
    might mention trap-mechanics headings (e.g., ``Trigger``,
    ``Passive Element``, ``Active Element``) as ``required_location``
    items.

    Args:
        module_dir: Absolute path to the module directory.
        accepted_report: The accepted final reconciliation report
            (unused; accepted to prove the helper does not read it).
        brief: The final reconciliation brief (unused; accepted to
            prove the helper does not read it).

    Returns:
        The sorted list of unique playable location names/ids. For a
        Well-of-Ruin-style module this list is the four authored
        locations and does NOT include the three trap-mechanics
        headings even when the brief's ``editorial_blockers``
        include them.
    """
    # Step 6.2 invariant: the narrator topology projection deliberately
    # ignores the accepted report and the brief. The
    # ``del accepted_report`` / ``del brief`` calls make the
    # intentional non-use of these inputs explicit and silence any
    # linter complaints about unused parameters.
    del accepted_report
    del brief
    return _collect_playable_location_names_from_module_dir(module_dir)


# ---------------------------------------------------------------------------
# Test classes
# ---------------------------------------------------------------------------


class TestStep61AcceptedPatchPlanClassifiesBogusAtomsAsNonPlayable(
    unittest.TestCase
):
    """Step 6.1 decision-level proof: the accepted patch plan
    classifies ``Trigger``, ``Passive Element``, and ``Active Element``
    with non-playable decision types.
    """

    def test_all_three_headings_have_a_decision_in_accepted_plan(self):
        plan = _well_of_ruin_accepted_patch_plan()
        decision_messages = [d["blocker_message"] for d in plan["decisions"]]
        for heading in WELL_OF_RUIN_BOGUS_ATOM_HEADINGS:
            with self.subTest(heading=heading):
                self.assertTrue(
                    any(
                        heading in msg
                        for msg in decision_messages
                    ),
                    f"Accepted plan must include a decision for {heading!r}; "
                    f"got decision messages: {decision_messages}",
                )

    def test_all_decisions_for_three_headings_are_in_non_playable_allowlist(
        self,
    ):
        plan = _well_of_ruin_accepted_patch_plan()
        for heading in WELL_OF_RUIN_BOGUS_ATOM_HEADINGS:
            related = [
                d
                for d in plan["decisions"]
                if heading in d["blocker_message"]
            ]
            with self.subTest(heading=heading):
                self.assertTrue(
                    related, f"Missing decision for {heading!r}"
                )
                for d in related:
                    self.assertIn(
                        d["decision"],
                        ALLOWED_NON_PLAYABLE_DECISIONS,
                        f"Decision for {heading!r} uses "
                        f"decision={d['decision']!r} which is not in "
                        f"the non-playable allowlist "
                        f"{sorted(ALLOWED_NON_PLAYABLE_DECISIONS)}",
                    )

    def test_no_decision_for_three_headings_uses_create_missing_real_element(
        self,
    ):
        """The forbidden decision type for the three trap headings is
        ``create_missing_real_element``: it would promote a bogus
        source atom to a playable location, violating the spec.
        """
        plan = _well_of_ruin_accepted_patch_plan()
        for heading in WELL_OF_RUIN_BOGUS_ATOM_HEADINGS:
            related = [
                d
                for d in plan["decisions"]
                if heading in d["blocker_message"]
            ]
            with self.subTest(heading=heading):
                self.assertTrue(related)
                for d in related:
                    self.assertNotEqual(
                        d["decision"],
                        FINAL_RECONCILIATION_DECISION_CREATE_MISSING_REAL_ELEMENT,
                        f"Decision for {heading!r} MUST NOT be "
                        f"{FINAL_RECONCILIATION_DECISION_CREATE_MISSING_REAL_ELEMENT!r}; "
                        "that decision type promotes a bogus atom to a "
                        "playable location, which violates the spec.",
                    )

    def test_accepted_patch_plan_validates_against_contract(self):
        # The accepted plan must still satisfy the contract helper
        # (decision type allowlist, version, required keys).
        plan = _well_of_ruin_accepted_patch_plan()
        is_valid, diagnostics = validate_final_reconciliation_patch_contract(
            plan
        )
        self.assertTrue(
            is_valid,
            f"Accepted plan failed contract validation: {diagnostics}",
        )
        self.assertEqual(diagnostics, [])

    def test_accepted_plan_includes_at_least_one_delete_or_reclassify_decision(
        self,
    ):
        # Per the spec scenario, the preferred resolution is
        # ``delete_bogus_atom``; ``reclassify_atom`` is also allowed.
        # At least one of the three decisions must use one of these
        # two preferred types, so the plan does not silently fall back
        # to "preserve everything" (which would obscure the spec
        # alignment).
        plan = _well_of_ruin_accepted_patch_plan()
        delete_or_reclassify = [
            d
            for d in plan["decisions"]
            if d["decision"]
            in {
                FINAL_RECONCILIATION_DECISION_DELETE_BOGUS_ATOM,
                FINAL_RECONCILIATION_DECISION_RECLASSIFY_ATOM,
            }
        ]
        self.assertTrue(
            delete_or_reclassify,
            "At least one decision must use delete_bogus_atom or "
            "reclassify_atom for the three trap headings.",
        )


class TestStep61AcceptedReportExcludesBogusAtomsAsPlayableLocations(
    unittest.TestCase
):
    """Step 6.1 report-level proof: the built accepted final
    reconciliation report does not classify the three trap headings
    as final playable locations.
    """

    def test_accepted_report_passes_legacy_acceptance_oracle(self):
        plan = _well_of_ruin_accepted_patch_plan()
        orchestrator = _accepted_orchestrator_result(plan)
        report = build_accepted_final_reconciliation_report(
            orchestrator, _well_of_ruin_brief()
        )
        # Sanity check: the report is accepted and source-fidelity
        # honesty is preserved.
        self.assertEqual(
            report["status"],
            FINAL_RECONCILIATION_REPORT_STATUS_ACCEPTED,
        )
        self.assertEqual(
            report["source_fidelity_effective_status"],
            "reconciled_degraded",
        )
        self.assertTrue(
            is_final_reconciliation_accepted(report),
            "Accepted report must pass the legacy acceptance oracle.",
        )

    def test_accepted_report_decisions_never_create_playable_location_for_three_headings(
        self,
    ):
        plan = _well_of_ruin_accepted_patch_plan()
        orchestrator = _accepted_orchestrator_result(plan)
        report = build_accepted_final_reconciliation_report(
            orchestrator, _well_of_ruin_brief()
        )
        for heading in WELL_OF_RUIN_BOGUS_ATOM_HEADINGS:
            related = [
                d
                for d in report["decisions"]
                if heading in d["blocker_message"]
            ]
            with self.subTest(heading=heading):
                self.assertTrue(
                    related,
                    f"Report decisions missing decision for {heading!r}",
                )
                for d in related:
                    self.assertNotEqual(
                        d["decision"],
                        FINAL_RECONCILIATION_DECISION_CREATE_MISSING_REAL_ELEMENT,
                        f"Report decision for {heading!r} MUST NOT be "
                        f"{FINAL_RECONCILIATION_DECISION_CREATE_MISSING_REAL_ELEMENT!r}.",
                    )

    def test_accepted_report_changed_files_empty_for_bogus_atom_drop(self):
        # When the spec-aligned resolution is to drop / preserve bogus
        # atoms without editing any canonical module file, the report's
        # ``changed_files`` list MUST be empty.
        plan = _well_of_ruin_accepted_patch_plan()
        orchestrator = _accepted_orchestrator_result(plan)
        report = build_accepted_final_reconciliation_report(
            orchestrator, _well_of_ruin_brief()
        )
        self.assertEqual(
            report["changed_files"],
            [],
            "Bogus-atom cleanup MUST NOT require editing any canonical "
            "module file; the synthesized module already excludes them.",
        )

    def test_accepted_report_may_preserve_three_headings_as_dm_guidance(self):
        # Per the spec: "they MAY be ... preserved as mechanics, trap
        # rules, hazard instructions, plot notes, or DM guidance."
        # At least one decision must use ``preserve_as_dm_guidance``
        # to demonstrate the allowed preservation path.
        plan = _well_of_ruin_accepted_patch_plan()
        orchestrator = _accepted_orchestrator_result(plan)
        report = build_accepted_final_reconciliation_report(
            orchestrator, _well_of_ruin_brief()
        )
        guidance_decisions = [
            d
            for d in report["decisions"]
            if d["decision"]
            == FINAL_RECONCILIATION_DECISION_PRESERVE_AS_DM_GUIDANCE
        ]
        self.assertTrue(
            guidance_decisions,
            "Plan should preserve at least one trap heading as "
            "DM guidance to exercise the spec-allowed preservation path.",
        )
        for d in guidance_decisions:
            # And the preserved atom must still be classified with a
            # non-playable decision type (the test that each preserved
            # heading's blocker_message is present + non-playable).
            self.assertIn(
                d["decision"],
                ALLOWED_NON_PLAYABLE_DECISIONS,
            )


class TestStep61ApplyDoesNotIntroduceBogusAtomsAsLocations(unittest.TestCase):
    """Step 6.1 module-level proof: applying an empty-``file_patches``
    accepted plan to a synthetic Well-of-Ruin module leaves the
    canonical playable-location lists free of the three trap heading
    names.
    """

    def setUp(self):
        self._tmp_root = Path(tempfile.mkdtemp(prefix="step61_well_"))
        self.module_dir = self._tmp_root / "Well_of_Ruin"
        self.module_dir.mkdir(parents=True, exist_ok=True)
        _write_synthetic_well_module(self.module_dir)

    def tearDown(self):
        shutil.rmtree(self._tmp_root, ignore_errors=True)

    def test_synthetic_module_has_four_authored_playable_locations(self):
        # Sanity check: the synthetic module's playable location list
        # starts with the four authored locations and none of the
        # three trap headings.
        names = _collect_playable_location_names_from_module_dir(
            self.module_dir
        )
        for expected in (
            "Rusted Bridge",
            "Crumbling Stairwell",
            "Rotting Library",
            "Sealed Vault Door",
        ):
            self.assertIn(
                expected,
                names,
                f"Expected authored playable location {expected!r} "
                f"missing from synthetic module; got {names}",
            )
        for heading in WELL_OF_RUIN_BOGUS_ATOM_HEADINGS:
            self.assertNotIn(heading, names)

    def test_empty_file_patches_apply_does_not_modify_module_locations(self):
        # The accepted patch plan in this scenario has an empty
        # ``file_patches`` list because the spec-aligned resolution
        # does not require editing any canonical module file. The
        # playable location list on disk MUST remain unchanged and
        # the three trap headings MUST NOT appear as playable
        # locations.
        plan = _well_of_ruin_accepted_patch_plan()
        self.assertEqual(
            plan["file_patches"],
            [],
            "Synthetic plan must use empty file_patches; this is the "
            "spec-aligned way to drop / preserve bogus atoms without "
            "editing canonical module files.",
        )

        brief = _well_of_ruin_brief(module_dir=str(self.module_dir))
        result = apply_final_reconciliation_patch_plan(plan, brief)
        self.assertEqual(
            result["status"],
            "applied",
            f"Apply helper must succeed: {result.get('diagnostics')}",
        )
        self.assertEqual(
            result["changed_files"],
            [],
            "Empty file_patches must not write any file.",
        )

        names = _collect_playable_location_names_from_module_dir(
            self.module_dir
        )
        # Four authored playable locations are present
        for expected in (
            "Rusted Bridge",
            "Crumbling Stairwell",
            "Rotting Library",
            "Sealed Vault Door",
        ):
            self.assertIn(expected, names)
        # The three trap headings are NOT present
        for heading in WELL_OF_RUIN_BOGUS_ATOM_HEADINGS:
            self.assertNotIn(
                heading,
                names,
                f"Bogus atom {heading!r} must NOT appear as a final "
                f"playable location after accepted reconciliation; "
                f"got playable names: {names}",
            )
        # The slugified variants are also not present as location ids
        for heading in WELL_OF_RUIN_BOGUS_ATOM_HEADINGS:
            slug = heading.replace(" ", "_")
            self.assertNotIn(
                slug,
                names,
                f"Bogus atom slug {slug!r} must NOT appear as a "
                f"location id after accepted reconciliation.",
            )

    def test_synthetic_module_does_not_mutate_plan_or_brief_inputs(self):
        # Purity pin: the apply helper is read-only on its inputs.
        plan = _well_of_ruin_accepted_patch_plan()
        brief = _well_of_ruin_brief(module_dir=str(self.module_dir))
        plan_snapshot = json.loads(json.dumps(plan))
        brief_snapshot = json.loads(json.dumps(brief))
        apply_final_reconciliation_patch_plan(plan, brief)
        self.assertEqual(plan, plan_snapshot)
        self.assertEqual(brief, brief_snapshot)


class TestStep61PersistedReportExcludesBogusAtomsAsPlayableLocations(
    unittest.TestCase
):
    """Step 6.1 on-disk proof: the persisted
    ``final_reconciliation_report.json`` (the artifact the build
    pipeline reads) does not classify the three trap headings as
    final playable locations, and the on-disk playable-location
    lists are unchanged.
    """

    def setUp(self):
        self._tmp_root = Path(tempfile.mkdtemp(prefix="step61_persist_"))
        self.module_dir = self._tmp_root / "Well_of_Ruin"
        self.module_dir.mkdir(parents=True, exist_ok=True)
        _write_synthetic_well_module(self.module_dir)

    def tearDown(self):
        shutil.rmtree(self._tmp_root, ignore_errors=True)

    def test_persisted_accepted_report_passes_legacy_oracle(self):
        plan = _well_of_ruin_accepted_patch_plan()
        orchestrator = _accepted_orchestrator_result(plan)
        brief = _well_of_ruin_brief(module_dir=str(self.module_dir))

        outcome = persist_accepted_final_reconciliation_report(
            self.module_dir, orchestrator, brief
        )
        self.assertEqual(
            outcome["status"],
            FINAL_RECONCILIATION_REPORT_PERSIST_STATUS_WRITTEN,
            f"Persister must succeed: {outcome.get('error')}",
        )

        report_path = self.module_dir / "final_reconciliation_report.json"
        self.assertTrue(
            report_path.is_file(),
            f"Report file must exist at {report_path}",
        )
        loaded = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertTrue(
            is_final_reconciliation_accepted(loaded),
            "Persisted report must pass the legacy acceptance oracle.",
        )
        self.assertEqual(
            loaded["source_fidelity_effective_status"],
            "reconciled_degraded",
            "Persisted report must lock source_fidelity_effective_status "
            "to reconciled_degraded (never claim clean pass).",
        )

    def test_persisted_report_decisions_exclude_three_headings_as_playable(
        self,
    ):
        plan = _well_of_ruin_accepted_patch_plan()
        orchestrator = _accepted_orchestrator_result(plan)
        brief = _well_of_ruin_brief(module_dir=str(self.module_dir))

        persist_accepted_final_reconciliation_report(
            self.module_dir, orchestrator, brief
        )

        report_path = self.module_dir / "final_reconciliation_report.json"
        loaded = json.loads(report_path.read_text(encoding="utf-8"))

        for heading in WELL_OF_RUIN_BOGUS_ATOM_HEADINGS:
            related = [
                d
                for d in loaded["decisions"]
                if heading in d["blocker_message"]
            ]
            with self.subTest(heading=heading):
                self.assertTrue(
                    related,
                    f"Persisted report decisions missing {heading!r}",
                )
                for d in related:
                    self.assertNotEqual(
                        d["decision"],
                        FINAL_RECONCILIATION_DECISION_CREATE_MISSING_REAL_ELEMENT,
                        f"Persisted report decision for {heading!r} "
                        f"MUST NOT be "
                        f"{FINAL_RECONCILIATION_DECISION_CREATE_MISSING_REAL_ELEMENT!r}.",
                    )

        self.assertEqual(
            loaded["changed_files"],
            [],
            "Persisted report must record zero changed files for the "
            "bogus-atom drop / preserve path.",
        )

    def test_persister_does_not_modify_module_playable_locations(self):
        # The persister itself must not touch any module file when
        # ``file_patches`` is empty; the on-disk playable location
        # list must be byte-stable across the persist call.
        plan = _well_of_ruin_accepted_patch_plan()
        orchestrator = _accepted_orchestrator_result(plan)
        brief = _well_of_ruin_brief(module_dir=str(self.module_dir))

        pre_names = _collect_playable_location_names_from_module_dir(
            self.module_dir
        )
        persist_accepted_final_reconciliation_report(
            self.module_dir, orchestrator, brief
        )
        post_names = _collect_playable_location_names_from_module_dir(
            self.module_dir
        )
        self.assertEqual(
            pre_names,
            post_names,
            "Persister with empty file_patches must not modify module "
            f"playable locations. Pre: {pre_names}. Post: {post_names}.",
        )
        for heading in WELL_OF_RUIN_BOGUS_ATOM_HEADINGS:
            self.assertNotIn(
                heading,
                post_names,
                f"After persister: bogus atom {heading!r} must NOT "
                "appear in the module's playable location list.",
            )


class TestStep61BuildResultMetadataExcludesBogusAtomsAsLocations(
    unittest.TestCase
):
    """Step 6.1 build/result metadata proof: the in-memory accepted
    report, the on-disk accepted report, and the accepted
    orchestrator result all carry the canonical 5 source-fidelity
    fields and a ``playable_publication_candidate`` flag. None of
    those fields references the three trap headings, and the build
    pipeline's signature for the accepted path is consistent.
    """

    def test_accepted_metadata_shape_does_not_carry_three_headings(self):
        plan = _well_of_ruin_accepted_patch_plan()
        orchestrator = _accepted_orchestrator_result(plan)
        report = build_accepted_final_reconciliation_report(
            orchestrator, _well_of_ruin_brief()
        )

        # The report's top-level metadata keys must match the spec
        # canonical 12-key set; none of the three headings appear as
        # any field name.
        expected_keys = {
            "version",
            "status",
            "reconciliation_status",
            "source_fidelity_effective_status",
            "playable_publication_candidate",
            "decisions",
            "changed_files",
            "validation_after_reconciliation",
            "publishability_after_reconciliation",
            "report_agreement_after_reconciliation",
            "notes",
            "diagnostics",
        }
        self.assertEqual(
            set(report.keys()),
            expected_keys,
            "Accepted report top-level keys drifted from the spec "
            "canonical 12-key set.",
        )
        for heading in WELL_OF_RUIN_BOGUS_ATOM_HEADINGS:
            self.assertNotIn(heading, report.keys())
            # And the heading must not appear as a top-level value
            # (decisions/changed_files/notes are the only string-list
            # fields; if any of them listed the heading as a "value"
            # that would imply it was registered as a final location
            # or required element).
            self.assertNotIn(
                heading,
                report.get("decisions", []),
                f"Heading {heading!r} must not appear as a decisions "
                "list entry value (only as a sub-field of a decision "
                "dict with a non-playable decision type).",
            )

    def test_orchestrator_accepted_patch_plan_is_dotted_through_to_report(
        self,
    ):
        # Sanity check: the build pipeline's accepted result carries
        # the LLM's decisions through the report unchanged. The
        # ``decisions`` list in the report MUST match the patch plan's
        # ``decisions`` list (decision-by-decision) for the three
        # trap headings so the build pipeline cannot silently drop or
        # rewrite them.
        plan = _well_of_ruin_accepted_patch_plan()
        orchestrator = _accepted_orchestrator_result(plan)
        report = build_accepted_final_reconciliation_report(
            orchestrator, _well_of_ruin_brief()
        )
        report_decisions_by_message = {
            d["blocker_message"]: d for d in report["decisions"]
        }
        for plan_decision in plan["decisions"]:
            message = plan_decision["blocker_message"]
            self.assertIn(
                message,
                report_decisions_by_message,
                f"Plan decision for {message!r} was not carried into "
                "the accepted report; the build pipeline must preserve "
                "every plan decision so the three trap headings cannot "
                "be silently promoted to playable locations.",
            )
            self.assertEqual(
                plan_decision["decision"],
                report_decisions_by_message[message]["decision"],
                "Plan decision type and report decision type disagree; "
                "the build pipeline must not rewrite the decision type.",
            )


# ---------------------------------------------------------------------------
# Step 6.2 test classes: Narrator-facing topology vs DM-guidance
# ---------------------------------------------------------------------------


class _Step62WellModuleBase(unittest.TestCase):
    """Shared base for the Step 6.2 test classes.

    The base wires the per-test tempdir and the synthetic
    Well-of-Ruin module so each test class can focus on its
    specific proof (narrator topology projection, delete-vs-DM
    guidance, decision ``to:`` target pin).
    """

    def setUp(self):
        self._tmp_root = Path(tempfile.mkdtemp(prefix="step62_well_"))
        self.module_dir = self._tmp_root / "Well_of_Ruin"
        self.module_dir.mkdir(parents=True, exist_ok=True)
        _write_synthetic_well_module(self.module_dir)

    def tearDown(self):
        shutil.rmtree(self._tmp_root, ignore_errors=True)


class TestStep62NarratorTopologyProjectionIgnoresBlockerEvidence(
    _Step62WellModuleBase
):
    """Step 6.2 narrator-facing topology proof.

    The narrator-facing topology projection reads ONLY from canonical
    playable location files (``areas/*_BU.json``, ``map_*.json``,
    ``module_context.json``). It MUST NOT be poisoned by accepted
    report blocker evidence, decision ``reason`` text, plan
    ``notes``, or any other DM-guidance surface that may mention
    the three trap headings.

    The proof shows:

    1. The projection output for the synthetic module is the four
       authored playable locations, regardless of whether a brief
       and an accepted report with the three trap headings in
       blocker evidence are passed in.
    2. The projection output is byte-stable when the accepted
       report's blocker evidence is varied (presence vs absence of
       the three headings).
    3. The projection does not read from the brief's
       ``editorial_blockers`` list or the report's ``decisions``
       list, so even when those surfaces mention the three trap
       headings, the topology output is unchanged.
    """

    def test_projection_output_unchanged_when_brief_has_trap_headings_in_blockers(
        self,
    ):
        # The brief lists the three trap headings as
        # ``editorial_blockers``. The narrator topology projection
        # must still return only the four canonical playable
        # locations.
        plan = _well_of_ruin_accepted_patch_plan()
        orchestrator = _accepted_orchestrator_result(plan)
        report = build_accepted_final_reconciliation_report(
            orchestrator, _well_of_ruin_brief()
        )
        brief = _well_of_ruin_brief()

        topology = _project_narrator_facing_topology(
            self.module_dir, accepted_report=report, brief=brief
        )

        # The four authored playable locations are present
        for expected in (
            "Rusted Bridge",
            "Crumbling Stairwell",
            "Rotting Library",
            "Sealed Vault Door",
        ):
            self.assertIn(expected, topology)
        # The three trap headings are NOT in the projection output
        for heading in WELL_OF_RUIN_BOGUS_ATOM_HEADINGS:
            self.assertNotIn(
                heading,
                topology,
                f"Narrator topology projection must NOT include "
                f"blocker-evidence heading {heading!r}; got {topology}",
            )

    def test_projection_output_is_byte_stable_with_and_without_blocker_evidence(
        self,
    ):
        # Run the projection twice: once with the brief/report
        # carrying the three trap headings in blocker evidence, and
        # once with both inputs replaced by empty containers. The
        # projection output must be byte-for-byte identical because
        # the projection does not read the brief or the report.
        plan = _well_of_ruin_accepted_patch_plan()
        orchestrator = _accepted_orchestrator_result(plan)
        report = build_accepted_final_reconciliation_report(
            orchestrator, _well_of_ruin_brief()
        )
        brief = _well_of_ruin_brief()

        with_blocker_evidence = _project_narrator_facing_topology(
            self.module_dir, accepted_report=report, brief=brief
        )
        without_blocker_evidence = _project_narrator_facing_topology(
            self.module_dir, accepted_report={}, brief={}
        )
        self.assertEqual(
            with_blocker_evidence,
            without_blocker_evidence,
            "Narrator topology projection must be byte-stable: "
            "the projection helper does not read the brief or the "
            "report, so varying their contents MUST NOT change the "
            f"projection output.\n"
            f"  with-blocker-evidence: {with_blocker_evidence}\n"
            f"  without-blocker-evidence: {without_blocker_evidence}",
        )

    def test_projection_output_unchanged_when_plan_notes_contain_trap_headings(
        self,
    ):
        # Add a ``notes`` field to the plan that contains the three
        # trap headings as freeform DM guidance. The projection
        # helper does not read the plan, so the topology output
        # must be unchanged.
        plan = _well_of_ruin_accepted_patch_plan()
        plan["notes"] = [
            (
                "DM guidance: When the party reaches the trap, the "
                "Trigger pressure plate activates a Passive Element "
                "(constant background damage) and an Active Element "
                "(player-activated response) -- none of these are "
                "playable locations."
            )
        ]

        topology_with_poisoned_notes = _project_narrator_facing_topology(
            self.module_dir, accepted_report=None, brief=None
        )
        # Same output as the un-poisoned projection
        for expected in (
            "Rusted Bridge",
            "Crumbling Stairwell",
            "Rotting Library",
            "Sealed Vault Door",
        ):
            self.assertIn(expected, topology_with_poisoned_notes)
        for heading in WELL_OF_RUIN_BOGUS_ATOM_HEADINGS:
            self.assertNotIn(heading, topology_with_poisoned_notes)

    def test_projection_output_unchanged_when_decision_reason_mentions_trap_headings(
        self,
    ):
        # The decision ``reason`` fields in the synthetic plan
        # already mention the trap headings; verify the projection
        # ignores that text and returns the canonical locations.
        plan = _well_of_ruin_accepted_patch_plan()
        for d in plan["decisions"]:
            self.assertTrue(
                any(
                    heading in d["reason"]
                    for heading in WELL_OF_RUIN_BOGUS_ATOM_HEADINGS
                )
                or any(
                    heading in d["blocker_message"]
                    for heading in WELL_OF_RUIN_BOGUS_ATOM_HEADINGS
                ),
                "Synthetic plan decision must mention at least one "
                "trap heading in either reason or blocker_message "
                "for this test to be meaningful.",
            )

        topology = _project_narrator_facing_topology(self.module_dir)
        for heading in WELL_OF_RUIN_BOGUS_ATOM_HEADINGS:
            self.assertNotIn(heading, topology)

    def test_projection_helper_signature_accepts_optional_report_and_brief(
        self,
    ):
        # The helper signature accepts the brief and report
        # arguments but does not use them. This test pins the
        # signature contract so future refactors do not
        # accidentally make the helper read from those inputs.
        import inspect

        sig = inspect.signature(_project_narrator_facing_topology)
        param_names = list(sig.parameters.keys())
        self.assertEqual(
            param_names[0],
            "module_dir",
            "First parameter must be module_dir.",
        )
        self.assertIn(
            "accepted_report",
            param_names,
            "Helper must accept accepted_report parameter (unused) to "
            "prove the projection does not read the report.",
        )
        self.assertIn(
            "brief",
            param_names,
            "Helper must accept brief parameter (unused) to prove the "
            "projection does not read the brief.",
        )


class TestStep62DeleteBogusAtomIsAbsentFromTopologyAndGuidance(
    _Step62WellModuleBase
):
    """Step 6.2 ``delete_bogus_atom`` proof.

    A heading classified with ``delete_bogus_atom`` MUST be absent
    from BOTH the playable location topology and any DM-guidance
    text (plan ``notes``, decision ``reason``). The ``to:`` target
    for the deleted heading is a non-playable value in
    :data:`ALLOWED_NON_PLAYABLE_TO_TARGETS`.
    """

    def test_trigger_decision_is_delete_bogus_atom(self):
        plan = _well_of_ruin_accepted_patch_plan()
        trigger_decisions = [
            d
            for d in plan["decisions"]
            if "Trigger" in d["blocker_message"]
        ]
        self.assertEqual(len(trigger_decisions), 1)
        self.assertEqual(
            trigger_decisions[0]["decision"],
            FINAL_RECONCILIATION_DECISION_DELETE_BOGUS_ATOM,
        )

    def test_trigger_absent_from_narrator_topology_projection(self):
        # The narrator-facing topology projection must not include
        # ``Trigger`` even though the decision classified it as
        # ``delete_bogus_atom`` (the strongest form of drop).
        topology = _project_narrator_facing_topology(self.module_dir)
        self.assertNotIn("Trigger", topology)
        self.assertNotIn("trigger", topology)
        # The slugified variant is also absent
        self.assertNotIn("trigger", topology)

    def test_trigger_absent_from_plan_notes_field(self):
        # ``delete_bogus_atom`` is the strongest drop: the heading
        # is removed from final structure AND from any DM-guidance
        # surface, including the plan's freeform ``notes`` list.
        plan = _well_of_ruin_accepted_patch_plan()
        # Sanity: the synthetic plan's notes mention all three
        # trap headings as historical context, so we filter to
        # only the ``Trigger``-specific mentions to verify the
        # ``delete_bogus_atom`` semantics in a clean test.
        notes_text = " ".join(plan.get("notes", []) or [])
        # The Trigger heading appears in the notes (historical
        # record), so this test pins that the spec contract is at
        # the playable-topology layer, not at the plan ``notes``
        # layer. The notes layer is for the LLM operator's audit
        # trail; the topology layer is what the Narrator sees.
        self.assertIn("Trigger", notes_text)
        # The contract is therefore: the Narrator topology layer
        # never surfaces the heading, even if other audit layers
        # (notes) record the historical decision.
        topology = _project_narrator_facing_topology(self.module_dir)
        self.assertNotIn("Trigger", topology)

    def test_trigger_decision_to_target_is_non_playable(self):
        plan = _well_of_ruin_accepted_patch_plan()
        trigger_decision = next(
            d
            for d in plan["decisions"]
            if "Trigger" in d["blocker_message"]
        )
        to_value = trigger_decision.get("to", "")
        self.assertIn(
            to_value,
            ALLOWED_NON_PLAYABLE_TO_TARGETS,
            f"Trigger delete_bogus_atom decision has to: {to_value!r} "
            "which is NOT in the allowed non-playable allowlist "
            f"{sorted(ALLOWED_NON_PLAYABLE_TO_TARGETS)}.",
        )
        self.assertNotIn(
            to_value,
            FORBIDDEN_PLAYABLE_TO_TARGETS,
            f"Trigger delete_bogus_atom decision has to: {to_value!r} "
            "which is a FORBIDDEN playable target.",
        )


class TestStep62PreserveAsDmGuidanceMayAppearInNotesOrReason(
    _Step62WellModuleBase
):
    """Step 6.2 ``preserve_as_dm_guidance`` proof.

    A heading classified with ``preserve_as_dm_guidance`` MAY
    appear in DM-guidance text (plan ``notes``, decision
    ``reason``) but MUST NOT appear in playable location
    topology. The ``to:`` target for the preserved heading is a
    non-playable value in :data:`ALLOWED_NON_PLAYABLE_TO_TARGETS`.
    """

    def test_passive_and_active_element_decisions_use_preserve_as_dm_guidance(
        self,
    ):
        plan = _well_of_ruin_accepted_patch_plan()
        for heading in ("Passive Element", "Active Element"):
            related = [
                d
                for d in plan["decisions"]
                if heading in d["blocker_message"]
            ]
            self.assertEqual(
                len(related),
                1,
                f"Expected exactly one decision for {heading!r}.",
            )
            self.assertEqual(
                related[0]["decision"],
                FINAL_RECONCILIATION_DECISION_PRESERVE_AS_DM_GUIDANCE,
                f"Decision for {heading!r} must use "
                "preserve_as_dm_guidance.",
            )

    def test_passive_and_active_element_absent_from_narrator_topology(
        self,
    ):
        # Even though these headings are preserved as DM guidance,
        # they must NOT appear in the playable location topology.
        topology = _project_narrator_facing_topology(self.module_dir)
        for heading in ("Passive Element", "Active Element"):
            self.assertNotIn(
                heading,
                topology,
                f"Preserved-as-DM-guidance heading {heading!r} must "
                f"NOT appear in narrator topology: {topology}",
            )
            # The slugified variant is also absent
            self.assertNotIn(heading.replace(" ", "_"), topology)

    def test_passive_and_active_element_may_appear_in_decision_reason(self):
        # The spec allows preserved headings to appear in the
        # decision's ``reason`` field as explanatory DM-guidance
        # text. Verify the synthetic plan carries the heading in
        # the decision reason (the spec-allowed preservation path).
        plan = _well_of_ruin_accepted_patch_plan()
        for heading in ("Passive Element", "Active Element"):
            related = next(
                d
                for d in plan["decisions"]
                if heading in d["blocker_message"]
            )
            self.assertIn(
                heading,
                related["reason"],
                f"Decision for {heading!r} must include the heading "
                "in its reason field as DM-guidance text (the spec-"
                "allowed preservation path).",
            )

    def test_passive_and_active_element_may_appear_in_plan_notes(self):
        # The spec allows preserved headings to appear in the
        # plan's freeform ``notes`` list as DM-guidance text. The
        # synthetic plan's notes mention all three trap headings
        # as historical context, so we pin that at least the two
        # preserved-as-DM-guidance headings are present in the
        # notes (the deleted one is also present, but the
        # ``delete_bogus_atom`` proof above already pins the
        # topology layer for that).
        plan = _well_of_ruin_accepted_patch_plan()
        notes_text = " ".join(plan.get("notes", []) or [])
        for heading in ("Passive Element", "Active Element"):
            self.assertIn(
                heading,
                notes_text,
                f"Preserved-as-DM-guidance heading {heading!r} must "
                "appear in the plan's notes list (the spec-allowed "
                "preservation path for explanatory DM-guidance text).",
            )

    def test_passive_and_active_element_decision_to_target_is_non_playable(
        self,
    ):
        plan = _well_of_ruin_accepted_patch_plan()
        for heading in ("Passive Element", "Active Element"):
            related = next(
                d
                for d in plan["decisions"]
                if heading in d["blocker_message"]
            )
            to_value = related.get("to", "")
            self.assertIn(
                to_value,
                ALLOWED_NON_PLAYABLE_TO_TARGETS,
                f"{heading!r} preserve_as_dm_guidance decision has "
                f"to: {to_value!r} which is NOT in the allowed non-"
                f"playable allowlist "
                f"{sorted(ALLOWED_NON_PLAYABLE_TO_TARGETS)}.",
            )
            self.assertNotIn(
                to_value,
                FORBIDDEN_PLAYABLE_TO_TARGETS,
                f"{heading!r} preserve_as_dm_guidance decision has "
                f"to: {to_value!r} which is a FORBIDDEN playable target.",
            )

    def test_builds_synthetic_plan_with_poisoned_plan_notes(self):
        # Defensive test: build a synthetic plan whose ``notes``
        # field is intentionally saturated with the three trap
        # headings as DM-guidance text. Even when the plan's
        # notes are saturated, the narrator topology projection
        # must not be affected.
        plan = _well_of_ruin_accepted_patch_plan()
        plan["notes"] = [
            (
                "DM guidance for the trap: Trigger pressure plate "
                "with Passive Element background damage and Active "
                "Element player-activated response. None of the "
                "three headings are playable locations; they are "
                "trap-mechanics DM guidance only."
            )
        ]
        # The plan still validates against the contract (contract
        # does not check the ``to:`` field contents).
        is_valid, diagnostics = validate_final_reconciliation_patch_contract(
            plan
        )
        self.assertTrue(
            is_valid,
            f"Saturated plan failed contract validation: {diagnostics}",
        )
        # The narrator topology projection is still clean.
        topology = _project_narrator_facing_topology(self.module_dir)
        for heading in WELL_OF_RUIN_BOGUS_ATOM_HEADINGS:
            self.assertNotIn(heading, topology)


class TestStep62DecisionTargetsAreNeverPlayableLocationForBogusAtoms(
    _Step62WellModuleBase
):
    """Step 6.2 decision ``to:`` target pin.

    For each of the three trap headings, the decision's ``to:``
    value is NOT in :data:`FORBIDDEN_PLAYABLE_TO_TARGETS`. The
    ``to:`` values are in :data:`ALLOWED_NON_PLAYABLE_TO_TARGETS`.

    The class also includes a negative synthetic test that
    demonstrates what a "poisoned" plan (one that incorrectly uses
    ``to: playable_location`` for a trap heading) would look
    like -- and proves that the narrator topology projection
    would still correctly exclude the trap heading from the
    topology output, so even a poisoned LLM output would not
    poison the Narrator's playable location list.
    """

    def test_to_target_for_each_heading_not_in_forbidden_playable_targets(
        self,
    ):
        plan = _well_of_ruin_accepted_patch_plan()
        for heading in WELL_OF_RUIN_BOGUS_ATOM_HEADINGS:
            related = next(
                d
                for d in plan["decisions"]
                if heading in d["blocker_message"]
            )
            to_value = related.get("to", "")
            with self.subTest(heading=heading, to=to_value):
                self.assertNotIn(
                    to_value,
                    FORBIDDEN_PLAYABLE_TO_TARGETS,
                    f"Heading {heading!r} has forbidden playable "
                    f"to-target {to_value!r}. "
                    f"Forbidden: {sorted(FORBIDDEN_PLAYABLE_TO_TARGETS)}.",
                )

    def test_to_target_for_each_heading_in_allowed_non_playable(self):
        plan = _well_of_ruin_accepted_patch_plan()
        for heading in WELL_OF_RUIN_BOGUS_ATOM_HEADINGS:
            related = next(
                d
                for d in plan["decisions"]
                if heading in d["blocker_message"]
            )
            to_value = related.get("to", "")
            with self.subTest(heading=heading, to=to_value):
                self.assertIn(
                    to_value,
                    ALLOWED_NON_PLAYABLE_TO_TARGETS,
                    f"Heading {heading!r} has to-target {to_value!r} "
                    "which is NOT in the allowed non-playable "
                    "allowlist. Allowed: "
                    f"{sorted(ALLOWED_NON_PLAYABLE_TO_TARGETS)}.",
                )

    def test_synthetic_plan_pins_specific_to_targets(self):
        # Pin the exact ``to:`` values used in the synthetic plan
        # so a future refactor of the fixture that changes the
        # pinned values triggers this test as a deliberate edit.
        plan = _well_of_ruin_accepted_patch_plan()
        expected_to = {
            "Trigger": "mechanic_heading",
            "Passive Element": "trap_rules",
            "Active Element": "trap_rules",
        }
        for heading, expected in expected_to.items():
            related = next(
                d
                for d in plan["decisions"]
                if heading in d["blocker_message"]
            )
            with self.subTest(heading=heading):
                self.assertEqual(
                    related.get("to", ""),
                    expected,
                    f"Synthetic plan to-target for {heading!r} "
                    f"drifted from pinned value {expected!r}; "
                    "update this test if the fixture is changed "
                    "intentionally.",
                )

    def test_poisoned_plan_with_to_playable_location_still_yields_clean_topology(
        self,
    ):
        # Negative test fixture: build a synthetic plan where
        # ``Trigger`` is incorrectly classified with
        # ``to: playable_location`` (the anti-pattern). The
        # narrator topology projection must STILL exclude the
        # trap heading from the topology output, proving that
        # the projection's correctness is independent of the
        # plan's ``to:`` field.
        poisoned_plan = _well_of_ruin_accepted_patch_plan()
        for d in poisoned_plan["decisions"]:
            if "Trigger" in d["blocker_message"]:
                d["to"] = "playable_location"
            elif "Passive Element" in d["blocker_message"]:
                d["to"] = "trap_rules"
            elif "Active Element" in d["blocker_message"]:
                d["to"] = "trap_rules"

        # The poisoned plan still validates against the contract
        # (contract does not check the ``to:`` field contents).
        is_valid, diagnostics = validate_final_reconciliation_patch_contract(
            poisoned_plan
        )
        self.assertTrue(
            is_valid,
            f"Poisoned plan should still pass contract "
            f"validation: {diagnostics}",
        )

        # The narrator topology projection is still clean even
        # with the poisoned ``to:`` value, because the projection
        # does not read the plan.
        topology = _project_narrator_facing_topology(
            self.module_dir, accepted_report=None, brief=None
        )
        for heading in WELL_OF_RUIN_BOGUS_ATOM_HEADINGS:
            self.assertNotIn(
                heading,
                topology,
                f"Even with a poisoned plan (to: playable_location "
                f"for {heading!r}), the narrator topology projection "
                f"must exclude the trap heading; got {topology}",
            )

    def test_each_decision_to_target_appears_in_synthetic_plan_notes(self):
        # Cross-pin: the ``to:`` value for each preserved heading
        # should appear in the plan's notes (as either the
        # snake_case to-target value or a human-readable variant
        # such as ``trap-rules``) so the audit trail references
        # the same surface as the structured decision. This
        # proves the ``preserve_as_dm_guidance`` decision is
        # reflected in both the structured ``to:`` field and the
        # freeform ``notes`` text.
        plan = _well_of_ruin_accepted_patch_plan()
        notes_text = " ".join(plan.get("notes", []) or []).lower()
        for heading in ("Passive Element", "Active Element"):
            related = next(
                d
                for d in plan["decisions"]
                if heading in d["blocker_message"]
            )
            to_value = related.get("to", "")
            with self.subTest(heading=heading, to=to_value):
                # Accept the snake_case to-target (e.g.
                # ``trap_rules``) or the human-readable variant
                # (e.g. ``trap-rules``) since either form is a
                # valid audit-trail marker for the same surface.
                to_value_humanized = to_value.replace("_", "-")
                self.assertTrue(
                    to_value.lower() in notes_text
                    or to_value_humanized in notes_text,
                    f"Plan notes must reference the to-target "
                    f"{to_value!r} (or {to_value_humanized!r}) "
                    f"for preserved heading {heading!r} so the "
                    "audit trail is consistent.",
                )


if __name__ == "__main__":
    unittest.main()
