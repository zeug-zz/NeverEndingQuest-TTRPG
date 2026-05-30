# Narrator Long-Term Memory Integration

**Status:** COMPLETED (Phase 1)
**Priority:** High (Narrative Continuity)
**Effort:** Medium (~2-3 days for Phase 1+2)
**Plan Date:** 2026-05-28
**Implementation Date:** 2026-05-30

---

## Implementation Summary

**Phase 1 COMPLETED** — Campaign milestone injection into narrator prompts.

**What was built:**
- `build_campaign_milestones()` function in `core/memory/memory_retrieval.py`
- Entity ID resolution from `party_tracker.json` (PCs + NPCs)
- Transient injection into narrator payload in `main.py:get_ai_response()` after singularity guard
- `@CAMPAIGN_MILESTONES_USAGE` directive in both system prompts (compressed + uncompressed)
- 33 passing tests covering builder, resolver, injection, and prompt directives
- All files compile, ASCII compliant, TABLETOP MODE markers present

**What was NOT implemented (Phase 2 deferred):**
- `lookupMemory` action dispatch in `action_handler.py`
- Multi-site memory context collection in `process_ai_response()`
- `@MEMORY_LOOKUP` directive and examples in prompts
- Phase 2 tests

**OpenSpec:**
- Change `narrator-memory-milestone-injection` archived to `openspec/changes/archive/2026-05-30-narrator-memory-milestone-injection/`
- 3 main specs synced: `narrator-memory-milestone-builder`, `narrator-memory-milestone-injection`, `narrator-memory-milestone-prompt-contract`

---

## Verification Results (2026-05-30)

```bash
# Compilation
.venv/bin/python -m py_compile core/memory/memory_retrieval.py main.py  # PASS

# Tests
.venv/bin/python -m unittest scripts.test_narrator_memory_milestones  # 33/33 PASS
  - TestBuildCampaignMilestones: 15 tests PASS
  - TestEntityIdResolver: 5 tests PASS
  - TestMilestoneInjection: 6 tests PASS
  - TestPromptDirectiveContracts: 7 tests PASS

# Memory foundation regression
.venv/bin/python scripts/test_memory_foundation.py  # PASS (5/5)

# OpenSpec validation
openspec validate narrator-memory-milestone-injection  # VALID

# Archive
openspec archive narrator-memory-milestone-injection --yes  # SUCCESS
  - 3 specs synced to main (22 lines added)
  - Archived as 2026-05-30-narrator-memory-milestone-injection
```

---

## Problem Statement (Original)

The narrator LLM has severe long-term campaign amnesia. It correctly tracks current mechanical state (HP, conditions, spell slots via `@STATE_SYNC`) but forgets campaign history after a few conversation-compression cycles. In a recent session, the narrator forgot that Vitreol had died to stirge bite, been carried through the cave, and resurrected at the voidstone altar. The party had to stop roleplaying to explain campaign history to the DM.

### Root Cause (Original)

The memory infrastructure (`core/memory/*`) is fully functional but **completely disconnected from the narrator flow**:

| Layer | What exists | Connected to narrator? |
|-------|------------|----------------------|
| `memory_db.py` | SQLite schema (entities, events, links, journal) | No |
| `memory_ingest.py` | Journal + conversation history backfill | No |
| `memory_retrieval.py` | `get_entity_timeline()`, `get_context_memories()` with weighted scoring | No |
| `story_so_far_compiler.py` | Confirmed diary -> story text compilation | Only at PDF download time |

The narrator's only source of campaign history is the **compressed conversation history**, which gradually erases older events as compression cycles accumulate. The `@CHRONICLE_RULES` directive in the system prompt says to treat `=== CAMPAIGN HISTORY ===` blocks as authoritative, but those blocks are never injected.

---

## Phase 1: Campaign Milestone Outline (IMPLEMENTED)

**Goal:** Give the narrator a compact timeline of major campaign events so it remembers key plot points without blowing up the prompt.

**Effort:** ~1 day

