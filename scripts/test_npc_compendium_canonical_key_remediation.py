# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Unit tests for NPC compendium canonical key remediation."""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.remediate_npc_compendium_keys import (  # noqa: E402
    build_report_path,
    main,
    remediate_npc_compendium_file,
)
from utils.npc_identity import canonicalize_npc_identity  # noqa: E402


class TestNpcCompendiumCanonicalKeyRemediation(unittest.TestCase):
    def _write_fixture(self, tmpdir: str, payload: dict) -> Path:
        path = Path(tmpdir) / "npc_compendium.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return path

    def _load_json(self, path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    def test_remediation_merges_numillian_variants(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            compendium = {
                "version": "1.0.0",
                "created": "2025-09-08T21:54:54.376133",
                "total_npcs": 6,
                "npcs": {
                    "arannis,_vault_scholar_and_alarmed_archivist": {
                        "name": "Arannis, vault scholar and alarmed archivist",
                        "description": "Legacy Arannis description.",
                        "module": "The_Hidden_City_of_Numillian",
                    },
                    "arannis": {
                        "name": "Arannis",
                        "description": "Canonical Arannis description.",
                        "module": "The_Hidden_City_of_Numillian",
                    },
                    "kobe,_a_guarded_resident_tied_to_the_vault": {
                        "name": "Kobe, a guarded resident tied to the vault",
                        "description": "Primary Kobe description.",
                        "module": "The_Hidden_City_of_Numillian",
                    },
                    "kobe,_the_life_at_the_center_of_the_crisis": {
                        "name": "Kobe, the life at the center of the crisis",
                        "description": "Alternate Kobe description.",
                        "module": "The_Hidden_City_of_Numillian",
                    },
                    "merchant_gareth": {
                        "name": "Merchant Gareth",
                        "description": "Keep as-is.",
                        "module": "The_Thornwood_Watch",
                    },
                    "bad_entry": "not a dict",
                },
            }
            path = self._write_fixture(tmpdir, compendium)

            report = remediate_npc_compendium_file(path, apply_changes=True)
            updated = self._load_json(path)

            self.assertEqual(report["mode"], "apply")
            self.assertEqual(report["canonical_npcs"], 3)
            self.assertEqual(updated["total_npcs"], 3)
            self.assertEqual(set(updated["npcs"].keys()), {"arannis", "kobe", "merchant_gareth"})

            arannis = updated["npcs"]["arannis"]
            self.assertEqual(arannis["name"], "Arannis")
            self.assertEqual(arannis["description"], "Canonical Arannis description.")
            self.assertIn("arannis,_vault_scholar_and_alarmed_archivist", arannis["legacy_ids"])
            self.assertTrue(any(item["legacy_id"] == "arannis,_vault_scholar_and_alarmed_archivist" for item in arannis["alternate_descriptions"]))

            kobe = updated["npcs"]["kobe"]
            self.assertEqual(kobe["name"], "Kobe")
            self.assertEqual(kobe["description"], "Primary Kobe description.")
            self.assertIn("kobe,_the_life_at_the_center_of_the_crisis", kobe["legacy_ids"])
            self.assertGreaterEqual(len(kobe["alternate_descriptions"]), 1)
            self.assertEqual(kobe["role_hint"], "a guarded resident tied to the vault")
            self.assertIn("a guarded resident tied to the vault", kobe["role_hints"])

            self.assertIn("bad_entry", [item["source_key"] for item in report["skipped_entries"]])
            self.assertTrue(build_report_path(path).exists())
            self.assertTrue(Path(f"{path}.bak").exists())

    def test_dry_run_does_not_mutate_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            compendium = {
                "version": "1.0.0",
                "created": "2025-09-08T21:54:54.376133",
                "total_npcs": 2,
                "npcs": {
                    "elaris,_a_diplomat_of_the_secrecy_council": {
                        "name": "Elaris, a diplomat of the Secrecy Council",
                        "description": "Diplomatic Elaris.",
                        "module": "The_Hidden_City_of_Numillian",
                    },
                    "merchant_gareth": {
                        "name": "Merchant Gareth",
                        "description": "Keep as-is.",
                        "module": "The_Thornwood_Watch",
                    },
                },
            }
            path = self._write_fixture(tmpdir, compendium)
            original = path.read_text(encoding="utf-8")

            report = remediate_npc_compendium_file(path, apply_changes=False)
            after = path.read_text(encoding="utf-8")

            self.assertEqual(report["mode"], "dry-run")
            self.assertEqual(original, after)
            self.assertEqual(report["canonical_npcs"], 2)

    def test_cli_json_output_uses_path_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            compendium = {
                "version": "1.0.0",
                "created": "2025-09-08T21:54:54.376133",
                "total_npcs": 1,
                "npcs": {
                    "ilyra,_wardkeeper_adjudicator": {
                        "name": "Ilyra, wardkeeper adjudicator",
                        "description": "Wardkeeper Ilyra.",
                        "module": "The_Hidden_City_of_Numillian",
                    }
                },
            }
            path = self._write_fixture(tmpdir, compendium)

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = main(["--path", str(path), "--json"])

            self.assertEqual(exit_code, 0)
            output = json.loads(stdout.getvalue())
            self.assertEqual(output["status"], "ok")
            self.assertEqual(output["mode"], "dry-run")
            self.assertEqual(output["path"], str(path))
            self.assertEqual(output["canonical_npcs"], 1)
            self.assertEqual(canonicalize_npc_identity("Ilyra, wardkeeper adjudicator").slug, "ilyra")

    def test_source_contract_stays_compendium_only(self) -> None:
        script_source = Path(__file__).resolve().parents[0] / "remediate_npc_compendium_keys.py"
        source = script_source.read_text(encoding="utf-8")

        self.assertIn("data/bestiary/npc_compendium.json", source)
        self.assertIn("safe_write_json", source)
        self.assertIn("--apply", source)
        self.assertIn("--dry-run", source)
        self.assertIn("--json", source)
        self.assertNotIn("monster_compendium.json", source)
        self.assertNotIn("web_interface.py", source)
        self.assertNotIn("startup_required", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
