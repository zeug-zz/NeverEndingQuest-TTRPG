## Why

Multi-PC combat already tracks incapacitated PCs and has deterministic death-save mechanics in Python, but the runtime still relies on the LLM turn cycle to ask for and interpret death saving throws. This can produce inconsistent cadence: a PC at 0 HP may need a death saving throw, the user may type `I roll 3`, and the LLM may or may not emit the correct `updateCharacterInfo` action before the next round.

This violates the project authority rule: Python enforces mechanical reality; the LLM interprets it. Death saves are mechanical state and should not depend on the narrator model.

## What Changes

- Add a deterministic combat-loop death-save gate for PCs at 0 HP who still need death saves.
- Emit deterministic DM-continuity narration such as `Acheron falls still, breath shallow. Acheron needs to roll a death saving throw.` when the gate is active.
- Accept bare-number, natural-language, and command-style roll inputs without calling the LLM.
- Apply the death-save result in Python using existing 5e mechanics.
- Persist death-save counters, death, stabilization, or natural-20 recovery through deterministic character state updates.
- Ensure unstable 0-HP PCs are prompted at the start of each PC phase until stable, dead, or healed.

## Capabilities

### New Capabilities

- `tt-deterministic-combat-death-saves`: Python owns PC-phase-start death-save prompting, roll parsing, result application, persistence, and per-round cadence during multi-PC combat.

### Modified Capabilities

- `tt-combat-runtime-prompt-authority`: Combat prompt context may still show death-save state, but the mechanical death-save roll cycle is resolved before LLM narration.
- `tt-combat-phase-sync`: Incapacitated PCs remain part of PC phase only for deterministic death-save resolution, not normal attacks or damage commands.
- `tt-combat-structured-character-ops-routing`: Existing structured death-save ops remain valid and are reused for persistence where practical.

## Non-Goals

- Do not redesign initiative or the two-group phase model.
- Do not change enemy/NPC batch behavior.
- Do not make the LLM roll, interpret, or persist death saves.
- Do not add a new character schema field unless absolutely required; prefer in-memory per-combat cadence tracking.
- Do not change single-player combat behavior unless an existing shared helper requires a harmless compatibility guard.
- Do not implement UI dice buttons in this change.

## Impact

- **Affected code**: `core/managers/multi_pc_combat.py`, `core/managers/combat_manager.py`, focused combat tests, and optional prompt source-contract text.
- **Runtime behavior**: At PC phase start, each unstable 0-HP PC gets a deterministic Python-authored Dungeon Master prompt that is eligible for DM voice/TTS. LLM generation is bypassed for death-save roll input and resumes only after all current PC-phase death-save obligations have been committed.
- **Backward compatible**: Existing `/att`, `/dmg`, `/end`, and structured character ops remain unchanged.
- **SP/MP compatibility**: Scope is multi-PC combat manager path. Single-player combat should remain unchanged.
- **Rollout risk**: Medium. The combat loop is hot-path code. Mitigation is micro-edits, compile checks, and targeted regression coverage.

## Fallback Strategy

If the input gate is too broad, narrow accepted roll parsing to `/death <1-20>` and `/ds <1-20>` while keeping Python result application and PC-phase-start prompts. If cadence tracking causes phase issues, keep death-save prompting tied to PC phase entry rather than individual initiative turns. If persistence via structured ops fails in edge cases, add a small dedicated persistence helper that writes the same schema-valid fields with `safe_write_json`.
