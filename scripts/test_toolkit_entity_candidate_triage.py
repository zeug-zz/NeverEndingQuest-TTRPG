"""
Contract tests for toolkit_entity_candidate_triage helper.
"""

import json
import sys
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.toolkit_entity_candidate_triage import (
    TRIAGE_DECISIONS,
    TRIAGE_TYPES,
    NON_ACTOR_TYPES,
    ACTOR_TYPES,
    TRIAGE_REPORT_STATUSES,
    TRIAGE_REPORT_VERSION,
    DECISION_KEEP,
    DECISION_REJECT,
    DECISION_RECLASSIFY,
    TYPE_TRUE_NPC,
    TYPE_SCENE_ACTOR,
    TYPE_MONSTER_ACTOR,
    TYPE_ITEM_OR_CLUE,
    TYPE_LOCATION_NAME,
    TYPE_FACTION_NAME,
    TYPE_PLOT_NOTE,
    TYPE_TONE_MARKER,
    TYPE_NARRATIVE_PHRASE,
    TYPE_UNKNOWN,
    TRIAGE_REPORT_STATUS_PASS,
    TRIAGE_REPORT_STATUS_DEGRADED,
    TRIAGE_REPORT_STATUS_FAILED,
    TRIAGE_REPORT_STATUS_SKIPPED,
    validate_decision,
    validate_adjudicated_type,
    validate_report_status,
    is_non_actor_decision,
    is_actor_decision,
    is_rejected,
    is_kept,
    build_triage_decision,
    is_underbound_npc,
    build_entity_candidate_triage_report,
    looks_like_narrative_phrase,
    build_prefilter_decision,
    build_underbound_npc_findings,
)

from utils.toolkit_homebrew_upload_contract import (
    get_workspace_files,
    persist_entity_candidate_triage_artifact,
    load_entity_candidate_triage_artifact,
)


class TestTriageConstants(unittest.TestCase):
    """Verify bounded constants exist and have expected shapes."""

    def test_triage_decisions_are_bounded(self):
        self.assertIn(DECISION_KEEP, TRIAGE_DECISIONS)
        self.assertIn(DECISION_REJECT, TRIAGE_DECISIONS)
        self.assertIn(DECISION_RECLASSIFY, TRIAGE_DECISIONS)
        self.assertEqual(len(TRIAGE_DECISIONS), 3)

    def test_triage_types_are_bounded(self):
        for t in (
            TYPE_TRUE_NPC, TYPE_SCENE_ACTOR, TYPE_MONSTER_ACTOR,
            TYPE_ITEM_OR_CLUE, TYPE_LOCATION_NAME, TYPE_FACTION_NAME,
            TYPE_PLOT_NOTE, TYPE_TONE_MARKER, TYPE_NARRATIVE_PHRASE,
            TYPE_UNKNOWN,
        ):
            self.assertIn(t, TRIAGE_TYPES)

    def test_non_actor_types_separate_from_actor_types(self):
        self.assertTrue(NON_ACTOR_TYPES.isdisjoint(ACTOR_TYPES))

    def test_report_statuses_are_bounded(self):
        for s in (
            TRIAGE_REPORT_STATUS_PASS,
            TRIAGE_REPORT_STATUS_DEGRADED,
            TRIAGE_REPORT_STATUS_FAILED,
            TRIAGE_REPORT_STATUS_SKIPPED,
        ):
            self.assertIn(s, TRIAGE_REPORT_STATUSES)

    def test_report_version_defined(self):
        self.assertIsInstance(TRIAGE_REPORT_VERSION, str)
        self.assertTrue(TRIAGE_REPORT_VERSION.startswith("entity_candidate_triage_report.v"))


