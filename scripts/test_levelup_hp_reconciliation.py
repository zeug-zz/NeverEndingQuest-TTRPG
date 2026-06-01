#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root

"""
Level-up HP reconciliation regression tests.

Validates:
- Full characters remain full when max HP increases.
- Wounded characters preserve damage deficit.
- Zero-HP/dead characters are not revived by level-up normalization.
- main.py does not shadow module-level json inside main_game_loop.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.managers.level_up_manager import LevelUpSession


def _make_session(character_data, new_level=2):
    session = object.__new__(LevelUpSession)
    session.character_name = character_data.get("name", "Test")
    session.current_level = new_level - 1
    session.new_level = new_level
    session.character_data = character_data
    return session


def _normalize(character_data, changes, new_level=2):
    session = _make_session(character_data, new_level=new_level)
    return json.loads(session._normalize_final_level_up_changes(changes))


def test_full_hp_remains_full_after_max_hp_gain():
    result = _normalize(
        {
            "name": "Blairen",
            "status": "alive",
            "hitPoints": 9,
            "maxHitPoints": 9,
            "experience_points": 415,
        },
        {"maxHitPoints": 21, "experience_points": 0},
        new_level=2,
    )

    assert result["maxHitPoints"] == 21
    assert result["hitPoints"] == 21
    assert result["level"] == 2
    assert result["exp_required_for_next_level"] == 900
    assert "experience_points" not in result


def test_wounded_hp_preserves_damage_deficit_after_max_hp_gain():
    result = _normalize(
        {
            "name": "Wounded Fighter",
            "status": "alive",
            "hitPoints": 4,
            "maxHitPoints": 9,
        },
        {"maxHitPoints": 21},
        new_level=2,
    )

    assert result["maxHitPoints"] == 21
    assert result["hitPoints"] == 16


def test_zero_hp_character_not_revived_by_level_up_hp_gain():
    result = _normalize(
        {
            "name": "Unconscious Fighter",
            "status": "unconscious",
            "hitPoints": 0,
            "maxHitPoints": 9,
        },
        {"maxHitPoints": 21},
        new_level=2,
    )

    assert result["maxHitPoints"] == 21
    assert "hitPoints" not in result


def test_dead_character_not_revived_by_level_up_hp_gain():
    result = _normalize(
        {
            "name": "Dead Fighter",
            "status": "dead",
            "hitPoints": 0,
            "maxHitPoints": 9,
        },
        {"maxHitPoints": 21},
        new_level=2,
    )

    assert result["maxHitPoints"] == 21
    assert "hitPoints" not in result


def test_no_hp_change_when_max_hp_not_increased():
    result = _normalize(
        {
            "name": "Stable Fighter",
            "status": "alive",
            "hitPoints": 9,
            "maxHitPoints": 9,
        },
        {"maxHitPoints": 9},
        new_level=2,
    )

    assert result["maxHitPoints"] == 9
    assert "hitPoints" not in result


def test_main_game_loop_does_not_shadow_json_import():
    source = Path("main.py").read_text(encoding="utf-8")
    start = source.index("def main_game_loop")
    main_loop_source = source[start:]

    assert "\n                import json\n" not in main_loop_source
    assert "\n                import json\r\n" not in main_loop_source


if __name__ == "__main__":
    tests = [
        test_full_hp_remains_full_after_max_hp_gain,
        test_wounded_hp_preserves_damage_deficit_after_max_hp_gain,
        test_zero_hp_character_not_revived_by_level_up_hp_gain,
        test_dead_character_not_revived_by_level_up_hp_gain,
        test_no_hp_change_when_max_hp_not_increased,
        test_main_game_loop_does_not_shadow_json_import,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            print(f"[OK] {test.__name__}")
            passed += 1
        except Exception as exc:
            print(f"[FAIL] {test.__name__}: {exc}")
            failed += 1

    if failed:
        print(f"{passed} passed, {failed} failed")
        sys.exit(1)

    print(f"ALL {passed} TESTS PASSED")
