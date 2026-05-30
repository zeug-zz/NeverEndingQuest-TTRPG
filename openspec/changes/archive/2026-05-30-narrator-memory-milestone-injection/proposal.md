## Why

The narrator LLM has severe long-term campaign amnesia despite a fully functional memory DB (83MB, 12K events, 35K links). The memory infrastructure exists but is completely disconnected from the narrator flow. In a recent session, the narrator forgot that Vitreol had died to stirge bite, been carried through the cave, and resurrected at the voidstone altar. The party had to stop roleplaying to explain campaign history to the DM. We need a push-based skeleton timeline injected into every narrator call so the DM remembers major campaign events without blowing up the prompt budget.

## What Changes

- Add `build_campaign_milestones()` to `core/memory/memory_retrieval.py` with bounded retrieval (15 events, ~500 tokens)
- Add entity ID resolution from `party_tracker.json` (PCs + NPCs)
- Inject milestones into narrator payload in `main.py:get_ai_response()` after singularity guard (line 5248)
- Add `@CAMPAIGN_MILESTONES_USAGE` directive to system prompts (compressed + uncompressed parity)
- Export `build_campaign_milestones` in `core/memory/__init__.py`
- Fail-open everywhere: missing DB, query errors, or empty results never block narration
- Transient-only injection: milestones rebuilt fresh each call, not persisted to conversation history
- Skip on retry: injection only on `validation_retry_count == 0`

## Capabilities

### New Capabilities
- `narrator-memory-milestone-builder`: Deterministic milestone construction from memory DB with retrieval-score filtering and deduplication
- `narrator-memory-milestone-injection`: Transient system prompt injection with singularity-guard-safe append pattern
- `narrator-memory-milestone-prompt-contract`: System prompt directive establishing milestone authority over conversation history

### Modified Capabilities
<!-- None - this is additive infrastructure -->

## Impact

**Affected Code:**
- `core/memory/memory_retrieval.py` — Add new function and shared constants
- `core/memory/__init__.py` — Export new function
- `main.py` — Inject milestones after singularity guard, resolve entity IDs
- `prompts/system_prompt_compressed.txt` — Add `@CAMPAIGN_MILESTONES_USAGE`
- `prompts/system_prompt.txt` — Add `@CAMPAIGN_MILESTONES_USAGE` (uncompressed parity)
- `scripts/test_narrator_memory_milestones.py` — New test file

**Dependencies:** None (standalone, uses existing memory DB infrastructure)

**APIs:** No external API changes

**Rollout Risk:** Low — fail-open pattern ensures narration continues if memory DB unavailable

**Fallback Strategy:** If milestone injection fails, narrator falls back to existing behavior (conversation history only). No user-facing degradation.

**Merge-Safety:** Minimal host file edits (main.py only), all marked with `# TABLETOP MODE:` comments. Extension-based pattern preserves upstream compatibility.

**SP/MP Compatibility:** Works in both single-player and multiplayer modes. Entity ID resolution handles both PCs and NPCs. No party-size gating required.

**Provider Outage Behavior:** N/A — no LLM calls in milestone construction. Pure deterministic SQL queries from memory DB.

## Mandatory Constraints

- MUST use `retrieval_score >= 30` OR `pinned == 1` filter (not `importance`/`persistence_class` which aren't in result set)
- MUST append to existing main system prompt (not inject as separate message) to avoid singularity guard stripping
- MUST fail-open on any error (missing DB, query failure, empty results)
- MUST skip injection on validation retries (`validation_retry_count > 0`)
- MUST maintain ASCII-only output (no unicode in event summaries)
- MUST preserve uncompressed prompt parity (both `system_prompt.txt` and `system_prompt_compressed.txt`)

## Non-goals

- No automatic context memory injection (Phase 3 future work)
- No on-demand lookup action (Phase 2 separate change: `narrator-memory-lookup-action`)
- No memory DB schema changes (existing schema sufficient)
- No integration with `core/memories/` (plural) companion NPC system (independent)