class TestValidateHelpers(unittest.TestCase):
    """Test validate_decision, validate_adjudicated_type, validate_report_status."""

    def test_valid_decision_pass(self):
        self.assertTrue(validate_decision(DECISION_KEEP))
        self.assertTrue(validate_decision(DECISION_REJECT))
        self.assertTrue(validate_decision(DECISION_RECLASSIFY))

    def test_invalid_decision_fails(self):
        self.assertFalse(validate_decision(""))
        self.assertFalse(validate_decision("maybe"))
        self.assertFalse(validate_decision(None))  # type: ignore
        self.assertFalse(validate_decision(123))  # type: ignore

    def test_valid_adjudicated_type_pass(self):
        self.assertTrue(validate_adjudicated_type(TYPE_TRUE_NPC))
        self.assertTrue(validate_adjudicated_type(TYPE_NARRATIVE_PHRASE))

    def test_invalid_adjudicated_type_fails(self):
        self.assertFalse(validate_adjudicated_type(""))
        self.assertFalse(validate_adjudicated_type("ghost_type"))

    def test_valid_report_status_pass(self):
        self.assertTrue(validate_report_status(TRIAGE_REPORT_STATUS_PASS))
        self.assertTrue(validate_report_status(TRIAGE_REPORT_STATUS_DEGRADED))

    def test_invalid_report_status_fails(self):
        self.assertFalse(validate_report_status(""))
        self.assertFalse(validate_report_status("unknown"))


class TestBuildTriageDecision(unittest.TestCase):
    """Test build_triage_decision creates correct dict shapes."""

    def setUp(self):
        self.valid_kwargs: Dict[str, Any] = {
            "candidate_text": "but this is not true",
            "candidate_slug": "but_this_is_not_true",
            "proposed_type": "npc",
            "adjudicated_type": TYPE_NARRATIVE_PHRASE,
            "decision": DECISION_REJECT,
            "reason": "Prose assertion about Shuluth's fabricated mindscape.",
        }

    def test_valid_narrative_phrase_decision(self):
        d = build_triage_decision(**self.valid_kwargs)
        self.assertEqual(d["candidate_text"], "but this is not true")
        self.assertEqual(d["candidate_slug"], "but_this_is_not_true")
        self.assertEqual(d["proposed_type"], "npc")
        self.assertEqual(d["adjudicated_type"], TYPE_NARRATIVE_PHRASE)
        self.assertEqual(d["decision"], DECISION_REJECT)
        self.assertEqual(d["reason"], self.valid_kwargs["reason"])
        self.assertNotIn("source_refs", d)

    def test_valid_kept_npc_decision_with_bindings(self):
        d = build_triage_decision(
            candidate_text="Dog-Growl",
            candidate_slug="dog_growl",
            proposed_type="npc",
            adjudicated_type=TYPE_TRUE_NPC,
            decision=DECISION_KEEP,
            reason="Named Kenku resident of The Rookery.",
            location_bindings=["The Rookery"],
            source_role="Kenku composer using Shuluth-taught Qualith",
        )
        self.assertEqual(d["candidate_text"], "Dog-Growl")
        self.assertEqual(d["location_bindings"], ["The Rookery"])
        self.assertEqual(d["source_role"], "Kenku composer using Shuluth-taught Qualith")

    def test_valid_reclassified_decision(self):
        d = build_triage_decision(
            candidate_text="shadowy figure",
            candidate_slug="shadowy_figure",
            proposed_type="npc",
            adjudicated_type=TYPE_SCENE_ACTOR,
            decision=DECISION_RECLASSIFY,
            reason="Ambiguous description, not a named NPC.",
        )
        self.assertEqual(d["decision"], DECISION_RECLASSIFY)
        self.assertEqual(d["adjudicated_type"], TYPE_SCENE_ACTOR)

    def test_empty_candidate_text_raises(self):
        with self.assertRaises(ValueError):
            build_triage_decision(
                candidate_text="",
                candidate_slug="x",
                proposed_type="npc",
                adjudicated_type=TYPE_TRUE_NPC,
                decision=DECISION_KEEP,
                reason="test",
            )

    def test_invalid_decision_raises(self):
        with self.assertRaises(ValueError):
            build_triage_decision(
                candidate_text="test",
                candidate_slug="test",
                proposed_type="npc",
                adjudicated_type=TYPE_TRUE_NPC,
                decision="invalid",
                reason="test",
            )

    def test_invalid_adjudicated_type_raises(self):
        with self.assertRaises(ValueError):
            build_triage_decision(
                candidate_text="test",
                candidate_slug="test",
                proposed_type="npc",
                adjudicated_type="ghost_type",
                decision=DECISION_REJECT,
                reason="test",
            )


