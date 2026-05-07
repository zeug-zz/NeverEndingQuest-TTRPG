## Context

Fast PC_PHASE command handling needs a durable narrative/context trail that is not itself a mechanic. Without a ledger, `/end` has no clean compact summary of what PCs did unless it reads chat text. Reading chat text risks replaying already-applied mechanics.

The ledger should capture facts in a structured, compact, replay-safe form.

## Contract Layer (MUST)

### Ledger Authority Boundary

- PC_PHASE ledger entries MUST be historical metadata.
- Ledger entries MUST NOT be used as the primary source of HP, status, conditions, spell slots, or encounter state.
- Character files and encounter files MUST remain mechanical source of truth.
- Every mechanics-bearing ledger entry MUST mark `mechanics_already_applied` as true.

### Ledger Entry Content

- Ledger entries MUST include round, phase, actor, kind, and timestamp or deterministic sequence id.
- Ledger entries for attack/damage events SHOULD include target, roll, AC, damage, HP before/after, and target status when known.
- Ledger entries MUST remain compact and ASCII-safe.
- Ledger entries MUST avoid full prompt transcripts.

### Lifecycle

- Ledger entries MUST be clearable at combat end.
- Ledger entries MUST be grouped or filterable by round.
- Runtime MUST avoid duplicating the same deterministic command event in the ledger.

### Historical Prompt Injection

- Any ledger-derived prompt context MUST be explicitly labelled historical-only.
- Historical recap context MUST forbid mechanics replay.
- Historical recap context MUST NOT require the LLM to emit PC mechanics actions.

## Guidance Layer (SHOULD)

### Storage

Initial implementation should prefer in-memory storage on `MultiPCCombatManager`.

If resume support is needed, persist a compact list to encounter JSON under an additive field such as `pcPhaseEvents`. If persisted, keep entries bounded by recent round or configurable max count.

### Event Kinds

Initial event kinds:

- `attack_miss`
- `attack_hit_pending_damage`
- `attack_damage`
- `spell_damage`
- `spell_healing`
- `movement`
- `death_save`
- `manual_note`

### Formatting

Ledger-to-prompt formatting should be terse:

```text
=== PC PHASE RECAP FACTS (HISTORICAL ONLY; DO NOT REPLAY MECHANICS) ===
- Round 2: Acheron missed Skeleton_1 with axe, roll 9 vs AC 14.
- Round 2: Lidda dealt 8 damage to Skeleton_2, HP 6 -> 0, status dead.
```

## Rollback

- Disable prompt injection first.
- If needed, keep ledger in-memory and do not persist.
- If event recording causes command regressions, remove ledger writes while preserving fast command behavior.
