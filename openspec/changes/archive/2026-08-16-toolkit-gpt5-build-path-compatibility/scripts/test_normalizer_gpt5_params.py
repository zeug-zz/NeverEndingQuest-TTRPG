# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
Provider-free normalizer request-shape suite (change:
toolkit-gpt5-build-path-compatibility, task 2.1).

Runs ``normalize_homebrew_upload`` end-to-end with a recording mock client
and captures the FINAL kwargs of every Chat Completions create call inside
the normalizer (N1 section extraction, N2 identity adjudication, N3 plot
topology synthesis, N4 legacy one-shot normalization; N5 fidelity repair is
excluded by disabling the fidelity audit, matching the repo normalizer
suite). Asserts, per provider branch:

- Direct GPT-5 family (gpt-5.6-luna): every create call preserves the
  resolved model and the ``builders`` task profile (reasoning_effort and
  verbosity medium/medium), omits unsupported legacy temperature/top_p,
  and keeps the configured timeout and messages.
- Compatible non-GPT-5 (gpt-4.1-2025-04-14): every create call preserves
  the caller temperature intent (task temperature) with no GPT-5 profile
  keys.
- OpenRouter: every create call keeps the configured model, provider
  thinking/request fields from get_model_config, and compatible
  temperature, with no GPT-5 profile substitution.

Also adds a source contract that the normalizer spreads the shared helper
at exactly five create call sites and no longer passes direct legacy
sampling kwargs.

Provider-free: no live API, no credentials, no raw source persistence.
Transient workspaces use tempfile.TemporaryDirectory like the existing
repo normalizer suite (scripts/test_toolkit_homebrew_normalizer.py).
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

def _find_repo_root():
    candidate = os.path.dirname(os.path.abspath(__file__))
    while True:
        if os.path.isdir(os.path.join(candidate, "openspec")) and os.path.isfile(
            os.path.join(candidate, "config_template.py")
        ):
            return candidate
        parent = os.path.dirname(candidate)
        if parent == candidate:
            raise RuntimeError("Unable to locate NeverEndingQuest repository root")
        candidate = parent


_REPO_ROOT = _find_repo_root()
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

_CHANGE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FIXTURES_DIR = os.path.join(_CHANGE_DIR, "fixtures")
if _FIXTURES_DIR not in sys.path:
    sys.path.insert(0, _FIXTURES_DIR)

import build_request_fixture as bf
import utils.ai_client_factory as ai_client_factory
from utils.toolkit_homebrew_normalizer import normalize_homebrew_upload
from utils.toolkit_homebrew_upload_contract import ensure_workspace_placeholders

# Synthetic model ids mirroring the fixture module (task 1.2). DM_MAIN_MODEL
# is patched per branch so the tests are deterministic regardless of the
# current model_config assignment.
GPT5_DIRECT_MODEL = bf.GPT5_DIRECT_MODEL
NON_GPT5_DIRECT_MODEL = bf.NON_GPT5_DIRECT_MODEL

PREFLIGHT = {
    "source_readable": True,
    "structure_class": "unknown",
    "routing_outcome": "normalization_required",
    "ready": False,
    "can_auto_transform": False,
}

_SECTION_PAYLOAD = {
    "extracted_atoms": [
        {
            "type": "npc",
            "name": "Caretaker Noll",
            "summary": "Gravekeeper",
            "source_refs": [{"line_start": 1, "excerpt": "Noll guards"}],
        }
    ]
}

_IDENTITY_PAYLOAD = {"decisions": []}

_TOPOLOGY_PAYLOAD = {
    "plot_beats": [{"label": "Enter the crypt"}],
    "puzzle_chains": [],
    "clue_dependencies": [],
    "trials": [],
    "endings": [],
    "assumptions": [],
    "unresolved": [],
}

_LEGACY_PAYLOAD = {
    "title": "Crypt of Ash",
    "author": "Unknown",
    "description": "A short ruin crawl.",
    "estimated_level_min": 1,
    "estimated_level_max": 2,
    "locations": [{"name": "Ruined Gate", "summary": "Collapsed"}],
    "npc_seeds": [{"name": "Caretaker Noll", "role": "Guide"}],
    "monster_refs": ["Skeleton"],
    "assumptions": ["Author inferred from style clues."],
    "warnings": [{"type": "metadata_inferred", "message": "Author not explicit."}],
    "grounded_facts": ["The adventure references a crypt and gatehouse."],
    "builder_narrative": "Grounded builder summary.",
}

