# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Shared provider-free fixtures for tactical-brain unit tests."""

from __future__ import annotations

import copy
import sys
import types
import unittest
from typing import Any

from scripts import combat_latency_fixtures


class _ProviderTripwire(types.ModuleType):
    """Import sentinel that fails immediately if tactical code reaches an LLM."""

    def __init__(self, module_name: str) -> None:
        super().__init__(module_name)
        self.attempts = 0

        def forbidden_attribute(name: str) -> Any:
            self.attempts += 1
            raise AssertionError("provider boundary accessed: %s.%s" % (module_name, name))

        self.__getattr__ = forbidden_attribute  # type: ignore[method-assign]


PROVIDER_TRIPWIRES = tuple(
    _ProviderTripwire(name)
    for name in ("utils.llm_router", "utils.ai_client_factory")
)
for _tripwire in PROVIDER_TRIPWIRES:
    sys.modules[_tripwire.__name__] = _tripwire


class ProviderFreeTestCase(unittest.TestCase):
    """Fail each test if a provider/router surface was even accessed."""

    def tearDown(self) -> None:
        for tripwire in PROVIDER_TRIPWIRES:
            self.assertEqual(tripwire.attempts, 0, tripwire.__name__)


def build_g5t_scenario(party_size: int = 1) -> dict[str, Any]:
    """Build a fresh resolver input set from the named G5T fixture payload."""
    fixture = copy.deepcopy(
        combat_latency_fixtures.build_g5t_commander_fixture(party_size)
    )
    encounter = fixture["encounter"]
    # Tactical unit cases exercise choice semantics independently of the
    # battle-worn HP profile reserved for end-to-end G5T capture runs.
    for creature in encounter["creatures"]:
        if creature.get("type") == "enemy":
            creature["currentHitPoints"] = creature["maxHitPoints"]
    pc_states = {}
    for creature in encounter["creatures"]:
        if creature["type"] != "player":
            continue
        name = creature["name"]
        state = combat_latency_fixtures._character_payload(
            name, creature["initiative"]
        )
        state["hitPoints"] = creature["currentHitPoints"]
        state["maxHitPoints"] = creature["maxHitPoints"]
        state["armorClass"] = creature["armorClass"]
        pc_states[name] = state

    turn_order = [
        {"name": creature["name"], "kind": creature["type"]}
        for creature in sorted(
            encounter["creatures"],
            key=lambda row: row["initiative"],
            reverse=True,
        )
    ]
    enemy_turn_window = [
        identity for identity in turn_order if identity["kind"] == "enemy"
    ]
    return {
        "encounter": encounter,
        "pc_states": pc_states,
        "monster_definitions": fixture["monster_definitions"],
        "turn_order": turn_order,
        "batch_id": fixture["scenario_id"] + "-batch-1",
        "batch_kind": "enemy_phase",
        "fixture_seed": "tactical-brain-test-seed",
        "enemy_turn_window": enemy_turn_window,
        "tactical_features": fixture["training_pit_area"]["locations"][0][
            "tacticalFeatures"
        ],
    }


def build_menus(scenario: dict[str, Any]) -> Any:
    """Build menus without exposing fixture-only fields to the planner API."""
    from core.combat.tactical_brain import build_tactical_menus

    return build_tactical_menus(
        encounter=scenario["encounter"],
        pc_states=scenario["pc_states"],
        monster_definitions=scenario["monster_definitions"],
        turn_order=scenario["turn_order"],
        batch_id=scenario["batch_id"],
        batch_kind=scenario["batch_kind"],
        fixture_seed=scenario["fixture_seed"],
        enemy_turn_window=scenario["enemy_turn_window"],
        legal_targets=scenario.get("legal_targets"),
        tactical_features=scenario.get("tactical_features"),
    )


def enemy(scenario: dict[str, Any], name: str) -> dict[str, Any]:
    for creature in scenario["encounter"]["creatures"]:
        if creature["type"] == "enemy" and creature["name"] == name:
            return creature
    raise AssertionError("enemy not found: " + name)


def actor_menu(menus: Any, name: str) -> Any:
    for menu in menus.actor_menus:
        if menu.actor.name == name:
            return menu
    raise AssertionError("actor menu not found: " + name)


def option(menu: Any, kind: str, *, feature_id: str | None = None) -> Any:
    for candidate in menu.options:
        if candidate.kind == kind and (
            feature_id is None or candidate.feature_id == feature_id
        ):
            return candidate
    raise AssertionError("option not found: " + kind)


def plan_with_defaults(menus: Any, overrides: dict[str, list[str]] | None = None) -> dict[str, Any]:
    overrides = overrides or {}
    return {
        "choices": [
            {
                "actor": menu.actor.name,
                "option_ids": list(overrides.get(
                    menu.actor.name, menu.default_option_ids
                )),
            }
            for menu in menus.actor_menus
        ],
        "orders": [],
    }
