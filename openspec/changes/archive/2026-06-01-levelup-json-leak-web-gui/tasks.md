## 1. Web Game Loop JSON Parsing

- [x] 1.1 Add JSON parsing to web game loop level-up response handler (`main.py:8476-8554`): detect JSON responses (starts with `{`, ends with `}`), parse with `json.loads()`, extract `narration` field, display only narration text via `print(colored(...))` instead of raw response
- [x] 1.2 Add fallback handling: if JSON parse fails or `narration` key missing, display raw text as-is (intermediate interview steps) or "Level up complete!" (missing narration)
- [x] 1.3 Apply same JSON parsing logic to terminal-only level-up path (`main.py:6764-6907`) for parity
- [x] 1.4 Mark all changes with `# TABLETOP MODE:` comments

## 2. Action Routing Through process_action()

- [x] 2.1 After `LevelUpSession.handle_input()` applies character update, inject the `updateCharacterInfo` action into the main conversation history as a system/assistant message so the standard pipeline records it
- [x] 2.2 Ensure no double character update: `update_character_info()` in `handle_input()` is the authoritative apply point; `process_action()` routing is for conversation history only
- [x] 2.3 Mark all changes with `# TABLETOP MODE:` comments

## 3. Dead Code Removal

- [x] 3.1 Remove `level_up_summaries` injection path at `main.py:4696-4712` (attribute never populated, code unreachable)
- [x] 3.2 Verify no other code references `level_up_summaries` before removal

## 4. Shared Display Filter & Truncated JSON Handling

- [x] 4.1 Add `LevelUpSession.extract_display_text()` static method that parses final JSON, falls back to regex narration extraction for truncated JSON, and falls through to text for intermediate steps
- [x] 4.2 Add `LevelUpSession._looks_like_final_update_response()` to detect malformed final action envelopes
- [x] 4.3 Add automatic compact correction path: when malformed final JSON is detected, ask the model to re-emit compact valid JSON instead of treating it as interview prose
- [x] 4.4 Replace duplicated inline JSON parsing in both level-up loops with `extract_display_text()` calls
- [x] 4.5 Remove local `import json` shadowing from `main.py` to fix `NameError` on `/levelup` crash

## 5. /levelup [character] Support

- [x] 5.1 Add `find_character_file_fuzzy` import to main.py module level
- [x] 5.2 Change `/levelup` command to accept optional character argument (`/levelup Kira`)
- [x] 5.3 Fall back to active_character when no argument given (backward compatible)
- [x] 5.4 Update help text to show `[character]` parameter

## 6. HP Reconciliation on Level-Up

- [x] 6.1 Add `_safe_int()` static helper to `LevelUpSession`
- [x] 6.2 Add `_normalize_level_up_hit_points()` that increases current HP with max HP gain while preserving damage deficit
- [x] 6.3 Do not revive dead or zero-HP characters
- [x] 6.4 Keep no-op when max HP does not increase
- [x] 6.5 Wire HP normalization into `_normalize_final_level_up_changes()`

## 7. Prompt Contract Tightening

- [x] 7.1 Update `prompts/leveling/level_up_system_prompt.txt` to include `hitPoints` in example JSON when max HP increases
- [x] 7.2 Add guidance sentence about HP normalization

## 8. Regression Tests

- [x] 8.1 Create `scripts/test_levelup_json_web_output.py` with 13 tests: JSON parsing, raw JSON suppression, plain text passthrough, malformed JSON fallback, missing narration, whitespace tolerance, terminal/web parity, newline tolerance, curly braces, truncated JSON extraction, shared display filter, `/levelup [character]` argument, malformed correction path
- [x] 8.2 Create `scripts/test_levelup_hp_reconciliation.py` with 6 tests: full HP remains full, wounded preserves deficit, zero HP not revived, dead not revived, no change when max HP unchanged, no JSON shadowing in main_game_loop
- [x] 8.3 Verify all tests pass

## 9. Verification

- [x] 9.1 Compile check: `.venv/bin/python -m py_compile main.py core/managers/level_up_manager.py`
- [x] 9.2 Run all level-up tests: JSON web output (13), HP reconciliation (6), XP invariants (6)
- [x] 9.3 ASCII compliance: 0 violations
- [x] 9.4 `git diff --check`: clean
- [x] 9.5 OpenSpec validation