# One payload per create_chat_client() call in order: section, identity,
# topology, legacy one-shot. Fidelity audit is disabled in setUp so the
# repair call (N5) is not exercised here (covered by the dedicated
# TestNormalizerGPT5RepairBlock class below).
PAYLOADS = [_SECTION_PAYLOAD, _IDENTITY_PAYLOAD, _TOPOLOGY_PAYLOAD, _LEGACY_PAYLOAD]

# Expected timeout per create call index (N1-N3=90, N4 legacy=120).
EXPECTED_TIMEOUTS = [90, 90, 90, 120]

# --- N5 fidelity-repair block fixtures (task 4.1) ---------------------------
# The repair client returns one additive operation that passes
# validate_repair_operations: op type in _ALLOWED_REPAIR_OPS and
# source_atom_id matching a repairable finding.
_REPAIR_PAYLOAD = {
    "operations": [
        {
            "op": "add_location",
            "source_atom_id": "noll",
            "value": {
                "name": "Caretaker Noll",
                "role": "Guide",
                "summary": "Gravekeeper",
            },
        }
    ]
}

# Controlled fidelity audit reports. First call (initial audit) returns a
# degraded report with one repairable finding so the bounded repair loop
# fires the N5 create call; second call (re-audit) returns clean so the
# loop breaks after exactly one repair attempt.
_REPAIR_DEGRADED_REPORT = {
    "fidelity_report_version": "normalization_fidelity.v1",
    "status": "degraded",
    "reason": "test_repairable_gap",
    "findings": [
        {
            "source_atom_id": "noll",
            "repairable": True,
            "category": "missing",
            "severity": "blocking",
            "type": "npc",
            "message": "Npc seed missing from packet",
        }
    ],
    "summary": {
        "status": "degraded",
        "blocking_count": 1,
        "warning_count": 0,
        "info_count": 0,
        "covered_required": 0,
        "total_required": 1,
    },
}

_REPAIR_CLEAN_REPORT = {
    "fidelity_report_version": "normalization_fidelity.v1",
    "status": "clean",
    "reason": "",
    "findings": [],
    "summary": {
        "status": "clean",
        "blocking_count": 0,
        "warning_count": 0,
        "info_count": 0,
        "covered_required": 1,
        "total_required": 1,
    },
}


class _FakeChoice:
    def __init__(self, content):
        self.message = type("Msg", (), {"content": content})()


class _FakeResponse:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]


def _recording_client(payload):
    """Client whose create() records final kwargs and returns a JSON payload."""
    class _RecCompletions:
        def __init__(self):
            self.calls = []

        def create(self, **kwargs):
            self.calls.append(dict(kwargs))
            return _FakeResponse(json.dumps(payload))

    class _RecChat:
        def __init__(self):
            self.completions = _RecCompletions()

    class _RecClient:
        def __init__(self):
            self.chat = _RecChat()

    return _RecClient()


