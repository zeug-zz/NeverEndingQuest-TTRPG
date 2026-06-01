# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0

"""
Tests for builder blueprint fidelity precheck gate (Phase 4, Section 2).

Verifies that:
- clean/repaired fidelity allows blueprint generation
- blocked/failed fidelity refuses blueprint generation
- missing source artifacts refuse blueprint generation
- degraded fidelity (with or without blockers) allows blueprint generation
  (pre-build diagnostics are nonblocking; final gates remain authoritative)
- blueprint report persists refusal status
- Elden Ring-like source classification coverage
"""

import json
import os
import tempfile
import unittest
from pathlib import Path

from utils.toolkit_builder_blueprint import (
    STATUS_BLOCKED_BY_FIDELITY,
    STATUS_MISSING_ARTIFACTS,
    STATUS_READY,
    build_builder_blueprint_report,
    evaluate_blueprint_fidelity_precheck,
    load_phase2_artifacts,
)

from utils.toolkit_source_manifest import (
    build_source_graph,
    build_source_manifest,
    _extract_location_candidates,
    _extract_entity_candidates,
    _extract_heading_hierarchy,
    _is_heading_location_name,
    _is_likely_name,
    _is_map_key_style_heading,
    _normalize_heading_text,
    _APPENDIX_PATTERN,
    _HEADING_PREFIX_WORDS,
)


def _make_source_graph(npc_count: int = 5, loc_count: int = 3) -> dict:
    atoms = []
    for i in range(npc_count):
        atoms.append({"id": f"npc_{i}", "name": f"NPC_{i}", "type": "npc",
                       "criticality": "required", "source_refs": [{"excerpt": f"NPC {i} source"}]})
    for i in range(loc_count):
        atoms.append({"id": f"loc_{i}", "name": f"Location_{i}", "type": "location",
                       "criticality": "required", "source_refs": [{"excerpt": f"Location {i} source"}]})
    return {"atoms": atoms}


def _make_packet(title: str = "Test Module") -> dict:
    return {
        "packet_version": "v1",
        "normalization_state": "normalized",
        "source_hash": "abc123",
        "title": title,
        "locations": [],
        "npc_seeds": [],
    }


def _make_fidelity_report(status: str, blocking: bool = False) -> dict:
    findings = []
    if blocking:
        findings.append({
            "finding_id": "block_001",
            "source_atom_id": "npc_0",
            "category": "missing",
            "severity": "blocking",
            "repairable": True,
            "expected": "NPC_0",
            "actual": "",
        })
    return {
        "status": status,
        "findings": findings,
    }


