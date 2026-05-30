## Context

The memory DB (`core/memory/`) is fully operational with 83MB of data, 12K events, and 35K links across 7 entities. The retrieval layer (`memory_retrieval.py`) provides `get_entity_timeline()` with weighted scoring incorporating importance, persistence class, decay, reinforcement, and active-PC priority. However, zero code paths connect this infrastructure to the narrator prompt assembly in `main.py:get_ai_response()`.

The narrator's only campaign history source is compressed conversation history, which erodes older events through compression cycles. The `@CHRONICLE_RULES` directive references `=== CAMPAIGN HISTORY ===` blocks, but those are produced by compressors as assistant messages — not injected from the memory DB.

**Current narrator payload pipeline (main.py lines 5149-5275):**
1. Compression → `messages_to_send`
2. Sanitization (`_sanitize_narrator_payload`) → strips derived location blocks
3. Singularity guard (`dedupe_main_system_prompt_messages`) → ensures one system prompt
4. Transient correction (retry only) → appends correction as user message
5. LLM call

**Injection point:** After step 3 (line 5248), before step 4 (line 5251).

## Goals / Non-Goals

**Goals:**
- Inject a compact campaign milestone timeline (~500 tokens, 15 events) into every narrator call
- Use deterministic SQL queries — no extra LLM calls
- Fail-open: memory DB absence or errors never block narration
- Transient-only: rebuilt fresh each call, never persisted to conversation history
- Skip on validation retries to avoid redundant DB queries

**Non-Goals:**
- On-demand memory lookup (Phase 2: `narrator-memory-lookup-action`)
- Automatic context memory injection (Phase 3: future)
- Memory DB schema changes
- Integration with `core/memories/` (plural) companion NPC system

## Decisions

### D1: Append to main system prompt vs separate system message

**Decision:** Append milestone block to the existing main system prompt message.

**Rationale:** The singularity guard (`dedupe_main_system_prompt_messages()`) at line 5232 strips duplicate system messages. A separate system message would be removed. Appending to the main prompt (identified by `@DUNGEON_MASTER` marker) preserves the content through the guard.

**Alternative considered:** Inject as separate system message after singularity guard. Rejected because the guard runs on every call and the injection point is before transient correction — ordering is fragile.

### D2: Filter on `retrieval_score` vs `importance`/`persistence_class`

**Decision:** Filter on `retrieval_score >= 30` OR `pinned == 1`.

**Rationale:** `get_entity_timeline()` returns `retrieval_score` (computed) and `pinned` but NOT `importance` or `persistence_class` (used internally in SQL scoring). Using `retrieval_score` leverages the existing weighted scoring that already incorporates importance, persistence, decay, and reinforcement.

**Alternative considered:** Modify `get_entity_timeline()` SELECT to include `importance` and `persistence_class`. Rejected — adds schema coupling and the existing score already encodes these signals.

### D3: Entity ID resolution strategy

**Decision:** Use `normalize_character_name()` from `updates/update_character_info.py` to produce entity IDs, then pass directly to `get_entity_timeline()`.

**Rationale:** The memory ingest pipeline (`_normalize_name()` in `memory_ingest.py`) delegates to the same `normalize_character_name()`. Entity IDs in the `entities` table match. Additionally, `get_entity_timeline()` joins through `memory_links` which was populated during ingest, providing a second resolution path.

**Alternative considered:** Query `entity_aliases` table for each name. Rejected — unnecessary complexity when the primary path already works.

### D4: Injection gated on `validation_retry_count == 0`

**Decision:** Only inject milestones on the first narrator attempt, skip on retries.

**Rationale:** Matches existing patterns at lines 5072, 5090, 5431 where first-attempt-only logic gates expensive operations. Milestones don't change between retry attempts (same DB state), so re-injection wastes tokens.

### D5: Shared constants in `memory_retrieval.py`

**Decision:** Define `MAX_MILESTONE_CHARS = 120`, `MAX_LOOKUP_CHARS = 150`, `MILESTONE_SCORE_THRESHOLD = 30` at module level.

**Rationale:** Phase 2 (`narrator-memory-lookup-action`) will reuse `MAX_LOOKUP_CHARS`. Centralizing avoids magic numbers and ensures consistency.

## Risks / Trade-offs

**[Risk] Memory DB grows large, query latency increases** → Mitigation: `get_entity_timeline()` already uses indexed queries with `LIMIT`. 15 events × 5 entities = 75 rows max per call. Negligible latency.

**[Risk] Milestone content contradicts conversation history** → Mitigation: `@CAMPAIGN_MILESTONES_USAGE` directive explicitly states milestones WIN over conversation history. This is the correct authority hierarchy (Python state > compressed history).

**[Risk] Token budget exceeded for campaigns with many high-importance events** → Mitigation: Hard cap at 15 events, 120 chars each. ~500 tokens worst case. Acceptable overhead for a system prompt append.

**[Risk] Singularity guard strips appended content** → Mitigation: Append happens AFTER singularity guard runs. The guard deduplicates system messages, not content within a single message.

**[Trade-off] No per-scene filtering** → Milestones include all high-score events regardless of current scene. Phase 3 will add scene-aware filtering. Acceptable for MVP — better to show too much than too little.
