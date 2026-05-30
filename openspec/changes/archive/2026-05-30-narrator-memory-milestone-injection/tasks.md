## 1. Milestone Builder Function

- [x] 1.1 Add shared constants to `core/memory/memory_retrieval.py`: `MAX_MILESTONE_CHARS = 120`, `MAX_LOOKUP_CHARS = 150`, `MILESTONE_SCORE_THRESHOLD = 30`
- [x] 1.2 Implement `build_campaign_milestones(entity_ids: List[str], max_events: int = 15) -> str` function that queries memory DB for events with `retrieval_score >= 30` OR `pinned == 1`
- [x] 1.3 Implement event deduplication by `event_id` when same event links to multiple entities
- [x] 1.4 Implement sorting by `retrieval_score` descending, then `event_ts` descending as tiebreaker
- [x] 1.5 Implement event formatting: `[YYYY-MM-DD] entity_id: summary` with summary truncated to `MAX_MILESTONE_CHARS`
- [x] 1.6 Implement output structure: `@CAMPAIGN_MILESTONES={\n  events: [\n    ...\n  ]\n}`
- [x] 1.7 Implement empty result handling: return `""` when no events qualify or entity list is empty
- [x] 1.8 Implement fail-open error handling: catch all exceptions, log warning with category `narrator_memory`, return `""`
- [x] 1.9 Implement ASCII sanitization: replace or remove non-ASCII characters in summaries
- [x] 1.10 Add `build_campaign_milestones` to `__all__` in `core/memory/__init__.py`
- [x] 1.11 Verify: `python -m py_compile core/memory/memory_retrieval.py core/memory/__init__.py`

## 2. Entity ID Resolution

- [x] 2.1 Add `_resolve_party_entity_ids(party_tracker_data: Dict) -> List[str]` helper function to `main.py` near line 5000
- [x] 2.2 Implement PC extraction: iterate `party_tracker_data.get("partyMembers", [])`, normalize each name
- [x] 2.3 Implement NPC extraction: iterate `party_tracker_data.get("partyNPCs", [])`, handle both string and dict forms (`{"name": "..."}`)
- [x] 2.4 Implement deduplication: use set to ensure each entity appears once
- [x] 2.5 Implement normalization: call `normalize_character_name()` from `updates.update_character_info` on each name
- [x] 2.6 Verify: `python -m py_compile main.py`

## 3. Milestone Injection Hook

- [x] 3.1 Locate injection point in `main.py:get_ai_response()` after `dedupe_main_system_prompt_messages()` call (line ~5248) and before transient correction (line ~5251)
- [x] 3.2 Add retry guard: `if validation_retry_count == 0:` to skip injection on retries
- [x] 3.3 Add entity resolution call: `entity_ids = _resolve_party_entity_ids(party_tracker_data)`
- [x] 3.4 Add milestone build call: `milestones_block = build_campaign_milestones(entity_ids)`
- [x] 3.5 Implement append logic: find main system prompt message (contains `@DUNGEON_MASTER`), append milestones with `\n\n` separator
- [x] 3.6 Add fail-open error handling: try/except around entire injection block, log `MILESTONE_INJECT: Failed to build milestones: <error>`
- [x] 3.7 Add `# TABLETOP MODE: Campaign milestone injection` comment marker
- [x] 3.8 Verify: `python -m py_compile main.py`

## 4. Prompt Directive Addition

- [x] 4.1 Locate `@CHRONICLE_RULES` section in `prompts/system_prompt_compressed.txt`
- [x] 4.2 Add `@CAMPAIGN_MILESTONES_USAGE` directive within 20 lines of `@CHRONICLE_RULES` with content:
  ```
  @CAMPAIGN_MILESTONES_USAGE={
    recognition: "A @CAMPAIGN_MILESTONES block in conversation contains authoritative campaign timeline.",
    rule: "These events HAPPENED. When characters or narration refer to past campaign events, use this timeline as the authoritative record.",
    priority: "Same authority as DM Note for historical events. If conversation history contradicts milestone timeline, milestone timeline WINS."
  }
  ```
