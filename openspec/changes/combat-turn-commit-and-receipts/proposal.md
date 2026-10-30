# Proposal

## Why

Combat currently has more than one persistence/publication order, and atomic writes to individual files do not make a turn atomic across character and encounter files. A process restart at a write boundary can therefore expose a partial turn and replay HP, resources, enemy effects, or rewards; G7 assigns this reviewed commit/recovery contract to Build 6.

## What Changes

- MUST define one authoritative combat-turn commit: persist affected character state first, persist the encounter last with a durable receipt, then run post-commit phase work and publish success only after commit succeeds.
- MUST persist a stable `turn_id` with each accepted input before mechanical writes, derive a per-turn `applied_id`, and persist a bounded commit manifest in the existing pre-commit history write so bootstrap can finish pending commits without a provider call or re-planning. Define exact receipt fields, recovery at every commit boundary, and code-owned round advancement. Persisted state remains Python-owned and uses repository atomic-write helpers.
- MUST add provider-free interruption/restart tests and preserve 1-PC and 4-PC behavior, existing replay guards, G1/G3/G4/G5R compatibility goldens, and all nine legacy combat prompt hashes.
- MUST keep fault injection sandbox-only and default-off. The primary orchestrator owns the G7 live verdict; implementation builders provide tooling and focused fixes only.
- Non-goals: change combat mechanics, prompt bytes, provider policy, G5R targets, public APIs, `MULTIPLAYER_MODE`, or party-size gates; run or claim the live gate in this planning task.

## Capabilities

### New Capabilities

- `combat-turn-receipt-model`: Durable character-first/encounter-last commits, receipts, applied IDs, idempotent replay, and manager-owned round advancement.
- `combat-turn-interruption-boundaries`: Testable pre-/post-restart state for each approved interruption boundary and sandbox-only fault injection.
- `combat-turn-g7-verification`: G7 software compatibility and primary-owned live acceptance contract for both party shapes.

### Modified Capabilities

None. The new turn-commit protocol extends the scope beyond the existing enemy-state resume guard; that guard remains in force and is not replaced.

## Impact

Future implementation is expected in package-owned combat turn/persistence and enemy-batch apply paths, conversation-history turn metadata, character and encounter state schemas, and focused provider-free/capture tooling tests. Turn identity metadata MUST remain outside model-visible prompt bytes. There is no external API or prompt contract change. Shared combat behavior remains compatible with one-PC and multi-PC parties.
