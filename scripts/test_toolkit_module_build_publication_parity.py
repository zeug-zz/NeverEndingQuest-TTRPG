# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Regression tests for toolkit module post-build publication parity."""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import web.extensions.toolkit_module_finisher as finisher


class TestToolkitModuleFinisher(unittest.TestCase):
    """Verify finisher status mapping and report persistence."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self.temp_dir.name)
        self.original_cwd = Path.cwd()
        os.chdir(self.repo_root)

        self.module_slug = "Parity_Test_Module"
        self.module_dir = self.repo_root / "modules" / self.module_slug
        self.module_dir.mkdir(parents=True, exist_ok=True)
        (self.module_dir / "module_context.json").write_text("{}", encoding="utf-8")
        (self.module_dir / "module_context_BU.json").write_text("{}", encoding="utf-8")
        (self.module_dir / "module_plot.json").write_text("{}", encoding="utf-8")
        (self.module_dir / "module_plot_BU.json").write_text("{}", encoding="utf-8")
        # TABLETOP MODE: Write a pass validation report so report-agreement
        # stage doesn't block on missing reports in test stubs.
        (self.module_dir / "validation_report.json").write_text(
            json.dumps({"summary": {"total_failed": 0}}), encoding="utf-8"
        )
        (self.module_dir / "source_fidelity_report.json").write_text(
            json.dumps({"source_fidelity_status": "pass"}), encoding="utf-8"
        )
        self.original_continuity = finisher._run_continuity_stage
        self.original_registry = finisher._run_registry_stage
        self.original_materialization = finisher._run_monster_materialization_stage
        self.original_publishability = finisher._run_publishability_stage
        self.original_semantic_auth = finisher._run_semantic_authority_stage

        # Mock semantic authority to no-op (test stub modules have empty data)
        finisher._run_semantic_authority_stage = lambda *args, **kwargs: {
            "status": "success",
            "changed": False,
            "semantic_authority": {},
            "warnings": [],
            "errors": [],
        }

        # Disable LLM classification in test stubs
        import model_config
        self._orig_llm_classification = model_config.ENABLE_LLM_CLASSIFICATION
        model_config.ENABLE_LLM_CLASSIFICATION = False

        # Ensure _sf_report_persisted is True in test stubs by wrapping
        # safe_write_json to always return True while still writing files,
        # and stubbing _build_source_fidelity_report_artifact.
        self._orig_safe_write = finisher.safe_write_json
        def _force_success_safe_write(path, data, **kw):
            self._orig_safe_write(path, data, **kw)
            return True
        finisher.safe_write_json = _force_success_safe_write

        self._orig_sf_artifact_builder = None
        try:
            import scripts.audit_module_publishability as sap
            self._orig_sf_artifact_builder = sap._build_source_fidelity_report_artifact
            sap._build_source_fidelity_report_artifact = (
                lambda module_slug, module_path, publishability_report: {
                    "source_fidelity_status": "pass",
                    "module": module_slug,
                }
            )
        except Exception:
            pass

    def tearDown(self) -> None:
        finisher._run_continuity_stage = self.original_continuity
        finisher._run_registry_stage = self.original_registry
        finisher._run_monster_materialization_stage = self.original_materialization
        finisher._run_publishability_stage = self.original_publishability
        finisher._run_semantic_authority_stage = self.original_semantic_auth
        finisher.safe_write_json = self._orig_safe_write

        if self._orig_sf_artifact_builder:
            try:
                import scripts.audit_module_publishability as sap
                sap._build_source_fidelity_report_artifact = self._orig_sf_artifact_builder
            except Exception:
                pass

        import model_config
        model_config.ENABLE_LLM_CLASSIFICATION = self._orig_llm_classification

        os.chdir(self.original_cwd)
        self.temp_dir.cleanup()

    def test_finisher_success_writes_report(self) -> None:
        finisher._run_continuity_stage = lambda *args, **kwargs: {
            "status": "success",
            "stage": "continuity",
        }
        finisher._run_registry_stage = lambda *args, **kwargs: {
            "status": "success",
            "stage": "registry",
        }
        finisher._run_monster_materialization_stage = lambda *args, **kwargs: {
            "status": "success",
            "stage": "monster_materialization",
        }
        finisher._run_publishability_stage = lambda *args, **kwargs: {
            "status": "success",
            "ready_status": "pass",
            "publishable_status": "pass",
            "report": {
                "ready_status": "pass",
                "publishable_status": "pass",
                "source_fidelity_status": "pass",
                "source_fidelity_categories": [],
                "effective_publishable_status": "pass",
            },
        }

        result = finisher.run_toolkit_module_postbuild_finishing(
            self.module_slug, strict=True
        )

        self.assertEqual(result.get("status"), "success")
        report_path = Path(result.get("report_path", ""))
        self.assertTrue(report_path.exists())

        report_payload = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(report_payload.get("status"), "success")
        self.assertIn("publication_parity_note", report_payload)
        self.assertEqual(report_payload.get("ready_status"), "pass")
        self.assertEqual(report_payload.get("publishable_status"), "pass")
        self.assertEqual(report_payload.get("freshness_state"), "current")
        freshness = report_payload.get("report_freshness") or {}
        self.assertEqual(freshness.get("state"), "current")
        self.assertEqual(
            freshness.get("contract"),
            "toolkit_build_report_refresh_contract.v1",
        )
        provenance = report_payload.get("provenance") or {}
        self.assertEqual(
            provenance.get("refresh_contract"),
            "toolkit_build_report_refresh_contract.v1",
        )
        self.assertEqual(
            provenance.get("refresh_workflow"), "toolkit_postbuild_finisher"
        )
        self.assertEqual(provenance.get("refresh_reason"), "postbuild_finishing")

    def test_finisher_degraded_maps_status(self) -> None:
        finisher._run_continuity_stage = lambda *args, **kwargs: {"status": "success"}
        finisher._run_registry_stage = lambda *args, **kwargs: {"status": "success"}
        finisher._run_monster_materialization_stage = lambda *args, **kwargs: {
            "status": "degraded",
            "reason": "missing bestiary entries",
        }
        finisher._run_publishability_stage = lambda *args, **kwargs: {
            "status": "success",
            "ready_status": "pass",
            "publishable_status": "pass",
            "report": {
                "ready_status": "pass",
                "publishable_status": "pass",
                "source_fidelity_status": "pass",
                "source_fidelity_categories": [],
                "effective_publishable_status": "pass",
            },
        }

        result = finisher.run_toolkit_module_postbuild_finishing(
            self.module_slug, strict=True
        )
        self.assertEqual(result.get("status"), "degraded")
        self.assertEqual(result.get("freshness_state"), "degraded")
        self.assertEqual(
            (result.get("report_freshness") or {}).get("state"),
            "degraded",
        )

    def test_finisher_failed_registry_maps_failed(self) -> None:
        finisher._run_continuity_stage = lambda *args, **kwargs: {"status": "success"}
        finisher._run_registry_stage = lambda *args, **kwargs: {
            "status": "failed",
            "reason": "registry missing",
        }
        finisher._run_monster_materialization_stage = lambda *args, **kwargs: {
            "status": "success"
        }
        finisher._run_publishability_stage = lambda *args, **kwargs: {
            "status": "degraded",
            "ready_status": "pass",
            "publishable_status": "fail",
        }

        result = finisher.run_toolkit_module_postbuild_finishing(
            self.module_slug, strict=True
        )
        self.assertEqual(result.get("status"), "failed")
        self.assertEqual(
            (result.get("stages") or {}).get("registry", {}).get("reason"),
            "registry missing",
        )

    def test_finisher_publishable_failure_without_media_handoff_fails(self) -> None:
        finisher._run_continuity_stage = lambda *args, **kwargs: {"status": "success"}
        finisher._run_registry_stage = lambda *args, **kwargs: {"status": "success"}
        finisher._run_monster_materialization_stage = lambda *args, **kwargs: {
            "status": "success"
        }
        finisher._run_publishability_stage = lambda *args, **kwargs: {
            "status": "degraded",
            "ready_status": "pass",
            "publishable_status": "fail",
            "report": {
                "ready_status": "pass",
                "publishable_status": "fail",
                "readiness": {
                    "overall_status": "pass",
                },
                "remediation_categories": ["semantic_probe_failure"],
                "blocking_errors": ["semantic_probe_failure: travel continuity mismatch"],
                "toolkit_media_policy": {
                    "structural_media_debt_count": 0,
                    "structural_media_debt_slugs": [],
                },
            },
        }

        result = finisher.run_toolkit_module_postbuild_finishing(
            self.module_slug, strict=True
        )
        self.assertEqual(result.get("status"), "failed")
        self.assertEqual(result.get("ready_status"), "pass")
        self.assertEqual(result.get("publishable_status"), "fail")

    def test_monster_materialization_stage_fails_on_blocked_count(self) -> None:
        with patch(
            "scripts.homebrew_materialize_monsters.materialize_monsters",
            return_value={
                "status": "degraded",
                "blocked_count": 1,
                "blocker_classes": {"authorized_monster_provider_unavailable": 1},
            },
        ):
            stage = finisher._run_monster_materialization_stage(self.module_slug)
            self.assertEqual(stage.get("status"), "failed")
            self.assertIn(
                "authorized_monster_provider_unavailable",
                str(stage.get("reason") or ""),
            )
            parsed_output = stage.get("parsed_output") or {}
            self.assertEqual(int(parsed_output.get("blocked_count", 0)), 1)

    def test_same_run_provenance_report_exists_before_publishability_stage(self) -> None:
        """Verify toolkit_build_report.json is written BEFORE publishability runs."""
        write_order = []
        original_safe_write = finisher.safe_write_json

        def _tracking_safe_write(path: str, data, **kwargs):
            write_order.append(("write", Path(path).name))
            return original_safe_write(path, data, **kwargs)

        finisher._run_continuity_stage = lambda *args, **kwargs: {
            "status": "success",
        }
        finisher._run_registry_stage = lambda *args, **kwargs: {"status": "success"}
        finisher._run_monster_materialization_stage = lambda *args, **kwargs: {
            "status": "success",
        }

        def _tracking_publishability(*args, **kwargs):
            report_path = self.module_dir / "toolkit_build_report.json"
            exists_before = report_path.exists()
            write_order.append(("publishability_called", exists_before))
            return {
                "status": "success",
                "ready_status": "pass",
                "publishable_status": "pass",
                "report": {
                    "ready_status": "pass",
                    "publishable_status": "pass",
                    "source_fidelity_status": "pass",
                    "source_fidelity_categories": [],
                    "effective_publishable_status": "pass",
                },
            }

        finisher._run_publishability_stage = _tracking_publishability

        with patch.object(finisher, "safe_write_json", _tracking_safe_write):
            result = finisher.run_toolkit_module_postbuild_finishing(
                self.module_slug, strict=True
            )

        pre_write_events = [
            e for e in write_order if e[0] == "write"
        ]
        pub_called_after_pre_write = any(
            e[1] == "toolkit_build_report.json" for e in pre_write_events
        )
        pub_event = next(
            e for e in write_order if e[0] == "publishability_called"
        )
        self.assertTrue(
            pub_event[1],
            "toolkit_build_report.json must exist before publishability stage runs",
        )
        self.assertTrue(
            pub_called_after_pre_write,
            "toolkit_build_report.json must be written before publishability stage",
        )

    def test_pre_publishability_write_is_stale_then_final_write_is_current(self) -> None:
        """Report writes must progress stale -> current in one finisher run."""
        captured_reports = []
        original_safe_write = finisher.safe_write_json

        def _tracking_safe_write(path: str, data, **kwargs):
            if Path(path).name == "toolkit_build_report.json":
                captured_reports.append(json.loads(json.dumps(data)))
            return original_safe_write(path, data, **kwargs)

        finisher._run_continuity_stage = lambda *args, **kwargs: {"status": "success"}
        finisher._run_registry_stage = lambda *args, **kwargs: {"status": "success"}
        finisher._run_monster_materialization_stage = lambda *args, **kwargs: {
            "status": "success"
        }
        finisher._run_publishability_stage = lambda *args, **kwargs: {
            "status": "success",
            "ready_status": "pass",
            "publishable_status": "pass",
            "report": {
                "ready_status": "pass",
                "publishable_status": "pass",
                "source_fidelity_status": "pass",
                "source_fidelity_categories": [],
                "effective_publishable_status": "pass",
            },
        }

        with patch.object(finisher, "safe_write_json", _tracking_safe_write):
            result = finisher.run_toolkit_module_postbuild_finishing(
                self.module_slug, strict=True
            )

        self.assertEqual(result.get("status"), "success")
        self.assertGreaterEqual(len(captured_reports), 2)

        pre_publishability = captured_reports[0]
        final_report = captured_reports[-1]

        self.assertEqual(pre_publishability.get("freshness_state"), "stale")
        self.assertEqual(
            (pre_publishability.get("report_freshness") or {}).get("state"), "stale"
        )
        self.assertEqual(
            (pre_publishability.get("report_freshness") or {}).get("stale_reason"),
            "publishability_pending",
        )
        self.assertEqual(final_report.get("freshness_state"), "current")
        self.assertEqual((final_report.get("report_freshness") or {}).get("state"), "current")

    def test_refresh_helper_routes_shared_refresh_workflow(self) -> None:
        """Explicit refresh helper must use toolkit_report_refresh workflow."""
        with patch.object(
            finisher,
            "run_toolkit_module_postbuild_finishing",
            return_value={"status": "success"},
        ) as mocked_runner:
            finisher.refresh_toolkit_build_report(
                self.module_slug,
                strict=True,
                refresh_reason="toolkit_homebrew_route_finisher",
            )

        mocked_runner.assert_called_once_with(
            module_slug=self.module_slug,
            strict=True,
            refresh_reason="toolkit_homebrew_route_finisher",
            refresh_workflow="toolkit_report_refresh",
            extra_stages=None,
        )

    def test_mmg_completion_path_writes_final_media_report(self) -> None:
        source = (
            Path(__file__).resolve().parent.parent / "web" / "web_interface.py"
        ).read_text(encoding="utf-8")
        self.assertIn("write_module_media_generator_report", source)
        self.assertIn("media_report", source)

    def test_finisher_media_only_debt_yields_success_with_handoff(self) -> None:
        """Media-only debt: build succeeds with handoff semantics, not failure."""
        finisher._run_continuity_stage = lambda *args, **kwargs: {"status": "success"}
        finisher._run_registry_stage = lambda *args, **kwargs: {"status": "success"}
        finisher._run_monster_materialization_stage = lambda *args, **kwargs: {
            "status": "success",
        }
        finisher._run_publishability_stage = lambda *args, **kwargs: {
            "status": "degraded",
            "ready_status": "pass",
            "publishable_status": "fail",
            "report": {
                "ready_status": "pass",
                "publishable_status": "fail",
                "readiness": {
                    "overall_status": "pass",
                },
                "remediation_categories": ["structured_monster_media_missing"],
                "blocking_errors": ["missing base media files for monsters"],
                "toolkit_media_policy": {
                    "structural_media_debt_count": 2,
                    "structural_media_debt_slugs": ["goblin", "orc"],
                },
            },
        }

        result = finisher.run_toolkit_module_postbuild_finishing(
            self.module_slug, strict=True
        )

        self.assertEqual(result.get("status"), "success")
        publishability_stage = result.get("stages", {}).get("publishability", {})
        self.assertEqual(publishability_stage.get("status"), "degraded")
        media_handoff = publishability_stage.get("media_handoff", {})
        self.assertEqual(media_handoff.get("build_outcome"), "success_with_media_handoff")
        self.assertEqual(media_handoff.get("next_step"), "Module Builder -> Module Media Generator")
        self.assertEqual(media_handoff.get("media_debt_count"), 2)
        self.assertIn("goblin", media_handoff.get("media_debt_slugs", []))
        self.assertIn("Module Builder", str(media_handoff.get("message", "")))

    def test_finisher_media_handoff_allows_semantic_warning_only_context(self) -> None:
        """Semantic warning-only context must not block media handoff semantics."""
        finisher._run_continuity_stage = lambda *args, **kwargs: {"status": "success"}
        finisher._run_registry_stage = lambda *args, **kwargs: {"status": "success"}
        finisher._run_monster_materialization_stage = lambda *args, **kwargs: {
            "status": "success",
        }
        finisher._run_publishability_stage = lambda *args, **kwargs: {
            "status": "degraded",
            "ready_status": "pass",
            "publishable_status": "fail",
            "report": {
                "ready_status": "pass",
                "publishable_status": "fail",
                "readiness": {
                    "overall_status": "pass",
                },
                "remediation_categories": [
                    "structured_monster_media_missing",
                    "semantic_warning_only",
                ],
                "blocking_errors": ["missing base media files for monsters"],
                "toolkit_media_policy": {
                    "structural_media_debt_count": 1,
                    "structural_media_debt_slugs": ["oathbound_shade"],
                },
            },
        }

        result = finisher.run_toolkit_module_postbuild_finishing(
            self.module_slug, strict=True
        )

        self.assertEqual(result.get("status"), "success")
        publishability_stage = result.get("stages", {}).get("publishability", {})
        self.assertEqual(publishability_stage.get("status"), "degraded")
        media_handoff = publishability_stage.get("media_handoff", {})
        self.assertEqual(media_handoff.get("build_outcome"), "success_with_media_handoff")
        self.assertEqual(media_handoff.get("media_debt_count"), 1)
        self.assertIn("oathbound_shade", media_handoff.get("media_debt_slugs", []))

    def test_finisher_media_only_readiness_fail_still_yields_handoff(self) -> None:
        """Gameplay-only media debt failure should produce media handoff semantics."""
        finisher._run_continuity_stage = lambda *args, **kwargs: {"status": "success"}
        finisher._run_registry_stage = lambda *args, **kwargs: {"status": "success"}
        finisher._run_monster_materialization_stage = lambda *args, **kwargs: {
            "status": "success",
        }
        finisher._run_publishability_stage = lambda *args, **kwargs: {
            "status": "failed",
            "ready_status": "fail",
            "publishable_status": "fail",
            "report": {
                "ready_status": "fail",
                "publishable_status": "fail",
                "readiness": {
                    "overall_status": "fail",
                    "gates": {
                        "gameplay": {"status": "fail", "reason": "gameplay_blocking_errors"},
                        "schema": {"status": "pass"},
                        "continuity": {"status": "pass"},
                        "sidecar": {"status": "pass"},
                    },
                },
                "remediation_categories": [
                    "structured_monster_media_missing",
                    "toolkit_manual_media_generation_required",
                ],
                "blocking_errors": [
                    "readiness_gate_failed: module is not structurally ready"
                ],
                "toolkit_media_policy": {
                    "structural_media_debt_count": 2,
                    "structural_media_debt_slugs": ["goblin", "ogre"],
                },
            },
        }

        result = finisher.run_toolkit_module_postbuild_finishing(
            self.module_slug, strict=True
        )

        self.assertEqual(result.get("status"), "success")
        self.assertEqual(result.get("ready_status"), "fail")
        self.assertEqual(result.get("publishable_status"), "fail_with_media_handoff")
        media_handoff = (
            (result.get("stages") or {}).get("publishability") or {}
        ).get("media_handoff", {})
        self.assertEqual(media_handoff.get("build_outcome"), "success_with_media_handoff")
        self.assertEqual(media_handoff.get("media_debt_count"), 2)

    def test_finisher_real_structural_failure_still_fails(self) -> None:
        """Real structural failure (not media-only): build still fails."""
        finisher._run_continuity_stage = lambda *args, **kwargs: {
            "status": "failed",
            "reason": "continuity contract missing required keys",
        }
        finisher._run_registry_stage = lambda *args, **kwargs: {"status": "success"}
        finisher._run_monster_materialization_stage = lambda *args, **kwargs: {
            "status": "success",
        }
        finisher._run_publishability_stage = lambda *args, **kwargs: {
            "status": "failed",
            "ready_status": "fail",
            "publishable_status": "fail",
            "report": {
                "ready_status": "fail",
                "publishable_status": "fail",
                "readiness": {
                    "overall_status": "fail",
                },
                "remediation_categories": ["structured_monster_media_missing"],
                "blocking_errors": ["readiness_gate_failed: module is not structurally ready"],
                "toolkit_media_policy": {
                    "structural_media_debt_count": 0,
                    "structural_media_debt_slugs": [],
                },
            },
        }

        result = finisher.run_toolkit_module_postbuild_finishing(
            self.module_slug, strict=True
        )

        self.assertEqual(result.get("status"), "failed")
        self.assertIsNone(result.get("media_handoff"))
        continuity_stage = result.get("stages", {}).get("continuity", {})
        self.assertEqual(continuity_stage.get("status"), "failed")

    def test_finisher_non_media_blocking_errors_still_fails(self) -> None:
        """Non-media blocking errors present: build still fails even if media debt exists."""
        finisher._run_continuity_stage = lambda *args, **kwargs: {"status": "success"}
        finisher._run_registry_stage = lambda *args, **kwargs: {"status": "success"}
        finisher._run_monster_materialization_stage = lambda *args, **kwargs: {
            "status": "success",
        }
        finisher._run_publishability_stage = lambda *args, **kwargs: {
            "status": "degraded",
            "ready_status": "pass",
            "publishable_status": "fail",
            "report": {
                "ready_status": "pass",
                "publishable_status": "fail",
                "readiness": {
                    "overall_status": "pass",
                },
                "remediation_categories": ["structured_monster_media_missing"],
                "blocking_errors": [
                    "missing base media files for monsters",
                    "unresolved destination: NIG99 (does not exist in module)",
                ],
                "toolkit_media_policy": {
                    "structural_media_debt_count": 1,
                    "structural_media_debt_slugs": ["goblin"],
                },
            },
        }

        result = finisher.run_toolkit_module_postbuild_finishing(
            self.module_slug, strict=True
        )

        self.assertEqual(result.get("status"), "failed")
        self.assertIsNone(
            result.get("stages", {}).get("publishability", {}).get("media_handoff")
        )

    def test_finisher_mixed_category_blocks_media_handoff_even_if_blockers_are_sparse(self) -> None:
        """Mixed remediation category must block success-with-media-handoff semantics."""
        finisher._run_continuity_stage = lambda *args, **kwargs: {"status": "success"}
        finisher._run_registry_stage = lambda *args, **kwargs: {"status": "success"}
        finisher._run_monster_materialization_stage = lambda *args, **kwargs: {
            "status": "success",
        }
        finisher._run_publishability_stage = lambda *args, **kwargs: {
            "status": "degraded",
            "ready_status": "pass",
            "publishable_status": "fail",
            "report": {
                "ready_status": "pass",
                "publishable_status": "fail",
                "readiness": {
                    "overall_status": "pass",
                },
                "remediation_categories": [
                    "structured_monster_media_missing",
                    "semantic_publishability_blocking",
                    "mixed_media_semantic_blocking",
                ],
                "blocking_errors": [],
                "toolkit_media_policy": {
                    "structural_media_debt_count": 1,
                    "structural_media_debt_slugs": ["goblin"],
                },
            },
        }

        result = finisher.run_toolkit_module_postbuild_finishing(
            self.module_slug, strict=True
        )

        self.assertEqual(result.get("status"), "failed")
        self.assertIsNone(
            result.get("stages", {}).get("publishability", {}).get("media_handoff")
        )


class TestToolkitPublicationParitySourceContracts(unittest.TestCase):
    """Source-level contracts for web handler and toolkit UI integration."""

    def test_web_interface_invokes_finisher_and_reports_status(self) -> None:
        source = Path("web/web_interface.py").read_text(encoding="utf-8")
        routes_source = Path("web/routes/toolkit_homebrew_routes.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("run_toolkit_module_postbuild_finishing", source)
        self.assertIn("refresh_toolkit_build_report", routes_source)
        self.assertIn("stage_name': 'Post Build Finishing'", source)
        self.assertIn("generation_succeeded", source)
        self.assertIn("readiness_failed", source)
        self.assertIn("run_toolkit_builder_readiness_gate", source)
        self.assertIn("ready_for_finishing", source)
        self.assertIn("publishable_status", source)
        self.assertIn("_build_hydration_summary", routes_source)
        self.assertIn('"hydration_summary"', routes_source)

    def test_mmg_success_path_refreshes_persisted_build_report_fail_open(self) -> None:
        source = Path("web/web_interface.py").read_text(encoding="utf-8")

        self.assertIn("@socketio.on('generate_unified_assets')", source)
        self.assertIn('refresh_reason="module_media_generator"', source)
        self.assertIn("if refresh_toolkit_build_report", source)
        self.assertIn("MMG report refresh degraded", source)
        self.assertIn("socketio.emit('unified_generation_complete'", source)

    def test_unified_assets_tracks_static_media_without_marking_module_complete(self) -> None:
        source = Path("web/web_interface.py").read_text(encoding="utf-8")

        self.assertIn("@app.route('/api/toolkit/modules/<module_name>/unified-assets')", source)
        self.assertIn("'has_static_image': False", source)
        self.assertIn("'has_static_thumbnail': False", source)
        self.assertIn("'has_static_video': False", source)
        self.assertIn("MMG completion must align with module-side structural", source)

    def test_unified_assets_monster_slug_uses_runtime_normalization(self) -> None:
        source = Path("web/web_interface.py").read_text(encoding="utf-8")

        self.assertIn("normalize_character_name(monster['name'])", source)
        self.assertIn("normalize_character_name(monster_name)", source)

    def test_toolkit_module_scoped_media_route_exists(self) -> None:
        source = Path("web/web_interface.py").read_text(encoding="utf-8")

        self.assertIn("@app.route('/api/toolkit/modules/<module_name>/media/<media_type>/<path:filename>')", source)
        self.assertIn("def serve_toolkit_module_media", source)
        self.assertIn("ModulePathManager(module_name)", source)
        self.assertIn("from selected module", source)
        self.assertIn("from static fallback", source)

    def test_toolkit_template_exposes_finishing_stage_and_parity_note(self) -> None:
        source = Path("web/templates/module_toolkit.html").read_text(encoding="utf-8")

        self.assertIn("Post-Build Finishing", source)
        self.assertIn("Readiness Validation", source)
        self.assertIn("Readiness Repair", source)
        self.assertIn("Readiness Audit", source)
        self.assertIn("readiness_failed", source)
        self.assertIn("Publishability:", source)
        self.assertIn("Hydration Summary:", source)
        self.assertIn("buildHomebrewHydrationAwareDetails", source)

    def test_toolkit_template_exposes_fidelity_review_panel(self) -> None:
        source = Path("web/templates/module_toolkit.html").read_text(encoding="utf-8")

        self.assertIn("homebrew-fidelity-review-panel", source)
        self.assertIn("homebrew-fidelity-review-summary", source)
        self.assertIn("homebrew-fidelity-review-actions", source)
        self.assertIn("homebrew-fidelity-approve-btn", source)
        self.assertIn("homebrew-fidelity-reject-btn", source)
        self.assertIn("homebrew-fidelity-start-build-btn", source)
        self.assertIn("renderToolkitHomebrewFidelityReview", source)
        self.assertIn("submitToolkitHomebrewReviewDecision", source)
        self.assertIn("const canStartBuild = Boolean(reviewPayload && reviewPayload.can_start_build);", source)
        self.assertIn("Fidelity Review Can Start Build: ' + (canStartBuild ? 'yes' : 'no')", source)
        self.assertIn("['Can Start Build', canStartBuild ? 'yes' : 'no']", source)
        self.assertIn("if (canStartBuild) {", source)

    def test_toolkit_template_exposes_semantic_remediation_lane(self) -> None:
        source = Path("web/templates/module_toolkit.html").read_text(encoding="utf-8")

        self.assertIn("formatSemanticRemediationSection", source)
        self.assertIn("Semantic Remediation:", source)
        self.assertIn("blocking_findings", source)
        self.assertIn("Blocking Errors (fallback):", source)

    def test_toolkit_template_exposes_mixed_media_semantic_sections(self) -> None:
        source = Path("web/templates/module_toolkit.html").read_text(encoding="utf-8")

        self.assertIn("formatMediaRemediationSection", source)
        self.assertIn("Media Remediation:", source)
        self.assertIn("structural_media_debt_count", source)
        self.assertIn("buildToolkitFinishingFailureDetails", source)

    def test_toolkit_template_preserves_summary_plus_raw_payload_output(self) -> None:
        source = Path("web/templates/module_toolkit.html").read_text(encoding="utf-8")

        self.assertIn("const semanticRemediationText = formatSemanticRemediationSection", source)
        self.assertIn("const mediaRemediationText = formatMediaRemediationSection", source)
        self.assertIn("sections.push(semanticRemediationText)", source)
        self.assertIn("sections.push(mediaRemediationText)", source)
        self.assertIn("sections.push(`Raw Payload:", source)

    def test_toolkit_template_requests_module_list_after_mmg_completion(self) -> None:
        source = Path("web/templates/module_toolkit.html").read_text(encoding="utf-8")

        self.assertIn("socket.on('unified_generation_complete'", source)
        self.assertIn("socket.emit('request_module_list');", source)

    def test_toolkit_template_marks_static_fallback_as_non_complete(self) -> None:
        source = Path("web/templates/module_toolkit.html").read_text(encoding="utf-8")

        self.assertIn("getMediaStatusIcon", source)
        self.assertIn("Missing module media; static fallback exists", source)
        self.assertIn("[FB]", source)
        self.assertIn("Static Img Only", source)
        self.assertIn("Static Thumb Only", source)
        self.assertIn("have module images", source)
        self.assertIn("module-complete", source)

    def test_toolkit_template_uses_module_scoped_media_paths(self) -> None:
        source = Path("web/templates/module_toolkit.html").read_text(encoding="utf-8")

        self.assertIn("/api/toolkit/modules/${encodedModuleName}/media/${mediaFolder}/${encodedAssetId}", source)
        self.assertIn("const moduleSelect = document.getElementById('media-gen-module-select');", source)
        self.assertIn("source.src = `${basePath}_video.mp4${cacheBuster}`;", source)

    def test_toolkit_template_serializes_inline_media_handler_args(self) -> None:
        source = Path("web/templates/module_toolkit.html").read_text(encoding="utf-8")

        self.assertIn("const serializeForInlineArg = function(value)", source)
        self.assertIn(
            "viewAssetMedia(${assetIdArg}, ${assetTypeArg}, ${assetNameArg}, ${serializeForInlineArg(mediaType)})",
            source,
        )
        self.assertIn("toggleAssetSelection(", source)

    def test_toolkit_template_uses_safe_thumbnail_dom_id_helper(self) -> None:
        source = Path("web/templates/module_toolkit.html").read_text(encoding="utf-8")

        self.assertIn("function getAssetThumbElementId", source)
        self.assertIn("replace(/[^a-zA-Z0-9_-]/g, '_')", source)
        self.assertIn("getAssetThumbElementId", source)
        self.assertIn("document.getElementById(getAssetThumbElementId(", source)


    def test_readiness_adapter_function_exists_in_gate_module(self) -> None:
        source = Path("web/extensions/toolkit_homebrew_readiness_gate.py").read_text(encoding="utf-8")

        self.assertIn("def run_toolkit_builder_readiness_gate", source)
        self.assertIn("legacy_builder_narrative_v1", source)
        self.assertIn("ready_for_finishing", source)
        self.assertIn("source_workflow", source)

    def test_legacy_builder_readiness_cannot_be_bypassed_in_web_interface(self) -> None:
        source = Path("web/web_interface.py").read_text(encoding="utf-8")

        self.assertIn("run_toolkit_builder_readiness_gate", source)
        self.assertIn("ready_for_finishing", source)
        self.assertIn("readiness_failed", source)

    def test_homebrew_routes_recheck_fidelity_before_build(self) -> None:
        source = Path("web/routes/toolkit_homebrew_routes.py").read_text(encoding="utf-8")

        self.assertIn("fidelity_review_not_approvable", source)
        self.assertIn("_build_fidelity_review_or_error(workspace_path)", source)
        self.assertIn("can_approve", source)
        self.assertIn("can_start_build", source)

    def test_uploader_readiness_gate_function_signature_preserved(self) -> None:
        source = Path("web/extensions/toolkit_homebrew_readiness_gate.py").read_text(encoding="utf-8")

        self.assertIn("def run_toolkit_homebrew_readiness_gate", source)
        self.assertIn("workspace: Path", source)
        self.assertIn("job_id: str", source)

    def test_freshness_marker_function_exists(self) -> None:
        source = Path("web/extensions/toolkit_homebrew_readiness_gate.py").read_text(encoding="utf-8")

        self.assertIn("def _write_stale_report_marker", source)
        self.assertIn("pre_readiness", source)
        self.assertIn("post_readiness_failure", source)
        self.assertIn("freshness_state", source)
        self.assertIn("report_freshness", source)
        self.assertIn("toolkit_build_report_refresh_contract.v1", source)

    def test_readiness_report_artifact_function_exists(self) -> None:
        source = Path("web/extensions/toolkit_homebrew_readiness_gate.py").read_text(encoding="utf-8")

        self.assertIn("def _write_readiness_report_artifact", source)
        self.assertIn("toolkit_readiness_report.json", source)
        self.assertIn("convergence_outcome", source)

    def test_freshness_marker_invoked_before_readiness(self) -> None:
        source = Path("web/extensions/toolkit_homebrew_readiness_gate.py").read_text(encoding="utf-8")

        self.assertIn("_write_stale_report_marker", source)
        self.assertIn("marker_freshness=\"pre_readiness\"", source)
        self.assertIn("run_toolkit_homebrew_readiness_gate", source)

    def test_readiness_artifact_persisted_after_gate(self) -> None:
        source = Path("web/extensions/toolkit_homebrew_readiness_gate.py").read_text(encoding="utf-8")

        self.assertIn("_write_readiness_report_artifact", source)
        self.assertIn("ready_for_finishing", source)
        self.assertIn("validation", source)
        self.assertIn("readiness_audit", source)
        self.assertIn("repair_attempts", source)

    def test_readiness_adapter_exception_marker_exists(self) -> None:
        source = Path("web/extensions/toolkit_homebrew_readiness_gate.py").read_text(encoding="utf-8")

        self.assertIn("readiness_adapter_exception", source)
        self.assertIn("readiness_system_failure", source)

    def test_build_fidelity_workspace_paths_exist(self) -> None:
        source = Path("utils/toolkit_homebrew_upload_contract.py").read_text(encoding="utf-8")

        self.assertIn("build_fidelity_report.json", source)
        self.assertIn("source_fidelity_report.json", source)
        self.assertIn("persist_build_fidelity_report_artifact", source)
        self.assertIn("load_build_fidelity_report_artifact", source)
        self.assertIn("persist_source_fidelity_report_artifact", source)
        self.assertIn("load_source_fidelity_report_artifact", source)

    def test_build_fidelity_does_not_touch_builder_generator(self) -> None:
        source_py_files = [
            Path("utils/toolkit_build_fidelity.py"),
        ]
        for path in source_py_files:
            if path.exists():
                text = path.read_text(encoding="utf-8")
                self.assertNotIn("ModuleBuilder", text, f"{path} references ModuleBuilder")
                self.assertNotIn("ModuleGenerator", text, f"{path} references ModuleGenerator")

    def test_build_fidelity_flag_exists(self) -> None:
        source = Path("model_config.py").read_text(encoding="utf-8")

        self.assertIn("ENABLE_ACCURATE_INGEST_BUILD_FIDELITY_GATES", source)

    def test_fidelity_review_required_loading_bypasses_advanced_mode(self) -> None:
        source = Path("web/templates/module_toolkit.html").read_text(encoding="utf-8")

        self.assertIn("async function loadToolkitHomebrewReview(jobId, options)", source)
        self.assertIn("const required = Boolean(options && options.required);", source)
        self.assertIn("!HOME_BREW_ADVANCED_MODE && !required", source)
        self.assertIn("setHomebrewReviewPanelVisible(true, { required })", source)

    def test_fidelity_review_awaiting_polling_uses_required_mode(self) -> None:
        source = Path("web/templates/module_toolkit.html").read_text(encoding="utf-8")

        self.assertIn("job.status === 'awaiting_review'", source)
        self.assertIn("await loadToolkitHomebrewReview(jobId, { required: true });", source)
        self.assertNotIn("Legacy Homebrew job is awaiting review", source)
        self.assertIn("Homebrew job is awaiting source-fidelity review", source)

    def test_fidelity_review_required_action_fallback_exists(self) -> None:
        source = Path("web/templates/module_toolkit.html").read_text(encoding="utf-8")

        self.assertIn("function getToolkitFidelityApproveDisabledReason", source)
        self.assertIn("function renderToolkitHomebrewRequiredReviewActions", source)
        self.assertIn("renderToolkitHomebrewFidelityReview(review);", source)
        self.assertIn("renderToolkitHomebrewRequiredReviewActions(review);", source)

    def test_fidelity_review_fallback_cannot_be_blocked_by_reject_button(self) -> None:
        source = Path("web/templates/module_toolkit.html").read_text(encoding="utf-8")

        self.assertIn("const jobStatus = String(reviewPayload && reviewPayload.job_status || '').toLowerCase();", source)
        self.assertIn("const isRequiredState = jobStatus === 'awaiting_review' || jobStatus === 'approved_for_build';", source)
        self.assertIn("actionsEl.innerHTML.trim().length > 0 && !isRequiredState", source)

    def test_fidelity_review_disabled_approve_reason_checks(self) -> None:
        source = Path("web/templates/module_toolkit.html").read_text(encoding="utf-8")

        self.assertIn("review.refusal_reason", source)
        self.assertIn("blockers.length > 0", source)
        self.assertIn("blueprint.refusal_reason", source)
        self.assertIn("Blueprint is not ready", source)
        self.assertIn("Review is not currently approvable", source)

    def test_fidelity_review_backend_strict_approval_intact(self) -> None:
        source = Path("web/routes/toolkit_homebrew_routes.py").read_text(encoding="utf-8")

        self.assertIn("fidelity_review_state_missing", source)
        self.assertIn("fidelity_review_stale", source)
        self.assertIn("fidelity_review_not_approvable", source)
        self.assertIn("can_approve_fidelity_review(fidelity_review)", source)

    def test_fidelity_review_refresh_calls_preserve_required_visibility(self) -> None:
        source = Path("web/templates/module_toolkit.html").read_text(encoding="utf-8")

        self.assertIn("await loadToolkitHomebrewReview(activeJobId, { required: true });", source)
        self.assertIn("await loadToolkitHomebrewReview(homebrewActiveReviewJobId, { required: true });", source)

        self.assertGreaterEqual(
            source.count("await loadToolkitHomebrewReview(activeJobId, { required: true });"),
            6,
        )
        self.assertGreaterEqual(
            source.count("await loadToolkitHomebrewReview(homebrewActiveReviewJobId, { required: true });"),
            3,
        )

    def test_fidelity_review_optional_diagnostics_heading_exists(self) -> None:
        source = Path("web/templates/module_toolkit.html").read_text(encoding="utf-8")

        self.assertIn("homebrew-fidelity-review-heading", source)
        self.assertIn("Accurate Ingest Diagnostics", source)
        self.assertIn("'Accurate Ingest Diagnostics'", source)

    def test_fidelity_review_required_heading_still_exists(self) -> None:
        source = Path("web/templates/module_toolkit.html").read_text(encoding="utf-8")

        self.assertIn("Accurate Ingest Fidelity Review", source)

    def test_isToolkitFidelityReviewRequired_helper_exists(self) -> None:
        source = Path("web/templates/module_toolkit.html").read_text(encoding="utf-8")

        self.assertIn("function isToolkitFidelityReviewRequired", source)
        self.assertIn("return jobStatus === 'awaiting_review'", source)

    def test_fidelity_review_buttons_guarded_by_reviewRequired(self) -> None:
        source = Path("web/templates/module_toolkit.html").read_text(encoding="utf-8")

        self.assertIn("if (reviewRequired) {", source)
        self.assertIn("homebrew-fidelity-approve-btn", source)
        self.assertIn("homebrew-fidelity-reject-btn", source)

    def test_fidelity_review_optional_title_in_loadToolkitHomebrew(self) -> None:
        source = Path("web/templates/module_toolkit.html").read_text(encoding="utf-8")

        self.assertIn("Accurate Ingest Diagnostics [job: ${jobId}]", source)
        self.assertIn("fidelityReview.status", source)

    def test_fidelity_required_review_renders_disabled_approve_with_reason(self) -> None:
        source = Path("web/templates/module_toolkit.html").read_text(encoding="utf-8")

        self.assertIn("const reason = getToolkitFidelityApproveDisabledReason(reviewPayload);", source)
        self.assertIn("cursor:not-allowed", source)
        self.assertIn('disabled style="background-color:#444', source)

    def test_fidelity_required_review_always_shows_refresh_button(self) -> None:
        source = Path("web/templates/module_toolkit.html").read_text(encoding="utf-8")

        self.assertIn("homebrew-fidelity-refresh-btn", source)
        self.assertIn("Refresh Review", source)

    def test_fidelity_required_review_fallback_guard_preserved(self) -> None:
        source = Path("web/templates/module_toolkit.html").read_text(encoding="utf-8")

        self.assertIn("if (actionsEl.innerHTML.trim().length > 0 && !isRequiredState) return;", source)
        self.assertIn("const isRequiredState = jobStatus === 'awaiting_review' || jobStatus === 'approved_for_build';", source)

    def test_fidelity_required_review_validate_reject_disabled_refresh_present(self) -> None:
        source = Path("web/templates/module_toolkit.html").read_text(encoding="utf-8")

        self.assertIn("if (jobStatus === 'awaiting_review')", source)
        self.assertIn("getToolkitFidelityApproveDisabledReason", source)
        self.assertIn('id="homebrew-fidelity-reject-btn"', source)
        self.assertIn('id="homebrew-fidelity-refresh-btn"', source)
        self.assertIn("submitToolkitHomebrewReviewDecision(homebrewActiveReviewJobId, 'reject')", source)

    def test_default_packet_builder_path_not_seed_writer(self) -> None:
        source = Path("web/extensions/toolkit_homebrew_packet_builder.py").read_text(encoding="utf-8")

        self.assertIn("_use_seed_writer = False", source)
        self.assertIn("elif handoff_class in (\"source_blueprint_v2_ready\", \"source_blueprint_v2_degraded\"):", source)
        self.assertIn('_build_mode = "source_enhanced_modulebuilder"', source)
        self.assertIn("_execute_seed_writer_build", source)


class TestReportAgreementComposer(unittest.TestCase):
    """Provider-free tests for report-agreement contradiction detection."""

    def test_all_pass_produces_playable_pass(self):
        from utils.toolkit_report_agreement import compose_report_agreement

        result = compose_report_agreement(
            source_fidelity_status="pass",
            validation_status="pass",
            ready_status="pass",
            publishable_status="pass",
            effective_publishable_status="pass",
        )
        self.assertEqual(result.get("status"), "pass")
        self.assertEqual(result.get("playable_publication_status"), "pass")
        self.assertTrue(result.get("internal_coherent"))

    def test_source_fidelity_pass_validation_fail_blocks_playable(self):
        from utils.toolkit_report_agreement import compose_report_agreement

        result = compose_report_agreement(
            source_fidelity_status="pass",
            validation_status="fail",
            ready_status="pass",
            publishable_status="pass",
            effective_publishable_status="pass",
        )
        self.assertEqual(result.get("status"), "blocked")
        self.assertEqual(result.get("playable_publication_status"), "blocked")
        self.assertFalse(result.get("internal_coherent"))
        blockers = result.get("blockers", [])
        self.assertTrue(
            any("source_fidelity_pass_validation_fail" in b for b in blockers),
            "Expected contradiction block not found in " + str(blockers),
        )

    def test_validation_pass_publishability_fail_blocks_playable(self):
        from utils.toolkit_report_agreement import compose_report_agreement

        result = compose_report_agreement(
            source_fidelity_status="pass",
            validation_status="pass",
            ready_status="pass",
            publishable_status="fail",
            effective_publishable_status="fail",
        )
        self.assertEqual(result.get("status"), "blocked")
        self.assertEqual(result.get("playable_publication_status"), "blocked")
        self.assertFalse(result.get("internal_coherent"))
        blockers = result.get("blockers", [])
        self.assertTrue(
            any("validation_pass_publishability_fail" in b for b in blockers),
            "Expected validation/publishability contradiction not found in " + str(blockers),
        )

    def test_toolkit_failed_effective_pass_blocks_playable(self):
        from utils.toolkit_report_agreement import compose_report_agreement

        result = compose_report_agreement(
            source_fidelity_status="pass",
            validation_status="pass",
            ready_status="pass",
            publishable_status="pass",
            effective_publishable_status="pass",
            toolkit_top_level_status="failed",
        )
        self.assertEqual(result.get("status"), "blocked")
        self.assertFalse(result.get("internal_coherent"))
        blockers = result.get("blockers", [])
        self.assertTrue(
            any("toolkit_failed_effective_pass" in b for b in blockers),
            "Expected toolkit_failed_effective_pass block not found in " + str(blockers),
        )
        self.assertTrue(
            any("toolkit_failed_publishable_pass" in b for b in blockers),
            "Expected toolkit_failed_publishable_pass block not found in " + str(blockers),
        )

    def test_toolkit_pass_nested_publishability_fail_blocks(self):
        from utils.toolkit_report_agreement import compose_report_agreement

        result = compose_report_agreement(
            source_fidelity_status="pass",
            validation_status="pass",
            ready_status="pass",
            publishable_status="fail",
            effective_publishable_status="fail",
            toolkit_top_level_status="pass",
            toolkit_publishability_stage_status="blocked",
        )
        self.assertEqual(result.get("status"), "blocked")
        self.assertFalse(result.get("internal_coherent"))
        blockers = result.get("blockers", [])
        self.assertTrue(
            any("toolkit_pass_nested_publishability_fail" in b for b in blockers),
            "Expected nested publishability contradiction not found in " + str(blockers),
        )

    def test_missing_reports_produces_blocked_or_stale(self):
        from utils.toolkit_report_agreement import compose_report_agreement

        result = compose_report_agreement(
            source_fidelity_status="unknown",
            validation_status="unknown",
            ready_status="unknown",
            publishable_status="unknown",
            missing_reports=["validation", "source_fidelity"],
        )
        self.assertIn(result.get("status"), {"blocked", "stale"})
        self.assertNotEqual(result.get("playable_publication_status"), "pass")

    def test_stale_freshness_produces_blocked(self):
        from utils.toolkit_report_agreement import compose_report_agreement

        result = compose_report_agreement(
            source_fidelity_status="pass",
            validation_status="pass",
            ready_status="pass",
            publishable_status="pass",
            effective_publishable_status="pass",
            report_freshness_states={
                "validation": "stale",
                "source_fidelity": "current",
            },
        )
        self.assertEqual(result.get("status"), "blocked")
        self.assertEqual(result.get("playable_publication_status"), "blocked")
        self.assertIn("validation", result.get("stale_reports", []))

    def test_effective_pass_publishability_fail_blocks(self):
        from utils.toolkit_report_agreement import compose_report_agreement

        result = compose_report_agreement(
            source_fidelity_status="pass",
            validation_status="pass",
            ready_status="pass",
            publishable_status="fail",
            effective_publishable_status="pass",
        )
        self.assertEqual(result.get("status"), "blocked")
        self.assertFalse(result.get("internal_coherent"))
        blockers = result.get("blockers", [])
        self.assertTrue(
            any("effective_pass_publishability_fail" in b for b in blockers),
            "Expected effective/publishability contradiction not found in " + str(blockers),
        )

    def test_playable_separates_source_fidelity_from_playable(self):
        from utils.toolkit_report_agreement import compose_report_agreement

        result = compose_report_agreement(
            source_fidelity_status="degraded",
            validation_status="pass",
            ready_status="pass",
            publishable_status="pass",
            effective_publishable_status="pass",
        )
        self.assertNotEqual(
            result.get("source_fidelity_status"),
            result.get("playable_publication_status"),
            "source_fidelity_status must differ from playable_publication_status when degraded",
        )
        self.assertEqual(result.get("playable_publication_status"), "blocked")

    def test_finisher_includes_report_agreement_stage(self):
        import os, tempfile
        from pathlib import Path

        import web.extensions.toolkit_module_finisher as finisher

        self.orig_continuity = finisher._run_continuity_stage
        self.orig_registry = finisher._run_registry_stage
        self.orig_materialization = finisher._run_monster_materialization_stage
        self.orig_publishability = finisher._run_publishability_stage

        temp_dir = tempfile.TemporaryDirectory()
        old_cwd = Path.cwd()
        try:
            repo_root = Path(temp_dir.name)
            os.chdir(repo_root)
            module_dir = repo_root / "modules" / "RATestModule"
            module_dir.mkdir(parents=True, exist_ok=True)
            (module_dir / "module_context.json").write_text("{}", encoding="utf-8")
            (module_dir / "module_plot.json").write_text("{}", encoding="utf-8")
            (module_dir / "validation_report.json").write_text(
                json.dumps({"summary": {"total_failed": 0}}), encoding="utf-8"
            )

            finisher._run_continuity_stage = lambda *a, **kw: {"status": "success"}
            finisher._run_registry_stage = lambda *a, **kw: {"status": "success"}
            finisher._run_monster_materialization_stage = lambda *a, **kw: {"status": "success"}
            finisher._run_publishability_stage = lambda *a, **kw: {
                "status": "success",
                "ready_status": "pass",
                "publishable_status": "pass",
                "report": {
                    "source_fidelity_status": "pass",
                    "source_fidelity_categories": [],
                    "ready_status": "pass",
                    "publishable_status": "pass",
                    "effective_publishable_status": "pass",
                },
            }

            result = finisher.run_toolkit_module_postbuild_finishing(
                "RATestModule", strict=True
            )

            stages = result.get("stages", {})
            self.assertIn("report_agreement", stages,
                          "Finisher must include report_agreement stage")
            self.assertIn("playable_publication_status", result,
                          "Finisher report must include playable_publication_status")
            self.assertIn("report_agreement_status", result,
                          "Finisher report must include report_agreement_status")
            self.assertIn("report_agreement_internal_coherent", result,
                          "Finisher report must include report_agreement_internal_coherent")

            ra_stage = stages["report_agreement"]
            self.assertIn("blockers", ra_stage)
            self.assertIn("diagnostics", ra_stage)
        finally:
            finisher._run_continuity_stage = self.orig_continuity
            finisher._run_registry_stage = self.orig_registry
            finisher._run_monster_materialization_stage = self.orig_materialization
            finisher._run_publishability_stage = self.orig_publishability
            os.chdir(old_cwd)
            temp_dir.cleanup()

    def test_toolkit_template_has_report_agreement_formatting(self):
        source = Path("web/templates/module_toolkit.html").read_text(encoding="utf-8")
        self.assertIn("formatReportAgreementSection", source)
        self.assertIn("Playable Publication", source)
        self.assertIn("Report Agreement:", source)
        self.assertIn("Internal Coherent", source)

    def test_toolkit_degraded_with_all_gates_pass_remains_playable(self):
        from utils.toolkit_report_agreement import compose_report_agreement

        result = compose_report_agreement(
            source_fidelity_status="pass",
            validation_status="pass",
            ready_status="pass",
            publishable_status="pass",
            effective_publishable_status="pass",
            toolkit_top_level_status="degraded",
        )

        self.assertEqual(result.get("status"), "pass")
        self.assertTrue(result.get("internal_coherent"))
        self.assertEqual(result.get("playable_publication_status"), "pass")
        self.assertEqual(result.get("blockers"), [])
        self.assertEqual(result.get("stale_reports"), [])
        self.assertEqual(result.get("missing_reports"), [])

    # ---- compose_report_agreement_from_module_dir tests ----

    def test_disk_composer_all_pass_reports_yields_playable_pass(self):
        import os, tempfile
        from pathlib import Path

        from utils.toolkit_report_agreement import compose_report_agreement_from_module_dir

        temp_dir = tempfile.TemporaryDirectory()
        old_cwd = Path.cwd()
        try:
            repo_root = Path(temp_dir.name)
            os.chdir(repo_root)
            module_dir = repo_root / "modules" / "DiskTestAllPass"
            module_dir.mkdir(parents=True, exist_ok=True)
            (module_dir / "validation_report.json").write_text(
                json.dumps({"summary": {"total_failed": 0}}), encoding="utf-8"
            )
            (module_dir / "source_fidelity_report.json").write_text(
                json.dumps({"source_fidelity_status": "pass"}), encoding="utf-8"
            )
            (module_dir / "toolkit_build_report.json").write_text(
                json.dumps({
                    "status": "complete",
                    "ready_status": "pass",
                    "publishable_status": "pass",
                    "effective_publishable_status": "pass",
                }),
                encoding="utf-8",
            )

            res = compose_report_agreement_from_module_dir(module_dir)
            self.assertEqual(res["status"], "pass")
            self.assertEqual(res["playable_publication_status"], "pass")
            self.assertTrue(res["internal_coherent"])
            self.assertEqual(res["stale_reports"], [])
            self.assertEqual(res["missing_reports"], [])
        finally:
            os.chdir(old_cwd)
            temp_dir.cleanup()

    def test_disk_composer_validation_fail_blocks_playable(self):
        import os, tempfile
        from pathlib import Path

        from utils.toolkit_report_agreement import compose_report_agreement_from_module_dir

        temp_dir = tempfile.TemporaryDirectory()
        old_cwd = Path.cwd()
        try:
            repo_root = Path(temp_dir.name)
            os.chdir(repo_root)
            module_dir = repo_root / "modules" / "DiskTestValFail"
            module_dir.mkdir(parents=True, exist_ok=True)
            (module_dir / "validation_report.json").write_text(
                json.dumps({"summary": {"total_failed": 3}}), encoding="utf-8"
            )
            (module_dir / "source_fidelity_report.json").write_text(
                json.dumps({"source_fidelity_status": "pass"}), encoding="utf-8"
            )
            (module_dir / "toolkit_build_report.json").write_text(
                json.dumps({
                    "status": "complete",
                    "ready_status": "pass",
                    "publishable_status": "pass",
                    "effective_publishable_status": "pass",
                }),
                encoding="utf-8",
            )

            res = compose_report_agreement_from_module_dir(module_dir)
            self.assertNotEqual(res["playable_publication_status"], "pass")
        finally:
            os.chdir(old_cwd)
            temp_dir.cleanup()

    def test_disk_composer_legacy_no_freshness_not_stale(self):
        import os, tempfile
        from pathlib import Path

        from utils.toolkit_report_agreement import compose_report_agreement_from_module_dir

        temp_dir = tempfile.TemporaryDirectory()
        old_cwd = Path.cwd()
        try:
            repo_root = Path(temp_dir.name)
            os.chdir(repo_root)
            module_dir = repo_root / "modules" / "DiskTestNoFresh"
            module_dir.mkdir(parents=True, exist_ok=True)
            # Reports without freshness metadata but with valid status
            (module_dir / "validation_report.json").write_text(
                json.dumps({"summary": {"total_failed": 0}, "timestamp": "2024-01-01"}),
                encoding="utf-8",
            )
            (module_dir / "source_fidelity_report.json").write_text(
                json.dumps({"source_fidelity_status": "pass"}),
                encoding="utf-8",
            )
            (module_dir / "toolkit_build_report.json").write_text(
                json.dumps({
                    "status": "complete",
                    "ready_status": "pass",
                    "publishable_status": "pass",
                    "effective_publishable_status": "pass",
                }),
                encoding="utf-8",
            )

            res = compose_report_agreement_from_module_dir(module_dir)
            self.assertEqual(res["stale_reports"], [],
                             f"Legacy reports without freshness metadata must not be stale: {res['stale_reports']}")
        finally:
            os.chdir(old_cwd)
            temp_dir.cleanup()

    def test_disk_composer_explicit_stale_still_blocks(self):
        import os, tempfile
        from pathlib import Path

        from utils.toolkit_report_agreement import compose_report_agreement_from_module_dir

        temp_dir = tempfile.TemporaryDirectory()
        old_cwd = Path.cwd()
        try:
            repo_root = Path(temp_dir.name)
            os.chdir(repo_root)
            module_dir = repo_root / "modules" / "DiskTestStale"
            module_dir.mkdir(parents=True, exist_ok=True)
            (module_dir / "validation_report.json").write_text(
                json.dumps({
                    "summary": {"total_failed": 0},
                    "freshness_state": "stale",
                }),
                encoding="utf-8",
            )
            (module_dir / "source_fidelity_report.json").write_text(
                json.dumps({"source_fidelity_status": "pass"}), encoding="utf-8"
            )
            (module_dir / "toolkit_build_report.json").write_text(
                json.dumps({
                    "status": "complete",
                    "ready_status": "pass",
                    "publishable_status": "pass",
                    "effective_publishable_status": "pass",
                }),
                encoding="utf-8",
            )

            res = compose_report_agreement_from_module_dir(module_dir)
            self.assertNotEqual(res["status"], "pass",
                                f"Explicit stale freshness must block: {res}")
            self.assertGreater(len(res["stale_reports"]), 0,
                               "Stale reports must be listed")
        finally:
            os.chdir(old_cwd)
            temp_dir.cleanup()

    def test_disk_composer_missing_required_report_blocks(self):
        import os, tempfile
        from pathlib import Path

        from utils.toolkit_report_agreement import compose_report_agreement_from_module_dir

        temp_dir = tempfile.TemporaryDirectory()
        old_cwd = Path.cwd()
        try:
            repo_root = Path(temp_dir.name)
            os.chdir(repo_root)
            module_dir = repo_root / "modules" / "DiskTestMissing"
            module_dir.mkdir(parents=True, exist_ok=True)
            # No validation_report.json -- missing required report
            (module_dir / "source_fidelity_report.json").write_text(
                json.dumps({"source_fidelity_status": "pass"}), encoding="utf-8"
            )
            (module_dir / "toolkit_build_report.json").write_text(
                json.dumps({
                    "status": "complete",
                    "ready_status": "pass",
                    "publishable_status": "pass",
                    "effective_publishable_status": "pass",
                }),
                encoding="utf-8",
            )

            res = compose_report_agreement_from_module_dir(module_dir)
            self.assertGreater(len(res["missing_reports"]), 0,
                               "Missing required reports must be listed")
            self.assertNotEqual(res["playable_publication_status"], "pass",
                                "Missing reports must block playable status")
        finally:
            os.chdir(old_cwd)
            temp_dir.cleanup()

    # ---- Context BU parity test ----

    def test_finisher_llm_classification_syncs_context_backup(self):
        """After classification_metadata is written to module_context.json,
        module_context_BU.json must be synced to the same payload."""
        import os, tempfile
        from pathlib import Path

        import web.extensions.toolkit_module_finisher as finisher

        self.orig_continuity = finisher._run_continuity_stage
        self.orig_registry = finisher._run_registry_stage
        self.orig_materialization = finisher._run_monster_materialization_stage
        self.orig_publishability = finisher._run_publishability_stage

        temp_dir = tempfile.TemporaryDirectory()
        old_cwd = Path.cwd()
        try:
            repo_root = Path(temp_dir.name)
            os.chdir(repo_root)
            module_dir = repo_root / "modules" / "ParityContextTest"
            module_dir.mkdir(parents=True, exist_ok=True)

            # Pre-populate both files with identical baseline
            base_context = {"npcs": {"test_npc": {"name": "Test"}}, "module_slug": "ParityContextTest"}
            (module_dir / "module_context.json").write_text(
                json.dumps(base_context), encoding="utf-8"
            )
            (module_dir / "module_context_BU.json").write_text(
                json.dumps(base_context), encoding="utf-8"
            )
            (module_dir / "module_plot.json").write_text("{}", encoding="utf-8")
            (module_dir / "validation_report.json").write_text(
                json.dumps({"summary": {"total_failed": 0}}), encoding="utf-8"
            )

            # Run the finisher, which will call _run_llm_classification_stage
            # (llm classification is disabled by default in test environment
            #  so it'll be skipped, but the BU sync helper is always tested)
            finisher._run_continuity_stage = lambda *a, **kw: {"status": "success"}
            finisher._run_registry_stage = lambda *a, **kw: {"status": "success"}
            finisher._run_monster_materialization_stage = lambda *a, **kw: {"status": "success"}
            finisher._run_publishability_stage = lambda *a, **kw: {
                "status": "success",
                "ready_status": "pass",
                "publishable_status": "pass",
                "report": {
                    "source_fidelity_status": "pass",
                    "source_fidelity_categories": [],
                    "ready_status": "pass",
                    "publishable_status": "pass",
                    "effective_publishable_status": "pass",
                },
            }

            result = finisher.run_toolkit_module_postbuild_finishing(
                "ParityContextTest", strict=True
            )

            # After finisher, context and BU must be identical
            live = json.loads((module_dir / "module_context.json").read_text(encoding="utf-8"))
            backup = json.loads((module_dir / "module_context_BU.json").read_text(encoding="utf-8"))
            self.assertEqual(live, backup,
                             "module_context.json and module_context_BU.json must have exact parity")

            # If classification_metadata existed in live, it must exist in backup too
            if "classification_metadata" in live:
                self.assertIn("classification_metadata", backup,
                              "classification_metadata must appear in BU backup")
                self.assertEqual(
                    live["classification_metadata"],
                    backup["classification_metadata"],
                    "classification_metadata must be identical in both files",
                )
        finally:
            finisher._run_continuity_stage = self.orig_continuity
            finisher._run_registry_stage = self.orig_registry
            finisher._run_monster_materialization_stage = self.orig_materialization
            finisher._run_publishability_stage = self.orig_publishability
            os.chdir(old_cwd)
            temp_dir.cleanup()

    # ---- Edge-case hardening tests ----

    def test_finisher_blocks_playable_when_source_fidelity_report_not_persisted(self):
        """If source_fidelity_report.json cannot be written to disk,
        playable_publication_status must be blocked."""
        import os, tempfile
        from pathlib import Path

        import web.extensions.toolkit_module_finisher as finisher

        self.orig_continuity = finisher._run_continuity_stage
        self.orig_registry = finisher._run_registry_stage
        self.orig_materialization = finisher._run_monster_materialization_stage
        self.orig_publishability = finisher._run_publishability_stage
        self.orig_semantic_auth = finisher._run_semantic_authority_stage

        temp_dir = tempfile.TemporaryDirectory()
        old_cwd = Path.cwd()
        try:
            repo_root = Path(temp_dir.name)
            os.chdir(repo_root)
            module_dir = repo_root / "modules" / "SFBlockTest"
            module_dir.mkdir(parents=True, exist_ok=True)
            (module_dir / "module_context.json").write_text("{}", encoding="utf-8")
            (module_dir / "module_context_BU.json").write_text("{}", encoding="utf-8")
            (module_dir / "module_plot.json").write_text("{}", encoding="utf-8")
            (module_dir / "module_plot_BU.json").write_text("{}", encoding="utf-8")
            (module_dir / "validation_report.json").write_text(
                json.dumps({"summary": {"total_failed": 0}}), encoding="utf-8"
            )

            finisher._run_continuity_stage = lambda *a, **kw: {"status": "success"}
            finisher._run_registry_stage = lambda *a, **kw: {"status": "success"}
            finisher._run_semantic_authority_stage = lambda *a, **kw: {
                "status": "success",
                "changed": False,
                "semantic_authority": {},
                "warnings": [],
                "errors": [],
            }
            finisher._run_monster_materialization_stage = lambda *a, **kw: {"status": "success"}
            finisher._run_publishability_stage = lambda *a, **kw: {
                "status": "success",
                "ready_status": "pass",
                "publishable_status": "pass",
                "report": {
                    "source_fidelity_status": "pass",
                    "source_fidelity_categories": [],
                    "ready_status": "pass",
                    "publishable_status": "pass",
                    "effective_publishable_status": "pass",
                },
            }

            # Patch safe_write_json to return False ONLY for source_fidelity_report.json
            original_safe_write = finisher.safe_write_json
            def _fail_sf_report(path, data, **kw):
                if "source_fidelity_report.json" in str(path):
                    return False
                return original_safe_write(path, data, **kw)

            with patch.object(finisher, "safe_write_json", _fail_sf_report):
                result = finisher.run_toolkit_module_postbuild_finishing(
                    "SFBlockTest", strict=True
                )

            self.assertNotEqual(
                result.get("playable_publication_status"), "pass",
                "Must block playable when source_fidelity_report not persisted",
            )
            self.assertIn(
                result.get("report_agreement_status"), {"blocked", "stale", "failed"},
                "Report agreement must be blocked/stale/failed when SF report fails",
            )
            ra = result.get("report_agreement", {})
            self.assertIn(
                "source_fidelity", ra.get("missing_reports", []),
                "source_fidelity must appear in missing_reports when persistence fails",
            )
        finally:
            finisher._run_continuity_stage = self.orig_continuity
            finisher._run_registry_stage = self.orig_registry
            finisher._run_monster_materialization_stage = self.orig_materialization
            finisher._run_publishability_stage = self.orig_publishability
            finisher._run_semantic_authority_stage = self.orig_semantic_auth
            os.chdir(old_cwd)
            temp_dir.cleanup()

    def test_finisher_blocks_playable_when_context_backup_mismatches(self):
        """If module_context.json and module_context_BU.json differ,
        playable_publication_status must be blocked.

        The LLM classification stage auto-heals BU sync during normal operation.
        This test disables classification sync and semantic authority to prove
        the parity gate catches unaided mismatch.
        """
        import os, tempfile
        from pathlib import Path

        import web.extensions.toolkit_module_finisher as finisher

        self.orig_continuity = finisher._run_continuity_stage
        self.orig_registry = finisher._run_registry_stage
        self.orig_materialization = finisher._run_monster_materialization_stage
        self.orig_publishability = finisher._run_publishability_stage
        self.orig_semantic_auth = finisher._run_semantic_authority_stage
        self.orig_pub_finalizer = finisher._run_publishability_finalizer_stage

        temp_dir = tempfile.TemporaryDirectory()
        old_cwd = Path.cwd()
        try:
            repo_root = Path(temp_dir.name)
            os.chdir(repo_root)
            module_dir = repo_root / "modules" / "CtxMismatchTest"
            module_dir.mkdir(parents=True, exist_ok=True)
            # Deliberately different payloads
            (module_dir / "module_context.json").write_text(
                json.dumps({"npcs": {"a": 1}}), encoding="utf-8"
            )
            (module_dir / "module_context_BU.json").write_text(
                json.dumps({"npcs": {"b": 2}}), encoding="utf-8"
            )
            (module_dir / "module_plot.json").write_text("{}", encoding="utf-8")
            (module_dir / "module_plot_BU.json").write_text("{}", encoding="utf-8")
            (module_dir / "validation_report.json").write_text(
                json.dumps({"summary": {"total_failed": 0}}), encoding="utf-8"
            )

            # Disable LLM classification to prevent auto-healing BU sync
            # and mock semantic authority to no-op.
            import model_config
            orig_classification_flag = model_config.ENABLE_LLM_CLASSIFICATION
            model_config.ENABLE_LLM_CLASSIFICATION = False

            finisher._run_continuity_stage = lambda *a, **kw: {"status": "success"}
            finisher._run_registry_stage = lambda *a, **kw: {"status": "success"}
            finisher._run_semantic_authority_stage = lambda *a, **kw: {
                "status": "success",
                "changed": False,
                "semantic_authority": {},
                "warnings": [],
                "errors": [],
            }
            finisher._run_monster_materialization_stage = lambda *a, **kw: {"status": "success"}
            finisher._run_publishability_finalizer_stage = lambda *a, **kw: {"status": "success", "changed": False, "errors": [], "warnings": []}
            finisher._run_publishability_stage = lambda *a, **kw: {
                "status": "success",
                "ready_status": "pass",
                "publishable_status": "pass",
                "report": {
                    "source_fidelity_status": "pass",
                    "source_fidelity_categories": [],
                    "ready_status": "pass",
                    "publishable_status": "pass",
                    "effective_publishable_status": "pass",
                },
            }

            result = finisher.run_toolkit_module_postbuild_finishing(
                "CtxMismatchTest", strict=True
            )

            self.assertEqual(
                result.get("stages", {}).get("context_backup_parity", {}).get("status"),
                "failed",
                "Context backup parity must detect mismatch",
            )
            self.assertNotEqual(
                result.get("playable_publication_status"), "pass",
                "Must block playable when context backup mismatch",
            )
            self.assertEqual(
                result.get("report_agreement_status"), "blocked",
                "Report agreement must be blocked when pipeline fails",
            )
        finally:
            model_config.ENABLE_LLM_CLASSIFICATION = orig_classification_flag
            finisher._run_continuity_stage = self.orig_continuity
            finisher._run_registry_stage = self.orig_registry
            finisher._run_monster_materialization_stage = self.orig_materialization
            finisher._run_publishability_stage = self.orig_publishability
            finisher._run_semantic_authority_stage = self.orig_semantic_auth
            finisher._run_publishability_finalizer_stage = self.orig_pub_finalizer
            os.chdir(old_cwd)
            temp_dir.cleanup()

    def test_context_backup_sync_helper_copies_classification_metadata(self):
        """_sync_context_backup must copy classification_metadata to BU."""
        import os, tempfile
        from pathlib import Path

        from web.extensions.toolkit_module_finisher import _sync_context_backup

        temp_dir = tempfile.TemporaryDirectory()
        old_cwd = Path.cwd()
        try:
            repo_root = Path(temp_dir.name)
            os.chdir(repo_root)
            module_dir = repo_root / "modules" / "SyncTest"
            module_dir.mkdir(parents=True, exist_ok=True)

            live_payload = {
                "npcs": {"foo": "bar"},
                "classification_metadata": {
                    "classified_by": "test-model",
                    "classified_at": "2026-06-01T00:00:00Z",
                    "entity_count": 5,
                    "destination_count": 3,
                },
            }
            bu_payload = {"npcs": {"foo": "bar"}}

            (module_dir / "module_context.json").write_text(
                json.dumps(live_payload), encoding="utf-8"
            )
            (module_dir / "module_context_BU.json").write_text(
                json.dumps(bu_payload), encoding="utf-8"
            )

            ok = _sync_context_backup(module_dir, "SyncTest")
            self.assertTrue(ok, "sync must succeed")

            live = json.loads((module_dir / "module_context.json").read_text(encoding="utf-8"))
            backup = json.loads((module_dir / "module_context_BU.json").read_text(encoding="utf-8"))
            self.assertEqual(live, backup, "Exact JSON equality required after sync")
            self.assertIn("classification_metadata", backup,
                          "classification_metadata must be copied to BU")
            self.assertEqual(
                live["classification_metadata"],
                backup["classification_metadata"],
                "classification_metadata must be identical in both files",
            )
        finally:
            os.chdir(old_cwd)
            temp_dir.cleanup()

    def test_finisher_blocks_playable_when_source_fidelity_report_write_fails_even_if_old_report_exists(self):
        """Stale source_fidelity_report.json from prior run must not mask
        a failed current-run write. Playable must be blocked."""
        import os, tempfile
        from pathlib import Path

        import web.extensions.toolkit_module_finisher as finisher

        self.orig_continuity = finisher._run_continuity_stage
        self.orig_registry = finisher._run_registry_stage
        self.orig_materialization = finisher._run_monster_materialization_stage
        self.orig_publishability = finisher._run_publishability_stage
        self.orig_semantic_auth = finisher._run_semantic_authority_stage

        temp_dir = tempfile.TemporaryDirectory()
        old_cwd = Path.cwd()
        try:
            repo_root = Path(temp_dir.name)
            os.chdir(repo_root)
            module_dir = repo_root / "modules" / "SFStaleTest"
            module_dir.mkdir(parents=True, exist_ok=True)
            (module_dir / "module_context.json").write_text("{}", encoding="utf-8")
            (module_dir / "module_context_BU.json").write_text("{}", encoding="utf-8")
            (module_dir / "module_plot.json").write_text("{}", encoding="utf-8")
            (module_dir / "module_plot_BU.json").write_text("{}", encoding="utf-8")
            (module_dir / "validation_report.json").write_text(
                json.dumps({"summary": {"total_failed": 0}}), encoding="utf-8"
            )
            # Stale SF report from a prior run
            (module_dir / "source_fidelity_report.json").write_text(
                json.dumps({"source_fidelity_status": "pass"}), encoding="utf-8"
            )

            import model_config
            orig_class_flag = model_config.ENABLE_LLM_CLASSIFICATION
            model_config.ENABLE_LLM_CLASSIFICATION = False

            finisher._run_continuity_stage = lambda *a, **kw: {"status": "success"}
            finisher._run_registry_stage = lambda *a, **kw: {"status": "success"}
            finisher._run_semantic_authority_stage = lambda *a, **kw: {
                "status": "success", "changed": False,
                "semantic_authority": {}, "warnings": [], "errors": [],
            }
            finisher._run_monster_materialization_stage = lambda *a, **kw: {"status": "success"}
            finisher._run_publishability_stage = lambda *a, **kw: {
                "status": "success", "ready_status": "pass", "publishable_status": "pass",
                "report": {
                    "source_fidelity_status": "pass", "source_fidelity_categories": [],
                    "ready_status": "pass", "publishable_status": "pass",
                    "effective_publishable_status": "pass",
                },
            }

            # Patch safe_write_json to return False for SF report only
            original_safe_write = finisher.safe_write_json
            def _fail_sf_report(path, data, **kw):
                if "source_fidelity_report.json" in str(path):
                    return False
                return original_safe_write(path, data, **kw)

            with patch.object(finisher, "safe_write_json", _fail_sf_report):
                result = finisher.run_toolkit_module_postbuild_finishing(
                    "SFStaleTest", strict=True
                )

            self.assertNotEqual(
                result.get("playable_publication_status"), "pass",
                "Must block playable when current SF report write fails",
            )
            self.assertIn(
                result.get("report_agreement_status"), {"blocked", "stale", "failed"},
                "Report agreement must be blocked when SF report write fails",
            )
            ra = result.get("report_agreement", {})
            self.assertIn(
                "source_fidelity", ra.get("missing_reports", []),
                "source_fidelity must appear in missing_reports",
            )
        finally:
            model_config.ENABLE_LLM_CLASSIFICATION = orig_class_flag
            finisher._run_continuity_stage = self.orig_continuity
            finisher._run_registry_stage = self.orig_registry
            finisher._run_monster_materialization_stage = self.orig_materialization
            finisher._run_publishability_stage = self.orig_publishability
            finisher._run_semantic_authority_stage = self.orig_semantic_auth
            os.chdir(old_cwd)
            temp_dir.cleanup()


class TestSourceFidelityReportPersistence(unittest.TestCase):
    """Behavioral tests for source_fidelity_report.json mirroring in finisher build report."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self.temp_dir.name)
        self.original_cwd = Path.cwd()
        os.chdir(self.repo_root)

        self.module_slug = "Source_Fidelity_Test"
        self.module_dir = self.repo_root / "modules" / self.module_slug
        self.module_dir.mkdir(parents=True, exist_ok=True)
        (self.module_dir / "module_context.json").write_text("{}", encoding="utf-8")
        (self.module_dir / "module_context_BU.json").write_text("{}", encoding="utf-8")
        (self.module_dir / "module_plot.json").write_text("{}", encoding="utf-8")
        (self.module_dir / "module_plot_BU.json").write_text("{}", encoding="utf-8")
        (self.module_dir / "validation_report.json").write_text(
            json.dumps({"summary": {"total_failed": 0}}), encoding="utf-8"
        )
        (self.module_dir / "source_fidelity_report.json").write_text(
            json.dumps({"source_fidelity_status": "pass"}), encoding="utf-8"
        )

        # Stub safe_write_json and _build_source_fidelity_report_artifact
        self._orig_safe_write = finisher.safe_write_json
        def _force_success_safe_write(path, data, **kw):
            self._orig_safe_write(path, data, **kw)
            return True
        finisher.safe_write_json = _force_success_safe_write

        self._orig_sf_artifact_builder = None
        try:
            import scripts.audit_module_publishability as sap
            self._orig_sf_artifact_builder = sap._build_source_fidelity_report_artifact
            sap._build_source_fidelity_report_artifact = (
                lambda module_slug, module_path, publishability_report: {
                    "source_fidelity_status": "pass",
                    "module": module_slug,
                }
            )
        except Exception:
            pass

        # Save originals
        self.orig_continuity = finisher._run_continuity_stage
        self.orig_registry = finisher._run_registry_stage
        self.orig_materialization = finisher._run_monster_materialization_stage
        self.orig_publishability = finisher._run_publishability_stage
        self.orig_pub_finalizer = finisher._run_publishability_finalizer_stage
        self.orig_semantic_auth = finisher._run_semantic_authority_stage

        # Stub non-publishability stages to succeed so only the
        # publishability report content drives the result.
        finisher._run_continuity_stage = lambda *a, **kw: {"status": "success"}
        finisher._run_registry_stage = lambda *a, **kw: {"status": "success"}
        finisher._run_monster_materialization_stage = lambda *a, **kw: {"status": "success"}
        finisher._run_publishability_finalizer_stage = lambda *a, **kw: {"status": "success", "changed": False}
        finisher._run_semantic_authority_stage = lambda *a, **kw: {"status": "success", "changed": False}

    def tearDown(self):
        finisher._run_continuity_stage = self.orig_continuity
        finisher._run_registry_stage = self.orig_registry
        finisher._run_monster_materialization_stage = self.orig_materialization
        finisher._run_publishability_stage = self.orig_publishability
        finisher._run_publishability_finalizer_stage = self.orig_pub_finalizer
        finisher._run_semantic_authority_stage = self.orig_semantic_auth
        finisher.safe_write_json = self._orig_safe_write

        if self._orig_sf_artifact_builder:
            try:
                import scripts.audit_module_publishability as sap
                sap._build_source_fidelity_report_artifact = self._orig_sf_artifact_builder
            except Exception:
                pass

        os.chdir(self.original_cwd)
        self.temp_dir.cleanup()

    def _stub_publishability(self, status: str, categories: list):
        """Replace _run_publishability_stage with a stub that injects source-fidelity data into its report."""
        def _stage(*args, **kwargs):
            return {
                "status": "success",
                "ready_status": "pass",
                "publishable_status": "pass",
                "source": "toolkit",
                "report": {
                    "source_fidelity_status": status,
                    "source_fidelity_categories": categories,
                    "module": self.module_slug,
                    "ready_status": "pass",
                    "publishable_status": "pass",
                    "effective_publishable_status": "pass",
                },
            }
        return _stage

    def test_finisher_report_mirrors_source_fidelity_status(self):
        finisher._run_publishability_stage = self._stub_publishability(
            "degraded",
            [{"category": "npc_preservation", "status": "degraded", "score": 0.87}],
        )
        result = finisher.run_toolkit_module_postbuild_finishing(
            self.module_slug, strict=True
        )
        self.assertEqual(result.get("source_fidelity_status"), "degraded",
                         "Build report must mirror source_fidelity_status from publishability report")

    def test_finisher_report_mirrors_source_fidelity_categories(self):
        categories = [{"category": "npc_preservation", "status": "pass", "score": 1.0}]
        finisher._run_publishability_stage = self._stub_publishability("pass", categories)
        result = finisher.run_toolkit_module_postbuild_finishing(
            self.module_slug, strict=True
        )
        self.assertEqual(result.get("source_fidelity_categories"), categories,
                         "Build report must mirror source_fidelity_categories from publishability report")

    def test_finisher_report_includes_source_fidelity_report_ref(self):
        finisher._run_publishability_stage = self._stub_publishability(
            "pass",
            [{"category": "npc_preservation", "status": "pass", "score": 1.0}],
        )
        result = finisher.run_toolkit_module_postbuild_finishing(
            self.module_slug, strict=True
        )
        # source_fidelity_report.json is persisted when report exists
        self.assertEqual(result.get("source_fidelity_report"), "source_fidelity_report.json",
                         "Build report must include reference to source_fidelity_report.json when persisted")

    def test_finisher_report_unknown_when_no_report_key(self):
        """When publishability_stage has no report key, source_fidelity_status defaults to unknown."""
        finisher._run_publishability_stage = lambda *a, **kw: {
            "status": "success",
            "ready_status": "pass",
            "publishable_status": "pass",
        }
        result = finisher.run_toolkit_module_postbuild_finishing(
            self.module_slug, strict=True
        )
        self.assertEqual(result.get("source_fidelity_status"), "unknown",
                         "Without report key, build report must default source_fidelity_status to unknown")
        self.assertEqual(result.get("source_fidelity_categories"), [],
                         "Without report key, build report must include empty source_fidelity_categories list")
        self.assertNotIn("source_fidelity_report", result,
                         "Without report key, build report must not include source_fidelity_report ref")

    def test_module_summary_not_used_for_source_fidelity(self):
        """MODULE_SUMMARY.md must not be treated as a source-fidelity repair mechanism."""
        audit_source_path = Path(Path(__file__).resolve().parents[1] /
                                 "scripts/audit_module_publishability.py")
        audit_source = audit_source_path.read_text(encoding="utf-8")
        self.assertNotIn("MODULE_SUMMARY", audit_source,
                         "Audit module must not reference MODULE_SUMMARY for source fidelity")
        finisher_source = Path(Path(__file__).resolve().parents[1] /
                               "web/extensions/toolkit_module_finisher.py")
        finisher_src = finisher_source.read_text(encoding="utf-8")
        # finisher generates MODULE_SUMMARY but must not read it back to drive
        # source-fidelity decisions
        lines_to_check = [
            i + 1 for i, line in enumerate(finisher_src.splitlines())
            if "MODULE_SUMMARY" in line and "read_text" in line
        ]
        self.assertFalse(lines_to_check,
                         f"Finisher must not read MODULE_SUMMARY.md: lines={lines_to_check}")


