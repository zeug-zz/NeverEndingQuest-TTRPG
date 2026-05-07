## 1. Configuration And Command Result Contract

- [x] 1.1 Add `COMBAT_FAST_DETERMINISTIC_NARRATION` config flag with documented default.
- [x] 1.2 Define a structured command result contract or minimally extend the existing command return tuple.
- [x] 1.3 Ensure command result contract can represent mechanical feedback, spoken narration, optional history log, and no-LLM terminal handling.

**Verification for 1.1-1.3**: `.venv/bin/python -m py_compile model_config.py core/managers/multi_pc_combat.py core/managers/combat_manager.py` passes.

## 2. Deterministic Narration Helpers

- [x] 2.1 Add deterministic ASCII-only template helper for attack misses.
- [x] 2.2 Add deterministic ASCII-only template helper for damage, bloodied, and defeated results.
- [x] 2.3 Select template variants deterministically from stable event facts rather than global randomness.
- [x] 2.4 Ensure spoken narration never includes `[skipTTS]`.

**Verification for 2.1-2.4**: Unit tests prove deterministic template selection and no non-ASCII output.

## 3. Fast Path Runtime Wiring

- [x] 3.1 Route `/att` miss to mechanical report plus spoken narration when fast path is enabled.
- [x] 3.2 Route `/dmg` to mechanical report plus spoken narration when fast path is enabled.
- [x] 3.3 After fast-path output, continue the combat loop without appending a fresh combat LLM prompt.
- [x] 3.4 Preserve `/att` hit-pending-damage behavior and prefill marker behavior.
- [x] 3.5 Preserve existing LLM fall-through when flag is disabled.

**Verification for 3.1-3.5**: Focused tests prove `/att` miss and `/dmg` do not enter the combat LLM path when enabled.

## 4. Persistence And Replay Safety

- [x] 4.1 Ensure enemy HP/status from `/dmg` remains persisted to encounter data.
- [x] 4.2 Ensure PC/allied NPC target damage still queues/syncs character updates where applicable.
- [x] 4.3 Ensure already-applied markers and replay guards continue to pass existing combat replay tests.

**Verification for 4.1-4.3**: `.venv/bin/python scripts/test_multi_pc_combat.py` and `.venv/bin/python scripts/c5_regression_combat.py` pass.

## 5. Regression And Smoke Coverage

- [x] 5.1 Add tests for `/att` miss fast path output channels.
- [x] 5.2 Add tests for `/dmg` fast path output channels and state mutation.
- [x] 5.3 Add tests proving flag-off preserves pre-existing fall-through behavior.
- [x] 5.4 Run manual or scripted smoke: `/att` miss, `/att` hit plus `/dmg`, `/end` enemy batch still works.
- [x] 5.5 Run `openspec validate combat-pc-phase-fast-path`.