### Architecture

Add a `@CAMPAIGN_MILESTONES` directive to the system prompt, injected after payload sanitization but before the LLM call. Built deterministically from memory DB queries — no extra LLM call.

```
@CAMPAIGN_MILESTONES={
  purpose: "Authoritative campaign timeline. These events HAPPENED.",
  rule: "Use when narrating continuity, recalling past events, or characters refer to history.",
  source: "Memory DB — Python-authoritative record of campaign events.",
  entries: [
    {ts: "1492 DR Mar 14", entity: "vitreol", event: "Died to stirge bite in Thornwood cave"},
    {ts: "1492 DR Mar 14", entity: "vitreol", event: "Resurrected at blighted grove voidstone altar by Acheron"},
    {ts: "1492 DR Mar 14", entity: "vitreol", event: "Entered Voidstone Undeath supernatural state"},
    {ts: "1492 DR Mar 14", entity: "party", event: "Defeated Malarok the Corruptor at Thornwood nexus"},
    ...
  ]
}
```

### Implementation Steps

#### Step 1.1 — New helper: `build_campaign_milestones()` in `core/memory/memory_retrieval.py` ✅

```python
def build_campaign_milestones(
    party_entity_ids: List[str],
    max_events: int = 15,
    max_chars_per_entry: int = 120,
    db_path: str = DEFAULT_MEMORY_DB_PATH,
) -> str:
```

Logic:
1. For each entity_id in `party_entity_ids`, call `get_entity_timeline(entity_id, limit=5)`
2. Collect all results, deduplicate by `event_id`
3. Filter to events with `retrieval_score >= 30` OR `pinned == 1`
   (Note: `importance` and `persistence_class` are used internally by the SQL scoring
   but are NOT returned in the result set. `retrieval_score` already incorporates
   importance, persistence, decay, reinforcement, and active-PC priority weighting.)
4. Sort by `retrieval_score DESC, event_ts DESC`
5. Take top `max_events`
6. Format each entry as a compact line: `[YYYY-MM-DD] entity: summary (truncated to MAX_MILESTONE_CHARS)`
7. Join with newlines
8. Fail-open: return empty string `""` on any error (missing DB, query failure, etc.)

Shared constants (define at module level in `memory_retrieval.py`):
```python
MAX_MILESTONE_CHARS = 120
MAX_LOOKUP_CHARS = 150
MILESTONE_SCORE_THRESHOLD = 30
```

Token budget: ~500 tokens for 15 entries at ~30 tokens each. Keep as ASCII-only prose.

#### Step 1.2 — Resolve entity IDs from `party_tracker.json` ✅

In the caller (Step 1.4), resolve PC + NPC names to entity IDs using the same normalization as `_normalize_name()` in `memory_ingest.py`:

```python
from updates.update_character_info import normalize_character_name

def _resolve_party_entity_ids(party_tracker_data: Dict) -> List[str]:
    entity_ids = []
    for member_name in party_tracker_data.get("partyMembers", []):
        entity_ids.append(normalize_character_name(str(member_name)))
    for npc_entry in party_tracker_data.get("partyNPCs", []):
        name = npc_entry.get("name", npc_entry) if isinstance(npc_entry, dict) else npc_entry
        entity_ids.append(normalize_character_name(str(name)))
    return list(set(eid for eid in entity_ids if eid))
```

**Entity ID resolution note:** `normalize_character_name()` produces slugs like `vitreol`, `acheron`. The `entities` table `entity_id` column uses the same normalization (via `_normalize_name()` in `memory_ingest.py` which delegates to `normalize_character_name()`). However, `get_entity_timeline()` internally joins through `memory_links` which was populated during ingest — so even if entity IDs diverge slightly, the timeline query resolves correctly via the link table. No additional alias resolution step is needed.

#### Step 1.3 — Compact milestone formatting ✅

Format entries as a single compact directive. Example output:

