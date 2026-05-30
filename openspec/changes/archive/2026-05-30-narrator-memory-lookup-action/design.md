## Context

Phase 1 (`narrator-memory-milestone-injection`) injects a push-based skeleton timeline into every narrator call. This works for general awareness but cannot answer specific questions like "how did Vitreol die?" when the narrator needs detailed history.

The memory DB (`core/memory/memory_db.py`) already contains rich event data from backfill operations. `get_entity_timeline()` in `memory_retrieval.py` supports weighted scoring with retrieval_score, pinned, importance, and decay. The infrastructure is ready; we just need a pull-based action to surface it on demand.

`process_ai_response()` in `main.py` has 6 distinct `process_action()` call sites with different result handling patterns. Memory context must be collected from all of them and injected as a single transient system message after all action loops complete.

## Goals / Non-Goals

**Goals:**
- Narrator can request campaign history via `lookupMemory` action when unsure about past events
- Python returns bounded, ranked event timeline (8 events max, 150 chars per summary)
- Memory results injected as transient system message, cleaned up on next turn
- Fail-open: missing DB, query errors, or empty results never block narration
- `lookupMemory` is non-terminal: other actions in the same response proceed normally
- One `lookupMemory` per response (limit enforced by prompt guidance, not code)

**Non-Goals:**
- No automatic context memory injection (Phase 3 future work)
- No memory DB schema changes (existing schema sufficient)
- No integration with `core/memories/` (plural) companion NPC system (independent)
- No multi-turn memory conversation (one lookup per response, ask again next turn if needed)

## Decisions

### Decision 1: `create_return()` contract with `response_data` dict
**Choice:** Use existing `create_return(needs_update=False, response_data={"memory_context": ...})` pattern.
**Rationale:** Matches all other action handlers in `action_handler.py`. Memory context flows through the standard `response_data` dict that `process_ai_response()` already reads.
**Alternative considered:** Custom top-level key in return dict — rejected because it breaks the established pattern and requires special handling in 6 call sites.

### Decision 2: Single injection point after all action loops
**Choice:** Collect `_pending_memory_contexts` list during action processing, inject combined result once after all loops complete (~line 4560).
**Rationale:** Avoids 6 separate injection points. Ensures memory results appear in conversation history before any recursive `needs_dm_response` or `needs_post_combat_narration` calls.
**Alternative considered:** Inject at each call site — rejected because it would create 6 injection points with duplicate cleanup logic.

### Decision 3: Route through sequential `other_actions` loop
**Choice:** Add `ACTION_LOOKUP_MEMORY` to the `other_actions` filter so it runs in the sequential loop (line ~4534), not the concurrent `ThreadPoolExecutor` (line ~4418).
**Rationale:** Memory lookup is read-only and fast. The concurrent path is for character updates that benefit from parallelism. Memory lookup doesn't need it and would complicate the collection pattern.

### Decision 4: Transient cleanup keeps only latest
**Choice:** After injecting new memory results, remove all previous `_transient_memory` messages from conversation history, keeping only the latest.
**Rationale:** Prevents stale memory results from accumulating. The narrator always sees the most recent lookup results. Old results are irrelevant once a new lookup fires.

### Decision 5: `@MEMORY_LOOKUP` as separate directive (not inline in `@ACTIONS`)
**Choice:** Add a dedicated `@MEMORY_LOOKUP` directive block with `when`, `how`, `format`, `response`, `rule`, `limit` fields.
**Rationale:** The action needs more guidance than a one-liner in `@ACTIONS`. The directive explains when to use it, what to expect back, and the one-per-response limit. Keeps `@ACTIONS` compact.

## Risks / Trade-offs

- **[Risk] Narrator overuses lookupMemory** -> Mitigation: Prompt guidance limits to one per response. If the narrator fires it every turn, the token cost is bounded (~300 tokens per lookup).
- **[Risk] Memory results contain irrelevant events** -> Mitigation: `get_entity_timeline()` already uses weighted scoring. Top 8 events by retrieval_score are the most relevant.
- **[Risk] Transient cleanup removes messages the narrator still needs** -> Mitigation: Cleanup only removes `_transient_memory` tagged messages. Regular conversation history is untouched. The narrator can always fire another `lookupMemory` if it needs the info again.
- **[Risk] Thread safety with concurrent action processing** -> Mitigation: `lookupMemory` routed through sequential loop only. No concurrent access to `_pending_memory_contexts`.