class TestPredicateHelpers(unittest.TestCase):
    """Test is_rejected, is_kept, is_non_actor_decision, is_actor_decision, is_underbound_npc."""

    def test_is_rejected_returns_true(self):
        d = build_triage_decision(
            candidate_text="x", candidate_slug="x",
            proposed_type="npc", adjudicated_type=TYPE_NARRATIVE_PHRASE,
            decision=DECISION_REJECT, reason="test",
        )
        self.assertTrue(is_rejected(d))

    def test_is_kept_returns_true(self):
        d = build_triage_decision(
            candidate_text="x", candidate_slug="x",
            proposed_type="npc", adjudicated_type=TYPE_TRUE_NPC,
            decision=DECISION_KEEP, reason="test",
        )
        self.assertTrue(is_kept(d))

    def test_non_actor_decision_detected(self):
        for t in NON_ACTOR_TYPES:
            d = build_triage_decision(
                candidate_text="x", candidate_slug="x",
                proposed_type="npc", adjudicated_type=t,
                decision=DECISION_RECLASSIFY, reason="test",
            )
            self.assertTrue(is_non_actor_decision(d))
            self.assertFalse(is_actor_decision(d))

    def test_actor_decision_detected(self):
        for t in ACTOR_TYPES:
            d = build_triage_decision(
                candidate_text="x", candidate_slug="x",
                proposed_type="npc", adjudicated_type=t,
                decision=DECISION_KEEP, reason="test",
            )
            self.assertTrue(is_actor_decision(d))
            self.assertFalse(is_non_actor_decision(d))

    def test_underbound_npc_kept_true_npc_no_bindings(self):
        d = build_triage_decision(
            candidate_text="x", candidate_slug="x",
            proposed_type="npc", adjudicated_type=TYPE_TRUE_NPC,
            decision=DECISION_KEEP, reason="test",
        )
        self.assertTrue(is_underbound_npc(d))

    def test_underbound_npc_kept_true_npc_with_bindings(self):
        d = build_triage_decision(
            candidate_text="x", candidate_slug="x",
            proposed_type="npc", adjudicated_type=TYPE_TRUE_NPC,
            decision=DECISION_KEEP, reason="test",
            location_bindings=["The Rookery"],
        )
        self.assertFalse(is_underbound_npc(d))

    def test_underbound_npc_only_true_for_kept_true_npc(self):
        d = build_triage_decision(
            candidate_text="x", candidate_slug="x",
            proposed_type="npc", adjudicated_type=TYPE_SCENE_ACTOR,
            decision=DECISION_KEEP, reason="test",
        )
        self.assertFalse(is_underbound_npc(d))

    def test_underbound_npc_rejected_is_not_underbound(self):
        d = build_triage_decision(
            candidate_text="x", candidate_slug="x",
            proposed_type="npc", adjudicated_type=TYPE_NARRATIVE_PHRASE,
            decision=DECISION_REJECT, reason="test",
        )
        self.assertFalse(is_underbound_npc(d))


