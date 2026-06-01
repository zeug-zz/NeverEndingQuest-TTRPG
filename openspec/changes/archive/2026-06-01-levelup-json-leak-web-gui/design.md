## Context

The `\levelup` command uses a dedicated `LevelUpSession` (`core/managers/level_up_manager.py`) that conducts an interactive interview with a separate LLM call chain and its own conversation history file (`level_up_conversation.json`). The session correctly parses the final JSON response containing `updateCharacterInfo` and applies changes via `update_character_info()`. However, the raw JSON string is returned to the caller and displayed in the web GUI chat via `WebOutputCapture`.

The web game loop (`main.py:8476-8554`) catches the `enter_levelup_mode` status from `process_action()` and enters an `input()`-based sub-loop. Output from this sub-loop goes through `print()` → `sys.stdout` → `WebOutputCapture`, which emits the raw text to the web GUI without filtering.

The standard action handler pipeline (`process_action()` in `main.py`) is not used for level-up character updates — they go directly through `update_character_info()` in `LevelUpSession.handle_input()`.

## Goals / Non-Goals

**Goals:**
- Prevent raw JSON from appearing in web GUI chat during level-up finalization
- Route level-up `updateCharacterInfo` actions through the standard `process_action()` pipeline for consistent validation and persistence
- Remove dead `level_up_summaries` code path
- Maintain backward compatibility with terminal-only level-up flow
- Add regression tests for JSON parsing and web output filtering

**Non-Goals:**
- Changing the level-up interview flow or LLM prompt
- Modifying the level-up validation LLM call
- Adding new level-up features or capabilities
- Refactoring the `LevelUpSession` class architecture

## Decisions

### Decision 1: Parse JSON in the web game loop, not in `handle_input()`

**Choice:** Keep `handle_input()` returning the raw response string. Parse the JSON in the web game loop caller (`main.py:8476-8554`) to extract `narration` for display.

**Rationale:** `handle_input()` already correctly parses the JSON internally to apply character updates. Changing its return type would require updating both the terminal and web callers. Instead, the web game loop caller parses the response before displaying it, extracting only the `narration` field.

**Alternative considered:** Return a structured dict from `handle_input()` with `narration` and `actions_applied` fields. Rejected because it changes the API contract for both callers when only the web path has the display bug.

### Decision 2: Route `updateCharacterInfo` through `process_action()` after extraction

**Choice:** After `handle_input()` applies the character update via `update_character_info()`, also inject the action into the main conversation history as a processed action so the standard pipeline records it.

**Rationale:** The standard `process_action()` pipeline handles validation, persistence, conversation history injection, and UI state updates. By routing the level-up action through this pipeline, we ensure consistent behavior with combat/narrator character updates.

**Alternative considered:** Keep the direct `update_character_info()` call and add separate conversation history injection. Rejected because it duplicates logic already in `process_action()` and risks divergence.

### Decision 3: Fail-open on JSON parse failure

**Choice:** If the level-up response cannot be parsed as JSON (e.g., LLM returns plain text), display it as-is (current behavior for intermediate interview steps).

**Rationale:** Intermediate interview steps (HP roll, fighting style choice) return plain text, not JSON. The JSON parse must only apply to the final confirmation response. A parse failure means the response is an intermediate step, not the final action.

### Decision 4: Remove dead `level_up_summaries` code

**Choice:** Delete the `level_up_summaries` injection path at `main.py:4696-4712`.

**Rationale:** The attribute is never populated on `action_handler.process_action`, making this code unreachable. Removing it reduces maintenance burden and confusion.

## Risks / Trade-offs

- **[Risk] LLM returns JSON during intermediate step** → Mitigation: `_extract_update_action()` already checks for `updateCharacterInfo` action presence. Only responses containing this action trigger the finalization path.
- **[Risk] Double character update if both `handle_input()` and `process_action()` apply changes** → Mitigation: `handle_input()` applies the update; `process_action()` is used only for conversation history injection and UI state sync, not for re-applying the character change.
- **[Risk] Terminal-only level-up path regression** → Mitigation: Terminal path (`main.py:6764-6907`) uses the same `handle_input()` return value and same JSON parsing logic. Tests cover both paths.
- **[Trade-off] Minimal code change vs. architectural refactor** → Chose minimal change. A full refactor of `LevelUpSession` to use the standard action pipeline would be cleaner but is out of scope for this bug fix.
