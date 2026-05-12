#!/usr/bin/env python3
"""Regression tests for toolkit Homebrew normalization service."""

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parents[1]))

from utils.toolkit_homebrew_normalizer import normalize_homebrew_upload
from utils.toolkit_homebrew_upload_contract import (
    ensure_workspace_placeholders,
    load_section_extraction_artifact,
    persist_section_extraction_artifact,
)


# ---------------------------------------------------------------------------
#  Shared fake infrastructure
# ---------------------------------------------------------------------------
class _FakeChoice:
    def __init__(self, content):
        self.message = type("Msg", (), {"content": content})()


class _FakeResponse:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]


class _FakeCompletions:
    def __init__(self, content):
        self._content = content

    def create(self, **kwargs):
        return _FakeResponse(self._content)


class _FakeChat:
    def __init__(self, content):
        self.completions = _FakeCompletions(content)


class _FakeClient:
    def __init__(self, content):
        self.chat = _FakeChat(content)


# Captured .create(**kwargs) calls for sequenced fake clients
_CAPTURED = []


def _single_shot_fake(payload):
    """Factory returning a fake client that produces one response or raises."""
    class _ShotCompletions:
        def create(self, **kwargs):
            _CAPTURED.append(kwargs)
            if isinstance(payload, Exception):
                raise payload
            content = json.dumps(payload) if isinstance(payload, dict) else str(payload)
            return _FakeResponse(content)

    class _ShotClient:
        def __init__(self):
            self.chat = type("Chat", (), {"completions": _ShotCompletions()})()

    return _ShotClient()


# ---------------------------------------------------------------------------
#  Payload builders
# ---------------------------------------------------------------------------
def _tiny_section_payload():
    return {
        "extracted_atoms": [
            {
                "type": "npc",
                "name": "Caretaker Noll",
                "summary": "Gravekeeper",
                "source_refs": [{"line_start": 1, "excerpt": "Noll guards"}],
            }
        ]
    }


def _tiny_identity_payload():
    return {"decisions": []}


def _tiny_topology_payload():
    return {
        "plot_beats": [{"label": "Enter the crypt"}],
        "puzzle_chains": [],
        "clue_dependencies": [],
        "trials": [],
        "endings": [],
        "assumptions": [],
        "unresolved": [],
    }


def _full_legacy_payload():
    return {
        "title": "Crypt of Ash",
        "author": "Unknown",
        "description": "A short ruin crawl.",
        "estimated_level_min": 1,
        "estimated_level_max": 2,
        "locations": [
            {"name": "Ruined Gate", "summary": "Collapsed outer wall"},
        ],
        "npc_seeds": [{"name": "Caretaker Noll", "role": "Guide"}],
        "monster_refs": ["Skeleton"],
        "assumptions": ["Author inferred from style clues."],
        "warnings": [{"type": "metadata_inferred", "message": "Author not explicit."}],
        "grounded_facts": ["The adventure references a crypt and gatehouse."],
        "builder_narrative": "Grounded builder summary.",
    }


def _sparse_legacy_payload():
    return {
        "title": "Crypt of Ash",
        "author": "Unknown",
        "description": "A short ruin crawl.",
        "narrative": "Players explore a ruined crypt.",
        "builder_narrative": "Grounded builder summary.",
    }