```
@CAMPAIGN_MILESTONES={
  events: [
    "1492-03-14 | vitreol died to stirge bite in Thornwood cave",
    "1492-03-14 | vitreol resurrected at blighted grove voidstone altar by acheron",
    "1492-03-14 | vitreol entered Voidstone Undeath supernatural state",
    "1492-03-14 | party defeated Malarok the Corruptor at Thornwood nexus",
  ]
}
```

Keep entries short. No multi-sentence prose. This is a lookup index, not a story summary.

#### Step 1.4 — Inject into narrator prompt in `main.py:get_ai_response()` ✅

Hook point: After the prompt singularity guard (line ~5280) and before the transient correction injection. This ensures milestones are not stripped by `dedupe_main_system_prompt_messages()`.

```python
# TABLETOP MODE: Campaign milestone injection (after singularity guard)
if validation_retry_count == 0:
    try:
        from core.memory.memory_retrieval import build_campaign_milestones
        party_entity_ids = _resolve_party_entity_ids(party_tracker_data)
        if party_entity_ids:
            milestones_block = build_campaign_milestones(party_entity_ids)
            if milestones_block:
                # Append to existing main system prompt (not as separate message)
                # This avoids singularity guard stripping it
                for i, msg in enumerate(messages_to_send):
                    if msg.get("role") == "system" and "@DUNGEON_MASTER" in msg.get("content", ""):
                        messages_to_send[i]["content"] += "\n\n" + milestones_block
                        break
    except Exception as e:
        # Fail-open: milestone injection failure never blocks narration
        warning(f"MILESTONE_INJECT: Failed to build milestones: {e}", category="narrator_memory")
```

Key design decisions:
- **Append to main system prompt**: Rather than injecting as a separate system message (which the singularity guard might strip), append milestone content to the existing main system prompt message.
- **Transient only**: milestone block is NOT persisted to `conversation_history.json`. It's rebuilt fresh each call from the memory DB.
- **Fail-open**: any error returns empty milestone block, narration proceeds normally.
- **Skip on retry**: milestone injection only happens on `validation_retry_count == 0` (first attempt), matching existing patterns.

#### Step 1.5 — Add `@CAMPAIGN_MILESTONES` reference to system prompt ✅

Add a brief directive in `prompts/system_prompt_compressed.txt` near `@CHRONICLE_RULES`:

```
@CAMPAIGN_MILESTONES_USAGE={
  recognition: "A @CAMPAIGN_MILESTONES block in conversation contains authoritative campaign timeline.",
  rule: "These events HAPPENED. When characters or narration refer to past campaign events, use this timeline as the authoritative record.",
  priority: "Same authority as DM Note for historical events. If conversation history contradicts milestone timeline, milestone timeline WINS.",
}
```

~15 lines, ASCII-only.

#### Step 1.6 — Test coverage ✅

New test file: `scripts/test_narrator_memory_milestones.py`

Tests:
- `build_campaign_milestones` returns empty on missing DB
- `build_campaign_milestones` returns empty on empty entity list
- `build_campaign_milestones` deduplicates across entities
- `build_campaign_milestones` respects max_events and max_chars
- `build_campaign_milestones` prioritizes pinned + identity_core events
- `_resolve_party_entity_ids` handles dict and string NPC entries
- `_resolve_party_entity_ids` deduplicates by normalized name
- Smoke: milestone injection doesn't break narrator flow (fail-open test)
- ASCII compliance on all output

#### Phase 1 Verification ✅

```bash
.venv/bin/python -m py_compile core/memory/memory_retrieval.py main.py
.venv/bin/python -m unittest scripts.test_narrator_memory_milestones
```

---

## Phase 2: On-Demand Memory Lookup (NOT IMPLEMENTED — Deferred)

**Goal:** Let the narrator request specific campaign memories on the fly when it's unsure about history. Python acts as the "subagent" — deterministic retrieval, no extra LLM calls.

**Effort:** ~1-2 days

**Status:** Deferred until Phase 1 proves its value in live gameplay testing.

### Architecture