class TestStep61BuildReportReconciliationFields(unittest.TestCase):
    """Step 6.1: toolkit_build_report.json includes final reconciliation fields."""

    def test_stage_return_includes_reconciliation_fields(self):
        """_run_report_agreement_stage dict includes four reconciliation fields."""
        source = Path("web/extensions/toolkit_module_finisher.py").read_text(encoding="utf-8")
        self.assertIn("source_fidelity_effective_status", source)
        self.assertIn("final_reconciliation_accepted", source)
        self.assertIn("final_reconciliation_status", source)
        self.assertIn("source_fidelity_reconciled", source)

    def test_final_report_includes_reconciliation_top_level_fields(self):
        """Final report assembly writes four reconciliation fields at top level."""
        source = Path("web/extensions/toolkit_module_finisher.py").read_text(encoding="utf-8")
        self.assertIn('["source_fidelity_effective_status"]', source)
        self.assertIn('["final_reconciliation_accepted"]', source)
        self.assertIn('["final_reconciliation_status"]', source)
        self.assertIn('["source_fidelity_reconciled"]', source)

    def test_final_report_defaults_to_source_fidelity_when_no_reconciliation(self):
        """source_fidelity_effective_status defaults to source_fidelity_status when absent."""
        source = Path("web/extensions/toolkit_module_finisher.py").read_text(encoding="utf-8")
        self.assertIn("source_fidelity_status", source,
                      "Effective must fall back to original source_fidelity_status")

    def test_no_source_fidelity_pass_override_in_finisher(self):
        """Finisher never hard-assigns source_fidelity_status to pass."""
        source = Path("web/extensions/toolkit_module_finisher.py").read_text(encoding="utf-8")
        self.assertNotIn('["source_fidelity_status"] = "pass"', source)
        self.assertNotIn("'source_fidelity_status'] = 'pass'", source)

    def test_stage_loads_reconciliation_report(self):
        """_run_report_agreement_stage imports and uses reconciliation helpers."""
        source = Path("web/extensions/toolkit_module_finisher.py").read_text(encoding="utf-8")
        self.assertIn("load_final_reconciliation_report", source)
        self.assertIn("is_final_reconciliation_accepted", source)
        self.assertIn("source_fidelity_effective_status=sfe_status", source)
        self.assertIn("final_reconciliation_accepted=final_rec_accepted", source)
        self.assertIn("final_reconciliation_status=final_rec_status", source)

    def test_report_agreement_stage_reconciliation_fields_in_actual_run(self):
        """With accepted recon report in module dir, finisher stage emits reconciliation fields."""
        import os, tempfile
        from pathlib import Path
        import web.extensions.toolkit_module_finisher as finisher

        self.orig_continuity = finisher._run_continuity_stage
        self.orig_registry = finisher._run_registry_stage
        self.orig_materialization = finisher._run_monster_materialization_stage
        self.orig_publishability = finisher._run_publishability_stage
        self.orig_pub_finalizer = finisher._run_publishability_finalizer_stage
        self.orig_semantic_auth = finisher._run_semantic_authority_stage

        temp_dir = tempfile.TemporaryDirectory()
        # Safety reset: ensure CWD is valid before capturing it. Some preceding
        # tests in the same process may leave CWD pointing to a deleted tempdir.
        _repo_root = Path(__file__).resolve().parent.parent
        try:
            os.chdir(_repo_root)
        except Exception:
            pass
        old_cwd = Path.cwd()
        try:
            repo_root = Path(temp_dir.name)
            os.chdir(repo_root)
            module_dir = repo_root / "modules" / "RARecTest"
            module_dir.mkdir(parents=True, exist_ok=True)
            (module_dir / "module_context.json").write_text("{}", encoding="utf-8")
            (module_dir / "module_plot.json").write_text("{}", encoding="utf-8")
            (module_dir / "validation_report.json").write_text(
                json.dumps({"summary": {"total_failed": 0}}), encoding="utf-8"
            )
            (module_dir / "source_fidelity_report.json").write_text(
                json.dumps({"source_fidelity_status": "blocked"}), encoding="utf-8"
            )
            (module_dir / "final_reconciliation_report.json").write_text(json.dumps({
                "version": "v1", "status": "accepted",
                "reconciliation_status": "accepted",
                "source_fidelity_effective_status": "reconciled_degraded",
                "playable_publication_candidate": True,
                "decisions": ["accepted_final_reconciliation"],
            }), encoding="utf-8")
            # Ensure BU file exists so context_backup_parity check passes.
            (module_dir / "module_context_BU.json").write_text("{}", encoding="utf-8")

            finisher._run_continuity_stage = lambda *a, **kw: {"status": "success"}
            finisher._run_registry_stage = lambda *a, **kw: {"status": "success"}
            finisher._run_monster_materialization_stage = lambda *a, **kw: {"status": "success"}
            finisher._run_publishability_finalizer_stage = lambda *a, **kw: {"status": "success", "changed": False, "errors": [], "warnings": []}
            finisher._run_semantic_authority_stage = lambda *a, **kw: {"status": "success", "changed": False, "warnings": [], "errors": []}
            finisher._run_publishability_stage = lambda *a, **kw: {
                "status": "success",
                "ready_status": "pass",
                "publishable_status": "pass",
                "report": {
                    "source_fidelity_status": "blocked",
                    "source_fidelity_categories": [],
                    "ready_status": "pass",
                    "publishable_status": "pass",
                    "effective_publishable_status": "pass",
                },
            }

            result = finisher.run_toolkit_module_postbuild_finishing(
                "RARecTest", strict=True
            )

            self.assertEqual(result.get("source_fidelity_status"), "blocked")
            self.assertEqual(result.get("source_fidelity_effective_status"), "reconciled_degraded")
            self.assertTrue(result.get("final_reconciliation_accepted"))
            self.assertEqual(result.get("final_reconciliation_status"), "accepted")
            self.assertTrue(result.get("source_fidelity_reconciled"))
            self.assertEqual(result.get("playable_publication_status"), "pass")

            report_path = module_dir / "toolkit_build_report.json"
            self.assertTrue(report_path.exists())
            persisted = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(persisted.get("source_fidelity_status"), "blocked")
            self.assertEqual(persisted.get("source_fidelity_effective_status"), "reconciled_degraded")
            self.assertTrue(persisted.get("final_reconciliation_accepted"))
        finally:
            finisher._run_continuity_stage = self.orig_continuity
            finisher._run_registry_stage = self.orig_registry
            finisher._run_monster_materialization_stage = self.orig_materialization
            finisher._run_publishability_stage = self.orig_publishability
            finisher._run_publishability_finalizer_stage = self.orig_pub_finalizer
            finisher._run_semantic_authority_stage = self.orig_semantic_auth
            os.chdir(old_cwd)
            temp_dir.cleanup()


