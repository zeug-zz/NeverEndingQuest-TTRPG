## 1. Runtime Gate And Return Contract

- [x] 1.1 Gate `parse_pc_phase_action(...)` invocation on `COMBAT_PC_PHASE_NL_FAST_PATH`.
- [x] 1.2 Keep `COMBAT_PC_PHASE_NL_FAST_PATH = False` as the documented default.
- [x] 1.3 Ensure `handle_combat_command(...)` returns exactly four values on every path.
- [x] 1.4 Add regression coverage for unhandled command return shape.

**Verification for 1.1-1.4**: Source and unit tests prove the parser hook is flag-gated and unhandled commands return `(None, None, None, False)`.

## 2. Parser Apply Safety

- [x] 2.1 Reorder parser integration so feedback/history/ledger emission happens after deterministic mutation succeeds.
- [x] 2.2 Make `apply_pc_phase_parse_result(...)` report apply failure instead of swallowing update failures as success.
- [x] 2.3 Ensure parser apply failure does not append `[ALREADY_APPLIED]` history.
- [x] 2.4 Ensure parser apply failure does not record ledger facts.
- [x] 2.5 Add regression tests for apply failure behavior using mocked update helpers.

**Verification for 2.1-2.5**: Parser/apply tests prove failed mutation does not claim committed mechanics and does not skip safely into false success.

## 3. Parser Resource And Authority Hardening

- [x] 3.1 For Magic Missile, spend a caster spell slot when availability is proven.
- [x] 3.2 For Magic Missile, fall back when spell slot availability or valid casting source cannot be proven.
- [x] 3.3 For healing, load authoritative target character state for PC/allied NPC targets before ordinary healing is accepted.
- [x] 3.4 For healing, reject or fall back for mechanically dead targets based on authoritative state.
- [x] 3.5 For healing, spend caster spell slot only when available or fall back safely.
- [x] 3.6 Add parser tests for unavailable slot fallback, slot spend success, and dead-target healing fallback.

**Verification for 3.1-3.6**: Parser tests cover successful supported cases and conservative fallback cases without depending on the full combat LLM.

## 4. Prompt Closure

- [x] 4.1 Remove compressed generation prompt wording that says PC_PHASE should continue into enemy or allied NPC turns.
- [x] 4.2 Replace universal compressed generation `EXACTLY ONE updateEncounter` wording with `at most one updateEncounter when enemy state changes exist`.
- [x] 4.3 Remove or qualify compressed validation prompt universal `EXACTLY ONE` wording while preserving examples for multiple-updateEncounter violations.
- [x] 4.4 Preserve ENEMY_PHASE batch strictness and PC/allied vs enemy mutation routing.
- [x] 4.5 Mirror any necessary wording into uncompressed prompts if parity text drifts.

**Verification for 4.1-4.5**: Negative source-contract tests reject old contradictory strings and positive tests still find phase/routing authority.

## 5. Regression And Validation Gates

- [x] 5.1 Add negative source-contract tests for `continue processing remaining NPCs/monsters` and universal `EXACTLY ONE updateEncounter` strings.
- [x] 5.2 Run `.venv/bin/python -m py_compile model_config.py utils/combat_pc_action_parser.py core/managers/combat_manager.py core/managers/multi_pc_combat.py scripts/test_combat_pc_action_parser.py scripts/c5_regression_combat.py scripts/test_multi_pc_combat.py scripts/test_combat_state_coherence_repair.py scripts/test_gpt54_chat_params_contract.py`.
- [x] 5.3 Run `.venv/bin/python scripts/test_combat_pc_action_parser.py`.
- [x] 5.4 Run `.venv/bin/python scripts/test_multi_pc_combat.py`.
- [x] 5.5 Run `.venv/bin/python scripts/c5_regression_combat.py`.
- [x] 5.6 Run `.venv/bin/python scripts/test_combat_state_coherence_repair.py`.
- [x] 5.7 Run `.venv/bin/python scripts/test_gpt54_chat_params_contract.py`.
- [x] 5.8 Run `openspec validate combat-pc-phase-contract-closure`.
- [x] 5.9 Re-run `openspec validate` for `combat-pc-phase-prompt-alignment`, `combat-pc-phase-action-ledger`, `combat-pc-phase-fast-path`, `combat-pc-phase-natural-language-parser`, and `tt-deterministic-combat-death-saves`.

**Verification for 5.1-5.9**: All gates pass before the four active combat PC phase changes are archived.
