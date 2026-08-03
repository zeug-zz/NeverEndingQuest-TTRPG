#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root

"""
Test suite for Toolkit Accurate-Ingest Publication Readiness Closure.

Task 1.1: Provider-free, tempdir-backed tests reproducing all 4 blocker classes.

Test classes:
    TestBlockerReproduction - Baseline regression tests.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any, Dict, Optional
from unittest import mock


# ---------------------------------------------------------------------------
# Helper: create a minimal module_context.json
# ---------------------------------------------------------------------------

def _write_module_context(module_dir: Path, has_continuity: bool = False,
                          has_semantic_authority: bool = False) -> None:
    """Write a minimal module_context.json to module_dir."""
    context: Dict[str, Any] = {
        "title": "Test Module",
        "description": "A temp module for blocker reproduction tests.",
        "srd_attribution": "Portions derived from SRD 5.2.1, CC BY 4.0",
    }
    if has_continuity:
        context["continuity"] = {
            "continuity_version": "v1",
            "entry_state_variants": {
                "cold_start": "...",
                "partial_context": "...",
                "late_arc": "...",
            },
            "cross_module_refs": [],
            "standalone_fallback": {"summary": "..."},
        }
    if has_semantic_authority:
        context["semantic_authority"] = {
            "version": "v1",
            "location_aliases": {},
            "destination_phrases": {},
            "npc_scene_authority": {},
        }
    (module_dir / "module_context.json").write_text(
        json.dumps(context, indent=2), encoding="utf-8"
    )


def _write_module_plot(module_dir: Path) -> None:
    """Write a minimal module_plot.json."""
    plot = {
        "title": "Test Plot",
        "description": "Minimal plot for tests.",
    }
    (module_dir / "module_plot.json").write_text(
        json.dumps(plot, indent=2), encoding="utf-8"
    )


def _write_monster_json(module_dir: Path, *slugs: str) -> None:
    """Write minimal monster JSON files for the given slugs."""
    monsters_dir = module_dir / "monsters"
    monsters_dir.mkdir(parents=True, exist_ok=True)
    for slug in slugs:
        monster = {
            "name": slug.replace("_", " ").title(),
            "slug": slug,
            "size": "Medium",
            "alignment": "unaligned",
            "armorClass": 10,
        }
        (monsters_dir / f"{slug}.json").write_text(
            json.dumps(monster, indent=2), encoding="utf-8"
        )


# ===================================================================
# TestBlockerReproduction
# ===================================================================

class TestBlockerReproduction(unittest.TestCase):
    """Reproduce all 4 publication-readiness blocker classes."""

    maxDiff = None

    # ---------------------------------------------------------------
    # Blocker 1: Continuity missing
    # ---------------------------------------------------------------

    def test_continuity_missing_blocker(self) -> None:
        """Temp module without 'continuity' + audit fails in strict mode."""
        with tempfile.TemporaryDirectory() as td:
            module_dir = Path(td) / "Test_Module"
            module_dir.mkdir()
            _write_module_context(module_dir, has_continuity=False)
            _write_module_plot(module_dir)

            from scripts.module_continuity_audit import audit_module_continuity

            result = audit_module_continuity(module_dir, strict=True)

            self.assertEqual(result["status"], "fail")
            self.assertIn("continuity_version", result["missing_required_keys"])
            self.assertIn("entry_state_variants", result["missing_required_keys"])
            self.assertIn("cross_module_refs", result["missing_required_keys"])
            self.assertIn("standalone_fallback", result["missing_required_keys"])
            self.assertGreater(len(result["blocking_errors"]), 0)

    # ---------------------------------------------------------------
    # Blocker 2: Semantic authority missing
    # ---------------------------------------------------------------

    def test_semantic_missing_blocker(self) -> None:
        """Temp module without 'semantic_authority' + audit fails."""
        with tempfile.TemporaryDirectory() as td:
            module_dir = Path(td) / "Test_Module"
            module_dir.mkdir()
            _write_module_context(module_dir, has_semantic_authority=False)

            from scripts.module_semantic_authority_audit import (
                audit_module_semantic_authority,
            )

            result = audit_module_semantic_authority(module_dir)

            self.assertEqual(result["status"], "fail")
            self.assertIn(
                "semantic_authority_payload_missing", result["blocker_classes"]
            )
            self.assertGreater(len(result["blocking_errors"]), 0)

    # ---------------------------------------------------------------
    # Blocker 3: Sidecar missing
    # ---------------------------------------------------------------

    def test_sidecar_missing_blocker(self) -> None:
        """Temp slug with no sidecar + find_latest_sidecar_for_slug returns None."""
        from scripts.homebrew_sidecar_audit import find_latest_sidecar_for_slug

        with tempfile.TemporaryDirectory() as td:
            fake_archive = Path(td) / "ingest" / "archive"
            fake_archive.mkdir(parents=True, exist_ok=True)

            with mock.patch(
                "scripts.homebrew_sidecar_audit.ARCHIVE_ROOT", fake_archive
            ):
                result = find_latest_sidecar_for_slug("Well_of_Ruin")

            self.assertIsNone(result)

    # ---------------------------------------------------------------
    # Blocker 4: Monster media missing
    # ---------------------------------------------------------------

    def test_media_missing_blocker(self) -> None:
        """Temp module with monster JSON + no media dir + check returns base=False."""
        from scripts.audit_module_gameplay import check_monster_media

        with tempfile.TemporaryDirectory() as td:
            module_dir = Path(td) / "Test_Module"
            module_dir.mkdir()
            _write_monster_json(module_dir, "test_beast", "shadow_wisp")

            # No media/monsters/ directory at all
            result = check_monster_media(str(module_dir), "test_beast")

            self.assertIsInstance(result, dict)
            self.assertFalse(result.get("base"))
            self.assertFalse(result.get("thumb"))
            self.assertFalse(result.get("video"))


# ===================================================================
# TestContinuitySemanticFinalization
# ===================================================================

class TestContinuitySemanticFinalization(unittest.TestCase):
    """Test finalize_module_publishability_metadata()."""

    maxDiff = None

    # ---------------------------------------------------------------
    # Task 2.2 - Continuity block added when missing
    # ---------------------------------------------------------------

    def test_continuity_block_added_when_missing(self) -> None:
        """Continuity block is added when missing from module_context."""
        with tempfile.TemporaryDirectory() as td:
            module_dir = Path(td) / "Test_Module"
            module_dir.mkdir()
            _write_module_context(module_dir, has_continuity=False)
            _write_module_plot(module_dir)

            from utils.toolkit_publishability_finalizer import (
                finalize_module_publishability_metadata,
            )

            result = finalize_module_publishability_metadata(
                "Test_Module", module_dir
            )

            self.assertEqual(result["status"], "success")
            self.assertTrue(result["changed"])
            self.assertEqual(result["errors"], [])

            # Verify written file has full continuity block
            ctx = json.loads(
                (module_dir / "module_context.json").read_text(encoding="utf-8")
            )
            self.assertIn("continuity", ctx)
            c = ctx["continuity"]
            self.assertEqual(c.get("continuity_version"), "v1")
            self.assertIsInstance(c.get("entry_state_variants"), dict)
            for vk in ("cold_start", "partial_context", "late_arc"):
                self.assertIn(vk, c["entry_state_variants"])
                self.assertIsInstance(c["entry_state_variants"][vk], dict)
            self.assertIsInstance(c.get("cross_module_refs"), list)
            self.assertIsInstance(c.get("standalone_fallback"), dict)

    # ---------------------------------------------------------------
    # Task 2.2 - Semantic authority added when missing
    # ---------------------------------------------------------------

    def test_semantic_authority_added_when_missing(self) -> None:
        """Semantic authority payload is added when missing from module_context."""
        with tempfile.TemporaryDirectory() as td:
            module_dir = Path(td) / "Test_Module"
            module_dir.mkdir()
            _write_module_context(module_dir, has_semantic_authority=False)
            _write_module_plot(module_dir)

            from utils.toolkit_publishability_finalizer import (
                finalize_module_publishability_metadata,
            )

            result = finalize_module_publishability_metadata(
                "Test_Module", module_dir
            )

            self.assertEqual(result["status"], "success")
            self.assertTrue(result["changed"])

            # Verify written file has semantic authority
            ctx = json.loads(
                (module_dir / "module_context.json").read_text(encoding="utf-8")
            )
            sa = ctx.get("semantic_authority")
            self.assertIsInstance(sa, dict)
            self.assertEqual(sa.get("version"), "v1")
            self.assertIn("location_aliases", sa)
            self.assertIn("destination_phrases", sa)
            self.assertIn("npc_scene_authority", sa)
            self.assertIn("diagnostics", sa)
            self.assertIn("summary", sa)

    # ---------------------------------------------------------------
    # Task 2.2 - Noop when both already present
    # ---------------------------------------------------------------

    def test_noop_when_both_already_present(self) -> None:
        """No changes when continuity and semantic_authority are already present."""
        with tempfile.TemporaryDirectory() as td:
            module_dir = Path(td) / "Test_Module"
            module_dir.mkdir()
            _write_module_context(module_dir, has_continuity=False,
                                 has_semantic_authority=False)
            _write_module_plot(module_dir)

            from utils.toolkit_publishability_finalizer import (
                finalize_module_publishability_metadata,
            )

            # First call: adds both continuity and semantic authority
            r1 = finalize_module_publishability_metadata(
                "Test_Module", module_dir
            )
            self.assertTrue(r1["changed"])

            # Second call: everything is already present -> noop
            r2 = finalize_module_publishability_metadata(
                "Test_Module", module_dir
            )
            self.assertEqual(r2["status"], "success")
            self.assertFalse(r2["changed"])
            self.assertEqual(r2["errors"], [])

    # ---------------------------------------------------------------
    # Task 2.2 - Fail-open when module_plot.json is missing
    # ---------------------------------------------------------------

    def test_fail_open_missing_plot_file(self) -> None:
        """Returns degraded when module_plot.json is missing."""
        with tempfile.TemporaryDirectory() as td:
            module_dir = Path(td) / "Test_Module"
            module_dir.mkdir()
            _write_module_context(module_dir, has_continuity=False)

            from utils.toolkit_publishability_finalizer import (
                finalize_module_publishability_metadata,
            )

            result = finalize_module_publishability_metadata(
                "Test_Module", module_dir
            )

            self.assertEqual(result["status"], "degraded")
            warnings_str = " ".join(result["warnings"])
            self.assertIn("cross_refs_skipped_no_plot", warnings_str)
            self.assertIn("semantic_authority_skipped_no_plot", warnings_str)
            # Continuity keys should still be injected even without plot
            self.assertTrue(result["changed"])

    # ---------------------------------------------------------------
    # Task 2.2 - BU mirror parity
    # ---------------------------------------------------------------

    def test_bu_mirror_parity(self) -> None:
        """BU mirror is updated when module_context changes."""
        with tempfile.TemporaryDirectory() as td:
            module_dir = Path(td) / "Test_Module"
            module_dir.mkdir()
            _write_module_context(module_dir, has_continuity=False)
            _write_module_plot(module_dir)

            # Create BU mirror as exact copy of initial context
            src = (module_dir / "module_context.json").read_text(encoding="utf-8")
            (module_dir / "module_context_BU.json").write_text(src, encoding="utf-8")

            from utils.toolkit_publishability_finalizer import (
                finalize_module_publishability_metadata,
            )

            result = finalize_module_publishability_metadata(
                "Test_Module", module_dir
            )

            self.assertTrue(result["changed"])

            # Both files should now have continuity and be identical
            ctx = json.loads(
                (module_dir / "module_context.json").read_text(encoding="utf-8")
            )
            bu_ctx = json.loads(
                (module_dir / "module_context_BU.json").read_text(encoding="utf-8")
            )
            self.assertIn("continuity", ctx)
            self.assertEqual(ctx, bu_ctx)


# ===================================================================
# TestIngestSidecarPersistence
# ===================================================================

class TestIngestSidecarPersistence(unittest.TestCase):
    """Test persist_ingest_sidecar() and sidecar audit integration (Task 3.2)."""

    maxDiff = None

    # ---------------------------------------------------------------
    # Task 3.2 - Sidecar written after finalize
    # ---------------------------------------------------------------

    def test_sidecar_written_after_finalize(self) -> None:
        """Sidecar is written after finalize completes."""
        with tempfile.TemporaryDirectory() as td:
            module_dir = Path(td) / "Test_Module"
            module_dir.mkdir()
            archive_root = Path(td) / "ingest" / "archive"

            _write_module_context(module_dir, has_continuity=False)
            _write_module_plot(module_dir)

            from utils.toolkit_publishability_finalizer import (
                finalize_module_publishability_metadata,
                persist_ingest_sidecar,
            )

            # Step 1: Finalize metadata
            r1 = finalize_module_publishability_metadata(
                "Test_Module", module_dir
            )
            self.assertEqual(r1["status"], "success")

            # Step 2: Persist sidecar
            r2 = persist_ingest_sidecar(
                "Test_Module", module_dir, archive_root=archive_root
            )
            self.assertEqual(r2["status"], "success")

            # Step 3: Sidecar file exists on disk
            sidecar_path = Path(r2["sidecar_path"])
            self.assertTrue(
                sidecar_path.exists(),
                f"Sidecar file should exist: {sidecar_path}",
            )
            self.assertIn("Test_Module", sidecar_path.name)
            self.assertTrue(
                sidecar_path.name.endswith(".result.json")
            )

            # Step 4: Sidecar contains expected payload shape
            payload = json.loads(
                sidecar_path.read_text(encoding="utf-8")
            )
            self.assertEqual(payload["module_slug"], "Test_Module")
            self.assertEqual(payload["status"], "success")
            self.assertIn("ingest", payload)
            self.assertIn("registration", payload["ingest"])
            self.assertTrue(
                payload["ingest"]["registration"]["registration_attempted"]
            )

    # ---------------------------------------------------------------
    # Task 3.2 - Sidecar found by find_latest
    # ---------------------------------------------------------------

    def test_sidecar_found_by_find_latest(self) -> None:
        """Sidecar written via persist is found by find_latest_sidecar_for_slug."""
        with tempfile.TemporaryDirectory() as td:
            module_dir = Path(td) / "Test_Module"
            module_dir.mkdir()
            archive_root = Path(td) / "ingest" / "archive"

            from utils.toolkit_publishability_finalizer import (
                persist_ingest_sidecar,
            )

            # Write a sidecar
            r = persist_ingest_sidecar(
                "Test_Module", module_dir, archive_root=archive_root
            )
            self.assertEqual(r["status"], "success")

            # Find it via find_latest_sidecar_for_slug
            from scripts.homebrew_sidecar_audit import (
                find_latest_sidecar_for_slug,
            )

            with mock.patch(
                "scripts.homebrew_sidecar_audit.ARCHIVE_ROOT",
                archive_root,
            ):
                found = find_latest_sidecar_for_slug("Test_Module")

            self.assertIsNotNone(found)
            expected = Path(r["sidecar_path"]).resolve()
            actual = Path(found).resolve()
            self.assertEqual(actual, expected)

    # ---------------------------------------------------------------
    # Task 3.2 - Sidecar passes require_success audit
    # ---------------------------------------------------------------

    def test_sidecar_passes_require_success_audit(self) -> None:
        """Sidecar with status=success passes audit_sidecar require_success=True."""
        with tempfile.TemporaryDirectory() as td:
            module_dir = Path(td) / "Test_Module"
            module_dir.mkdir()
            archive_root = Path(td) / "ingest" / "archive"

            from utils.toolkit_publishability_finalizer import (
                persist_ingest_sidecar,
            )

            # Write a success sidecar
            r = persist_ingest_sidecar(
                "Test_Module", module_dir, archive_root=archive_root
            )
            self.assertEqual(r["status"], "success")

            # Audit it with require_success=True
            from scripts.homebrew_sidecar_audit import audit_sidecar

            with mock.patch(
                "scripts.homebrew_sidecar_audit.ARCHIVE_ROOT",
                archive_root,
            ):
                result = audit_sidecar(
                    "Test_Module", require_success=True
                )

            self.assertTrue(
                result["valid"],
                f"Sidecar should be valid: {result.get('errors')}",
            )
            self.assertEqual(result["status"], "success")
            self.assertEqual(result["exit_code"], 0)
            self.assertTrue(result["sidecar_found"])
            self.assertTrue(
                result["registration"]["registration_attempted"]
            )
            self.assertTrue(
                result["registration"]["registry_module_present"]
            )

    # ---------------------------------------------------------------
    # Task 3.2 - Sidecar idempotent overwrite (by mtime recency)
    # ---------------------------------------------------------------

    def test_sidecar_idempotent_overwrite(self) -> None:
        """Multiple sidecars for same slug: find_latest returns the newest."""
        with tempfile.TemporaryDirectory() as td:
            module_dir = Path(td) / "Test_Module"
            module_dir.mkdir()
            archive_root = Path(td) / "ingest" / "archive"

            from utils.toolkit_publishability_finalizer import (
                persist_ingest_sidecar,
            )

            # Write first sidecar
            r1 = persist_ingest_sidecar(
                "Test_Module", module_dir, archive_root=archive_root
            )
            self.assertEqual(r1["status"], "success")
            p1 = Path(r1["sidecar_path"])

            # Wait for the timestamp to roll over (format is YYYYMMDD_HHMMSS,
            # 1-second resolution) so the second write gets a different filename.
            time.sleep(1.1)

            # Write second sidecar
            r2 = persist_ingest_sidecar(
                "Test_Module", module_dir, archive_root=archive_root
            )
            self.assertEqual(r2["status"], "success")
            p2 = Path(r2["sidecar_path"])

            # Both files exist with distinct paths and timestamps
            self.assertTrue(p1.exists())
            self.assertTrue(p2.exists())
            self.assertNotEqual(
                p1.name, p2.name,
                "Each sidecar should have a unique timestamped filename",
            )

            # find_latest should return the newest sidecar
            from scripts.homebrew_sidecar_audit import (
                find_latest_sidecar_for_slug,
            )

            with mock.patch(
                "scripts.homebrew_sidecar_audit.ARCHIVE_ROOT",
                archive_root,
            ):
                found = find_latest_sidecar_for_slug("Test_Module")

            self.assertIsNotNone(found)
            expected = p2.resolve()
            actual = Path(found).resolve()
            self.assertEqual(
                actual, expected,
                "find_latest_sidecar_for_slug should return the newest sidecar",
            )

            # audit_sidecar with the latest file should also pass
            from scripts.homebrew_sidecar_audit import audit_sidecar

            with mock.patch(
                "scripts.homebrew_sidecar_audit.ARCHIVE_ROOT",
                archive_root,
            ):
                audit_result = audit_sidecar(
                    "Test_Module", require_success=True
                )
            self.assertTrue(audit_result["valid"])
            self.assertEqual(audit_result["status"], "success")


# ===================================================================
# TestMonsterMediaClosure
# ===================================================================

class TestMonsterMediaClosure(unittest.TestCase):
    """Test deterministic monster media placeholder closure (Task 4.2)."""

    maxDiff = None

    # ---------------------------------------------------------------
    # Task 4.2 - Placeholders created for missing monsters
    # ---------------------------------------------------------------

    def test_placeholders_created_for_missing_monsters(self) -> None:
        """Placeholder JPEGs are created for every monster missing base media."""
        with tempfile.TemporaryDirectory() as td:
            module_dir = Path(td) / "Test_Module"
            module_dir.mkdir()
            _write_monster_json(module_dir, "goblin", "skeleton", "zombie")

            from utils.module_monster_media_closure import close_monster_base_media

            result = close_monster_base_media(str(module_dir))

            self.assertEqual(result["created"], 3)
            self.assertEqual(result["skipped"], 0)
            self.assertEqual(result["errors"], [])

            # Verify each file exists on disk
            for slug in ("goblin", "skeleton", "zombie"):
                target = module_dir / "media" / "monsters" / f"{slug}.jpg"
                self.assertTrue(
                    target.exists(),
                    f"Placeholder JPEG should exist: {target}",
                )

    # ---------------------------------------------------------------
    # Task 4.2 - Existing media is preserved (not overwritten)
    # ---------------------------------------------------------------

    def test_existing_media_preserved(self) -> None:
        """Existing monster media files are never overwritten by closure."""
        SENTINEL: bytes = b"SENTINEL_MEDIA_CONTENT_PRESERVE_ME"

        with tempfile.TemporaryDirectory() as td:
            module_dir = Path(td) / "Test_Module"
            module_dir.mkdir()
            _write_monster_json(module_dir, "goblin", "skeleton", "zombie")

            # Pre-create skeleton.jpg with distinctive sentinel content
            media_dir = module_dir / "media" / "monsters"
            media_dir.mkdir(parents=True, exist_ok=True)
            (media_dir / "skeleton.jpg").write_bytes(SENTINEL)

            from utils.module_monster_media_closure import close_monster_base_media

            result = close_monster_base_media(str(module_dir))

            # Only goblin and zombie should be created; skeleton was skipped
            self.assertEqual(result["created"], 2)
            self.assertEqual(result["skipped"], 1)
            self.assertEqual(result["errors"], [])

            # Verify skeleton.jpg content is unchanged (sentinel preserved)
            actual: bytes = (media_dir / "skeleton.jpg").read_bytes()
            self.assertEqual(actual, SENTINEL,
                             "Existing media must not be overwritten")

            # Verify the new placeholders do exist
            for slug in ("goblin", "zombie"):
                target = media_dir / f"{slug}.jpg"
                self.assertTrue(
                    target.exists(),
                    f"New placeholder should exist: {target}",
                )

    # ---------------------------------------------------------------
    # Task 4.2 - Placeholder is a valid JPEG
    # ---------------------------------------------------------------

    def test_placeholder_is_valid_jpeg(self) -> None:
        """Generated placeholder JPEG starts with SOI and ends with EOI."""
        with tempfile.TemporaryDirectory() as td:
            module_dir = Path(td) / "Test_Module"
            module_dir.mkdir()
            _write_monster_json(module_dir, "test_beast")

            from utils.module_monster_media_closure import close_monster_base_media

            result = close_monster_base_media(str(module_dir))
            self.assertEqual(result["created"], 1)

            target = module_dir / "media" / "monsters" / "test_beast.jpg"
            data: bytes = target.read_bytes()

            self.assertGreaterEqual(len(data), 2,
                                    "JPEG must be at least 2 bytes")
            self.assertEqual(
                data[:2], b"\xff\xd8",
                "JPEG must start with SOI marker (FF D8)",
            )
            self.assertEqual(
                data[-2:], b"\xff\xd9",
                "JPEG must end with EOI marker (FF D9)",
            )

    # ---------------------------------------------------------------
    # Task 4.2 - Gameplay audit passes after closure
    # ---------------------------------------------------------------

    def test_base_media_detected_as_present_after_closure(self) -> None:
        """check_monster_media reports base=True and classify returns reused."""
        from scripts.audit_module_gameplay import (
            MEDIA_OUTCOME_REUSED_OR_GENERATED,
            check_monster_media,
            classify_monster_media_outcome,
        )

        with tempfile.TemporaryDirectory() as td:
            module_dir = Path(td) / "Test_Module"
            module_dir.mkdir()
            _write_monster_json(module_dir, "goblin", "skeleton")

            from utils.module_monster_media_closure import close_monster_base_media

            result = close_monster_base_media(str(module_dir))
            self.assertEqual(result["created"], 2)

            # Verify each monster's media is detected as present
            for slug in ("goblin", "skeleton"):
                media_status = check_monster_media(str(module_dir), slug)
                self.assertTrue(
                    media_status.get("base"),
                    f"Base media for '{slug}' should be present after closure",
                )
                outcome = classify_monster_media_outcome(media_status)
                self.assertEqual(
                    outcome,
                    MEDIA_OUTCOME_REUSED_OR_GENERATED,
                    f"Outcome for '{slug}' should indicate reused/generated",
                )

    # ---------------------------------------------------------------
    # Task 4.2 - No PIL/Pillow dependency
    # ---------------------------------------------------------------

    def test_no_pillow_dependency(self) -> None:
        """Closure helper module has no PIL/Pillow import statements."""
        module_path = (
            Path(__file__).resolve().parent.parent
            / "utils"
            / "module_monster_media_closure.py"
        )
        source: str = module_path.read_text(encoding="utf-8")
        for pattern in (
            "import PIL",
            "from PIL",
            "import Pillow",
            "from Pillow",
            "Pillow.",
        ):
            self.assertNotIn(
                pattern, source,
                f"Source must not contain '{pattern}'",
            )


# ===================================================================
# TestPipelineIntegration - Task 5.4
# ===================================================================

class TestPipelineIntegration(unittest.TestCase):
    """Test finisher stage helpers directly (Task 5.4).

    Each test exercises one stage helper isolated from the full
    ``run_toolkit_module_postbuild_finishing()`` pipeline.  All tests
    are tempdir-backed and require no server or provider dependencies.
    """

    maxDiff = None

    @staticmethod
    def _make_module(td_root: str) -> Path:
        """Create a minimal temp module dir with context, plot, and monsters."""
        module_dir = Path(td_root) / "Test_Module"
        module_dir.mkdir()
        _write_module_context(module_dir, has_continuity=False,
                              has_semantic_authority=False)
        _write_module_plot(module_dir)
        _write_monster_json(module_dir, "goblin", "skeleton")
        return module_dir

    # ---------------------------------------------------------------
    # Task 5.4 - Finisher adds continuity via publishability finalizer
    # ---------------------------------------------------------------

    def test_finisher_adds_continuity(self) -> None:
        """``_run_publishability_finalizer_stage`` adds continuity to module_context."""
        with tempfile.TemporaryDirectory() as td:
            module_dir = self._make_module(td)

            from web.extensions.toolkit_module_finisher import (
                _run_publishability_finalizer_stage,
            )

            result = _run_publishability_finalizer_stage(
                "Test_Module", module_dir,
            )

            self.assertEqual(result["status"], "success")
            self.assertTrue(result["changed"])
            self.assertEqual(result["errors"], [])

            ctx = json.loads(
                (module_dir / "module_context.json").read_text(encoding="utf-8")
            )
            c = ctx.get("continuity")
            self.assertIsInstance(c, dict)
            self.assertEqual(c.get("continuity_version"), "v1")
            self.assertIn("entry_state_variants", c)
            self.assertIn("cross_module_refs", c)
            self.assertIn("standalone_fallback", c)

    # ---------------------------------------------------------------
    # Task 5.4 - Finisher adds semantic authority
    # ---------------------------------------------------------------

    def test_finisher_adds_semantic_authority(self) -> None:
        """``_run_publishability_finalizer_stage`` adds semantic_authority."""
        with tempfile.TemporaryDirectory() as td:
            module_dir = self._make_module(td)

            from web.extensions.toolkit_module_finisher import (
                _run_publishability_finalizer_stage,
            )

            result = _run_publishability_finalizer_stage(
                "Test_Module", module_dir,
            )

            self.assertEqual(result["status"], "success")
            self.assertTrue(result["changed"])

            ctx = json.loads(
                (module_dir / "module_context.json").read_text(encoding="utf-8")
            )
            sa = ctx.get("semantic_authority")
            self.assertIsInstance(sa, dict)
            self.assertEqual(sa.get("version"), "v1")
            self.assertIn("location_aliases", sa)
            self.assertIn("destination_phrases", sa)
            self.assertIn("npc_scene_authority", sa)

    # ---------------------------------------------------------------
    # Task 5.4 - Finisher persists ingest sidecar
    # ---------------------------------------------------------------

    def test_finisher_adds_sidecar(self) -> None:
        """``_run_ingest_sidecar_persistence_stage`` writes a valid sidecar
        that can be found and audited."""
        with tempfile.TemporaryDirectory() as td:
            module_dir = self._make_module(td)
            archive_root = Path(td) / "ingest" / "archive"

            # Monkeypatch the finalizer's default archive root so the
            # stage helper writes into our temp directory.
            import utils.toolkit_publishability_finalizer as _tpf

            orig_root = _tpf._DEFAULT_ARCHIVE_ROOT
            _tpf._DEFAULT_ARCHIVE_ROOT = archive_root

            try:
                from web.extensions.toolkit_module_finisher import (
                    _run_ingest_sidecar_persistence_stage,
                )

                result = _run_ingest_sidecar_persistence_stage(
                    "Test_Module", module_dir, "success",
                )
                self.assertEqual(result["status"], "success")
                self.assertTrue(result["sidecar_path"])
                self.assertIn("Test_Module", result["sidecar_path"])
                self.assertTrue(result["sidecar_path"].endswith(".result.json"))

                sidecar_path = Path(result["sidecar_path"])
                self.assertTrue(
                    sidecar_path.exists(),
                    f"Sidecar file should exist: {sidecar_path}",
                )

                # Verify payload shape
                payload = json.loads(
                    sidecar_path.read_text(encoding="utf-8")
                )
                self.assertEqual(payload["module_slug"], "Test_Module")
                self.assertEqual(payload["status"], "success")
                self.assertIn("ingest", payload)
                self.assertTrue(
                    payload["ingest"]["registration"]["registration_attempted"]
                )

                # Verify sidecar is findable by the audit helpers
                from scripts.homebrew_sidecar_audit import (
                    audit_sidecar,
                    find_latest_sidecar_for_slug,
                )

                with mock.patch(
                    "scripts.homebrew_sidecar_audit.ARCHIVE_ROOT",
                    archive_root,
                ):
                    found = find_latest_sidecar_for_slug("Test_Module")
                    self.assertIsNotNone(found)
                    self.assertEqual(
                        Path(found).resolve(), sidecar_path.resolve()
                    )

                    audit = audit_sidecar(
                        "Test_Module", require_success=True
                    )
                    self.assertTrue(
                        audit["valid"],
                        f"Sidecar audit should pass: {audit.get('errors')}",
                    )
                    self.assertEqual(audit["status"], "success")
                    self.assertTrue(audit["sidecar_found"])
            finally:
                _tpf._DEFAULT_ARCHIVE_ROOT = orig_root

    # ---------------------------------------------------------------
    # Task 5.4 - Finisher closes missing monster base media
    # ---------------------------------------------------------------

    def test_finisher_closes_monster_media(self) -> None:
        """``_run_monster_media_closure_stage`` writes placeholder JPEGs for
        missing monster media and gameplay audit sees them as present."""
        with tempfile.TemporaryDirectory() as td:
            module_dir = self._make_module(td)

            from web.extensions.toolkit_module_finisher import (
                _run_monster_media_closure_stage,
            )

            result = _run_monster_media_closure_stage(module_dir)

            self.assertEqual(result["status"], "success")
            self.assertEqual(result["created"], 2)   # goblin, skeleton
            self.assertEqual(result["skipped"], 0)
            self.assertEqual(result["errors"], [])

            for slug in ("goblin", "skeleton"):
                target = module_dir / "media" / "monsters" / f"{slug}.jpg"
                self.assertTrue(
                    target.exists(),
                    f"Placeholder JPEG should exist: {target}",
                )
                data = target.read_bytes()
                self.assertEqual(data[:2], b"\xff\xd8",
                                 "JPEG must start with SOI marker")
                self.assertEqual(data[-2:], b"\xff\xd9",
                                 "JPEG must end with EOI marker")

            # gameplay audit helpers detect base media as present
            from scripts.audit_module_gameplay import (
                check_monster_media,
                classify_monster_media_outcome,
            )
            from scripts.audit_module_gameplay import (
                MEDIA_OUTCOME_REUSED_OR_GENERATED,
            )

            for slug in ("goblin", "skeleton"):
                media_status = check_monster_media(str(module_dir), slug)
                self.assertTrue(
                    media_status.get("base"),
                    f"Base media for '{slug}' should be present",
                )
                outcome = classify_monster_media_outcome(media_status)
                self.assertEqual(
                    outcome, MEDIA_OUTCOME_REUSED_OR_GENERATED,
                )

        # Also verify existing media is preserved (skipped)
        with tempfile.TemporaryDirectory() as td:
            module_dir = self._make_module(td)
            media_dir = module_dir / "media" / "monsters"
            media_dir.mkdir(parents=True, exist_ok=True)
            SENTINEL = b"EXISTING_MEDIA_DO_NOT_OVERWRITE"
            (media_dir / "goblin.jpg").write_bytes(SENTINEL)

            result = _run_monster_media_closure_stage(module_dir)

            self.assertEqual(result["created"], 1)    # skeleton only
            self.assertEqual(result["skipped"], 1)    # goblin pre-existed
            self.assertEqual(result["errors"], [])

            # Verify sentinel preserved
            actual = (media_dir / "goblin.jpg").read_bytes()
            self.assertEqual(actual, SENTINEL)
            self.assertTrue((media_dir / "skeleton.jpg").exists())


# ===================================================================
# Entrypoint
# ===================================================================

if __name__ == "__main__":
    unittest.main()
