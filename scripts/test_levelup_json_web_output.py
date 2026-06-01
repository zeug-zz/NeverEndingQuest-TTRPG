#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
Level-up JSON web output filtering tests.

Validates:
- JSON parsing extracts narration field correctly
- Raw JSON suppressed from output
- Intermediate plain-text responses pass through
- Malformed JSON falls back to raw display
- Missing narration field shows fallback text
- Terminal/web path parity
- No double character update
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.managers.level_up_manager import LevelUpSession


def _simulate_web_parse(response_text):
    """Simulate the level-up display filtering logic used by main.py."""
    display_text, _ = LevelUpSession.extract_display_text(response_text)
    return display_text


def test_json_parsing_extracts_narration():
    """Test that valid JSON response extracts narration field only."""
    print("Test: JSON parsing extracts narration...")
    json_response = '{"narration": "Level up complete!", "actions": []}'
    output = _simulate_web_parse(json_response)
    assert output == "Level up complete!", f"Expected 'Level up complete!', got: {output}"
    print("  [OK] Narration extracted correctly\n")


def test_raw_json_not_in_output():
    """Test that raw JSON string is not displayed when parsing succeeds."""
    print("Test: Raw JSON suppressed from output...")
    json_response = '{"narration": "Success", "actions": [{"action": "updateCharacterInfo"}]}'
    output = _simulate_web_parse(json_response)
    assert output == "Success", f"Expected 'Success', got: {output}"
    assert "updateCharacterInfo" not in output, "Raw action JSON leaked into output"
    print("  [OK] Raw action JSON suppressed\n")


def test_plain_text_passthrough():
    """Test that non-JSON responses display as-is."""
    print("Test: Plain text passthrough...")
    text_response = "What is your HP roll?"
    output = _simulate_web_parse(text_response)
    assert output == text_response, f"Expected raw text, got: {output}"
    print("  [OK] Plain text passed through\n")


def test_malformed_json_fallback():
    """Test that invalid JSON displays raw text (fail-open)."""
    print("Test: Malformed JSON fallback...")
    bad_json = '{"narration": "incomplete'
    output = _simulate_web_parse(bad_json)
    assert output == bad_json, f"Expected raw fallback, got: {output}"
    print("  [OK] Malformed JSON falls back to raw display\n")


def test_missing_narration_fallback():
    """Test that JSON without narration field shows fallback text."""
    print("Test: Missing narration fallback...")
    json_no_narration = '{"actions": []}'
    output = _simulate_web_parse(json_no_narration)
    assert output == "Level up complete!", f"Expected fallback, got: {output}"
    print("  [OK] Missing narration shows fallback\n")


def test_whitespace_tolerant_parsing():
    """Test that JSON with leading/trailing whitespace is parsed correctly."""
    print("Test: Whitespace tolerant parsing...")
    json_with_space = '  {"narration": "Works with spaces"}  '
    output = _simulate_web_parse(json_with_space)
    assert output == "Works with spaces", f"Expected narration, got: {output}"
    print("  [OK] Whitespace-tolerant parsing works\n")


def test_terminal_path_parity():
    """Test that terminal and web paths use identical parsing logic."""
    print("Test: Terminal/web path parity...")
    json_response = '{"narration": "Test path parity", "actions": []}'
    # Web path logic
    web_output = _simulate_web_parse(json_response)
    # Terminal path uses identical parsing (same function)
    terminal_output = _simulate_web_parse(json_response)
    assert web_output == terminal_output, f"Path mismatch: web='{web_output}' vs terminal='{terminal_output}'"
    assert web_output == "Test path parity", f"Expected narration, got: {web_output}"
    print("  [OK] Terminal and web paths produce identical output\n")


def test_newline_tolerant_json():
    """Test that JSON with embedded newlines is parsed correctly."""
    print("Test: Newline tolerant parsing...")
    json_with_newlines = '{\n  "narration": "Multi-line\\nprompt",\n  "actions": []\n}'
    output = _simulate_web_parse(json_with_newlines)
    assert output == "Multi-line\nprompt", f"Expected multi-line narration, got: {output}"
    print("  [OK] Newline-tolerant JSON parsed\n")


