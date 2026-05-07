# Builder Prompts

## Full Builder Prompt

Implement OpenSpec change `tt-deterministic-combat-death-saves` end-to-end. Do not commit or push.

Goal: Make multi-PC combat death saving throws deterministic in Python at PC phase start. An unstable PC at 0 HP should trigger a Python-authored Dungeon Master narration prompt like `Dungeon Master: Acheron falls still, breath shallow. Acheron needs to roll a death saving throw.` This prompt must be eligible for DM voice/TTS. Inputs such as bare `3`, `I roll 3`, or `/death 3` should be parsed and applied in Python, persisted immediately, and repeated on later PC phases only if still required.

Allowed files:
- `core/managers/multi_pc_combat.py`
- `core/managers/combat_manager.py`
- `prompts/combat/combat_sim_prompt_multipc_compressed.txt` only if minimal prompt alignment is needed
- `prompts/combat/combat_validation_prompt_multipc_compressed.txt` only if minimal validation alignment is needed
- `scripts/test_multi_pc_combat.py`
- `scripts/c5_regression_combat.py`
- narrowly necessary helper/test files if the implementation cannot stay in the listed files

Forbidden:
- Do not redesign initiative, two-group phase start, `/end`, enemy/NPC batch behavior, or single-player combat.
- Do not rely on the LLM to ask for, parse, apply, or persist death saves.
- Do not add new character schema fields unless absolutely necessary and justified.
- Do not write `status: stable` to character JSON because `schemas/char_schema.json` does not allow it.
- Do not use destructive git commands or make commits.

MUST implementation contract:
- Detect all current PC-phase death-save obligations for PCs at `0 HP`, not dead, not stable, and with fewer than three death-save successes/failures.
- Emit deterministic Dungeon Master narration prompts naming each PC that must roll a death saving throw at PC phase start.
- The death-save request prompt must use the normal visible/spoken `Dungeon Master:` output path and must not include `[skipTTS]` or `[SYSTEM]` markers.
- Invalid input, blocked `/end`, and blocked action guidance should remain `[skipTTS]` system-style output because those are mechanical guardrails rather than story narration.
- While this death-save gate is pending, parse valid roll input before any LLM call. Accept at least: bare `3`, `I roll 3`, `roll 3`, `/death 3`, `/ds 3`.
- Interpret bare integer input as a death-save roll only while the deterministic death-save gate is active; outside the gate, preserve existing bare-number input behavior.
- Reject missing, non-integer, and out-of-range roll values with user-safe guidance and no LLM call.
- Apply natural d20 death-save mechanics in Python: `1` = two failures, `2..9` = one failure, `10..19` = one success, `20` = HP 1 and death saves clear.
- Three failures mark mechanical death. Three successes stabilize in combat state and persist schema-valid unconscious/stable-equivalent JSON with `deathSaves.successes == 3`.
- Persist every resolved death-save result immediately. Prefer existing deterministic `update_character_info(..., ops=...)` if it can produce schema-valid results; otherwise add a narrow schema-valid persistence helper using existing safe JSON utilities.
- Track PC-phase cadence so a PC does not roll twice in the same PC phase after resolving their death save, but is prompted again on a later PC phase if still at 0 HP and not stable/dead.
- Block `/att`, `/dmg`, `/end`, and normal action commands while any current PC-phase death-save obligation is unresolved. Preserve normal behavior after obligations are resolved.

SHOULD guidance:
- Keep new logic as small helpers in `MultiPCCombatManager`; keep `combat_manager.py` as a thin input gate.
- Use micro-edits: one logical patch at a time, with `.venv/bin/python -m py_compile <file>` after each touched Python file.
- Prefer in-memory cadence tracking such as `death_save_resolved_phases` over persisted schema changes.
- Keep the death-save request TTS-eligible. Use `[skipTTS]` only for invalid input or blocked-command guidance.

Verification commands:
- `.venv/bin/python -m py_compile core/managers/multi_pc_combat.py core/managers/combat_manager.py`
- `.venv/bin/python scripts/test_multi_pc_combat.py`
- `.venv/bin/python scripts/c5_regression_combat.py`
- `openspec validate tt-deterministic-combat-death-saves`
- `python3 scripts/check_ascii_compliance.py --summary-only` or targeted ASCII check for modified Python files

Report format:
- List modified files.
- Summarize the deterministic death-save flow.
- Report each verification command and pass/fail result.
- Note any intentionally deferred UI prompt/prefill behavior.

## Step 1 Builder Prompt - State Helpers

Implement tasks 1.1-1.5 only for `tt-deterministic-combat-death-saves`.

Allowed: `core/managers/multi_pc_combat.py`, `scripts/test_multi_pc_combat.py`.

Required: add helper methods for current PC-phase pending death-save PC detection, gated roll parsing, deterministic result application, PC-phase cadence tracking, and healing cleanup. Do not edit the combat loop yet. Keep methods unit-testable without Flask or web runtime.

Verify: `.venv/bin/python -m py_compile core/managers/multi_pc_combat.py scripts/test_multi_pc_combat.py` and `.venv/bin/python scripts/test_multi_pc_combat.py`.

## Step 2 Builder Prompt - Persistence

Implement tasks 2.1-2.5 only after Step 1 passes.

Allowed: `core/managers/multi_pc_combat.py`, `updates/update_character_info.py` only if necessary, `scripts/test_multi_pc_combat.py`.

Required: persist death-save results immediately and schema-validly. Natural 20 must persist HP 1 and clear saves. Three failures must persist dead. Three successes must not persist `status: stable`.

Verify: `.venv/bin/python -m py_compile core/managers/multi_pc_combat.py updates/update_character_info.py scripts/test_multi_pc_combat.py` for touched files and `.venv/bin/python scripts/test_multi_pc_combat.py`.

## Step 3 Builder Prompt - Combat Loop Gate

Implement tasks 3.1-3.6 only after Steps 1-2 pass.

Allowed: `core/managers/combat_manager.py`, `core/managers/multi_pc_combat.py`, `scripts/c5_regression_combat.py`, `scripts/test_multi_pc_combat.py`.

Required: at PC phase start and before fast-lane command handling or LLM calls, prompt/gate current PC-phase death-save obligations with TTS-eligible Dungeon Master narration, route valid death-save roll input to Python, reject invalid input with `[skipTTS]` guidance, block `/end` until obligations are resolved, and preserve existing behavior after obligations are resolved and during ENEMY_PHASE.

Verify: `.venv/bin/python -m py_compile core/managers/combat_manager.py core/managers/multi_pc_combat.py scripts/c5_regression_combat.py` and `.venv/bin/python scripts/c5_regression_combat.py`.

## Step 4 Builder Prompt - Prompt Alignment And Final Validation

Implement tasks 4.1-6.5 after Steps 1-3 pass.

Allowed: compressed combat prompt files only if needed, `scripts/test_multi_pc_combat.py`, `scripts/c5_regression_combat.py`.

Required: add minimal prompt/validation wording only if tests show the LLM may duplicate already-applied Python death-save results. Run all final validation commands from tasks section 6.

Verify: `.venv/bin/python scripts/test_multi_pc_combat.py`, `.venv/bin/python scripts/c5_regression_combat.py`, `openspec validate tt-deterministic-combat-death-saves`, and ASCII compliance.
