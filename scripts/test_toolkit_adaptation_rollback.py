# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.

"""Provider-free rollback verification for the production adaptation wiring.

This test deliberately uses process-local configuration patches.  It does not
create staging artifacts, invoke a provider, or touch live module state.  The
existing project-local ``tmp/`` tree is treated as prior staging evidence and
must be byte-for-byte unchanged by the rollback checks.
"""

from __future__ import annotations

import hashlib
import sys
import unittest
from pathlib import Path
from typing import Any, Dict, Mapping
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import model_config
from utils.toolkit_adaptation_config import (
    BUILD_MODE_LEGACY_ACCURATE_INGEST,
    BUILD_MODE_LLM_ADAPTATION,
    INPUT_KIND_TEXT_DESCRIPTION,
    INPUT_KIND_UPLOAD_MARKDOWN,
    INPUT_KIND_UPLOAD_PDF,
    canonical_monster_generation_enabled,
    resolve_adaptation_input_route,
)
from utils.toolkit_adaptation_dossier import RIGHTS_CLASS_USER_AUTHORED
from utils.toolkit_adaptation_provenance import build_adaptation_provenance
from web.extensions import toolkit_adaptation_runtime
from web.extensions import toolkit_homebrew_packet_builder
from web.extensions import toolkit_text_adaptation_worker
from web.routes import toolkit_homebrew_routes


REPO_ROOT = Path(__file__).resolve().parents[1]
TMP_ROOT = REPO_ROOT / "tmp"
SOURCE_HASH = "c" * 64


def _tree_snapshot(root: Path) -> Dict[str, Any]:
    """Hash existing project-local staging/report evidence without writing."""
    snapshot: Dict[str, Any] = {}
    if not root.is_dir():
        return snapshot
    for path in sorted(root.rglob("*")):
        relative = str(path.relative_to(root))
        if path.is_symlink():
            snapshot[relative] = ("symlink", str(path.readlink()))
        elif path.is_file():
            snapshot[relative] = (
                "file",
                hashlib.sha256(path.read_bytes()).hexdigest(),
                path.stat().st_size,
            )
        elif path.is_dir():
            snapshot[relative] = ("directory",)
    return snapshot


def _upload_kwargs(kind: str) -> Dict[str, Any]:
    return {
        "input_kind": kind,
        "enabled_override": None,
        "source_kind": kind,
        "source_hash": SOURCE_HASH,
        "source_title": "Rollback Adventure",
        "rights_class": RIGHTS_CLASS_USER_AUTHORED,
        "rights_basis": "uploader_declared_user_authored",
        "rights_review_required": False,
        "rights_review_status": "not_required",
        "attempt_id": "rollback-attempt",
        "job_id": "rollback-job",
        "attempt_number": 1,
    }


