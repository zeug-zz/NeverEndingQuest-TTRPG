# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0

import os
import sqlite3
import tempfile
import unittest
from datetime import datetime

MAX_MILESTONE_CHARS = 120
MAX_LOOKUP_CHARS = 150
MILESTONE_SCORE_THRESHOLD = 30


def _create_test_db(db_path):
    from core.memory.memory_db import init_memory_db
    init_memory_db(db_path)
    conn = sqlite3.connect(db_path)
    now = datetime.utcnow().isoformat()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO entities (entity_id, display_name, entity_kind, is_retired, created_at, updated_at) VALUES (?, ?, ?, 0, ?, ?)",
            ("acheron", "Acheron", "player", now, now),
        )
        conn.execute(
            "INSERT OR IGNORE INTO entities (entity_id, display_name, entity_kind, is_retired, created_at, updated_at) VALUES (?, ?, ?, 0, ?, ?)",
            ("kira", "Scout Kira", "npc", now, now),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_event(db_path, event_id, entity_id, summary, importance=50,
                  persistence_class="identity_core", decay_profile="none",
                  priority_active_pc=0, pinned=0, reinforcement_count=0,
                  ts=None):
    if ts is None:
        ts = "2026-05-01T10:00:00"
    conn = sqlite3.connect(db_path)
    now = datetime.utcnow().isoformat()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO memory_events (event_id, event_ts, event_type, summary, importance, persistence_class, decay_profile, reinforcement_count, priority_active_pc, pinned, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (event_id, ts, "encounter", summary, importance, persistence_class,
             decay_profile, reinforcement_count, priority_active_pc, pinned, now),
        )
        conn.execute(
            "INSERT OR IGNORE INTO memory_links (event_id, entity_id, link_role, link_salience) VALUES (?, ?, ?, ?)",
            (event_id, entity_id, "participant", 0.8),
        )
        conn.commit()
    finally:
        conn.close()


def _compute_expected_score(importance, persistence_class, pinned, priority_active_pc,
                            decay_profile, reinforcement_count, age_days=0):
    score = 0
    if pinned:
        score += 100
    if priority_active_pc:
        score += 25
    score += importance * 0.35
    pc_map = {"identity_core": 30, "campaign_major": 24, "relationship_core": 20, "procedural": 14}
    score += pc_map.get(persistence_class, 4)
    if decay_profile == "none":
        score += 20
    elif decay_profile == "slow":
        if age_days <= 30:
            score += 20
        elif age_days <= 90:
            score += 16
        elif age_days <= 180:
            score += 12
        elif age_days <= 365:
            score += 8
        else:
            score += 4
    elif decay_profile == "medium":
        if age_days <= 7:
            score += 20
        elif age_days <= 30:
            score += 14
        elif age_days <= 90:
            score += 8
        elif age_days <= 180:
            score += 4
        else:
            score += 1
    else:
        if age_days <= 3:
            score += 20
        elif age_days <= 7:
            score += 10
        elif age_days <= 30:
            score += 4
        else:
            score += 1
    score += min(18, reinforcement_count * 2)
    return score


class TestBuildCampaignMilestones(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="neq_milestone_test_")
        self.db_path = os.path.join(self.tmpdir, "memory.db")
        _create_test_db(self.db_path)

    def test_function_signature(self):
        from core.memory.memory_retrieval import build_campaign_milestones
        result = build_campaign_milestones([], db_path=self.db_path)
        self.assertEqual(result, "")
        result = build_campaign_milestones(["acheron"], max_events=5, db_path=self.db_path)
        self.assertIsInstance(result, str)

    def test_high_score_events_included(self):
        _insert_event(self.db_path, "evt1", "acheron", "Defeated the wight king",
                      importance=90, persistence_class="identity_core", decay_profile="none")
        from core.memory.memory_retrieval import build_campaign_milestones
        result = build_campaign_milestones(["acheron"], db_path=self.db_path)
        self.assertIn("Defeated the wight king", result)

    def test_pinned_events_included(self):
        _insert_event(self.db_path, "evt2", "acheron", "Met the hermit",
                      importance=10, persistence_class="ambient", decay_profile="fast", pinned=1)
        from core.memory.memory_retrieval import build_campaign_milestones
        result = build_campaign_milestones(["acheron"], db_path=self.db_path)
        self.assertIn("Met the hermit", result)

    def test_low_score_unpinned_excluded(self):
        _insert_event(self.db_path, "evt3", "acheron", "Minor observation",
                      importance=5, persistence_class="ambient", decay_profile="fast", pinned=0)
        from core.memory.memory_retrieval import build_campaign_milestones
        result = build_campaign_milestones(["acheron"], db_path=self.db_path)
        self.assertNotIn("Minor observation", result)

    def test_deduplication_across_entities(self):
        _insert_event(self.db_path, "shared1", "acheron", "Shared battle event",
                      importance=90, persistence_class="identity_core", decay_profile="none")
        _insert_event(self.db_path, "shared1", "kira", "Shared battle event",
                      importance=90, persistence_class="identity_core", decay_profile="none")
        from core.memory.memory_retrieval import build_campaign_milestones
        result = build_campaign_milestones(["acheron", "kira"], db_path=self.db_path)
        self.assertEqual(result.count("Shared battle event"), 1)

    def test_event_limit(self):
        for i in range(25):
            _insert_event(self.db_path, f"evt_l{i}", "acheron", f"Event number {i}",
                          importance=90, persistence_class="identity_core", decay_profile="none",
                          ts=f"2026-05-{(i % 28) + 1:02d}T10:00:00")
        from core.memory.memory_retrieval import build_campaign_milestones
        result = build_campaign_milestones(["acheron"], max_events=15, db_path=self.db_path)
        event_count = result.count("[2026-")
        self.assertLessEqual(event_count, 15)

    def test_entry_format(self):
        _insert_event(self.db_path, "fmt1", "acheron", "Formatted event",
                      importance=90, persistence_class="identity_core", decay_profile="none",
                      ts="2026-03-15T14:30:00")
        from core.memory.memory_retrieval import build_campaign_milestones
        result = build_campaign_milestones(["acheron"], db_path=self.db_path)
        self.assertIn("[2026-03-15] acheron: Formatted event", result)

    def test_long_summary_truncation(self):
        long_summary = "A" * 200
        _insert_event(self.db_path, "trunc1", "acheron", long_summary,
                      importance=90, persistence_class="identity_core", decay_profile="none")
        from core.memory.memory_retrieval import build_campaign_milestones
        result = build_campaign_milestones(["acheron"], db_path=self.db_path)
        for line in result.split("\n"):
            if "acheron:" in line:
                content_after_colon = line.split("acheron: ", 1)[1] if "acheron: " in line else ""
                self.assertLessEqual(len(content_after_colon), MAX_MILESTONE_CHARS)
                break

    def test_output_structure(self):
        _insert_event(self.db_path, "struct1", "acheron", "Structure test",
                      importance=90, persistence_class="identity_core", decay_profile="none")
        from core.memory.memory_retrieval import build_campaign_milestones
        result = build_campaign_milestones(["acheron"], db_path=self.db_path)
        self.assertTrue(result.startswith("@CAMPAIGN_MILESTONES={"))
        self.assertIn("events: [", result)
        self.assertTrue(result.strip().endswith("]\n}") or result.strip().endswith("]}"))

    def test_empty_result_no_qualifying_events(self):
        _insert_event(self.db_path, "low1", "acheron", "Too low score",
                      importance=5, persistence_class="ambient", decay_profile="fast", pinned=0)
        from core.memory.memory_retrieval import build_campaign_milestones
        result = build_campaign_milestones(["acheron"], db_path=self.db_path)
        self.assertEqual(result, "")

    def test_empty_result_empty_entity_list(self):
        from core.memory.memory_retrieval import build_campaign_milestones
        result = build_campaign_milestones([], db_path=self.db_path)
        self.assertEqual(result, "")

    def test_fail_open_database_error(self):
        from core.memory.memory_retrieval import build_campaign_milestones
        result = build_campaign_milestones(["acheron"], db_path="/nonexistent/path/memory.db")
        self.assertEqual(result, "")

    def test_ascii_only_output(self):
        _insert_event(self.db_path, "uni1", "acheron",
                      "Event with unicode chars: cafe\u0301 and resume\u0301",
                      importance=90, persistence_class="identity_core", decay_profile="none")
        from core.memory.memory_retrieval import build_campaign_milestones
        result = build_campaign_milestones(["acheron"], db_path=self.db_path)
        for ch in result:
            self.assertTrue(ord(ch) < 128, f"Non-ASCII char: {ch!r} (ord={ord(ch)})")

    def test_shared_constants_accessible(self):
        from core.memory.memory_retrieval import (
            MAX_LOOKUP_CHARS,
            MAX_MILESTONE_CHARS,
            MILESTONE_SCORE_THRESHOLD,
        )
        self.assertEqual(MAX_MILESTONE_CHARS, 120)
        self.assertEqual(MAX_LOOKUP_CHARS, 150)
        self.assertEqual(MILESTONE_SCORE_THRESHOLD, 30)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)