class TestBlueprintFidelityPrecheck(unittest.TestCase):

    def test_clean_fidelity_allows_generation(self):
        result = evaluate_blueprint_fidelity_precheck(
            source_graph=_make_source_graph(),
            normalized_packet=_make_packet(),
            fidelity_report=_make_fidelity_report("clean"),
            normalization_report=None,
        )
        self.assertEqual(result["precheck_status"], "allowed")

    def test_repaired_fidelity_allows_generation(self):
        result = evaluate_blueprint_fidelity_precheck(
            source_graph=_make_source_graph(),
            normalized_packet=_make_packet(),
            fidelity_report=_make_fidelity_report("repaired"),
            normalization_report=None,
        )
        self.assertEqual(result["precheck_status"], "allowed")

    def test_blocked_fidelity_refuses_generation(self):
        result = evaluate_blueprint_fidelity_precheck(
            source_graph=_make_source_graph(),
            normalized_packet=_make_packet(),
            fidelity_report=_make_fidelity_report("blocked"),
            normalization_report=None,
        )
        self.assertEqual(result["precheck_status"], "refused")
        self.assertEqual(result["refusal_reason"], STATUS_BLOCKED_BY_FIDELITY)

    def test_failed_fidelity_refuses_generation(self):
        result = evaluate_blueprint_fidelity_precheck(
            source_graph=_make_source_graph(),
            normalized_packet=_make_packet(),
            fidelity_report=_make_fidelity_report("failed"),
            normalization_report=None,
        )
        self.assertEqual(result["precheck_status"], "refused")
        self.assertEqual(result["refusal_reason"], STATUS_BLOCKED_BY_FIDELITY)

    def test_missing_source_graph_refuses_generation(self):
        result = evaluate_blueprint_fidelity_precheck(
            source_graph=None,
            normalized_packet=_make_packet(),
            fidelity_report=_make_fidelity_report("clean"),
            normalization_report=None,
        )
        self.assertEqual(result["precheck_status"], "refused")
        self.assertEqual(result["refusal_reason"], STATUS_MISSING_ARTIFACTS)

    def test_missing_packet_refuses_generation(self):
        result = evaluate_blueprint_fidelity_precheck(
            source_graph=_make_source_graph(),
            normalized_packet=None,
            fidelity_report=_make_fidelity_report("clean"),
            normalization_report=None,
        )
        self.assertEqual(result["precheck_status"], "refused")
        self.assertEqual(result["refusal_reason"], STATUS_MISSING_ARTIFACTS)

    def test_degraded_with_blocking_findings_allows(self):
        """Degraded fidelity with blocking findings now ALLOWS blueprint generation.

        Pre-build diagnostics are nonblocking by default.  Final gates
        (validation, benchmark, publishability) remain authoritative.
        """
        result = evaluate_blueprint_fidelity_precheck(
            source_graph=_make_source_graph(),
            normalized_packet=_make_packet(),
            fidelity_report=_make_fidelity_report("degraded", blocking=True),
            normalization_report=None,
        )
        self.assertEqual(result["precheck_status"], "allowed")

    def test_degraded_without_blockers_allows(self):
        result = evaluate_blueprint_fidelity_precheck(
            source_graph=_make_source_graph(),
            normalized_packet=_make_packet(),
            fidelity_report=_make_fidelity_report("degraded", blocking=False),
            normalization_report=None,
        )
        self.assertEqual(result["precheck_status"], "allowed")

    def test_fidelity_report_rollup_reads_from_normalization_report(self):
        result = evaluate_blueprint_fidelity_precheck(
            source_graph=_make_source_graph(),
            normalized_packet=_make_packet(),
            fidelity_report=None,
            normalization_report={"fidelity": {"status": "clean"}},
        )
        self.assertEqual(result["precheck_status"], "allowed")

    def test_unknown_fidelity_status_allows_if_no_blockers(self):
        result = evaluate_blueprint_fidelity_precheck(
            source_graph=_make_source_graph(),
            normalized_packet=_make_packet(),
            fidelity_report=None,
            normalization_report=None,
        )
        self.assertEqual(result["precheck_status"], "allowed")


class TestLoadPhase2Artifacts(unittest.TestCase):

    def test_returns_none_for_missing_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            files = {
                "source_graph": Path(tmp) / "missing.json",
            }
            artifacts = load_phase2_artifacts(files)
            self.assertIsNone(artifacts["source_graph"])

    def test_loads_existing_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "source_graph.json"
            path.write_text(json.dumps({"atoms": [{"id": "test"}]}))
            files = {"source_graph": path}
            artifacts = load_phase2_artifacts(files)
            self.assertIsNotNone(artifacts["source_graph"])
            self.assertEqual(artifacts["source_graph"]["atoms"][0]["id"], "test")


class TestBlueprintReportBuilder(unittest.TestCase):

    def test_report_contains_input_artifact_status(self):
        artifacts = {
            "source_graph": _make_source_graph(),
            "identity_resolution_report": {"canonical_identities": [{"display_name": "Test"}]},
            "plot_topology_report": {},
            "normalized_packet": _make_packet(),
            "normalization_fidelity_report": _make_fidelity_report("clean"),
            "normalization_report": None,
            "source_graph_synthesis_report": None,
        }
        precheck = {"precheck_status": "allowed", "fidelity_status": "clean", "blocking_findings": [], "detail": "", "refusal_reason": ""}
        report = build_builder_blueprint_report("ready", artifacts, precheck)
        self.assertEqual(report["blueprint_status"], "ready")
        self.assertTrue(report["input_artifacts"]["source_graph_present"])
        self.assertTrue(report["input_artifacts"]["identity_resolution_present"])

    def test_report_refusal_has_reason(self):
        artifacts = {"source_graph": None}
        precheck = {"precheck_status": "refused", "refusal_reason": "missing_artifacts", "fidelity_status": "unknown", "blocking_findings": [], "detail": "missing source_graph"}
        report = build_builder_blueprint_report("missing_artifacts", artifacts, precheck)
        self.assertEqual(report["refusal_reason"], "missing_artifacts")


# ---------------------------------------------------------------------------
# Source atom classification coverage (Section 2)
# ---------------------------------------------------------------------------

