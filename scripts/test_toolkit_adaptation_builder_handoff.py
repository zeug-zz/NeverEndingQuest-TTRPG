# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free tests for the task 3.1 adaptation builder handoff."""

from contextlib import ExitStack
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import web.extensions.toolkit_homebrew_packet_builder as packet_builder
from utils.toolkit_adaptation_dossier import ADAPTATION_MODE_LLM
from utils.toolkit_adaptation_staging import cleanup_adaptation_staging_target
from web.extensions.toolkit_homebrew_packet_builder import (
    _execute_module_builder,
    _adaptation_failure_classification,
    build_llm_adaptation_handoff,
    run_toolkit_homebrew_packet_build,
)
from core.generators.module_builder import BuilderConfig, ModuleBuilder


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = REPO_ROOT / "scripts" / "fixtures"
DOSSIER_PATH = FIXTURE_DIR / "toolkit_adaptation_dossier_valid.json"
CATALOGUE_PATH = FIXTURE_DIR / "toolkit_adaptation_catalogue.md"


def _load_dossier():
    with DOSSIER_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _builder_input(llm_adaptation):
    return {
        "build_mode": ADAPTATION_MODE_LLM,
        "builder_narrative": "Build the adapted Lantern Market module.",
        "derived_builder_parameters": {
            "module_name": "Lantern_Market",
            "num_areas": 1,
            "locations_per_area": 3,
            "output_directory": "./modules/Lantern_Market",
        },
        "llm_adaptation": llm_adaptation,
    }