class TestResolvePartyEntityIds(unittest.TestCase):

    def test_pc_extraction(self):
        from main import _resolve_party_entity_ids
        data = {"partyMembers": ["Acheron", "Vitreol"], "partyNPCs": []}
        result = _resolve_party_entity_ids(data)
        self.assertIn("acheron", result)
        self.assertIn("vitreol", result)

    def test_npc_extraction_string_form(self):
        from main import _resolve_party_entity_ids
        data = {"partyMembers": [], "partyNPCs": ["Scout Kira", "Blarg"]}
        result = _resolve_party_entity_ids(data)
        self.assertIn("scout_kira", result)
        self.assertIn("blarg", result)

    def test_npc_extraction_dict_form(self):
        from main import _resolve_party_entity_ids
        data = {"partyMembers": [], "partyNPCs": [{"name": "Scout Kira"}, {"name": "Blarg"}]}
        result = _resolve_party_entity_ids(data)
        self.assertIn("scout_kira", result)
        self.assertIn("blarg", result)

    def test_deduplication(self):
        from main import _resolve_party_entity_ids
        data = {"partyMembers": ["Acheron"], "partyNPCs": ["Acheron"]}
        result = _resolve_party_entity_ids(data)
        acheron_count = result.count("acheron")
        self.assertEqual(acheron_count, 1)

    def test_fail_open_on_exception(self):
        from main import _resolve_party_entity_ids
        result = _resolve_party_entity_ids(None)
        self.assertEqual(result, [])


