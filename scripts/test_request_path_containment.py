# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free regressions for request-supplied path segment containment.

Module slugs, graphic pack names and character file names taken from web
requests must name a direct child of their approved root.  Traversal inputs
are rejected before any filesystem read or write.
"""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from flask import Flask

from utils.repo_paths import (
    safe_child_name,
    validate_graphic_pack_name,
    validate_module_slug,
)

TRAVERSAL_NAMES = [
    "..",
    ".",
    "../escape",
    "../../escape",
    "a/b",
    "a\\b",
    "/abs",
    "C:\\abs",
    ".hidden",
    "x\x00y",
    "",
]


class SafeChildNameTests(unittest.TestCase):
    def test_rejects_traversal_and_non_text(self) -> None:
        for name in TRAVERSAL_NAMES + [None, 7, ["x"]]:
            with self.subTest(name=name):
                self.assertIsNone(validate_module_slug(name))
                self.assertIsNone(validate_graphic_pack_name(name))
                self.assertIsNone(safe_child_name(name, "characters"))

    def test_slug_pattern_rejects_spaces_and_punctuation(self) -> None:
        for name in ["Keep of Doom", "x;y", "x" * 121, "-leading", "_backup"]:
            with self.subTest(name=name):
                self.assertIsNone(validate_module_slug(name))

    def test_accepts_installed_modules_and_packs(self) -> None:
        installed = [
            entry.name
            for entry in (ROOT / "modules").iterdir()
            if entry.is_dir() and not entry.name.startswith(("_", "."))
        ]
        self.assertTrue(installed)
        for name in installed:
            with self.subTest(module=name):
                self.assertEqual(validate_module_slug(name), name)
        packs_root = ROOT / "graphic_packs"
        if packs_root.is_dir():
            for entry in packs_root.iterdir():
                if entry.is_dir() and not entry.name.startswith("."):
                    with self.subTest(pack=entry.name):
                        self.assertEqual(validate_graphic_pack_name(entry.name), entry.name)

    def test_character_file_names_allow_existing_spellings(self) -> None:
        for name in ["merisiel.json", "d'arcy_vane.json", "kira-7.json"]:
            with self.subTest(name=name):
                self.assertEqual(safe_child_name(name, "characters"), name)


class _IsolatedCwd(unittest.TestCase):
    """Run route checks from a disposable directory so no real state is touched."""

    def setUp(self) -> None:
        (ROOT / "tmp").mkdir(exist_ok=True)
        self.workdir = Path(tempfile.mkdtemp(prefix="path-containment-", dir=ROOT / "tmp"))
        for sub in ("characters", "modules", "temp", "graphic_packs"):
            (self.workdir / "sandbox" / sub).mkdir(parents=True)
        self.previous_cwd = os.getcwd()
        os.chdir(self.workdir / "sandbox")
        self.addCleanup(self._restore)

    def _restore(self) -> None:
        os.chdir(self.previous_cwd)
        shutil.rmtree(self.workdir, ignore_errors=True)

    def assert_no_escape(self) -> None:
        escaped = [p.name for p in self.workdir.iterdir() if p.name != "sandbox"]
        self.assertEqual(escaped, [])


class TabletopCharacterRouteTests(_IsolatedCwd):
    def setUp(self) -> None:
        super().setUp()
        from web.routes import tabletop_party_routes

        self.routes = tabletop_party_routes
        app = Flask(__name__)
        tabletop_party_routes.register_tabletop_party_routes(app, mock.Mock())
        self.client = app.test_client()

    def test_create_player_rejects_traversal_name(self) -> None:
        response = self.client.post("/api/party/create_player", json={"name": "../../escape"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "Invalid character name")
        self.assert_no_escape()

    def test_manual_update_rejects_traversal_before_lookup(self) -> None:
        with mock.patch.object(self.routes.pc_manager, 'get_character_state') as read:
            response = self.client.post('/api/party/update_manual',
                                        json={'character_name': '../escape'})
        self.assertEqual(response.status_code, 400)
        read.assert_not_called()

    def test_create_manual_rejects_traversal_name_before_write(self) -> None:
        audit = SimpleNamespace(
            result_type=self.routes.AUDIT_RESULT_SUCCESS,
            normalized_data={"name": "../../escape"},
            errors=[],
            missing_paths=[],
        )
        with mock.patch.object(self.routes, "audit_character_creation", return_value=audit), \
                mock.patch.object(self.routes, "safe_write_json") as write:
            response = self.client.post("/api/party/create_manual", json={"name": "../../escape"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "Invalid character name")
        write.assert_not_called()
        self.assert_no_escape()


class ToolkitClassificationRouteTests(_IsolatedCwd):
    def test_apply_classification_rejects_traversal_slug(self) -> None:
        from web.routes import toolkit_homebrew_routes as routes

        app = Flask(__name__)
        routes.register_toolkit_homebrew_routes(app)
        client = app.test_client()
        (self.workdir / "areas").mkdir()
        with mock.patch.object(routes, "_HAS_LLM_CLASSIFICATION", True), \
                mock.patch.object(routes, "is_classification_enabled", return_value=True, create=True), \
                mock.patch.dict(routes._jobs, {"job-1": {"result": {}}}), \
                mock.patch.object(routes, "apply_npc_visibility_classifications", create=True) as apply:
            response = client.post(
                "/api/toolkit/homebrew/jobs/job-1/apply_classification",
                json={"module_slug": "../..", "npc_visibility": {"x": "visible"}},
            )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["reason"], "module_slug_invalid")
        apply.assert_not_called()


class ToolkitWebInterfaceRouteTests(_IsolatedCwd):
    @classmethod
    def setUpClass(cls) -> None:
        from web import web_interface

        cls.web = web_interface

    def setUp(self) -> None:
        super().setUp()
        self.patches = [
            mock.patch.object(self.web, "TOOLKIT_AVAILABLE", True),
            mock.patch("utils.file_operations.safe_write_json"),
        ]
        for patcher in self.patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = self.web.app.test_client()

    def test_url_module_routes_reject_parent_segment(self) -> None:
        for path in [
            "/api/toolkit/modules/%2E%2E/monsters",
            "/api/toolkit/modules/%2E%2E/unified-assets",
            "/api/toolkit/modules/%2E%2E/npcs?pack=photorealistic",
            "/api/toolkit/modules/Keep_of_Doom/npcs?pack=%2E%2E",
        ]:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 400)
        self.assert_no_escape()

    def test_json_module_routes_reject_traversal(self) -> None:
        cases = [
            ("/api/toolkit/npcs/fetch-descriptions", {"module_name": "../escape", "npcs": ["a"]}),
            ("/api/toolkit/npcs/description", {
                "module_name": "../escape", "npc_id": "a", "description": "d"}),
            ("/api/toolkit/npcs/generate-portraits", {
                "module_name": "Keep_of_Doom", "pack_name": "../escape", "npcs": ["a"]}),
            ("/api/toolkit/add-to-bestiary", {"module_name": "../escape", "monster_ids": ["a"]}),
        ]
        with mock.patch("threading.Thread") as thread:
            for path, payload in cases:
                with self.subTest(path=path):
                    response = self.client.post(path, json=payload)
                    self.assertEqual(response.status_code, 400)
            thread.assert_not_called()
        response = self.client.get("/api/toolkit/npcs/description?module=../escape&npc_id=a")
        self.assertEqual(response.status_code, 400)
        self.assert_no_escape()

    def test_unified_asset_socket_rejects_traversal(self) -> None:
        with mock.patch.object(self.web, "emit") as emit, \
                mock.patch("threading.Thread") as thread:
            self.web.handle_generate_unified_assets({"module_name": "../escape", "assets": []})
        emit.assert_called_once_with("unified_generation_error", {"error": "Invalid module name"})
        thread.assert_not_called()

    def test_character_lookup_rejects_traversal(self) -> None:
        with mock.patch('utils.file_operations.safe_read_json') as read:
            response = self.client.get('/get_character_data',
                                       query_string={'character_name': '../escape'})
        self.assertEqual(response.status_code, 400)
        read.assert_not_called()

    def test_export_rejects_unsafe_pack_and_ids_before_copy(self) -> None:
        for payload in [
            {'pack_name': '../escape', 'npc_ids': ['kira']},
            {'pack_name': 'photorealistic', 'npc_ids': ['../escape']},
            {'pack_name': 'photorealistic', 'npc_ids': 'kira'},
            {'pack_name': 'photorealistic', 'npc_ids': [None]},
        ]:
            with self.subTest(payload=payload), mock.patch('os.makedirs') as mkdir, \
                    mock.patch('shutil.copy2') as copy:
                response = self.client.post('/api/toolkit/npcs/export-to-pack', json=payload)
                self.assertEqual(response.status_code, 400)
                mkdir.assert_not_called()
                copy.assert_not_called()
        self.assert_no_escape()


if __name__ == "__main__":
    unittest.main()