- [x] 4.3 Verify ASCII-only: no smart quotes, em-dashes, or special symbols in directive text
- [x] 4.4 Locate `@CHRONICLE_RULES` section in `prompts/system_prompt.txt` (uncompressed variant)
- [x] 4.5 Add identical `@CAMPAIGN_MILESTONES_USAGE` directive to uncompressed prompt
- [x] 4.6 Verify both prompts contain identical directive content

## 5. Test Coverage

- [x] 5.1 Create `scripts/test_narrator_memory_milestones.py` with test class `TestBuildCampaignMilestones`
- [x] 5.2 Add test: `test_function_signature` - verify function accepts entity_ids list and optional max_events parameter
- [x] 5.3 Add test: `test_high_score_events_included` - event with score 45, pinned 0 is included
- [x] 5.4 Add test: `test_pinned_events_included` - event with score 10, pinned 1 is included
- [x] 5.5 Add test: `test_low_score_unpinned_excluded` - event with score 20, pinned 0 is excluded
- [x] 5.6 Add test: `test_deduplication_across_entities` - shared event appears once when multiple entities queried
- [x] 5.7 Add test: `test_event_limit` - 25 qualifying events with max_events=15 returns exactly 15
- [x] 5.8 Add test: `test_entry_format` - verify `[YYYY-MM-DD] entity_id: summary` format
- [x] 5.9 Add test: `test_long_summary_truncation` - summary >120 chars truncated to exactly 120
- [x] 5.10 Add test: `test_output_structure` - verify `@CAMPAIGN_MILESTONES={\n  events: [\n    ...\n  ]\n}` structure
- [x] 5.11 Add test: `test_empty_result_no_qualifying_events` - returns `""` when no events qualify
- [x] 5.12 Add test: `test_empty_result_empty_entity_list` - returns `""` when entity_ids is empty
- [x] 5.13 Add test: `test_fail_open_database_error` - returns `""` and logs warning when DB unavailable
- [x] 5.14 Add test: `test_ascii_only_output` - all output characters are ASCII
- [x] 5.15 Add test: `test_shared_constants_accessible` - import `MAX_MILESTONE_CHARS`, `MAX_LOOKUP_CHARS`, `MILESTONE_SCORE_THRESHOLD` succeeds
- [x] 5.16 Add test class `TestResolvePartyEntityIds` to `scripts/test_narrator_memory_milestones.py`
- [x] 5.17 Add test: `test_pc_extraction` - extracts and normalizes partyMembers
- [x] 5.18 Add test: `test_npc_extraction_string_form` - extracts string NPCs
- [x] 5.19 Add test: `test_npc_extraction_dict_form` - extracts dict NPCs with `{"name": "..."}`
- [x] 5.20 Add test: `test_deduplication` - same entity in both lists appears once
- [x] 5.21 Add test class `TestMilestoneInjection` to `scripts/test_narrator_memory_milestones.py`
- [x] 5.22 Add test: `test_injection_on_first_attempt` - milestones injected when validation_retry_count=0
- [x] 5.23 Add test: `test_skip_on_retry` - milestones not injected when validation_retry_count>0
- [x] 5.24 Add test: `test_append_to_main_prompt` - milestones appended to message with `@DUNGEON_MASTER`
- [x] 5.25 Add test: `test_fail_open_on_error` - narration continues without milestones on exception
- [x] 5.26 Add test: `test_no_persistence` - milestones not written to conversation_history.json
- [x] 5.27 Verify: `python -m unittest scripts.test_narrator_memory_milestones`

## 6. Integration Verification

- [x] 6.1 Run full test suite: `python -m unittest discover scripts`
- [x] 6.2 Verify no regressions in existing memory tests: `python -m unittest scripts.test_memory_foundation scripts.test_memory_retrieval`
- [x] 6.3 Manual smoke test: start game, verify narrator receives milestones in first call (check debug logs for `MILESTONE_BUILD` or `MILESTONE_INJECT`)
- [x] 6.4 Verify ASCII compliance: `python scripts/check_ascii_compliance.py`
- [x] 6.5 Update `AGENTS.md` Recent Changes section with implementation summary
