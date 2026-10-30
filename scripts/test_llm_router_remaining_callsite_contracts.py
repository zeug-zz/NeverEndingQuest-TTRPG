# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free request and caller contracts for migrated chat operations."""

import ast
import contextlib
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from typing import Any, Callable, Dict, List, Optional
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SCRIPTS_ROOT = ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from scripts.core_chat_test_safety import arm_process_tripwires

_TRIPWIRES = arm_process_tripwires()

import model_config
from core.generators import area_generator, location_generator, plot_generator, module_generator
from core.generators import monster_builder, npc_builder
from core.generators import module_stitcher, location_summarizer
from core.ai import (
    adv_summary,
    combat_compression_engine,
    cumulative_summary,
    incremental_compression,
    transition_validator,
)
from core.generators.module_builder import ModuleBuilder, parse_narrative_to_module_params
from core.memory import players_diary, session_diary, story_so_far_compiler
from core.validation import (
    character_effects_validator,
    character_validator,
    npc_codex_generator,
)
from utils import ai_client_factory, llm_router
from utils import toolkit_homebrew_normalizer, toolkit_llm_final_reconciliation
from utils import toolkit_adaptation_author, toolkit_adaptation_auditor
from utils import action_predictor, bestiary_updater, character_creation_audit
from utils.compression import ai_narrative_compressor_agentic, location_compressor
from utils.llm_runtime import make_legacy_receipt_observer
from utils.toolkit_homebrew_upload_contract import ensure_workspace_placeholders
from web.extensions import toolkit_adaptation_runtime, toolkit_llm_classification
from updates import plot_update, update_character_effects, update_character_info, update_encounter

with mock.patch.object(
    ai_client_factory,
    "create_chat_client",
    side_effect=AssertionError("utility owner constructed a provider client"),
) as _utility_import_client:
    from utils import (
        homebrewery_adventure_writer,
        level_up,
        npc_name_canonicalizer,
        npc_reconciler,
        prompt_sanitizer,
        quest_player_formatter,
        reconcile_location_state,
        spatial_contract,
        startup_wizard,
    )
    _utility_import_client.assert_not_called()

# Keep manager imports provider-free while retaining the no-constructor guard.
with mock.patch.object(ai_client_factory, "create_chat_client", return_value=mock.Mock()):
    from core.managers import campaign_manager, level_up_manager, storage_processor


# SHA-256 fingerprints of the exact messages captured from the pre-migration
# raw-client requests for the fixtures below.
PRE_MIGRATION_MESSAGE_DIGESTS = {
    "toolkit_adaptation_author": "52a0362032bbe83b52a51a3af2bd41018405236be3dbe2899b94d706ae870f82",
    "toolkit_adaptation_auditor": "91923963522d64ed1946a4a11fd59799393d30f34a9f86dd37a8222526cf31ad",
    "toolkit_adaptation_convergence": "7e677c2153c4aea230b5fd8b020705c779f9b2851878af8c3e0509173d158d79",
    "action_prediction": "f8e9d689d107a5ffa4c64f957e36ce39d1907d38d331b3f6495ea0b1796eaf14",
    "bestiary_updater": "e20d0ac241e6a2b4fba66ac56c7e123f189b6ec6d3b9c525846d868593d724be",
    "character_creation_audit": "46c33726fec4ccc04dabbbf7cd535c467f3facb7db0867ad3cc0ac7222cae51d",
    "ai_narrative_compressor": "35f7de01a7439584aa51205992e277bfa447ac07f1440c9e3cbf2e21a41d2131",
    "location_compressor": "67c0ad57c2ea7ed833223feba1e07e5e277ae590cde52f5b3c92d6fc0d31c58f",
    "generate_thematic_names": "bbf2a52b00c979300590d9dcc9257e414558e19e7f89be5e8e9ba9f6fff1f742",
    "generate_area_name": "e729ad0a297810d3d36031d97a1411a2f32ec4f8077b8deb27939b8c977ee1f0",
    "generate_area_description": "4ce3141fdd05cb0cbf36a3326db16607a94ddbf2a665659ff69c9364b7d154c9",
    "location_generator": "ea718599f2bd2bbdf3949ea30bedbe0d68f346aa04f419b66774483528278ae9",
    "location_generator_batch": "51fdef28eb600a3be05fbac367ad73c5fc6d2928f5ad72722fcd396c3feeae1f",
    "plot_generator_field": "0d3728778b3ef186dc0ee8833bfa00971084a16b205628308aca7842cc8da2ad",
    "plot_generator_structure": "30bde03bc5f40e3014cef56dfcc083ff1c913698789f25c83998487acd09ec66",
    "update_plot_hooks": "27723a5d205a2879cd623e218540fc5f0710d169cb7a472d0339efd6ac58c0f1",
    "unify_plots": "943f8d581e91d92de1571626ea8cda0b204f40076587627f9f637eea89f57b31",
    "safety_review": "5f1c732f47b640a2adcd877c300611b698154bdd81e6d658db076ee8e65d6180",
    "travel_narration": "a4de39a61015137c62cc70aafe2aae504869c79ce943eb80ccadf275217c5ac7",
    "location_summarizer": "143e8a648233915234688356e307157722415c7bf7ca18f0868b9f9d2b5c958d",
    "monster_builder": "0de99daddb3f53890f55bd8895a0906840b39788d681b8f273ed27c81de795b4",
    "npc_builder": "eaa63bb2b80e456ed915a8a718e6d4a517afa7a31c93b09c79c0e8e8a088a4a0",
    "combat_compression": "e179d8a27a5a425bb279474b9f755507fe87ece570cf7ed1348dbf45a5118c07",
    "incremental_compression": "1a17ab33a420b308e52b038b6274256acbc6817baac023a1c6d638d22073586e",
    "transition_validator": "404cc009aac058b4d7c21f926c9c4d632708c4159b6a4b058efaf2bb771098bb",
    "character_effects_validator": "142ec621bba38577a97c26f16da4d40c18f32cc4f44b191eb3d82a49921cb237",
    "character_validator_armor_class": "7d16ba4df4ca194a2a1b86c09674a37da59527af81ba167dd28a8c7b0a506b66",
    "character_validator_inventory_categories": "cb1503c0298e3419064eb6103f52288095ed6c8f0582571e11f2695642d9032c",
    "character_validator_all_batched": "0d168fbf31919e856ab574e448a6cb00129dd574400c7ea7742846aecef0991c",
    "character_validator_consolidate_inventory": "bf1f68cf7cb8b62dc33dc12dda5590d07ce1d56294e61173d61be03466ca35da",
    "npc_codex_generator": "c9fb276c2017adfaf543bccd90d8c39f97fd0375975995e53dff7d85aca0d311",
    "homebrewery_intro": "982001b664731c34c0dc29878abaaef22684a2ad12922c24b63e327b7030ac13",
    "homebrewery_plot": "4859e595f656eefd2d500ad4368bbe4e827c385337407de35cbcefde1a446bb2",
    "homebrewery_area": "a7d4596ed296a5d351383c669dc9fbe4e6f05c95290f0e4faadd00eb1ae093f0",
    "level_up_utility": "ca11eff81c7fa668e5016f744ec2eae5bde1938b86e23c148857a5a7673fa012",
    "npc_name_canonicalizer": "cc809d9ac7d34c594f482df5ad528dcb44cca533191cbffba4b16304443896cf",
    "npc_reconciler": "3cb14824aaad6807e0fa64289fc499732ba88c33ad56de4531fedb0cc28bba03",
    "prompt_sanitizer": "624ad6e9df5d0fe61440905facee20eff4a3b7422b3d1d32330e670296bdcd78",
    "quest_player_formatter": "0bebd3620e089da220a8e7c27d4a07a0c1e7195956ee57b9b2cae8fac29d1c54",
    "reconcile_location_state": "b089959ccc5ea2cd7a2eb423d0c6da19716b8eb34aab0c020804cd1131257704",
    "spatial_contract": "bc1001266f0123378fd96320183cd8a64451041d7a79875ca3f624443b20176d",
    "startup_get_ai_response": "14374ce16bff0732be46408665d1d392e5966a858702bc4cb257e760c2dfa22e",
    "startup_get_ai_starting_location": "fb134418fccaeafb4282c2868cc88aa3fcec00e0b0dc16836f46a85baf90ea7d",
    "toolkit_homebrew_section": "268b3d626223d9fc49df00b5e1ec945dca514fbc21f606c08df70f391ca0088e",
    "toolkit_homebrew_identity": "96189fe54f403a0252ee369fcb91a14fd470f542e489350981635bccd92c1ea0",
    "toolkit_homebrew_topology": "a38692403b437495a78a543a43f32592545b9e692667fad18447a68ecbaba62e",
    "toolkit_homebrew_legacy": "623c84b40b04255024565050a33b434d4dbef7b112482f6ddfdb81902eff0697",
    "toolkit_homebrew_repair": "a832a028380bc543808eef74d5d222a60b4b4bf0690890b3e58e3f6ce144f3a2",
    "toolkit_final_reconciliation": "8e1910749963d7591f789943fdcbf90373be484072e925aea3b53fe561fcfc02",
    "toolkit_llm_classification": "a17ab9632b251b760d5d395fe69876d3d37fb3c42ed9bfaa56208ed3103ac24d",
    "web_fetch_npc_descriptions": "4f4afcb14dbed99246a3372cbcf00f9917099058096b39a6b4ba09dee46703c9",
    "web_toolkit_npc_description": "665de8d0f965f3cca1f6c49c9ad1c5f7e41c06a1f38784869a811c85cfdc3a1e",
    "web_promote_to_bestiary": "2535fa66cda2e9c87ad8cc21de8d0ae328d368c37b3e5ef3c529756bc76d69c9",
    "plot_update": "376e935375b8ab299e239f148505367076538c5474c448389f2be30b51acae88",
    "update_character_effects": "de10a7fc220ab49941762eedd3b4e0c73b866b5b39616403c7f539c9177e7ea2",
    "update_character_info": "9a54d02300cce9fccd8b665b805bc05b33abc66a08908487659cd52ab87c2f84",
    "update_encounter": "b0b46a5d4093a6474becfaeb950ea242bcea0a237e30d71680234ba3e838698b",
    "critical_narrative_repair": "ba712c8a8406ee6be6af32b7208550ae8f20df6bc480720205e0984b44a8a822",
}

_GENERATOR_PATHS = (
    "core/ai/adv_summary.py",
    "core/ai/cumulative_summary.py",
    "core/ai/combat_compression_engine.py",
    "core/ai/incremental_compression.py",
    "core/ai/transition_validator.py",
    "core/generators/area_generator.py",
    "core/generators/location_generator.py",
    "core/generators/plot_generator.py",
    "core/generators/module_builder.py",
    "core/generators/module_generator.py",
    "core/generators/module_stitcher.py",
    "core/generators/location_summarizer.py",
    "core/generators/monster_builder.py",
    "core/generators/npc_builder.py",
)

_TASK_KEYS = (
    "generate_thematic_names",
    "generate_area_name",
    "generate_area_description",
    "builders",
    "toolkit_final_reconciliation",
    "location_generator",
    "location_generator_batch",
    "plot_generator",
    "update_plot_hooks",
    "parse_module_params",
    "unify_plots",
    "module_generator",
)

_DEFAULT_AUTO_MODEL = "openrouter/auto"
_DEFAULT_AUTO_PROVIDER = "openrouter"


def _assert_default_auto_profile(testcase: unittest.TestCase, task: str) -> Dict[str, Any]:
    profile = llm_router.llm.resolve_profile(task)
    testcase.assertEqual(profile["task"], task)
    testcase.assertEqual(profile["provider_name"], _DEFAULT_AUTO_PROVIDER)
    testcase.assertEqual(profile["model"], _DEFAULT_AUTO_MODEL)
    return profile


def _call_name(node: ast.Call) -> str:
    parts = []
    value = node.func
    while isinstance(value, ast.Attribute):
        parts.append(value.attr)
        value = value.value
    if isinstance(value, ast.Name):
        parts.append(value.id)
    return ".".join(reversed(parts))