class TestStep62TemplateReconciliationDisplay(unittest.TestCase):
    """Step 6.2: template displays reconciliation fields distinctly from source fidelity."""

    def test_template_shows_source_fidelity_effective(self):
        source = Path("web/templates/module_toolkit.html").read_text(encoding="utf-8")
        self.assertIn("Source Fidelity Effective", source)

    def test_template_shows_source_fidelity_reconciled(self):
        source = Path("web/templates/module_toolkit.html").read_text(encoding="utf-8")
        self.assertIn("Source Fidelity Reconciled", source)

    def test_template_shows_final_reconciliation(self):
        source = Path("web/templates/module_toolkit.html").read_text(encoding="utf-8")
        self.assertIn("Final Reconciliation", source)

    def test_template_still_shows_original_source_fidelity_and_playable(self):
        source = Path("web/templates/module_toolkit.html").read_text(encoding="utf-8")
        self.assertIn("Source Fidelity:", source)
        self.assertIn("Playable Publication:", source)

    def test_template_uses_effective_and_reconciled_fields(self):
        source = Path("web/templates/module_toolkit.html").read_text(encoding="utf-8")
        self.assertIn("source_fidelity_effective_status", source)
        self.assertIn("source_fidelity_reconciled", source)
        self.assertIn("final_reconciliation_status", source)
        self.assertIn("final_reconciliation_accepted", source)

    def test_template_no_source_fidelity_pass_override(self):
        source = Path("web/templates/module_toolkit.html").read_text(encoding="utf-8")
        fields = ["source_fidelity_status", "source_fidelity_effective_status"]
        for f in fields:
            self.assertNotIn(f'{f} = "pass"', source,
                             f"Template must not hard-assign {f} to pass")