class TestTriageReportBuilder(unittest.TestCase):
    """Test build_entity_candidate_triage_report output shape and counts."""

    def _make_npc_decision(self, slug, decision, adj_type, bindings=None):
        kwargs = dict(
            candidate_text=slug.replace("_", " "),
            candidate_slug=slug,
            proposed_type="npc",
            adjudicated_type=adj_type,
            decision=decision,
            reason="test reason",
        )
        if bindings:
            kwargs["location_bindings"] = bindings
        return build_triage_decision(**kwargs)

    def test_empty_decisions_report(self):
        report = build_entity_candidate_triage_report([])
        self.assertEqual(report["triage_report_version"], TRIAGE_REPORT_VERSION)
        self.assertEqual(report["status"], TRIAGE_REPORT_STATUS_PASS)
        self.assertEqual(report["total_candidates"], 0)
        self.assertEqual(report["summary"]["kept"], 0)
        self.assertEqual(report["summary"]["rejected"], 0)
        self.assertEqual(report["summary"]["reclassified"], 0)
        self.assertEqual(report["summary"]["non_actor"], 0)
        self.assertEqual(report["summary"]["underbound_npcs"], 0)
        self.assertEqual(report["type_counts"], {})
        self.assertEqual(report["decisions"], [])

    def test_report_with_mixed_decisions(self):
        decisions = [
            self._make_npc_decision("dog_growl", DECISION_KEEP, TYPE_TRUE_NPC, ["The Rookery"]),
            self._make_npc_decision("book_shut", DECISION_KEEP, TYPE_TRUE_NPC, ["The Rookery"]),
            self._make_npc_decision("deflation", DECISION_KEEP, TYPE_TRUE_NPC, ["The Rookery"]),
            self._make_npc_decision("but_this_is_not_true", DECISION_REJECT, TYPE_NARRATIVE_PHRASE),
            self._make_npc_decision("shadowy_figure", DECISION_RECLASSIFY, TYPE_SCENE_ACTOR),
        ]
        report = build_entity_candidate_triage_report(decisions)
        self.assertEqual(report["total_candidates"], 5)
        self.assertEqual(report["summary"]["kept"], 3)
        self.assertEqual(report["summary"]["rejected"], 1)
        self.assertEqual(report["summary"]["reclassified"], 1)
        self.assertEqual(report["summary"]["non_actor"], 1)
        self.assertEqual(report["summary"]["underbound_npcs"], 0)
        self.assertIn(TYPE_TRUE_NPC, report["type_counts"])
        self.assertEqual(report["type_counts"][TYPE_TRUE_NPC], 3)
        self.assertEqual(report["type_counts"][TYPE_NARRATIVE_PHRASE], 1)
        self.assertEqual(report["type_counts"][TYPE_SCENE_ACTOR], 1)

    def test_report_with_underbound_npc(self):
        decisions = [
            self._make_npc_decision("underbound_npc", DECISION_KEEP, TYPE_TRUE_NPC),
        ]
        report = build_entity_candidate_triage_report(decisions)
        self.assertEqual(report["summary"]["underbound_npcs"], 1)

    def test_report_with_warnings_and_blockers(self):
        report = build_entity_candidate_triage_report(
            [],
            status=TRIAGE_REPORT_STATUS_DEGRADED,
            warnings=[{"message": "some warnings"}],
            blockers=[{"reason": "some blockers"}],
        )
        self.assertEqual(report["status"], TRIAGE_REPORT_STATUS_DEGRADED)
        self.assertIn("warnings", report)
        self.assertIn("blockers", report)

    def test_invalid_report_status_raises(self):
        with self.assertRaises(ValueError):
            build_entity_candidate_triage_report([], status="invalid")

    def test_report_json_serializable(self):
        decisions = [
            self._make_npc_decision("dog_growl", DECISION_KEEP, TYPE_TRUE_NPC, ["The Rookery"]),
            self._make_npc_decision("but_this_is_not_true", DECISION_REJECT, TYPE_NARRATIVE_PHRASE),
        ]
        report = build_entity_candidate_triage_report(decisions)
        serialized = json.dumps(report, ensure_ascii=True)
        parsed = json.loads(serialized)
        self.assertEqual(parsed["total_candidates"], 2)
        self.assertEqual(parsed["summary"]["kept"], 1)
        self.assertEqual(parsed["summary"]["rejected"], 1)

    def test_report_source_role_counts_as_binding(self):
        d = build_triage_decision(
            candidate_text="Dog-Growl",
            candidate_slug="dog_growl",
            proposed_type="npc",
            adjudicated_type=TYPE_TRUE_NPC,
            decision=DECISION_KEEP,
            reason="Named Kenku resident.",
            source_role="Kenku composer",
        )
        report = build_entity_candidate_triage_report([d])
        self.assertEqual(report["summary"]["underbound_npcs"], 0)


class TestLooksLikeNarrativePhrase(unittest.TestCase):
    """Test deterministic prefilter narrative phrase detection."""

    def test_but_this_is_not_true_detected(self):
        self.assertTrue(looks_like_narrative_phrase("but this is not true"))

    def test_start_uppercase_not_narrative(self):
        self.assertFalse(looks_like_narrative_phrase("Dog-Growl"))
        self.assertFalse(looks_like_narrative_phrase("Book-shut"))
        self.assertFalse(looks_like_narrative_phrase("Deflation"))
        self.assertFalse(looks_like_narrative_phrase("The Rookery"))

    def test_hyphenated_uppercase_names_not_narrative(self):
        self.assertFalse(looks_like_narrative_phrase("Will-o'-Wisp"))
        self.assertFalse(looks_like_narrative_phrase("Scout Kira"))

    def test_common_prose_conjunctions_detected(self):
        for phrase in (
            "but the guards are nowhere to be seen",
            "yet the party does not know",
            "however the truth is hidden",
            "although the door is locked",
            "there is a hidden passage",
            "this is not what it seems",
            "it was a dark and stormy night",
            "the figure disappears into mist",
        ):
            self.assertTrue(looks_like_narrative_phrase(phrase))

    def test_simple_npc_names_not_narrative(self):
        for name in (
            "shadowy figure",
            "old man",
            "mysterious stranger",
            "captain",
            "innkeeper",
        ):
            self.assertFalse(looks_like_narrative_phrase(name))

    def test_empty_text_not_narrative(self):
        self.assertFalse(looks_like_narrative_phrase(""))

    def test_single_lowercase_word_not_narrative(self):
        self.assertFalse(looks_like_narrative_phrase("goblin"))
        self.assertFalse(looks_like_narrative_phrase("skeleton"))