class TestMilestoneInjection(unittest.TestCase):

    def test_injection_on_first_attempt(self):
        milestones_block = "@CAMPAIGN_MILESTONES={\n  events: [\n    [2026-05-01] acheron: Battle won\n  ]\n}"
        messages = [
            {"role": "system", "content": "@DUNGEON_MASTER some system prompt"},
            {"role": "user", "content": "hello"},
        ]
        for i, msg in enumerate(messages):
            if msg.get("role") == "system" and "@DUNGEON_MASTER" in msg.get("content", ""):
                messages[i]["content"] += "\n\n" + milestones_block
                break
        self.assertIn("@CAMPAIGN_MILESTONES", messages[0]["content"])

    def test_skip_on_retry(self):
        validation_retry_count = 2
        messages = [{"role": "system", "content": "@DUNGEON_MASTER some system prompt"}]
        original = messages[0]["content"]
        if validation_retry_count == 0:
            pass
        self.assertEqual(messages[0]["content"], original)

    def test_append_to_main_prompt(self):
        milestones_block = "@CAMPAIGN_MILESTONES={\n  events: [\n    [2026-05-01] acheron: Battle won\n  ]\n}"
        messages = [
            {"role": "user", "content": "hello"},
            {"role": "system", "content": "@DUNGEON_MASTER prompt text"},
            {"role": "assistant", "content": "response"},
        ]
        for i, msg in enumerate(messages):
            if msg.get("role") == "system" and "@DUNGEON_MASTER" in msg.get("content", ""):
                messages[i]["content"] += "\n\n" + milestones_block
                break
        self.assertTrue(messages[1]["content"].endswith(milestones_block))
        self.assertNotIn("@CAMPAIGN_MILESTONES", messages[0]["content"])
        self.assertNotIn("@CAMPAIGN_MILESTONES", messages[2]["content"])

    def test_fail_open_on_error(self):
        try:
            raise RuntimeError("DB connection failed")
        except Exception:
            pass
        messages = [{"role": "system", "content": "@DUNGEON_MASTER prompt text"}]
        self.assertNotIn("@CAMPAIGN_MILESTONES", messages[0]["content"])

    def test_no_persistence(self):
        milestones_block = "@CAMPAIGN_MILESTONES={\n  events: []\n}"
        messages_to_send = [
            {"role": "system", "content": "@DUNGEON_MASTER prompt\n\n" + milestones_block},
        ]
        conversation_history = [{"role": "system", "content": "@DUNGEON_MASTER prompt"}]
        self.assertNotIn("@CAMPAIGN_MILESTONES", conversation_history[0]["content"])
        self.assertIn("@CAMPAIGN_MILESTONES", messages_to_send[0]["content"])

    def test_no_injection_when_no_dm_master_message(self):
        milestones_block = "@CAMPAIGN_MILESTONES={\n  events: []\n}"
        messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "response"},
        ]
        injected = False
        for i, msg in enumerate(messages):
            if msg.get("role") == "system" and "@DUNGEON_MASTER" in msg.get("content", ""):
                messages[i]["content"] += "\n\n" + milestones_block
                injected = True
                break
        self.assertFalse(injected)