class TestAdaptationBuilderHandoff(unittest.TestCase):
    """The adaptation boundary is validated and remains distinct from locks."""

    def test_valid_dossier_becomes_bounded_provenance_envelope(self):
        dossier = _load_dossier()
        handoff = build_llm_adaptation_handoff(
            dossier,
            {
                "attempt_id": "adaptation-fixture-1",
                "source_path": "scripts/fixtures/toolkit_adaptation_catalogue.md",
                "model_metadata": {
                    "provider": "fixture",
                    "model": "mock-adaptation-model",
                    "ignored": "not copied",
                },
            },
        )

        self.assertEqual(handoff["dossier"]["adaptation_mode"], ADAPTATION_MODE_LLM)
        self.assertEqual(handoff["dossier"]["source_profile"], "catalogue")
        self.assertEqual(handoff["provenance"]["attempt_id"], "adaptation-fixture-1")
        self.assertEqual(
            handoff["provenance"]["model_metadata"],
            {"provider": "fixture", "model": "mock-adaptation-model"},
        )
        self.assertNotIn("ignored", handoff["provenance"].get("model_metadata", {}))
        self.assertNotIn("source_location_names", handoff)
        self.assertNotIn("source_puzzle_ids", handoff)
        self.assertNotIn("source_tone", handoff)

    def test_provider_provenance_cannot_elevate_canonical_generation(self):
        dossier = _load_dossier()
        with patch(
            "model_config.ENABLE_LLM_ADAPTATION_CANONICAL_MONSTER_GENERATION",
            False,
        ):
            handoff = build_llm_adaptation_handoff(
                {"dossier": dossier, "provenance": {"allow_canonical_monster_generation": True}}
            )
        self.assertNotIn(
            "allow_canonical_monster_generation",
            handoff["provenance"],
        )

    def test_operator_true_is_copied_into_python_owned_provenance(self):
        dossier = _load_dossier()
        with patch(
            "model_config.ENABLE_LLM_ADAPTATION_CANONICAL_MONSTER_GENERATION",
            True,
        ):
            handoff = build_llm_adaptation_handoff(dossier)
        self.assertIs(
            handoff["provenance"]["allow_canonical_monster_generation"],
            True,
        )

    def test_malformed_dossier_is_rejected_before_handoff(self):
        malformed = _load_dossier()
        malformed.pop("areas")

        with self.assertRaisesRegex(ValueError, "llm_adaptation_dossier_invalid"):
            build_llm_adaptation_handoff(malformed)

    @patch("core.generators.module_builder.ModuleGenerator")
    @patch("core.generators.module_builder.PlotGenerator")
    @patch("core.generators.module_builder.LocationGenerator")
    @patch("core.generators.module_builder.AreaGenerator")
    def test_module_builder_stores_adaptation_without_source_lock(
        self, mock_area_gen, mock_location_gen, mock_plot_gen, mock_module_gen
    ):
        with tempfile.TemporaryDirectory(
            dir=str(REPO_ROOT / "tmp"), prefix="toolkit_adaptation_builder_"
        ) as tmpdir:
            builder = ModuleBuilder(
                BuilderConfig(
                    module_name="Lantern_Market",
                    output_directory=tmpdir,
                    verbose=False,
                )
            )
            builder.module_gen = MagicMock()
            builder.module_gen.generate_module.return_value = {
                "moduleName": "Lantern Market",
                "moduleDescription": "A market adaptation.",
                "worldMap": [],
            }
            builder.generate_areas = MagicMock()
            builder.generate_locations = MagicMock()
            builder.generate_plots = MagicMock()
            builder.create_party_tracker = MagicMock()
            builder.create_module_summary = MagicMock()
            builder.validate_module = MagicMock()
            builder.create_bu_backups = MagicMock()

            handoff = build_llm_adaptation_handoff(_load_dossier())
            builder.build_module(
                "Build the market.\n\n=== SOURCE LOCK CONTEXT ===\n"
                "LOCATIONS: Hooded Lantern, Black Lantern",
                llm_adaptation=handoff,
            )

            self.assertEqual(builder.build_mode, ADAPTATION_MODE_LLM)
            self.assertEqual(builder.llm_adaptation, handoff)
            self.assertEqual(builder.source_lock_context, "")
            self.assertNotIn("SOURCE LOCK CONTEXT", builder.context_header)

    @patch("core.generators.module_builder.ModuleBuilder")
    @patch("core.generators.module_builder.BuilderConfig")
    def test_execute_passes_adaptation_without_source_lock_context(
        self, mock_config, mock_builder_cls
    ):
        mock_builder = MagicMock()
        mock_builder_cls.return_value = mock_builder
        handoff = build_llm_adaptation_handoff(_load_dossier())
        builder_input = _builder_input(handoff)

        with patch(
            "web.extensions.toolkit_homebrew_packet_builder._build_module_builder_source_context",
            side_effect=AssertionError("adaptation must not use source-lock context"),
        ):
            _execute_module_builder(builder_input)

        mock_config.assert_called_once()
        self.assertEqual(mock_config.call_args.kwargs["build_mode"], ADAPTATION_MODE_LLM)
        mock_builder.build_module.assert_called_once_with(
            builder_input["builder_narrative"],
            llm_adaptation=handoff,
        )

    @patch("core.generators.module_builder.ModuleBuilder")
    @patch("core.generators.module_builder.BuilderConfig")
    def test_execute_legacy_direct_builder_omits_adaptation_kwargs(
        self, mock_config, mock_builder_cls
    ):
        """Legacy ModuleBuilder calls keep their original positional shape."""
        mock_builder = MagicMock()
        mock_builder_cls.return_value = mock_builder
        builder_input = {
            "build_mode": "source_enhanced_modulebuilder",
            "builder_narrative": "Build the legacy lighthouse module.",
            "derived_builder_parameters": {
                "module_name": "Legacy_Lighthouse",
                "num_areas": 1,
                "locations_per_area": 3,
                "output_directory": "./modules/Legacy_Lighthouse",
            },
        }

        _execute_module_builder(builder_input)

        mock_config.assert_called_once()
        config_kwargs = mock_config.call_args.kwargs
        self.assertEqual(config_kwargs["build_mode"], "source_enhanced_modulebuilder")
        self.assertIsNone(config_kwargs["llm_timeout_seconds"])
        mock_builder.build_module.assert_called_once_with(
            builder_input["builder_narrative"]
        )
        self.assertEqual(mock_builder.build_module.call_args.kwargs, {})

    @patch("core.generators.module_builder.ModuleBuilder")
    @patch("core.generators.module_builder.BuilderConfig")
    def test_catalogue_item_headings_are_not_promoted_to_locations(
        self, mock_config, mock_builder_cls
    ):
        mock_builder = MagicMock()
        mock_builder_cls.return_value = mock_builder
        dossier = _load_dossier()
        handoff = build_llm_adaptation_handoff(
            dossier,
            {"source_path": "scripts/fixtures/toolkit_adaptation_catalogue.md"},
        )
        builder_input = _builder_input(handoff)

        # These are source headings, not authored adaptation locations. The
        # adaptation handoff must not reconstruct legacy location locks from
        # the catalogue or its extracted item evidence.
        item_headings = {"Hooded Lantern", "Black Lantern"}
        location_names = {
            location["name"]
            for area in handoff["dossier"]["areas"]
            for location in area["location_seeds"]
        }
        self.assertEqual(location_names, {"Lantern Market Gate", "Lanternwright Stall"})
        self.assertTrue(item_headings.isdisjoint(location_names))
        self.assertNotIn("source_location_names", builder_input)
        self.assertNotIn("source_npc_names", builder_input)
        self.assertNotIn("source_puzzle_ids", builder_input)
        self.assertNotIn("source_tone", builder_input)

        with patch(
            "web.extensions.toolkit_homebrew_packet_builder._build_module_builder_source_context",
            side_effect=AssertionError("catalogue adaptation must not use source locks"),
        ):
            _execute_module_builder(builder_input)

        call_kwargs = mock_builder.build_module.call_args.kwargs
        self.assertEqual(call_kwargs["llm_adaptation"]["dossier"]["source_profile"], "catalogue")
        self.assertNotIn("SOURCE_LOCKS", json.dumps(call_kwargs, sort_keys=True))
        self.assertIn("catalogue", CATALOGUE_PATH.read_text(encoding="utf-8").lower())

    @patch("model_config.ENABLE_LLM_ADAPTATION_CANONICAL_MONSTER_GENERATION", True)
    @patch("web.extensions.toolkit_homebrew_packet_builder.ENABLE_LLM_ADAPTATION", True)
    def test_packet_builder_persists_distinct_adaptation_input(self):
        dossier = _load_dossier()
        captured = []

        with tempfile.TemporaryDirectory(
            dir=str(REPO_ROOT / "tmp"), prefix="toolkit_adaptation_builder_"
        ) as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            workspace.mkdir(parents=True, exist_ok=True)
            source_hash = dossier["source_hash"]
            (workspace / "normalized_packet.json").write_text(
                json.dumps(
                    {
                        "packet_version": "packet.v1",
                        "name": "catalogue-fixture",
                        "title": "Lantern Market",
                        "description": "A catalogue adaptation fixture.",
                        "source_hash": source_hash,
                        "source_rights": "user_authored",
                        "normalization_state": "normalized",
                    }
                ),
                encoding="utf-8",
            )
            (workspace / "ui_review_snapshot.json").write_text(
                json.dumps(
                    {
                        "decision": "approve",
                        "recorded_at": "2026-01-01T00:00:00Z",
                        "job_id": "catalogue-handoff",
                        "packet_identity": {"source_hash": source_hash},
                    }
                ),
                encoding="utf-8",
            )
            (workspace / "builder_narrative.txt").write_text(
                "Build a shop-centered adaptation.",
                encoding="utf-8",
            )

            def capture(builder_input):
                captured.append(builder_input)

            guardrail_report = {
                "version": "toolkit_adaptation_monster_guardrail.v1",
                "report_version": "toolkit_adaptation_monster_guardrail.v1",
                "status": "pass",
                "monsters_unresolved": 0,
                "encounters_unresolved": 0,
                "encounters_unbound": 0,
                "unresolved_refs": [],
            }
            with patch(
                "utils.toolkit_adaptation_monster_guardrail.build_adaptation_monster_guardrail_report",
                return_value=guardrail_report,
            ) as guardrail, patch(
                "utils.monster_reference_closure.ensure_monster_reference_closure",
                return_value={"required": 0, "existing_before": 0, "generated": 0, "unresolved": 0},
            ) as closure, patch(
                "utils.spatial_repair.repair_module_spatial",
                return_value={"status": "pass", "input_location_count": 0},
            ), patch(
                "utils.calendar_normalization.normalize_party_calendar",
                return_value={"status": "pass"},
            ):
                result = run_toolkit_homebrew_packet_build(
                    workspace,
                    "catalogue-handoff",
                    builder_executor=capture,
                    adaptation_route=ADAPTATION_MODE_LLM,
                    adaptation_dossier=dossier,
                    adaptation_staging_root="tmp/toolkit_adaptation_builder_handoff",
                )

            if isinstance(result.get("staging_target"), dict):
                cleanup_adaptation_staging_target(result["staging_target"])

            self.assertTrue(captured)
            builder_input = captured[0]
            guardrail.assert_called_once()
            closure.assert_called_once()
            self.assertIs(closure.call_args.kwargs["allow_generation"], False)
            self.assertEqual(guardrail.call_args.args[0], builder_input["llm_adaptation"])
            self.assertEqual(
                guardrail.call_args.kwargs["staging_root"],
                str(Path(result["output_directory"]).resolve()),
            )
            # Canonical generation is an explicit operator rollout.  The
            # disabled contract is covered separately by the provenance test;
            # this adaptation staging test proves the enabled handoff reaches
            # the guardrail without changing legacy closure behavior.
            self.assertIs(guardrail.call_args.kwargs["allow_generation"], True)
            self.assertTrue(
                guardrail.call_args.kwargs["monster_builder_path"].endswith(
                    "core/generators/monster_builder.py"
                )
            )
            self.assertEqual(
                guardrail.call_args.kwargs["generation_timeout_seconds"], 120
            )
            self.assertEqual(result["adaptation_monster_guardrail"], guardrail_report)
            persisted_build_result = json.loads(
                (workspace / "build_result.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                persisted_build_result["adaptation_monster_guardrail"],
                guardrail_report,
            )
            self.assertEqual(result["build_mode"], ADAPTATION_MODE_LLM)
            self.assertEqual(builder_input["build_mode"], ADAPTATION_MODE_LLM)
            self.assertEqual(
                builder_input["llm_adaptation"]["dossier"]["source_profile"],
                "catalogue",
            )
            for legacy_field in (
                "source_npc_names",
                "source_location_names",
                "source_puzzle_ids",
                "source_tone",
                "blueprint",
            ):
                self.assertNotIn(legacy_field, builder_input)
            persisted = json.loads((workspace / "builder_input.json").read_text(encoding="utf-8"))
            self.assertEqual(persisted["build_mode"], ADAPTATION_MODE_LLM)
            self.assertEqual(persisted["llm_adaptation"], builder_input["llm_adaptation"])

    @patch("web.extensions.toolkit_homebrew_packet_builder.ENABLE_LLM_ADAPTATION", True)
    def test_packet_builder_materializes_post_normalization_ref_before_final_closure(self):
        """Generated area refs are materialized before the no-generation closure."""
        dossier = _load_dossier()
        dossier["encounter_seeds"][0]["adversaries"] = []
        calls = []

        with tempfile.TemporaryDirectory(
            dir=str(REPO_ROOT / "tmp"), prefix="toolkit_adaptation_builder_generated_"
        ) as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            workspace.mkdir(parents=True, exist_ok=True)
            source_hash = dossier["source_hash"]
            (workspace / "normalized_packet.json").write_text(
                json.dumps({
                    "packet_version": "packet.v1", "name": "generated-fixture",
                    "title": "Lantern Market", "description": "Fixture",
                    "source_hash": source_hash, "source_rights": "user_authored",
                    "normalization_state": "normalized",
                }), encoding="utf-8"
            )
            (workspace / "ui_review_snapshot.json").write_text(
                json.dumps({
                    "decision": "approve", "recorded_at": "2026-01-01T00:00:00Z",
                    "job_id": "generated-ref", "packet_identity": {"source_hash": source_hash},
                }), encoding="utf-8"
            )
            (workspace / "builder_narrative.txt").write_text(
                "Build the generated-ref adaptation.", encoding="utf-8"
            )

            def normalize(staging_root, _dossier, **_kwargs):
                calls.append("normalize")
                area = Path(staging_root) / "areas" / "A001.json"
                area.parent.mkdir(parents=True, exist_ok=True)
                area.write_text(json.dumps({
                    "areaId": "A001", "locations": [{
                        "locationId": "A01", "name": "Gate",
                        "monsters": [{"name": "Generated Canonical Beast"}],
                    }],
                }), encoding="utf-8")
                return {
                    "version": "toolkit_adaptation_monster_guardrail.v1",
                    "status": "pass", "areas_scanned": 1, "locations_scanned": 1,
                    "entries_seen": 1, "normalized_refs": ["Generated Canonical Beast"],
                    "excluded_entries": [], "unresolved_entries": [],
                    "diagnostics": [], "files_changed": [str(area)],
                }

            def fake_guardrail(_input, **kwargs):
                calls.append("materialize")
                self.assertEqual(
                    kwargs["additional_canonical_refs"],
                    ["Generated Canonical Beast"],
                )
                output = Path(kwargs["staging_root"])
                target = output / "monsters" / "generated_canonical_beast.json"
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps({
                    "name": "Generated Canonical Beast", "size": "Medium",
                    "alignment": "neutral", "armorClass": 12,
                }), encoding="utf-8")
                return {
                    "version": "toolkit_adaptation_monster_guardrail.v1",
                    "report_version": "toolkit_adaptation_monster_guardrail.v1",
                    "status": "pass", "monsters_planned": 1,
                    "monsters_reused": 0, "monsters_generated": 1,
                    "monsters_unresolved": 0, "unresolved_refs": [],
                    "unresolved_diagnostics": [], "diagnostics": [],
                    "resolution_diagnostics": [],
                }

            def closure(module_name, module_dir, **kwargs):
                calls.append("closure")
                self.assertFalse(kwargs["allow_generation"])
                self.assertTrue(
                    (Path(module_dir) / "monsters" / "generated_canonical_beast.json").is_file()
                )
                return {"required": 1, "existing_before": 1, "generated": 0, "unresolved": 0}

            with patch(
                "utils.toolkit_adaptation_monster_guardrail.normalize_adaptation_module_monsters",
                side_effect=normalize,
            ), patch(
                "utils.toolkit_adaptation_monster_guardrail.build_adaptation_monster_guardrail_report",
                side_effect=fake_guardrail,
            ), patch(
                "utils.monster_reference_closure.ensure_monster_reference_closure",
                side_effect=closure,
            ) as closure_mock, patch(
                "utils.spatial_repair.repair_module_spatial",
                return_value={"status": "pass", "input_location_count": 1},
            ), patch(
                "utils.calendar_normalization.normalize_party_calendar",
                return_value={"status": "pass"},
            ):
                result = run_toolkit_homebrew_packet_build(
                    workspace, "generated-ref", builder_executor=lambda _input: None,
                    adaptation_route=ADAPTATION_MODE_LLM,
                    adaptation_dossier=dossier,
                    adaptation_staging_root="tmp/toolkit_adaptation_builder_generated",
                )

            if isinstance(result.get("staging_target"), dict):
                cleanup_adaptation_staging_target(result["staging_target"])

            # The fixture intentionally omits the full module artifact set, so
            # later readiness/build gates may block.  The relevant contract is
            # that the adaptation monster stages complete and normal gates are
            # reached rather than stopping at the monster guardrail.
            self.assertNotEqual(result.get("stage"), "adaptation_monster_guardrail")
            self.assertNotEqual(result.get("stage"), "adaptation_monster_normalization")
            self.assertEqual(calls, ["normalize", "materialize", "closure"])
            closure_mock.assert_called_once()
            self.assertEqual(
                result["adaptation_monster_materialization"]["monsters_generated"], 1
            )

    def test_module_builder_climactic_area_write_is_filepath_first(self):
        source = Path("core/generators/module_builder.py").read_text(encoding="utf-8")
        self.assertIn("safe_write_json(area_file_path, area_data)", source)
        self.assertNotIn("safe_write_json(area_data, area_file_path)", source)

    def test_guardrail_hook_is_adaptation_only_and_precedes_closure(self):
        source = Path(packet_builder.__file__).read_text(encoding="utf-8")
        guardrail_gate = "if _is_adaptation_build and _build_mode == ADAPTATION_MODE_LLM:"
        self.assertIn(guardrail_gate, source)
        self.assertIn('build_result["adaptation_monster_guardrail"]', source)
        self.assertLess(
            source.index("build_adaptation_monster_guardrail_report"),
            source.index("ensure_monster_reference_closure"),
        )
        self.assertIn("normalize_adaptation_module_monsters", source)
        self.assertLess(
            source.index("normalize_adaptation_module_monsters"),
            source.index("ensure_monster_reference_closure"),
        )
        self.assertIn("staging_root=_module_dir_str", source)
        self.assertIn("allow_generation=False", source)

    def test_adaptation_skips_legacy_generator_closure_but_legacy_keeps_it(self):
        builder_source = Path(ModuleBuilder.__module__.replace(".", "/") + ".py")
        generator_source = Path(
            "core/generators/module_generator.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "self.module_gen.adaptation_mode = self.llm_adaptation is not None",
            builder_source.read_text(encoding="utf-8"),
        )
        self.assertIn(
            'if getattr(self, "adaptation_mode", False):',
            generator_source,
        )
        self.assertIn(
            "closure_report = self._ensure_monster_reference_closure",
            generator_source,
        )
        self.assertLess(
            generator_source.index('if getattr(self, "adaptation_mode", False):'),
            generator_source.index("closure_report = self._ensure_monster_reference_closure"),
        )
    @patch("web.extensions.toolkit_homebrew_packet_builder.ENABLE_LLM_ADAPTATION", True)
    def test_terminal_guardrail_blocks_before_legacy_closure(self):
        dossier = _load_dossier()
        with tempfile.TemporaryDirectory(
            dir=str(REPO_ROOT / "tmp"), prefix="toolkit_adaptation_guardrail_block_"
        ) as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            workspace.mkdir(parents=True, exist_ok=True)
            source_hash = dossier["source_hash"]
            (workspace / "normalized_packet.json").write_text(
                json.dumps(
                    {
                        "packet_version": "packet.v1",
                        "name": "catalogue-fixture",
                        "title": "Lantern Market",
                        "description": "A catalogue adaptation fixture.",
                        "source_hash": source_hash,
                        "source_rights": "user_authored",
                        "normalization_state": "normalized",
                    }
                ),
                encoding="utf-8",
            )
            (workspace / "ui_review_snapshot.json").write_text(
                json.dumps(
                    {
                        "decision": "approve",
                        "recorded_at": "2026-01-01T00:00:00Z",
                        "job_id": "guardrail-block",
                        "packet_identity": {"source_hash": source_hash},
                    }
                ),
                encoding="utf-8",
            )
            (workspace / "builder_narrative.txt").write_text(
                "Build a shop-centered adaptation.", encoding="utf-8"
            )

            with patch(
                "utils.toolkit_adaptation_monster_guardrail.build_adaptation_monster_guardrail_report",
                return_value={
                    "version": "toolkit_adaptation_monster_guardrail.v1",
                    "report_version": "toolkit_adaptation_monster_guardrail.v1",
                    "status": "blocked",
                    "monsters_unresolved": 1,
                    "unresolved_refs": ["Missing Beast"],
                    "provider_payload": "must not enter build_result",
                },
            ), patch(
                "utils.monster_reference_closure.ensure_monster_reference_closure"
            ) as closure:
                result = run_toolkit_homebrew_packet_build(
                    workspace,
                    "guardrail-block",
                    builder_executor=lambda _builder_input: None,
                    adaptation_route=ADAPTATION_MODE_LLM,
                    adaptation_dossier=dossier,
                    adaptation_staging_root="tmp/toolkit_adaptation_guardrail_block",
                )

            if isinstance(result.get("staging_target"), dict):
                cleanup_adaptation_staging_target(result["staging_target"])

            self.assertEqual(result["status"], "blocked")
            self.assertEqual(result["stage"], "adaptation_monster_guardrail")
            self.assertEqual(
                result["adaptation_monster_guardrail"]["status"], "blocked"
            )
            self.assertNotIn(
                "provider_payload",
                json.dumps(result["adaptation_monster_guardrail"], sort_keys=True),
            )
            closure.assert_not_called()


