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

        # Stub non-publishability stages to succeed so only the
        # publishability report content drives the result.
        finisher._run_continuity_stage = lambda *a, **kw: {"status": "success"}
        finisher._run_registry_stage = lambda *a, **kw: {"status": "success"}
        finisher._run_monster_materialization_stage = lambda *a, **kw: {"status": "success"}

    def tearDown(self):
        finisher._run_continuity_stage = self.orig_continuity
        finisher._run_registry_stage = self.orig_registry
        finisher._run_monster_materialization_stage = self.orig_materialization
        finisher._run_publishability_stage = self.orig_publishability
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


if __name__ == "__main__":
    unittest.main()