_ELDEN_LIKE_SOURCE = """\
# Elden Ring Side Quest

## Introduction

The party sets out on a dangerous path. Gathered around a crumbling stone
archway they spot a **Nomadic Merchant** with a strange look in his eye.
"Beware the **Lesser Black Knife Assassin** who stalks these grounds."

### Bridge of Sacrifice

This ancient stone bridge spans a dark chasm. A **Guard Dog** patrols the
right side and a **Lion Guardian** rests near the far pillar.

#### 1\\. Chapel

A ruined chapel stands at the bridge's end. Inside, a single bloodstained
altar suggests a grim ritual took place here.

#### 2\\. Tower

A crumbling watchtower overlooks the bridge. **Two Sentinels** stand guard.

### Non Player Character

- **Nomadic Merchant** -- sells basic supplies
- **Lion Guardian** -- defends the bridge

## Appendix A: Creatures

- Guard Dog: HP 22, AC 12
- Lesser Black Knife Assassin: HP 35, AC 15
- Lion Guardian: HP 45, AC 16

## Getting Started

This adventure is designed for a party of 4-6 characters.

## Appendix B: Credits

Written by the community.
"""


class TestSourceAtomClassification(unittest.TestCase):
    """Provider-free tests for source atom classification coverage."""

    def test_heading_locations_are_extracted(self):
        """Markdown headings like '### Bridge of Sacrifice' become location atoms."""
        graph = build_source_graph(_ELDEN_LIKE_SOURCE)
        loc_names = {a["name"] for a in graph["atoms"] if a["type"] == "location"}
        self.assertIn("Bridge of Sacrifice", loc_names)
        # Chapel and Tower should also be extracted via heading hierarchy
        # (they're sub-headings under Bridge of Sacrifice)
        self.assertIn("1. Chapel", loc_names)
        self.assertIn("2. Tower", loc_names)

    def test_escaped_room_headings_normalized(self):
        """Escaped headings like '1\\. Chapel' normalize to '1. Chapel'.
        The heading text is what comes after the '####' markers.
        """
        result = _normalize_heading_text("1\\. Chapel")
        self.assertEqual(result, "1. Chapel")

    def test_appendix_headings_are_not_location_candidates(self):
        """Appendix/credits headings are NOT location candidates."""
        manifest = build_source_manifest(_ELDEN_LIKE_SOURCE)
        loc_names = {c["name"] for c in manifest["location_candidates"]}
        self.assertNotIn("Appendix A", loc_names)
        self.assertNotIn("Appendix B", loc_names)

    def test_appendix_headings_are_not_graph_locations(self):
        """Appendix headings do not appear as location atoms in the source graph."""
        graph = build_source_graph(_ELDEN_LIKE_SOURCE)
        loc_names = {a["name"] for a in graph["atoms"] if a["type"] == "location"}
        self.assertNotIn("Appendix A", loc_names)
        self.assertNotIn("Appendix B", loc_names)
        self.assertNotIn("Getting Started", loc_names)

    def test_prose_fragment_not_classified_as_entity(self):
        """'gathered around a' is NOT promoted to an entity atom."""
        manifest = build_source_manifest(_ELDEN_LIKE_SOURCE)
        entity_names = {c["name"].lower() for c in manifest["entity_candidates"]}
        self.assertNotIn("gathered around a", entity_names)

    def test_prose_fragment_not_in_source_graph_atoms(self):
        """Prose fragments must not appear as atoms in the source graph."""
        graph = build_source_graph(_ELDEN_LIKE_SOURCE)
        all_names = {a["name"].lower() for a in graph["atoms"]}
        self.assertNotIn("gathered around a", all_names)
        # "Gathered Around A" (proper-noun extraction) should also not appear
        self.assertNotIn("gathered around a crumbling", all_names)

    def test_npc_like_names_kept_as_source_context(self):
        """NPC-like names (Nomadic Merchant) are captured as source atoms."""
        graph = build_source_graph(_ELDEN_LIKE_SOURCE)
        npc_names = {a["name"] for a in graph["atoms"] if a["type"] == "npc"}
        self.assertIn("Nomadic Merchant", npc_names)

    def test_creature_like_names_kept_as_source_context(self):
        """Creature names (Guard Dog, Lesser Black Knife Assassin, Lion Guardian)
        are captured as entity atoms in the source graph."""
        graph = build_source_graph(_ELDEN_LIKE_SOURCE)
        entity_names = {a["name"] for a in graph["atoms"]}
        # Guard Dog is bolded in the source
        self.assertIn("Guard Dog", entity_names)
        # Lion Guardian is bolded in the source
        self.assertIn("Lion Guardian", entity_names)
        # Lesser Black Knife Assassin is bolded
        self.assertIn("Lesser Black Knife Assassin", entity_names)

    def test_bold_spans_detected(self):
        """Bold spans (**Name**) are detected as entity candidates."""
        manifest = build_source_manifest(_ELDEN_LIKE_SOURCE)
        entity_names = {c["name"] for c in manifest["entity_candidates"]}
        self.assertIn("Nomadic Merchant", entity_names)
        self.assertIn("Lesser Black Knife Assassin", entity_names)
        self.assertIn("Guard Dog", entity_names)
        self.assertIn("Lion Guardian", entity_names)
        self.assertIn("Two Sentinels", entity_names)