class TestBuildPrefilterDecision(unittest.TestCase):
    """Test build_prefilter_decision creates correct decisions."""

    def test_narrative_phrase_returns_reject_decision(self):
        candidate = {
            "candidate_text": "but this is not true",
            "candidate_slug": "but_this_is_not_true",
            "proposed_type": "npc",
        }
        decision = build_prefilter_decision(candidate)
        self.assertIsNotNone(decision)
        self.assertEqual(decision["decision"], DECISION_REJECT)
        self.assertEqual(decision["adjudicated_type"], TYPE_NARRATIVE_PHRASE)

    def test_valid_npc_returns_none(self):
        for text, slug in [
            ("Dog-Growl", "dog_growl"),
            ("Book-shut", "book_shut"),
            ("Deflation", "deflation"),
        ]:
            candidate = {
                "candidate_text": text,
                "candidate_slug": slug,
                "proposed_type": "npc",
            }
            self.assertIsNone(build_prefilter_decision(candidate))

    def test_empty_candidate_returns_none(self):
        self.assertIsNone(build_prefilter_decision({}))
        self.assertIsNone(build_prefilter_decision({"candidate_text": ""}))
        self.assertIsNone(build_prefilter_decision({"candidate_text": "test"}))

    def test_prefiltered_decision_uses_build_triage_decision_schema(self):
        candidate = {
            "candidate_text": "but this is not true",
            "candidate_slug": "but_this_is_not_true",
            "proposed_type": "npc",
        }
        decision = build_prefilter_decision(candidate)
        self.assertIn("candidate_text", decision)
        self.assertIn("candidate_slug", decision)
        self.assertIn("adjudicated_type", decision)
        self.assertIn("decision", decision)
        self.assertIn("reason", decision)


class TestBuildUnderboundNpcFindings(unittest.TestCase):
    """Test build_underbound_npc_findings output."""

    def _make_decisions(self, specs):
        results = []
        for spec in specs:
            kwargs = dict(
                candidate_text=spec["text"],
                candidate_slug=spec["slug"],
                proposed_type="npc",
                adjudicated_type=spec.get("adj_type", TYPE_TRUE_NPC),
                decision=spec.get("decision", DECISION_KEEP),
                reason="test",
            )
            if spec.get("bindings"):
                kwargs["location_bindings"] = spec["bindings"]
            if spec.get("source_role"):
                kwargs["source_role"] = spec["source_role"]
            results.append(build_triage_decision(**kwargs))
        return results

    def test_underbound_npc_produces_warning(self):
        decisions = self._make_decisions([
            {"text": "Underbound", "slug": "underbound"},
        ])
        findings = build_underbound_npc_findings(decisions)
        self.assertEqual(len(findings["warnings"]), 1)
        self.assertEqual(len(findings["blockers"]), 0)
        self.assertIn("Underbound", findings["warnings"][0]["finding"])

    def test_bound_npc_no_finding(self):
        decisions = self._make_decisions([
            {"text": "Dog-Growl", "slug": "dog_growl", "bindings": ["The Rookery"]},
        ])
        findings = build_underbound_npc_findings(decisions)
        self.assertEqual(len(findings["warnings"]), 0)
        self.assertEqual(len(findings["blockers"]), 0)

    def test_source_role_counts_as_binding(self):
        decisions = self._make_decisions([
            {"text": "Composer", "slug": "composer", "source_role": "Kenku composer"},
        ])
        findings = build_underbound_npc_findings(decisions)
        self.assertEqual(len(findings["warnings"]), 0)

    def test_rejected_npc_not_flagged(self):
        decisions = self._make_decisions([
            {
                "text": "but this is not true",
                "slug": "but_this_is_not_true",
                "adj_type": TYPE_NARRATIVE_PHRASE,
                "decision": DECISION_REJECT,
            },
        ])
        findings = build_underbound_npc_findings(decisions)
        self.assertEqual(len(findings["warnings"]), 0)

    def test_mixed_decisions_correct_counts(self):
        decisions = self._make_decisions([
            {"text": "Bound1", "slug": "bound1", "bindings": ["LocationA"]},
            {"text": "Unbound1", "slug": "unbound1"},
            {"text": "Bound2", "slug": "bound2", "bindings": ["LocationB"]},
            {"text": "Unbound2", "slug": "unbound2"},
        ])
        findings = build_underbound_npc_findings(decisions)
        self.assertEqual(len(findings["warnings"]), 2)
        self.assertEqual(len(findings["blockers"]), 0)
        self.assertIn("unbound1", findings["warnings"][0]["candidate_slug"])
        self.assertIn("unbound2", findings["warnings"][1]["candidate_slug"])

    def test_empty_decisions(self):
        findings = build_underbound_npc_findings([])
        self.assertEqual(len(findings["warnings"]), 0)
        self.assertEqual(len(findings["blockers"]), 0)