def _message_digest(messages: Any) -> str:
    serialized = json.dumps(
        messages,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _assert_usage_only_observer(
    testcase: unittest.TestCase,
    observer_factory: mock.Mock,
    expected_calls: int,
) -> None:
    testcase.assertEqual(observer_factory.call_count, expected_calls)
    for call in observer_factory.call_args_list:
        testcase.assertEqual(call.kwargs, {"track_usage": True})


class _FakeFacade:
    """Fake llm.call, whose json_output=False result is response text."""

    def __init__(
        self,
        response: Optional[str] = None,
        failure: Optional[BaseException] = None,
    ) -> None:
        self.response = response
        self.failure = failure
        self.calls: List[Dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> str:
        self.calls.append(copy.deepcopy(kwargs))
        if self.failure is not None:
            raise self.failure
        return self.response or ""


class _ObservedFacade:
    """Fake facade that supplies one provider response to legacy observers."""

    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: List[Dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> str:
        request = {
            key: copy.deepcopy(value)
            for key, value in kwargs.items()
            if key != "observer"
        }
        self.calls.append(request)
        observer = kwargs.get("observer")
        if observer is not None:
            receipt = SimpleNamespace(
                kind="response",
                attempt_id=f"attempt-{len(self.calls)}",
                call_id=f"call-{len(self.calls)}",
                task=kwargs.get("task"),
            )
            raw_response = SimpleNamespace(
                usage=SimpleNamespace(
                    prompt_tokens=10,
                    completion_tokens=5,
                    total_tokens=15,
                )
            )
            observer(receipt, raw_response)
        return self.response


def _web_interface_for_contract():
    """Import the web routes without starting their unrelated runtime workers."""
    if "web.web_interface" in sys.modules:
        return sys.modules["web.web_interface"]

    import threading
    from core.memory import memory_db
    from web.extensions import missing_media_autogen, module_ingest_watch

    class _NoStartThread:
        def __init__(self, *args, **kwargs):
            self.daemon = kwargs.get("daemon", False)

        def start(self):
            return None

    with mock.patch.object(
        memory_db, "bootstrap_memory_db_from_seed", return_value={"status": "skipped"}
    ), mock.patch.object(memory_db, "init_memory_db", return_value=True), mock.patch.object(
        missing_media_autogen, "start_missing_media_autogen_worker"
    ), mock.patch.object(
        module_ingest_watch, "start_module_ingest_watch_worker"
    ), mock.patch.object(
        threading, "Thread", _NoStartThread
    ), mock.patch.object(
        ai_client_factory, "create_chat_client", return_value=mock.Mock()
    ), mock.patch(
        "os.makedirs", return_value=None
    ):
        import web.web_interface as web_interface

    return web_interface


def _area_generator() -> area_generator.AreaGenerator:
    return area_generator.AreaGenerator()


def _location_generator() -> location_generator.LocationGenerator:
    generator = location_generator.LocationGenerator.__new__(
        location_generator.LocationGenerator
    )
    generator.prompt_guide = location_generator.LocationPromptGuide()
    return generator


def _plot_generator() -> plot_generator.PlotGenerator:
    generator = plot_generator.PlotGenerator.__new__(plot_generator.PlotGenerator)
    generator.prompt_guide = plot_generator.PlotPromptGuide()
    return generator


def _area_name_config() -> area_generator.AreaConfig:
    return area_generator.AreaConfig(area_type="wilderness", danger_level="high")


def _area_thematic_names() -> List[str]:
    return area_generator.MapLayoutGenerator().generate_thematic_names(
        [{"id": "R01", "type": "entrance", "connections": ["R02"]}],
        {
            "module_name": "Test Module",
            "area_name": "Ashen Coast",
            "area_type": "dungeon",
            "theme": "stormbound",
        },
    )


def _area_name_and_description() -> tuple[str, str]:
    return _area_generator().generate_area_name_and_description(
        "Ash Coast", _area_name_config()
    )


def _area_description() -> str:
    return _area_generator().generate_area_description(
        "Ash Coast", _area_name_config()
    )


def _location_field() -> Any:
    return _location_generator().generate_field("description", {"type": "string"}, {})


def _location_batch() -> Dict[str, Any]:
    return _location_generator().generate_location_batch(
        {
            "areaName": "Ash Coast",
            "areaType": "wilderness",
            "areaDescription": "Rugged coast.",
            "dangerLevel": "high",
            "recommendedLevel": 2,
        },
        {
            "plotTitle": "Salt Oath",
            "mainObjective": "Find wreck survivors.",
            "plotPoints": [{"description": "A lantern fails."}],
        },
        {
            "moduleName": "Greyreach",
            "moduleDescription": "Stormy coast.",
            "worldSettings": {"era": "Age of Sail", "magicPrevalence": "rare"},
        },
        [{"locationId": "R01", "name": "Shattered Pier"}],
        excluded_names=["Aster", "Bryn"],
        context_header="HEADER\n",
    )


def _plot_context() -> Dict[str, Any]:
    return {"module_name": "Greyreach", "areas": {}, "locations": {}, "npcs": {}}


def _plot_field() -> Any:
    return _plot_generator().generate_field(
        "plotTitle", {"type": "string"}, _plot_context()
    )


def _plot_structure() -> Dict[str, Any]:
    return _plot_generator().generate_plot_structure(
        2, _plot_context(), context_header="HEADER\n"
    )


def _module_builder() -> ModuleBuilder:
    builder = ModuleBuilder.__new__(ModuleBuilder)
    builder.adaptation_prompt_context = {}
    builder.build_mode = "legacy"
    builder.config = type("Config", (), {"output_directory": "unused"})()
    builder.module_data = {"moduleName": "Greyreach", "moduleDescription": "Stormy coast."}
    builder.areas_data = {"A001": {"areaName": "Ash Coast", "areaType": "wilderness", "recommendedLevel": 2}}
    builder.plots_data = {"A001": {"plotTitle": "Salt Oath", "mainObjective": "Find wreck survivors.", "plotPoints": [{"id": "PP001", "title": "Lantern", "description": "A lantern fails.", "sideQuests": []}]}}
    builder.log = lambda message: None
    builder.save_json = lambda data, filename: None
    builder._create_fallback_unified_plot = lambda: None
    return builder


class RemainingCallsiteContracts(unittest.TestCase):
    def test_utility_content_facade_profiles_and_transport_boundary(self) -> None:
        for task in (
            "action_prediction", "dm_mini", "compression", "location_compression",
        ):
            _assert_default_auto_profile(self, task)
        paths = (
            "utils/action_predictor.py", "utils/bestiary_updater.py",
            "utils/character_creation_audit.py",
            "utils/compression/ai_narrative_compressor_agentic.py",
            "utils/compression/location_compressor.py",
        )
        for path in paths:
            tree = ast.parse((ROOT / path).read_text(encoding="utf-8"), filename=path)
            self.assertFalse([
                node.lineno for node in ast.walk(tree)
                if isinstance(node, ast.Call)
                and _call_name(node).endswith("chat.completions.create")
            ], path)

    def test_action_prediction_facade_boolean_and_fail_open_contract(self) -> None:
        for response, expected in (
            ('{"requires_actions":true,"reason":"movement"}', True),
            ('{"requires_actions":false,"reason":"dialogue"}', False),
            ("not-json", False),
        ):
            fake = _FakeFacade(response=response)
            with mock.patch.object(
                ai_client_factory,
                "create_chat_client",
                side_effect=AssertionError("action predictor constructed a provider client"),
            ) as create_client, mock.patch.object(
                llm_router.llm, "call", side_effect=fake
            ):
                result = action_predictor.predict_actions_required("sample")
            self.assertIs(result["requires_actions"], expected)
            self.assertIs(type(result["requires_actions"]), bool)
            call = fake.calls[0]
            self.assertEqual(call["task"], "action_prediction")
            self.assertIs(call["json_output"], False)
            self.assertEqual(
                _message_digest(call["messages"]),
                PRE_MIGRATION_MESSAGE_DIGESTS["action_prediction"],
            )
            self.assertEqual(
                {key: value for key, value in call.items() if key not in {"task", "messages"}},
                {"json_output": False},
            )
            self.assertFalse(
                {"model", "temperature", "top_p", "timeout", "client", "extra_body"}.intersection(call)
            )
            self.assertNotIn("observer", call)
            self.assertEqual(len(fake.calls), 1)
            create_client.assert_not_called()
        failing = _FakeFacade(failure=RuntimeError("provider down"))
        with mock.patch.object(
            ai_client_factory,
            "create_chat_client",
            side_effect=AssertionError("action predictor constructed a provider client"),
        ) as create_client, mock.patch.object(
            llm_router.llm, "call", side_effect=failing
        ):
            result = action_predictor.predict_actions_required("sample")
        self.assertIs(result["requires_actions"], True)
        self.assertEqual(result["confidence"], "error")
        self.assertEqual(len(failing.calls), 1)
        create_client.assert_not_called()

    def test_bestiary_updater_facade_request_parse_and_retry_contract(self) -> None:
        async def no_sleep(_seconds: float) -> None:
            return None

        response = '{"name":"Goblin","type":"humanoid","description":"A small raider.","tags":[]}'
        fake = _FakeFacade(response=response)
        with mock.patch.object(
            ai_client_factory,
            "create_chat_client",
            side_effect=AssertionError("bestiary updater constructed a provider client"),
        ) as create_client:
            updater = bestiary_updater.BestiaryUpdater()
        create_client.assert_not_called()
        self.assertFalse(hasattr(updater, "client"))

        with mock.patch.object(
            llm_router.llm, "call", side_effect=fake
        ), mock.patch.object(
            bestiary_updater.time, "time", side_effect=[10.0, 11.0]
        ), mock.patch.object(
            bestiary_updater.asyncio, "sleep", side_effect=no_sleep
        ), mock.patch.object(
            ai_client_factory,
            "create_chat_client",
            side_effect=AssertionError("bestiary updater constructed a provider client"),
        ) as create_client, contextlib.redirect_stdout(io.StringIO()):
            coroutine = updater.generate_monster_description("Goblin", "A cave.")
            try:
                coroutine.send(None)
            except StopIteration as completed:
                result = completed.value
        self.assertEqual(result["name"], "Goblin")
        self.assertEqual(result["type"], "humanoid")
        self.assertEqual(result["description"], "A small raider.")
        request = fake.calls[0]
        self.assertEqual(request["task"], "dm_mini")
        self.assertEqual(_message_digest(request["messages"]), PRE_MIGRATION_MESSAGE_DIGESTS["bestiary_updater"])
        self.assertEqual(
            {key: value for key, value in request.items() if key not in {"task", "messages"}},
            {"json_output": False, "response_format": {"type": "json_object"}},
        )
        self.assertFalse(
            {"model", "temperature", "top_p", "timeout", "client", "extra_body", "observer"}.intersection(request)
        )
        self.assertEqual(len(fake.calls), 1)
        create_client.assert_not_called()

        failing = _FakeFacade(failure=RuntimeError("provider down"))
        with mock.patch.object(
            llm_router.llm, "call", side_effect=failing
        ), mock.patch.object(
            bestiary_updater.time, "time", return_value=10.0
        ), mock.patch.object(
            bestiary_updater.asyncio, "sleep", side_effect=no_sleep
        ), mock.patch.object(
            ai_client_factory,
            "create_chat_client",
            side_effect=AssertionError("bestiary updater constructed a provider client"),
        ) as create_client, contextlib.redirect_stdout(io.StringIO()):
            coroutine = bestiary_updater.BestiaryUpdater().generate_monster_description("Goblin", "A cave.")
            try:
                coroutine.send(None)
            except StopIteration as completed:
                failure_result = completed.value
        self.assertIsNone(failure_result)
        self.assertEqual(len(failing.calls), 3)
        self.assertTrue(all(call["task"] == "dm_mini" for call in failing.calls))
        create_client.assert_not_called()

    def test_character_creation_audit_facade_request_parse_and_fallback(self) -> None:
        character = {"name": "Aster", "class": "Rogue", "race": "Elf", "background": "Sailor"}
        fake = _FakeFacade(response='{"updates":{"personality_traits":"Careful and curious."}}')
        with mock.patch.object(
            ai_client_factory,
            "create_chat_client",
            side_effect=AssertionError("character audit constructed a provider client"),
        ) as create_client, mock.patch.object(llm_router.llm, "call", side_effect=fake):
            result = character_creation_audit.build_readiness_repair_proposal(character, ["personality_traits"])
        self.assertEqual(result["source"], "llm")
        self.assertEqual(result["updates"], {"personality_traits": "Careful and curious."})
        request = fake.calls[0]
        self.assertEqual(request["task"], "dm_mini")
        self.assertEqual(_message_digest(request["messages"]), PRE_MIGRATION_MESSAGE_DIGESTS["character_creation_audit"])
        self.assertEqual(
            {key: value for key, value in request.items() if key not in {"task", "messages"}},
            {"json_output": False},
        )
        self.assertFalse(
            {"model", "temperature", "top_p", "timeout", "client", "extra_body", "observer"}.intersection(request)
        )
        self.assertEqual(len(fake.calls), 1)
        create_client.assert_not_called()

        failing = _FakeFacade(failure=RuntimeError("provider down"))
        with mock.patch.object(
            ai_client_factory,
            "create_chat_client",
            side_effect=AssertionError("character audit constructed a provider client"),
        ) as create_client, mock.patch.object(llm_router.llm, "call", side_effect=failing):
            fallback = character_creation_audit.build_readiness_repair_proposal(character, ["personality_traits"])
        self.assertEqual(fallback, character_creation_audit._build_readiness_repair_fallback(["personality_traits"]))
        self.assertEqual(fallback["source"], "fallback")
        self.assertEqual(len(failing.calls), 1)
        create_client.assert_not_called()

    def test_compressors_facade_requests_usage_and_failures(self) -> None:
        raw_response = SimpleNamespace(
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15)
        )
        compressor_cases = (
            (
                "narrative",
                ai_narrative_compressor_agentic,
                lambda: ai_narrative_compressor_agentic.compress_with_ai("The party enters."),
                '{"blocks":[{"text":"@C={}\\n@L={}\\nEVT[\\n1) @L1 meet.\\n]"}]}',
                "@C={}\n@L={}\nEVT[\n1) @L1 meet.\n]",
                "compression",
                "ai_narrative_compressor",
            ),
            (
                "location",
                location_compressor,
                lambda: location_compressor.compress_location('{"name":"Cave"}', max_retries=0),
                "@T=CS/v2",
                "@T=CS/v2",
                "location_compression",
                "location_compressor",
            ),
        )
        for name, owner, operation, response, expected, task, digest_key in compressor_cases:
            with self.subTest(compressor=name):
                tracker = mock.Mock()
                trace_writer = mock.Mock()
                api_logger = mock.Mock()
                observer_calls = []

                def observer_factory(**kwargs):
                    observer_calls.append(copy.deepcopy(kwargs))
                    return make_legacy_receipt_observer(
                        tracker_getter=lambda: tracker,
                        trace_gate=lambda: True,
                        trace_writer=trace_writer,
                        api_logger=api_logger,
                        **kwargs,
                    )

                facade = _ObservedFacade(response)
                with mock.patch.object(
                    owner, "USAGE_TRACKING_AVAILABLE", True
                ), mock.patch.object(
                    owner, "make_legacy_receipt_observer", side_effect=observer_factory
                ), mock.patch.object(
                    ai_client_factory,
                    "create_chat_client",
                    side_effect=AssertionError(f"{name} compressor constructed a provider client"),
                ) as create_client, mock.patch.object(
                    llm_router.llm, "call", side_effect=facade
                ), contextlib.redirect_stdout(io.StringIO()):
                    result = operation()

                if name == "narrative":
                    self.assertEqual(result["blocks"][0]["text"], expected)
                else:
                    self.assertEqual(result, expected)
                request = facade.calls[0]
                self.assertEqual(request["task"], task)
                self.assertEqual(_message_digest(request["messages"]), PRE_MIGRATION_MESSAGE_DIGESTS[digest_key])
                self.assertEqual(
                    {key: value for key, value in request.items() if key not in {"task", "messages"}},
                    {"json_output": False},
                )
                self.assertFalse(
                    {"model", "temperature", "top_p", "timeout", "client", "extra_body"}.intersection(request)
                )
                self.assertEqual(observer_calls, [{"track_usage": True}])
                self.assertNotIn("trace_site", observer_calls[0])
                self.assertNotIn("endpoint_name", observer_calls[0])
                self.assertNotIn("messages", observer_calls[0])
                self.assertNotIn("api_log_before_tracker", observer_calls[0])
                tracker.track.assert_called_once()
                trace_writer.assert_not_called()
                api_logger.assert_not_called()
                create_client.assert_not_called()

                failing = _FakeFacade(failure=RuntimeError("provider down"))
                failure_tracker = mock.Mock()
                failure_observers = []

                def failure_observer_factory(**kwargs):
                    failure_observers.append(copy.deepcopy(kwargs))
                    return make_legacy_receipt_observer(
                        tracker_getter=lambda: failure_tracker,
                        **kwargs,
                    )

                with mock.patch.object(
                    owner, "USAGE_TRACKING_AVAILABLE", True
                ), mock.patch.object(
                    owner, "make_legacy_receipt_observer", side_effect=failure_observer_factory
                ), mock.patch.object(
                    ai_client_factory,
                    "create_chat_client",
                    side_effect=AssertionError(f"{name} compressor constructed a provider client"),
                ) as create_client, mock.patch.object(
                    llm_router.llm, "call", side_effect=failing
                ), contextlib.redirect_stdout(io.StringIO()):
                    if name == "location":
                        failed_result = location_compressor.compress_location('{"name":"Cave"}')
                    else:
                        failed_result = ai_narrative_compressor_agentic.compress_with_ai("The party enters.")

                self.assertIsNone(failed_result)
                self.assertEqual(len(failing.calls), 3 if name == "location" else 1)
                self.assertTrue(all(call["task"] == task for call in failing.calls))
                self.assertEqual(len(failure_observers), len(failing.calls))
                failure_tracker.track.assert_not_called()
                create_client.assert_not_called()

    @staticmethod
    def _merge_validation_data(original: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
        merged = copy.deepcopy(original)
        for key, value in updates.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = RemainingCallsiteContracts._merge_validation_data(
                    merged[key], value
                )
            else:
                merged[key] = copy.deepcopy(value)
        return merged

    def _new_character_validator(self) -> character_validator.AICharacterValidator:
        with mock.patch.object(
            ai_client_factory,
            "create_chat_client",
            side_effect=AssertionError("character validator constructed a provider client"),
        ) as create_client, mock.patch.object(
            character_validator.AICharacterValidator, "_load_prompt", return_value=""
        ), mock.patch.object(
            character_validator.AICharacterValidator, "_load_cache", return_value={}
        ):
            validator = character_validator.AICharacterValidator()
        create_client.assert_not_called()
        self.assertFalse(hasattr(validator, "client"))

        validator.extract_ac_relevant_data = mock.Mock(return_value={"armorClass": 10})
        validator._compute_ac_hash = mock.Mock(return_value="ac-hash")
        validator._is_ac_validation_cached = mock.Mock(return_value=False)
        validator.build_ac_validation_prompt = mock.Mock(return_value="ac prompt")
        validator.get_validator_system_prompt = mock.Mock(return_value="ac system")
        validator._update_ac_cache = mock.Mock()

        inventory = {
            "name": "A",
            "equipment": [
                {"item_name": "odd item", "item_type": "miscellaneous"}
            ],
        }
        validator.extract_inventory_data = mock.Mock(return_value=inventory)
        validator._compute_inventory_hash = mock.Mock(return_value="inventory-hash")
        validator._is_inventory_validation_cached = mock.Mock(return_value=False)
        validator.build_inventory_validation_prompt = mock.Mock(
            return_value="inventory prompt"
        )
        validator.get_inventory_validator_system_prompt = mock.Mock(
            return_value="inventory system"
        )
        validator._update_inventory_cache = mock.Mock()

        consolidation = {
            "name": "A",
            "currency": {"gold": 1},
            "equipment": [{"item_name": "5 gold pieces"}],
        }
        validator.extract_currency_consolidation_data = mock.Mock(
            return_value=consolidation
        )
        validator._compute_currency_hash = mock.Mock(return_value="currency-hash")
        validator._is_currency_validation_cached = mock.Mock(return_value=False)
        validator.build_inventory_consolidation_prompt = mock.Mock(
            return_value="consolidation prompt"
        )
        validator.get_inventory_consolidation_system_prompt = mock.Mock(
            return_value="consolidation system"
        )
        validator._update_currency_cache = mock.Mock()

        validator.build_combined_validation_prompt = mock.Mock(
            return_value="combined prompt"
        )
        validator.get_combined_validator_system_prompt = mock.Mock(
            return_value="combined system"
        )
        return validator

    def _new_character_effects_validator(
        self,
    ) -> character_effects_validator.AICharacterEffectsValidator:
        with mock.patch.object(
            ai_client_factory,
            "create_chat_client",
            side_effect=AssertionError("effects validator constructed a provider client"),
        ) as create_client, mock.patch(
            "utils.encoding_utils.safe_json_load", return_value={}
        ), mock.patch.object(
            character_effects_validator,
            "ModulePathManager",
            return_value=mock.Mock(),
        ):
            validator = character_effects_validator.AICharacterEffectsValidator()
        create_client.assert_not_called()
        self.assertFalse(hasattr(validator, "client"))
        return validator

    def test_monster_and_npc_builder_requests_parsing_and_failures(self) -> None:
        cases = (
            ("monster_builder", monster_builder, lambda: monster_builder.generate_monster("Goblin", {}), "{}", "monster_builder"),
            ("npc_builder", npc_builder, lambda: npc_builder.generate_npc("Aster", {}), "{}", "npc_builder"),
        )
        for task, owner, operation, text, digest_key in cases:
            with self.subTest(task=task):
                fake = _FakeFacade(response=text)
                with mock.patch.object(llm_router.llm, "call", side_effect=fake), mock.patch.object(
                    ai_client_factory, "create_chat_client",
                    side_effect=AssertionError("builder constructed a provider client"),
                ) as create_client, contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(operation(), {})
                request = fake.calls[0]
                self.assertEqual(request["task"], task)
                self.assertEqual(_message_digest(request["messages"]), PRE_MIGRATION_MESSAGE_DIGESTS[digest_key])
                self.assertEqual({key: value for key, value in request.items() if key not in {"task", "messages"}}, {"json_output": False})
                self.assertFalse({"model", "temperature", "top_p", "client", "timeout"}.intersection(request))
                create_client.assert_not_called()

                failing = _FakeFacade(failure=RuntimeError("provider down"))
                with mock.patch.object(llm_router.llm, "call", side_effect=failing), mock.patch.object(
                    owner, "handle_provider_error", return_value={"should_fallback": True}
                ) as handler, contextlib.redirect_stdout(io.StringIO()):
                    self.assertIsNone(operation())
                self.assertEqual(len(failing.calls), 3)
                self.assertEqual(handler.call_count, 3)

    def test_monster_and_npc_builder_profiles_preserve_models(self) -> None:
        for task in ("monster_builder", "npc_builder"):
            with self.subTest(task=task):
                _assert_default_auto_profile(self, task)

    def _assert_success_contract(
        self,
        operation: Callable[[], Any],
        task: str,
        digest_key: str,
        response: str,
        expected_result: Any,
        response_format: Optional[Dict[str, str]] = None,
    ) -> None:
        fake = _FakeFacade(response=response)
        with mock.patch.object(llm_router.llm, "call", side_effect=fake):
            with mock.patch.object(
                ai_client_factory,
                "create_chat_client",
                side_effect=AssertionError("generator constructed a provider client"),
            ) as create_client:
                result = operation()

        self.assertEqual(result, expected_result)
        self.assertEqual(len(fake.calls), 1)
        request = fake.calls[0]
        self.assertEqual(request["task"], task)
        self.assertEqual(
            _message_digest(request["messages"]),
            PRE_MIGRATION_MESSAGE_DIGESTS[digest_key],
        )
        expected_kwargs: Dict[str, Any] = {"json_output": False}
        if response_format is not None:
            expected_kwargs["response_format"] = response_format
        self.assertEqual(
            {key: value for key, value in request.items() if key not in {"task", "messages"}},
            expected_kwargs,
        )
        self.assertFalse(
            {"model", "temperature", "top_p", "client", "timeout"}.intersection(request)
        )
        create_client.assert_not_called()

    def test_area_generator_requests_and_parsing(self) -> None:
        self._assert_success_contract(
            _area_thematic_names,
            "generate_thematic_names",
            "generate_thematic_names",
            '["Weathered Gate Chamber"]',
            ["Weathered Gate Chamber"],
        )
        self._assert_success_contract(
            _area_name_and_description,
            "generate_area_name",
            "generate_area_name",
            '{"refinedName":"Ashen Shore","description":"Salt wind cuts across the cliffs."}',
            ("Ashen Shore", "Salt wind cuts across the cliffs."),
            response_format={"type": "json_object"},
        )
        self._assert_success_contract(
            _area_description,
            "generate_area_description",
            "generate_area_description",
            "  Salt wind cuts across the cliffs.  ",
            "Salt wind cuts across the cliffs.",
        )

    def test_location_generator_requests_and_parsing(self) -> None:
        self._assert_success_contract(
            _location_field,
            "location_generator",
            "location_generator",
            '{"name":"Weathered Pier","type":"dock"}',
            {"name": "Weathered Pier", "type": "dock"},
        )
        self._assert_success_contract(
            _location_batch,
            "location_generator_batch",
            "location_generator_batch",
            '{"locations":[{"locationId":"R01","name":"Weathered Pier"}]}',
            {"locations": [{"locationId": "R01", "name": "Weathered Pier"}]},
            response_format={"type": "json_object"},
        )

    def test_plot_generator_requests_and_parsing(self) -> None:
        self._assert_success_contract(
            _plot_field,
            "plot_generator",
            "plot_generator_field",
            "  The Salt Oath  ",
            "The Salt Oath",
        )
        self._assert_success_contract(
            _plot_structure,
            "plot_generator",
            "plot_generator_structure",
            '{"plotPoints":[{"id":"PP001","sideQuests":[]}]}',
            {"plotPoints": [{"id": "PP001", "sideQuests": []}]},
            response_format={"type": "json_object"},
        )

    def test_task_profiles_use_default_openrouter_auto_model(self) -> None:
        self.assertEqual(model_config.LLM_PROVIDER, "openrouter")
        self.assertEqual(model_config.ACTIVE_PROFILE, "production-auto")
        for task in _TASK_KEYS:
            with self.subTest(task=task):
                _assert_default_auto_profile(self, task)

    def test_module_generator_task_profiles_preserve_models(self) -> None:
        for task in ("update_plot_hooks", "unify_plots", "module_generator", "parse_module_params"):
            with self.subTest(task=task):
                _assert_default_auto_profile(self, task)

    def test_remaining_generator_task_profiles_preserve_models(self) -> None:
        for task in ("safety_review", "travel_narration", "location_summarizer"):
            with self.subTest(task=task):
                _assert_default_auto_profile(self, task)

    def test_adventure_summary_task_profile_preserves_model(self) -> None:
        _assert_default_auto_profile(self, "adventure_summary")

    def test_cumulative_summary_router_requests_and_fallbacks(self) -> None:
        operations = (
            (cumulative_summary.generate_location_summary, ("Harbor", [{"role": "assistant", "content": "A ship arrived."}]), "location_summary"),
            (cumulative_summary._enhance_summary_for_journal, ("A ship arrived.",), "journal_summary"),
        )
        for operation, args, _ in operations:
            with self.subTest(operation=operation.__name__):
                tracker = mock.Mock()
                trace_writer = mock.Mock()
                api_logger = mock.Mock()
                observer_calls = []
                def observer_factory(**kwargs):
                    observer_calls.append(kwargs)
                    return make_legacy_receipt_observer(
                        tracker_getter=lambda: tracker,
                        trace_gate=lambda: True,
                        trace_writer=trace_writer,
                        api_logger=api_logger,
                        **kwargs,
                    )
                def invoke(**kwargs):
                    kwargs["observer"](
                        SimpleNamespace(kind="response", attempt_id="attempt-1", call_id="call-1", task="adventure_summary"),
                        SimpleNamespace(usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2)),
                    )
                    return "  Chronicle entry.  "
                with mock.patch.object(cumulative_summary, "make_legacy_receipt_observer", side_effect=observer_factory), mock.patch.object(llm_router.llm, "call", side_effect=invoke) as call, mock.patch.object(cumulative_summary, "debug_print"), mock.patch("utils.combat_latency_trace.trace_enabled", return_value=True), mock.patch("utils.combat_latency_trace.emit_trace_event", trace_writer), mock.patch("utils.api_logger.log_api_call", api_logger):
                    self.assertEqual(operation(*args), "Chronicle entry.")
                self.assertTrue(observer_calls[0]["track_usage"])
                self.assertNotIn("trace_site", observer_calls[0])
                self.assertNotIn("messages", observer_calls[0])
                tracker.track.assert_called_once()
                trace_writer.assert_not_called()
                api_logger.assert_not_called()
                request = call.call_args.kwargs
                self.assertEqual(request["task"], "adventure_summary")
                self.assertIs(request["json_output"], False)
                self.assertFalse({"model", "temperature", "top_p", "client", "timeout"}.intersection(request))
                failing = _FakeFacade(failure=RuntimeError("provider down"))
                with mock.patch.object(cumulative_summary, "make_legacy_receipt_observer", return_value=mock.Mock()), mock.patch.object(llm_router.llm, "call", side_effect=failing), mock.patch.object(cumulative_summary, "debug_print"):
                    expected = None if operation is cumulative_summary.generate_location_summary else args[0]
                    self.assertEqual(operation(*args), expected)
                self.assertEqual(len(failing.calls), 1)

    def test_adv_summary_generate_adventure_summary_request_return_and_failure(self) -> None:
        writes = []
        def capture_write(data, path):
            writes.append((path, copy.deepcopy(data)))
        fake = _FakeFacade(response="  A vivid chronicle.  ")
        tracker = mock.Mock()
        trace_writer = mock.Mock()
        api_logger = mock.Mock()
        observer_calls = []
        def observer_factory(**kwargs):
            observer_calls.append(kwargs)
            return make_legacy_receipt_observer(tracker_getter=lambda: tracker, trace_gate=lambda: True, trace_writer=trace_writer, api_logger=api_logger, **kwargs)
        def observe_once(**kwargs):
            kwargs["observer"](SimpleNamespace(kind="response", attempt_id="attempt-1", call_id="call-1", task="adventure_summary"), SimpleNamespace(usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2)))
            return "  A vivid chronicle.  "
        with mock.patch.object(adv_summary.os.path, "exists", return_value=False), mock.patch.object(adv_summary, "safe_json_dump", side_effect=capture_write), mock.patch.object(
            adv_summary, "status_generating_summary"
        ), mock.patch.object(adv_summary, "debug_print"), mock.patch.object(
            adv_summary, "make_legacy_receipt_observer", side_effect=observer_factory
        ), mock.patch.object(llm_router.llm, "call", side_effect=observe_once) as call, mock.patch("utils.combat_latency_trace.trace_enabled", return_value=True), mock.patch("utils.combat_latency_trace.emit_trace_event", trace_writer), mock.patch("utils.api_logger.log_api_call", api_logger):
            result = adv_summary.generate_adventure_summary(
                [{"role": "assistant", "content": "The party crossed the bridge."}],
                {}, "Old Bridge",
            )
        self.assertEqual(result, "A vivid chronicle.")
        self.assertEqual([path for path, _ in writes], ["summary_dump.json", "trimmed_summary_dump.json", "dialogue_summary.json"])
        request = call.call_args.kwargs
        self.assertEqual(request["task"], "adventure_summary")
        self.assertIs(request["json_output"], False)
        self.assertEqual(request["messages"], writes[-1][1])
        self.assertFalse({"model", "temperature", "top_p", "client", "timeout"}.intersection(request))
        self.assertTrue(observer_calls[0]["track_usage"])
        self.assertNotIn("trace_site", observer_calls[0])
        self.assertNotIn("messages", observer_calls[0])
        tracker.track.assert_called_once()
        trace_writer.assert_not_called()
        api_logger.assert_not_called()

        failing = _FakeFacade(failure=RuntimeError("provider down"))
        with mock.patch.object(adv_summary.os.path, "exists", return_value=False), mock.patch.object(adv_summary, "safe_json_dump"), mock.patch.object(
            adv_summary, "status_generating_summary"
        ), mock.patch.object(adv_summary, "debug_print"), mock.patch.object(
            adv_summary, "make_legacy_receipt_observer", return_value=mock.Mock()
        ), mock.patch.object(llm_router.llm, "call", side_effect=failing):
            self.assertIsNone(adv_summary.generate_adventure_summary([], {}, "Old Bridge"))
        self.assertEqual(len(failing.calls), 1)

    def test_adv_summary_update_location_json_request_parse_persistence_and_failure(self) -> None:
        scratch = ROOT / "tmp" / "router-rollout" / "g6" / "adv_summary_area.json"
        scratch.parent.mkdir(parents=True, exist_ok=True)
        location = {"name": "Old Bridge", "locationId": "R01"}
        schema = {"properties": {"locations": {"items": {}}}}
        area = {"locations": [copy.deepcopy(location)]}
        path_manager = mock.Mock()
        path_manager.module_name = "Test_Module"
        path_manager.module_dir = str(scratch.parent)
        path_manager.get_area_path.return_value = str(scratch)
        writes = []
        tracker = mock.Mock()
        trace_writer = mock.Mock()
        api_logger = mock.Mock()
        observer_calls = []
        def observer_factory(**kwargs):
            observer_calls.append(kwargs)
            return make_legacy_receipt_observer(tracker_getter=lambda: tracker, trace_gate=lambda: True, trace_writer=trace_writer, api_logger=api_logger, **kwargs)
        def observe_once(**kwargs):
            kwargs["observer"](SimpleNamespace(kind="response", attempt_id="attempt-1", call_id="call-1", task="adventure_summary"), SimpleNamespace(usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2)))
            return '{"name":"Old Bridge","adventureSummary":"The bridge was crossed."}'
        with mock.patch.object(adv_summary, "debug_print"), mock.patch.object(
            adv_summary, "safe_json_load", return_value={}
        ), mock.patch.object(adv_summary, "load_json_file", side_effect=[schema, copy.deepcopy(area)]), mock.patch.object(
            adv_summary, "get_game_time", return_value="1 Spring 1, Dawn"
        ), mock.patch.object(adv_summary, "ModulePathManager", return_value=path_manager), mock.patch.object(
            adv_summary.os.path, "exists", return_value=True
        ), mock.patch.object(adv_summary, "validate_location_json"), mock.patch.object(
            adv_summary, "safe_json_dump", side_effect=lambda data, path: writes.append((path, copy.deepcopy(data)))
        ), mock.patch.object(adv_summary, "make_legacy_receipt_observer", side_effect=observer_factory), mock.patch.object(
            llm_router.llm, "call", side_effect=observe_once
        ) as call, mock.patch("utils.combat_latency_trace.trace_enabled", return_value=True), mock.patch("utils.combat_latency_trace.emit_trace_event", trace_writer), mock.patch("utils.api_logger.log_api_call", api_logger):
            result = adv_summary.update_location_json("The party crossed the bridge.", location, "A01")
        self.assertEqual(result["adventureSummary"], "The bridge was crossed.")
        self.assertEqual(len(writes), 1)
        self.assertEqual(writes[0][0], str(scratch))
        request = call.call_args.kwargs
        self.assertEqual(request["task"], "adventure_summary")
        self.assertIs(request["json_output"], False)
        self.assertFalse({"model", "temperature", "top_p", "client", "timeout"}.intersection(request))
        self.assertEqual(request["messages"][0]["role"], "system")
        self.assertIn('"Old Bridge"', request["messages"][0]["content"])
        self.assertTrue(observer_calls[0]["track_usage"])
        self.assertNotIn("trace_site", observer_calls[0])
        self.assertNotIn("messages", observer_calls[0])
        tracker.track.assert_called_once()
        trace_writer.assert_not_called()
        api_logger.assert_not_called()

        failing = _FakeFacade(failure=RuntimeError("provider down"))
        with mock.patch.object(adv_summary, "debug_print"), mock.patch.object(
            adv_summary, "safe_json_load", return_value={}
        ), mock.patch.object(adv_summary, "load_json_file", side_effect=[schema]), mock.patch.object(
            adv_summary, "get_game_time", return_value="1 Spring 1, Dawn"
        ), mock.patch.object(adv_summary, "make_legacy_receipt_observer", return_value=mock.Mock()), mock.patch.object(
            llm_router.llm, "call", side_effect=failing
        ), mock.patch.object(adv_summary.sys, "exit", side_effect=SystemExit):
            with self.assertRaises(SystemExit):
                adv_summary.update_location_json("Events.", location, "A01")
        self.assertEqual(len(failing.calls), 3)

    def test_combat_compression_router_request_trace_usage_and_failure(self) -> None:
        content = "combat block input that must remain byte-identical"
        compressor = combat_compression_engine.CombatCompressor(enable_caching=False)
        tracker = mock.Mock()
        trace_writer = mock.Mock()
        api_logger = mock.Mock()
        consumer_order = []
        tracker.track.side_effect = lambda *_args, **_kwargs: consumer_order.append("tracker")
        trace_writer.side_effect = lambda event, **_kwargs: consumer_order.append(event)
        observer_calls = []
        raw_response = SimpleNamespace(
            usage=SimpleNamespace(prompt_tokens=12, completion_tokens=5, total_tokens=17)
        )
        receipt = SimpleNamespace(
            kind="response",
            attempt_id="compression-attempt-1",
            call_id="compression-call-1",
            attempt_number=1,
            task="compression",
        )

        def observer_factory(**kwargs):
            observer_calls.append(copy.deepcopy(kwargs))
            return make_legacy_receipt_observer(
                tracker_getter=lambda: tracker,
                trace_gate=lambda: True,
                trace_writer=trace_writer,
                api_logger=api_logger,
                **kwargs,
            )

        def respond(**kwargs):
            request = {
                key: copy.deepcopy(value)
                for key, value in kwargs.items()
                if key != "observer"
            }
            facade.calls.append(request)
            kwargs["observer"](receipt, raw_response)
            return "@T=CS/v2\n@ROUND=2"

        facade = _FakeFacade()
        with contextlib.redirect_stdout(io.StringIO()), mock.patch.object(
            combat_compression_engine, "USAGE_TRACKING_AVAILABLE", True
        ), mock.patch.object(
            combat_compression_engine, "make_legacy_receipt_observer",
            side_effect=observer_factory,
        ), mock.patch.object(llm_router.llm, "call", side_effect=respond), mock.patch.object(
            ai_client_factory,
            "create_chat_client",
            side_effect=AssertionError("combat compressor constructed a provider client"),
        ) as create_client:
            self.assertEqual(compressor.compress(content), "@T=CS/v2\n@ROUND=2")

        request = facade.calls[0]
        self.assertEqual(request["task"], "compression")
        self.assertEqual(
            _message_digest(request["messages"]),
            PRE_MIGRATION_MESSAGE_DIGESTS["combat_compression"],
        )
        self.assertEqual(
            {key: value for key, value in request.items() if key not in {"task", "messages"}},
            {"json_output": False},
        )
        self.assertFalse({"model", "temperature", "top_p", "client", "timeout"}.intersection(request))
        self.assertEqual(len(observer_calls), 1)
        self.assertEqual(observer_calls[0]["trace_site"], "combat_compression")
        self.assertEqual(observer_calls[0]["legacy_context"], {"purpose": "combat_turn_processing"})
        self.assertTrue(observer_calls[0]["track_usage"])
        self.assertNotIn("endpoint_name", observer_calls[0])
        self.assertNotIn("messages", observer_calls[0])
        self.assertEqual(consumer_order, ["provider", "tracker"])
        tracker.track.assert_called_once()
        trace_writer.assert_called_once()
        trace_fields = trace_writer.call_args.kwargs
        self.assertEqual(trace_fields["site"], "combat_compression")
        self.assertEqual(trace_fields["purpose"], "combat_turn_processing")
        self.assertEqual(trace_fields["call_id"], "compression-call-1")
        self.assertEqual(trace_fields["attempt_id"], "compression-attempt-1")
        api_logger.assert_not_called()
        create_client.assert_not_called()

        failing = _FakeFacade(failure=RuntimeError("provider down"))
        with contextlib.redirect_stdout(io.StringIO()), mock.patch.object(
            combat_compression_engine, "make_legacy_receipt_observer", return_value=mock.Mock()
        ), mock.patch.object(llm_router.llm, "call", side_effect=failing), mock.patch.object(
            ai_client_factory,
            "create_chat_client",
            side_effect=AssertionError("combat compressor constructed a provider client"),
        ) as create_client:
            self.assertEqual(compressor.compress(content), content)
        self.assertEqual(len(failing.calls), 1)
        self.assertEqual(failing.calls[0]["task"], "compression")
        create_client.assert_not_called()

    def test_incremental_compression_router_request_return_and_failure(self) -> None:
        messages = [
            {"role": "user", "content": "We enter the salt cave."},
            {"role": "assistant", "content": '{"narration":"The tide recedes."}'},
            {"role": "system", "content": "Summary: the old beacon is dark."},
        ]
        location_info = {
            "name": "Salt Cave",
            "id": "C01",
            "description": "A damp cavern.",
        }
        compressor = incremental_compression.IncrementalLocationCompressor()
        response = "  The party follows the receding tide.  "
        facade = _FakeFacade(response=response)
        with mock.patch.object(llm_router.llm, "call", side_effect=facade), mock.patch.object(
            incremental_compression, "safe_json_load", return_value={}
        ), mock.patch.object(
            incremental_compression, "inject_location_provenance", side_effect=lambda text, *_args: text
        ), mock.patch.object(
            ai_client_factory,
            "create_chat_client",
            side_effect=AssertionError("incremental compressor constructed a provider client"),
        ) as create_client:
            result = compressor.compress_messages(messages, location_info)

        self.assertEqual(result["role"], "assistant")
        self.assertIn(response, result["content"])
        request = facade.calls[0]
        self.assertEqual(request["task"], "compression")
        self.assertEqual(
            _message_digest(request["messages"]),
            PRE_MIGRATION_MESSAGE_DIGESTS["incremental_compression"],
        )
        self.assertEqual(
            {key: value for key, value in request.items() if key not in {"task", "messages"}},
            {"json_output": False},
        )
        self.assertFalse({"model", "temperature", "top_p", "client", "timeout", "observer"}.intersection(request))
        self.assertFalse(hasattr(compressor, "client"))
        create_client.assert_not_called()

        failing = _FakeFacade(failure=RuntimeError("provider down"))
        with mock.patch.object(llm_router.llm, "call", side_effect=failing), mock.patch.object(
            incremental_compression, "error"
        ), mock.patch.object(
            ai_client_factory,
            "create_chat_client",
            side_effect=AssertionError("incremental compressor constructed a provider client"),
        ) as create_client:
            self.assertIsNone(compressor.compress_messages(messages, location_info))
        self.assertEqual(len(failing.calls), 1)
        self.assertEqual(failing.calls[0]["task"], "compression")
        create_client.assert_not_called()

    def test_transition_validator_router_request_logging_and_fail_open(self) -> None:
        arguments = (
            "Travel to the Glass Tower.",
            "C01",
            "Salt Cave",
            "A01",
            "Ash Coast",
            "T01",
            ["C01", "T01"],
            {"path_segments": [{
                "location_id": "T01",
                "location_name": "Glass Tower",
                "area_name": "North Reach",
            }]},
            "Known transition atlas.",
            {"plotPoints": [{"id": "PP01", "title": "The Beacon", "status": "in progress", "location": "C01"}]},
        )
        response_text = '{"approved":false,"stop_location":"T01","reason":"Unexplored crypt"}'
        raw_response = SimpleNamespace(
            usage=SimpleNamespace(prompt_tokens=18, completion_tokens=8, total_tokens=26)
        )
        receipt = SimpleNamespace(
            kind="response",
            attempt_id="transition-attempt-1",
            call_id="transition-call-1",
            attempt_number=1,
            task="dm_main",
        )
        api_logger = mock.Mock()
        tracker = mock.Mock()
        observer_calls = []

        def observer_factory(**kwargs):
            observer_calls.append(copy.deepcopy(kwargs))
            return make_legacy_receipt_observer(
                tracker_getter=lambda: tracker,
                api_logger=api_logger,
                **kwargs,
            )

        facade = _FakeFacade()

        def respond(**kwargs):
            request = {
                key: copy.deepcopy(value)
                for key, value in kwargs.items()
                if key != "observer"
            }
            facade.calls.append(request)
            kwargs["observer"](receipt, raw_response)
            return response_text

        with mock.patch.object(
            transition_validator, "load_transition_validation_prompt",
            return_value="Transition policy prompt.",
        ), mock.patch(
            "utils.path_encounter_analyzer.build_path_context_for_ai",
            return_value="Known path context.",
        ), mock.patch.object(
            transition_validator, "make_legacy_receipt_observer",
            side_effect=observer_factory,
        ), mock.patch.object(llm_router.llm, "call", side_effect=respond), mock.patch.object(
            ai_client_factory,
            "create_chat_client",
            side_effect=AssertionError("transition validator constructed a provider client"),
        ) as create_client, mock.patch.object(transition_validator, "debug"), mock.patch.object(
            transition_validator, "info"
        ), mock.patch.object(transition_validator, "warning"), mock.patch.object(
            transition_validator, "error"
        ):
            result = transition_validator.validate_transition_request(*arguments)

        self.assertFalse(result["approved"])
        self.assertEqual(result["stop_location"], "T01")
        self.assertEqual(result["reason"], "Unexplored crypt")
        self.assertEqual(result["narrative_guidance"], "")
        request = facade.calls[0]
        self.assertEqual(request["task"], "dm_main")
        self.assertEqual(
            _message_digest(request["messages"]),
            PRE_MIGRATION_MESSAGE_DIGESTS["transition_validator"],
        )
        self.assertEqual(
            {key: value for key, value in request.items() if key not in {"task", "messages", "observer"}},
            {"json_output": False, "json_contract": True},
        )
        self.assertFalse({"model", "temperature", "top_p", "client", "timeout"}.intersection(request))
        self.assertEqual(observer_calls[0]["endpoint_name"], "transition_agent")
        self.assertEqual(observer_calls[0]["messages"], request["messages"])
        self.assertFalse(observer_calls[0]["track_usage"])
        self.assertNotIn("trace_site", observer_calls[0])
        self.assertNotIn("api_log_before_tracker", observer_calls[0])
        api_logger.assert_called_once()
        self.assertEqual(api_logger.call_args.args[:2], ("transition_agent", request["messages"]))
        self.assertEqual(api_logger.call_args.args[2], raw_response)
        self.assertEqual(api_logger.call_args.kwargs["metadata"]["current_location_id"], "C01")
        tracker.track.assert_not_called()
        create_client.assert_not_called()

        failing = _FakeFacade(failure=RuntimeError("request timed out"))
        api_logger.reset_mock()
        with mock.patch.object(
            transition_validator, "load_transition_validation_prompt",
            return_value="Transition policy prompt.",
        ), mock.patch(
            "utils.path_encounter_analyzer.build_path_context_for_ai",
            return_value="Known path context.",
        ), mock.patch.object(
            transition_validator, "make_legacy_receipt_observer", return_value=mock.Mock()
        ), mock.patch.object(llm_router.llm, "call", side_effect=failing), mock.patch.object(
            ai_client_factory,
            "create_chat_client",
            side_effect=AssertionError("transition validator constructed a provider client"),
        ) as create_client, mock.patch.object(transition_validator, "debug"), mock.patch.object(
            transition_validator, "info"
        ), mock.patch.object(transition_validator, "warning"), mock.patch.object(
            transition_validator, "error"
        ):
            self.assertEqual(
                transition_validator.validate_transition_request(*arguments),
                {
                    "approved": True,
                    "stop_location": None,
                    "stop_location_name": None,
                    "reason": "Validator error: request timed out",
                    "narrative_guidance": "",
                    "requires_encounter": False,
                    "plot_guidance": None,
                },
            )
        self.assertEqual(len(failing.calls), 1)
        self.assertEqual(failing.calls[0]["task"], "dm_main")
        api_logger.assert_not_called()
        create_client.assert_not_called()

    def test_remaining_compression_and_transition_profiles_keep_model_sources(self) -> None:
        _assert_default_auto_profile(self, "compression")
        _assert_default_auto_profile(self, "dm_main")
        self.assertEqual(
            incremental_compression.get_chat_model_name(),
            ai_client_factory.get_chat_model_name(),
        )
        self.assertEqual(
            transition_validator.get_chat_model_name(),
            ai_client_factory.get_chat_model_name(),
        )

    def test_module_stitcher_router_requests_and_fallbacks(self) -> None:
        stitcher = module_stitcher.ModuleStitcher.__new__(module_stitcher.ModuleStitcher)
        stitcher.provider_stage_errors = []
        fake = _FakeFacade(response='{"safe":false,"reason":"unsafe"}')
        with mock.patch.object(llm_router.llm, "call", side_effect=fake):
            self.assertTrue(stitcher._ai_validate_content_safety({"areas": {}}))
        self.assertEqual(fake.calls[0]["task"], "safety_review")
        self.assertEqual(_message_digest(fake.calls[0]["messages"]), PRE_MIGRATION_MESSAGE_DIGESTS["safety_review"])
        self.assertFalse({"model", "temperature", "timeout", "client"}.intersection(fake.calls[0]))

        stitcher.provider_stage_errors = []
        failing = _FakeFacade(failure=RuntimeError("provider down"))
        with mock.patch.object(llm_router.llm, "call", side_effect=failing):
            self.assertTrue(stitcher._ai_validate_content_safety({"areas": {}}))
        self.assertEqual(len(failing.calls), 1)

        stitcher.provider_stage_errors = []
        failing = _FakeFacade(failure=RuntimeError("provider down"))
        with mock.patch.object(llm_router.llm, "call", side_effect=failing):
            result = stitcher._generate_travel_narration({})
        self.assertEqual(result["travelNarration"], "The party travels to a new region where fresh adventures await.")
        self.assertEqual(len(failing.calls), 1)
        self.assertEqual(failing.calls[0]["task"], "travel_narration")
        self.assertEqual(_message_digest(failing.calls[0]["messages"]), PRE_MIGRATION_MESSAGE_DIGESTS["travel_narration"])

    def test_location_summarizer_router_request_and_failure(self) -> None:
        summarizer = location_summarizer.LocationSummarizer.__new__(location_summarizer.LocationSummarizer)
        summarizer.ai_model = "gpt-6-luna"
        summarizer._format_messages_for_compression = lambda messages: "A journey."
        fake = _FakeFacade(response="Chronicle")
        with mock.patch.object(llm_router.llm, "call", side_effect=fake):
            result = summarizer._generate_ai_chronicle("Start", "End", [], {}, [])
        self.assertEqual(result, "Chronicle\n\n[AI-Generated Chronicle Summary]")
        self.assertEqual(len(fake.calls), 1)
        request = fake.calls[0]
        self.assertEqual(request["task"], "location_summarizer")
        self.assertEqual(_message_digest(request["messages"]), PRE_MIGRATION_MESSAGE_DIGESTS["location_summarizer"])
        self.assertEqual(request["max_tokens"], 650)
        self.assertFalse({"model", "temperature", "timeout", "client"}.intersection(request))

        failing = _FakeFacade(failure=RuntimeError("provider down"))
        with mock.patch.object(llm_router.llm, "call", side_effect=failing), mock.patch.object(
            location_summarizer.time, "sleep", return_value=None
        ):
            result = summarizer._generate_ai_chronicle("Start", "End", [], {}, [])
        self.assertIsNone(result)
        self.assertEqual(len(failing.calls), 3)

    def test_generator_initializers_do_not_create_provider_clients(self) -> None:
        scratch_modules = ROOT / "tmp" / "router-rollout" / "g6" / "modules"
        scratch_modules.mkdir(parents=True, exist_ok=True)
        with mock.patch.object(
            ai_client_factory,
            "create_chat_client",
            side_effect=AssertionError("generator constructed a provider client"),
        ) as create_client, mock.patch.object(
            module_stitcher.os.path, "abspath", return_value=str(scratch_modules)
        ), mock.patch.object(
            module_stitcher.os.path, "exists", return_value=False
        ), mock.patch.object(module_stitcher, "safe_json_dump"):
            with mock.patch.object(module_stitcher.os, "makedirs"):
                stitcher = module_stitcher.ModuleStitcher()
                summarizer = location_summarizer.LocationSummarizer()

        create_client.assert_not_called()
        self.assertFalse(hasattr(stitcher, "client"))
        self.assertFalse(hasattr(summarizer, "client"))

    def test_module_generator_calls_use_facade_and_return_text(self) -> None:
        generator = module_generator.ModuleGenerator.__new__(module_generator.ModuleGenerator)
        generator.prompt_guide = module_generator.ModulePromptGuide()
        generator.adaptation_mode = True
        generator.llm_timeout_seconds = 15
        fake = _FakeFacade(response='  {"name":"Greyreach"}  ')
        with mock.patch.object(llm_router.llm, "call", side_effect=fake):
            result = generator.generate_field("moduleName", {"type": "string"}, {})
        self.assertEqual(result, {"name": "Greyreach"})
        self.assertEqual(fake.calls[0]["task"], "module_generator")
        self.assertFalse({"model", "temperature", "timeout", "client"}.intersection(fake.calls[0]))

    def test_parse_module_params_uses_facade_and_parses_canned_json(self) -> None:
        response = '{"module_name":"Greyreach","num_areas":3,"locations_per_area":6,"level_range":{"min":2,"max":4},"adventure_type":"mixed","plot_themes":"find the lost beacon"}'
        fake = _FakeFacade(response=response)
        with mock.patch.object(llm_router.llm, "call", side_effect=fake):
            result = parse_narrative_to_module_params("A stormbound coast")
        self.assertEqual(result["module_name"], "Greyreach")
        self.assertEqual(fake.calls[0]["task"], "parse_module_params")
        self.assertFalse({"model", "temperature", "timeout", "client"}.intersection(fake.calls[0]))

    def test_module_builder_plot_hooks_request_parse_and_retry_fallback(self) -> None:
        builder = _module_builder()
        fake = _FakeFacade(response='{"plotHookUpdates":[{"locationId":"R01","plotHooks":["Follow the lantern"]}]}')
        with mock.patch.object(llm_router.llm, "call", side_effect=fake):
            result = builder._generate_enhanced_plot_hooks(
                "A001", {"areaName": "Ash Coast", "locations": []}, [{"id": "PP001"}], [],
            )
        self.assertEqual(result, [{"locationId": "R01", "plotHooks": ["Follow the lantern"]}])
        request = fake.calls[0]
        self.assertEqual(request["task"], "update_plot_hooks")
        self.assertEqual(_message_digest(request["messages"]), PRE_MIGRATION_MESSAGE_DIGESTS["update_plot_hooks"])
        self.assertEqual(request["response_format"], {"type": "json_object"})
        self.assertFalse({"model", "temperature", "timeout", "client"}.intersection(request))

        failing = _FakeFacade(failure=RuntimeError("rate limit"))
        with mock.patch.object(llm_router.llm, "call", side_effect=failing), mock.patch.object(
            ai_client_factory, "handle_provider_error", return_value={"should_fallback": True}
        ) as handler:
            self.assertEqual(builder._generate_enhanced_plot_hooks("A001", {}, [], [],), [])
        self.assertEqual(len(failing.calls), 3)
        self.assertTrue(all(call["task"] == "update_plot_hooks" for call in failing.calls))
        self.assertEqual(handler.call_count, 3)

    def test_module_builder_unify_plots_request_parse_and_retry_fallback(self) -> None:
        builder = _module_builder()
        fake = _FakeFacade(response='{"plotTitle":"Unified","plotPoints":[]}')
        with mock.patch.object(llm_router.llm, "call", side_effect=fake):
            builder.unify_plots()
        request = fake.calls[0]
        self.assertEqual(request["task"], "unify_plots")
        self.assertEqual(_message_digest(request["messages"]), PRE_MIGRATION_MESSAGE_DIGESTS["unify_plots"])
        self.assertEqual(request["response_format"], {"type": "json_object"})
        self.assertFalse({"model", "temperature", "timeout", "client"}.intersection(request))

        failing = _FakeFacade(failure=RuntimeError("rate limit"))
        with mock.patch.object(llm_router.llm, "call", side_effect=failing), mock.patch.object(
            ai_client_factory, "handle_provider_error", return_value={"should_fallback": True}
        ) as handler:
            builder.unify_plots()
        self.assertEqual(len(failing.calls), 3)
        self.assertTrue(all(call["task"] == "unify_plots" for call in failing.calls))
        self.assertEqual(handler.call_count, 3)

    def test_retryable_failure_attempts_and_fallback_results(self) -> None:
        cases = (
            (
                "area_thematic",
                area_generator,
                "generate_thematic_names",
                "generate_thematic_names",
                _area_thematic_names,
                ["Ancient Entrance"],
                False,
            ),
            (
                "area_name",
                area_generator,
                "generate_area_name",
                "generate_area_name",
                _area_name_and_description,
                ("Ash Coast", "A high wilderness area known as Ash Coast."),
                False,
            ),
            (
                "area_description",
                area_generator,
                "generate_area_description",
                "generate_area_description",
                _area_description,
                "Ash Coast is a untamed wilderness area with moderate challenges suitable for level 1 adventurers.",
                False,
            ),
            (
                "location_field",
                location_generator,
                "location_generator",
                "generate_location_field",
                _location_field,
                None,
                True,
            ),
            (
                "location_batch",
                location_generator,
                "location_generator_batch",
                "generate_location_batch",
                _location_batch,
                None,
                True,
            ),
            (
                "plot_field",
                plot_generator,
                "plot_generator",
                "generate_plot_field",
                _plot_field,
                None,
                True,
            ),
            (
                "plot_structure",
                plot_generator,
                "plot_generator",
                "generate_plot_structure",
                _plot_structure,
                None,
                True,
            ),
        )

        for label, owner, task, error_context, operation, expected, raises in cases:
            with self.subTest(operation=label):
                ai_client_factory.reset_fallback_status()
                fake = _FakeFacade(failure=RuntimeError("rate limit"))
                with contextlib.ExitStack() as stack:
                    stack.enter_context(
                        mock.patch.object(llm_router.llm, "call", side_effect=fake)
                    )
                    create_client = stack.enter_context(
                        mock.patch.object(
                            ai_client_factory,
                            "create_chat_client",
                            side_effect=AssertionError(
                                "generator constructed a provider client"
                            ),
                        )
                    )
                    error_handler = stack.enter_context(
                        mock.patch.object(
                            owner,
                            "handle_provider_error",
                            wraps=owner.handle_provider_error,
                        )
                    )
                    stack.enter_context(
                        mock.patch.object(
                            area_generator.random,
                            "choice",
                            side_effect=lambda values: values[0],
                        )
                    )
                    stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
                    if raises:
                        with self.assertRaisesRegex(RuntimeError, "rate limit"):
                            operation()
                    else:
                        self.assertEqual(operation(), expected)

                self.assertEqual(len(fake.calls), 3)
                self.assertTrue(all(call["task"] == task for call in fake.calls))
                self.assertTrue(all(call["json_output"] is False for call in fake.calls))
                self.assertEqual(
                    [call.args[1] for call in error_handler.call_args_list],
                    [error_context] * 3,
                )
                create_client.assert_not_called()
                ai_client_factory.reset_fallback_status()

    def test_character_effects_validator_router_request_parse_and_failure(self) -> None:
        _assert_default_auto_profile(self, "character_validator")
        validator = self._new_character_effects_validator()
        validator.build_categorization_prompt = mock.Mock(return_value="effects prompt")
        validator.get_effects_system_prompt = mock.Mock(return_value="effects system")
        character = {
            "name": "A",
            "temporaryEffects": [{"name": "Wound", "description": "damage"}],
        }
        fake = _ObservedFacade(
            '{"temporaryEffects":[],"injuries":[{"name":"Lingering Wound"}]}'
        )
        tracker = mock.Mock()
        api_logger = mock.Mock()
        trace_writer = mock.Mock()
        observer_calls = []

        def observer_factory(**kwargs: Any) -> Callable[[Any, Any], None]:
            observer_calls.append(copy.deepcopy(kwargs))
            return make_legacy_receipt_observer(
                tracker_getter=lambda: tracker,
                api_logger=api_logger,
                trace_writer=trace_writer,
                trace_gate=lambda: True,
                **kwargs,
            )

        with mock.patch.object(
            character_effects_validator,
            "make_legacy_receipt_observer",
            side_effect=observer_factory,
        ), mock.patch.object(
            character_effects_validator, "USAGE_TRACKING_AVAILABLE", True
        ), mock.patch.object(
            llm_router.llm, "call", side_effect=fake
        ), mock.patch.object(
            ai_client_factory,
            "create_chat_client",
            side_effect=AssertionError("effects validator constructed a provider client"),
        ) as create_client:
            result = validator.ai_categorize_effects(character, {"day": 1})

        self.assertEqual(result["temporaryEffects"], [])
        self.assertEqual(result["injuries"], [{"name": "Lingering Wound"}])
        self.assertEqual(len(fake.calls), 1)
        request = fake.calls[0]
        self.assertEqual(request["task"], "character_validator")
        self.assertEqual(
            _message_digest(request["messages"]),
            PRE_MIGRATION_MESSAGE_DIGESTS["character_effects_validator"],
        )
        self.assertEqual(
            {key: value for key, value in request.items() if key not in {"task", "messages"}},
            {"json_output": False},
        )
        self.assertFalse(
            {"model", "temperature", "top_p", "timeout", "client", "extra_body"}.intersection(request)
        )
        self.assertEqual(observer_calls, [{"track_usage": True}])
        tracker.track.assert_called_once()
        api_logger.assert_not_called()
        trace_writer.assert_not_called()
        create_client.assert_not_called()

        failing = _FakeFacade(failure=RuntimeError("provider down"))
        failure_character = {
            "name": "A",
            "temporaryEffects": [{"name": "Wound", "description": "damage"}],
        }
        with mock.patch.object(
            character_effects_validator,
            "make_legacy_receipt_observer",
            return_value=mock.Mock(),
        ), mock.patch.object(llm_router.llm, "call", side_effect=failing):
            failure_result = validator.ai_categorize_effects(
                failure_character, {"day": 1}
            )
        self.assertIs(failure_result, failure_character)
        self.assertEqual(len(failing.calls), 1)

    def test_character_validator_facade_requests_parse_batch_and_accounting(self) -> None:
        _assert_default_auto_profile(self, "validation")
        character = {
            "name": "A",
            "equipment": [
                {"item_name": "odd item", "item_type": "miscellaneous"}
            ],
            "currency": {"gold": 1, "silver": 0, "copper": 0},
        }
        cases = (
            (
                "ai_validate_armor_class",
                '{"validated_character_data":{"armorClass":14},"corrections_made":[]}',
                "character_validator_armor_class",
                "validate_character_data",
            ),
            (
                "ai_validate_inventory_categories",
                '{"equipment":[{"item_name":"odd item","item_type":"weapon"}],"corrections_made":[]}',
                "character_validator_inventory_categories",
                "validate_character_effects",
            ),
            (
                "ai_validate_all_batched",
                '{"ac_validation":{"correction_needed":true,"calculated_ac":14},"inventory_corrections":{"equipment":[{"item_name":"odd item","item_type":"weapon"}]},"currency_consolidation":{"currency":{"gold":5}}}',
                "character_validator_all_batched",
                "validate_character_data",
            ),
            (
                "ai_consolidate_inventory",
                '{"inventory":{"currency":{"gold":5}}}',
                "character_validator_consolidate_inventory",
                "validate_character_effects",
            ),
        )

        for operation, response, digest_key, purpose in cases:
            with self.subTest(operation=operation):
                validator = self._new_character_validator()
                tracker = mock.Mock()
                api_logger = mock.Mock()
                trace_writer = mock.Mock()
                observer_calls = []
                fake = _ObservedFacade(response)
                legacy_context = {
                    "endpoint": "character_validation",
                    "purpose": purpose,
                }

                def observer_factory(**kwargs: Any) -> Callable[[Any, Any], None]:
                    observer_calls.append(copy.deepcopy(kwargs))
                    return make_legacy_receipt_observer(
                        tracker_getter=lambda: tracker,
                        api_logger=api_logger,
                        trace_writer=trace_writer,
                        trace_gate=lambda: True,
                        **kwargs,
                    )

                with mock.patch.dict(
                    sys.modules,
                    {
                        "updates.update_character_info": SimpleNamespace(
                            deep_merge_dict=self._merge_validation_data
                        )
                    },
                ), mock.patch.object(
                    character_validator,
                    "make_legacy_receipt_observer",
                    side_effect=observer_factory,
                ), mock.patch.object(
                    character_validator, "USAGE_TRACKING_AVAILABLE", True
                ), mock.patch.object(
                    llm_router.llm, "call", side_effect=fake
                ), mock.patch.object(
                    ai_client_factory,
                    "create_chat_client",
                    side_effect=AssertionError("character validator constructed a provider client"),
                ) as create_client:
                    result = getattr(validator, operation)(copy.deepcopy(character))

                self.assertEqual(len(fake.calls), 1)
                request = fake.calls[0]
                self.assertEqual(request["task"], "validation")
                self.assertEqual(
                    _message_digest(request["messages"]),
                    PRE_MIGRATION_MESSAGE_DIGESTS[digest_key],
                )
                self.assertEqual(
                    {key: value for key, value in request.items() if key not in {"task", "messages"}},
                    {"json_output": False},
                )
                self.assertFalse(
                    {"model", "temperature", "top_p", "timeout", "client", "extra_body"}.intersection(request)
                )
                self.assertEqual(len(observer_calls), 1)
                self.assertEqual(observer_calls[0]["legacy_context"], legacy_context)
                self.assertTrue(observer_calls[0]["track_usage"])
                for absent in (
                    "trace_site",
                    "endpoint_name",
                    "messages",
                    "api_log_before_tracker",
                ):
                    self.assertNotIn(absent, observer_calls[0])
                tracker.track.assert_called_once()
                tracker_context = tracker.track.call_args.args[1]
                self.assertEqual(tracker_context["endpoint"], "character_validation")
                self.assertEqual(tracker_context["purpose"], purpose)
                api_logger.assert_not_called()
                trace_writer.assert_not_called()
                create_client.assert_not_called()

                if operation == "ai_validate_armor_class":
                    self.assertEqual(result["armorClass"], 14)
                    self.assertEqual(result["equipment"], character["equipment"])
                elif operation == "ai_validate_inventory_categories":
                    self.assertEqual(result["equipment"][0]["item_type"], "weapon")
                    self.assertEqual(result["currency"], character["currency"])
                elif operation == "ai_validate_all_batched":
                    self.assertEqual(result["armorClass"], 14)
                    self.assertEqual(result["equipment"][0]["item_type"], "weapon")
                    self.assertEqual(result["currency"]["gold"], 5)
                else:
                    self.assertEqual(result["inventory"], {"currency": {"gold": 5}})

        failing_cases = (
            ("ai_validate_armor_class", 1),
            ("ai_validate_inventory_categories", 3),
            ("ai_validate_all_batched", 1),
            ("ai_consolidate_inventory", 3),
        )
        for operation, attempts in failing_cases:
            with self.subTest(failure_operation=operation):
                validator = self._new_character_validator()
                original = copy.deepcopy(character)
                failing = _FakeFacade(failure=RuntimeError("provider down"))
                with mock.patch.object(
                    character_validator,
                    "make_legacy_receipt_observer",
                    return_value=mock.Mock(),
                ), mock.patch.object(
                    llm_router.llm, "call", side_effect=failing
                ), mock.patch.dict(
                    sys.modules,
                    {
                        "updates.update_character_info": SimpleNamespace(
                            deep_merge_dict=self._merge_validation_data
                        )
                    },
                ):
                    result = getattr(validator, operation)(original)
                self.assertIs(result, original)
                self.assertEqual(len(failing.calls), attempts)
                if attempts > 1:
                    self.assertTrue(
                        all(call["messages"] == failing.calls[0]["messages"] for call in failing.calls)
                    )

    def test_npc_codex_generator_router_request_parse_and_failure(self) -> None:
        _assert_default_auto_profile(self, "npc_builder")
        module_content = {
            "plot_content": "PLOT",
            "area_content": "AREA",
            "character_files": ["Aster"],
        }
        fake = _FakeFacade(
            response='Candidates: [{"name":"Aster","source":"plot_character"},{"bad":true}] Done.'
        )
        with mock.patch.object(
            llm_router.llm, "call", side_effect=fake
        ), mock.patch.object(
            ai_client_factory,
            "create_chat_client",
            side_effect=AssertionError("NPC codex generator constructed a provider client"),
        ) as create_client:
            result = npc_codex_generator.extract_npcs_with_ai(module_content, "Greyreach")

        self.assertEqual(result, [{"name": "Aster", "source": "plot_character"}])
        self.assertEqual(len(fake.calls), 1)
        request = fake.calls[0]
        self.assertEqual(request["task"], "npc_builder")
        self.assertEqual(
            _message_digest(request["messages"]),
            PRE_MIGRATION_MESSAGE_DIGESTS["npc_codex_generator"],
        )
        self.assertEqual(
            {key: value for key, value in request.items() if key not in {"task", "messages"}},
            {"json_output": False},
        )
        self.assertFalse(
            {"model", "temperature", "top_p", "timeout", "client", "extra_body", "observer"}.intersection(request)
        )
        create_client.assert_not_called()

        failing = _FakeFacade(failure=RuntimeError("provider down"))
        with mock.patch.object(llm_router.llm, "call", side_effect=failing):
            self.assertEqual(
                npc_codex_generator.extract_npcs_with_ai(module_content, "Greyreach"),
                [],
            )
        self.assertEqual(len(failing.calls), 1)

    def test_toolkit_adaptation_author_facade_contract(self) -> None:
        fixture_path = ROOT / "scripts" / "fixtures" / "toolkit_adaptation_dossier_valid.json"
        with fixture_path.open("r", encoding="utf-8") as handle:
            dossier = json.load(handle)
        metadata = {
            "attempt_id": "attempt-test-1",
            "source_title": dossier["source_title"],
            "source_hash": dossier["source_hash"],
            "source_profile": dossier["source_profile"],
            "rights_class": dossier["rights_class"],
        }
        source_context = {
            "source_title": dossier["source_title"],
            "source_profile_hint": "catalogue",
            "bounded_excerpt": "A catalogue of useful lanterns.",
        }
        task = toolkit_adaptation_author.ADAPTATION_AUTHOR_TASK_ID
        profile = llm_router.llm.resolve_profile(task)
        self.assertEqual(profile["provider_name"], _DEFAULT_AUTO_PROVIDER)
        self.assertEqual(profile["model"], _DEFAULT_AUTO_MODEL)
        resolver_calls = []

        def resolver(task_id: str, model: str) -> Dict[str, Any]:
            resolver_calls.append((task_id, model))
            return {"model": model, "reasoning_effort": "medium", "verbosity": "medium"}

        fake = _FakeFacade(response=json.dumps(dossier, ensure_ascii=True))
        with mock.patch.object(
            ai_client_factory,
            "create_chat_client",
            side_effect=AssertionError("adaptation author constructed a provider client"),
        ) as create_client, mock.patch.object(
            toolkit_adaptation_author.llm, "call", side_effect=fake
        ):
            result = toolkit_adaptation_author.run_llm_adaptation_author(
                source_context,
                metadata,
                parameter_resolver=resolver,
            )
        self.assertEqual(result["status"], toolkit_adaptation_author.RUNNER_STATUS_SUCCESS)
        self.assertEqual(result["dossier"]["source_hash"], dossier["source_hash"])
        self.assertEqual(resolver_calls, [(task, _DEFAULT_AUTO_MODEL)])
        self.assertEqual(len(fake.calls), 1)
        request = fake.calls[0]
        self.assertEqual(request["task"], task)
        self.assertIs(request["json_output"], False)
        self.assertEqual(
            _message_digest(request["messages"]),
            PRE_MIGRATION_MESSAGE_DIGESTS["toolkit_adaptation_author"],
        )
        self.assertEqual(
            request["response_format"]["type"],
            "json_object",
        )
        self.assertFalse(
            {"model", "temperature", "top_p", "timeout", "client", "extra_body", "observer"}.intersection(request)
        )
        self.assertNotIn("observer", request)
        create_client.assert_not_called()

        failing = _FakeFacade(failure=RuntimeError("provider down"))
        with mock.patch.object(toolkit_adaptation_author.llm, "call", side_effect=failing):
            failed = toolkit_adaptation_author.run_llm_adaptation_author(
                source_context, metadata, parameter_resolver=resolver
            )
        self.assertEqual(failed["status"], toolkit_adaptation_author.RUNNER_STATUS_PROVIDER_FAILED)
        self.assertEqual(len(failing.calls), 1)

    def test_toolkit_adaptation_auditor_facade_contract(self) -> None:
        from scripts import test_toolkit_adaptation_auditor as auditor_fixtures

        packet = auditor_fixtures._packet()
        response = auditor_fixtures._base_response(
            packet, toolkit_adaptation_auditor.AUDITOR_DECISION_REVISE
        )
        response["rebuild_directive"] = {
            "action": "fresh_build",
            "target": "staging",
            "basis": "revised_dossier",
            "guidance": ["Use the canonical destination identity from the semantic gate evidence."],
        }
        task = toolkit_adaptation_auditor.ADAPTATION_AUDITOR_TASK_ID
        profile = llm_router.llm.resolve_profile(task)
        self.assertEqual(profile["provider_name"], _DEFAULT_AUTO_PROVIDER)
        self.assertEqual(profile["model"], _DEFAULT_AUTO_MODEL)
        resolver_calls = []

        def resolver(task_id: str, model: str) -> Dict[str, Any]:
            resolver_calls.append((task_id, model))
            return {"model": model, "temperature": 0.2}

        fake = _FakeFacade(response=auditor_fixtures._raw(response))
        with mock.patch.object(
            ai_client_factory,
            "create_chat_client",
            side_effect=AssertionError("adaptation auditor constructed a provider client"),
        ) as create_client, mock.patch.object(
            toolkit_adaptation_auditor.llm, "call", side_effect=fake
        ):
            result = toolkit_adaptation_auditor.run_llm_adaptation_auditor(
                packet, parameter_resolver=resolver
            )
        self.assertEqual(result["status"], toolkit_adaptation_auditor.AUDITOR_STATUS_SUCCESS)
        self.assertEqual(result["decision"], toolkit_adaptation_auditor.AUDITOR_DECISION_REVISE)
        self.assertEqual(resolver_calls, [(task, _DEFAULT_AUTO_MODEL)])
        self.assertEqual(len(fake.calls), 1)
        request = fake.calls[0]
        self.assertEqual(request["task"], task)
        self.assertIs(request["json_output"], False)
        self.assertEqual(
            _message_digest(request["messages"]),
            PRE_MIGRATION_MESSAGE_DIGESTS["toolkit_adaptation_auditor"],
        )
        self.assertEqual(request["response_format"], {"type": "json_object"})
        self.assertFalse(
            {"model", "temperature", "top_p", "timeout", "client", "extra_body", "observer"}.intersection(request)
        )
        create_client.assert_not_called()

        failing = _FakeFacade(failure=RuntimeError("provider down"))
        with mock.patch.object(toolkit_adaptation_auditor.llm, "call", side_effect=failing):
            failed = toolkit_adaptation_auditor.run_llm_adaptation_auditor(
                packet, parameter_resolver=resolver
            )
        self.assertEqual(failed["status"], toolkit_adaptation_auditor.AUDITOR_STATUS_PROVIDER_FAILED)
        self.assertEqual(len(failing.calls), 1)

    def test_toolkit_adaptation_convergence_facade_contract(self) -> None:
        task = toolkit_adaptation_runtime.ADAPTATION_CONVERGENCE_TASK_ID
        profile = llm_router.llm.resolve_profile(task)
        self.assertEqual(profile["provider_name"], _DEFAULT_AUTO_PROVIDER)
        self.assertEqual(profile["model"], _DEFAULT_AUTO_MODEL)
        context = {
            "contract_version": "toolkit_adaptation_publication_convergence.v1",
            "attempt_id": "contract-attempt",
            "attempt_number": 1,
            "revision_number": 0,
            "source_hash": "a" * 64,
            "staging_identity": {
                "stage_id": "contract-attempt:revision_000",
                "module_slug": "Contract_Module",
                "path": "tmp/router-rollout/g6/contract-attempt/revision_000",
                "output_directory": "tmp/router-rollout/g6/contract-attempt/revision_000",
            },
            "budget": {
                "current_attempt": 0,
                "max_attempts": 2,
                "max_operations_per_round": 3,
                "operation_timeout_seconds": 30,
            },
            "request": {"operation": "bounded_repair"},
            "validation_context": {
                "status": "blocked",
                "repairable": True,
                "repair_requests": [{"code": "destination_alias"}],
                "source_reference_ids": ["source_manifest"],
                "canonical_location_ids": ["LOC01"],
                "authored_target_ids": [],
                "approved_monster_ids": [],
                "approved_monster_identities": ["Cave Guardian"],
                "monster_reference_keys": ["cave_guardians"],
                "quantity_bounds": {"cave_guardians": {"min": 1, "max": 2}},
                "topology": {"location_ids": ["LOC01"], "edges": []},
            },
        }
        resolver_calls = []

        def resolver(task_id: str, model: str) -> Dict[str, Any]:
            resolver_calls.append((task_id, model))
            return {"model": model}

        fake = _FakeFacade(response='{"status":"success","proposal":{"operation":"bounded_repair"}}')
        with mock.patch.object(
            ai_client_factory,
            "create_chat_client",
            side_effect=AssertionError("convergence callback constructed a provider client"),
        ) as create_client, mock.patch.object(
            toolkit_adaptation_runtime.llm, "call", side_effect=fake
        ):
            result = toolkit_adaptation_runtime.adaptation_convergence_callback(
                context, parameter_resolver=resolver
            )
        self.assertEqual(result["status"], "success")
        self.assertEqual(resolver_calls, [(task, _DEFAULT_AUTO_MODEL)])
        self.assertEqual(len(fake.calls), 1)
        request = fake.calls[0]
        self.assertEqual(request["task"], task)
        self.assertIs(request["json_output"], False)
        self.assertEqual(
            _message_digest(request["messages"]),
            PRE_MIGRATION_MESSAGE_DIGESTS["toolkit_adaptation_convergence"],
        )
        self.assertEqual(request["response_format"], {"type": "json_object"})
        self.assertFalse(
            {"model", "temperature", "top_p", "timeout", "client", "extra_body", "observer"}.intersection(request)
        )
        create_client.assert_not_called()

        failing = _FakeFacade(failure=RuntimeError("provider down"))
        with mock.patch.object(toolkit_adaptation_runtime.llm, "call", side_effect=failing):
            failed = toolkit_adaptation_runtime.adaptation_convergence_callback(
                context, parameter_resolver=resolver
            )
        self.assertEqual(failed["reason_code"], "provider_unknown")
        self.assertEqual(len(failing.calls), 1)

        factory_calls = []
        factory_facade = _FakeFacade(
            response='{"status":"success","proposal":{"operation":"bounded_repair"}}'
        )

        def facade_factory() -> _FakeFacade:
            factory_calls.append("called")
            return factory_facade

        with mock.patch.object(
            ai_client_factory,
            "create_chat_client",
            side_effect=AssertionError("convergence factory constructed a provider client"),
        ) as create_client:
            factory_result = toolkit_adaptation_runtime.adaptation_convergence_callback(
                context,
                client_factory=facade_factory,
                parameter_resolver=resolver,
            )
        self.assertEqual(factory_result["status"], "success")
        self.assertEqual(factory_calls, ["called"])
        self.assertEqual(len(factory_facade.calls), 1)
        self.assertEqual(factory_facade.calls[0]["task"], task)
        self.assertIs(factory_facade.calls[0]["json_output"], False)
        self.assertEqual(factory_facade.calls[0]["response_format"], {"type": "json_object"})
        create_client.assert_not_called()

    def test_migrated_files_have_no_direct_chat_transport(self) -> None:
        for path in _GENERATOR_PATHS + (
            "core/managers/campaign_manager.py",
            "core/managers/level_up_manager.py",
            "core/managers/storage_processor.py",
            "core/memory/players_diary.py",
            "core/memory/session_diary.py",
            "core/memory/story_so_far_compiler.py",
            "core/validation/character_effects_validator.py",
            "core/validation/character_validator.py",
            "core/validation/npc_codex_generator.py",
            "utils/homebrewery_adventure_writer.py",
            "utils/level_up.py",
            "utils/npc_name_canonicalizer.py",
            "utils/npc_reconciler.py",
            "utils/prompt_sanitizer.py",
            "utils/quest_player_formatter.py",
            "utils/reconcile_location_state.py",
            "utils/spatial_contract.py",
            "utils/startup_wizard.py",
            "utils/toolkit_adaptation_author.py",
            "utils/toolkit_adaptation_auditor.py",
            "utils/toolkit_homebrew_normalizer.py",
            "utils/toolkit_llm_final_reconciliation.py",
            "web/extensions/toolkit_adaptation_runtime.py",
            "web/extensions/toolkit_llm_classification.py",
            "updates/plot_update.py",
            "updates/update_character_effects.py",
            "updates/update_character_info.py",
            "updates/update_encounter.py",
            "scripts/run_critical_narrative_repair.py",
        ):
            with self.subTest(path=path):
                source = (ROOT / path).read_text(encoding="utf-8")
                tree = ast.parse(source, filename=path)
                direct_calls = [
                    f"{path}:{node.lineno}"
                    for node in ast.walk(tree)
                    if isinstance(node, ast.Call)
                    and _call_name(node).endswith("chat.completions.create")
                ]
                self.assertEqual(direct_calls, [])

        web_path = "web/web_interface.py"
        web_tree = ast.parse((ROOT / web_path).read_text(encoding="utf-8"), filename=web_path)
        web_chat_functions = {
            node.name: node
            for node in web_tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name in {
                "fetch_npc_descriptions",
                "_generate_toolkit_npc_description",
                "promote_to_bestiary",
            }
        }
        self.assertEqual(
            set(web_chat_functions),
            {
                "fetch_npc_descriptions",
                "_generate_toolkit_npc_description",
                "promote_to_bestiary",
            },
        )
        for function_name, function_node in web_chat_functions.items():
            with self.subTest(web_function=function_name):
                direct_calls = [
                    f"{web_path}:{node.lineno}"
                    for node in ast.walk(function_node)
                    if isinstance(node, ast.Call)
                    and _call_name(node).endswith("chat.completions.create")
                ]
                self.assertEqual(direct_calls, [])
        web_calls = [
            _call_name(node)
            for node in ast.walk(web_tree)
            if isinstance(node, ast.Call)
        ]
        self.assertEqual(web_calls.count("client.images.generate"), 2)
        self.assertEqual(web_calls.count("client.audio.speech.create"), 1)

    def test_homebrew_normalizer_ordered_passes_and_failure_policy(self) -> None:
        source_text = "# Test Adventure\n\nA crypt and ruined gatehouse."
        legacy_payload = {
            "title": "Crypt of Ash",
            "author": "Unknown",
            "description": "A short ruin crawl.",
            "estimated_level_min": 1,
            "estimated_level_max": 2,
            "locations": [{"name": "Ruined Gate", "summary": "Collapsed outer wall"}],
            "npc_seeds": [{"name": "Caretaker Noll", "role": "Guide"}],
            "monster_refs": ["Skeleton"],
            "assumptions": ["Author inferred from style clues."],
            "warnings": [{"type": "metadata_inferred", "message": "Author not explicit."}],
            "grounded_facts": ["The adventure references a crypt and gatehouse."],
            "builder_narrative": "Grounded builder summary.",
        }
        response_texts = [
            json.dumps({
                "extracted_atoms": [{
                    "type": "npc",
                    "name": "Caretaker Noll",
                    "summary": "Gravekeeper",
                    "source_refs": [{"line_start": 1, "excerpt": "Noll guards"}],
                }]
            }),
            json.dumps({"decisions": []}),
            json.dumps({
                "plot_beats": [{"label": "Enter the crypt"}],
                "puzzle_chains": [],
                "clue_dependencies": [],
                "trials": [],
                "endings": [],
                "assumptions": [],
                "unresolved": [],
            }),
            json.dumps(legacy_payload),
            json.dumps({"operations": [{"operation": "additive_test"}]}),
        ]
        digest_keys = (
            "toolkit_homebrew_section",
            "toolkit_homebrew_identity",
            "toolkit_homebrew_topology",
            "toolkit_homebrew_legacy",
            "toolkit_homebrew_repair",
        )
        cases = (
            ("success", None),
            ("section", 0),
            ("identity", 1),
            ("topology", 2),
            ("legacy", 3),
            ("repair", 4),
        )
        scratch_root = ROOT / "tmp" / "router-rollout" / "g6"
        scratch_root.mkdir(parents=True, exist_ok=True)
        blocked_fidelity = {
            "status": "blocked",
            "findings": [{
                "repairable": True,
                "code": "test_gap",
                "evidence": "test",
            }],
        }
        clean_fidelity = {"status": "clean", "findings": []}

        for case_name, failure_index in cases:
            with self.subTest(case=case_name):
                with tempfile.TemporaryDirectory(
                    prefix="72-homebrew-contract-", dir=str(scratch_root)
                ) as temp_dir:
                    case_root = Path(temp_dir)
                    source_path = case_root / "source.md"
                    workspace = case_root / "workspace"
                    source_path.write_text(source_text, encoding="utf-8")
                    workspace.mkdir(parents=True)
                    ensure_workspace_placeholders(workspace)

                    calls: List[Dict[str, Any]] = []

                    def facade_call(**kwargs: Any) -> str:
                        calls.append(copy.deepcopy(kwargs))
                        call_index = len(calls) - 1
                        if call_index == failure_index:
                            raise RuntimeError(f"provider failure at {case_name}")
                        return response_texts[call_index]

                    def model_config(_task: str, fallback: str) -> Dict[str, Any]:
                        return {
                            "model": fallback,
                            "temperature": 0.2,
                            "extra_body": {},
                        }

                    with mock.patch.object(
                        toolkit_homebrew_normalizer,
                        "ENABLE_ACCURATE_INGEST_MULTI_PASS",
                        True,
                    ), mock.patch.object(
                        toolkit_homebrew_normalizer,
                        "ENABLE_NORMALIZATION_FIDELITY_AUDIT",
                        True,
                    ), mock.patch.object(
                        toolkit_homebrew_normalizer,
                        "ENABLE_NORMALIZATION_FIDELITY_REPAIR",
                        True,
                    ), mock.patch.object(
                        toolkit_homebrew_normalizer,
                        "NORMALIZATION_FIDELITY_MAX_REPAIR_ATTEMPTS",
                        1,
                    ), mock.patch.object(
                        toolkit_homebrew_normalizer,
                        "ENABLE_ACCURATE_INGEST_BLUEPRINT_HANDOFF",
                        False,
                    ), mock.patch.object(
                        toolkit_homebrew_normalizer,
                        "run_normalization_fidelity_audit",
                        side_effect=[
                            copy.deepcopy(blocked_fidelity),
                            copy.deepcopy(clean_fidelity),
                        ],
                    ), mock.patch.object(
                        toolkit_homebrew_normalizer,
                        "validate_repair_operations",
                        return_value=([{"operation": "additive_test"}], []),
                    ), mock.patch.object(
                        toolkit_homebrew_normalizer,
                        "apply_repair_operations",
                        side_effect=lambda packet, _ops: packet,
                    ), mock.patch.object(
                        toolkit_homebrew_normalizer,
                        "get_model_config",
                        side_effect=model_config,
                    ), mock.patch.object(
                        toolkit_homebrew_normalizer.llm,
                        "call",
                        side_effect=facade_call,
                    ), mock.patch.object(
                        ai_client_factory,
                        "create_chat_client",
                        side_effect=AssertionError(
                            "homebrew normalizer constructed a provider client"
                        ),
                    ) as create_client:
                        result = toolkit_homebrew_normalizer.normalize_homebrew_upload(
                            source_path=source_path,
                            workspace=workspace,
                            preflight={"source_readable": True},
                            source_rights_class="user_authored",
                        )

                    expected_count = 4 if failure_index == 3 else 5
                    self.assertEqual(len(calls), expected_count)
                    create_client.assert_not_called()
                    for index, request in enumerate(calls):
                        self.assertEqual(request["task"], "builders")
                        self.assertIs(request["json_output"], False)
                        self.assertFalse({
                            "model", "temperature", "top_p", "timeout", "client",
                            "extra_body", "observer",
                        }.intersection(request))
                        if failure_index is None or index <= failure_index:
                            self.assertEqual(
                                _message_digest(request["messages"]),
                                PRE_MIGRATION_MESSAGE_DIGESTS[digest_keys[index]],
                            )

                    if failure_index is None:
                        self.assertEqual(result["status"], "success")
                        self.assertEqual(len(calls), len(digest_keys))
                        self.assertEqual(
                            [call["task"] for call in calls], ["builders"] * 5
                        )
                        self.assertEqual(
                            [
                                _message_digest(call["messages"])
                                for call in calls
                            ],
                            [PRE_MIGRATION_MESSAGE_DIGESTS[key] for key in digest_keys],
                        )
                    elif failure_index == 0:
                        self.assertEqual(result["status"], "success")
                        self.assertEqual(
                            result["normalization_report"]["multipass"]["degraded_sections"],
                            1,
                        )
                    elif failure_index == 1:
                        self.assertEqual(result["status"], "success")
                        self.assertTrue(
                            result["normalization_report"]["multipass"]["identity_degraded"]
                        )
                    elif failure_index == 2:
                        self.assertEqual(result["status"], "success")
                        self.assertTrue(
                            result["normalization_report"]["multipass"]["topology_degraded"]
                        )
                    elif failure_index == 3:
                        self.assertEqual(result["status"], "failed")
                        self.assertIn("normalizer_provider_failed", result["error"])
                    else:
                        self.assertEqual(result["status"], "success")
                        self.assertEqual(
                            result["normalization_report"]["repair"]["repair_status"],
                            "provider_failed",
                        )

    def test_final_reconciliation_facade_request_and_terminal_failure(self) -> None:
        task = toolkit_llm_final_reconciliation.FINAL_RECONCILIATION_TASK_ID
        self.assertEqual(task, "toolkit_final_reconciliation")
        profile = llm_router.llm.resolve_profile(task)
        self.assertEqual(profile["model"], _DEFAULT_AUTO_MODEL)
        self.assertEqual(profile["provider_name"], _DEFAULT_AUTO_PROVIDER)

        brief = {
            "job_id": "contract-job",
            "source_fidelity_status": "degraded",
            "editable_surfaces": [],
        }
        raw_text = json.dumps({
            "version": toolkit_llm_final_reconciliation.FINAL_RECONCILIATION_PATCH_VERSION,
            "status": "ready",
            "source_fidelity_claim": "reconciled_degraded",
            "publication_intent": "playable_module",
            "decisions": [],
            "file_patches": [],
        })
        fake = _FakeFacade(response=raw_text)
        with mock.patch.object(
            ai_client_factory,
            "create_chat_client",
            side_effect=AssertionError(
                "final reconciliation constructed a provider client"
            ),
        ) as create_client, mock.patch.object(
            toolkit_llm_final_reconciliation.llm,
            "call",
            side_effect=fake,
        ):
            result = toolkit_llm_final_reconciliation.run_llm_final_editor(brief)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["raw_response_text"], raw_text)
        self.assertEqual(
            result["model"],
            ai_client_factory.get_chat_completion_params(
                task, model_config.DM_MAIN_MODEL
            )["model"],
        )
        self.assertEqual(len(fake.calls), 1)
        request = fake.calls[0]
        self.assertEqual(request["task"], task)
        self.assertIs(request["json_output"], False)
        self.assertEqual(
            _message_digest(request["messages"]),
            PRE_MIGRATION_MESSAGE_DIGESTS["toolkit_final_reconciliation"],
        )
        self.assertEqual(
            {key: value for key, value in request.items() if key not in {"task", "messages"}},
            {"json_output": False},
        )
        self.assertFalse({
            "model", "temperature", "top_p", "timeout", "client", "extra_body",
            "observer",
        }.intersection(request))
        self.assertNotIn("observer", request)
        create_client.assert_not_called()

        failing = _FakeFacade(failure=RuntimeError("provider down"))
        with mock.patch.object(
            ai_client_factory,
            "create_chat_client",
            side_effect=AssertionError(
                "final reconciliation constructed a provider client"
            ),
        ) as create_client, mock.patch.object(
            toolkit_llm_final_reconciliation.llm,
            "call",
            side_effect=failing,
        ):
            failed = toolkit_llm_final_reconciliation.run_llm_final_editor(brief)
        self.assertEqual(failed["status"], "provider_failed")
        self.assertEqual(len(failing.calls), 1)
        self.assertEqual(failing.calls[0]["task"], task)
        self.assertIn("provider down", failed["error"])
        create_client.assert_not_called()

    def test_memory_diary_router_branches_prompt_parity_and_fallbacks(self) -> None:
        import config

        _assert_default_auto_profile(self, "summaries")
        entry = {"source_index": 1, "summary": "The party crossed the old bridge.", "world_fields": {"world_month": "Hammer", "world_day": 1, "world_year": 1492, "world_time": "08:00:00"}, "checkpoint_location": "Old Bridge"}
        group = [entry]
        cases = (
            ("players", players_diary, lambda: players_diary._generate_markdown_from_prompt("PROMPT", "ctx"), "A new chronicle.", [
                {"role": "system", "content": "Write only markdown chronicle content suitable for direct GUI display."},
                {"role": "user", "content": "PROMPT"},
            ]),
            ("rebuild", session_diary, lambda: session_diary._generate_rebuild_chapter_summary(group, 1), "The party crossed the old bridge in triumph.", [
                {"role": "system", "content": "Write concise in-world chapter recap prose and return only the paragraph."},
                {"role": "user", "content": "Chapter prompt"},
            ]),
            ("checkpoint", session_diary, lambda: session_diary._generate_checkpoint_summary([{"summary_text": "The party crossed the old bridge."}], {"checkpoint_location": "Old Bridge"}, {}, "save"), "The party crossed the old bridge in triumph.", [
                {"role": "system", "content": "You write concise in-world checkpoint diary prose and return only the diary text."},
                {"role": "user", "content": "Checkpoint prompt"},
            ]),
            ("story", story_so_far_compiler, lambda: story_so_far_compiler._generate_story_text_with_llm([], {}), "The campaign's story continues.", [
                {"role": "system", "content": "You produce grounded campaign chronicle prose and return only the requested narrative."},
                {"role": "user", "content": "Story prompt"},
            ]),
        )
        for name, owner, operation, response, expected_messages in cases:
            with self.subTest(operation=name):
                fake = _FakeFacade(response=response)
                with mock.patch.object(owner, "AI_CLIENTS_AVAILABLE", True), mock.patch.object(owner, "get_model_config", return_value={"model": config.DM_SUMMARIZATION_MODEL}), mock.patch.object(owner, "_render_chapter_summary_prompt", return_value="Chapter prompt", create=True), mock.patch.object(owner, "_render_diary_prompt", return_value="Checkpoint prompt", create=True), mock.patch.object(owner, "_render_story_prompt", return_value="Story prompt", create=True), mock.patch.object(llm_router.llm, "call", side_effect=fake), mock.patch.object(ai_client_factory, "create_chat_client", side_effect=AssertionError("provider client created")) as create_client:
                    result = operation()
                self.assertEqual(fake.calls[0]["task"], "summaries")
                self.assertEqual(fake.calls[0]["messages"], expected_messages)
                self.assertEqual(fake.calls[0]["json_output"], False)
                self.assertFalse({"model", "temperature", "top_p", "timeout", "client"}.intersection(fake.calls[0]))
                create_client.assert_not_called()
                self.assertEqual(len(fake.calls), 1)

                failing = _FakeFacade(failure=RuntimeError("provider down"))
                with mock.patch.object(owner, "AI_CLIENTS_AVAILABLE", True), mock.patch.object(owner, "get_model_config", return_value={"model": config.DM_SUMMARIZATION_MODEL}), mock.patch.object(owner, "handle_provider_error", return_value={"should_fallback": True}), mock.patch.object(owner, "_render_chapter_summary_prompt", return_value="Chapter prompt", create=True), mock.patch.object(owner, "_render_diary_prompt", return_value="Checkpoint prompt", create=True), mock.patch.object(owner, "_render_story_prompt", return_value="Story prompt", create=True), mock.patch.object(llm_router.llm, "call", side_effect=failing):
                    operation()
                self.assertEqual(len(failing.calls), 2)
                self.assertEqual(failing.calls[0], failing.calls[1])

        with mock.patch.object(players_diary, "ENABLE_PLAYERS_DIARY_APPEND_LLM", False), mock.patch.object(llm_router.llm, "call", side_effect=AssertionError("provider branch entered")):
            self.assertEqual(players_diary._generate_markdown_from_prompt("PROMPT", "ctx")["status"], "error")
        with mock.patch.object(session_diary, "ENABLE_SESSION_DIARY_LLM", False), mock.patch.object(llm_router.llm, "call", side_effect=AssertionError("provider branch entered")):
            self.assertEqual(session_diary._generate_checkpoint_summary([], {}, {}, "save")["generation_mode"], "fallback")

    def test_remaining_manager_profiles_preserve_model_sources(self) -> None:
        for task in ("summaries", "level_up", "dm_validation", "storage_processor"):
            with self.subTest(task=task):
                _assert_default_auto_profile(self, task)

    def test_manager_initializers_do_not_create_provider_clients(self) -> None:
        original_scan_flag = campaign_manager.CampaignManager._module_scan_attempted
        campaign_manager.CampaignManager._module_scan_attempted = True
        try:
            with mock.patch.object(ai_client_factory, "create_chat_client", side_effect=AssertionError("provider client created")) as create_client, mock.patch.object(
                campaign_manager.os, "makedirs"
            ), mock.patch.object(campaign_manager.CampaignManager, "_load_campaign_data", return_value={}), mock.patch.object(
                storage_processor.os, "makedirs", create=True
            ):
                campaign_manager.CampaignManager()
                level_up_manager.LevelUpSession("Aster", 1, 2)
                with mock.patch.object(storage_processor, "safe_json_load", return_value={}), mock.patch.object(
                    storage_processor, "ModulePathManager", return_value=mock.Mock()
                ):
                    storage_processor.StorageProcessor()
            create_client.assert_not_called()
        finally:
            campaign_manager.CampaignManager._module_scan_attempted = original_scan_flag

    def _campaign_summary(self, first_failure=None, export_response='{"relationships":{},"artifacts":[],"hubs":[],"worldState":{},"unlockedModules":[]}'):
        manager = campaign_manager.CampaignManager.__new__(campaign_manager.CampaignManager)
        manager._archive_conversation_history = mock.Mock()
        manager._load_module_plot_data = mock.Mock(return_value={})
        responses = [first_failure or "Module story.", export_response]
        calls = []

        def invoke(**kwargs):
            calls.append(copy.deepcopy(kwargs))
            response = responses.pop(0)
            if isinstance(response, BaseException):
                raise response
            return response

        with mock.patch.object(llm_router.llm, "call", side_effect=invoke), mock.patch.object(
            ai_client_factory, "create_chat_client", side_effect=AssertionError("manager constructed a provider client")
        ) as create_client:
            result = manager._generate_module_summary(
                "Greyreach", {"partyNPCs": [], "activeQuests": []}, [], skip_archiving=True
            )
        create_client.assert_not_called()
        return result, calls

    def test_campaign_summary_and_export_contracts(self) -> None:
        expected_export = {"relationships": {}, "artifacts": [], "hubs": [], "worldState": {}, "unlockedModules": []}
        result, calls = self._campaign_summary()
        self.assertEqual(result["summary"], "Module story.")
        self.assertEqual(result["exportedData"], expected_export)
        self.assertEqual([call["task"] for call in calls], ["summaries", "summaries"])
        self.assertTrue(all(call["json_output"] is False for call in calls))
        self.assertIn("Complete Conversation History", calls[0]["messages"][1]["content"])
        self.assertIn("Module story.", calls[1]["messages"][1]["content"])

        for export_result in (RuntimeError("provider down"), "not json"):
            with self.subTest(export_result=export_result):
                result, calls = self._campaign_summary(export_response=export_result)
                self.assertEqual(
                    result["exportedData"],
                    {"relationships": {}, "artifacts": {}, "hubs": {}, "worldState": {}, "unlockedModules": []},
                )
                self.assertEqual(len(calls), 2)

        result, calls = self._campaign_summary(first_failure=RuntimeError("provider down"))
        self.assertEqual(result["summary"], "Module Greyreach was completed successfully.")
        self.assertEqual(result["keyDecisions"], [])
        self.assertEqual(len(calls), 1)

    def test_level_up_and_storage_owner_requests_and_failures(self) -> None:
        with mock.patch.object(
            ai_client_factory, "create_chat_client", side_effect=AssertionError("manager constructed a provider client")
        ) as create_client:
            session = level_up_manager.LevelUpSession("Aster", 1, 2)
            session.conversation = [{"role": "user", "content": "Choose a path."}]
            response = _FakeFacade(response="A path.")
            with mock.patch.object(llm_router.llm, "call", side_effect=response):
                self.assertEqual(session._get_ai_response(), "A path.")
            self.assertEqual(response.calls[0]["task"], "level_up")
            self.assertEqual(response.calls[0]["messages"], session.conversation)

            validation = _FakeFacade(response="VALID")
            with mock.patch.object(session, "_load_system_prompts", return_value=("", "Check", "Rules")), mock.patch.object(
                llm_router.llm, "call", side_effect=validation
            ):
                self.assertEqual(session._validate_level_up_response("{}"), (True, "VALID"))
            self.assertEqual(validation.calls[0]["task"], "dm_validation")
            self.assertEqual(len(validation.calls[0]["messages"]), 4)

            failing = _FakeFacade(failure=RuntimeError("provider down"))
            with mock.patch.object(llm_router.llm, "call", side_effect=failing), mock.patch.object(level_up_manager, "error"):
                self.assertEqual(session._get_ai_response(), "I'm having trouble processing that. Could you clarify your choice?")
            self.assertEqual(len(failing.calls), 1)
            create_client.assert_not_called()

        with mock.patch.object(storage_processor, "safe_json_load", return_value={}), mock.patch.object(
            storage_processor, "ModulePathManager", return_value=mock.Mock()
        ), mock.patch.object(
            ai_client_factory, "create_chat_client", side_effect=AssertionError("manager constructed a provider client")
        ) as create_client:
            processor = storage_processor.StorageProcessor()
            processor._get_game_context = mock.Mock(return_value={})
            processor._create_processing_prompt = mock.Mock(return_value=[{"role": "user", "content": "store item"}])
            processor._post_process_operation = mock.Mock(side_effect=lambda operation, _context: operation)
            processor._validate_operation = mock.Mock(return_value=(True, ""))
            fake = _FakeFacade(response='```json\n{"action":"store_item"}\n```')
            with mock.patch.object(llm_router.llm, "call", side_effect=fake):
                result = processor.process_storage_description("store item", "Aster")
            self.assertTrue(result["success"])
            self.assertEqual(result["operation"], {"action": "store_item"})
            self.assertEqual(fake.calls[0]["task"], "storage_processor")
            self.assertEqual(fake.calls[0]["messages"], [{"role": "user", "content": "store item"}])
            failing = _FakeFacade(failure=RuntimeError("provider down"))
            with mock.patch.object(llm_router.llm, "call", side_effect=failing), mock.patch.object(storage_processor, "error"):
                result = processor.process_storage_description("store item", "Aster")
            self.assertFalse(result["success"])
            self.assertIn("after 3 attempts", result["error"])
            self.assertEqual(len(failing.calls), 3)
            create_client.assert_not_called()

    def _assert_utility_request(
        self,
        request: Dict[str, Any],
        task: str,
        digest_name: str,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.assertEqual(request["task"], task)
        self.assertEqual(_message_digest(request["messages"]), PRE_MIGRATION_MESSAGE_DIGESTS[digest_name])
        self.assertEqual(
            {key: value for key, value in request.items() if key not in {"task", "messages"}},
            {"json_output": False, **(extra or {})},
        )
        self.assertFalse(
            {
                "model", "temperature", "top_p", "timeout", "client", "extra_body",
                "observer", "endpoint_name", "trace_site", "stream",
            }.intersection(request)
        )

    def test_utility_content_profiles_preserve_model_sources(self) -> None:
        tasks = (
            "summaries", "level_up", "npc_name_canonicalizer", "dm_validation",
            "prompt_sanitizer", "updates", "plot_update", "encounter_update", "builders",
        )
        for task in tasks:
            with self.subTest(task=task):
                _assert_default_auto_profile(self, task)
                fallback = llm_router.llm.resolve_profile(task, use_fallback=True)
                self.assertEqual(fallback["provider_name"], "openai")
                self.assertEqual(fallback["model"], model_config.OPENAI_FALLBACK_MODEL)

        configured_model = ai_client_factory.get_chat_model_name()
        for role in ("player", "npc"):
            with self.subTest(character_role=role):
                self.assertEqual(
                    update_character_info.get_model_for_character(role),
                    configured_model,
                )

    def test_state_update_modules_do_not_construct_provider_clients(self) -> None:
        import importlib
        from scripts import run_critical_narrative_repair

        modules = (
            plot_update,
            update_character_effects,
            update_character_info,
            update_encounter,
            run_critical_narrative_repair,
        )
        for module in modules:
            with self.subTest(module=module.__name__):
                with mock.patch.object(
                    ai_client_factory,
                    "create_chat_client",
                    side_effect=AssertionError("migrated call site constructed a provider client"),
                ) as create_client:
                    importlib.reload(module)
                create_client.assert_not_called()
                self.assertFalse(hasattr(module, "client"))

    def test_plot_update_facade_request_parse_persistence_and_failure(self) -> None:
        initial_plot = {
            "plotPoints": [{"id": "PP001", "status": "not started", "plotImpact": ""}]
        }
        path_manager = SimpleNamespace(get_plot_path=lambda: "plot.json")
        result_text = '{"PP001":{"status":"in_progress","plotImpact":"Changed"}}'
        facade = _ObservedFacade(result_text)
        tracker = mock.Mock()
        events = []

        def save_plot(path, data):
            events.append("plot_save")
            return True

        with mock.patch("utils.llm_usage_tracker.get_global_tracker", return_value=tracker), \
             mock.patch.object(
                 plot_update,
                 "make_legacy_receipt_observer",
                 wraps=plot_update.make_legacy_receipt_observer,
             ) as observer_factory, \
             mock.patch.object(plot_update.llm, "call", side_effect=facade) as llm_call, \
             mock.patch.object(
                 plot_update,
                 "safe_read_json",
                 side_effect=[{"module": "Test_Module"}, copy.deepcopy(initial_plot)],
             ), \
             mock.patch.object(plot_update, "ModulePathManager", return_value=path_manager), \
             mock.patch.object(plot_update, "load_schema", return_value={}), \
             mock.patch.object(plot_update, "validate"), \
             mock.patch.object(plot_update, "safe_write_json", side_effect=save_plot), \
             mock.patch.object(
                 plot_update,
                 "update_party_tracker",
                 side_effect=lambda *args: events.append("party_tracker"),
             ), \
             mock.patch("utils.quest_player_formatter.format_quests_for_player"), \
             mock.patch.object(plot_update, "info"), \
             mock.patch.object(plot_update, "debug"), \
             mock.patch.object(plot_update, "warning"), \
             mock.patch.object(plot_update, "error"):
            result = plot_update.update_plot(
                "PP001", "in progress", "Changed", "plot.json", max_retries=1
            )

        self.assertEqual(result["plotPoints"][0]["status"], "in progress")
        self.assertEqual(events, ["plot_save", "party_tracker"])
        self.assertEqual(len(facade.calls), 1)
        request = facade.calls[0]
        self.assertEqual(request["task"], "plot_update")
        self.assertEqual(
            _message_digest(request["messages"]),
            PRE_MIGRATION_MESSAGE_DIGESTS["plot_update"],
        )
        self.assertIs(request["json_output"], False)
        self.assertTrue(callable(llm_call.call_args.kwargs["observer"]))
        _assert_usage_only_observer(self, observer_factory, 1)
        self.assertFalse(
            {"model", "temperature", "top_p", "timeout", "client", "extra_body"}.intersection(
                llm_call.call_args.kwargs
            )
        )
        tracker.track.assert_called_once()

        invalid = _FakeFacade("not json")
        invalid_path_manager = SimpleNamespace(get_plot_path=lambda: "plot.json")
        with mock.patch.object(plot_update.llm, "call", side_effect=invalid), \
             mock.patch.object(
                 plot_update,
                 "safe_read_json",
                 side_effect=[{"module": "Test_Module"}, copy.deepcopy(initial_plot)],
             ), \
             mock.patch.object(plot_update, "ModulePathManager", return_value=invalid_path_manager), \
             mock.patch.object(plot_update, "load_schema", return_value={}), \
             mock.patch.object(plot_update, "validate"), \
             mock.patch.object(plot_update, "safe_write_json") as save_json, \
             mock.patch.object(plot_update, "update_party_tracker") as update_tracker, \
             mock.patch("utils.quest_player_formatter.format_quests_for_player"), \
             mock.patch.object(plot_update, "info"), \
             mock.patch.object(plot_update, "debug"), \
             mock.patch.object(plot_update, "warning"), \
             mock.patch.object(plot_update, "error"):
            invalid_result = plot_update.update_plot(
                "PP001", "in progress", "Changed", "plot.json", max_retries=1
            )

        self.assertEqual(invalid_result, initial_plot)
        self.assertEqual(len(invalid.calls), 1)
        save_json.assert_not_called()
        update_tracker.assert_not_called()

        provider_failure = _FakeFacade(failure=RuntimeError("provider unavailable"))
        with mock.patch.object(plot_update.llm, "call", side_effect=provider_failure), \
             mock.patch.object(
                 plot_update,
                 "safe_read_json",
                 side_effect=[{"module": "Test_Module"}, copy.deepcopy(initial_plot)],
             ), \
             mock.patch.object(plot_update, "ModulePathManager", return_value=invalid_path_manager), \
             mock.patch.object(plot_update, "load_schema", return_value={}), \
             mock.patch.object(plot_update, "validate"), \
             mock.patch.object(plot_update, "safe_write_json") as failed_save, \
             mock.patch.object(plot_update, "update_party_tracker") as failed_tracker, \
             mock.patch("utils.quest_player_formatter.format_quests_for_player"), \
             mock.patch.object(plot_update, "info"), \
             mock.patch.object(plot_update, "debug"), \
             mock.patch.object(plot_update, "warning"), \
             mock.patch.object(plot_update, "error"):
            with self.assertRaisesRegex(RuntimeError, "provider unavailable"):
                plot_update.update_plot(
                    "PP001", "in progress", "Changed", "plot.json", max_retries=2
                )

        self.assertEqual(len(provider_failure.calls), 1)
        failed_save.assert_not_called()
        failed_tracker.assert_not_called()

    def test_character_effect_analysis_facade_parse_and_failure(self) -> None:
        response_text = '```json\n{"should_track":false,"effect":{}}\n```'
        facade = _ObservedFacade(response_text)
        tracker = mock.Mock()
        with mock.patch("utils.llm_usage_tracker.get_global_tracker", return_value=tracker), \
             mock.patch.object(
                 update_character_effects,
                 "make_legacy_receipt_observer",
                 wraps=update_character_effects.make_legacy_receipt_observer,
             ) as observer_factory, \
             mock.patch.object(update_character_effects.llm, "call", side_effect=facade) as llm_call, \
             mock.patch.object(
                 update_character_effects, "safe_read_json", return_value={"abilities": {}}
             ):
            result = update_character_effects.analyze_effect_with_ai(
                "Smoke Hero", "Bless for one minute"
            )

        self.assertEqual(result, {"should_track": False, "effect": {}})
        self.assertEqual(len(facade.calls), 1)
        request = facade.calls[0]
        self.assertEqual(request["task"], "updates")
        self.assertEqual(
            _message_digest(request["messages"]),
            PRE_MIGRATION_MESSAGE_DIGESTS["update_character_effects"],
        )
        self.assertIs(request["json_output"], False)
        self.assertTrue(callable(llm_call.call_args.kwargs["observer"]))
        _assert_usage_only_observer(self, observer_factory, 1)
        self.assertFalse(
            {"model", "temperature", "top_p", "timeout", "client", "extra_body"}.intersection(
                llm_call.call_args.kwargs
            )
        )
        tracker.track.assert_called_once()

        failure = _FakeFacade(failure=RuntimeError("provider down"))
        with mock.patch.object(update_character_effects.llm, "call", side_effect=failure), \
             mock.patch.object(
                 update_character_effects, "safe_read_json", return_value={"abilities": {}}
             ), \
             mock.patch.object(update_character_effects, "error"):
            failed_result = update_character_effects.analyze_effect_with_ai(
                "Smoke Hero", "Bless for one minute"
            )
        self.assertIsNone(failed_result)
        self.assertEqual(len(failure.calls), 1)

    def test_character_info_facade_retry_tier_parse_and_canonical_writes(self) -> None:
        character_data = {
            "name": "Smoke Hero",
            "hitPoints": 10,
            "maxHitPoints": 10,
            "equipment": [],
            "currency": {"gold": 0, "silver": 0, "copper": 0},
        }
        tracker = mock.Mock()
        call_requests = []
        writes = []
        attempt_outcomes = [RuntimeError("temporary provider failure"), '{"experience_points":50}']

        def facade_call(**kwargs):
            call_requests.append(copy.deepcopy({
                key: value for key, value in kwargs.items() if key != "observer"
            }))
            outcome = attempt_outcomes[len(call_requests) - 1]
            if isinstance(outcome, BaseException):
                raise outcome
            observer = kwargs.get("observer")
            self.assertTrue(callable(observer))
            observer(
                SimpleNamespace(
                    kind="response",
                    call_id="character-update-call",
                    attempt_id="character-update-attempt-2",
                    task="updates",
                ),
                SimpleNamespace(
                    usage=SimpleNamespace(
                        prompt_tokens=10,
                        completion_tokens=5,
                        total_tokens=15,
                    )
                ),
            )
            return outcome

        def read_json(path):
            if path == "characters/smoke_hero.json":
                return copy.deepcopy(character_data)
            return None

        def safe_write(path, data):
            writes.append((path, copy.deepcopy(data)))
            return True

        validator = SimpleNamespace(
            corrections_made=[],
            validate_and_correct_character_smart=lambda data: data,
        )
        effects_validator = SimpleNamespace(
            corrections_made=[],
            validate_character_effects_safe=lambda path: (character_data, True),
        )

        with tempfile.TemporaryDirectory(
            prefix="character-info-contract-",
            dir=ROOT / "tmp/router-rollout/g6",
        ) as temp_dir:
            previous_cwd = Path.cwd()
            os.chdir(temp_dir)
            try:
                Path("characters").mkdir()
                Path("characters/smoke_hero.json").write_text(
                    json.dumps(character_data), encoding="utf-8"
                )
                with contextlib.ExitStack() as stack:
                    stack.enter_context(
                        mock.patch("utils.llm_usage_tracker.get_global_tracker", return_value=tracker)
                    )
                    observer_factory = stack.enter_context(
                        mock.patch.object(
                            update_character_info,
                            "make_legacy_receipt_observer",
                            wraps=update_character_info.make_legacy_receipt_observer,
                        )
                    )
                    llm_call = stack.enter_context(
                        mock.patch.object(
                            update_character_info.llm, "call", side_effect=facade_call
                        )
                    )
                    handle_error = stack.enter_context(
                        mock.patch.object(
                            update_character_info,
                            "handle_provider_error",
                            return_value={"should_fallback": True},
                        )
                    )
                    patches = (
                        mock.patch.object(
                            update_character_info,
                            "get_character_path",
                            return_value="characters/smoke_hero.json",
                        ),
                        mock.patch.object(
                            update_character_info,
                            "safe_json_load",
                            return_value={"partyMembers": ["Smoke Hero"]},
                        ),
                        mock.patch.object(update_character_info, "safe_read_json", side_effect=read_json),
                        mock.patch.object(update_character_info, "safe_write_json", side_effect=safe_write),
                        mock.patch.object(update_character_info, "load_schema", return_value={}),
                        mock.patch.object(update_character_info, "repair_character_data", side_effect=lambda data: data),
                        mock.patch.object(update_character_info, "create_character_backup", return_value=None),
                        mock.patch.object(update_character_info, "load_conversation_history", return_value=[]),
                        mock.patch.object(update_character_info, "process_conversation_history", return_value=[]),
                        mock.patch.object(update_character_info, "format_schema_for_prompt", return_value="schema"),
                        mock.patch.object(update_character_info, "fix_item_types", side_effect=lambda data: data),
                        mock.patch.object(update_character_info, "fix_injury_types", side_effect=lambda data: data),
                        mock.patch.object(update_character_info, "validate_critical_fields_preserved", return_value=[]),
                        mock.patch.object(update_character_info, "normalize_status_and_condition", side_effect=lambda data, role: data),
                        mock.patch.object(update_character_info, "purge_invalid_fields", side_effect=lambda data, schema, name: (data, [])),
                        mock.patch.object(update_character_info, "validate_character_data", return_value=(True, "")),
                        mock.patch.object(update_character_info, "get_world_observer", return_value=SimpleNamespace(record_event=mock.Mock())),
                        mock.patch.object(update_character_info, "AICharacterValidator", return_value=validator),
                        mock.patch.object(update_character_info, "AICharacterEffectsValidator", return_value=effects_validator),
                        mock.patch.object(update_character_info, "info"),
                        mock.patch.object(update_character_info, "debug"),
                        mock.patch.object(update_character_info, "warning"),
                        mock.patch.object(update_character_info, "error"),
                    )
                    for patcher in patches:
                        stack.enter_context(patcher)
                    result = update_character_info.update_character_info(
                        "Smoke Hero", "Award 50 XP", character_role="player"
                    )
            finally:
                os.chdir(previous_cwd)

        self.assertTrue(result)
        self.assertEqual(len(call_requests), 2)
        self.assertEqual([call["task"] for call in call_requests], ["updates", "updates"])
        self.assertEqual([call["retry_tier"] for call in call_requests], [None, "retry"])
        self.assertTrue(all(call["json_output"] is False for call in call_requests))
        self.assertEqual(
            [_message_digest(call["messages"]) for call in call_requests],
            [PRE_MIGRATION_MESSAGE_DIGESTS["update_character_info"]] * 2,
        )
        self.assertFalse(
            any(
                {"model", "temperature", "top_p", "timeout", "client", "extra_body"}.intersection(call)
                for call in call_requests
            )
        )
        self.assertEqual(llm_call.call_count, 2)
        _assert_usage_only_observer(self, observer_factory, 2)
        handle_error.assert_called_once()
        self.assertEqual(writes[0][0], "characters/smoke_hero.json")
        self.assertEqual(writes[0][1]["experience_points"], 50)
        tracker.track.assert_called_once()

    def test_encounter_update_facade_parse_persist_and_failure_return(self) -> None:
        encounter = {"encounterId": "capture", "creatures": []}
        tracker = mock.Mock()
        facade = _ObservedFacade('{"encounterSummary":"Changed"}')

        with tempfile.TemporaryDirectory(
            prefix="encounter-update-contract-",
            dir=ROOT / "tmp/router-rollout/g6",
        ) as temp_dir:
            previous_cwd = Path.cwd()
            os.chdir(temp_dir)
            try:
                Path("modules/encounters").mkdir(parents=True)
                Path("party_tracker.json").write_text(
                    json.dumps({"module": "Test_Module"}), encoding="utf-8"
                )
                encounter_path = Path("modules/encounters/encounter_capture.json")
                encounter_path.write_text(json.dumps(encounter), encoding="utf-8")
                with mock.patch("utils.llm_usage_tracker.get_global_tracker", return_value=tracker), \
                     mock.patch.object(
                         update_encounter,
                         "make_legacy_receipt_observer",
                         wraps=update_encounter.make_legacy_receipt_observer,
                     ) as observer_factory, \
                     mock.patch.object(update_encounter.llm, "call", side_effect=facade) as llm_call, \
                     mock.patch.object(update_encounter, "ModulePathManager", return_value=SimpleNamespace()), \
                     mock.patch.object(update_encounter, "load_encounter_schema", return_value={}), \
                     mock.patch.object(update_encounter, "validate"), \
                     mock.patch.object(update_encounter, "_sync_non_enemy_creatures"), \
                     mock.patch.object(update_encounter, "info"), \
                     mock.patch.object(update_encounter, "warning"), \
                     mock.patch.object(update_encounter, "error"), \
                     mock.patch.object(update_encounter, "debug"):
                    result = update_encounter.update_encounter(
                        "capture", "The goblin fled", max_retries=1
                    )

                self.assertEqual(result["encounterSummary"], "Changed")
                self.assertEqual(
                    json.loads(encounter_path.read_text(encoding="utf-8")), result
                )
                self.assertEqual(len(facade.calls), 1)
                request = facade.calls[0]
                self.assertEqual(request["task"], "encounter_update")
                self.assertEqual(
                    _message_digest(request["messages"]),
                    PRE_MIGRATION_MESSAGE_DIGESTS["update_encounter"],
                )
                self.assertIs(request["json_output"], False)
                self.assertTrue(callable(llm_call.call_args.kwargs["observer"]))
                _assert_usage_only_observer(self, observer_factory, 1)
                self.assertFalse(
                    {"model", "temperature", "top_p", "timeout", "client", "extra_body"}.intersection(
                        llm_call.call_args.kwargs
                    )
                )
                tracker.track.assert_called_once()

                encounter_path.write_text(json.dumps(encounter), encoding="utf-8")
                invalid = _FakeFacade("not json")
                with mock.patch.object(update_encounter.llm, "call", side_effect=invalid), \
                     mock.patch.object(update_encounter, "ModulePathManager", return_value=SimpleNamespace()), \
                     mock.patch.object(update_encounter, "load_encounter_schema", return_value={}), \
                     mock.patch.object(update_encounter, "validate"), \
                     mock.patch.object(update_encounter, "_sync_non_enemy_creatures"), \
                     mock.patch.object(update_encounter, "info"), \
                     mock.patch.object(update_encounter, "warning"), \
                     mock.patch.object(update_encounter, "error"), \
                     mock.patch.object(update_encounter, "debug"):
                    failed_result = update_encounter.update_encounter(
                        "capture", "The goblin fled", max_retries=1
                    )
                self.assertEqual(failed_result, encounter)
                self.assertEqual(
                    json.loads(encounter_path.read_text(encoding="utf-8")), encounter
                )
                self.assertEqual(len(invalid.calls), 1)

                provider_failure = _FakeFacade(
                    failure=RuntimeError("provider unavailable")
                )
                with mock.patch.object(
                    update_encounter.llm, "call", side_effect=provider_failure
                ), mock.patch.object(
                    update_encounter,
                    "ModulePathManager",
                    return_value=SimpleNamespace(),
                ), mock.patch.object(
                    update_encounter, "load_encounter_schema", return_value={}
                ), mock.patch.object(
                    update_encounter, "validate"
                ), mock.patch.object(
                    update_encounter, "_sync_non_enemy_creatures"
                ), mock.patch.object(
                    update_encounter, "info"
                ), mock.patch.object(
                    update_encounter, "warning"
                ), mock.patch.object(
                    update_encounter, "error"
                ), mock.patch.object(
                    update_encounter, "debug"
                ):
                    with self.assertRaisesRegex(RuntimeError, "provider unavailable"):
                        update_encounter.update_encounter(
                            "capture", "The goblin fled", max_retries=2
                        )
                self.assertEqual(len(provider_failure.calls), 1)
                self.assertEqual(
                    json.loads(encounter_path.read_text(encoding="utf-8")), encounter
                )
            finally:
                os.chdir(previous_cwd)

    def test_critical_narrative_repair_facade_return_and_failure_marker(self) -> None:
        from scripts import run_critical_narrative_repair

        facade = _FakeFacade("raw builder text")
        with mock.patch.object(run_critical_narrative_repair.llm, "call", side_effect=facade) as llm_call:
            content = run_critical_narrative_repair._try_provider_call("Repair this narrative")

        self.assertEqual(content, "raw builder text")
        self.assertEqual(len(facade.calls), 1)
        request = facade.calls[0]
        self.assertEqual(request["task"], "builders")
        self.assertEqual(
            _message_digest(request["messages"]),
            PRE_MIGRATION_MESSAGE_DIGESTS["critical_narrative_repair"],
        )
        self.assertIs(request["json_output"], False)
        self.assertNotIn("observer", request)
        self.assertFalse(
            {"model", "temperature", "top_p", "timeout", "client", "extra_body"}.intersection(
                request
            )
        )
        self.assertNotIn("observer", llm_call.call_args.kwargs)

        provider_failure = _FakeFacade(failure=RuntimeError("provider down"))
        with mock.patch.object(
            run_critical_narrative_repair.llm,
            "call",
            side_effect=provider_failure,
        ), mock.patch.object(
            ai_client_factory,
            "handle_provider_error",
            return_value={"should_fallback": True},
        ):
            failure_text = run_critical_narrative_repair._try_provider_call(
                "Repair this narrative"
            )
        failure = json.loads(failure_text)
        self.assertTrue(failure["provider_error"])
        self.assertEqual(failure["provider_stage"], "accurate_ingest.critical_narrative_repair")
        self.assertTrue(failure["retryable"])
        self.assertEqual(len(provider_failure.calls), 1)

    def test_homebrewery_adventure_writer_requests_fallbacks_and_parsing(self) -> None:
        area = {
            "areaName": "North",
            "areaId": "A1",
            "areaType": "wilderness",
            "areaDescription": "Dense pine",
            "locations": [{
                "name": "Camp",
                "description": "Cold",
                "npcs": [{"name": "Mara"}],
                "monsters": [{"name": "Wolf"}],
                "connectivity": ["R2"],
                "areaConnectivity": ["A2"],
            }],
        }
        responses = [
            "## Module Overview\nOverview.\n## The Story So Far\nStory.\n## Running the Adventure\nRun.",
            "Plot hook.",
            "Area overview.",
        ]
        with mock.patch.object(llm_router.llm, "call", side_effect=responses) as facade, mock.patch.object(
            ai_client_factory,
            "create_chat_client",
            side_effect=AssertionError("homebrewery constructed a provider client"),
        ) as create_client:
            intro = homebrewery_adventure_writer._llm_intro_narrative(
                "Module", 1, 2, 3, 4, "Author", "Plot text"
            )
            plot = homebrewery_adventure_writer._llm_plot_hook("Plot text", 2, "Author")
            overview = homebrewery_adventure_writer._llm_area_overview(
                area, {"plot_points": [], "_cross_area_edges": [], "areas": []}
            )
        self.assertIn("### Module Overview", intro)
        self.assertIn("### The Story So Far", intro)
        self.assertIn("### Running the Adventure", intro)
        self.assertEqual(plot, "Plot hook.\n\n")
        self.assertEqual(overview, "Area overview.")
        requests = [call.kwargs for call in facade.call_args_list]
        self._assert_utility_request(
            requests[0], "summaries", "homebrewery_intro", {
                "max_completion_tokens": 800,
                "g10_source_id": "utils/homebrewery_adventure_writer.py:_llm_intro_narrative",
            }
        )
        self._assert_utility_request(
            requests[1], "summaries", "homebrewery_plot", {
                "max_completion_tokens": 250,
                "g10_source_id": "utils/homebrewery_adventure_writer.py:_llm_plot_hook",
            }
        )
        self._assert_utility_request(
            requests[2], "summaries", "homebrewery_area", {
                "max_completion_tokens": 500,
                "g10_source_id": "utils/homebrewery_adventure_writer.py:_llm_area_overview",
            }
        )
        self.assertEqual(len(requests), 3)
        create_client.assert_not_called()

        for operation, args in (
            (homebrewery_adventure_writer._llm_intro_narrative, ("Module", 1, 2, 3, 4, "Author", "Plot text")),
            (homebrewery_adventure_writer._llm_plot_hook, ("Plot text", 2, "Author")),
            (homebrewery_adventure_writer._llm_area_overview, (area, {"plot_points": [], "_cross_area_edges": [], "areas": []})),
        ):
            failing = _FakeFacade(failure=RuntimeError("provider down"))
            with self.subTest(operation=operation.__name__), mock.patch.object(
                llm_router.llm, "call", side_effect=failing
            ):
                self.assertIsNone(operation(*args))
            self.assertEqual(len(failing.calls), 1)

    def test_level_up_utility_router_parse_and_failure(self) -> None:
        import config

        response = '```json\n{"hitPoints":12,"maxHitPoints":12}\n```'
        fake = _FakeFacade(response=response)
        character_data = {"experience_points": 700}
        with mock.patch.object(level_up, "load_leveling_info", return_value="LEVEL INFO"), mock.patch.object(
            llm_router.llm, "call", side_effect=fake
        ), mock.patch.object(
            ai_client_factory,
            "create_chat_client",
            side_effect=AssertionError("level_up constructed a provider client"),
        ) as create_client:
            result = level_up.get_npc_level_up_changes("Aster", character_data, 2, 3)
        self.assertTrue(result["success"])
        self.assertEqual(result["changes"]["level"], 3)
        self.assertEqual(result["changes"]["experience_points"], 700)
        self.assertEqual(result["changes"]["exp_required_for_next_level"], level_up.get_next_level_threshold(3))
        self._assert_utility_request(fake.calls[0], "level_up", "level_up_utility")
        self.assertEqual(len(fake.calls), 1)
        create_client.assert_not_called()
        _assert_default_auto_profile(self, "level_up")

        failing = _FakeFacade(failure=RuntimeError("provider down"))
        with mock.patch.object(level_up, "load_leveling_info", return_value="LEVEL INFO"), mock.patch.object(
            llm_router.llm, "call", side_effect=failing
        ):
            failed = level_up.get_npc_level_up_changes("Aster", character_data, 2, 3)
        self.assertFalse(failed["success"])
        self.assertIn("Failed to generate level up changes", failed["error"])
        self.assertEqual(len(failing.calls), 1)

    def test_npc_name_canonicalizer_router_parse_and_fallback(self) -> None:
        fake = _FakeFacade(response=' "Aldric" ')
        with mock.patch.object(llm_router.llm, "call", side_effect=fake), mock.patch.object(
            ai_client_factory,
            "create_chat_client",
            side_effect=AssertionError("name canonicalizer constructed a provider client"),
        ) as create_client:
            canonical = npc_name_canonicalizer.call_mini_model_for_name("Sir Aldric Stoneheart")
        self.assertEqual(canonical, "Aldric")
        self._assert_utility_request(
            fake.calls[0], "npc_name_canonicalizer", "npc_name_canonicalizer", {"max_tokens": 20}
        )
        self.assertEqual(len(fake.calls), 1)
        create_client.assert_not_called()

        failing = _FakeFacade(failure=RuntimeError("provider down"))
        with mock.patch.object(npc_name_canonicalizer, "load_name_cache", return_value={}), mock.patch.object(
            npc_name_canonicalizer, "save_name_cache", return_value=True
        ), mock.patch.object(llm_router.llm, "call", side_effect=failing):
            fallback = npc_name_canonicalizer.get_canonical_name(
                "Sir Aldric Stoneheart", skip_cache=True
            )
        self.assertEqual(fallback, "Aldric")
        self.assertEqual(len(failing.calls), 1)
        self._assert_utility_request(
            failing.calls[0], "npc_name_canonicalizer", "npc_name_canonicalizer", {"max_tokens": 20}
        )

    def test_npc_reconciler_router_confirmation_and_fail_closed(self) -> None:
        with mock.patch.object(
            ai_client_factory,
            "create_chat_client",
            side_effect=AssertionError("NPC reconciler constructed a provider client"),
        ) as create_client:
            reconciler = npc_reconciler.NpcReconciler("Fixture", llm_timeout_seconds=15)
        create_client.assert_not_called()
        self.assertFalse(hasattr(reconciler, "client"))

        fake = _FakeFacade(response="TRUE\n")
        with mock.patch.object(llm_router.llm, "call", side_effect=fake):
            self.assertTrue(reconciler._ai_confirm_merge("Old Elara", "Elara"))
        self._assert_utility_request(
            fake.calls[0], "dm_validation", "npc_reconciler", {"max_tokens": 1}
        )
        self.assertEqual(len(fake.calls), 1)

        failing = _FakeFacade(failure=RuntimeError("provider outage"))
        with mock.patch.object(llm_router.llm, "call", side_effect=failing):
            self.assertFalse(reconciler._ai_confirm_merge("Old Elara", "Elara"))
        self._assert_utility_request(
            failing.calls[0], "dm_validation", "npc_reconciler", {"max_tokens": 1}
        )
        self.assertEqual(len(failing.calls), 1)
        self.assertEqual(reconciler.provider_stage_errors[-1]["fallback"], "do_not_merge")

    def test_prompt_sanitizer_router_return_and_failure(self) -> None:
        fake = _FakeFacade(response="  A safer prompt.\n")
        with mock.patch.object(llm_router.llm, "call", side_effect=fake), mock.patch.object(
            ai_client_factory,
            "create_chat_client",
            side_effect=AssertionError("prompt sanitizer constructed a provider client"),
        ) as create_client:
            result = prompt_sanitizer.sanitize_prompt("A cult threatens the party")
        self.assertEqual(result, "A safer prompt.")
        self._assert_utility_request(fake.calls[0], "prompt_sanitizer", "prompt_sanitizer")
        self.assertEqual(len(fake.calls), 1)
        create_client.assert_not_called()

        failing = _FakeFacade(failure=RuntimeError("provider down"))
        with mock.patch.object(llm_router.llm, "call", side_effect=failing):
            with self.assertRaisesRegex(RuntimeError, "provider down"):
                prompt_sanitizer.sanitize_prompt("A cult threatens the party")
        self.assertEqual(len(failing.calls), 1)
        self._assert_utility_request(failing.calls[0], "prompt_sanitizer", "prompt_sanitizer")

    def test_quest_player_formatter_router_parse_and_failure(self) -> None:
        quests = {
            "Q1": {
                "title": "Hidden Pass",
                "description": "The party reaches a pass.",
                "status": "in progress",
            }
        }
        fake = _FakeFacade(response='{"Q1":"You find the hidden pass."}')
        with mock.patch.object(llm_router.llm, "call", side_effect=fake), mock.patch.object(
            ai_client_factory,
            "create_chat_client",
            side_effect=AssertionError("quest formatter constructed a provider client"),
        ) as create_client:
            result = quest_player_formatter.format_quest_batch(quests)
        self.assertEqual(result, {"Q1": "You find the hidden pass."})
        self._assert_utility_request(fake.calls[0], "updates", "quest_player_formatter")
        self.assertEqual(len(fake.calls), 1)
        create_client.assert_not_called()

        malformed = _FakeFacade(response="not json")
        with mock.patch.object(llm_router.llm, "call", side_effect=malformed):
            self.assertIsNone(quest_player_formatter.format_quest_batch(quests))
        self.assertEqual(len(malformed.calls), 1)
        self._assert_utility_request(malformed.calls[0], "updates", "quest_player_formatter")

        failing = _FakeFacade(failure=RuntimeError("provider down"))
        with mock.patch.object(llm_router.llm, "call", side_effect=failing):
            self.assertIsNone(quest_player_formatter.format_quest_batch(quests))
        self.assertEqual(len(failing.calls), 1)
        self._assert_utility_request(failing.calls[0], "updates", "quest_player_formatter")

    def test_reconcile_location_state_router_retry_and_failure(self) -> None:
        history = [{"role": "user", "content": "The party defeats the wolf."}]

        def invoke(responses):
            area_data = {"locations": [{"locationId": "R1", "monsters": [{"name": "Wolf"}]}]}
            values = list(responses)
            calls = []

            def fake_call(**kwargs):
                calls.append(copy.deepcopy(kwargs))
                value = values.pop(0)
                if isinstance(value, BaseException):
                    raise value
                return value

            path_manager = mock.Mock()
            path_manager.get_area_path.return_value = "tmp/router-rollout/g6/fixture-area.json"
            writer = mock.Mock(return_value=True)
            with mock.patch.object(
                reconcile_location_state, "safe_read_json", side_effect=[{"module": "Fixture"}, area_data]
            ), mock.patch.object(reconcile_location_state.os.path, "exists", return_value=True), mock.patch.object(
                reconcile_location_state, "ModulePathManager", return_value=path_manager
            ), mock.patch.object(
                reconcile_location_state, "create_area_backup", return_value=None
            ), mock.patch.object(
                reconcile_location_state, "safe_write_json", writer
            ), mock.patch.object(llm_router.llm, "call", side_effect=fake_call), mock.patch.object(
                ai_client_factory,
                "create_chat_client",
                side_effect=AssertionError("location reconciler constructed a provider client"),
            ) as create_client:
                reconcile_location_state.run("A1", "R1", history)
            create_client.assert_not_called()
            return calls, area_data, writer

        calls, area_data, writer = invoke(["invalid response", '[{"name":"Survivor"}]'])
        self.assertEqual(len(calls), 2)
        for request in calls:
            self._assert_utility_request(request, "updates", "reconcile_location_state")
        self.assertEqual(area_data["locations"][0]["monsters"], [{"name": "Survivor"}])
        writer.assert_called_once()

        failing_calls, failed_area_data, failed_writer = invoke(
            [RuntimeError("provider down")] * 3
        )
        self.assertEqual(len(failing_calls), 3)
        for request in failing_calls:
            self._assert_utility_request(request, "updates", "reconcile_location_state")
        self.assertEqual(failed_area_data["locations"][0]["monsters"], [{"name": "Wolf"}])
        failed_writer.assert_not_called()

    def test_spatial_contract_router_parse_and_degrade(self) -> None:
        fallback_plan = {
            "coordinates": {"R1": "X10Y10"},
            "connectivity": {"R1": []},
            "directions": {},
            "layout": [],
        }
        room_records = [{"id": "R1", "name": "Room"}]
        response = '{"coordinates":{"R1":"X10Y10"},"connectivity":{"R1":[]},"directions":{},"layout":[]}'
        fake = _FakeFacade(response=response)
        with mock.patch.object(llm_router.llm, "call", side_effect=fake), mock.patch.object(
            ai_client_factory,
            "create_chat_client",
            side_effect=AssertionError("spatial contract constructed a provider client"),
        ) as create_client:
            result = spatial_contract._resolve_semantic_spatial_plan_with_llm(
                room_records, ["R1"], fallback_plan
            )
        self.assertEqual(result["coordinates"], {"R1": "X10Y10"})
        self._assert_utility_request(
            fake.calls[0],
            "dm_validation",
            "spatial_contract",
            {"response_format": {"type": "json_object"}, "json_contract": True},
        )
        self.assertEqual(len(fake.calls), 1)
        create_client.assert_not_called()

        failing = _FakeFacade(failure=RuntimeError("provider down"))
        with mock.patch.object(llm_router.llm, "call", side_effect=failing), mock.patch.object(
            ai_client_factory, "handle_provider_error", return_value={"should_fallback": True}
        ):
            degraded = spatial_contract._resolve_semantic_spatial_plan_with_llm(
                room_records, ["R1"], fallback_plan
            )
        self.assertEqual(degraded["coordinates"], {"R1": "X10Y10"})
        self.assertEqual(degraded["status"], "degraded")
        self.assertEqual(degraded["provider_diagnostics"]["fallback"], "deterministic_spatial_plan")
        self.assertTrue(degraded["provider_diagnostics"]["retryable"])
        self.assertEqual(len(failing.calls), 1)
        self._assert_utility_request(
            failing.calls[0],
            "dm_validation",
            "spatial_contract",
            {"response_format": {"type": "json_object"}, "json_contract": True},
        )

    def test_startup_wizard_router_contracts_and_fallbacks(self) -> None:
        import config

        self.assertFalse(hasattr(startup_wizard, "client"))
        conversation = [{"role": "system", "content": "Start here."}]
        events = []
        fake = _FakeFacade(response=" Hello, adventurer. \n")

        def record_save(payload, path):
            events.append(("save", copy.deepcopy(payload), path))
            return True

        with mock.patch.object(llm_router.llm, "call", side_effect=fake), mock.patch.object(
            startup_wizard, "status_processing_ai", side_effect=lambda: events.append("processing")
        ), mock.patch.object(
            startup_wizard, "status_saving", side_effect=lambda: events.append("saving")
        ), mock.patch.object(
            startup_wizard, "status_ready", side_effect=lambda: events.append("ready")
        ), mock.patch.object(startup_wizard, "safe_json_dump", side_effect=record_save), mock.patch.object(
            ai_client_factory,
            "create_chat_client",
            side_effect=AssertionError("startup response constructed a provider client"),
        ) as create_client:
            result = startup_wizard.get_ai_response(conversation)
        self.assertEqual(result, "Hello, adventurer.")
        self.assertEqual(
            conversation,
            [
                {"role": "system", "content": "Start here."},
                {"role": "assistant", "content": "Hello, adventurer."},
            ],
        )
        self._assert_utility_request(
            fake.calls[0], "dm_main", "startup_get_ai_response"
        )
        self.assertEqual(len(fake.calls), 1)
        self.assertEqual([event if isinstance(event, str) else event[0] for event in events], ["processing", "saving", "save", "ready"])
        create_client.assert_not_called()

        failed_conversation = [{"role": "system", "content": "Start here."}]
        failing = _FakeFacade(failure=RuntimeError("provider down"))
        with mock.patch.object(config, "OPENAI_API_KEY", "configured"), mock.patch.object(
            llm_router.llm, "call", side_effect=failing
        ), mock.patch.object(startup_wizard, "safe_json_dump") as save:
            fallback = startup_wizard.get_ai_response(failed_conversation)
        self.assertIn("connection seems unstable", fallback)
        self.assertEqual(failed_conversation, [{"role": "system", "content": "Start here."}])
        self.assertEqual(len(failing.calls), 1)
        self._assert_utility_request(
            failing.calls[0], "dm_main", "startup_get_ai_response"
        )
        save.assert_not_called()

        location_data = {"module_name": "Fixture", "areas": {}, "plot": {}}
        location_response = '{"areaId":"A1","areaName":"North","locationId":"R1","locationName":"Camp","weather":"Clear","politicalClimate":"Quiet"}'
        location_fake = _FakeFacade(response=location_response)
        with mock.patch.object(
            startup_wizard, "load_module_for_ai_analysis", return_value=location_data
        ), mock.patch.object(
            llm_router.llm, "call", side_effect=location_fake
        ), mock.patch.object(
            ai_client_factory,
            "create_chat_client",
            side_effect=AssertionError("startup location constructed a provider client"),
        ) as create_location_client:
            location = startup_wizard.get_ai_starting_location({"moduleName": "Fixture"})
        self.assertEqual(location["locationId"], "R1")
        self._assert_utility_request(
            location_fake.calls[0], "dm_main", "startup_get_ai_starting_location",
            {"json_contract": True},
        )
        self.assertEqual(len(location_fake.calls), 1)
        create_location_client.assert_not_called()

        fallback_location = {"locationId": "fallback"}
        location_failure = _FakeFacade(failure=RuntimeError("provider down"))
        with mock.patch.object(
            startup_wizard, "load_module_for_ai_analysis", return_value=location_data
        ), mock.patch.object(
            startup_wizard, "get_fallback_starting_location", return_value=fallback_location
        ), mock.patch.object(llm_router.llm, "call", side_effect=location_failure):
            self.assertEqual(
                startup_wizard.get_ai_starting_location({"moduleName": "Fixture"}),
                fallback_location,
            )
        self.assertEqual(len(location_failure.calls), 1)
        self._assert_utility_request(
            location_failure.calls[0], "dm_main", "startup_get_ai_starting_location",
            {"json_contract": True},
        )


    def test_toolkit_classification_router_request_parse_and_failure(self) -> None:
        _assert_default_auto_profile(self, "dm_validation")
        fake = _FakeFacade(response='{"entity":"combatant"}')
        with mock.patch.object(
            ai_client_factory,
            "create_chat_client",
            side_effect=AssertionError("classification constructed a provider client"),
        ) as create_client, mock.patch.object(
            toolkit_llm_classification.llm, "call", side_effect=fake
        ):
            result = toolkit_llm_classification._call_llm_with_fallback(
                "Classification system.", "Classify this entity."
            )
        self.assertEqual(result, {"entity": "combatant"})
        request = fake.calls[0]
        self.assertEqual(request["task"], "dm_validation")
        self.assertEqual(
            _message_digest(request["messages"]),
            PRE_MIGRATION_MESSAGE_DIGESTS["toolkit_llm_classification"],
        )
        self.assertEqual(
            {
                key: value
                for key, value in request.items()
                if key not in {"task", "messages"}
            },
            {"json_output": False, "response_format": {"type": "json_object"}},
        )
        self.assertFalse(
            {
                "model", "temperature", "top_p", "timeout", "client",
                "extra_body", "observer",
            }.intersection(request)
        )
        self.assertEqual(len(fake.calls), 1)
        create_client.assert_not_called()

        failure = _FakeFacade(failure=RuntimeError("provider down"))
        error_sink = []
        with mock.patch.object(
            ai_client_factory,
            "create_chat_client",
            side_effect=AssertionError("classification constructed a provider client"),
        ) as create_client, mock.patch.object(
            toolkit_llm_classification.llm, "call", side_effect=failure
        ), mock.patch.object(
            toolkit_llm_classification,
            "handle_provider_error",
            return_value={"should_fallback": True},
        ) as handle_error, mock.patch.object(toolkit_llm_classification, "warning"):
            failed = toolkit_llm_classification._call_llm_with_fallback(
                "Classification system.", "Classify this entity.", error_sink=error_sink
            )
        self.assertIsNone(failed)
        self.assertEqual(len(failure.calls), 1)
        self.assertEqual(failure.calls[0]["task"], "dm_validation")
        self.assertEqual(
            error_sink,
            [{
                "status": "degraded",
                "stage": "toolkit_classification",
                "error_type": "RuntimeError",
                "retryable": True,
                "fallback": "classification_defaults_or_empty_proposals",
            }],
        )
        handle_error.assert_called_once()
        create_client.assert_not_called()

        _assert_default_auto_profile(self, "dm_validation")

    def test_web_chat_profiles_preserve_inventory_models(self) -> None:
        self.assertEqual(model_config.LLM_PROVIDER, "openrouter")
        self.assertEqual(model_config.ACTIVE_PROFILE, "production-auto")
        for task in ("dm_validation", "dm_mini", "npc_builder", "monster_builder"):
            with self.subTest(task=task):
                _assert_default_auto_profile(self, task)

    def test_web_fetch_npc_descriptions_route_router_request_and_failures(self) -> None:
        import config

        web_interface = _web_interface_for_contract()

        class _CapturedThread:
            def __init__(self, target):
                self.target = target
                self.daemon = False
                self.started = False

            def start(self):
                self.started = True

        def run_route(facade):
            threads = []
            writes = []
            tracker = mock.Mock()

            def capture_write(path, data):
                writes.append((path, copy.deepcopy(data)))

            def capture_thread(target):
                thread = _CapturedThread(target)
                threads.append(thread)
                return thread

            with mock.patch.object(web_interface, "TOOLKIT_AVAILABLE", True), mock.patch.object(
                web_interface.threading, "Thread", side_effect=capture_thread
            ) as thread_factory:
                response = web_interface.app.test_client().post(
                    "/api/toolkit/npcs/fetch-descriptions",
                    json={"module_name": "Fixture", "npcs": [{"id": "elara", "name": "Elara"}]},
                )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()["success"], True)
            thread_factory.assert_called_once()
            self.assertTrue(threads[0].started)
            self.assertTrue(threads[0].daemon)

            with mock.patch.object(
                web_interface,
                "create_chat_client",
                side_effect=AssertionError("web text prompt constructed a chat client"),
                create=True,
            ) as chat_client, mock.patch.object(
                ai_client_factory,
                "create_chat_client",
                side_effect=AssertionError("web text prompt constructed a chat client"),
            ) as factory_client, mock.patch.object(
                web_interface,
                "OpenAI",
                side_effect=AssertionError("web text prompt constructed a media client"),
            ) as media_client, mock.patch.object(
                web_interface.llm, "call", side_effect=facade
            ), mock.patch.object(
                web_interface, "USAGE_TRACKING_AVAILABLE", True
            ), mock.patch.object(
                config, "OPENAI_API_KEY", "provider-free-test", create=True
            ), mock.patch.object(
                web_interface, "extract_module_context_for_npcs", return_value="Fixture module context"
            ), mock.patch(
                "utils.file_operations.safe_read_json", side_effect=[{"npcs": {}}, {}]
            ), mock.patch(
                "utils.file_operations.safe_write_json", side_effect=capture_write
            ), mock.patch.object(
                web_interface.os, "makedirs"
            ), mock.patch.object(
                web_interface.socketio, "emit"
            ) as emit, mock.patch.object(
                web_interface, "info"
            ), mock.patch.object(
                web_interface, "error"
            ), mock.patch(
                "utils.llm_usage_tracker.get_global_tracker", return_value=tracker
            ), mock.patch(
                "utils.api_logger.log_api_call"
            ) as api_logger, mock.patch(
                "utils.combat_latency_trace.emit_trace_event"
            ) as trace_writer, mock.patch("time.sleep"):
                threads[0].target()

            chat_client.assert_not_called()
            factory_client.assert_not_called()
            media_client.assert_not_called()
            api_logger.assert_not_called()
            trace_writer.assert_not_called()
            return facade, writes, tracker, emit

        success = _ObservedFacade("An elven scout.")
        facade, writes, tracker, emit = run_route(success)
        self.assertEqual(len(facade.calls), 1)
        request = facade.calls[0]
        self.assertEqual(request["task"], "dm_mini")
        self.assertEqual(
            _message_digest(request["messages"]),
            PRE_MIGRATION_MESSAGE_DIGESTS["web_fetch_npc_descriptions"],
        )
        self.assertEqual(
            {key: value for key, value in request.items() if key not in {"task", "messages"}},
            {"json_output": False},
        )
        self.assertFalse(
            {
                "model", "temperature", "top_p", "timeout", "client", "extra_body",
                "endpoint_name", "trace_site", "stream",
            }.intersection(request)
        )
        self.assertEqual([path for path, _ in writes], [
            "data/bestiary/npc_compendium.json",
            "temp/npc_descriptions_Fixture.json",
        ])
        self.assertEqual(writes[0][1]["npcs"]["elara"]["description"], "An elven scout.")
        tracker.track.assert_called_once()
        tracked_context = tracker.track.call_args.args[1]
        self.assertEqual(
            {key: tracked_context[key] for key in ("endpoint", "purpose", "interface")},
            {
                "endpoint": "web_validation",
                "purpose": "validate_web_response",
                "interface": "web",
            },
        )
        self.assertEqual(emit.call_count, 1)

        failure = _FakeFacade(failure=RuntimeError("provider down"))
        failure, failure_writes, failure_tracker, failure_emit = run_route(failure)
        self.assertEqual(len(failure.calls), 1)
        self.assertEqual(failure.calls[0]["task"], "dm_mini")
        self.assertEqual(
            _message_digest(failure.calls[0]["messages"]),
            PRE_MIGRATION_MESSAGE_DIGESTS["web_fetch_npc_descriptions"],
        )
        self.assertEqual(
            {key: value for key, value in failure.calls[0].items() if key not in {"task", "messages", "observer"}},
            {"json_output": False},
        )
        self.assertEqual(failure_writes, [])
        failure_tracker.track.assert_not_called()
        self.assertEqual(failure_emit.call_args.args[0], "npc_description_progress")
        self.assertEqual(failure_emit.call_args.args[1]["status"], "error")

    def test_web_toolkit_npc_description_function_router_request_and_fallback(self) -> None:
        web_interface = _web_interface_for_contract()

        fake = _FakeFacade(response="  A lantern-eyed scout.  ")
        with mock.patch.object(
            web_interface,
            "create_chat_client",
            side_effect=AssertionError("toolkit NPC description constructed a chat client"),
            create=True,
        ) as chat_client, mock.patch.object(
            ai_client_factory,
            "create_chat_client",
            side_effect=AssertionError("toolkit NPC description constructed a chat client"),
        ) as factory_client, mock.patch.object(
            web_interface,
            "OpenAI",
            side_effect=AssertionError("toolkit NPC description constructed a media client"),
        ) as media_client, mock.patch.object(
            web_interface.llm, "call", side_effect=fake
        ):
            result = web_interface._generate_toolkit_npc_description("Elara")
        self.assertEqual(
            result, {"status": "success", "description": "A lantern-eyed scout."}
        )
        request = fake.calls[0]
        self.assertEqual(request["task"], "npc_builder")
        self.assertEqual(
            _message_digest(request["messages"]),
            PRE_MIGRATION_MESSAGE_DIGESTS["web_toolkit_npc_description"],
        )
        self.assertEqual(
            {key: value for key, value in request.items() if key not in {"task", "messages"}},
            {"json_output": False, "max_tokens": 300},
        )
        self.assertFalse(
            {"model", "temperature", "top_p", "timeout", "client", "extra_body", "observer"}.intersection(request)
        )
        self.assertEqual(len(fake.calls), 1)
        chat_client.assert_not_called()
        factory_client.assert_not_called()
        media_client.assert_not_called()

        failure = _FakeFacade(failure=RuntimeError("provider down"))
        with mock.patch.object(web_interface.llm, "call", side_effect=failure), mock.patch.object(
            web_interface, "error"
        ):
            fallback = web_interface._generate_toolkit_npc_description("Elara")
        self.assertEqual(fallback["status"], "degraded")
        self.assertEqual(fallback["description"], "A fantasy NPC named Elara")
        self.assertEqual(fallback["failure"]["error_type"], "RuntimeError")
        self.assertEqual(len(failure.calls), 1)

    def test_web_promote_to_bestiary_route_router_usage_and_failure(self) -> None:
        web_interface = _web_interface_for_contract()

        class _CapturedWrite(io.StringIO):
            def __init__(self, completed_writes):
                super().__init__()
                self.completed_writes = completed_writes

            def __exit__(self, exc_type, exc, traceback):
                if exc_type is None:
                    self.completed_writes.append(self.getvalue())
                self.close()
                return False

        def run_route(facade):
            writes = []
            tracker = mock.Mock()

            def open_compendium(path, mode, encoding=None):
                if path != "data/bestiary/monster_compendium.json":
                    raise AssertionError(f"unexpected test path: {path}")
                if mode == "r":
                    return io.StringIO(json.dumps({"monsters": {}}))
                if mode == "w":
                    return _CapturedWrite(writes)
                raise AssertionError(f"unexpected open mode: {mode}")

            with mock.patch.object(web_interface, "TOOLKIT_AVAILABLE", True), mock.patch.object(
                web_interface,
                "open",
                side_effect=open_compendium,
                create=True,
            ), mock.patch.object(
                web_interface,
                "create_chat_client",
                side_effect=AssertionError("bestiary route constructed a chat client"),
                create=True,
            ) as chat_client, mock.patch.object(
                ai_client_factory,
                "create_chat_client",
                side_effect=AssertionError("bestiary route constructed a chat client"),
            ) as factory_client, mock.patch.object(
                web_interface,
                "OpenAI",
                side_effect=AssertionError("bestiary route constructed a media client"),
            ) as media_client, mock.patch.object(
                web_interface.llm, "call", side_effect=facade
            ), mock.patch.object(
                web_interface, "USAGE_TRACKING_AVAILABLE", True
            ), mock.patch(
                "utils.llm_usage_tracker.get_global_tracker", return_value=tracker
            ), mock.patch(
                "utils.api_logger.log_api_call"
            ) as api_logger, mock.patch(
                "utils.combat_latency_trace.emit_trace_event"
            ) as trace_writer, mock.patch.object(
                web_interface, "info"
            ), mock.patch.object(
                web_interface, "error"
            ):
                response = web_interface.app.test_client().post(
                    "/api/toolkit/promote-to-bestiary", json={"monster_id": "ash_wyrm"}
                )

            self.assertEqual(response.status_code, 200)
            chat_client.assert_not_called()
            factory_client.assert_not_called()
            media_client.assert_not_called()
            api_logger.assert_not_called()
            trace_writer.assert_not_called()
            return response.get_json(), writes, tracker, facade

        success = _ObservedFacade("Ash Wyrms coil around the ruins.")
        result, writes, tracker, facade = run_route(success)
        self.assertTrue(result["success"])
        self.assertEqual(len(facade.calls), 1)
        request = facade.calls[0]
        self.assertEqual(request["task"], "monster_builder")
        self.assertEqual(
            _message_digest(request["messages"]),
            PRE_MIGRATION_MESSAGE_DIGESTS["web_promote_to_bestiary"],
        )
        self.assertEqual(
            {key: value for key, value in request.items() if key not in {"task", "messages"}},
            {"json_output": False},
        )
        self.assertFalse(
            {
                "model", "temperature", "top_p", "timeout", "client", "extra_body",
                "endpoint_name", "trace_site", "stream",
            }.intersection(request)
        )
        saved = json.loads(writes[0])
        self.assertEqual(
            saved["monsters"]["ash_wyrm"]["description"],
            "Ash Wyrms coil around the ruins.",
        )
        tracker.track.assert_called_once()
        tracked_context = tracker.track.call_args.args[1]
        self.assertEqual(
            {key: tracked_context[key] for key in ("endpoint", "purpose", "interface")},
            {
                "endpoint": "web_dm",
                "purpose": "web_interface_response",
                "interface": "web",
            },
        )

        failure = _FakeFacade(failure=RuntimeError("provider down"))
        failed_result, failed_writes, failed_tracker, failed_facade = run_route(failure)
        self.assertFalse(failed_result["success"])
        self.assertIn("provider down", failed_result["error"])
        self.assertEqual(len(failed_facade.calls), 1)
        self.assertEqual(failed_facade.calls[0]["task"], "monster_builder")
        self.assertEqual(
            _message_digest(failed_facade.calls[0]["messages"]),
            PRE_MIGRATION_MESSAGE_DIGESTS["web_promote_to_bestiary"],
        )
        self.assertEqual(failed_writes, [])
        failed_tracker.track.assert_not_called()


if __name__ == "__main__":
    unittest.main()