class TestHeadingClassificationHelpers(unittest.TestCase):
    """Unit tests for source manifest heading classification helpers."""

    def test_is_heading_location_name_accepts_place(self):
        self.assertTrue(_is_heading_location_name("Bridge of Sacrifice"))
        self.assertTrue(_is_heading_location_name("1. Chapel"))
        self.assertTrue(_is_heading_location_name("The Dark Tower"))

    def test_is_heading_location_name_rejects_appendix(self):
        self.assertFalse(_is_heading_location_name("Appendix A"))
        self.assertFalse(_is_heading_location_name("Appendices"))
        self.assertFalse(_is_heading_location_name("Credits"))
        self.assertFalse(_is_heading_location_name("Bibliography"))

    def test_is_heading_location_name_rejects_common_labels(self):
        self.assertFalse(_is_heading_location_name("Introduction"))
        self.assertFalse(_is_heading_location_name("Getting Started"))
        self.assertFalse(_is_heading_location_name("Overview"))
        self.assertFalse(_is_heading_location_name("Running the Adventure"))
        self.assertFalse(_is_heading_location_name("Player Character"))

    def test_is_heading_location_name_rejects_prose_fragment(self):
        """Headings that are dominated by function words fail."""
        self.assertFalse(_is_heading_location_name("Gathered around a stone"))
        self.assertFalse(_is_heading_location_name("Across the great beyond"))
        self.assertFalse(_is_heading_location_name("What the players should know"))

    def test_is_map_key_style_heading_detects_numbered(self):
        self.assertTrue(_is_map_key_style_heading("1. The Bridge"))
        self.assertTrue(_is_map_key_style_heading("12) Chamber"))
        self.assertTrue(_is_map_key_style_heading("3 - Armory"))

    def test_is_map_key_style_heading_rejects_plain_text(self):
        self.assertFalse(_is_map_key_style_heading("Bridge of Sacrifice"))
        self.assertFalse(_is_map_key_style_heading("The Chapel"))

    def test_is_likely_name_rejects_prose_fragments(self):
        """Prose fragments dominated by function words are NOT likely names."""
        self.assertFalse(_is_likely_name("gathered around a"))
        self.assertFalse(_is_likely_name("across the great"))
        self.assertFalse(_is_likely_name("this is not"))

    def test_is_likely_name_accepts_creature_names(self):
        self.assertTrue(_is_likely_name("Guard Dog"))
        self.assertTrue(_is_likely_name("Lesser Black Knife Assassin"))
        self.assertTrue(_is_likely_name("Lion Guardian"))

    def test_appendix_pattern_matches(self):
        self.assertIsNotNone(_APPENDIX_PATTERN.match("Appendix A"))
        self.assertIsNotNone(_APPENDIX_PATTERN.match("Appendices"))
        self.assertIsNotNone(_APPENDIX_PATTERN.match("Credits"))
        self.assertIsNotNone(_APPENDIX_PATTERN.match("Version History"))
        self.assertIsNotNone(_APPENDIX_PATTERN.match("Changelog"))

    def test_appendix_pattern_rejects_normal_headings(self):
        self.assertIsNone(_APPENDIX_PATTERN.match("Bridge of Sacrifice"))
        self.assertIsNone(_APPENDIX_PATTERN.match("1. Chapel"))

    def test_normalize_heading_text_handles_escaped_period(self):
        self.assertEqual(_normalize_heading_text("1\\. Chapel"), "1. Chapel")
        self.assertEqual(_normalize_heading_text("2\\. Tower"), "2. Tower")

    def test_normalize_heading_text_handles_no_escape(self):
        self.assertEqual(_normalize_heading_text("Bridge of Sacrifice"), "Bridge of Sacrifice")

    def test_heading_prefix_words_include_function_words(self):
        self.assertIn("gathered", _HEADING_PREFIX_WORDS)
        self.assertIn("around", _HEADING_PREFIX_WORDS)
        self.assertIn("across", _HEADING_PREFIX_WORDS)
        self.assertIn("through", _HEADING_PREFIX_WORDS)


