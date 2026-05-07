## Why

Once deterministic PC_PHASE actions stop using the full combat LLM, runtime still needs a compact way to remember what happened during the facilitator-owned PC phase. That record is useful for future `/end` recap, merged PC/enemy narration, replay protection, debugging, and prompt grounding.

The ledger must be historical metadata, not a new source of mechanical truth. Character files and encounter files remain authoritative.

## What Changes

- Add a PC_PHASE event ledger for deterministic and parsed PC actions.
- Record compact already-applied facts such as actor, target, kind, roll, damage, HP before/after, status, and spoken narration.
- Format ledger facts for optional `/end` historical recap context.
- Clear or roll over ledger entries at round boundaries and combat completion.
- Keep recap/merged narration disabled by default, but establish safe contract for later use.

## Capabilities

### New Capabilities

- `tt-combat-pc-phase-event-ledger`: PC_PHASE events can be recorded as historical already-applied facts for recap/debug/prompt context without becoming mechanical authority.

### Modified Capabilities

- `tt-combat-deterministic-command-replay-guard`: Ledger facts reinforce already-applied replay protection.
- `tt-combat-validation-retry-hygiene`: Future recap context can be marked historical-only to avoid validation loops.

## Non-Goals

- Do not enable `/end` recap by default in this change.
- Do not implement merged PC/enemy narration in this change.
- Do not replace encounter or character files as mechanical sources of truth.
- Do not persist large narrative transcripts in encounter files.

## Impact

- **Affected code**: `core/managers/multi_pc_combat.py`, `core/managers/combat_manager.py`, possibly `core/managers/combat_state_sync.py`, tests.
- **Runtime behavior**: Minimal visible change initially; ledger supports future recap and improved observability.
- **Backward compatible**: Ledger is additive and should be ignored when empty or unavailable.
- **Risk**: Low-medium. Main risk is confusing ledger facts with replayable mechanics.

## Fallback Strategy

If ledger causes confusion or persistence issues, keep it in-memory only and disable prompt injection. Mechanical state remains unaffected.