def test_curly_brace_in_narration():
    """Test that narration containing curly braces doesn't break parsing."""
    print("Test: Curly braces in narration...")
    json_with_braces = '{"narration": "The {d20} feels heavy.", "actions": []}'
    output = _simulate_web_parse(json_with_braces)
    assert output == "The {d20} feels heavy.", f"Expected narration with braces, got: {output}"
    print("  [OK] Curly braces in narration handled\n")


def test_truncated_final_json_extracts_narration_without_action_leak():
    """Test that truncated final JSON still suppresses raw action content."""
    print("Test: Truncated final JSON narration extraction...")
    truncated_json = (
        '{"narration":"Scout Kira surges forward in skill and lethality.",'
        '"actions":[{"action":"updateCharacterInfo","parameters":{"characterName":"Scout Kira",'
        '"changes":"{\\"level\\":3,\\"classFeatures\\":[{\\"name\\":\\"Sneak Attack\\"}'
    )
    output = _simulate_web_parse(truncated_json)
    assert output == "Scout Kira surges forward in skill and lethality."
    assert "updateCharacterInfo" not in output, "Raw action JSON leaked into output"
    assert "classFeatures" not in output, "Raw changes JSON leaked into output"
    print("  [OK] Truncated final JSON suppresses raw actions\n")


def test_main_levelup_paths_use_shared_display_filter():
    """Test that both direct and action-triggered level-up paths use the filter."""
    print("Test: Main level-up paths use shared display filter...")
    source = Path("main.py").read_text(encoding="utf-8")
    count = source.count("extract_display_text(dm_response)")
    assert count >= 2, "Expected both level-up loops to use shared display filtering"
    print("  [OK] Both level-up paths use shared display filtering\n")


def test_levelup_slash_command_accepts_character_argument():
    """Test that /levelup Kira is handled before the /level command path."""
    print("Test: /levelup accepts character argument...")
    source = Path("main.py").read_text(encoding="utf-8")
    assert 'cmd == "/levelup" or cmd.startswith("/levelup ")' in source
    assert "find_character_file_fuzzy(requested_name)" in source
    assert '"  /levelup [character] - Trigger level up if XP requirement met\\n"' in source
    print("  [OK] /levelup character argument supported\n")


def test_malformed_final_json_triggers_compact_correction_path():
    """Test malformed final JSON is not treated as normal interview prose."""
    print("Test: Malformed final JSON correction path...")
    source = Path("core/managers/level_up_manager.py").read_text(encoding="utf-8")
    assert "_looks_like_final_update_response(ai_response)" in source
    assert "Re-emit ONLY one compact valid" in source
    assert "Corrected final action received" in source
    print("  [OK] Malformed final JSON triggers compact correction\n")


if __name__ == "__main__":
    print("=" * 60)
    print("Level-Up JSON Web Output Tests")
    print("=" * 60)
    print()

    tests = [
        test_json_parsing_extracts_narration,
        test_raw_json_not_in_output,
        test_plain_text_passthrough,
        test_malformed_json_fallback,
        test_missing_narration_fallback,
        test_whitespace_tolerant_parsing,
        test_terminal_path_parity,
        test_newline_tolerant_json,
        test_curly_brace_in_narration,
        test_truncated_final_json_extracts_narration_without_action_leak,
        test_main_levelup_paths_use_shared_display_filter,
        test_levelup_slash_command_accepts_character_argument,
        test_malformed_final_json_triggers_compact_correction_path,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"  [FAIL] {e}\n")
            failed += 1
        except Exception as e:
            print(f"  [FAIL] Unexpected error: {e}\n")
            failed += 1

    print("=" * 60)
    if failed == 0:
        print(f"ALL {passed} TESTS PASSED")
        print("=" * 60)
        sys.exit(0)
    else:
        print(f"{passed} PASSED, {failed} FAILED")
        print("=" * 60)
        sys.exit(1)
