# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Regression tests for DM Note death-state visibility in tabletop mode."""

import os
import sys
import unittest


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


from utils.multi_pc_dm_note import format_pc_full_stats, format_pc_condensed


def _make_pc(
    name="Test PC",
    hp=20,
    max_hp=20,
    status="alive",
    condition="none",
    conditions=None,
    death_saves=None,
):
    return {
        "character_role": "player",
        "character_type": "player",
        "name": name,
        "type": "player",
        "level": 5,
        "class": "Fighter",
        "hitPoints": hp,
        "maxHitPoints": max_hp,
        "armorClass": 15,
        "status": status,
        "condition": condition,
        "condition_affected": conditions or [],
        "deathSaves": death_saves or {"successes": 0, "failures": 0},
        "abilities": {"strength": 14, "dexterity": 12, "constitution": 13, "intelligence": 10, "wisdom": 12, "charisma": 8},
        "xp": 0,
        "nextLevelXP": 1000,
    }


class TestDmNoteDeathVisibilityFullStats(unittest.TestCase):
    """Task 3.1-3.2: Full PC stats show explicit death status and death saves."""

    def _fs(self, **kw):
        return format_pc_full_stats(_make_pc(**kw), "Test PC", is_active=True)

    def test_full_stats_dead_status_tag(self):
        result = self._fs(hp=0, status="dead", condition="none", conditions=[],
                          death_saves={"successes": 0, "failures": 3})
        self.assertIn("[DEAD]", result)

    def test_full_stats_no_dead_tag_when_alive(self):
        result = self._fs(hp=20, status="alive")
        self.assertNotIn("[DEAD]", result)

    def test_full_stats_shows_death_saves_when_dead(self):
        result = self._fs(hp=0, status="dead", condition="none", conditions=[],
                          death_saves={"successes": 0, "failures": 3})
        self.assertIn("Death Saves:", result)

    def test_full_stats_shows_death_saves_when_unconscious(self):
        result = self._fs(hp=0, status="unconscious", condition="unconscious",
                          conditions=["unconscious"], death_saves={"successes": 1, "failures": 1})
        self.assertIn("Death Saves:", result)

    def test_full_stats_no_death_saves_when_alive(self):
        result = self._fs(hp=20, status="alive")
        self.assertNotIn("Death Saves:", result)


class TestDmNoteDeathVisibilityCondensed(unittest.TestCase):
    """Task 3.3: Condensed PC stats show compact dead/dying status."""

    def _cs(self, **kw):
        return format_pc_condensed(_make_pc(**kw), "Test PC")

    def test_condensed_dead_tag(self):
        result = self._cs(hp=0, status="dead", condition="none", conditions=[],
                          death_saves={"successes": 0, "failures": 3})
        self.assertIn("[DEAD]", result)

    def test_condensed_no_dead_tag_when_alive(self):
        result = self._cs(hp=20, status="alive")
        self.assertNotIn("[DEAD]", result)

    def test_condensed_down_tag_when_unconscious(self):
        result = self._cs(hp=0, status="unconscious", condition="unconscious",
                          conditions=["unconscious"])
        self.assertIn("[DOWN]", result)

    def test_condensed_death_saves_when_dead(self):
        result = self._cs(hp=0, status="dead", condition="none", conditions=[],
                          death_saves={"successes": 0, "failures": 3})
        self.assertIn("DS:", result)

    def test_condensed_no_death_saves_when_alive(self):
        result = self._cs(hp=20, status="alive")
        self.assertNotIn("DS:", result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