class TestStep63ReconciledPlayableNoGenericErrors(unittest.TestCase):
    """Step 6.3: reconciled playable modules do not show generic error copy."""

    def test_is_final_reconciled_playable_helper_exists(self):
        source = Path("web/templates/module_toolkit.html").read_text(encoding="utf-8")
        self.assertIn("isFinalReconciledPlayable", source)

    def test_helper_checks_all_required_fields(self):
        source = Path("web/templates/module_toolkit.html").read_text(encoding="utf-8")
        self.assertIn("final_reconciliation_accepted", source)
        self.assertIn("source_fidelity_reconciled", source)
        self.assertIn("source_fidelity_effective_status", source)
        self.assertIn("playable_publication_status", source)

    def test_helper_inspects_nested_payloads(self):
        source = Path("web/templates/module_toolkit.html").read_text(encoding="utf-8")
        self.assertIn("obj.result || {}", source,
                      "Helper must check payload.result")
        self.assertIn("report_agreement", source,
                      "Helper must check nested report_agreement")

    def test_blocked_branch_calls_is_final_reconciled_playable(self):
        source = Path("web/templates/module_toolkit.html").read_text(encoding="utf-8")
        blocked_start = source.find("job.status === 'blocked'")
        self.assertGreater(blocked_start, 0)
        section = source[blocked_start:blocked_start + 800]
        self.assertIn("isFinalReconciledPlayable", section)

    def test_not_publishable_branch_calls_is_final_reconciled_playable(self):
        source = Path("web/templates/module_toolkit.html").read_text(encoding="utf-8")
        np_start = source.find("job.status === 'not_publishable'")
        self.assertGreater(np_start, 0)
        section = source[np_start:np_start + 800]
        self.assertIn("isFinalReconciledPlayable", section)

    def test_reconciled_branch_no_build_fidelity_blocked_text(self):
        source = Path("web/templates/module_toolkit.html").read_text(encoding="utf-8")
        idx_reconciled = source.find("isFinalReconciledPlayable(blockedResult)")
        idx_build_blocked = source.find("Build fidelity blocked")
        self.assertLess(idx_reconciled, idx_build_blocked,
                        "Reconciled check must precede generic Build fidelity blocked")

    def test_reconciled_blocked_title_is_not_failure(self):
        source = Path("web/templates/module_toolkit.html").read_text(encoding="utf-8")
        blocked_start = source.find("job.status === 'blocked'")
        section = source[blocked_start:blocked_start + 1200]
        self.assertIn("Final Reconciliation Accepted", section,
                      "Reconciled blocked title must mention Final Reconciliation Accepted")
        self.assertIn("Build Blocked - Fidelity Check Failed", source,
                      "Generic blocked title must remain for non-reconciled cases")

    def test_reconciled_not_publishable_title_is_not_failure(self):
        source = Path("web/templates/module_toolkit.html").read_text(encoding="utf-8")
        np_start = source.find("job.status === 'not_publishable'")
        section = source[np_start:np_start + 1200]
        self.assertIn("Final Reconciliation Accepted", section,
                      "Reconciled not_publishable title must mention Final Reconciliation Accepted")
        self.assertIn("Not Publishable", source,
                      "Generic not_publishable title must remain for non-reconciled cases")

    def test_generic_blocked_text_still_present_for_non_reconciled(self):
        source = Path("web/templates/module_toolkit.html").read_text(encoding="utf-8")
        self.assertIn("Build fidelity blocked", source)
        self.assertIn("not_publishable", source)


