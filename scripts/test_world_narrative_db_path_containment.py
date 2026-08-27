# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root

"""Provider-free tests for world-narrative database path authorization."""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from flask import Flask

from utils.database_paths import resolve_database_target
from utils.repo_paths import PathBoundaryError
from web.routes import world_narrative_routes


class TestDatabaseTargetResolver(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="neq_db_path_test_"))
        (self.temp_dir / "data").mkdir()

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_default_and_local_targets(self) -> None:
        self.assertEqual(
            resolve_database_target(root=self.temp_dir),
            (self.temp_dir / "data/memory.db").resolve(strict=False),
        )
        self.assertEqual(
            resolve_database_target("data/local.db", root=self.temp_dir),
            (self.temp_dir / "data/local.db").resolve(strict=False),
        )

    def test_unsafe_targets_are_rejected(self) -> None:
        targets = [
            str(self.temp_dir / "outside.db"),
            "../../outside.db",
            "data/../outside.db",
            "data/local.sqlite",
        ]
        for target in targets:
            with self.subTest(target=target), self.assertRaises(PathBoundaryError):
                resolve_database_target(target, root=self.temp_dir)

    def test_windows_absolute_target_is_rejected(self) -> None:
        with self.assertRaises(PathBoundaryError):
            resolve_database_target(r"C:\\outside.db", root=self.temp_dir)

    def test_symlink_target_and_parent_are_rejected(self) -> None:
        outside = self.temp_dir / "outside.db"
        outside.write_bytes(b"not a database")
        (self.temp_dir / "data" / "link.db").symlink_to(outside)
        with self.assertRaises(PathBoundaryError):
            resolve_database_target("data/link.db", root=self.temp_dir)
        linked_dir = self.temp_dir / "linked"
        linked_dir.mkdir()
        (self.temp_dir / "data" / "nested").symlink_to(linked_dir, target_is_directory=True)
        with self.assertRaises(PathBoundaryError):
            resolve_database_target("data/nested/local.db", root=self.temp_dir)


class TestWorldNarrativeRouteDatabaseBoundary(unittest.TestCase):
    def setUp(self) -> None:
        self.original_cwd = Path.cwd()
        self.temp_dir = Path(tempfile.mkdtemp(prefix="neq_world_db_route_test_")).resolve()
        self.uploads_root = (self.temp_dir / "user_uploads" / "text").resolve()
        self.ingestion_root = self.uploads_root / "ingestion"
        self.banned_terms_file = self.uploads_root / "banned_terms.txt"
        self.route_paths_patch = mock.patch.multiple(
            world_narrative_routes,
            USER_UPLOADS_ROOT=self.uploads_root,
            INGESTION_ROOT=self.ingestion_root,
            BANNED_TERMS_FILE=self.banned_terms_file,
        )
        self.route_paths_patch.start()
        os.chdir(self.temp_dir)
        self.uploads_root.mkdir(parents=True)
        (self.temp_dir / "data").mkdir()
        self.atoms_path = self.temp_dir / "user_uploads/text/atoms.json"
        self.atoms_path.write_text(json.dumps({
            "profile": {"profile_id": "test.profile", "profile_kind": "test"},
            "atoms": [{"atom_id": "atom.one", "atom_type": "motif", "label": "A", "description": "B"}],
        }), encoding="utf-8")
        self.app = Flask(__name__)
        world_narrative_routes.register_world_narrative_routes(self.app)
        self.client = self.app.test_client()

    def tearDown(self) -> None:
        self.route_paths_patch.stop()
        os.chdir(self.original_cwd)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_rejection_is_bounded_and_does_not_ingest(self) -> None:
        with mock.patch(
            "web.routes.world_narrative_routes.resolve_database_target",
            side_effect=PathBoundaryError("outside host path should not leak"),
        ), mock.patch("web.routes.world_narrative_routes.ingest_source_anonymous_atoms") as ingest:
            response = self.client.post(
                "/api/toolkit/world/sources/ingest",
                json={"atoms_path": str(self.atoms_path), "db_path": "../../outside.db"},
            )
        self.assertEqual(response.status_code, 400)
        payload = response.get_json()
        self.assertEqual(payload["error_code"], "database_path_policy")
        self.assertEqual(payload["message"], "Database path is not allowed")
        self.assertNotIn("outside host path", response.get_data(as_text=True))
        self.assertNotIn(str(self.temp_dir), response.get_data(as_text=True))
        ingest.assert_not_called()

    def test_approved_target_preserves_success_shape(self) -> None:
        resolved = self.temp_dir / "data/local.db"
        with mock.patch(
            "web.routes.world_narrative_routes.resolve_database_target", return_value=resolved
        ), mock.patch(
            "web.routes.world_narrative_routes.database_target_label", return_value="data/local.db"
        ), mock.patch(
            "web.routes.world_narrative_routes.ingest_source_anonymous_atoms",
            return_value={"status": "success", "atom_count": 1},
        ) as ingest:
            response = self.client.post(
                "/api/toolkit/world/sources/ingest",
                json={"atoms_path": str(self.atoms_path), "db_path": "data/local.db"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "success")
        self.assertEqual(ingest.call_args.kwargs["db_path"], str(resolved))


if __name__ == "__main__":
    unittest.main()
