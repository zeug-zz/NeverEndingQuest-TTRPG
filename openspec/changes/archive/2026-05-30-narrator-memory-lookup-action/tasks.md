## 1. Action Handler Dispatch

- [ ] 1.1 Add `ACTION_LOOKUP_MEMORY = "lookupMemory"` constant to `core/ai/action_handler.py`
- [ ] 1.2 Add `elif action_type == ACTION_LOOKUP_MEMORY: return _process_memory_lookup(parameters)` to the action dispatch chain
- [ ] 1.3 Implement `_process_memory_lookup()` function using `create_return()` contract with `response_data={"memory_context": ...}`
- [ ] 1.4 Add fail-open exception handling that logs warning and returns `create_return(needs_update=False)`

## 2. Memory Retrieval Logic

- [ ] 2.1 Normalize entity names via `normalize_character_name()` before querying
- [ ] 2.2 Call `get_entity_timeline(entity_id, limit=5)` for each entity
- [ ] 2.3 Deduplicate events by `event_id` across all entities
- [ ] 2.4 Sort by `retrieval_score DESC`, take top 8
- [ ] 2.5 Format output as `[SYSTEM] Campaign memory -- Python-authoritative record:` with timestamped entries truncated to `MAX_LOOKUP_CHARS`
- [ ] 2.6 Return empty `create_return(needs_update=False)` when entities list is empty or no events found

## 3. Multi-Site Collection in main.py

- [ ] 3.1 Add `_pending_memory_contexts = []` at top of `process_ai_response()`
- [ ] 3.2 After each `process_action()` call site, check for `response_data.memory_context` and append to list
- [ ] 3.3 Add `ACTION_LOOKUP_MEMORY` to the `other_actions` filter for sequential routing (not concurrent `ThreadPoolExecutor`)

## 4. Transient Injection

- [ ] 4.1 After all action loops complete, if `_pending_memory_contexts` is non-empty, join with `"\n\n"` and append as system message with `_transient_memory: True`
- [ ] 4.2 Before injection, remove all previous `_transient_memory` messages from conversation history
- [ ] 4.3 Set `needs_conversation_history_update = True` when memory results are injected
- [ ] 4.4 Ensure injection occurs before any `needs_dm_response` or `needs_post_combat_narration` recursive calls

## 5. Prompt Contract

- [ ] 5.1 Add `lookupMemory` to `@ACTIONS` in `prompts/system_prompt_compressed.txt`
- [ ] 5.2 Add `lookupMemory` parameter spec to `@PARAMS` in `prompts/system_prompt_compressed.txt`
- [ ] 5.3 Add `@MEMORY_LOOKUP` directive block to `prompts/system_prompt_compressed.txt`
- [ ] 5.4 Add `lookupMemory` example to `@EXAMPLES` in `prompts/system_prompt_compressed.txt`
- [ ] 5.5 Mirror all additions in `prompts/system_prompt.txt` (uncompressed parity)
- [ ] 5.6 Add `lookupMemory: ALWAYS VALID` rule to `prompts/validation/validation_prompt_compressed.txt`
- [ ] 5.7 Mirror validation rule in `prompts/validation/validation_prompt.txt` (uncompressed parity)
- [ ] 5.8 Verify all prompt additions are ASCII-only

## 6. Test Coverage

- [x] 6.1 Add `_process_memory_lookup` tests: known entity, unknown entity, DB error (fail-open), deduplication, limit enforcement
- [x] 6.2 Add action dispatch routing test for `lookupMemory`
- [x] 6.3 Add non-terminal action test (returns continue, other actions proceed)
- [x] 6.4 Add transient cleanup test (old messages removed, new message kept)
- [x] 6.5 Add prompt contract tests: `lookupMemory` in `@ACTIONS`, `@PARAMS`, `@MEMORY_LOOKUP`, `@EXAMPLES`
- [x] 6.6 Add validation prompt contract test: `lookupMemory: ALWAYS VALID`
- [x] 6.7 Add ASCII compliance test on all prompt additions

## 7. Verification

- [x] 7.1 `.venv/bin/python -m py_compile core/ai/action_handler.py main.py` -> PASS
- [x] 7.2 `.venv/bin/python -m unittest scripts.test_narrator_memory_milestones` -> ALL PASS (63/63)
- [x] 7.3 `openspec validate narrator-memory-lookup-action` -> VALID