class TestStep64ReconciledDegradedWording(unittest.TestCase):
    """Step 6.4: wording tests for reconciled/degraded status in template."""

    def setUp(self):
        self.source = Path("web/templates/module_toolkit.html").read_text(encoding="utf-8")

    def test_template_contains_reconciled_degraded_wording(self):
        self.assertIn("reconciled/degraded", self.source)
        self.assertIn("not clean pass", self.source)

    def test_template_contains_playable_publication_wording(self):
        self.assertIn("Playable Publication", self.source)

    def test_template_contains_source_fidelity_effective(self):
        self.assertIn("Source Fidelity Effective", self.source)

    def test_template_contains_final_reconciliation_labels(self):
        self.assertIn("Final Reconciliation", self.source)
        self.assertIn("Final Reconciliation Accepted", self.source)

    def test_template_no_clean_pass_claim_in_reconciled_branch(self):
        self.assertNotIn("source fidelity pass", self.source.lower())
        self.assertNotIn("source fidelity is pass", self.source.lower())
        self.assertNotIn("clean source-fidelity pass", self.source.lower())

    def test_source_fidelity_before_effective_ordering(self):
        idx_sf = self.source.find("Source Fidelity:")
        idx_sfe = self.source.find("Source Fidelity Effective:")
        self.assertLess(idx_sf, idx_sfe,
                        "Source Fidelity must appear before Source Fidelity Effective")
        self.assertIn("source_fidelity_effective_status", self.source)

    def test_reconciled_copy_includes_playable_and_degraded(self):
        idx = self.source.find("reconciled/degraded")
        section = self.source[idx - 200:idx + 200]
        self.assertIn("Playable publication candidate", section,
                      "Reconciled copy must mention playable publication")

    def test_generic_failure_copy_still_present(self):
        self.assertIn("Build fidelity blocked", self.source,
                      "Generic blocked copy must remain for non-reconciled")
        self.assertIn("not_publishable", self.source,
                      "Generic not_publishable copy must remain for non-reconciled")

    # ------------------------------------------------------------------
    # Step 6.4 source-contract tests: prove isFinalReconciledPlayable
    # helper gates on all four required axes simultaneously and rejects
    # clean-pass source-fidelity effective status.
    # ------------------------------------------------------------------

    def _extract_helper_block(self):
        """Return the body of the isFinalReconciledPlayable function."""
        start = self.source.find("function isFinalReconciledPlayable(")
        self.assertGreater(start, 0, "Helper isFinalReconciledPlayable must exist")
        end = self.source.find("\n        }\n", start)
        if end == -1:
            end = self.source.find("function formatReportAgreementSection", start)
        self.assertGreater(end, start)
        return self.source[start:end]

    def test_helper_requires_playable_publication_status_pass(self):
        block = self._extract_helper_block()
        self.assertIn(
            "playable_publication_status === 'pass'",
            block,
            "isFinalReconciledPlayable must require playable_publication_status='pass'",
        )

    def test_helper_requires_source_fidelity_effective_status_reconciled_degraded(self):
        block = self._extract_helper_block()
        self.assertIn(
            "source_fidelity_effective_status === 'reconciled_degraded'",
            block,
            "isFinalReconciledPlayable must require "
            "source_fidelity_effective_status='reconciled_degraded'",
        )

    def test_helper_rejects_clean_pass_source_fidelity_effective(self):
        block = self._extract_helper_block()
        self.assertNotIn(
            "source_fidelity_effective_status === 'pass'",
            block,
            "isFinalReconciledPlayable must NOT match when "
            "source_fidelity_effective_status is 'pass' (would conflate "
            "clean pass with reconciled/degraded)",
        )
        self.assertNotIn(
            'source_fidelity_effective_status === "pass"',
            block,
            "isFinalReconciledPlayable must NOT match double-quoted 'pass' either",
        )

    def test_helper_requires_final_reconciliation_accepted_true(self):
        block = self._extract_helper_block()
        self.assertIn(
            "final_reconciliation_accepted === true",
            block,
            "isFinalReconciledPlayable must require final_reconciliation_accepted=true",
        )

    def test_helper_requires_source_fidelity_reconciled_true(self):
        block = self._extract_helper_block()
        self.assertIn(
            "source_fidelity_reconciled === true",
            block,
            "isFinalReconciledPlayable must require source_fidelity_reconciled=true",
        )

    def test_helper_uses_single_conditional_with_all_four_axes(self):
        """The helper must combine all four required axes in ONE
        conditional so a payload missing any axis is rejected."""
        block = self._extract_helper_block()
        # All four required keys must appear in the same return-true branch.
        return_idx = block.find("return true")
        self.assertGreater(return_idx, 0, "Helper must have a return-true branch")
        branch = block[:return_idx]
        self.assertIn("final_reconciliation_accepted", branch)
        self.assertIn("source_fidelity_reconciled", branch)
        self.assertIn("source_fidelity_effective_status", branch)
        self.assertIn("playable_publication_status", branch)

    def test_helper_walks_multiple_nested_payload_shapes(self):
        """The helper must inspect nested report_agreement and result
        candidates so the reconciled/degraded axes are surfaced no
        matter where the GUI mounts the report."""
        block = self._extract_helper_block()
        for needle in (
            "obj",
            "obj.result || {}",
            "obj.report_agreement || {}",
            "(obj.result || {}).report_agreement || {}",
            "(obj.stages || {}).report_agreement || {}",
        ):
            self.assertIn(needle, block, f"isFinalReconciledPlayable must inspect {needle}")

    # ------------------------------------------------------------------
    # Step 6.4 source-contract tests: prove formatReportAgreementSection
    # emits Source Fidelity:, Source Fidelity Effective:, and Playable
    # Publication: as separate, distinct output lines.
    # ------------------------------------------------------------------

    def _extract_formatter_block(self):
        """Return the body of the formatReportAgreementSection function."""
        start = self.source.find("function formatReportAgreementSection(")
        self.assertGreater(start, 0, "formatReportAgreementSection must exist")
        end = self.source.find("\n        }\n", start)
        if end == -1:
            end = self.source.find("\n        function ", start + 1)
        self.assertGreater(end, start)
        return self.source[start:end]

    def test_formatter_emits_source_fidelity_label(self):
        block = self._extract_formatter_block()
        self.assertIn("Source Fidelity:", block,
                      "Formatter must emit 'Source Fidelity:' line")

    def test_formatter_emits_source_fidelity_effective_label(self):
        block = self._extract_formatter_block()
        self.assertIn("Source Fidelity Effective:", block,
                      "Formatter must emit 'Source Fidelity Effective:' line")

    def test_formatter_emits_playable_publication_label(self):
        block = self._extract_formatter_block()
        self.assertIn("Playable Publication:", block,
                      "Formatter must emit 'Playable Publication:' line")

    def test_three_axes_are_independent_lines(self):
        """The three axes (Source Fidelity, Source Fidelity Effective,
        Playable Publication) must be emitted on INDEPENDENT lines, not
        concatenated into a single output line, so the GUI display can
        style each axis separately."""
        block = self._extract_formatter_block()
        for label in ("Source Fidelity:", "Source Fidelity Effective:", "Playable Publication:"):
            push_idx = block.find(f"lines.push(`- {label}")
            self.assertGreater(
                push_idx, 0,
                f"'{label}' must be emitted via a separate lines.push() call",
            )

    def test_formatter_distinguishes_source_fidelity_from_effective(self):
        """The formatter must read source_fidelity_status and
        source_fidelity_effective_status from INDEPENDENT sources so
        the two axes never collapse into one another."""
        block = self._extract_formatter_block()
        # sf reads ra.source_fidelity_status or _obj.source_fidelity_status
        self.assertIn("ra.source_fidelity_status", block)
        # sfe reads ra.source_fidelity_effective_status (with fallback)
        self.assertIn("ra.source_fidelity_effective_status", block)
        # The two lines must be emitted in distinct lines.push calls
        sf_push = block.find("Source Fidelity: ${sf}")
        sfe_push = block.find("Source Fidelity Effective:")
        self.assertGreater(sf_push, 0,
                          "Source Fidelity line must use a distinct "
                          "lines.push() with its own template literal")
        self.assertGreater(sfe_push, 0,
                          "Source Fidelity Effective line must use a distinct "
                          "lines.push() with its own template literal")
        self.assertNotEqual(sf_push, sfe_push,
                           "Source Fidelity and Source Fidelity Effective must be "
                           "emitted by DIFFERENT lines.push() calls")

    def test_formatter_keeps_final_reconciliation_accepted_distinct(self):
        """The formatter must surface final_reconciliation_accepted
        alongside the source-fidelity axes (not collapse them) so the
        reconciled/degraded truth remains visible."""
        block = self._extract_formatter_block()
        self.assertIn("Final Reconciliation:", block)
        self.assertIn("ra.final_reconciliation_accepted", block)
        self.assertIn("source_fidelity_reconciled", block)

    # ------------------------------------------------------------------
    # Step 6.4 source-contract tests: prove the reconciled branch copy
    # does NOT contain clean-pass source-fidelity wording.
    # ------------------------------------------------------------------

    def _extract_reconciled_branch_block(self):
        """Return the reconciled success branch block: the section
        between the first isFinalReconciledPlayable(true) body and its
        end of branch."""
        marker = "Build completed after final reconciliation"
        idx = self.source.find(marker)
        self.assertGreater(idx, 0, "Reconciled branch copy must exist")
        # Use a generous window to capture the entire branch message
        return self.source[idx:idx + 800]

    def test_reconciled_branch_states_reconciled_degraded_explicitly(self):
        block = self._extract_reconciled_branch_block()
        self.assertIn("reconciled/degraded", block,
                      "Reconciled branch must say 'reconciled/degraded'")
        self.assertIn("not clean pass", block,
                      "Reconciled branch must say 'not clean pass'")

    def test_reconciled_branch_mentions_playable_publication(self):
        block = self._extract_reconciled_branch_block()
        self.assertIn("Playable publication candidate", block,
                      "Reconciled branch must mention playable publication")

    def test_reconciled_branch_no_clean_pass_phrase(self):
        """The reconciled branch must not contain the clean-pass
        source-fidelity claim phrases that the spec forbids."""
        block = self._extract_reconciled_branch_block().lower()
        for forbidden in (
            "source fidelity pass",
            "source fidelity is pass",
            "clean source-fidelity pass",
            "clean_pass",
        ):
            self.assertNotIn(
                forbidden, block,
                f"Reconciled branch must not contain '{forbidden}' "
                "(would falsely imply clean pass)",
            )

    # ------------------------------------------------------------------
    # Step 6.4 source-contract tests: prove the generic failure copy
    # remains for non-reconciled / non-playable cases (i.e. the
    # separate-axes contract does not collapse generic failure text).
    # ------------------------------------------------------------------

    def test_generic_blocked_branch_copy_intact(self):
        """The generic 'Build Blocked - Fidelity Check Failed' copy
        must still exist for non-reconciled blocked cases."""
        self.assertIn("Build Blocked - Fidelity Check Failed", self.source,
                      "Generic blocked title must remain for non-reconciled cases")
        self.assertIn("Build fidelity blocked", self.source,
                      "Generic blocked error must remain for non-reconciled cases")

    def test_generic_not_publishable_branch_copy_intact(self):
        """The generic not_publishable copy must still exist for
        non-reconciled / non-accepted-reconciliation cases."""
        self.assertIn("Not Publishable", self.source,
                      "Generic not_publishable title must remain for non-reconciled cases")
        self.assertIn("publishability remains blocked", self.source,
                      "Generic not_publishable copy must remain for non-reconciled cases")


