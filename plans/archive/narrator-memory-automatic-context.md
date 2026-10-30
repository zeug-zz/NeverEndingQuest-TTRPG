# Narrator Memory Automatic Context Injection (Phase 3)

> Archived as superseded planning on 2026-10-27. Current implementation planning:
> [V2 Narrator](../v2-narrator.md). Automatic retrieval and layered context are now
> core build scope; the low-priority deferral and fixed token assumption below are
> retired. The original draft is preserved, not marked implemented or accepted.

**Status:** DRAFT / Deferred
**Priority:** Low (awaiting Phase 1+2 gameplay validation)
**Effort:** TBD
**Plan Date:** 2026-05-30
**Dependency:** Phase 1 (milestone injection) + Phase 2 (memory lookup) proven in live gameplay as per plans/archive/narrator_memory_update.md

---

## Goal

Complement the current pull-based model (narrator must explicitly emit `lookupMemory`) with automatic context injection before every narrator call. The system determines which entities are relevant to the current scene and injects bounded memory context without the narrator asking.

## Open Question

Phase 1+2 must prove retrieval quality is high enough that automatic injection adds signal, not noise. Premature Phase 3 risks context-window waste on irrelevant memories.

## Stub

Details deferred until Phase 1+2 gameplay validation. Possible approaches:

1. **Scene-type routing** — Use `get_context_memories(scene_type, active_entities)` with the current scene classification (combat, social, exploration) and inject top results automatically
2. **Rolling window** — Always inject the N most recent high-importance events regardless of current scene
3. **Hybrid** — Push N high-importance milestones + let narrator pull specific details via `lookupMemory`

Key constraint: must remain within ~500 token budget for automatic injection to avoid prompt bloat.
