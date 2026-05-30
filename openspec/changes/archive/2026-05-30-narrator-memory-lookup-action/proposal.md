## Why

Phase 1 (narrator-memory-milestone-injection) gives the narrator a push-based skeleton timeline of major campaign events. But the narrator sometimes needs detailed history for specific entities (e.g., "how did Vitreol die and come back?"). The skeleton timeline alone cannot answer that.

We need a pull-based mechanism where the narrator can explicitly request campaign memories on the fly, with Python acting as a deterministic subagent (no extra LLM calls).

## What Changes

- Add `lookupMemory` action to the narrator action dispatch in `core/ai/action_handler.py`
- Add `_process_memory_lookup()` function returning memory context via `response_data` dict
- Add `ACTION_LOOKUP_MEMORY` constant
- Collect memory context from all 6 `process_action()` call sites in `main.py:process_ai_response()`
- Inject collected memory results as transient system message after all action loops complete
- Add `lookupMemory` to `@ACTIONS`, `@PARAMS`, new `@MEMORY_LOOKUP` directive in system prompts
- Add `lookupMemory` validation rule to validation prompts (always valid, any entity name)
- Add example to `@EXAMPLES` showing memory lookup usage
- Route `lookupMemory` through sequential `other_actions` loop (not concurrent `ThreadPoolExecutor`)
- Transient cleanup: keep only latest memory results, remove previous transient messages
- Non-terminal action: returns `create_return(needs_update=False)`, other actions proceed normally

## Capabilities

### New Capabilities
- `narrator-memory-lookup-action-dispatch`: Action handler routing with `create_return()` contract and `response_data` pattern
- `narrator-memory-lookup-retrieval`: Bounded entity timeline retrieval (8 events max, 150 chars per summary)
- `narrator-memory-lookup-collection`: Multi-site action result collection in `process_ai_response()` with thread-safe routing
- `narrator-memory-lookup-injection`: Transient system message injection with cleanup semantics
- `narrator-memory-lookup-prompt-contract`: System prompt directive, validation rule, and usage example

## Impact

### Affected Code
- `core/ai/action_handler.py` — Add `ACTION_LOOKUP_MEMORY`, `_process_memory_lookup()`, dispatch
- `main.py` — Collect memory context from all call sites, single injection point
- `prompts/system_prompt_compressed.txt` — Add `lookupMemory` to `@ACTIONS`, `@PARAMS`, `@MEMORY_LOOKUP`, `@EXAMPLES`
- `prompts/system_prompt.txt` — Add `lookupMemory` (uncompressed parity)
- `prompts/validation/validation_prompt_compressed.txt` — Add `lookupMemory` validation rule
- `prompts/validation/validation_prompt.txt` — Add `lookupMemory` validation rule (uncompressed parity)
- `scripts/test_narrator_memory_milestones.py` — Extend with Phase 2 tests

### Dependencies
- Requires `narrator-memory-milestone-injection` (Phase 1) for shared retrieval infrastructure and constants (`MAX_LOOKUP_CHARS`, `get_entity_timeline()`, `normalize_character_name()`)