class TestGuiStatusGuidanceContracts(unittest.TestCase):
    """Source-contract tests for GUI status/guidance behavior (Section 3).

    These verify that status strings emitted by the backend/protocol do not
    imply success for rejected/blocked/no-module states, and that MMG
    guidance is gated.
    """

    def test_blocked_status_is_not_success(self):
        """Blocked status details must not contain success markers."""
        from web.routes.toolkit_homebrew_routes import _get_canonical_accurate_ingest_phase
        phase = _get_canonical_accurate_ingest_phase(
            {"status": "blocked", "stage": "build", "pipeline_status": "blocked"}
        )
        self.assertEqual(phase, "blocked")
        self.assertNotEqual(phase, "completed")

    def test_rejected_status_is_not_success(self):
        """Rejected job maps to 'rejected' canonical phase, not 'completed'."""
        from web.routes.toolkit_homebrew_routes import _get_canonical_accurate_ingest_phase
        phase = _get_canonical_accurate_ingest_phase(
            {"status": "rejected", "stage": "build", "pipeline_status": "rejected"}
        )
        self.assertEqual(phase, "rejected")
        self.assertNotEqual(phase, "completed")

    def test_quarantined_status_is_not_success(self):
        from web.routes.toolkit_homebrew_routes import _get_canonical_accurate_ingest_phase
        phase = _get_canonical_accurate_ingest_phase(
            {"status": "quarantined", "stage": "pipeline", "quarantine_reason": "test"}
        )
        self.assertEqual(phase, "quarantined")
        self.assertNotEqual(phase, "completed")

    def test_not_publishable_status_does_not_imply_success(self):
        from web.routes.toolkit_homebrew_routes import _get_canonical_accurate_ingest_phase
        phase = _get_canonical_accurate_ingest_phase(
            {"status": "not_publishable", "stage": "finish", "pipeline_status": "not_publishable"}
        )
        self.assertEqual(phase, "not_publishable")
        self.assertNotEqual(phase, "completed")

    def test_awaiting_review_is_not_completed(self):
        from web.routes.toolkit_homebrew_routes import _get_canonical_accurate_ingest_phase
        phase = _get_canonical_accurate_ingest_phase(
            {"status": "awaiting_review", "stage": "review"}
        )
        self.assertEqual(phase, "awaiting_review")
        self.assertNotEqual(phase, "completed")

    def test_blocked_in_terminal_job_states(self):
        """Blocked is a terminal job state."""
        from web.routes.toolkit_homebrew_routes import _TERMINAL_JOB_STATES
        self.assertIn("blocked", _TERMINAL_JOB_STATES)

    def test_blocked_in_canonical_phases(self):
        """Blocked is a canonical accurate-ingest phase."""
        from web.routes.toolkit_homebrew_routes import _ACCURATE_INGEST_CANONICAL_PHASES
        self.assertIn("blocked", _ACCURATE_INGEST_CANONICAL_PHASES)

    def test_rejected_review_decision_not_success(self):
        """Rejected fidelity review must not render as success.

        The source contract: a job with status 'rejected' maps to canonical
        phase 'rejected', never 'completed'.  The frontend is expected to
        use this phase to select 'error' or 'warning' rendering, not 'success'.
        """
        from web.routes.toolkit_homebrew_routes import _get_canonical_accurate_ingest_phase
        phase = _get_canonical_accurate_ingest_phase(
            {"status": "rejected", "stage": "review", "pipeline_status": "rejected"}
        )
        self.assertEqual(phase, "rejected")
        self.assertNotEqual(phase, "completed")

    def test_blocked_build_status_in_canonical_phase(self):
        """Job with status blocked maps to canonical blocked phase."""
        from web.routes.toolkit_homebrew_routes import _get_canonical_accurate_ingest_phase
        phase = _get_canonical_accurate_ingest_phase(
            {"status": "blocked", "stage": "build_fidelity", "pipeline_status": "blocked"}
        )
        self.assertEqual(phase, "blocked")


if __name__ == "__main__":
    unittest.main()
