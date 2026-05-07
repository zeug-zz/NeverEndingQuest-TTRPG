## Why

The combat PC phase enhancement workstream has four active OpenSpec changes plus the archived deterministic death-save change. A follow-up audit found that the implementation is close but still has contract drift in places that normal validation did not catch.

The most important gaps are runtime safety and prompt authority:

- The natural-language PC_PHASE parser feature flag exists but the runtime hook does not check it.
- Unsupported natural-language inputs can fall through into a tuple-unpack crash instead of the full combat LLM fallback.
- Parser-handled actions can print `[ALREADY_APPLIED]` feedback before deterministic mutations are confirmed.
- Magic Missile and healing parsing do not yet prove spell slot availability or authoritative target life state before claiming success.
- Compressed combat prompts still contain residual PC_PHASE and `updateEncounter` wording that contradicts the new phase model.
- Existing source-contract tests mostly prove desired strings exist, but do not reject the old contradictory strings.

This change closes those audit findings before archiving the combat PC phase workstream.

## What Changes

- Enforce the `COMBAT_PC_PHASE_NL_FAST_PATH` flag at the runtime hook.
- Make local combat command handling obey a stable four-value return contract for handled and unhandled commands.
- Reorder parser application so mechanical feedback, spoken narration, and `[ALREADY_APPLIED]` history are emitted only after deterministic mutations succeed.
- Make parser mutation failures fail closed or fall back safely; never claim committed mechanics on failure.
- Harden Magic Missile and healing parser cases around caster spell slots and authoritative target state.
- Remove residual compressed-prompt contradictions around PC_PHASE and `updateEncounter` consolidation.
- Add negative source-contract tests that reject legacy contradictory strings.
- Re-run the four combat PC phase OpenSpec validations plus the archived deterministic death-save spec validation.

## Capabilities

### New Capabilities

- `tt-combat-pc-phase-contract-closure`: Runtime, prompt, and test contracts for the combat PC phase enhancement workstream are closed against audit findings.

### Modified Capabilities

- `tt-combat-pc-natural-action-parser`: Parser enablement, mutation ordering, resource checks, and fallback behavior are made conservative and feature-flag compliant.
- `tt-combat-pc-phase-prompt-contract`: Residual prompt contradictions are removed and locked by negative source-contract tests.
- `tt-combat-pc-phase-deterministic-fast-path`: Command fallback preserves the four-value command result contract.
- `tt-combat-pc-phase-event-ledger`: Parser-driven ledger entries are emitted only for confirmed already-applied mechanics.
- `tt-deterministic-combat-death-saves`: Regression validation remains part of the closure gate because death-save gating precedes PC_PHASE fast paths.

## Non-Goals

- Do not expand the parser beyond the existing supported cases.
- Do not enable the natural-language parser by default.
- Do not add `/end` recap mode, merged round narration, or micro-narration LLM behavior.
- Do not rewrite the combat manager loop beyond the narrow contract fixes.
- Do not archive the four active combat PC phase changes in this change.

## Impact

- **Affected code**: `model_config.py`, `core/managers/combat_manager.py`, `core/managers/multi_pc_combat.py`, `utils/combat_pc_action_parser.py`, combat prompt files, and regression tests.
- **Runtime behavior**: Default behavior is safer because the NL parser remains off unless explicitly enabled; unsupported prose falls back rather than crashing or claiming success.
- **Prompt behavior**: Compressed runtime prompts match the phase authority model without old PC_PHASE continuation language.
- **Risk**: Low-medium. The fixes are contract-closure work, but touch hot combat loop code.

## Fallback Strategy

If parser hardening creates risk, leave `COMBAT_PC_PHASE_NL_FAST_PATH = False` and retain slash-command fast paths. If prompt changes regress ENEMY_PHASE behavior, revert the prompt text only while keeping runtime safety fixes.
