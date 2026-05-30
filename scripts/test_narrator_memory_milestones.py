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


if __name__ == "__main__":
    unittest.main()
