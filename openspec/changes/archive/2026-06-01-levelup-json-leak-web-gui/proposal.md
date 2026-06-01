## Why

The `\levelup` command leaks raw JSON (`updateCharacterInfo` action) into the web GUI chat instead of applying it as a character update. Players see the full JSON blob displayed as chat text, breaking immersion and preventing the character update from being applied through the standard action handler pipeline.

**Root cause:** `LevelUpSession.handle_input()` correctly parses the JSON and calls `update_character_info()`, but returns the raw JSON string to the caller. The web game loop (`main.py:8476-8554`) displays this via `print()` → `WebOutputCapture`, leaking the raw JSON into chat. Additionally, the level-up path bypasses the normal `process_action()` pipeline, so character updates aren't routed through the standard validation/persistence path.

## What Changes

- **Fix web output path**: Parse level-up JSON response in the web game loop, extract `narration` field only for display, suppress raw JSON from reaching `WebOutputCapture`
- **Route through standard action handler**: When level-up JSON contains `updateCharacterInfo` action, route it through `process_action()` to ensure character updates follow the same validation/persistence path as combat/narrator updates
- **Remove dead code**: Delete the `level_up_summaries` injection path (`main.py:4696-4712`) which is never populated
- **Add regression tests**: Test JSON parsing, web output filtering, action routing, and intermediate interview step handling

## Capabilities

### New Capabilities
- `levelup-web-output-filtering`: Parse level-up LLM JSON responses in the web game loop and extract only the `narration` field for display, preventing raw JSON from leaking into chat
- `levelup-action-routing`: Route level-up `updateCharacterInfo` actions through the standard `process_action()` pipeline to ensure consistent validation and persistence

### Modified Capabilities
(No existing capability requirements are changing — this is a bug fix within existing level-up flow)

## Impact

**Code:**
- `core/managers/level_up_manager.py` — `handle_input()` return value structure
- `main.py:8476-8554` — web game loop level-up response handling
- `main.py:4696-4712` — dead `level_up_summaries` code removal
- `core/ai/action_handler.py` — level-up action routing (if needed)

**APIs:** No external API changes

**Dependencies:** None

**Systems:** Web GUI chat display, character state persistence

**Merge safety:** Minimal — changes are isolated to level-up path, marked with `# TABLETOP MODE:` comments, and preserve upstream behavior for single-player mode

**SP/MP compatibility:** No impact — level-up flow works identically in both modes

**Rollout risk:** Low — narrow bug fix with clear root cause and regression tests

**Fallback strategy:** If JSON parsing fails, fall back to displaying raw response (current broken behavior) rather than crashing

**Provider outage behavior:** No LLM provider changes — bug is in response handling, not LLM calls