class TestProductionAdaptationRollback(unittest.TestCase):
    """Disabling rollout flags restores both legacy entry-point contracts."""

    def setUp(self) -> None:
        self.before_tmp = _tree_snapshot(TMP_ROOT)
        self.old_adaptation = getattr(model_config, "ENABLE_LLM_ADAPTATION", None)
        self.had_adaptation = hasattr(model_config, "ENABLE_LLM_ADAPTATION")
        self.old_canonical = getattr(
            model_config,
            "ENABLE_LLM_ADAPTATION_CANONICAL_MONSTER_GENERATION",
            None,
        )
        self.had_canonical = hasattr(
            model_config, "ENABLE_LLM_ADAPTATION_CANONICAL_MONSTER_GENERATION"
        )
        model_config.ENABLE_LLM_ADAPTATION = False
        model_config.ENABLE_LLM_ADAPTATION_CANONICAL_MONSTER_GENERATION = False

    def tearDown(self) -> None:
        if self.had_adaptation:
            model_config.ENABLE_LLM_ADAPTATION = self.old_adaptation
        else:
            delattr(model_config, "ENABLE_LLM_ADAPTATION")
        if self.had_canonical:
            model_config.ENABLE_LLM_ADAPTATION_CANONICAL_MONSTER_GENERATION = (
                self.old_canonical
            )
        else:
            delattr(
                model_config, "ENABLE_LLM_ADAPTATION_CANONICAL_MONSTER_GENERATION"
            )
        self.assertEqual(_tree_snapshot(TMP_ROOT), self.before_tmp)

    def test_upload_inputs_return_to_legacy_without_adaptation_handoff(self) -> None:
        """Both eligible upload types omit callback and adaptation kwargs."""
        callback = object()
        for kind in (INPUT_KIND_UPLOAD_MARKDOWN, INPUT_KIND_UPLOAD_PDF):
            with self.subTest(input_kind=kind):
                decision = resolve_adaptation_input_route(**_upload_kwargs(kind))
                self.assertEqual(decision["route_selected"], BUILD_MODE_LEGACY_ACCURATE_INGEST)

                captured: Dict[str, Any] = {}

                def fake_packet_builder(**kwargs: Any) -> Dict[str, Any]:
                    captured.update(kwargs)
                    return {"status": "success", "build_mode": BUILD_MODE_LEGACY_ACCURATE_INGEST}

                with patch.object(
                    toolkit_homebrew_packet_builder,
                    "run_toolkit_homebrew_packet_build",
                    side_effect=fake_packet_builder,
                ):
                    result = toolkit_homebrew_routes._run_homebrew_packet_build(
                        TMP_ROOT,
                        "rollback-upload-job",
                        adaptation_route=decision["route_selected"],
                        adaptation_convergence_callback_override=callback,
                    )

                self.assertEqual(result["build_mode"], BUILD_MODE_LEGACY_ACCURATE_INGEST)
                self.assertNotIn("adaptation_convergence_callback", captured)
                self.assertNotIn("adaptation_provenance", captured)
                self.assertNotIn("adaptation_dossier", captured)
                self.assertNotIn("adaptation_staging_target", captured)
                self.assertNotIn("adaptation_route", captured)

    def test_text_description_returns_none_without_authoring_or_provenance(self) -> None:
        """The text worker's adaptation seam falls through to its legacy worker."""
        provider_calls = []

        def forbidden_author(*args: Any, **kwargs: Any) -> Dict[str, Any]:
            provider_calls.append((args, kwargs))
            raise AssertionError("rollback must not invoke adaptation authoring")

        result = toolkit_text_adaptation_worker.run_text_description_adaptation_seam(
            "Rollback_Text_Adventure",
            "A bounded legacy text-description fixture.",
            {"job_id": "rollback-text-job", "attempt_number": 1},
            author_runner=forbidden_author,
        )
        self.assertIsNone(result)
        self.assertEqual(provider_calls, [])
        self.assertIs(
            toolkit_adaptation_runtime.adaptation_convergence_callback is not None,
            True,
        )

    def test_canonical_generation_stays_disabled_and_provider_metadata_cannot_elevate(self) -> None:
        """False, missing, invalid, and advisory metadata all remain disabled."""
        self.assertIs(canonical_monster_generation_enabled(), False)
        for invalid in (None, "true", 1, {}, [], "False"):
            with self.subTest(value=repr(invalid)):
                self.assertIs(canonical_monster_generation_enabled(invalid), False)

        provenance = build_adaptation_provenance(
            provenance={
                "source_hash": SOURCE_HASH,
                "source_title": "Rollback",
                "rights_class": RIGHTS_CLASS_USER_AUTHORED,
                "allow_canonical_monster_generation": True,
                "provider_metadata": {
                    "allow_canonical_monster_generation": True,
                },
            },
            adaptation_status="adapted",
            module_slug="Rollback_Module",
        )
        self.assertNotIn("allow_canonical_monster_generation", provenance)

    def test_process_local_flags_are_restored(self) -> None:
        """Rollback verification does not alter shipped process configuration."""
        self.assertIs(model_config.ENABLE_LLM_ADAPTATION, False)
        self.assertIs(
            model_config.ENABLE_LLM_ADAPTATION_CANONICAL_MONSTER_GENERATION, False
        )


if __name__ == "__main__":
    unittest.main()