class TestStep64ReportAgreementAxesSeparation(unittest.TestCase):
    """Step 6.4: prove report data itself separates playable
    publication from reconciled/degraded source fidelity.

    The Step 6.3 GUI tests pin template wording and helper
    conditional structure. This class pins the *data* side: the
    compose_report_agreement result must keep the playable_publication
    axis and the source-fidelity axis as INDEPENDENT fields so
    downstream consumers (GUI, finisher, audit reports) cannot
    collapse them."""

    def _all_pass_kwargs(self):
        return dict(
            validation_status="pass",
            ready_status="pass",
            publishable_status="pass",
            effective_publishable_status="pass",
            toolkit_top_level_status="pass",
        )

    def _accepted_recon_kwargs(self):
        return dict(
            source_fidelity_effective_status="reconciled_degraded",
            final_reconciliation_accepted=True,
            final_reconciliation_status="accepted",
        )

    def test_result_dict_has_separate_playable_and_fidelity_keys(self):
        """The result dict must expose playable_publication_status,
        source_fidelity_status, source_fidelity_effective_status,
        source_fidelity_reconciled, and final_reconciliation_accepted
        as INDEPENDENT keys (no aliasing)."""
        from utils.toolkit_report_agreement import compose_report_agreement
        result = compose_report_agreement(
            **self._all_pass_kwargs(),
            source_fidelity_status="blocked",
            **self._accepted_recon_kwargs(),
        )
        for key in (
            "playable_publication_status",
            "source_fidelity_status",
            "source_fidelity_effective_status",
            "source_fidelity_reconciled",
            "final_reconciliation_accepted",
            "final_reconciliation_status",
        ):
            self.assertIn(key, result,
                          f"Result must expose {key} as an independent key")

    def test_accepted_recon_playable_pass_does_not_rewrite_source_fidelity(self):
        """Accepted reconciliation that flips playable to pass MUST
        leave source_fidelity_status at the original blocked value
        (no silent rewrite to pass)."""
        from utils.toolkit_report_agreement import compose_report_agreement
        result = compose_report_agreement(
            **self._all_pass_kwargs(),
            source_fidelity_status="blocked",
            **self._accepted_recon_kwargs(),
        )
        self.assertEqual(result["playable_publication_status"], "pass")
        self.assertEqual(result["source_fidelity_status"], "blocked")
        self.assertEqual(result["source_fidelity_effective_status"], "reconciled_degraded")
        self.assertTrue(result["source_fidelity_reconciled"])
        self.assertTrue(result["final_reconciliation_accepted"])
        # source_fidelity_status must NOT be the clean-pass value
        self.assertNotEqual(result["source_fidelity_status"], "pass")

    def test_clean_pass_keeps_effective_status_pass_no_reconciled_flag(self):
        """A clean source-fidelity pass (no reconciliation needed)
        must keep playable_publication_status=pass WITHOUT firing
        the reconciled flag, and effective status must equal pass
        (no false reconciled_degraded label)."""
        from utils.toolkit_report_agreement import compose_report_agreement
        result = compose_report_agreement(
            **self._all_pass_kwargs(),
            source_fidelity_status="pass",
        )
        self.assertEqual(result["playable_publication_status"], "pass")
        self.assertEqual(result["source_fidelity_status"], "pass")
        self.assertEqual(result["source_fidelity_effective_status"], "pass")
        self.assertFalse(result["source_fidelity_reconciled"])
        self.assertFalse(result["final_reconciliation_accepted"])

    def test_degraded_original_with_accepted_recon_axes_remain_separate(self):
        """Degraded original + accepted reconciliation: playable flips
        to pass, source_fidelity_status stays degraded (not pass), and
        effective status carries the reconciled_degraded label."""
        from utils.toolkit_report_agreement import compose_report_agreement
        result = compose_report_agreement(
            **self._all_pass_kwargs(),
            source_fidelity_status="degraded",
            **self._accepted_recon_kwargs(),
        )
        self.assertEqual(result["playable_publication_status"], "pass")
        self.assertEqual(result["source_fidelity_status"], "degraded")
        self.assertEqual(result["source_fidelity_effective_status"], "reconciled_degraded")
        self.assertNotEqual(result["source_fidelity_status"], "pass")
        self.assertTrue(result["source_fidelity_reconciled"])

    def test_blocked_without_recon_axes_blocked_separately(self):
        """Blocked source fidelity without accepted reconciliation
        must keep BOTH axes blocked. Playable stays blocked even when
        other gates pass."""
        from utils.toolkit_report_agreement import compose_report_agreement
        result = compose_report_agreement(
            **self._all_pass_kwargs(),
            source_fidelity_status="blocked",
        )
        self.assertEqual(result["playable_publication_status"], "blocked")
        self.assertEqual(result["source_fidelity_status"], "blocked")
        self.assertEqual(result["source_fidelity_effective_status"], "blocked")
        self.assertFalse(result["source_fidelity_reconciled"])
        self.assertFalse(result["final_reconciliation_accepted"])

    def test_blocked_effective_status_with_accepted_recon_does_not_pretend_pass(self):
        """If the caller marks final_reconciliation_accepted but
        leaves source_fidelity_effective_status at 'blocked' (i.e.
        a malformed non-reconciled path), the composer must NOT
        pretend the source-fidelity is clean pass. The reconciled
        flag must be false because effective != 'reconciled_degraded'."""
        from utils.toolkit_report_agreement import compose_report_agreement
        result = compose_report_agreement(
            **self._all_pass_kwargs(),
            source_fidelity_status="blocked",
            source_fidelity_effective_status="blocked",
            final_reconciliation_accepted=True,
        )
        # Playable must NOT be pass because the accepted flag is
        # meaningless without the reconciled_degraded effective status
        self.assertNotEqual(result["playable_publication_status"], "pass")
        self.assertFalse(result["source_fidelity_reconciled"])
        self.assertEqual(result["source_fidelity_status"], "blocked")

    def test_playable_and_fidelity_values_can_diverge(self):
        """The two axes must be ABLE to diverge: one may be pass
        while the other is not. This proves they are independent
        rather than aliased or co-derived."""
        from utils.toolkit_report_agreement import compose_report_agreement
        # Diverged case A: playable=pass, source_fidelity=blocked
        result_a = compose_report_agreement(
            **self._all_pass_kwargs(),
            source_fidelity_status="blocked",
            **self._accepted_recon_kwargs(),
        )
        self.assertEqual(result_a["playable_publication_status"], "pass")
        self.assertEqual(result_a["source_fidelity_status"], "blocked")
        self.assertNotEqual(
            result_a["playable_publication_status"],
            result_a["source_fidelity_status"],
            "Axes must be able to diverge (playable=pass, fidelity=blocked)",
        )
        # Diverged case B: playable=blocked, source_fidelity=pass
        result_b_kwargs = self._all_pass_kwargs()
        result_b_kwargs["source_fidelity_status"] = "pass"
        result_b_kwargs["publishable_status"] = "blocked"  # force playable blocked
        result_b = compose_report_agreement(**result_b_kwargs)
        self.assertEqual(result_b["source_fidelity_status"], "pass")
        self.assertEqual(result_b["playable_publication_status"], "blocked")
        self.assertNotEqual(
            result_b["playable_publication_status"],
            result_b["source_fidelity_status"],
            "Axes must be able to diverge (playable=blocked, fidelity=pass)",
        )

    def test_no_aliasing_or_co_derivation_in_production_source(self):
        """Static guard: the production compose_report_agreement
        source must not co-derive playable_publication_status from
        source_fidelity_status. The two assignments must be
        independent in the source."""
        import inspect
        from utils.toolkit_report_agreement import compose_report_agreement
        source = inspect.getsource(compose_report_agreement)
        # The function must NOT contain any alias assignment such as
        # 'playable = sf' (which would co-derive the two axes).
        self.assertNotRegex(
            source,
            r"^\s*playable\s*=\s*sf\b",
            "playable_publication_status must not be aliased to "
            "source_fidelity_status (would co-derive the axes)",
            # Python 3 unittest supports msg= for assertNotRegex
        )
        # The two result keys must be assigned independently.
        self.assertIn('"playable_publication_status": playable', source)
        self.assertIn('"source_fidelity_status": sf', source)
        # And the keys must appear in distinct assignment contexts
        # (both inside the same return dict, but as separate keys,
        # not as one alias of the other).

    def test_module_dir_accepted_recon_axes_separate_in_real_data(self):
        """End-to-end via compose_report_agreement_from_module_dir:
        when a module dir has a real accepted reconciliation report
        on disk, the returned dict must keep playable_publication
        and source_fidelity_status as INDEPENDENT fields, with the
        effective status labelled reconciled_degraded and the
        original source_fidelity_status preserved as blocked."""
        import tempfile
        from pathlib import Path
        from utils.toolkit_report_agreement import compose_report_agreement_from_module_dir

        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        module_dir = Path(tmpdir.name)
        (module_dir / "validation_report.json").write_text(
            json.dumps({"status": "pass", "valid": True}))
        (module_dir / "source_fidelity_report.json").write_text(
            json.dumps({"source_fidelity_status": "blocked"}))
        (module_dir / "toolkit_build_report.json").write_text(
            json.dumps({
                "status": "pass",
                "ready_status": "pass",
                "publishable_status": "pass",
                "effective_publishable_status": "pass",
            }))
        (module_dir / "final_reconciliation_report.json").write_text(
            json.dumps({
                "version": "accurate_ingest_final_reconciliation_report.v1",
                "status": "accepted",
                "reconciliation_status": "accepted",
                "source_fidelity_effective_status": "reconciled_degraded",
                "playable_publication_candidate": True,
                "decisions": [{"decision": "delete_bogus_atom"}],
            }))

        result = compose_report_agreement_from_module_dir(module_dir)
        # The two axes must be INDEPENDENT fields, not the same value.
        self.assertEqual(result["playable_publication_status"], "pass")
        self.assertEqual(result["source_fidelity_status"], "blocked")
        self.assertEqual(result["source_fidelity_effective_status"], "reconciled_degraded")
        self.assertTrue(result["source_fidelity_reconciled"])
        self.assertTrue(result["final_reconciliation_accepted"])
        # The original must NOT have been rewritten.
        self.assertNotEqual(result["source_fidelity_status"], "pass")


