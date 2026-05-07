## Why

Multi-PC tabletop combat deliberately gives `PC_PHASE` authority to the human facilitator. The LLM should not be in the hot path for deterministic slash commands whose mechanics Python has already applied.

Today, missed `/att` results and `/dmg` results can still fall through to the full combat LLM and validation flow. This creates visible delay for simple actions, adds provider cost, and risks replay-style interpretation of already-applied mechanics.

The first low-risk improvement is to make deterministic PC commands truly fast: Python applies or confirms mechanics, emits a mechanical report, emits short deterministic DM narration, records a compact event, and waits for the next facilitator input without calling the combat LLM or combat validator.

## What Changes

- Add a feature flag for deterministic PC-phase command narration.
- Add local deterministic narration templates for `/att` misses and `/dmg` results.
- Keep mechanical reports `[skipTTS]` and emit narrative lines separately so DM Voice can speak only the immersive result.
- Bypass full combat LLM and validation for supported deterministic command outcomes when the flag is enabled.
- Preserve current fall-through behavior behind flag-off fallback.
- Add telemetry/source-contract tests proving the fast path does not call combat LLM.

## Capabilities

### New Capabilities

- `tt-combat-pc-phase-deterministic-fast-path`: Deterministic PC-phase command outcomes resolve locally without full combat LLM or validator involvement.

### Modified Capabilities

- `tt-combat-deterministic-command-replay-guard`: Already-applied deterministic command outputs remain unambiguous, now with spoken local narration rather than LLM replay.
- `tt-combat-phase-authority-cleanup`: PC_PHASE remains facilitator-owned and does not require LLM turn progression for deterministic commands.

## Non-Goals

- Do not implement natural-language PC action parsing in this change.
- Do not implement `/end` PC-phase recap or merged PC/enemy narration in this change.
- Do not alter ENEMY_PHASE LLM batch behavior.
- Do not change command syntax for `/att` or `/dmg`.
- Do not remove existing combat validation for normal LLM responses.

## Impact

- **Affected code**: `model_config.py`, `core/managers/multi_pc_combat.py`, `core/managers/combat_manager.py`, combat regression tests.
- **Runtime behavior**: `/att` misses and `/dmg` results should display and narrate immediately in PC_PHASE when the flag is enabled.
- **Backward compatible**: Existing command syntax and LLM fallback remain available with the flag disabled.
- **SP/MP compatibility**: Scope is multi-PC tabletop command handling.
- **Risk**: Low-medium. The mechanics are already Python-owned; risk is mostly UX wording and accidental bypass of needed persistence.

## Fallback Strategy

If deterministic narration feels too bare or causes confusion, disable `COMBAT_FAST_DETERMINISTIC_NARRATION` and restore current fall-through behavior while keeping tests and helpers available for later iteration.