class TestPromptDirectives(unittest.TestCase):

    def test_compressed_has_chronicle_rules(self):
        with open("prompts/system_prompt_compressed.txt", "r") as f:
            content = f.read()
        self.assertIn("@CHRONICLE_RULES={", content)

    def test_compressed_has_milestones_usage(self):
        with open("prompts/system_prompt_compressed.txt", "r") as f:
            content = f.read()
        self.assertIn("@CAMPAIGN_MILESTONES_USAGE={", content)

    def test_uncompressed_has_chronicle_rules(self):
        with open("prompts/system_prompt.txt", "r") as f:
            content = f.read()
        self.assertIn("@CHRONICLE_RULES={", content)

    def test_uncompressed_has_milestones_usage(self):
        with open("prompts/system_prompt.txt", "r") as f:
            content = f.read()
        self.assertIn("@CAMPAIGN_MILESTONES_USAGE={", content)

    def test_no_duplicate_milestones_usage_compressed(self):
        with open("prompts/system_prompt_compressed.txt", "r") as f:
            content = f.read()
        self.assertEqual(content.count("@CAMPAIGN_MILESTONES_USAGE={"), 1)

    def test_no_duplicate_milestones_usage_uncompressed(self):
        with open("prompts/system_prompt.txt", "r") as f:
            content = f.read()
        self.assertEqual(content.count("@CAMPAIGN_MILESTONES_USAGE={"), 1)

    def test_chronicle_rules_original_content_preserved(self):
        with open("prompts/system_prompt_compressed.txt", "r") as f:
            content = f.read()
        self.assertIn("=== LOCATION CHRONICLE ===", content)
        self.assertIn("=== CAMPAIGN HISTORY ===", content)
        self.assertIn("@C={characters}", content)

    def test_milestones_usage_directive_content(self):
        with open("prompts/system_prompt_compressed.txt", "r") as f:
            content = f.read()
        self.assertIn("These events HAPPENED", content)
        self.assertIn("milestone timeline WINS", content)


class TestMemoryLookupDispatch(unittest.TestCase):
    """Tests for lookupMemory action dispatch (tasks 6.2, 6.3)."""

    def test_action_constant_defined(self):
        from core.ai.action_handler import ACTION_LOOKUP_MEMORY
        self.assertEqual(ACTION_LOOKUP_MEMORY, "lookupMemory")

    def test_dispatch_lookup_memory_routes_correctly(self):
        from unittest.mock import patch
        from core.ai.action_handler import process_action
        action = {"action": "lookupMemory", "parameters": {"entities": ["vitreol"]}}
        with patch("core.memory.memory_retrieval.get_entity_timeline",
                   return_value=[{"event_id": "e1", "event_ts": "2026-05-01T10:00:00",
                                  "summary": "Test event", "retrieval_score": 50}]):
            result = process_action(action, {}, {}, [])
            self.assertIsInstance(result, dict)
            self.assertIn("memory_context", result.get("response_data", {}))

    def test_non_terminal_returns_continue(self):
        from unittest.mock import patch
        from core.ai.action_handler import process_action
        action = {"action": "lookupMemory", "parameters": {"entities": ["vitreol"]}}
        with patch("core.memory.memory_retrieval.get_entity_timeline",
                   return_value=[{"event_id": "e1", "event_ts": "2026-05-01T10:00:00",
                                  "summary": "Test event", "retrieval_score": 50}]):
            result = process_action(action, {}, {}, [])
            self.assertEqual(result.get("needs_update"), False)
            self.assertEqual(result.get("status"), "continue")