class TestNormalizerGPT5Params(unittest.TestCase):
    """Captured final kwargs of every normalizer create call per branch."""

    def setUp(self):
        import utils.toolkit_homebrew_normalizer as tn

        self.tn = tn
        self._orig_fid_audit = getattr(tn, "ENABLE_NORMALIZATION_FIDELITY_AUDIT", True)
        tn.ENABLE_NORMALIZATION_FIDELITY_AUDIT = False

    def tearDown(self):
        self.tn.ENABLE_NORMALIZATION_FIDELITY_AUDIT = self._orig_fid_audit

    def _run_normalization(self, dm_main_model, provider):
        """Run normalization with a recording client; return (result, calls)."""
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            ensure_workspace_placeholders(workspace)
            source_path = Path(tmp) / "source.md"
            source_path.write_text(
                "# Test Adventure\n\nA crypt and ruined gatehouse.",
                encoding="utf-8",
            )
            clients = [_recording_client(p) for p in PAYLOADS]
            with bf.forced_provider(provider[0], provider[1]), patch(
                "utils.toolkit_homebrew_normalizer.create_chat_client",
                side_effect=clients,
            ), patch(
                "utils.toolkit_homebrew_normalizer.DM_MAIN_MODEL", dm_main_model
            ):
                result = normalize_homebrew_upload(
                    source_path=source_path,
                    workspace=workspace,
                    preflight=PREFLIGHT,
                    source_rights_class="user_authored",
                )
            calls = []
            for client in clients:
                calls.extend(client.chat.completions.calls)
            return result, calls

    def test_gpt5_direct_requests_omit_legacy_sampling_and_keep_profile(self):
        result, calls = self._run_normalization(
            GPT5_DIRECT_MODEL, ("openai", False)
        )
        self.assertEqual(result.get("status"), "success")
        self.assertEqual(len(calls), 4, "expected section/identity/topology/legacy calls")
        for index, kwargs in enumerate(calls):
            with self.subTest(call_index=index):
                self.assertEqual(kwargs["model"], GPT5_DIRECT_MODEL)
                self.assertEqual(kwargs["reasoning_effort"], "medium")
                self.assertEqual(kwargs["verbosity"], "medium")
                self.assertNotIn("temperature", kwargs)
                self.assertNotIn("top_p", kwargs)
                self.assertEqual(len(kwargs["messages"]), 2)
                self.assertEqual(kwargs["timeout"], EXPECTED_TIMEOUTS[index])
                self.assertEqual(
                    set(kwargs.keys()),
                    {"model", "reasoning_effort", "verbosity", "messages", "timeout"},
                )

    def test_non_gpt5_requests_preserve_temperature_intent(self):
        with bf.forced_provider("openai", False):
            expected_temperature = ai_client_factory.get_model_config(
                "builders", NON_GPT5_DIRECT_MODEL
            )["temperature"]
        result, calls = self._run_normalization(
            NON_GPT5_DIRECT_MODEL, ("openai", False)
        )
        self.assertEqual(result.get("status"), "success")
        self.assertEqual(len(calls), 4)
        for index, kwargs in enumerate(calls):
            with self.subTest(call_index=index):
                self.assertEqual(kwargs["model"], NON_GPT5_DIRECT_MODEL)
                self.assertEqual(kwargs["temperature"], expected_temperature)
                self.assertNotIn("reasoning_effort", kwargs)
                self.assertNotIn("verbosity", kwargs)
                self.assertNotIn("top_p", kwargs)
                self.assertEqual(kwargs["timeout"], EXPECTED_TIMEOUTS[index])

    def test_openrouter_requests_preserve_thinking_shape(self):
        with bf.forced_provider("openrouter", True):
            expected = ai_client_factory.get_model_config(
                "builders", GPT5_DIRECT_MODEL
            )
        result, calls = self._run_normalization(
            GPT5_DIRECT_MODEL, ("openrouter", True)
        )
        self.assertEqual(result.get("status"), "success")
        self.assertEqual(len(calls), 4)
        for index, kwargs in enumerate(calls):
            with self.subTest(call_index=index):
                self.assertEqual(kwargs["model"], expected["model"])
                self.assertEqual(kwargs["temperature"], expected["temperature"])
                for key, value in (expected.get("extra_body") or {}).items():
                    self.assertEqual(
                        kwargs.get(key),
                        value,
                        "OpenRouter extra_body field %s must be preserved" % key,
                    )
                self.assertNotIn("reasoning_effort", kwargs)
                self.assertNotIn("verbosity", kwargs)
                self.assertEqual(kwargs["timeout"], EXPECTED_TIMEOUTS[index])