```
Narrator LLM                     Python (memory subagent)
     |                                   |
     | "What happened to Vitreol?"      |
     |---lookupMemory action----------->|
     |                                   |-> get_entity_timeline("vitreol")
     |                                   |<- [ranked event list]
     |<--[SYSTEM] memory results--------|
     | (now knows Vitreol's history)    |
     |---narrates correctly------------>
```

### Implementation Steps

#### Step 2.1 — Add `lookupMemory` to action set

In `prompts/system_prompt_compressed.txt`:

Add to `@ACTIONS`:
```
lookupMemory: Request campaign history for entities when unsure about past events.
```

Add to `@PARAMS`:
```
lookupMemory: REQUIRED keys: "entities" (array of entity names), "query" (string, what the narrator is trying to remember). Example: {"action":"lookupMemory","parameters":{"entities":["vitreol","malarok"],"query":"how did vitreol die and come back"}}
```

Add to `@MEMORY_LOOKUP` (new directive):
```
@MEMORY_LOOKUP={
  when: "Use when you need campaign history you're unsure about. Characters referencing past events, DM needs to recall what happened.",
  how: "Emit lookupMemory action with entities and query. Python will return authorative history from the memory database.",
  format: "entities: array of character/creature names. query: what you need to know.",
  response: "Python will inject a [SYSTEM] message with the relevant campaign history. Read it, then continue narration.",
  rule: "The memory DB is authoritative for campaign history. Trust its results over your own uncertain memory.",
  limit: "One lookupMemory per response. If you need more history, ask in the NEXT turn.",
}
```

~15 lines, ASCII-only.

Add example to `@EXAMPLES`:
```
// Memory lookup when narrator forgot campaign history
Prompt: "Wait, how did Vitreol die again?"
Response:
{
  "narration": "Blairen's question hangs in the damp cave air...",
  "actions": [
    {"action":"lookupMemory","parameters":{"entities":["vitreol"],"query":"vitreol death and resurrection history"}}
  ]
}
```

#### Step 2.2 — Add `lookupMemory` to validation prompt

In `prompts/validation/validation_prompt_compressed.txt`:
```
lookupMemory: ALWAYS VALID. The narrator may request campaign history at any time. VALID entities are any character/NPC name. No other validation required.
```

#### Step 2.3 — Handle `lookupMemory` in `action_handler.py`

In `core/ai/action_handler.py`, add to the action dispatch (if/elif chain at line ~1389):

```python
ACTION_LOOKUP_MEMORY = "lookupMemory"

# In the action processing elif chain:
elif action_type == ACTION_LOOKUP_MEMORY:
    return _process_memory_lookup(parameters)
```

New function `_process_memory_lookup()`:

```python
def _process_memory_lookup(parameters: Dict) -> Dict:
    """Process a narrator memory lookup request.

    Returns memory context via response_data for main.py to collect.
    Uses create_return() to match existing action handler conventions.
    """
    try:
        from core.memory.memory_retrieval import get_entity_timeline
        from updates.update_character_info import normalize_character_name

        entities = parameters.get("entities", [])
        if not entities:
            return create_return(needs_update=False)

        all_events = []
        seen_ids = set()

        for entity_name in entities:
            entity_id = normalize_character_name(str(entity_name))
            events = get_entity_timeline(entity_id, limit=5)
            for event in events:
                eid = event.get("event_id", "")
                if eid and eid not in seen_ids:
                    seen_ids.add(eid)
                    all_events.append(event)

        if not all_events:
            return create_return(needs_update=False)

        all_events.sort(key=lambda e: e.get("retrieval_score", 0), reverse=True)
        top_events = all_events[:8]

        lines = ["[SYSTEM] Campaign memory -- Python-authoritative record:"]
        for event in top_events:
            ts = str(event.get("event_ts", ""))[:10]
            summary = str(event.get("summary", ""))[:MAX_LOOKUP_CHARS]
            lines.append(f"  [{ts}] {summary}")

        memory_context = "\n".join(lines)

        info(f"MEMORY_LOOKUP: Retrieved {len(top_events)} events for {entities}", category="narrator_memory")
        return create_return(
            needs_update=False,
            response_data={"memory_context": memory_context}
        )

    except Exception as e:
        warning(f"MEMORY_LOOKUP: Failed: {e}", category="narrator_memory")
        return create_return(needs_update=False)
```