# ---------------------------------------------------------------------------
#  Tests
# ---------------------------------------------------------------------------
class TestToolkitHomebrewNormalizer(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name) / "workspace"
        ensure_workspace_placeholders(self.workspace)
        self.source_path = Path(self.temp_dir.name) / "source.md"
        self.source_path.write_text(
            "# Test Adventure\n\nA crypt and ruined gatehouse.",
            encoding="utf-8",
        )
        self.preflight = {
            "source_readable": True,
            "structure_class": "unknown",
            "routing_outcome": "normalization_required",
            "ready": False,
            "can_auto_transform": False,
        }
        # Disable fidelity audit for multipass tests (they mock exact call counts)
        import utils.toolkit_homebrew_normalizer as tn
        self._orig_fid_audit = getattr(tn, "ENABLE_NORMALIZATION_FIDELITY_AUDIT", True)
        tn.ENABLE_NORMALIZATION_FIDELITY_AUDIT = False

    def tearDown(self):
        import utils.toolkit_homebrew_normalizer as tn
        tn.ENABLE_NORMALIZATION_FIDELITY_AUDIT = self._orig_fid_audit
        self.temp_dir.cleanup()

    # --- Legacy tests (preserved) ---

    @patch("utils.toolkit_homebrew_normalizer.get_model_config")
    @patch("utils.toolkit_homebrew_normalizer.create_chat_client")
    def test_successful_normalization_persists_artifacts(self, mock_client_factory, mock_model_config):
        payload = _full_legacy_payload()
        mock_client_factory.return_value = _FakeClient(json.dumps(payload))
        mock_model_config.return_value = {
            "model": "fake-model",
            "temperature": 0.3,
            "extra_body": {},
        }

        result = normalize_homebrew_upload(
            source_path=self.source_path,
            workspace=self.workspace,
            preflight=self.preflight,
            source_rights_class="user_authored",
        )

        self.assertEqual(result.get("status"), "success")
        packet_path = self.workspace / "normalized_packet.json"
        report_path = self.workspace / "normalization_report.json"
        narrative_path = self.workspace / "builder_narrative.txt"
        self.assertTrue(packet_path.exists())
        self.assertTrue(report_path.exists())
        self.assertTrue(narrative_path.exists())

        packet = json.loads(packet_path.read_text(encoding="utf-8"))
        self.assertEqual(packet.get("normalization_state"), "normalized")
        self.assertEqual(packet.get("title"), "Crypt of Ash")
        self.assertEqual(
            packet.get("confidence_notes", {}).get("grounded_facts", [])[0],
            "The adventure references a crypt and gatehouse.",
        )
        self.assertGreater(len(packet.get("assumptions", [])), 0)

    @patch("utils.toolkit_homebrew_normalizer.get_model_config")
    @patch("utils.toolkit_homebrew_normalizer.create_chat_client")
    def test_malformed_model_output_fails_closed(self, mock_client_factory, mock_model_config):
        mock_client_factory.return_value = _FakeClient("This is not JSON")
        mock_model_config.return_value = {
            "model": "fake-model",
            "temperature": 0.3,
            "extra_body": {},
        }

        result = normalize_homebrew_upload(
            source_path=self.source_path,
            workspace=self.workspace,
            preflight=self.preflight,
            source_rights_class="user_authored",
        )

        self.assertEqual(result.get("status"), "failed")
        self.assertEqual(result.get("stage"), "normalizing")
        self.assertIn("invalid_json", str(result.get("error")))
        self.assertIn("source_graph_degraded", result)
        self.assertIn("source_graph", result)

        report = json.loads(
            (self.workspace / "normalization_report.json").read_text(encoding="utf-8")
        )
        self.assertEqual(report.get("status"), "failed")
        self.assertIn("source_graph_degraded", report)
        self.assertIn("source_graph", report)

    @patch("utils.toolkit_homebrew_normalizer.get_model_config")
    @patch("utils.toolkit_homebrew_normalizer.create_chat_client")
    def test_provider_failure_keeps_source_graph_status(self, mock_client_factory, mock_model_config):
        class _BoomClient:
            class _BoomChat:
                class _BoomCompletions:
                    @staticmethod
                    def create(**kwargs):
                        raise RuntimeError("provider boom")

                def __init__(self):
                    self.completions = self._BoomCompletions()

            def __init__(self):
                self.chat = self._BoomChat()

        mock_client_factory.return_value = _BoomClient()
        mock_model_config.return_value = {
            "model": "fake-model",
            "temperature": 0.3,
            "extra_body": {},
        }

        result = normalize_homebrew_upload(
            source_path=self.source_path,
            workspace=self.workspace,
            preflight=self.preflight,
            source_rights_class="user_authored",
        )

        self.assertEqual(result.get("status"), "failed")
        self.assertIn("source_graph_degraded", result)
        self.assertIn("source_graph", result)

        report = json.loads(
            (self.workspace / "normalization_report.json").read_text(encoding="utf-8")
        )
        self.assertEqual(report.get("status"), "failed")
        self.assertIn("source_graph_degraded", report)
        self.assertIn("source_graph", report)

    @patch("utils.toolkit_homebrew_normalizer.get_model_config")
    @patch("utils.toolkit_homebrew_normalizer.create_chat_client")
    @patch("utils.toolkit_homebrew_normalizer.persist_builder_narrative_artifact")
    def test_persistence_failure_rewrites_report_as_failed(
        self,
        mock_narrative_persist,
        mock_client_factory,
        mock_model_config,
    ):
        payload = {
            "title": "Crypt of Ash",
            "description": "A short ruin crawl.",
            "locations": [{"name": "Ruined Gate"}],
        }
        mock_narrative_persist.return_value = False
        mock_client_factory.return_value = _FakeClient(json.dumps(payload))
        mock_model_config.return_value = {
            "model": "fake-model",
            "temperature": 0.3,
            "extra_body": {},
        }

        result = normalize_homebrew_upload(
            source_path=self.source_path,
            workspace=self.workspace,
            preflight=self.preflight,
            source_rights_class="user_authored",
        )

        self.assertEqual(result.get("status"), "failed")
        report = json.loads(
            (self.workspace / "normalization_report.json").read_text(encoding="utf-8")
        )
        self.assertEqual(report.get("status"), "failed")
        self.assertEqual(report.get("error"), "normalization_artifact_persistence_failed")
        self.assertFalse(report.get("builder_narrative_persisted"))

    # --- Multipass orchestration tests ---

    def _make_multipass_model_config(self):
        return patch(
            "utils.toolkit_homebrew_normalizer.get_model_config",
            return_value={
                "model": "fake-model",
                "temperature": 0.2,
                "extra_body": {},
            },
        )

    @patch("utils.toolkit_homebrew_normalizer.get_model_config")
    @patch("utils.toolkit_homebrew_normalizer.create_chat_client")
    def test_multipass_success_calls_section_identity_topology_and_synthesizes_packet(
        self, mock_client_factory, mock_model_config
    ):
        mock_model_config.return_value = {
            "model": "fake-model",
            "temperature": 0.2,
            "extra_body": {},
        }
        global _CAPTURED
        _CAPTURED = []
        mock_client_factory.side_effect = [
            _single_shot_fake(_tiny_section_payload()),
            _single_shot_fake(_tiny_identity_payload()),
            _single_shot_fake(_tiny_topology_payload()),
            _single_shot_fake(_full_legacy_payload()),
        ]

        result = normalize_homebrew_upload(
            source_path=self.source_path,
            workspace=self.workspace,
            preflight=self.preflight,
            source_rights_class="user_authored",
        )

        self.assertEqual(result.get("status"), "success")
        self.assertEqual(mock_client_factory.call_count, 4)

        # All multipass artifacts must exist
        index_path = self.workspace / "section_extractions" / "index.json"
        identity_path = self.workspace / "identity_resolution_report.json"
        topology_path = self.workspace / "plot_topology_report.json"
        synthesis_path = self.workspace / "source_graph_synthesis_report.json"
        packet_path = self.workspace / "normalized_packet.json"
        report_path = self.workspace / "normalization_report.json"
        self.assertTrue(index_path.exists(), "section_extractions/index.json missing")
        self.assertTrue(identity_path.exists(), "identity_resolution_report.json missing")
        self.assertTrue(topology_path.exists(), "plot_topology_report.json missing")
        self.assertTrue(synthesis_path.exists(), "source_graph_synthesis_report.json missing")
        self.assertTrue(packet_path.exists())
        self.assertTrue(report_path.exists())

        report = json.loads(report_path.read_text(encoding="utf-8"))
        mp = report.get("multipass")
        self.assertIsNotNone(mp)
        self.assertTrue(mp.get("enabled"))
        self.assertFalse(mp.get("degraded"))

    @patch("utils.toolkit_homebrew_normalizer.get_model_config")
    @patch("utils.toolkit_homebrew_normalizer.create_chat_client")
    def test_section_cache_hit_skips_section_provider_call(
        self, mock_client_factory, mock_model_config
    ):
        mock_model_config.return_value = {
            "model": "fake-model",
            "temperature": 0.2,
            "extra_body": {},
        }
        # Pre-populate cache by running the normalizer once with all 4 providers,
        # then run again with only 3 providers and verify section call was skipped.
        global _CAPTURED
        _CAPTURED = []

        # First run: create all section artifacts
        mock_client_factory.side_effect = [
            _single_shot_fake(_tiny_section_payload()),
            _single_shot_fake(_tiny_identity_payload()),
            _single_shot_fake(_tiny_topology_payload()),
            _single_shot_fake(_full_legacy_payload()),
        ]
        result1 = normalize_homebrew_upload(
            source_path=self.source_path,
            workspace=self.workspace,
            preflight=self.preflight,
            source_rights_class="user_authored",
        )
        self.assertEqual(result1.get("status"), "success")

        # Second run: should use cache for section extraction
        mock_client_factory.reset_mock()
        mock_client_factory.side_effect = [
            _single_shot_fake(_tiny_identity_payload()),
            _single_shot_fake(_tiny_topology_payload()),
            _single_shot_fake(_full_legacy_payload()),
        ]

        result = normalize_homebrew_upload(
            source_path=self.source_path,
            workspace=self.workspace,
            preflight=self.preflight,
            source_rights_class="user_authored",
        )

        self.assertEqual(result.get("status"), "success")
        # 3 calls: identity, topology, legacy (section skipped via cache)
        self.assertEqual(mock_client_factory.call_count, 3)

        report = json.loads(
            (self.workspace / "normalization_report.json").read_text(encoding="utf-8")
        )
        mp = report.get("multipass")
        self.assertIsNotNone(mp)
        self.assertEqual(mp.get("cached_sections"), 1)

    @patch("utils.toolkit_homebrew_normalizer.get_model_config")
    @patch("utils.toolkit_homebrew_normalizer.create_chat_client")
    def test_section_cache_source_hash_mismatch_reextracts(
        self, mock_client_factory, mock_model_config
    ):
        mock_model_config.return_value = {
            "model": "fake-model",
            "temperature": 0.2,
            "extra_body": {},
        }
        # First run: populate cache with correct source_hash
        global _CAPTURED
        _CAPTURED = []
        mock_client_factory.side_effect = [
            _single_shot_fake(_tiny_section_payload()),
            _single_shot_fake(_tiny_identity_payload()),
            _single_shot_fake(_tiny_topology_payload()),
            _single_shot_fake(_full_legacy_payload()),
        ]
        result0 = normalize_homebrew_upload(
            source_path=self.source_path,
            workspace=self.workspace,
            preflight=self.preflight,
            source_rights_class="user_authored",
        )
        self.assertEqual(result0.get("status"), "success")

        # Second run: overwrite cache with WRONG source_hash, section should re-extract
        sec_id = "S001"
        sec_dir = self.workspace / "section_extractions"
        cached = load_section_extraction_artifact(self.workspace, sec_id)
        self.assertIsNotNone(cached)
        cached["source_hash"] = "WRONG"
        sec_dir.mkdir(parents=True, exist_ok=True)
        (sec_dir / f"{sec_id}.json").write_text(json.dumps(cached), encoding="utf-8")

        _CAPTURED = []
        mock_client_factory.reset_mock()
        mock_client_factory.side_effect = [
            _single_shot_fake(_tiny_section_payload()),
            _single_shot_fake(_tiny_identity_payload()),
            _single_shot_fake(_tiny_topology_payload()),
            _single_shot_fake(_full_legacy_payload()),
        ]

        result = normalize_homebrew_upload(
            source_path=self.source_path,
            workspace=self.workspace,
            preflight=self.preflight,
            source_rights_class="user_authored",
        )

        self.assertEqual(result.get("status"), "success")
        # 4 calls: section re-extracted due to mismatched source_hash
        self.assertEqual(mock_client_factory.call_count, 4)

    @patch("utils.toolkit_homebrew_normalizer.get_model_config")
    @patch("utils.toolkit_homebrew_normalizer.create_chat_client")
    def test_malformed_section_payload_records_degraded_not_success(
        self, mock_client_factory, mock_model_config
    ):
        mock_model_config.return_value = {
            "model": "fake-model",
            "temperature": 0.2,
            "extra_body": {},
        }
        global _CAPTURED
        _CAPTURED = []
        # Section provider returns valid JSON but missing extracted_atoms
        bad_section = {"wrong": "shape", "no_extracted_atoms": True}
        mock_client_factory.side_effect = [
            _single_shot_fake(bad_section),
            _single_shot_fake(_tiny_identity_payload()),
            _single_shot_fake(_tiny_topology_payload()),
            _single_shot_fake(_full_legacy_payload()),
        ]

        result = normalize_homebrew_upload(
            source_path=self.source_path,
            workspace=self.workspace,
            preflight=self.preflight,
            source_rights_class="user_authored",
        )

        self.assertEqual(result.get("status"), "success")
        report = json.loads(
            (self.workspace / "normalization_report.json").read_text(encoding="utf-8")
        )
        mp = report.get("multipass")
        self.assertIsNotNone(mp)
        self.assertTrue(mp.get("degraded"))
        self.assertEqual(mp.get("degraded_sections"), 1)

        # Check section artifact status
        cached = load_section_extraction_artifact(self.workspace, "S001")
        self.assertIsNotNone(cached)
        self.assertEqual(cached.get("status"), "degraded")
        self.assertIn("invalid_section_extraction_shape", cached.get("error", ""))

    @patch("utils.toolkit_homebrew_normalizer.get_model_config")
    @patch("utils.toolkit_homebrew_normalizer.create_chat_client")
    def test_identity_provider_failure_degrades_but_normalization_succeeds(
        self, mock_client_factory, mock_model_config
    ):
        mock_model_config.return_value = {
            "model": "fake-model",
            "temperature": 0.2,
            "extra_body": {},
        }
        global _CAPTURED
        _CAPTURED = []
        mock_client_factory.side_effect = [
            _single_shot_fake(_tiny_section_payload()),
            _single_shot_fake(RuntimeError("identity boom")),
            _single_shot_fake(_tiny_topology_payload()),
            _single_shot_fake(_full_legacy_payload()),
        ]

        result = normalize_homebrew_upload(
            source_path=self.source_path,
            workspace=self.workspace,
            preflight=self.preflight,
            source_rights_class="user_authored",
        )

        self.assertEqual(result.get("status"), "success")
        report = json.loads(
            (self.workspace / "normalization_report.json").read_text(encoding="utf-8")
        )
        mp = report.get("multipass")
        self.assertIsNotNone(mp)
        self.assertTrue(mp.get("identity_degraded"))

    @patch("utils.toolkit_homebrew_normalizer.get_model_config")
    @patch("utils.toolkit_homebrew_normalizer.create_chat_client")
    def test_topology_provider_failure_degrades_but_normalization_succeeds(
        self, mock_client_factory, mock_model_config
    ):
        mock_model_config.return_value = {
            "model": "fake-model",
            "temperature": 0.2,
            "extra_body": {},
        }
        global _CAPTURED
        _CAPTURED = []
        mock_client_factory.side_effect = [
            _single_shot_fake(_tiny_section_payload()),
            _single_shot_fake(_tiny_identity_payload()),
            _single_shot_fake(RuntimeError("topology boom")),
            _single_shot_fake(_full_legacy_payload()),
        ]

        result = normalize_homebrew_upload(
            source_path=self.source_path,
            workspace=self.workspace,
            preflight=self.preflight,
            source_rights_class="user_authored",
        )

        self.assertEqual(result.get("status"), "success")
        report = json.loads(
            (self.workspace / "normalization_report.json").read_text(encoding="utf-8")
        )
        mp = report.get("multipass")
        self.assertIsNotNone(mp)
        self.assertTrue(mp.get("topology_degraded"))

    @patch("utils.toolkit_homebrew_normalizer.ENABLE_ACCURATE_INGEST_MULTI_PASS", False)
    @patch("utils.toolkit_homebrew_normalizer.get_model_config")
    @patch("utils.toolkit_homebrew_normalizer.create_chat_client")
    def test_multipass_disabled_uses_legacy_only(
        self, mock_client_factory, mock_model_config
    ):
        mock_model_config.return_value = {
            "model": "fake-model",
            "temperature": 0.3,
            "extra_body": {},
        }
        mock_client_factory.return_value = _FakeClient(json.dumps(_full_legacy_payload()))

        result = normalize_homebrew_upload(
            source_path=self.source_path,
            workspace=self.workspace,
            preflight=self.preflight,
            source_rights_class="user_authored",
        )

        self.assertEqual(result.get("status"), "success")
        # Only legacy call
        self.assertEqual(mock_client_factory.call_count, 1)

        report = json.loads(
            (self.workspace / "normalization_report.json").read_text(encoding="utf-8")
        )
        mp = report.get("multipass")
        self.assertIsNotNone(mp)
        self.assertFalse(mp.get("enabled"))

        # Multipass artifacts should NOT exist
        index_path = self.workspace / "section_extractions" / "index.json"
        identity_path = self.workspace / "identity_resolution_report.json"
        self.assertFalse(index_path.exists())
        self.assertFalse(identity_path.exists())

    @patch("utils.toolkit_homebrew_normalizer.get_model_config")
    @patch("utils.toolkit_homebrew_normalizer.create_chat_client")
    @patch("utils.toolkit_homebrew_normalizer.persist_identity_resolution_artifact")
    def test_multipass_artifact_persistence_failure_marks_degraded(
        self, mock_identity_persist, mock_client_factory, mock_model_config
    ):
        mock_model_config.return_value = {
            "model": "fake-model",
            "temperature": 0.2,
            "extra_body": {},
        }
        mock_identity_persist.return_value = False
        global _CAPTURED
        _CAPTURED = []
        mock_client_factory.side_effect = [
            _single_shot_fake(_tiny_section_payload()),
            _single_shot_fake(_tiny_identity_payload()),
            _single_shot_fake(_tiny_topology_payload()),
            _single_shot_fake(_full_legacy_payload()),
        ]

        result = normalize_homebrew_upload(
            source_path=self.source_path,
            workspace=self.workspace,
            preflight=self.preflight,
            source_rights_class="user_authored",
        )

        self.assertEqual(result.get("status"), "success")
        report = json.loads(
            (self.workspace / "normalization_report.json").read_text(encoding="utf-8")
        )
        mp = report.get("multipass")
        self.assertIsNotNone(mp)
        self.assertTrue(mp.get("artifact_persistence_degraded"))
        self.assertTrue(mp.get("degraded"))

    @patch("utils.toolkit_homebrew_normalizer.get_model_config")
    @patch("utils.toolkit_homebrew_normalizer.create_chat_client")
    def test_synthesized_packet_path_used_when_legacy_payload_omits_arrays(
        self, mock_client_factory, mock_model_config
    ):
        mock_model_config.return_value = {
            "model": "fake-model",
            "temperature": 0.2,
            "extra_body": {},
        }
        global _CAPTURED
        _CAPTURED = []
        mock_client_factory.side_effect = [
            _single_shot_fake(_tiny_section_payload()),
            _single_shot_fake(_tiny_identity_payload()),
            _single_shot_fake(_tiny_topology_payload()),
            _single_shot_fake(_sparse_legacy_payload()),
        ]

        result = normalize_homebrew_upload(
            source_path=self.source_path,
            workspace=self.workspace,
            preflight=self.preflight,
            source_rights_class="user_authored",
        )

        self.assertEqual(result.get("status"), "success")
        packet = json.loads(
            (self.workspace / "normalized_packet.json").read_text(encoding="utf-8")
        )
        # Packet was synthesized via multipass path
        self.assertEqual(packet.get("normalization_state"), "normalized")
        self.assertEqual(packet.get("title"), "Crypt of Ash")


if __name__ == "__main__":
    unittest.main(verbosity=2)