class TestNormalizerGPT5RepairBlock(unittest.TestCase):
    """N5 fidelity-repair create block: final kwargs captured end-to-end.

    Task 4.1: the existing four-call runs disable the fidelity audit, so the
    fifth create block (fidelity repair, inventory site N5 at
    utils/toolkit_homebrew_normalizer.py:905) was only source-covered. This
    class runs the full pipeline with the fidelity audit AND bounded repair
    enabled and a patched, deterministic audit (degraded -> clean), so the
    repair block fires exactly once and its final request kwargs are
    captured like every other block.
    """

    def setUp(self):
        import utils.toolkit_homebrew_normalizer as tn

        self.tn = tn
        self._orig_audit = getattr(tn, "ENABLE_NORMALIZATION_FIDELITY_AUDIT", True)
        self._orig_repair = getattr(tn, "ENABLE_NORMALIZATION_FIDELITY_REPAIR", True)
        self._orig_max = getattr(
            tn, "NORMALIZATION_FIDELITY_MAX_REPAIR_ATTEMPTS", 3
        )

    def tearDown(self):
        self.tn.ENABLE_NORMALIZATION_FIDELITY_AUDIT = self._orig_audit
        self.tn.ENABLE_NORMALIZATION_FIDELITY_REPAIR = self._orig_repair
        self.tn.NORMALIZATION_FIDELITY_MAX_REPAIR_ATTEMPTS = self._orig_max

    def _run_normalization_with_repair(self):
        """Run normalization with audit + repair; return (result, calls)."""
        self.tn.ENABLE_NORMALIZATION_FIDELITY_AUDIT = True
        self.tn.ENABLE_NORMALIZATION_FIDELITY_REPAIR = True
        self.tn.NORMALIZATION_FIDELITY_MAX_REPAIR_ATTEMPTS = 1
        payloads = PAYLOADS + [_REPAIR_PAYLOAD]
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            ensure_workspace_placeholders(workspace)
            source_path = Path(tmp) / "source.md"
            source_path.write_text(
                "# Test Adventure\n\nA crypt and ruined gatehouse.",
                encoding="utf-8",
            )
            clients = [_recording_client(p) for p in payloads]
            with bf.forced_provider("openai", False), patch(
                "utils.toolkit_homebrew_normalizer.create_chat_client",
                side_effect=clients,
            ), patch(
                "utils.toolkit_homebrew_normalizer.DM_MAIN_MODEL", GPT5_DIRECT_MODEL
            ), patch(
                "utils.toolkit_homebrew_normalizer.run_normalization_fidelity_audit",
                side_effect=[_REPAIR_DEGRADED_REPORT, _REPAIR_CLEAN_REPORT],
            ):
                result = normalize_homebrew_upload(
                    source_path=source_path,
                    workspace=workspace,
                    preflight=PREFLIGHT,
                    source_rights_class="user_authored",
                )
            calls = []
            for client in clients:
                calls.extend(client.chat.completions.calls)
            return result, calls

    def test_gpt5_repair_block_captures_profile_and_omits_legacy_sampling(self):
        result, calls = self._run_normalization_with_repair()
        self.assertEqual(result.get("status"), "success")
        self.assertEqual(
            len(calls),
            5,
            "expected section/identity/topology/legacy/repair calls",
        )
        expected_profile = ai_client_factory._resolve_gpt5_chat_profile("builders")
        expected_timeouts = EXPECTED_TIMEOUTS + [90]
        for index, kwargs in enumerate(calls):
            with self.subTest(call_index=index):
                self.assertEqual(kwargs["model"], GPT5_DIRECT_MODEL)
                for key, value in expected_profile.items():
                    self.assertEqual(kwargs[key], value)
                self.assertNotIn("temperature", kwargs)
                self.assertNotIn("top_p", kwargs)
                self.assertEqual(len(kwargs["messages"]), 2)
                self.assertEqual(kwargs["timeout"], expected_timeouts[index])

    def test_repair_block_preserves_repair_prompt_messages_and_timeout(self):
        result, calls = self._run_normalization_with_repair()
        self.assertEqual(result.get("status"), "success")
        self.assertEqual(len(calls), 5)
        repair_kwargs = calls[4]
        self.assertEqual(repair_kwargs["timeout"], 90)
        messages = repair_kwargs["messages"]
        self.assertEqual(len(messages), 2)
        self.assertEqual(
            messages[0]["content"],
            self.tn._load_fidelity_repair_prompt(),
        )
        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(messages[1]["role"], "user")
        self.assertIn("CURRENT_PACKET_KEYS", messages[1]["content"])
        self.assertIn("MISSING_FINDINGS", messages[1]["content"])
        self.assertNotIn("temperature", repair_kwargs)
        self.assertNotIn("top_p", repair_kwargs)

    def test_repair_block_resolves_profile_from_task_identity(self):
        _, calls = self._run_normalization_with_repair()
        repair_kwargs = calls[4]
        # The repair block must resolve its profile from the ``builders``
        # task identity, not from a global default.
        expected = ai_client_factory._resolve_gpt5_chat_profile("builders")
        for key, value in expected.items():
            self.assertEqual(repair_kwargs[key], value)
        self.assertEqual(repair_kwargs["reasoning_effort"], "medium")
        self.assertEqual(repair_kwargs["verbosity"], "medium")


class TestNormalizerHelperSourceContract(unittest.TestCase):
    """The normalizer spreads the shared helper at all five create sites."""

    def _source(self):
        return Path("utils/toolkit_homebrew_normalizer.py").read_text(
            encoding="utf-8"
        )

    def test_five_create_sites_spread_the_helper(self):
        source = self._source()
        self.assertEqual(source.count("**get_chat_completion_params("), 5)
        self.assertIn("get_chat_completion_params", source)

    def test_no_direct_legacy_sampling_kwargs_remain(self):
        source = self._source()
        for fragment in (
            "**section_config.get(\"extra_body\"",
            "**ident_config.get(\"extra_body\"",
            "**topo_config.get(\"extra_body\"",
            "**model_config.get(\"extra_body\"",
            "**repair_config.get(\"extra_body\"",
        ):
            with self.subTest(fragment=fragment):
                self.assertNotIn(fragment, source)
        for fragment in (
            "temperature=section_config.get(",
            "temperature=ident_config.get(",
            "temperature=topo_config.get(",
            "temperature=model_config.get(",
            "temperature=repair_config.get(",
        ):
            with self.subTest(fragment=fragment):
                self.assertNotIn(fragment, source)


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