Key differences from original plan:
- Uses `create_return()` helper (line 1377) to match existing action handler conventions
- Memory context returned via `response_data` dict (standard pattern), not a custom top-level key
- No `party_tracker_data` parameter needed (entity names come from action parameters)
- Uses shared `MAX_LOOKUP_CHARS` constant (150) for truncation

#### Step 2.4 — Collect and inject memory results in `main.py`

`process_ai_response()` has **6 distinct `process_action()` call sites** (lines 4083, 4119, 4418, 4487, 4534) with different result handling patterns. Memory context must be collected from all of them.

**Collection pattern:** Add a `_pending_memory_contexts` list at the top of `process_ai_response()`, and collect `response_data.memory_context` from every action result:

```python
# At top of process_ai_response() (~line 4025):
_pending_memory_contexts = []

# After each process_action() call, add:
if isinstance(result, dict):
    mc = result.get("response_data", {}).get("memory_context")
    if mc:
        _pending_memory_contexts.append(mc)
```

**Single injection point:** After all action loops complete (~line 4560), before any `needs_dm_response` or `needs_post_combat_narration` recursive calls:

```python
# TABLETOP MODE: Inject collected memory lookup results
if _pending_memory_contexts:
    combined = "\n\n".join(_pending_memory_contexts)
    conversation_history.append({
        "role": "system",
        "content": combined,
        "_transient_memory": True
    })
    # Clean up previous transient memory messages (keep only latest)
    conversation_history[:] = [
        msg for msg in conversation_history
        if not msg.get("_transient_memory")
        or msg is conversation_history[-1]
    ]
    needs_conversation_history_update = True
```

**Flow:**
1. Narrator emits `lookupMemory` + narration (optional)
2. `process_ai_response()` calls `process_action()` which returns `response_data.memory_context`
3. Memory contexts collected into `_pending_memory_contexts` list
4. After all actions processed, combined memory injected as transient system message
5. Conversation history saved with the transient message
6. On the NEXT narrator call, results are in context
7. Transient cleanup ensures only latest memory results persist

**Thread safety note:** The concurrent char update path (line 4418) uses `ThreadPoolExecutor`. Memory lookup should be routed through the sequential `other_actions` loop (line 4534), not the concurrent path. Add `ACTION_LOOKUP_MEMORY` to the `other_actions` filter.

#### Step 2.5 — Prevent `lookupMemory` from blocking other actions

`lookupMemory` is a non-terminal action:

- Returns `create_return(needs_update=False)` — standard continue pattern
- Other actions in the same response array proceed normally
- Memory results collected but don't change the action processing flow
- Routed through sequential `other_actions` loop (not concurrent `ThreadPoolExecutor`)

#### Step 2.6 — Test coverage

Extend `scripts/test_narrator_memory_milestones.py` with Phase 2 tests:

- `_process_memory_lookup` returns memory context for known entity
- `_process_memory_lookup` returns None for unknown entity
- `_process_memory_lookup` returns None on DB error (fail-open)
- `_process_memory_lookup` deduplicates across entities
- `_process_memory_lookup` respects limit (8 events max)
- Action dispatch routes `lookupMemory` correctly
- `lookupMemory` is non-terminal (returns continue)
- Transient memory cleanup removes old results
- Contract: `lookupMemory` in `@ACTIONS` and `@PARAMS`
- ASCII compliance on memory output

#### Phase 2 Verification

```bash
.venv/bin/python -m py_compile core/ai/action_handler.py main.py core/memory/memory_retrieval.py
.venv/bin/python -m unittest scripts.test_narrator_memory_milestones
```

---

## Files Modified (Phase 1)