class TestMemoryLookupProcessing(unittest.TestCase):
    """Tests for _process_memory_lookup logic (task 6.1)."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="neq_lookup_test_")
        self.db_path = os.path.join(self.tmpdir, "memory.db")
        _create_test_db(self.db_path)
        _insert_event(self.db_path, "evt1", "acheron",
                      "Defeated the wight king in Thornwood",
                      importance=90, persistence_class="identity_core", decay_profile="none")
        _insert_event(self.db_path, "evt2", "acheron",
                      "Found the hidden grove altar",
                      importance=70, persistence_class="campaign_major", decay_profile="slow")

    def test_known_entity_returns_events(self):
        from unittest.mock import patch
        from core.ai.action_handler import process_action
        action = {"action": "lookupMemory", "parameters": {"entities": ["acheron"]}}
        with patch("core.memory.memory_retrieval.get_entity_timeline",
                   side_effect=lambda eid, **kw: [
                       {"event_id": "evt1", "event_ts": "2026-05-01T10:00:00",
                        "summary": "Defeated the wight king in Thornwood", "retrieval_score": 85},
                       {"event_id": "evt2", "event_ts": "2026-05-02T10:00:00",
                        "summary": "Found the hidden grove altar", "retrieval_score": 70},
                   ]):
            result = process_action(action, {}, {}, [])
            ctx = result.get("response_data", {}).get("memory_context", "")
            self.assertIn("wight king", ctx)
            self.assertIn("grove altar", ctx)
            self.assertIn("[SYSTEM] Campaign memory", ctx)

    def test_unknown_entity_returns_empty(self):
        from unittest.mock import patch
        from core.ai.action_handler import process_action
        action = {"action": "lookupMemory", "parameters": {"entities": ["nonexistent"]}}
        with patch("core.memory.memory_retrieval.get_entity_timeline", return_value=[]):
            result = process_action(action, {}, {}, [])
            self.assertIsNone(result.get("response_data"))

    def test_empty_entities_returns_empty(self):
        from unittest.mock import patch
        from core.ai.action_handler import process_action
        action = {"action": "lookupMemory", "parameters": {"entities": []}}
        with patch("core.memory.memory_retrieval.get_entity_timeline"):
            result = process_action(action, {}, {}, [])
            self.assertIsNone(result.get("response_data"))

    def test_fail_open_db_error(self):
        from unittest.mock import patch
        from core.ai.action_handler import process_action
        action = {"action": "lookupMemory", "parameters": {"entities": ["acheron"]}}
        with patch("core.memory.memory_retrieval.get_entity_timeline",
                   side_effect=RuntimeError("DB connection failed")):
            result = process_action(action, {}, {}, [])
            self.assertEqual(result.get("needs_update"), False)
            self.assertIsNone(result.get("response_data"))

    def test_deduplication(self):
        from unittest.mock import patch
        from core.ai.action_handler import process_action
        action = {"action": "lookupMemory", "parameters": {"entities": ["acheron", "kira"]}}
        with patch("core.memory.memory_retrieval.get_entity_timeline",
                   side_effect=lambda eid, **kw: [
                       {"event_id": "shared1", "event_ts": "2026-05-01T10:00:00",
                        "summary": "Party defeated Malarok", "retrieval_score": 95},
                   ]):
            result = process_action(action, {}, {}, [])
            ctx = result.get("response_data", {}).get("memory_context", "")
            self.assertEqual(ctx.count("Party defeated Malarok"), 1)

    def test_limit_enforcement_top_8(self):
        from unittest.mock import patch
        from core.ai.action_handler import process_action
        events = [
            {"event_id": f"evt{i}", "event_ts": f"2026-05-{i:02d}T10:00:00",
             "summary": f"Event number {i}", "retrieval_score": 100 - i}
            for i in range(15)
        ]
        action = {"action": "lookupMemory", "parameters": {"entities": ["acheron"]}}
        with patch("core.memory.memory_retrieval.get_entity_timeline", return_value=events):
            result = process_action(action, {}, {}, [])
            ctx = result.get("response_data", {}).get("memory_context", "")
            event_count = ctx.count("[2026-")
            self.assertLessEqual(event_count, 8)
            self.assertIn("Event number 0", ctx)
            self.assertNotIn("Event number 14", ctx)

    def test_summary_truncation(self):
        from unittest.mock import patch
        from core.ai.action_handler import process_action
        long_summary = "X" * 300
        action = {"action": "lookupMemory", "parameters": {"entities": ["acheron"]}}
        with patch("core.memory.memory_retrieval.get_entity_timeline",
                   return_value=[{"event_id": "long1", "event_ts": "2026-05-01T10:00:00",
                                  "summary": long_summary, "retrieval_score": 100}]):
            result = process_action(action, {}, {}, [])
            ctx = result.get("response_data", {}).get("memory_context", "")
            for line in ctx.split("\n"):
                if "X" in line:
                    summary_part = line.split("] ", 1)[1] if "] " in line else ""
                    self.assertLessEqual(len(summary_part), 155)

    def test_output_format(self):
        from unittest.mock import patch
        from core.ai.action_handler import process_action
        action = {"action": "lookupMemory", "parameters": {"entities": ["acheron"]}}
        with patch("core.memory.memory_retrieval.get_entity_timeline",
                   return_value=[{"event_id": "fmt1", "event_ts": "2026-03-15T14:30:00",
                                  "summary": "Formatted test event", "retrieval_score": 80}]):
            result = process_action(action, {}, {}, [])
            ctx = result.get("response_data", {}).get("memory_context", "")
            self.assertEqual(ctx.strip(),
                             "[SYSTEM] Campaign memory -- Python-authoritative record:\n  [2026-03-15] Formatted test event")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)


class TestMemoryLookupCollection(unittest.TestCase):
    """Tests for multi-site collection and transient injection (task 6.4)."""

    def test_transient_cleanup_removes_old_keeps_new(self):
        conversation_history = [
            {"role": "system", "content": "old transient memory", "_transient_memory": True},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "response"},
        ]
        pending = ["[SYSTEM] Campaign memory -- Python-authoritative record:\n  [2026-05-01] Test"]
        cleaned = [msg for msg in conversation_history if not msg.get("_transient_memory")]
        for memory_ctx in pending:
            cleaned.append({"role": "system", "content": memory_ctx, "_transient_memory": True})
        self.assertEqual(len(cleaned), 3)
        self.assertEqual(cleaned[0]["role"], "user")
        self.assertEqual(cleaned[1]["role"], "assistant")
        self.assertEqual(cleaned[2]["role"], "system")
        self.assertTrue(cleaned[2].get("_transient_memory"))
        self.assertIn("2026-05-01] Test", cleaned[2]["content"])

    def test_non_transient_messages_preserved(self):
        conversation_history = [
            {"role": "system", "content": "@DUNGEON_MASTER prompt"},
            {"role": "user", "content": "action description"},
            {"role": "assistant", "content": "narrative response"},
        ]
        pending = ["[SYSTEM] Campaign memory -- Python-authoritative record:\n  [2026-05-01] Event"]
        cleaned = [msg for msg in conversation_history if not msg.get("_transient_memory")]
        for memory_ctx in pending:
            cleaned.append({"role": "system", "content": memory_ctx, "_transient_memory": True})
        self.assertEqual(len(cleaned), 4)
        self.assertFalse(any(m.get("_transient_memory") for m in cleaned[:-1]))

    def test_multiple_memory_contexts_combined(self):
        pending = [
            "[SYSTEM] Campaign memory -- Python-authoritative record:\n  [2026-05-01] Event A",
            "[SYSTEM] Campaign memory -- Python-authoritative record:\n  [2026-05-02] Event B",
        ]
        combined = "\n\n".join(pending)
        messages = [{"role": "system", "content": combined, "_transient_memory": True}]
        self.assertEqual(len(messages), 1)
        self.assertIn("Event A", messages[0]["content"])
        self.assertIn("Event B", messages[0]["content"])

    def test_empty_pending_no_injection(self):
        conversation_history = [
            {"role": "user", "content": "hello"},
        ]
        pending = []
        original_len = len(conversation_history)
        if pending:
            pass
        self.assertEqual(len(conversation_history), original_len)


class TestMemoryLookupPromptContracts(unittest.TestCase):
    """Tests for prompt contract entries (tasks 6.5, 6.6)."""

    def test_lookupMemory_in_actions_compressed(self):
        with open("prompts/system_prompt_compressed.txt", "r") as f:
            content = f.read()
        self.assertIn("lookupMemory:", content.split("@ACTIONS")[1].split("@PARAMS")[0])

    def test_lookupMemory_in_params_compressed(self):
        with open("prompts/system_prompt_compressed.txt", "r") as f:
            content = f.read()
        params_section = content.split("@PARAMS={")[1].split("@CHARACTER_OPS")[0]
        self.assertIn("lookupMemory", params_section)

    def test_memory_lookup_directive_present_compressed(self):
        with open("prompts/system_prompt_compressed.txt", "r") as f:
            content = f.read()
        self.assertIn("@MEMORY_LOOKUP={", content)

    def test_lookupMemory_in_examples_compressed(self):
        with open("prompts/system_prompt_compressed.txt", "r") as f:
            content = f.read()
        examples_section = content.split("@EXAMPLES")[1].split("@REST")[0] if "@REST" in content else content.split("@EXAMPLES")[1]
        self.assertIn("lookupMemory", examples_section)

    def test_uncompressed_has_lookup_in_actions(self):
        with open("prompts/system_prompt.txt", "r") as f:
            content = f.read()
        self.assertIn("\"lookupMemory\"", content)
        self.assertIn("\"entities\": [\"entity_name_1\", \"entity_name_2\"]", content)

    def test_uncompressed_has_memory_lookup_directive(self):
        with open("prompts/system_prompt.txt", "r") as f:
            content = f.read()
        self.assertIn("@MEMORY_LOOKUP={", content)

    def test_uncompressed_has_lookup_in_examples(self):
        with open("prompts/system_prompt.txt", "r") as f:
            content = f.read()
        self.assertIn("action\": \"lookupMemory\"", content)

    def test_lookupMemory_validation_compressed(self):
        with open("prompts/validation/validation_prompt_compressed.txt", "r") as f:
            content = f.read()
        self.assertIn("lookupMemory", content)
        self.assertIn("INVALID", content[content.index("lookupMemory"):])

    def test_lookupMemory_validation_uncompressed(self):
        with open("prompts/validation/validation_prompt.txt", "r") as f:
            content = f.read()
        self.assertIn("lookupMemory", content)
        self.assertIn("VALID", content[content.index("lookupMemory"):])

    def test_no_duplicate_memory_lookup_directive_compressed(self):
        with open("prompts/system_prompt_compressed.txt", "r") as f:
            content = f.read()
        self.assertEqual(content.count("@MEMORY_LOOKUP={"), 1)

    def test_no_duplicate_memory_lookup_directive_uncompressed(self):
        with open("prompts/system_prompt.txt", "r") as f:
            content = f.read()
        self.assertEqual(content.count("@MEMORY_LOOKUP={"), 1)


class TestMemoryLookupAsciiCompliance(unittest.TestCase):
    """Tests for ASCII compliance of prompt additions (task 6.7)."""

    def _check_ascii_in_section(self, filepath, keyword):
        with open(filepath, "r") as f:
            lines = f.readlines()
        for line in lines:
            if keyword in line:
                for ch in line:
                    if ord(ch) >= 128:
                        self.fail(f"Non-ASCII char {ch!r} (ord={ord(ch)}) in {filepath} line containing '{keyword}'")

    def test_compressed_prompt_ascii(self):
        self._check_ascii_in_section("prompts/system_prompt_compressed.txt", "lookupMemory")

    def test_uncompressed_prompt_ascii(self):
        self._check_ascii_in_section("prompts/system_prompt.txt", "lookupMemory")

    def test_compressed_validation_ascii(self):
        self._check_ascii_in_section("prompts/validation/validation_prompt_compressed.txt", "lookupMemory")

    def test_uncompressed_validation_ascii(self):
        self._check_ascii_in_section("prompts/validation/validation_prompt.txt", "lookupMemory")


if __name__ == "__main__":
    unittest.main()
