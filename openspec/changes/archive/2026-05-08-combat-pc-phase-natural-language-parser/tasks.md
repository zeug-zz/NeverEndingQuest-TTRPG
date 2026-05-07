    

## 1. Parser Foundation

- [X] 1.1 Add feature flag `COMBAT_PC_PHASE_NL_FAST_PATH` with documented default.
- [X] 1.2 Create a conservative parser helper for PC_PHASE natural-language actions.
- [X] 1.3 Define parse result shape including handled flag, kind, mechanics ops, feedback, narration, ledger event, and fallback reason.
- [X] 1.4 Restrict parser invocation to multi-PC PC_PHASE.

**Verification for 1.1-1.4**: Parser unit tests can exercise pure parse functions without running the full combat loop.

## 2. Weapon Attack Parsing

- [X] 2.1 Detect supplied attack rolls in common forms such as `roll 13`, `13 to hit`, and `attack roll 13`.
- [X] 2.2 Resolve target names through existing combat target resolution.
- [X] 2.3 Resolve weapon/flavor text conservatively.
- [X] 2.4 Apply hit/miss using known AC.
- [X] 2.5 On hit without damage, reuse existing hit-pending-damage behavior and prefill `/dmg`.
- [X] 2.6 On miss, reuse deterministic miss narration path.

**Verification for 2.1-2.6**: Tests cover explicit roll hit, explicit roll miss, missing roll fallback, and ambiguous target fallback.

## 3. Magic Missile Parsing

- [X] 3.1 Detect Magic Missile action text.
- [X] 3.2 Require explicit target-to-damage allocation.
- [X] 3.3 Apply enemy damage through deterministic encounter ops or equivalent helper.
- [X] 3.4 Apply caster spell slot spend through deterministic character ops where supported.
- [X] 3.5 Emit mechanical report and spoken deterministic narration.
- [X] 3.6 Fall back when allocation, target, or spell resource is unclear.

**Verification for 3.1-3.6**: Tests cover one dart each, multiple darts into one target, unclear allocation fallback, and unavailable slot fallback.

## 4. Healing And Movement Parsing

- [X] 4.1 Detect Cure Wounds/direct healing with explicit target and amount.
- [X] 4.2 Apply target healing through deterministic character ops where supported.
- [X] 4.3 Apply caster spell slot spend through deterministic character ops where supported.
- [X] 4.4 Reject or fall back for mechanically dead targets requiring resurrection authority.
- [X] 4.5 Detect movement-only prose and emit narration without mechanical mutation.

**Verification for 4.1-4.5**: Tests cover explicit healing, dead target fallback, and movement-only no-mutation behavior.

## 5. Runtime Integration

- [X] 5.1 Invoke parser before full combat LLM for eligible PC_PHASE prose.
- [X] 5.2 If parser handles action, apply deterministic mutations, emit feedback/narration, record ledger event if available, and continue input loop.
- [X] 5.3 If parser does not handle action, preserve current full combat LLM behavior.
- [X] 5.4 Add telemetry for parser handled/fallback reason.

**Verification for 5.1-5.4**: Integration/source tests prove handled parser cases skip combat LLM and fallback cases still reach existing path.

## 6. Validation

- [X] 6.1 Run `.venv/bin/python -m py_compile` on modified parser and combat manager files.
- [X] 6.2 Run parser unit tests.
- [X] 6.3 Run `.venv/bin/python scripts/test_multi_pc_combat.py`.
- [X] 6.4 Run `.venv/bin/python scripts/c5_regression_combat.py`.
- [X] 6.5 Run `openspec validate combat-pc-phase-natural-language-parser`.