class TestLiveWellOfRuinStatusRoutingFix(unittest.TestCase):
    """Post-7 fix: final_reconciliation_required routing and safe_write_json fix."""

    def test_final_reconciliation_required_is_terminal_job_state(self):
        source = Path("web/routes/toolkit_homebrew_routes.py").read_text(encoding="utf-8")
        self.assertIn('"final_reconciliation_required"', source)

    def test_final_reconciliation_required_is_canonical_phase(self):
        source = Path("web/routes/toolkit_homebrew_routes.py").read_text(encoding="utf-8")
        self.assertIn('"final_reconciliation_required"', source)

    def test_final_reconciliation_is_canonical_phase(self):
        source = Path("web/routes/toolkit_homebrew_routes.py").read_text(encoding="utf-8")
        self.assertIn('"final_reconciliation"', source)

    def test_build_status_handler_exists(self):
        source = Path("web/routes/toolkit_homebrew_routes.py").read_text(encoding="utf-8")
        self.assertIn('build_status == "final_reconciliation_required"', source)

    def test_build_handler_maps_to_job_status(self):
        source = Path("web/routes/toolkit_homebrew_routes.py").read_text(encoding="utf-8")
        self.assertIn('"final_reconciliation_required"', source)
        self.assertIn('"final_reconciliation"', source)
        self.assertIn("final_reconciliation_brief_path", source)

    def test_template_has_final_reconciliation_required_branch(self):
        source = Path("web/templates/module_toolkit.html").read_text(encoding="utf-8")
        self.assertIn("'final_reconciliation_required'", source)
        self.assertIn("editorial, not fatal", source)
        self.assertIn("final_reconciliation_brief_path", source)

    def test_template_final_reconciliation_before_generic_failed(self):
        source = Path("web/templates/module_toolkit.html").read_text(encoding="utf-8")
        idx_final_rec = source.find("'final_reconciliation_required'")
        idx_failed = source.rfind("Homebrew ingest failed")
        self.assertLess(idx_final_rec, idx_failed,
                        "final_reconciliation_required must appear before generic failed")

    def test_npc_reconciler_safe_write_json_args_correct(self):
        source = Path("utils/npc_reconciler.py").read_text(encoding="utf-8")
        self.assertIn("safe_write_json(area_path, area_data)", source)


