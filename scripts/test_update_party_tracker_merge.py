# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
Test suite for updatePartyTracker merge behavior (Prompt 5 functional tests).

This module tests the _merge_party_tracker_updates helper to ensure
peaceful resolution markers and other special keys are persisted correctly.
"""

import unittest
import sys
import os

# Ensure we can import from utils
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.action_normalization import normalize_action_list_for_authority
from utils.party_tracker_merge import PartyTrackerMergeError, _merge_party_tracker_updates


class TestDirectKeyMerge(unittest.TestCase):
    """Test cases for direct resolvedHostilesByLocation key merge."""

    def test_direct_key_merges_with_existing_markers(self):
        """Test 1: Direct key merge preserves existing markers and adds new."""
        # Setup: existing state has V03 resolved
        current_data = {
            "module": "TestModule",
            "worldConditions": {
                "currentLocationId": "V03",
                "resolvedHostilesByLocation": {"V03": True}
            }
        }
        
        # Add V04 as new resolution
        parameters = {"resolvedHostilesByLocation": {"V04": True}}
        
        # Execute
        result = _merge_party_tracker_updates(current_data, parameters)
        
        # Assertions: Both V03 and V04 present
        markers = result["worldConditions"]["resolvedHostilesByLocation"]
        self.assertIn("V03", markers)
        self.assertIn("V04", markers)
        self.assertTrue(markers["V03"])
        self.assertTrue(markers["V04"])

    def test_direct_key_creates_world_conditions_if_missing(self):
        """Test 2: Direct key creates worldConditions if not present."""
        current_data = {"module": "TestModule"}
        parameters = {"resolvedHostilesByLocation": {"V05": True}}
        
        result = _merge_party_tracker_updates(current_data, parameters)
        
        # Assertions: worldConditions created with marker
        self.assertIn("worldConditions", result)
        self.assertIn("resolvedHostilesByLocation", result["worldConditions"])
        self.assertTrue(result["worldConditions"]["resolvedHostilesByLocation"]["V05"])


class TestNestedWorldConditionsMerge(unittest.TestCase):
    """Test cases for nested worldConditions dict merge."""

    def test_nested_world_conditions_merges_location_markers(self):
        """Test 3: Nested worldConditions merge preserves existing and adds new."""
        # Setup: existing V03 resolved
        current_data = {
            "module": "TestModule",
            "worldConditions": {
                "resolvedHostilesByLocation": {"V03": True}
            }
        }
        
        # Add V05 via nested worldConditions
        parameters = {
            "worldConditions": {
                "resolvedHostilesByLocation": {"V05": True}
            }
        }
        
        result = _merge_party_tracker_updates(current_data, parameters)
        
        # Assertions: Both markers present
        markers = result["worldConditions"]["resolvedHostilesByLocation"]
        self.assertIn("V03", markers)
        self.assertIn("V05", markers)

    def test_nested_world_conditions_preserves_other_keys(self):
        """Test 4: Nested merge preserves unrelated worldConditions keys."""
        current_data = {
            "module": "TestModule",
            "worldConditions": {
                "currentLocationId": "V03",
                "weather": "foggy",
                "resolvedHostilesByLocation": {"V03": True}
            }
        }
        
        # Add new marker
        parameters = {
            "worldConditions": {
                "resolvedHostilesByLocation": {"V04": True}
            }
        }
        
        result = _merge_party_tracker_updates(current_data, parameters)
        
        # Assertions: All original keys preserved
        wc = result["worldConditions"]
        self.assertEqual(wc["currentLocationId"], "V03")
        self.assertEqual(wc["weather"], "foggy")
        self.assertIn("V03", wc["resolvedHostilesByLocation"])
        self.assertIn("V04", wc["resolvedHostilesByLocation"])


class TestPreserveUnrelatedKeys(unittest.TestCase):
    """Test cases for preserving unrelated worldConditions keys."""

    def test_location_keys_preserved_during_resolution_update(self):
        """Test 5: Location keys preserved when adding resolution markers."""
        current_data = {
            "module": "TestModule",
            "worldConditions": {
                "currentLocationId": "V04",
                "currentLocation": "Petitioner's Rest",
                "currentAreaId": "BOO001",
                "currentArea": "Fields of Supplication",
                "weather": "misty"
            }
        }
        
        parameters = {"resolvedHostilesByLocation": {"V04": True}}
        
        result = _merge_party_tracker_updates(current_data, parameters)
        
        # Assertions: All location context preserved
        wc = result["worldConditions"]
        self.assertEqual(wc["currentLocationId"], "V04")
        self.assertEqual(wc["currentLocation"], "Petitioner's Rest")
        self.assertEqual(wc["currentAreaId"], "BOO001")
        self.assertEqual(wc["currentArea"], "Fields of Supplication")
        self.assertEqual(wc["weather"], "misty")
        self.assertTrue(wc["resolvedHostilesByLocation"]["V04"])


class TestSpecialKeyBehavior(unittest.TestCase):
    """Test cases for special key handling."""

    def test_location_keys_go_to_world_conditions(self):
        """Test 6: Location keys persist under worldConditions."""
        current_data = {"module": "TestModule"}
        parameters = {
            "currentLocationId": "V06",
            "currentLocation": "Threshing Floor",
            "currentAreaId": "BOO002",
            "currentArea": "Heart of Fields"
        }
        
        result = _merge_party_tracker_updates(
            current_data,
            parameters,
            current_module="TestModule",
            allow_same_module_location_write=True,
        )
        
        # Assertions: All location keys in worldConditions
        wc = result["worldConditions"]
        self.assertEqual(wc["currentLocationId"], "V06")
        self.assertEqual(wc["currentLocation"], "Threshing Floor")
        self.assertEqual(wc["currentAreaId"], "BOO002")
        self.assertEqual(wc["currentArea"], "Heart of Fields")

    def test_module_key_goes_top_level(self):
        """Test 7: Module key persists at top level."""
        current_data = {"module": "OldModule"}
        parameters = {"module": "NewModule"}
        
        result = _merge_party_tracker_updates(current_data, parameters)
        
        self.assertEqual(result["module"], "NewModule")


class TestBackwardCompatibility(unittest.TestCase):
    """Test cases for backward compatibility with unknown keys."""

    def test_unknown_keys_persist_top_level(self):
        """Test 8: Unknown keys go to top level (existing behavior)."""
        current_data = {"module": "TestModule"}
        parameters = {
            "customField": "customValue",
            "partySize": 4,
            "sessionGold": 125
        }
        
        result = _merge_party_tracker_updates(current_data, parameters)
        
        # Assertions: Unknown keys at top level
        self.assertEqual(result["customField"], "customValue")
        self.assertEqual(result["partySize"], 4)
        self.assertEqual(result["sessionGold"], 125)
        # module preserved
        self.assertEqual(result["module"], "TestModule")


class TestEdgeCases(unittest.TestCase):
    """Test edge cases and error handling."""

    def test_empty_parameters_returns_unchanged(self):
        """Test 9: Empty parameters returns data unchanged."""
        current_data = {
            "module": "TestModule",
            "worldConditions": {"currentLocationId": "V01"}
        }
        parameters = {}
        
        result = _merge_party_tracker_updates(current_data, parameters)
        
        self.assertEqual(result, current_data)

    def test_non_dict_resolved_hostiles_overwrites(self):
        """Test 10: Non-dict value for resolvedHostilesByLocation overwrites."""
        current_data = {
            "module": "TestModule",
            "worldConditions": {
                "resolvedHostilesByLocation": {"V03": True}
            }
        }
        # Invalid: string instead of dict
        parameters = {"resolvedHostilesByLocation": "invalid"}
        
        result = _merge_party_tracker_updates(current_data, parameters)
        
        # Assertions: Overwrites with invalid value (graceful handling)
        self.assertEqual(result["worldConditions"]["resolvedHostilesByLocation"], "invalid")

    def test_non_dict_world_conditions_overwrites(self):
        """Test 11: Non-dict value for worldConditions overwrites entirely."""
        current_data = {
            "module": "TestModule",
            "worldConditions": {"currentLocationId": "V01"}
        }
        # Unexpected: string instead of dict
        parameters = {"worldConditions": "cleared"}
        
        result = _merge_party_tracker_updates(current_data, parameters)
        
        # Assertions: Replaces entirely
        self.assertEqual(result["worldConditions"], "cleared")


class TestActionAuthorityNormalization(unittest.TestCase):
    """Tests for updatePartyTracker same-module authority normalization."""

    def test_no_module_location_tracker_converts_to_transition(self):
        actions = [
            {
                "action": "updatePartyTracker",
                "parameters": {"currentLocationId": "NC05"},
            }
        ]
        party_state = {
            "module": "The_Thornwood_Watch",
            "worldConditions": {"currentLocationId": "NC02"},
        }

        normalized, events = normalize_action_list_for_authority(actions, party_state)

        self.assertEqual(len(normalized), 1)
        self.assertEqual(normalized[0].get("action"), "transitionLocation")
        self.assertEqual(
            normalized[0].get("parameters", {}).get("newLocation"),
            "NC05",
        )
        self.assertTrue(
            any(
                event.get("type")
                == "converted_same_module_tracker_location_to_transition"
                for event in events
            )
        )

    def test_same_location_tracker_keys_stripped_preserving_world_state(self):
        actions = [
            {
                "action": "updatePartyTracker",
                "parameters": {
                    "currentLocationId": "NC05",
                    "resolvedHostilesByLocation": {"NC05": True},
                },
            }
        ]
        party_state = {
            "module": "The_Thornwood_Watch",
            "worldConditions": {"currentLocationId": "NC05"},
        }

        normalized, events = normalize_action_list_for_authority(actions, party_state)

        self.assertEqual(len(normalized), 1)
        self.assertEqual(normalized[0].get("action"), "updatePartyTracker")
        self.assertNotIn("currentLocationId", normalized[0].get("parameters", {}))
        self.assertEqual(
            normalized[0].get("parameters", {}).get("resolvedHostilesByLocation"),
            {"NC05": True},
        )
        self.assertTrue(
            any(
                event.get("type") == "stripped_noop_same_location_tracker_keys"
                for event in events
            )
        )


class TestPartyTrackerMergeGuard(unittest.TestCase):
    """Tests for fail-closed same-module tracker merge guard."""

    def test_reject_unsafe_same_module_location_write(self):
        current_data = {
            "module": "The_Thornwood_Watch",
            "worldConditions": {"currentLocationId": "NC02"},
        }
        parameters = {"currentLocationId": "NC05"}

        with self.assertRaises(PartyTrackerMergeError):
            _merge_party_tracker_updates(
                current_data,
                parameters,
                current_module="The_Thornwood_Watch",
            )

    def test_cross_module_tracker_update_allowed(self):
        current_data = {
            "module": "The_Thornwood_Watch",
            "worldConditions": {"currentLocationId": "NC02"},
        }
        parameters = {
            "module": "Keep_of_Doom",
            "currentLocationId": "KD01",
            "currentAreaId": "KD001",
            "currentArea": "Outer Keep",
        }

        result = _merge_party_tracker_updates(
            current_data,
            parameters,
            current_module="The_Thornwood_Watch",
        )

        self.assertEqual(result.get("module"), "Keep_of_Doom")
        self.assertEqual(
            result.get("worldConditions", {}).get("currentLocationId"),
            "KD01",
        )


if __name__ == "__main__":
    unittest.main()
