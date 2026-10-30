# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-tripwire tests for default-off ally rollout gates."""

import unittest
from unittest import mock

import model_config
from core.combat import enemy_batch_apply
from scripts.combat_tactical_test_support import ProviderFreeTestCase


class CombatAllyFlagTests(ProviderFreeTestCase):
    def test_shipped_defaults_are_off_and_inert(self):
        self.assertIs(model_config.COMBAT_ALLY_CONTROLLER_ENABLED, False)
        self.assertIs(model_config.COMBAT_ALLY_PREFETCH_ENABLED, False)
        self.assertFalse(enemy_batch_apply.is_ally_controller_enabled())
        self.assertFalse(enemy_batch_apply.is_ally_prefetch_enabled())

    def test_controller_requires_deterministic_resolver_and_strict_true(self):
        cases = ((False, True, False), (True, 1, False), (True, "true", False), (True, True, True))
        for resolver, controller, expected in cases:
            with self.subTest(resolver=resolver, controller=controller), \
                    mock.patch.object(model_config, "DETERMINISTIC_ENEMY_RESOLUTION_ENABLED", resolver), \
                    mock.patch.object(model_config, "COMBAT_ALLY_CONTROLLER_ENABLED", controller):
                self.assertIs(enemy_batch_apply.is_ally_controller_enabled(), expected)

    def test_prefetch_requires_controller_chain_and_strict_true(self):
        cases = (
            (False, True, True, False),
            (True, False, True, False),
            (True, True, 1, False),
            (True, True, "true", False),
            (True, True, True, True),
        )
        for resolver, controller, prefetch, expected in cases:
            with self.subTest(resolver=resolver, controller=controller, prefetch=prefetch), \
                    mock.patch.object(model_config, "DETERMINISTIC_ENEMY_RESOLUTION_ENABLED", resolver), \
                    mock.patch.object(model_config, "COMBAT_ALLY_CONTROLLER_ENABLED", controller), \
                    mock.patch.object(model_config, "COMBAT_ALLY_PREFETCH_ENABLED", prefetch):
                self.assertIs(enemy_batch_apply.is_ally_prefetch_enabled(), expected)


if __name__ == "__main__":
    unittest.main()
