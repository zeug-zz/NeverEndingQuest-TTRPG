## 1. Compressed Generation Prompt Alignment

- [x] 1.1 Make `@PHASE_MODEL` the single source of PC_PHASE and ENEMY_PHASE authority.
- [x] 1.2 Remove or rewrite PC_PHASE instructions that tell the model to continue to enemy or allied NPC turns.
- [x] 1.3 Add/strengthen rule that PC_PHASE resolves only the active PC action, then stops or requests a roll.
- [x] 1.4 Add/strengthen rule that ENEMY_PHASE resolves enemies plus allied NPCs in batch.
- [x] 1.5 Fix Spirit Guardians or ongoing enemy damage routing to `updateEncounter`.
- [x] 1.6 Fix healing spell wording so spell slot spend can be recorded while HP healing awaits a roll/value.
- [x] 1.7 Strengthen `[ALREADY_APPLIED]` guidance so the model narrates only and emits no duplicate mechanics.

**Verification for 1.1-1.7**: Source-contract tests identify all required compressed prompt clauses.

## 2. Compressed Validation Prompt Alignment

- [x] 2.1 Add explicit PC_PHASE validation branch.
- [x] 2.2 Add explicit ENEMY_PHASE validation branch.
- [x] 2.3 Treat valid `requestRoll`-only PC_PHASE responses as valid pause responses.
- [x] 2.4 Treat narration-only already-applied responses as valid when no duplicate mechanics are emitted.
- [x] 2.5 Replace universal `exactly one updateEncounter` language with `at most one updateEncounter when enemy state changes exist`.
- [x] 2.6 Keep ENEMY_PHASE forbidden-PC-actor validation strict.

**Verification for 2.1-2.6**: Source-contract tests identify validation branch language and no universal exactly-one requirement.

## 3. Uncompressed Prompt Parity

- [x] 3.1 Mirror compressed generation prompt authority into uncompressed generation prompt.
- [x] 3.2 Mirror compressed validation prompt authority into uncompressed validation prompt.
- [x] 3.3 Remove or qualify legacy examples that auto-run a full PC-side round during PC_PHASE.
- [x] 3.4 Remove newly introduced non-ASCII punctuation or glyphs from edited sections.

**Verification for 3.1-3.4**: Prompt parity tests pass and targeted ASCII scan of edited prompt files finds no new non-ASCII.

## 4. Regression Tests

- [x] 4.1 Add prompt-source tests for PC_PHASE active-PC-only wording.
- [x] 4.2 Add prompt-source tests for ENEMY_PHASE batch wording.
- [x] 4.3 Add prompt-source tests for Spirit Guardians/enemy ongoing damage routing.
- [x] 4.4 Add prompt-source tests for healing slot spend plus pending healing value.
- [x] 4.5 Add prompt-source tests for updateEncounter `at most one` wording.
- [x] 4.6 Run `.venv/bin/python scripts/test_combat_runtime_prompt_authority.py` or the nearest current prompt authority suite.
- [x] 4.7 Run `openspec validate combat-pc-phase-prompt-alignment`.