class TestAdaptationEarlyFailurePersistence(unittest.TestCase):
    """Every pre-readiness adaptation blocker leaves a current result."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(
            dir=str(REPO_ROOT / "tmp"), prefix="toolkit_adaptation_persistence_"
        )
        self.addCleanup(self.tmp.cleanup)
        self.workspace = Path(self.tmp.name) / "workspace"
        self.workspace.mkdir(parents=True, exist_ok=True)
        dossier = _load_dossier()
        packet = {
            "packet_version": "packet.v1",
            "name": "catalogue-fixture",
            "title": "Lantern Market",
            "description": "A catalogue adaptation fixture.",
            "source_hash": dossier["source_hash"],
            "source_rights": "user_authored",
            "normalization_state": "normalized",
        }
        (self.workspace / "normalized_packet.json").write_text(
            json.dumps(packet), encoding="utf-8"
        )
        (self.workspace / "ui_review_snapshot.json").write_text(
            json.dumps(
                {
                    "decision": "approve",
                    "recorded_at": "2026-01-01T00:00:00Z",
                    "job_id": "early-failure-persistence",
                    "packet_identity": {"source_hash": dossier["source_hash"]},
                }
            ),
            encoding="utf-8",
        )
        (self.workspace / "builder_narrative.txt").write_text(
            "Build the adapted market.", encoding="utf-8"
        )
        # A prior attempt's compatibility report must never survive as the
        # visible current result when the new attempt blocks early.
        (self.workspace / "build_result.json").write_text(
            json.dumps(
                {
                    "status": "blocked",
                    "stage": "stale_prior_stage",
                    "error": "stale_prior_failure",
                }
            ),
            encoding="utf-8",
        )
        self.dossier = dossier
        self.staging_root = (
            "tmp/toolkit_adaptation_early_failure_persistence/"
            + Path(self.tmp.name).name
            + "/staging"
        )

    def _run(self, failure: str):
        pass_guardrail = {
            "version": "toolkit_adaptation_monster_guardrail.v1",
            "report_version": "toolkit_adaptation_monster_guardrail.v1",
            "status": "pass",
            "monsters_unresolved": 0,
            "encounters_unresolved": 0,
            "encounters_unbound": 0,
            "unresolved_refs": [],
        }
        pass_normalization = {
            "version": "toolkit_adaptation_monster_guardrail.v1",
            "status": "pass",
        }
        pass_closure = {
            "required": 0,
            "existing_before": 0,
            "generated": 0,
            "unresolved": 0,
        }
        with ExitStack() as stack:
            stack.enter_context(
                patch.object(packet_builder, "ENABLE_LLM_ADAPTATION", True)
            )
            stack.enter_context(
                patch(
                    "utils.toolkit_adaptation_monster_guardrail.build_adaptation_monster_guardrail_report",
                    return_value=(
                        {
                            **pass_guardrail,
                            "status": "blocked",
                            "monsters_unresolved": 1,
                            "unresolved_refs": ["Missing Beast"],
                        }
                        if failure == "guardrail"
                        else pass_guardrail
                    ),
                )
            )
            stack.enter_context(
                patch(
                    "utils.toolkit_adaptation_monster_guardrail.normalize_adaptation_module_monsters",
                    return_value=(
                        {
                            **pass_normalization,
                            "status": "blocked",
                            "diagnostics": [{"code": "ambiguous_monster_phrase"}],
                        }
                        if failure == "normalization"
                        else pass_normalization
                    ),
                )
            )
            stack.enter_context(
                patch(
                    "utils.monster_reference_closure.ensure_monster_reference_closure",
                    return_value=(
                        {**pass_closure, "unresolved": 1}
                        if failure == "closure"
                        else pass_closure
                    ),
                )
            )
            stack.enter_context(
                patch(
                    "utils.spatial_repair.repair_module_spatial",
                    return_value={"status": "pass"},
                )
            )
            stack.enter_context(
                patch(
                    "utils.calendar_normalization.normalize_party_calendar",
                    return_value={"status": "pass"},
                )
            )
            if failure == "builder_input":
                stack.enter_context(
                    patch.object(
                        packet_builder,
                        "persist_builder_input_artifact",
                        return_value=False,
                    )
                )
            result = run_toolkit_homebrew_packet_build(
                self.workspace,
                "early-failure-persistence",
                builder_executor=lambda _builder_input: None,
                adaptation_route=ADAPTATION_MODE_LLM,
                adaptation_dossier=self.dossier,
                adaptation_provenance={
                    "attempt_id": "adaptation-persistence-1",
                    "source_path": "scripts/fixtures/toolkit_adaptation_catalogue.md",
                    "attempt_number": 1,
                    "revision_number": 0,
                },
                adaptation_staging_root=self.staging_root,
            )

        self.addCleanup(
            cleanup_adaptation_staging_target,
            result.get("staging_target") or {},
        )
        return result

    def _assert_current_artifacts(
        self,
        result,
        expected_stage,
        expected_error,
        expected_failure_class,
        expected_failure_code,
    ):
        self.assertEqual(result["stage"], expected_stage)
        self.assertEqual(result["error"], expected_error)
        if expected_failure_class:
            self.assertEqual(
                result["failure_classification"]["failure_class"],
                expected_failure_class,
            )
            self.assertEqual(
                result["failure_classification"]["code"], expected_failure_code
            )
        workspace_result = self.workspace / "build_result.json"
        self.assertTrue(workspace_result.is_file())
        current = json.loads(workspace_result.read_text(encoding="utf-8"))
        self.assertEqual(current["stage"], expected_stage)
        self.assertEqual(current["error"], expected_error)
        if expected_failure_class:
            self.assertEqual(
                current["failure_classification"]["failure_class"],
                expected_failure_class,
            )
            self.assertEqual(
                current["failure_classification"]["code"], expected_failure_code
            )
        self.assertNotEqual(current.get("error"), "stale_prior_failure")

        attempt_result = (
            self.workspace
            / "adaptation_attempts"
            / "adaptation-persistence-1"
            / "build_result.json"
        )
        self.assertTrue(attempt_result.is_file())
        artifact = json.loads(attempt_result.read_text(encoding="utf-8"))
        self.assertEqual(artifact["attempt_id"], "adaptation-persistence-1")
        self.assertEqual(artifact["revision_number"], 0)
        self.assertEqual(artifact["payload"]["gate_summary"]["stage"], expected_stage)
        self.assertEqual(artifact["payload"]["gate_summary"]["error"], expected_error)
        if expected_failure_class:
            self.assertEqual(
                artifact["payload"]["gate_summary"]["failure_classification"]["failure_class"],
                expected_failure_class,
            )

    def test_guardrail_block_persists_current_result(self):
        result = self._run("guardrail")
        self._assert_current_artifacts(
            result,
            "adaptation_monster_guardrail",
            "adaptation_monster_guardrail_unresolved",
            "semantic",
            "adaptation_monster_guardrail_unresolved",
        )

    def test_normalization_block_persists_current_result(self):
        result = self._run("normalization")
        self._assert_current_artifacts(
            result,
            "adaptation_monster_normalization",
            "adaptation_monster_normalization_blocked",
            "semantic",
            "adaptation_monster_normalization_blocked",
        )

    def test_closure_block_persists_current_result(self):
        result = self._run("closure")
        self._assert_current_artifacts(
            result,
            "monster_closure",
            "monster_closure_unresolved:1 unresolved monster reference(s)",
            "semantic",
            "monster_closure_unresolved",
        )

    def test_early_builder_block_persists_current_result(self):
        result = self._run("builder_input")
        self._assert_current_artifacts(
            result,
            "build",
            "builder_input_persist_failed",
            "",
            "",
        )


class TestAdaptationFailureClassification(unittest.TestCase):
    """Terminal monster blockers carry bounded provider-free classification."""

    _HANDOFF = {
        "provenance": {
            "attempt_id": "adaptation-classification-fixture",
            "revision_number": 0,
        }
    }

    def _assert_bounded_fields(self, result, *, stage, failure_class, code):
        classification = _adaptation_failure_classification(
            result,
            adaptation_handoff=self._HANDOFF,
        )
        self.assertIsNotNone(classification)
        self.assertEqual(classification["contract_version"], "toolkit_adaptation_failure_classification.v1")
        self.assertEqual(classification["failure_class"], failure_class)
        self.assertEqual(classification["failure_group"], "content" if failure_class == "semantic" else "infrastructure")
        self.assertEqual(classification["group"], classification["failure_group"])
        self.assertEqual(classification["code"], code)
        self.assertEqual(classification["stage"], stage)
        self.assertEqual(classification["failed_stage"], stage)
        self.assertIn(classification["classification_status"], {"blocked", "terminal"})
        self.assertIn("revision_eligible", classification)
        self.assertIn("revision_budget", classification)
        self.assertIn("decision", classification["revision_budget"])
        return classification

    def test_semantic_guardrail_failure_is_bounded_and_redacted(self):
        classification = self._assert_bounded_fields(
            {
                "status": "blocked",
                "stage": "adaptation_monster_guardrail",
                "error": "adaptation_monster_guardrail_unresolved",
                "adaptation_monster_guardrail": {
                    "status": "blocked",
                    "unresolved_diagnostics": [
                        {"reason": "ambiguous_canonical_match"}
                    ],
                },
            },
            stage="adaptation_monster_guardrail",
            failure_class="semantic",
            code="ambiguous_canonical_match",
        )
        serialized = json.dumps(classification, sort_keys=True)
        self.assertNotIn("raw_prompt", serialized)
        self.assertNotIn("raw_response", serialized)
        self.assertNotIn("api_key", serialized)

    def test_materialization_generation_failure_is_infrastructure(self):
        self._assert_bounded_fields(
            {
                "status": "blocked",
                "stage": "adaptation_monster_guardrail",
                "error": "adaptation_monster_guardrail_unresolved",
                "adaptation_monster_guardrail": {
                    "status": "degraded",
                    "resolution_diagnostics": [
                        {"status": "unresolved", "reason": "generation_builder_missing"}
                    ],
                },
            },
            stage="adaptation_monster_guardrail",
            failure_class="dependency",
            code="generation_builder_missing",
        )

    def test_normalization_write_failure_is_file_infrastructure(self):
        self._assert_bounded_fields(
            {
                "status": "blocked",
                "stage": "adaptation_monster_normalization",
                "error": "adaptation_monster_normalization_blocked",
                "adaptation_monster_normalization": {
                    "status": "blocked",
                    "diagnostics": [{"code": "area_atomic_write_failed"}],
                },
            },
            stage="adaptation_monster_normalization",
            failure_class="file",
            code="area_atomic_write_failed",
        )

    def test_closure_unresolved_failure_is_concrete_semantic_blocker(self):
        self._assert_bounded_fields(
            {
                "status": "blocked",
                "stage": "monster_closure",
                "error": "monster_closure_unresolved:2 unresolved monster references",
            },
            stage="monster_closure",
            failure_class="semantic",
            code="monster_closure_unresolved",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