| File | Change |
|------|--------|
| `core/memory/memory_retrieval.py` | Added `build_campaign_milestones()`, shared constants (`MAX_MILESTONE_CHARS`, `MAX_LOOKUP_CHARS`, `MILESTONE_SCORE_THRESHOLD`) |
| `core/memory/__init__.py` | Export `build_campaign_milestones` in `__all__` |
| `main.py` | Inject milestones into narrator payload (append to main system prompt after singularity guard), resolve entity IDs via `_resolve_party_entity_ids()` |
| `prompts/system_prompt_compressed.txt` | Add `@CAMPAIGN_MILESTONES_USAGE` |
| `prompts/system_prompt.txt` | Add `@CAMPAIGN_MILESTONES_USAGE` (uncompressed parity) |
| `scripts/test_narrator_memory_milestones.py` | New test file (33 tests) |

Files unchanged but relevant:
- `core/memory/memory_db.py` — schema is already sufficient
- `core/memory/memory_ingest.py` — backfill already works
- `core/memory/story_so_far_compiler.py` — separate concern (PDF download)
- `core/ai/conversation_utils.py` — no memory DB dependency (uses flat JSON campaign summaries)
- `core/memories/` (plural) — companion NPC emotional physics, completely independent system

---

## Design Decisions

1. **Python as subagent, not LLM subagent**: Memory retrieval is deterministic SQL queries. No need for an LLM subagent — Python is faster, cheaper, and more reliable. The narrator LLM calls `lookupMemory`, Python queries the DB, results come back.

2. **Transient messages only**: Milestone blocks and memory lookup results are NOT persisted to `conversation_history.json`. They're rebuilt fresh each call. This prevents stale memory blocks from accumulating and ensures the latest DB state is always used.

3. **Fail-open everywhere**: If the memory DB is missing, corrupt, or any query fails, narration proceeds normally. Memory is an enhancement, not a dependency. The narrator falls back to its existing behavior (conversation history only).

4. **Bounded token budgets**: Phase 1 milestones capped at 15 events (~500 tokens). Phase 2 lookup results capped at 8 events (~300 tokens). This keeps the prompt lean while providing meaningful history.

5. **ASCII-only**: All memory output follows the repo's ASCII compliance rules. No unicode in event summaries injected into prompts.

6. **No prompt drift**: The `@CAMPAIGN_MILESTONES` block is rebuilt from the DB on every call. It reflects current state, not stale accumulated text.

7. **`lookupMemory` is pull, not push**: The narrator only gets detailed history when it asks. This keeps the prompt sparse most of the time, with Phase 1 milestones providing a skeleton. When the narrator needs more detail (e.g., "how did Vitreol die?"), it explicitly requests it.

---

## Future: Phase 3 (Not Planned in Detail)

Automatic context memory injection before every narrator call. Run `get_context_memories(scene_type, active_entities)` with the current scene context and inject top results automatically. Removes the need for the narrator to ask. Higher token cost, higher risk of irrelevant memories surfacing. Best implemented after Phase 1+2 prove the retrieval quality in live gameplay.

---

## Rollback

Phase 1 is additive. Removing it involves:
1. Remove the milestone injection block from `get_ai_response()`
2. Remove `@CAMPAIGN_MILESTONES_USAGE` from the prompt directives
3. The memory DB and retrieval functions remain unchanged (no data migration needed)

No schema changes. No data migration. No configuration flags needed.

---

## OpenSpec Implementation Sequence

Based on archive patterns (226 changes, memory work split into focused capabilities like `memory-schema-retrieval-foundation`, `pc-leave-return-world-memory`), this plan decomposes into **2 OpenSpec changes** — one per phase. Each is independently implementable, testable, and archivable.

### Change 1: `narrator-memory-milestone-injection` ✅ COMPLETED

**Scope:** Phase 1 — Automatic campaign milestone injection into narrator prompts

