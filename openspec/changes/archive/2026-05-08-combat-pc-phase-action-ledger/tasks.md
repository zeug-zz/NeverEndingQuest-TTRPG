## 1. Ledger Data Model

- [x] 1.1 Add in-memory PC_PHASE ledger storage to `MultiPCCombatManager` or an associated helper.
- [x] 1.2 Define compact event fields for round, sequence id, phase, actor, kind, target, mechanics facts, narration, and `mechanics_already_applied`.
- [x] 1.3 Add bounded event kinds for attack miss, hit pending damage, damage, spell damage, healing, movement, death save, and manual note.
- [x] 1.4 Ensure ledger entries are ASCII-safe and compact.

**Verification for 1.1-1.4**: Unit tests can construct and inspect ledger entries.

## 2. Event Recording

- [x] 2.1 Record `/att` miss events.
- [x] 2.2 Record `/att` hit-pending-damage events.
- [x] 2.3 Record `/dmg` events with HP before/after and status when known.
- [x] 2.4 Record deterministic death save events if applicable.
- [x] 2.5 Avoid duplicate ledger entries for the same command result.

**Verification for 2.1-2.5**: Tests prove one ledger event per deterministic command result.

## 3. Lifecycle And Optional Persistence

- [x] 3.1 Clear or mark ledger state at combat completion.
- [x] 3.2 Group or filter entries by combat round.
- [x] 3.3 Decide whether first implementation persists compact entries to encounter JSON; if yes, keep entries bounded.
- [x] 3.4 Ensure resume behavior remains safe when ledger is absent.

**Verification for 3.1-3.4**: Combat manager tests prove stale facts are not injected into unrelated combat.

## 4. Historical Context Formatting

- [x] 4.1 Add helper to format ledger facts for prompt context.
- [x] 4.2 Label formatted context `HISTORICAL ONLY; DO NOT REPLAY MECHANICS`.
- [x] 4.3 Do not inject formatted context into ENEMY_PHASE by default unless a dependent recap change enables it.

**Verification for 4.1-4.3**: Source/unit tests prove formatted context is replay-safe and disabled by default.

## 5. Validation

- [x] 5.1 Run `.venv/bin/python -m py_compile core/managers/multi_pc_combat.py core/managers/combat_manager.py`.
- [x] 5.2 Run `.venv/bin/python scripts/test_multi_pc_combat.py`.
- [x] 5.3 Run `.venv/bin/python scripts/c5_regression_combat.py`.
- [x] 5.4 Run `openspec validate combat-pc-phase-action-ledger`.