class TestStep52ReadinessFinisherGate(unittest.TestCase):
    """Step 5.2: readiness/finisher continuation is allowed ONLY when
    final reconciliation is accepted and deterministic gates passed.

    The gate is currently encoded as `build_status == "success"` in the
    route layer (see ``web/routes/toolkit_homebrew_routes.py``). The
    packet builder is the single source of truth for that status; the
    finisher reads the accepted ``final_reconciliation_report.json``
    from ``module_dir`` and pins accepted metadata into
    ``compose_report_agreement(...)``.

    These tests pin the contract so future refactors cannot silently
    widen the gate (e.g. by treating ``build_status == "blocked"`` as
    success or by skipping the finisher's accepted-report load).
    """

    def _read(self, rel: str) -> str:
        return Path(rel).read_text(encoding="utf-8")

    def test_route_layer_has_blocked_branch(self):
        """Route layer must handle ``build_status == "blocked"`` before
        the success branch (terminal block returns early)."""
        source = self._read("web/routes/toolkit_homebrew_routes.py")
        self.assertIn('build_status == "blocked"', source)
        idx_blocked = source.find('build_status == "blocked"')
        idx_success = source.find('build_status == "success"')
        self.assertGreater(idx_blocked, 0)
        self.assertGreater(idx_success, 0)
        self.assertLess(
            idx_blocked,
            idx_success,
            "build_status == 'blocked' branch must appear BEFORE "
            "build_status == 'success' so terminal blocks return before "
            "readiness/finisher continuation",
        )

    def test_route_layer_has_final_reconciliation_required_branch(self):
        """Route layer must handle ``build_status == "final_reconciliation_required"``
        as a separate pause branch before the success branch."""
        source = self._read("web/routes/toolkit_homebrew_routes.py")
        self.assertIn('build_status == "final_reconciliation_required"', source)
        idx_required = source.find('build_status == "final_reconciliation_required"')
        idx_success = source.find('build_status == "success"')
        self.assertGreater(idx_required, 0)
        self.assertGreater(idx_success, 0)
        self.assertLess(
            idx_required,
            idx_success,
            "build_status == 'final_reconciliation_required' branch must "
            "appear BEFORE the success branch so the legacy pause returns "
            "before readiness/finisher continuation",
        )

    def test_route_layer_success_branch_launches_readiness_then_finisher(self):
        """The only path that reaches readiness and finisher is
        ``build_status == "success"``."""
        source = self._read("web/routes/toolkit_homebrew_routes.py")
        # Find the first occurrence of the success branch in the build
        # handler (the packet-build gate area). There are several
        # ``build_status`` checks in the file; we want the one closest
        # to the readiness/finisher invocations.
        idx_success = source.find('if build_status == "success":')
        self.assertGreater(idx_success, 0)
        # Both readiness and finisher invocations must live AFTER the
        # build_status == "success" branch starts.
        success_block = source[idx_success:]
        self.assertIn(
            "_run_homebrew_readiness_gate", success_block,
            "readiness gate must be invoked inside the build_status == "
            "'success' branch (Step 5.2 gate)",
        )
        self.assertIn(
            "_run_homebrew_finisher", success_block,
            "finisher must be invoked inside the build_status == 'success' "
            "branch (Step 5.2 gate)",
        )
        # Function definitions of readiness/finisher wrappers (and any
        # OTHER route handler that also calls them, e.g. the standalone
        # finish endpoint) may appear before the build-status success
        # branch. The contract is about INVOCATIONS inside the build
        # handler, not about definitions. So we pin:
        #   1. At least one readiness invocation appears AFTER the
        #      build_status == "success" check.
        #   2. At least one finisher invocation appears AFTER that
        #      readiness invocation.
        idx_readiness_invocation = success_block.find("_run_homebrew_readiness_gate(")
        self.assertGreater(idx_readiness_invocation, 0)
        post_readiness = success_block[idx_readiness_invocation:]
        idx_finisher_invocation = post_readiness.find("_run_homebrew_finisher(")
        self.assertGreater(
            idx_finisher_invocation, 0,
            "finisher must be invoked AFTER readiness inside the "
            "build_status == 'success' branch",
        )

    def test_route_layer_has_explicit_step52_gate_comment(self):
        """The route layer's success branch should carry the Step 5.2
        gate comment so future maintainers do not widen the gate."""
        source = self._read("web/routes/toolkit_homebrew_routes.py")
        self.assertIn("Step 5.2 gate", source)

    def test_packet_builder_editor_accepted_keeps_status_success(self):
        """When the editor accepts and persist succeeds, the packet
        builder's ``build_result["status"]`` must remain ``"success"``
        (the only status that lets the route layer proceed to
        readiness/finisher)."""
        source = self._read("web/extensions/toolkit_homebrew_packet_builder.py")
        # The accepted branch must NOT mutate build_result["status"].
        # Find the helper's accepted path block (between the
        # ``# Accepted path:`` comment and the helper's ``return True``).
        accepted_idx = source.find("# Accepted path: set accepted metadata")
        self.assertGreater(accepted_idx, 0)
        accepted_block_end = source.find("return True", accepted_idx)
        self.assertGreater(accepted_block_end, 0)
        block = source[accepted_idx:accepted_block_end]
        self.assertNotIn(
            'build_result["status"] = "blocked"',
            block,
            "accepted path must NOT mark build_result as blocked",
        )
        self.assertNotIn(
            'build_result["status"] = "final_reconciliation_required"',
            block,
            "accepted path must NOT mark build_result as required",
        )
        # And the accepted path MUST set the accepted metadata.
        self.assertIn('build_result["final_reconciliation_accepted"] = True', block)
        self.assertIn(
            'build_result["source_fidelity_effective_status"] = "reconciled_degraded"',
            block,
        )

    def test_packet_builder_helper_blocked_path_returns_early(self):
        """When the editor helper marks build_result as blocked, the
        packet builder must return early so the build does NOT reach
        readiness/finisher."""
        source = self._read("web/extensions/toolkit_homebrew_packet_builder.py")
        # Locate the editor-call site and the helper's blocked return.
        helper_call_idx = source.find("_invoke_final_editor_or_fallback(")
        self.assertGreater(helper_call_idx, 0)
        block = source[helper_call_idx:helper_call_idx + 4000]
        # The if-not-editor-accepted branch must short-circuit on
        # "blocked" status (the helper already mutated build_result).
        self.assertIn('if _resolved_status == "blocked":', block)
        self.assertIn("return build_result", block)

    def test_packet_builder_status_blocked_does_not_reach_normal_persistence(self):
        """``status: blocked`` paths must NOT re-enter the normal
        build_result persistence block at the end of the function."""
        source = self._read("web/extensions/toolkit_homebrew_packet_builder.py")
        # Find the normal build_result_persisted call near the end of
        # the function. The blocked / required branches return before
        # this block runs.
        persisted_idx = source.find("build_result_persisted")
        self.assertGreater(persisted_idx, 0)
        # Trace the helper's blocked return statement and confirm it
        # appears BEFORE the persisted block.
        blocked_return_idx = source.rfind("return build_result", 0, persisted_idx)
        self.assertGreater(blocked_return_idx, 0)
        self.assertLess(
            blocked_return_idx,
            persisted_idx,
            "blocked return must precede normal build_result persistence",
        )

    def test_packet_builder_source_fidelity_honesty_never_claims_clean_pass(self):
        """The accepted branch must never claim clean source-fidelity
        pass. ``source_fidelity_effective_status`` must be
        ``reconciled_degraded`` only."""
        source = self._read("web/extensions/toolkit_homebrew_packet_builder.py")
        accepted_idx = source.find("# Accepted path: set accepted metadata")
        self.assertGreater(accepted_idx, 0)
        accepted_block_end = source.find("return True", accepted_idx)
        self.assertGreater(accepted_block_end, 0)
        block = source[accepted_idx:accepted_block_end]
        for forbidden in ('"pass"', "'pass'", '"clean_pass"', '"clean"',
                          '"source_fidelity_pass"'):
            self.assertNotIn(
                forbidden, block,
                f"accepted path must never assign clean-pass variant {forbidden}",
            )

    def test_finisher_loads_accepted_final_reconciliation_report_from_module_dir(self):
        """The finisher's report-agreement stage must load the accepted
        ``final_reconciliation_report.json`` from ``module_dir`` (not
        from a top-level build_result flag)."""
        source = self._read("web/extensions/toolkit_module_finisher.py")
        # The finisher imports the helper API.
        self.assertIn("load_final_reconciliation_report", source)
        self.assertIn("is_final_reconciliation_accepted", source)
        # And invokes it on module_dir.
        self.assertIn(
            "recon_report = load_final_reconciliation_report(module_dir)",
            source,
            "finisher must load final_reconciliation_report.json from "
            "module_dir (not from a top-level build_result flag)",
        )
        # And pins the accepted metadata into compose_report_agreement.
        self.assertIn(
            "final_reconciliation_accepted=final_rec_accepted",
            source,
            "finisher must forward final_reconciliation_accepted to "
            "compose_report_agreement",
        )
        self.assertIn(
            "source_fidelity_effective_status=sfe_status",
            source,
            "finisher must forward source_fidelity_effective_status to "
            "compose_report_agreement",
        )

    def test_finisher_never_assigns_clean_pass_in_source_fidelity_effective(self):
        """The finisher must never hard-assign
        ``source_fidelity_effective_status = "pass"``."""
        source = self._read("web/extensions/toolkit_module_finisher.py")
        for forbidden in (
            '["source_fidelity_effective_status"] = "pass"',
            "['source_fidelity_effective_status'] = 'pass'",
        ):
            self.assertNotIn(forbidden, source)

    def test_finisher_uses_persisted_report_not_build_result_flag(self):
        """Step 5.2 contract: the finisher's reconciliation facts come
        from the persisted ``final_reconciliation_report.json`` (read
        inside the function from module_dir), NOT from a top-level
        build_result flag passed in by the caller.

        The Step 5.1 packet builder path MAY set
        ``build_result["final_reconciliation_accepted"] = True`` as
        metadata, but the finisher does NOT consume that flag - it
        re-loads the persisted report and asks the legacy oracle
        ``is_final_reconciliation_accepted(...)`` whether the report is
        accepted. This protects against top-level build_result flag
        drift (e.g. a build_result in memory with the flag set but the
        on-disk report missing or corrupt)."""
        source = self._read("web/extensions/toolkit_module_finisher.py")
        # The stage function receives module_dir, not build_result.
        self.assertIn("module_dir", source)
        # And reads the report through the legacy oracle.
        self.assertIn("is_final_reconciliation_accepted(recon_report)", source)
        # The accepted flag is sourced from the report, not build_result.
        # Pin: the stage must NOT pin ``final_rec_accepted = True`` from
        # anything other than the legacy oracle's verdict.
        helper_block_idx = source.find("is_final_reconciliation_accepted(recon_report)")
        helper_block = source[helper_block_idx:helper_block_idx + 800]
        self.assertIn(
            "final_rec_accepted = True",
            helper_block,
            "finisher must set final_rec_accepted=True ONLY after the "
            "legacy oracle marks the persisted report as accepted",
        )
        self.assertNotIn(
            'final_rec_accepted = build_result.get(',
            helper_block,
            "finisher must NOT source final_rec_accepted from a "
            "top-level build_result flag (Step 5.2 contract)",
        )

    def test_finisher_consumes_accepted_report_in_actual_run(self):
        """End-to-end: when a module has an accepted
        ``final_reconciliation_report.json`` on disk, the finisher
        surfaces the accepted metadata + reconciled_degraded effective
        source fidelity in the published build report. (Mirrors the
        Step 6.1 happy path test, but added here under Step 5.2 to lock
        down the post-gate consumption.)"""
        import os
        import web.extensions.toolkit_module_finisher as finisher

        orig_continuity = finisher._run_continuity_stage
        orig_registry = finisher._run_registry_stage
        orig_materialization = finisher._run_monster_materialization_stage
        orig_publishability = finisher._run_publishability_stage
        orig_semantic_auth = finisher._run_semantic_authority_stage
        orig_safe_write = finisher.safe_write_json

        def _force_success_safe_write(path, data, **kw):
            orig_safe_write(path, data, **kw)
            return True

        temp_dir = tempfile.TemporaryDirectory()
        old_cwd = Path.cwd()
        try:
            repo_root = Path(temp_dir.name)
            os.chdir(repo_root)
            module_dir = repo_root / "modules" / "Step52FinisherConsumeTest"
            module_dir.mkdir(parents=True, exist_ok=True)
            (module_dir / "module_context.json").write_text("{}", encoding="utf-8")
            (module_dir / "module_context_BU.json").write_text("{}", encoding="utf-8")
            (module_dir / "module_plot.json").write_text("{}", encoding="utf-8")
            (module_dir / "module_plot_BU.json").write_text("{}", encoding="utf-8")
            (module_dir / "validation_report.json").write_text(
                json.dumps({"summary": {"total_failed": 0}}), encoding="utf-8"
            )
            (module_dir / "source_fidelity_report.json").write_text(
                json.dumps({"source_fidelity_status": "blocked"}), encoding="utf-8"
            )
            (module_dir / "final_reconciliation_report.json").write_text(
                json.dumps({
                    "version": "accurate_ingest_final_reconciliation_report.v1",
                    "status": "accepted",
                    "reconciliation_status": "accepted",
                    "source_fidelity_effective_status": "reconciled_degraded",
                    "playable_publication_candidate": True,
                    "decisions": [{"decision": "delete_bogus_atom"}],
                }),
                encoding="utf-8",
            )

            finisher._run_continuity_stage = lambda *a, **kw: {"status": "success"}
            finisher._run_registry_stage = lambda *a, **kw: {"status": "success"}
            finisher._run_monster_materialization_stage = (
                lambda *a, **kw: {"status": "success"}
            )
            finisher._run_publishability_stage = lambda *a, **kw: {
                "status": "success",
                "ready_status": "pass",
                "publishable_status": "pass",
                "report": {
                    "source_fidelity_status": "blocked",
                    "source_fidelity_categories": [],
                    "ready_status": "pass",
                    "publishable_status": "pass",
                    "effective_publishable_status": "pass",
                },
            }
            finisher._run_semantic_authority_stage = (
                lambda *a, **kw: {
                    "status": "success",
                    "changed": False,
                    "semantic_authority": {},
                    "warnings": [],
                    "errors": [],
                }
            )
            finisher.safe_write_json = _force_success_safe_write

            try:
                import scripts.audit_module_publishability as sap
                orig_sf = sap._build_source_fidelity_report_artifact
                sap._build_source_fidelity_report_artifact = (
                    lambda module_slug, module_path, publishability_report: {
                        "source_fidelity_status": "blocked",
                        "module": module_slug,
                    }
                )
            except Exception:
                orig_sf = None

            import model_config
            orig_llm = model_config.ENABLE_LLM_CLASSIFICATION
            model_config.ENABLE_LLM_CLASSIFICATION = False

            try:
                result = finisher.run_toolkit_module_postbuild_finishing(
                    "Step52FinisherConsumeTest", strict=True
                )
                # Step 5.2 contract: the finisher surfaces the accepted
                # metadata and the reconciled_degraded effective source
                # fidelity in the result, even though the raw
                # source_fidelity_status was "blocked".
                self.assertTrue(
                    result.get("final_reconciliation_accepted"),
                    "finisher must surface final_reconciliation_accepted=True "
                    "when the on-disk report is accepted",
                )
                self.assertEqual(
                    result.get("source_fidelity_effective_status"),
                    "reconciled_degraded",
                    "finisher must surface source_fidelity_effective_status="
                    "reconciled_degraded when an accepted report is on disk",
                )
                self.assertEqual(
                    result.get("final_reconciliation_status"),
                    "accepted",
                )
            finally:
                model_config.ENABLE_LLM_CLASSIFICATION = orig_llm
                if orig_sf is not None:
                    try:
                        import scripts.audit_module_publishability as sap
                        sap._build_source_fidelity_report_artifact = orig_sf
                    except Exception:
                        pass
        finally:
            finisher._run_continuity_stage = orig_continuity
            finisher._run_registry_stage = orig_registry
            finisher._run_monster_materialization_stage = orig_materialization
            finisher._run_publishability_stage = orig_publishability
            finisher._run_semantic_authority_stage = orig_semantic_auth
            finisher.safe_write_json = orig_safe_write
            os.chdir(old_cwd)
            temp_dir.cleanup()


if __name__ == "__main__":
    unittest.main()