class TestWorkspaceArtifactKey(unittest.TestCase):
    """Test workspace artifact key exists in contract."""

    def test_entity_candidate_triage_report_key_exists(self):
        files = get_workspace_files(Path("/tmp/test_workspace"))
        self.assertIn("entity_candidate_triage_report", files)
        self.assertEqual(
            files["entity_candidate_triage_report"].name,
            "entity_candidate_triage_report.json",
        )


class TestTriageArtifactPersistence(unittest.TestCase):
    """Test persist/load helpers for entity candidate triage report."""

    def setUp(self):
        self._tmpdir = Path(tempfile.mkdtemp(prefix="triage_artifact_test_"))

    def tearDown(self):
        import shutil
        shutil.rmtree(str(self._tmpdir), ignore_errors=True)

    def test_persist_and_load_round_trip(self):
        report = build_entity_candidate_triage_report(
            decisions=[], status=TRIAGE_REPORT_STATUS_PASS
        )
        ok = persist_entity_candidate_triage_artifact(self._tmpdir, report)
        self.assertTrue(ok)

        loaded = load_entity_candidate_triage_artifact(self._tmpdir)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["status"], TRIAGE_REPORT_STATUS_PASS)

    def test_load_missing_returns_none(self):
        result = load_entity_candidate_triage_artifact(Path("/nonexistent/path"))
        self.assertIsNone(result)

    def test_persist_writes_valid_json(self):
        report = build_entity_candidate_triage_report(
            decisions=[], status=TRIAGE_REPORT_STATUS_PASS, warnings=None, blockers=None
        )
        ok = persist_entity_candidate_triage_artifact(self._tmpdir, report)
        self.assertTrue(ok)

        target = get_workspace_files(self._tmpdir)["entity_candidate_triage_report"]
        self.assertTrue(target.exists())

        raw = target.read_text(encoding="utf-8")
        parsed = json.loads(raw)
        self.assertEqual(parsed["total_candidates"], 0)


class TestNormalizerTriageIntegration(unittest.TestCase):
    """Source-contract tests: normalizer imports and uses triage helpers."""

    def test_normalizer_imports_persist_entity_candidate_triage(self):
        from utils.toolkit_homebrew_normalizer import (
            persist_entity_candidate_triage_artifact as imported,
        )
        self.assertTrue(callable(imported))

    def test_normalizer_imports_triage_helpers(self):
        from utils.toolkit_homebrew_normalizer import (
            build_entity_candidate_triage_report as report_import,
            build_prefilter_decision as prefilter_import,
            build_underbound_npc_findings as findings_import,
        )
        self.assertTrue(callable(report_import))
        self.assertTrue(callable(prefilter_import))
        self.assertTrue(callable(findings_import))

    def test_normalizer_source_contains_entity_candidate_triage_call(self):
        source = Path("utils/toolkit_homebrew_normalizer.py").read_text(encoding="utf-8")
        self.assertIn("persist_entity_candidate_triage_artifact", source)
        self.assertIn("build_entity_candidate_triage_report", source)
        self.assertIn("build_prefilter_decision", source)
        self.assertIn("entity_candidate_triage_report", source)

    def test_blueprint_call_passes_triage_report(self):
        """Step 2.2: normalizer must pass triage_report to generate_builder_blueprint_v2."""
        source = Path("utils/toolkit_homebrew_normalizer.py").read_text(encoding="utf-8")
        self.assertIn("triage_report=bp_artifacts.get(\"entity_candidate_triage_report\")", source)
