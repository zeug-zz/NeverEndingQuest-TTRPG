# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.

"""Provider-free tests for the task 6.1 world-narrative context boundary."""

import hashlib
import inspect
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils import toolkit_adaptation_world_context as world_context
from utils.toolkit_adaptation_world_context import (
    MAX_CONTEXT_SERIALIZED_CHARS,
    MAX_PRESSURES,
    MAX_REGISTRY_MODULES,
    MAX_SEEDS,
    WORLD_CONTEXT_FALLBACK_SEED_INVALID,
    WORLD_CONTEXT_FALLBACK_SEED_UNAVAILABLE,
    WORLD_CONTEXT_SEED_STATUS_AVAILABLE,
    WORLD_CONTEXT_SEED_STATUS_INVALID,
    WORLD_CONTEXT_SEED_STATUS_UNAVAILABLE,
    WORLD_CONTEXT_STATUS_AVAILABLE,
    WORLD_CONTEXT_STATUS_FALLBACK,
    WorldNarrativeContextProvider,
    WORLD_CONTEXT_PROVENANCE_VERSION,
    build_world_context_provenance,
    build_world_narrative_context,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def _campaign_model() -> dict:
    return {
        "campaign_id": "fixture-campaign",
        "version": 3,
        "summary": "A frontier world balances old pacts and new roads.",
        "tone": "mystery with resilient hope",
        "themes": ["broken pacts", "hidden roads"],
        "credentials": "must not appear",
    }


def _pressures() -> list:
    return [
        {"thread_id": "thread-02", "thread_type": "faction", "summary": "A rival faction tests the frontier.", "priority": 60},
        {"thread_id": "thread-01", "thread_type": "mystery", "summary": "A sealed road is opening below the hills.", "priority": 80},
    ]


def _registry() -> dict:
    return {
        "worldName": "Fixture World",
        "registryVersion": "2.0.0",
        "modules": {
            "Lantern_Market": {
                "moduleName": "Lantern Market",
                "areaCount": 2,
                "levelRange": {"min": 1, "max": 3},
                "plotObjective": "Recover a missing shipment.",
                "themes": ["ignored raw registry prose"],
            }
        },
        "api_key": "must not appear",
    }


def _seed() -> dict:
    return {
        "seed_id": "seed-01",
        "module_slug": "Lantern_Market",
        "seed_type": "continuity",
        "content": {
            "summary": "A missing shipment connects the market to the frontier.",
            "hook": "A sealed lantern carries an unfamiliar crest.",
            "raw_source": "must not appear",
        },
    }


def _create_seed_db(path: Path, *, content_json: str = "valid") -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE schema_version (version TEXT PRIMARY KEY, build_date TEXT NOT NULL)")
        connection.execute("INSERT INTO schema_version VALUES ('2.1.0', '2026-08-04')")
        connection.execute(
            """
            CREATE TABLE module_narrative_seeds (
                seed_id INTEGER PRIMARY KEY,
                module_slug TEXT NOT NULL,
                seed_type TEXT NOT NULL,
                content_json TEXT NOT NULL,
                applied INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        payload = json.dumps(_seed()["content"]) if content_json == "valid" else content_json
        connection.execute(
            "INSERT INTO module_narrative_seeds VALUES (?, ?, ?, ?, ?)",
            (1, "Lantern_Market", "continuity", payload, 1),
        )
        connection.commit()
    finally:
        connection.close()


class TestWorldNarrativeContextContract(unittest.TestCase):
    def test_successful_pack_is_versioned_allowlisted_and_read_only(self):
        pack = build_world_narrative_context(
            _campaign_model(),
            _pressures(),
            _registry(),
            [_seed()],
            selected_module="Lantern_Market",
            seed_version="fixture.v2",
        )

        self.assertEqual(pack["status"], WORLD_CONTEXT_STATUS_AVAILABLE)
        self.assertEqual(pack["context_status"], WORLD_CONTEXT_STATUS_AVAILABLE)
        self.assertTrue(pack["read_only"])
        self.assertTrue(pack["provider_free"])
        self.assertEqual(pack["world_seed_status"], WORLD_CONTEXT_SEED_STATUS_AVAILABLE)
        self.assertEqual(pack["world_seed_version"], "fixture.v2")
        self.assertRegex(pack["world_seed_hash"], r"^[0-9a-f]{64}$")
        self.assertRegex(pack["provenance"]["context_hash"], r"^[0-9a-f]{64}$")
        self.assertEqual(pack["context_hash"], pack["provenance"]["context_hash"])
        self.assertEqual(pack["approved_module_seeds"][0]["module_slug"], "Lantern_Market")
        self.assertIn("summary", pack["approved_module_seeds"][0]["content"])
        self.assertNotIn("credentials", json.dumps(pack).lower())
        self.assertNotIn("raw_source", json.dumps(pack).lower())

    def test_provider_reads_approved_seed_rows_without_writes(self):
        with tempfile.TemporaryDirectory(dir=str(REPO_ROOT / "tmp"), prefix="toolkit_adaptation_world_context_") as temp_dir:
            seed_path = Path(temp_dir) / "seed.db"
            _create_seed_db(seed_path)
            before = hashlib.sha256(seed_path.read_bytes()).hexdigest()
            provider = WorldNarrativeContextProvider(seed_db_path=seed_path)
            pack = provider.build(
                campaign_model=_campaign_model(),
                active_pressures=_pressures(),
                registry_context=_registry(),
            )
            after = hashlib.sha256(seed_path.read_bytes()).hexdigest()

        self.assertEqual(pack["status"], WORLD_CONTEXT_STATUS_AVAILABLE)
        self.assertEqual(pack["world_seed_version"], "2.1.0")
        self.assertEqual(len(pack["approved_module_seeds"]), 1)
        self.assertEqual(before, after)

    def test_unavailable_seed_data_has_explicit_fallback(self):
        pack = build_world_narrative_context(
            _campaign_model(),
            _pressures(),
            _registry(),
            [],
        )
        self.assertEqual(pack["status"], WORLD_CONTEXT_STATUS_FALLBACK)
        self.assertEqual(pack["fallback_status"], WORLD_CONTEXT_FALLBACK_SEED_UNAVAILABLE)
        self.assertEqual(pack["world_seed_status"], WORLD_CONTEXT_SEED_STATUS_UNAVAILABLE)
        self.assertEqual(pack["approved_module_seeds"], [])
        self.assertTrue(any(item["code"] == "no_approved_module_seeds" for item in pack["diagnostics"]))

    def test_missing_seed_database_has_explicit_fallback_diagnostic(self):
        missing_seed_path = REPO_ROOT / "tmp" / "toolkit_adaptation_world_context_missing_seed.db"
        pack = build_world_narrative_context(
            _campaign_model(),
            _pressures(),
            _registry(),
            runtime_db_path=missing_seed_path,
            seed_db_path=missing_seed_path,
        )
        self.assertEqual(pack["status"], WORLD_CONTEXT_STATUS_FALLBACK)
        self.assertEqual(pack["fallback_status"], WORLD_CONTEXT_FALLBACK_SEED_UNAVAILABLE)
        self.assertEqual(pack["world_seed_status"], WORLD_CONTEXT_SEED_STATUS_UNAVAILABLE)
        self.assertTrue(any(item["code"] == "seed_database_missing" for item in pack["diagnostics"]))

    def test_invalid_seed_data_has_explicit_fallback(self):
        with tempfile.TemporaryDirectory(dir=str(REPO_ROOT / "tmp"), prefix="toolkit_adaptation_world_context_") as temp_dir:
            seed_path = Path(temp_dir) / "seed.db"
            _create_seed_db(seed_path, content_json="{not-json")
            pack = build_world_narrative_context(
                _campaign_model(),
                _pressures(),
                _registry(),
                seed_db_path=seed_path,
            )

        self.assertEqual(pack["status"], WORLD_CONTEXT_STATUS_FALLBACK)
        self.assertEqual(pack["fallback_status"], WORLD_CONTEXT_FALLBACK_SEED_INVALID)
        self.assertEqual(pack["world_seed_status"], WORLD_CONTEXT_SEED_STATUS_INVALID)
        self.assertTrue(any(item["code"] == "invalid_seed_json" for item in pack["diagnostics"]))

    def test_bounds_and_deterministic_serialization(self):
        huge = "x" * 100000
        pressures = [{"thread_id": str(index), "summary": huge, "priority": index} for index in range(40)]
        registry = {
            "worldName": huge,
            "registryVersion": "1",
            "modules": {
                str(index): {"moduleName": huge, "areaCount": index}
                for index in range(80)
            },
        }
        seeds = [
            {
                "module_slug": "Fixture",
                "seed_type": "pressure",
                "content": {"summary": huge, "unknown_secret_field": huge},
            }
            for _ in range(40)
        ]
        first = build_world_narrative_context({}, pressures, registry, seeds)
        second = build_world_narrative_context(
            {},
            list(reversed(pressures)),
            registry,
            list(reversed(seeds)),
        )
        first_serialized = json.dumps(first, sort_keys=True, separators=(",", ":"))
        self.assertLessEqual(len(first_serialized), MAX_CONTEXT_SERIALIZED_CHARS)
        self.assertLessEqual(len(first["active_pressures"]), MAX_PRESSURES)
        self.assertLessEqual(len(first["registry_context"].get("modules", [])), MAX_REGISTRY_MODULES)
        self.assertLessEqual(len(first["approved_module_seeds"]), MAX_SEEDS)
        self.assertEqual(first, second)
        self.assertNotIn("unknown_secret_field", first_serialized)

    def test_provider_is_provider_free_and_has_no_persistence_surface(self):
        source = inspect.getsource(world_context)
        self.assertNotIn("create_chat_client", source)
        self.assertNotIn("requests.", source)
        self.assertNotIn("safe_write_json", source)
        self.assertNotIn("write_text", source)
        self.assertNotIn("INSERT INTO", source)
        self.assertNotIn("UPDATE ", source)
        self.assertNotIn("DELETE FROM", source)


class TestWorldContextProvenanceBoundary(unittest.TestCase):
    """Only scalar seed identity and read-only authority reach adaptation reports."""

    def test_provenance_contains_seed_identity_without_world_payload(self):
        pack = build_world_narrative_context(
            _campaign_model(),
            _pressures(),
            _registry(),
            [_seed()],
            selected_module="Lantern_Market",
            seed_version="fixture.v2",
        )
        provenance = build_world_context_provenance(pack)

        self.assertEqual(provenance["provenance_version"], WORLD_CONTEXT_PROVENANCE_VERSION)
        self.assertEqual(provenance["context_version"], pack["context_version"])
        self.assertEqual(provenance["world_seed_version"], "fixture.v2")
        self.assertEqual(provenance["world_seed_hash"], pack["world_seed_hash"])
        self.assertEqual(provenance["context_hash"], pack["context_hash"])
        self.assertTrue(provenance["read_only"])
        self.assertTrue(provenance["provider_free"])
        self.assertFalse(provenance["raw_context_included"])
        self.assertFalse(provenance["canon_write_allowed"])
        self.assertFalse(provenance["registry_write_allowed"])
        self.assertFalse(provenance["mechanical_write_allowed"])
        serialized = json.dumps(provenance, sort_keys=True)
        self.assertNotIn("campaign_model", serialized)
        self.assertNotIn("active_pressures", serialized)
        self.assertNotIn("approved_module_seeds", serialized)

    def test_unavailable_context_has_explicit_scalar_fallback(self):
        provenance = build_world_context_provenance({
            "context_status": "fallback",
            "fallback_status": "seed_data_unavailable",
            "world_seed_status": "unavailable",
        })

        self.assertEqual(provenance["world_seed_status"], "unavailable")
        self.assertIsNone(provenance["world_seed_version"])
        self.assertIsNone(provenance["world_seed_hash"])
        self.assertEqual(provenance["fallback_status"], "seed_data_unavailable")
        self.assertFalse(provenance["canon_write_allowed"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