**What Changed:**
- Add `build_campaign_milestones()` to `core/memory/memory_retrieval.py` with bounded retrieval (15 events, ~500 tokens)
- Add entity ID resolution from `party_tracker.json` (PCs + NPCs)
- Inject milestones into narrator payload in `main.py:get_ai_response()` after singularity guard
- Add `@CAMPAIGN_MILESTONES_USAGE` directive to system prompts (compressed + uncompressed parity)
- Export `build_campaign_milestones` in `core/memory/__init__.py`
- Fail-open everywhere: missing DB, query errors, or empty results never block narration
- Transient-only injection: milestones rebuilt fresh each call, not persisted to conversation history
- Skip on retry: injection only on `validation_retry_count == 0`

**Capabilities:**
- `narrator-memory-milestone-builder`: Deterministic milestone construction from memory DB with retrieval-score filtering and deduplication
- `narrator-memory-milestone-injection`: Transient system prompt injection with singularity-guard-safe append pattern
- `narrator-memory-milestone-prompt-contract`: System prompt directive establishing milestone authority over conversation history

**Mandatory Constraints (all met):**
- ✅ MUST use `retrieval_score >= 30` OR `pinned == 1` filter
- ✅ MUST append to existing main system prompt (not inject as separate message)
- ✅ MUST fail-open on any error
- ✅ MUST skip injection on validation retries (`validation_retry_count > 0`)
- ✅ MUST maintain ASCII-only output
- ✅ MUST preserve uncompressed prompt parity

**Verification:**
```bash
.venv/bin/python -m py_compile core/memory/memory_retrieval.py main.py  # PASS
.venv/bin/python -m unittest scripts.test_narrator_memory_milestones  # 33/33 PASS
openspec validate narrator-memory-milestone-injection  # VALID
openspec archive narrator-memory-milestone-injection --yes  # SUCCESS
```

---

### Change 2: `narrator-memory-lookup-action` (NOT STARTED — Deferred)

**Scope:** Phase 2 — On-demand memory lookup via `lookupMemory` action

**Status:** Deferred until Phase 1 proves its value in live gameplay testing.

**Why:** Phase 1 milestones provide a skeleton timeline, but the narrator sometimes needs detailed history for specific entities (e.g., "how did Vitreol die?"). We need a pull-based mechanism where the narrator can explicitly request campaign memories on the fly, with Python acting as a deterministic subagent (no extra LLM calls).

**What Changes:**
- Add `lookupMemory` action to action dispatch in `core/ai/action_handler.py` (elif chain at line ~1389)
- Add `_process_memory_lookup()` function returning memory context via `response_data` dict
- Add `ACTION_LOOKUP_MEMORY` constant
- Collect memory context from all 6 `process_action()` call sites in `main.py:process_ai_response()`
- Inject collected memory results as transient system message after all action loops complete (line ~4560)
- Add `lookupMemory` to `@ACTIONS`, `@PARAMS`, new `@MEMORY_LOOKUP` directive in system prompts
- Add `lookupMemory` validation rule to validation prompts (always valid, any entity name)
- Add example to `@EXAMPLES` showing memory lookup usage
- Route `lookupMemory` through sequential `other_actions` loop (not concurrent `ThreadPoolExecutor`)
- Transient cleanup: keep only latest memory results, remove previous transient messages
- Non-terminal action: returns `create_return(needs_update=False)`, other actions proceed normally

**Dependencies:** Requires Change 1 (`narrator-memory-milestone-injection`) for shared retrieval infrastructure and constants

---

### Implementation Order

1. **Change 1 first** — Establishes retrieval infrastructure, shared constants, and entity ID resolution ✅ DONE
2. **Change 2 second** — Builds on Change 1's foundation, adds action dispatch and multi-site collection ⏸️ DEFERRED

Both changes are independently archivable. Change 1 can ship alone (push-based milestones only). Change 2 requires Change 1 but adds pull-based lookup capability.

**Phase 3 (future):** `narrator-memory-automatic-context` — Automatic context memory injection before every narrator call. Deferred until Phase 1+2 prove retrieval quality in live gameplay.