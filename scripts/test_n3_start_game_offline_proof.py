# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Offline tests for the N3 start_game provider-free proof tool."""

from __future__ import annotations

import builtins
import contextlib
import io
import json
import os
import shutil
import socket
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from scripts import n3_start_game_offline_proof as proof


class FakeSocket:
    family = socket.AF_INET


class FakeClient:
    def __init__(self, web_module: Any) -> None:
        self.web_module = web_module
        self.events: list[dict[str, Any]] = []
        self.disconnected = False

    def emit(self, name: str) -> None:
        if name != "start_game":
            raise AssertionError("unexpected event")
        if getattr(self.web_module, "handler_error", False):
            self.events.append(
                {"name": "error", "args": [{"message": "private-handler-error"}]}
            )
            return
        egress_host = getattr(self.web_module, "egress_host", None)
        if isinstance(egress_host, str):
            socket.getaddrinfo(egress_host, 443)
        call_mode = getattr(self.web_module, "provider_call_mode", None)
        messages = getattr(self.web_module, "provider_call_messages", [])
        self.web_module.alive = True
        if call_mode == "get_ai_response":
            self.web_module.dm_main.get_ai_response(messages)
        elif call_mode == "llm_router":
            self.web_module.router.call(
                task="dm_main", messages=messages, model_tier="simple"
            )
        self.web_module.alive = True
        self.events.extend(
            [
                {"name": "status_update", "args": [{"message": "private-status"}]},
                {"name": "game_output", "args": [{"content": "private-output"}]},
                {"name": "game_started", "args": [{"message": "started"}]},
            ]
        )

    def get_received(self) -> list[dict[str, Any]]:
        events = self.events
        self.events = []
        return events

    def disconnect(self) -> None:
        self.disconnected = True


class FakeSocketIO:
    def __init__(self, web_module: Any, version_module: Any) -> None:
        self.web_module = web_module
        self.version_module = version_module
        self.seen_origin: str | None = None

    def test_client(self, app: Any, headers: dict[str, str]) -> FakeClient:
        del app
        self.seen_origin = headers.get("Origin")
        self.version_module.get_latest_remote_version(
            "fake/repo", "main", silent=True
        )
        return FakeClient(self.web_module)


class FakeHostImporter:
    def __init__(self, sandbox: Path, fail_name: str | None = None) -> None:
        self.names: list[str] = []
        self.fail_name = fail_name
        self.ledger_module = SimpleNamespace(
            __file__=str(sandbox / "utils" / "provider_attempt_budget.py"),
            activate_provider_attempt_budget=self.activate_budget
        )
        self.router_module = SimpleNamespace(
            __file__=str(sandbox / "utils" / "llm_router.py"),
            llm=SimpleNamespace(call=self.unused),
        )
        self.model_config_module = SimpleNamespace(
            __file__=str(sandbox / "model_config.py"),
            ACTIVE_PROFILE="proof-profile",
            LLM_PROVIDER="openrouter",
            AUTO_ROUTER_TASK_COST_TIERS={"dm_main": "medium"},
            TASK_OVERRIDES={},
            MODEL_PROFILES={
                "proof-profile": {
                    "simple": {
                        "model": "test/simple-model",
                        "price_per_1k": {"prompt": 0.25, "completion": 0.5},
                        "params": {},
                        "provider": {},
                    },
                    "complex": {
                        "model": "test/complex-model",
                        "price_per_1k": {},
                        "params": {},
                        "provider": {},
                    },
                }
            },
        )
        self.main_module = SimpleNamespace(
            __file__=str(sandbox / "main.py"),
            get_ai_response=self.unused,
        )
        self.version_module = SimpleNamespace(
            __file__=str(sandbox / "utils" / "version_checker.py"),
            get_latest_remote_version=self.unused,
        )
        self.web_module = SimpleNamespace(
            __file__=str(sandbox / "web" / "web_interface.py"),
            app=object(),
            alive=False,
            dm_main=self.main_module,
            router=self.router_module.llm,
            provider_call_mode=None,
            provider_call_messages=[],
            egress_host=None,
        )
        self.web_module._player_sharing_runtime_available = (
            lambda: self.web_module.alive
        )
        self.web_module.socketio = FakeSocketIO(
            self.web_module, self.version_module
        )
        self.ledger_path: Path | None = None

    @staticmethod
    def unused(*args: Any, **kwargs: Any) -> None:
        del args, kwargs

    def activate_budget(self) -> Path:
        path = Path(os.environ["NEQ_PROVIDER_ATTEMPT_LEDGER"])
        self.ledger_path = path
        records = [
            {"event": "header", "schema_version": 1},
            {"event": "activated", "schema_version": 1},
        ]
        with open(path, "w", encoding="ascii") as stream:
            for record in records:
                stream.write(json.dumps(record, ensure_ascii=True) + "\n")
        return path

    def __call__(self, name: str) -> Any:
        self.names.append(name)
        if name == self.fail_name:
            raise RuntimeError(
                "setup failed at /outside/repo/config.py config API_KEY=private-value"
            )
        modules = {
            "utils.provider_attempt_budget": self.ledger_module,
            "utils.llm_router": self.router_module,
            "utils.version_checker": self.version_module,
            "model_config": self.model_config_module,
            "web.web_interface": self.web_module,
        }
        if name in modules:
            return modules[name]
        if name.startswith("openai.resources."):
            raise ImportError("optional SDK module is unavailable in fake host")
        raise AssertionError("unexpected import request: " + name)


class FakePreintegrateImporter:
    def __init__(
        self,
        sandbox: Path,
        uncovered_call: bool = False,
        fail_name: str | None = None,
        scan_during_web_import: bool = False,
        create_registry_on_scan: bool = True,
        register_capture_module: bool = True,
    ) -> None:
        self.names: list[str] = []
        self.uncovered_call = uncovered_call
        self.fail_name = fail_name
        self.scan_during_web_import = scan_during_web_import
        self.create_registry_on_scan = create_registry_on_scan
        self.register_capture_module = register_capture_module
        self.scan_calls = 0
        self.manager_calls = 0
        self.registry_exists_at_scan: bool | None = None
        self.registry_writer_calls = 0
        self.manager_calls_at_web_import: int | None = None
        self.scan_attempted_at_web_import: bool | None = None
        self.ledger_module = SimpleNamespace(
            __file__=str(sandbox / "utils" / "provider_attempt_budget.py"),
            activate_provider_attempt_budget=self.activate_budget,
        )
        self.router_module = SimpleNamespace(
            __file__=str(sandbox / "utils" / "llm_router.py"),
            llm=SimpleNamespace(call=self.unused),
        )
        self.version_module = SimpleNamespace(
            __file__=str(sandbox / "utils" / "version_checker.py"),
            get_latest_remote_version=self.unused,
        )
        self.main_module = SimpleNamespace(
            __file__=str(sandbox / "main.py"),
            get_ai_response=self.unused,
        )
        self.web_module = SimpleNamespace(
            __file__=str(sandbox / "web" / "web_interface.py"),
            dm_main=self.main_module,
        )

        def registry_writer(payload: Any, path: str) -> bool:
            self.registry_writer_calls += 1
            Path(path).write_text(json.dumps(payload), encoding="utf-8")
            return True

        self.stitcher_module = SimpleNamespace(
            __file__=str(sandbox / "core" / "generators" / "module_stitcher.py"),
            llm=SimpleNamespace(call=self.unused),
            safe_json_dump=registry_writer,
        )

        def scan_and_integrate_new_modules() -> list[str]:
            self.scan_calls += 1
            self.stitcher_module.llm.call(task="safety_review", payload="private")
            self.stitcher_module.llm.call(task="travel_narration", payload="private")
            if self.uncovered_call:
                self.stitcher_module.llm.call(
                    task="uncovered", private_value="private-provider-token"
                )
            registry_path = sandbox / "modules" / "world_registry.json"
            self.registry_exists_at_scan = registry_path.is_file()
            if self.create_registry_on_scan:
                if registry_path.is_file():
                    registry = json.loads(registry_path.read_text(encoding="utf-8"))
                else:
                    registry = {"modules": {}}
                if self.register_capture_module:
                    registry["modules"]["Capture_Arena"] = {
                        "moduleName": "Capture_Arena"
                    }
                registry_path.write_text(json.dumps(registry), encoding="utf-8")
            return ["Capture_Arena"]

        self.stitcher_module.scan_and_integrate_new_modules = (
            scan_and_integrate_new_modules
        )

        def campaign_manager_init(instance: Any) -> None:
            del instance
            self.manager_calls += 1
            manager_class._module_scan_attempted = True
            self.stitcher_module.scan_and_integrate_new_modules()

        manager_class = type(
            "FakeCampaignManager",
            (),
            {"_module_scan_attempted": False, "__init__": campaign_manager_init},
        )
        self.manager_class = manager_class
        self.campaign_module = SimpleNamespace(
            __file__=str(sandbox / "core" / "managers" / "campaign_manager.py"),
            CampaignManager=manager_class,
        )
        self.ledger_path: Path | None = None

    @staticmethod
    def unused(*args: Any, **kwargs: Any) -> None:
        del args, kwargs

    def activate_budget(self) -> Path:
        path = Path(os.environ["NEQ_PROVIDER_ATTEMPT_LEDGER"])
        self.ledger_path = path
        with open(path, "w", encoding="ascii") as stream:
            stream.write('{"event":"header","schema_version":1}\n')
            stream.write('{"event":"activated","schema_version":1}\n')
        return path

    def __call__(self, name: str) -> Any:
        self.names.append(name)
        if name == "web.web_interface":
            self.manager_calls_at_web_import = self.manager_calls
            self.scan_attempted_at_web_import = (
                self.manager_class._module_scan_attempted
            )
            if self.scan_during_web_import:
                self.manager_class._module_scan_attempted = True
                self.manager_calls += 1
                self.scan_calls += 1
        if name == self.fail_name:
            raise RuntimeError(
                "setup failed at /outside/repo/config.py config API_KEY=private-value"
            )
        modules = {
            "utils.provider_attempt_budget": self.ledger_module,
            "utils.llm_router": self.router_module,
            "utils.version_checker": self.version_module,
            "web.web_interface": self.web_module,
            "core.generators.module_stitcher": self.stitcher_module,
            "core.managers.campaign_manager": self.campaign_module,
        }
        if name in modules:
            return modules[name]
        if name.startswith("openai.resources."):
            raise ImportError("optional SDK module is unavailable in fake host")
        raise AssertionError("unexpected import request: " + name)


class N3StartGameOfflineProofTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scratch_parent = proof.REPO_ROOT / "tmp"
        self.scratch_parent.mkdir(parents=True, exist_ok=True)
        self.scratch = Path(
            tempfile.mkdtemp(prefix="n3-start-game-proof-tests-", dir=self.scratch_parent)
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.scratch, ignore_errors=True)

    def _fake_sandbox(self) -> Path:
        sandbox = self.scratch / "combat_capture"
        for relative in (
            "main.py",
            "web/web_interface.py",
            "utils/llm_router.py",
            "utils/provider_attempt_budget.py",
            "utils/version_checker.py",
            "model_config.py",
        ):
            source = sandbox / relative
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text("", encoding="ascii")
        history = sandbox / "modules" / "conversation_history"
        history.mkdir(parents=True, exist_ok=True)
        return sandbox

    def _seed_provider_free_sandbox(
        self,
        modules_registry: Any,
        *,
        active_combat: Any = "",
        history_messages: Any = None,
        malformed_registry: bool = False,
        missing_registry: bool = False,
    ) -> Path:
        sandbox = self.scratch / "seed"
        modules_dir = sandbox / "modules"
        areas = modules_dir / "Capture_Arena" / "areas"
        areas.mkdir(parents=True, exist_ok=True)
        registry_path = modules_dir / "world_registry.json"
        if missing_registry:
            pass
        elif malformed_registry:
            registry_path.write_text("{malformed", encoding="utf-8")
        else:
            registry_path.write_text(
                json.dumps({"modules": modules_registry}), encoding="utf-8"
            )
        (sandbox / "party_tracker.json").write_text(
            json.dumps({"worldConditions": {"activeCombatEncounter": active_combat}}),
            encoding="utf-8",
        )
        (areas / "CA01.json").write_text(
            json.dumps(
                {
                    "areaId": "CA01",
                    "areaName": "Capture Arena",
                    "locations": [],
                }
            ),
            encoding="utf-8",
        )
        if history_messages is not None:
            history_dir = modules_dir / "conversation_history"
            history_dir.mkdir(parents=True, exist_ok=True)
            (history_dir / "history.json").write_text(
                json.dumps({"messages": history_messages}), encoding="utf-8"
            )
        return sandbox

    def _fake_preintegrate_sandbox(self, *, missing_registry: bool = False) -> Path:
        sandbox = self._seed_provider_free_sandbox(
            [], missing_registry=missing_registry
        )
        for relative in (
            "main.py",
            "web/web_interface.py",
            "core/generators/module_stitcher.py",
            "core/managers/campaign_manager.py",
            "utils/llm_router.py",
            "utils/provider_attempt_budget.py",
            "utils/version_checker.py",
        ):
            source = sandbox / relative
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text("", encoding="ascii")
        return sandbox

    def test_provider_and_egress_guards_detect_forbidden_calls(self) -> None:
        recorder = proof.ProviderCallRecorder()
        with self.assertRaises(proof.ProviderCallBlocked):
            recorder.block_provider_function()
        self.assertEqual(recorder.snapshot(), (0, 1, 0))

        guard = proof.EgressGuard()
        with guard:
            with self.assertRaises(proof.EgressBlocked):
                guard._connect(FakeSocket(), ("198.51.100.20", 9443), "connect")
            with self.assertRaises(proof.EgressBlocked):
                socket.socket.connect_ex(FakeSocket(), ("198.51.100.23", 9446))
            with self.assertRaises(proof.EgressBlocked):
                socket.create_connection(("198.51.100.21", 9444))
            with self.assertRaises(proof.EgressBlocked):
                socket.getaddrinfo("198.51.100.22", 9445)
        self.assertEqual(
            guard.snapshot(),
            [
                {"host_class": "non_loopback", "port": 9443},
                {"host_class": "non_loopback", "port": 9446},
                {"host_class": "non_loopback", "port": 9444},
                {"host_class": "non_loopback", "port": 9445},
            ],
        )

    def test_egress_attribution_is_relative_bounded_and_deduplicated(self) -> None:
        sandbox = self._fake_sandbox()
        frames = [
            SimpleNamespace(
                filename="/usr/local/lib/python3.11/socket.py", name="getaddrinfo"
            ),
            SimpleNamespace(
                filename=(
                    "/usr/local/lib/python3.11/site-packages/httpx/_client.py"
                ),
                name="send",
            ),
            SimpleNamespace(
                filename=str(sandbox / "core" / "outer.py"), name="outer_call"
            ),
            SimpleNamespace(filename=str(sandbox / "main.py"), name="narrate"),
            SimpleNamespace(
                filename=str(sandbox / "utils" / "transport.py"), name="connect"
            ),
        ]
        project_frames, libraries = proof._collect_egress_origin(frames, sandbox)
        self.assertEqual(
            project_frames,
            [
                "utils/transport.py:connect",
                "main.py:narrate",
                "core/outer.py:outer_call",
            ],
        )
        self.assertEqual(libraries, ["httpx"])

        guard = proof.EgressGuard()
        guard.set_sandbox_root(sandbox)
        with (
            patch.object(
                proof,
                "_collect_egress_origin",
                return_value=(project_frames, libraries),
            ),
            patch.object(
                proof,
                "_thread_name_class",
                side_effect=["background", "background", "main"],
            ),
        ):
            for host in (
                "api.openrouter.ai",
                "api.openrouter.ai",
                "github.com",
            ):
                with self.assertRaises(proof.EgressBlocked):
                    guard._record(host, 443, record_loopback=False)

        attributions = proof._safe_egress_attributions(
            guard.attribution_snapshot()
        )
        openrouter = next(
            item for item in attributions if item["hostname_class"] == "openrouter"
        )
        github = next(
            item for item in attributions if item["hostname_class"] == "github"
        )
        self.assertEqual(openrouter["count"], 2)
        self.assertEqual(openrouter["thread_classes"], ["background"])
        self.assertEqual(github["count"], 1)
        self.assertEqual(github["thread_classes"], ["main"])
        serialized = json.dumps(attributions, ensure_ascii=True)
        self.assertNotIn("api.openrouter.ai", serialized)
        self.assertNotIn("github.com", serialized)
        self.assertNotIn("/usr/local", serialized)

    def test_proof_tripwires_report_only_initial_request_size_and_labels(self) -> None:
        sandbox = self._fake_sandbox()
        messages = [
            {"role": "system", "content": "private-system-narration-prompt"},
            {"role": "user", "content": "private-user-action"},
        ]
        expected_characters = sum(len(message["content"]) for message in messages)

        for mode, capture_site in (
            ("get_ai_response", "get_ai_response"),
            ("llm_router", "llm_router"),
        ):
            with self.subTest(mode=mode):
                importer = FakeHostImporter(sandbox)
                importer.web_module.provider_call_mode = mode
                importer.web_module.provider_call_messages = messages
                report = proof.run_proof(
                    sandbox_root=sandbox,
                    run_id="request-metrics-" + mode,
                    output_dir=self.scratch / ("request-metrics-" + mode),
                    startup_timeout=0.2,
                    settle_seconds=0.01,
                    host_importer=importer,
                )

                request = report["initial_narration_request"]
                self.assertEqual(report["verdict"], "BLOCKED")
                self.assertEqual(request["capture_site"], capture_site)
                self.assertEqual(request["task"], "dm_main")
                self.assertEqual(request["message_count"], 2)
                self.assertEqual(request["content_characters"], expected_characters)
                self.assertEqual(
                    request["estimated_tokens"], (expected_characters + 3) // 4
                )
                self.assertEqual(request["active_profile"], "proof-profile")
                self.assertEqual(request["task_tier"], "medium")
                self.assertEqual(request["model_tier"], "simple" if mode == "llm_router" else None)
                self.assertEqual(
                    report["router_calls"], 1 if mode == "llm_router" else 0
                )
                self.assertEqual(
                    report["provider_function_calls"],
                    1 if mode == "get_ai_response" else 0,
                )
                self.assertEqual(request["profile_models"][0]["model_id"], "test/simple-model")
                self.assertEqual(
                    request["profile_models"][0]["price_per_1k"],
                    {"prompt": 0.25, "completion": 0.5},
                )
                serialized = json.dumps(report, ensure_ascii=True, sort_keys=True)
                written = json.loads(
                    (
                        self.scratch
                        / ("request-metrics-" + mode)
                        / "proof.json"
                    ).read_text(encoding="ascii")
                )
                self.assertEqual(written["initial_narration_request"], request)
                self.assertNotIn("private-system-narration-prompt", serialized)
                self.assertNotIn("private-user-action", serialized)

        self.assertIsNone(proof._safe_model_label("sk-" + "a" * 24))

    def test_expected_startup_narration_is_blocked_and_priced_without_provider_use(self) -> None:
        sandbox = self._fake_sandbox()
        for mode in ("get_ai_response", "llm_router"):
            with self.subTest(capture_site=mode):
                importer = FakeHostImporter(sandbox)
                importer.model_config_module.ACTIVE_PROFILE = "n3-luna"
                importer.model_config_module.MODEL_PROFILES = {
                    "n3-luna": {
                        tier: {
                            "model": "openai/gpt-6-luna",
                            "params": {"max_tokens": 2048},
                            "provider": {"allow_fallbacks": False},
                            "price_per_1k": {
                                "prompt": 0.0001,
                                "completion": 0.0005,
                            },
                        }
                        for tier in ("simple", "complex")
                    }
                }
                importer.web_module.provider_call_mode = mode
                importer.web_module.provider_call_messages = [
                    {"role": "user", "content": "x" * 39997}
                ]

                report = proof.run_proof(
                    sandbox_root=sandbox,
                    run_id="expected-startup-" + mode,
                    output_dir=self.scratch / ("expected-startup-" + mode),
                    startup_timeout=0.2,
                    settle_seconds=0.01,
                    host_importer=importer,
                    expect_startup_narration=True,
                    require_priced_route=True,
                )

                self.assertEqual(report["verdict"], "PASS")
                self.assertTrue(report["startup_narration_expected"])
                self.assertTrue(report["startup_narration_intercepted"])
                self.assertIn("not sent to a provider", report["notes"])
                self.assertEqual(
                    report["router_calls"], 1 if mode == "llm_router" else 0
                )
                self.assertEqual(
                    report["provider_function_calls"],
                    1 if mode == "get_ai_response" else 0,
                )
                self.assertEqual(report["ledger_reservations"], 0)
                self.assertEqual(report["egress_attempts"], [])
                self.assertEqual(
                    proof.PROVIDER_ENVIRONMENT["NEQ_PROVIDER_ATTEMPT_BUDGET"],
                    "1",
                )
                route_pin = report["route_pin"]
                self.assertEqual(route_pin["provider"], "openrouter")
                self.assertEqual(route_pin["profile"], "n3-luna")
                self.assertEqual(route_pin["model_tier"], "simple" if mode == "llm_router" else None)
                self.assertEqual(route_pin["model_id"], "openai/gpt-6-luna")
                self.assertIs(route_pin["allow_fallbacks"], False)
                self.assertEqual(route_pin["max_completion_tokens"], 2048)
                self.assertTrue(route_pin["priced"])
                self.assertTrue(route_pin["historical_rates"])
                self.assertTrue(route_pin["n3_luna"])
                self.assertEqual(report["estimated_cost_usd_upper_bound"], 0.002024)
                assumptions = report["cost_estimate_assumptions"]
                self.assertEqual(
                    assumptions["rate_source"],
                    "scripts/mise_en_scene/llm_staging_study3/sizing.py:21-29",
                )
                self.assertEqual(
                    assumptions["rate_classification"],
                    "historical_estimate_not_live_quote",
                )
                self.assertEqual(assumptions["actual_cost_source"], "provider receipt")
                serialized = json.dumps(report, ensure_ascii=True, sort_keys=True)
                self.assertNotIn("x" * 100, serialized)
                self.assertNotIn("config.py", importer.names)

    def test_proof_report_includes_sanitized_egress_attribution(self) -> None:
        sandbox = self._fake_sandbox()
        importer = FakeHostImporter(sandbox)
        importer.web_module.egress_host = "api.openrouter.ai"
        report = proof.run_proof(
            sandbox_root=sandbox,
            run_id="egress-attribution",
            output_dir=self.scratch / "egress-attribution",
            startup_timeout=0.2,
            settle_seconds=0.01,
            host_importer=importer,
        )
        self.assertEqual(report["egress_attempts"][0]["host_class"], "non_loopback")
        self.assertEqual(len(report["egress_attributions"]), 1)
        attribution = report["egress_attributions"][0]
        self.assertEqual(attribution["hostname_class"], "openrouter")
        self.assertEqual(attribution["thread_classes"], ["main"])
        self.assertEqual(attribution["count"], 1)
        serialized = json.dumps(report, ensure_ascii=True, sort_keys=True)
        self.assertNotIn("api.openrouter.ai", serialized)
        self.assertNotIn("/Users/", serialized)

    def test_self_test_proves_both_tripwires(self) -> None:
        self.assertEqual(
            proof.run_guard_self_test(),
            {
                "verdict": "PASS",
                "provider_stub_detected": True,
                "update_check_stub_detected": True,
                "non_version_egress_detected": True,
                "egress_guard_detected": True,
            },
        )

    def test_history_count_reads_only_direct_json_message_lists(self) -> None:
        sandbox = self._fake_sandbox()
        history_dir = sandbox / "modules" / "conversation_history"
        (history_dir / "seed.json").write_text(
            json.dumps(
                {
                    "conversation_history": [
                        {"role": "system", "content": "private"},
                        {"role": "user", "content": "private"},
                    ]
                }
            ),
            encoding="utf-8",
        )
        nested = history_dir / "nested"
        nested.mkdir()
        (nested / "ignored.json").write_text(
            json.dumps([{"role": "user"}]), encoding="utf-8"
        )
        self.assertEqual(proof.count_conversation_history(sandbox), (2, 1))

    def test_static_seed_helper_accepts_list_and_dict_registries(self) -> None:
        for registry in (["Capture_Arena"], {"Capture_Arena": {}}):
            with self.subTest(registry_type=type(registry).__name__):
                sandbox = self._seed_provider_free_sandbox(registry)
                checks = proof.check_capture_seed_provider_free(sandbox)
                self.assertEqual(
                    checks,
                    {
                        "registry_has_no_unregistered_modules": True,
                        "no_active_combat": True,
                        "no_history_user_messages": True,
                        "provider_free_startup_seed": True,
                    },
                )

    def test_static_seed_helper_treats_missing_registry_as_empty(self) -> None:
        sandbox = self._seed_provider_free_sandbox(
            [], missing_registry=True
        )
        checks = proof.check_capture_seed_provider_free(sandbox)
        self.assertFalse(checks["registry_has_no_unregistered_modules"])
        self.assertTrue(checks["no_active_combat"])
        self.assertTrue(checks["no_history_user_messages"])
        self.assertFalse(checks["provider_free_startup_seed"])
        self.assertFalse((sandbox / "modules" / "world_registry.json").exists())

    def test_relative_seed_helpers_remain_rooted_after_chdir(self) -> None:
        sandbox = self._fake_preintegrate_sandbox()
        relative_sandbox = sandbox.relative_to(proof.REPO_ROOT)

        def registry_writer(payload: Any, path: str) -> bool:
            Path(path).write_text(json.dumps(payload), encoding="utf-8")
            return True

        original_cwd = Path.cwd()
        try:
            os.chdir(sandbox)
            proof._normalize_registry_for_integration(
                relative_sandbox, registry_writer
            )
            inspected = proof._inspect_capture_seed(relative_sandbox)
        finally:
            os.chdir(original_cwd)

        registry = json.loads(
            (sandbox / "modules" / "world_registry.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(registry["modules"], {})
        self.assertTrue(inspected["checks"]["no_active_combat"])
        self.assertTrue(inspected["checks"]["no_history_user_messages"])
        self.assertFalse(inspected["checks"]["registry_has_no_unregistered_modules"])

    def test_static_seed_helper_rejects_unregistered_area_module(self) -> None:
        sandbox = self._seed_provider_free_sandbox({})
        checks = proof.check_capture_seed_provider_free(sandbox)
        self.assertFalse(checks["registry_has_no_unregistered_modules"])
        self.assertFalse(checks["provider_free_startup_seed"])

    def test_static_seed_helper_rejects_active_combat_and_user_history(self) -> None:
        active_sandbox = self._seed_provider_free_sandbox(
            {"Capture_Arena": {}}, active_combat="encounter-secret"
        )
        active_checks = proof.check_capture_seed_provider_free(active_sandbox)
        self.assertFalse(active_checks["no_active_combat"])
        self.assertFalse(active_checks["provider_free_startup_seed"])

        history_sandbox = self._seed_provider_free_sandbox(
            {"Capture_Arena": {}},
            history_messages=[{"role": "user", "content": "private"}],
        )
        history_checks = proof.check_capture_seed_provider_free(history_sandbox)
        self.assertFalse(history_checks["no_history_user_messages"])
        self.assertFalse(history_checks["provider_free_startup_seed"])

    def test_static_seed_helper_fails_closed_for_malformed_json(self) -> None:
        sandbox = self._seed_provider_free_sandbox({}, malformed_registry=True)
        self.assertEqual(
            proof.check_capture_seed_provider_free(sandbox),
            {
                "registry_has_no_unregistered_modules": False,
                "no_active_combat": False,
                "no_history_user_messages": False,
                "provider_free_startup_seed": False,
            },
        )

    def test_static_seed_helper_fails_closed_for_symlinked_sandbox(self) -> None:
        target = self._seed_provider_free_sandbox({"Capture_Arena": {}})
        link = self.scratch / "seed-link"
        link.symlink_to(target, target_is_directory=True)
        checks = proof.check_capture_seed_provider_free(link)
        self.assertFalse(any(checks.values()))

    def test_report_shape_verdict_and_redaction(self) -> None:
        report = proof.build_report(
            sandbox_path_class="repository_tmp/combat_capture",
            conversation_history_message_count=3,
            conversation_history_user_message_count=1,
            game_thread_alive=True,
            seconds_to_alive=0.12549,
            router_calls=0,
            provider_function_calls=0,
            egress_attempts=[
                {
                    "host_class": "loopback",
                    "port": 8360,
                    "host": "secret.example",
                    "token": "not-for-report",
                }
            ],
            ledger_reservations=0,
            observed_events={"game_output": 4, "status_update": 2, "payload": "secret"},
            update_check_calls=7,
        )
        self.assertEqual(report["verdict"], "FAIL")
        self.assertEqual(report["seconds_to_alive"], 0.125)
        self.assertEqual(
            set(report),
            {
                "sandbox_path_class",
                "conversation_history_message_count",
                "conversation_history_user_message_count",
                "game_thread_alive",
                "seconds_to_alive",
                "router_calls",
                "provider_function_calls",
                "egress_attempts",
                "egress_attributions",
                "known_product_contacts",
                "initial_narration_request",
                "route_pin",
                "estimated_cost_usd_upper_bound",
                "cost_estimate_assumptions",
                "startup_narration_expected",
                "startup_narration_intercepted",
                "require_priced_route",
                "ledger_reservations",
                "update_check_calls",
                "observed_events",
                "notes",
                "verdict",
                "reason",
            },
        )
        serialized = json.dumps(report, ensure_ascii=True, sort_keys=True)
        self.assertTrue(serialized.isascii())
        self.assertEqual(report["egress_attributions"], [])
        self.assertEqual(report["known_product_contacts"], [])
        self.assertIsNone(report["initial_narration_request"])
        self.assertIsNone(report["route_pin"])
        self.assertIsNone(report["estimated_cost_usd_upper_bound"])
        self.assertFalse(report["startup_narration_intercepted"])
        self.assertNotIn("secret.example", serialized)
        self.assertNotIn("not-for-report", serialized)
        self.assertNotIn("\"payload\"", serialized)

    def test_verdict_requires_alive_and_zero_provider_network_and_ledger_counts(self) -> None:
        base = {
            "sandbox_path_class": "repository_tmp/combat_capture",
            "conversation_history_message_count": 0,
            "conversation_history_user_message_count": 0,
            "game_thread_alive": True,
            "seconds_to_alive": 0.1,
            "router_calls": 0,
            "provider_function_calls": 0,
            "egress_attempts": [],
            "ledger_reservations": 0,
            "update_check_calls": 5,
            "observed_events": {},
        }
        self.assertEqual(proof.build_report(**base)["verdict"], "PASS")
        for field, value in (
            ("router_calls", 1),
            ("provider_function_calls", 1),
            ("egress_attempts", [{"host_class": "non_loopback", "port": 443}]),
            ("ledger_reservations", 1),
            ("game_thread_alive", False),
        ):
            variant = dict(base)
            variant[field] = value
            self.assertEqual(proof.build_report(**variant)["verdict"], "FAIL")
        blocked = proof.build_report(**base, blocked_reason="host import failed")
        self.assertEqual(blocked["verdict"], "BLOCKED")
        self.assertEqual(blocked["blocked_reason"], "RuntimeError: host import failed")
        missing_narration = proof.build_report(
            **base,
            expect_startup_narration=True,
            require_priced_route=True,
        )
        self.assertEqual(missing_narration["verdict"], "FAIL")
        self.assertIn("startup narration request was not observed", missing_narration["reason"])
        self.assertIn("priced n3-luna dm_main route was not resolved", missing_narration["reason"])

    def test_expected_startup_allows_only_fully_attributed_exchange_rate_egress(self) -> None:
        known_origin = {
            "origin": {
                "project_frames": [proof.KNOWN_EXCHANGE_RATE_ORIGIN],
                "library_packages": ["requests"],
            },
            "hostname_class": "other",
            "thread_classes": ["background"],
            "count": 1,
        }
        base = {
            "sandbox_path_class": "repository_tmp/combat_capture",
            "conversation_history_message_count": 0,
            "conversation_history_user_message_count": 0,
            "game_thread_alive": True,
            "seconds_to_alive": 0.1,
            "router_calls": 1,
            "provider_function_calls": 0,
            "egress_attempts": [{"host_class": "non_loopback", "port": 443}],
            "egress_attributions": [known_origin],
            "ledger_reservations": 0,
            "observed_events": {},
            "initial_narration_request": {
                "capture_site": "llm_router",
                "task": "dm_main",
            },
            "expect_startup_narration": True,
        }

        accepted = proof.build_report(**base)
        self.assertEqual(accepted["verdict"], "PASS")
        self.assertEqual(
            accepted["known_product_contacts"],
            [{"name": proof.KNOWN_EXCHANGE_RATE_ORIGIN, "count": 1}],
        )
        proof_path = self.scratch / "known-product-contact" / "proof.json"
        proof._atomic_write_report(proof_path, accepted)
        written = json.loads(proof_path.read_text(encoding="ascii"))
        self.assertEqual(
            written["known_product_contacts"], accepted["known_product_contacts"]
        )

        mixed = dict(base)
        mixed["egress_attempts"] = [
            {"host_class": "non_loopback", "port": 443},
            {"host_class": "non_loopback", "port": 443},
        ]
        mixed["egress_attributions"] = [
            known_origin,
            {
                "origin": {
                    "project_frames": ["utils/llm_router.py:call"],
                    "library_packages": ["httpx"],
                },
                "hostname_class": "github",
                "thread_classes": ["background"],
                "count": 1,
            },
        ]
        mixed_report = proof.build_report(**mixed)
        self.assertEqual(mixed_report["verdict"], "FAIL")
        self.assertEqual(mixed_report["reason"], "unexpected egress origin")
        self.assertEqual(
            mixed_report["known_product_contacts"],
            [{"name": proof.KNOWN_EXCHANGE_RATE_ORIGIN, "count": 1}],
        )

        unattributed = dict(base)
        unattributed["egress_attempts"] = [
            {"host_class": "non_loopback", "port": 443},
            {"host_class": "non_loopback", "port": 443},
        ]
        unattributed_report = proof.build_report(**unattributed)
        self.assertEqual(unattributed_report["verdict"], "FAIL")
        self.assertEqual(unattributed_report["reason"], "unexpected egress origin")

        orphaned_attribution = dict(base)
        orphaned_attribution["egress_attempts"] = []
        orphaned_report = proof.build_report(**orphaned_attribution)
        self.assertEqual(orphaned_report["verdict"], "FAIL")
        self.assertEqual(orphaned_report["reason"], "unexpected egress origin")

        strict = dict(base)
        strict.pop("expect_startup_narration")
        strict.pop("initial_narration_request")
        strict["router_calls"] = 0
        strict_report = proof.build_report(**strict)
        self.assertEqual(strict_report["verdict"], "FAIL")
        self.assertEqual(strict_report["reason"], "socket attempt detected")
        self.assertEqual(strict_report["known_product_contacts"], [])

    def test_expected_startup_rejects_provider_classified_exchange_rate_egress(self) -> None:
        report = proof.build_report(
            sandbox_path_class="repository_tmp/combat_capture",
            conversation_history_message_count=0,
            conversation_history_user_message_count=0,
            game_thread_alive=True,
            seconds_to_alive=0.1,
            router_calls=1,
            provider_function_calls=0,
            egress_attempts=[{"host_class": "non_loopback", "port": 443}],
            egress_attributions=[
                {
                    "origin": {
                        "project_frames": [proof.KNOWN_EXCHANGE_RATE_ORIGIN],
                        "library_packages": [],
                    },
                    "hostname_class": "openrouter",
                    "thread_classes": ["background"],
                    "count": 1,
                }
            ],
            ledger_reservations=0,
            observed_events={},
            initial_narration_request={
                "capture_site": "llm_router",
                "task": "dm_main",
            },
            expect_startup_narration=True,
        )
        self.assertEqual(report["verdict"], "FAIL")
        self.assertEqual(report["reason"], "unexpected egress origin")
        self.assertEqual(report["known_product_contacts"], [])

    def test_fake_preintegrate_counts_named_stubs_and_integrates_once(self) -> None:
        sandbox = self._fake_preintegrate_sandbox()
        importer = FakePreintegrateImporter(sandbox)
        output_dir = self.scratch / "preintegrate-output"
        report = proof.run_preintegrate(
            sandbox_root=sandbox.relative_to(proof.REPO_ROOT),
            run_id="fake-preintegrate-1",
            output_dir=output_dir,
            host_importer=importer,
        )
        self.assertEqual(report["verdict"], "PASS")
        self.assertEqual(
            report["stub_call_counts"],
            {
                "module_stitcher.safety_review": 1,
                "module_stitcher.travel_narration": 1,
            },
        )
        self.assertEqual(importer.manager_calls, 1)
        self.assertEqual(importer.scan_calls, 1)
        self.assertEqual(importer.manager_calls_at_web_import, 0)
        self.assertFalse(importer.scan_attempted_at_web_import)
        self.assertNotIn("main", importer.names)
        self.assertLess(
            importer.names.index("web.web_interface"),
            importer.names.index("core.generators.module_stitcher"),
        )
        self.assertLess(
            importer.names.index("web.web_interface"),
            importer.names.index("core.managers.campaign_manager"),
        )
        self.assertEqual(report["registered_modules"], ["Capture_Arena"])
        self.assertEqual(report["detect_new_modules_after"], [])
        self.assertEqual(report["active_combat_encounter_after"], "")
        self.assertEqual(report["egress_attempts"], [])
        self.assertEqual(report["ledger_reservations"], 0)
        registry = json.loads(
            (sandbox / "modules" / "world_registry.json").read_text(encoding="utf-8")
        )
        self.assertIsInstance(registry["modules"], dict)
        output = output_dir / "preintegrate.json"
        self.assertTrue(output.is_file())
        self.assertEqual(json.loads(output.read_text(encoding="ascii")), report)
        self.assertFalse(importer.ledger_path.exists())

    def test_preintegrate_lets_product_create_missing_registry(self) -> None:
        sandbox = self._fake_preintegrate_sandbox(missing_registry=True)
        registry_path = sandbox / "modules" / "world_registry.json"
        self.assertFalse(registry_path.exists())
        importer = FakePreintegrateImporter(sandbox)
        report = proof.run_preintegrate(
            sandbox_root=sandbox.relative_to(proof.REPO_ROOT),
            run_id="fake-preintegrate-missing-registry",
            output_dir=self.scratch / "missing-registry-output",
            host_importer=importer,
        )
        self.assertEqual(report["verdict"], "PASS")
        self.assertFalse(importer.registry_exists_at_scan)
        self.assertEqual(importer.registry_writer_calls, 0)
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        self.assertIn("Capture_Arena", registry["modules"])
        self.assertEqual(report["registered_modules"], ["Capture_Arena"])

    def test_preintegrate_fails_if_product_does_not_register_capture_module(self) -> None:
        for mode in ("missing", "empty"):
            with self.subTest(post_scan_registry=mode):
                sandbox = self._fake_preintegrate_sandbox(missing_registry=True)
                importer = FakePreintegrateImporter(
                    sandbox,
                    create_registry_on_scan=mode == "empty",
                    register_capture_module=False,
                )
                report = proof.run_preintegrate(
                    sandbox_root=sandbox.relative_to(proof.REPO_ROOT),
                    run_id="fake-preintegrate-unregistered-" + mode,
                    output_dir=self.scratch / ("unregistered-" + mode),
                    host_importer=importer,
                )
                self.assertEqual(report["verdict"], "FAIL")
                self.assertLessEqual(len(report["reason"]), proof.MAX_REASON_LENGTH)
                self.assertTrue(report["reason"].isascii())
                if mode == "missing":
                    self.assertIn(
                        "world registry is unavailable after integration",
                        report["reason"],
                    )
                    self.assertFalse(
                        (sandbox / "modules" / "world_registry.json").exists()
                    )
                else:
                    self.assertEqual(report["registered_modules"], [])
                    self.assertIn("Capture_Arena", report["detect_new_modules_after"])

    def test_preintegrate_setup_blocked_reason_is_bounded_and_sanitized(self) -> None:
        sandbox = self._fake_preintegrate_sandbox()
        importer = FakePreintegrateImporter(sandbox, fail_name="web.web_interface")
        output_dir = self.scratch / "blocked-preintegrate"
        report = proof.run_preintegrate(
            sandbox_root=sandbox,
            run_id="fake-preintegrate-blocked",
            output_dir=output_dir,
            host_importer=importer,
        )
        blocked_reason = report["blocked_reason"]
        self.assertEqual(report["verdict"], "BLOCKED")
        self.assertTrue(blocked_reason.startswith("RuntimeError: "))
        self.assertLessEqual(len(blocked_reason), proof.MAX_BLOCKED_REASON_LENGTH)
        self.assertTrue(blocked_reason.isascii())
        serialized = (output_dir / "preintegrate.json").read_text(encoding="ascii")
        self.assertEqual(json.loads(serialized), report)
        for private_value in (
            "/outside/repo",
            "config",
            "API_KEY",
            "private-value",
        ):
            self.assertNotIn(private_value, serialized)

    def test_preintegrate_does_not_repeat_import_time_campaign_scan(self) -> None:
        sandbox = self._fake_preintegrate_sandbox()
        importer = FakePreintegrateImporter(sandbox, scan_during_web_import=True)
        report = proof.run_preintegrate(
            sandbox_root=sandbox,
            run_id="fake-preintegrate-import-scan",
            output_dir=self.scratch / "import-scan-output",
            host_importer=importer,
        )
        self.assertEqual(report["verdict"], "BLOCKED")
        self.assertIn("attempted during host import", report["blocked_reason"])
        self.assertEqual(importer.manager_calls, 1)
        self.assertEqual(importer.scan_calls, 1)

    def test_fake_preintegrate_blocks_and_records_uncovered_router_calls(self) -> None:
        sandbox = self._fake_preintegrate_sandbox()
        importer = FakePreintegrateImporter(sandbox, uncovered_call=True)
        report = proof.run_preintegrate(
            sandbox_root=sandbox,
            run_id="fake-preintegrate-uncovered",
            output_dir=self.scratch / "preintegrate-uncovered",
            host_importer=importer,
        )
        self.assertEqual(report["verdict"], "FAIL")
        self.assertEqual(report["router_calls"], 1)
        self.assertEqual(
            report["stub_call_counts"],
            {
                "module_stitcher.safety_review": 1,
                "module_stitcher.travel_narration": 1,
            },
        )
        serialized = json.dumps(report, ensure_ascii=True, sort_keys=True)
        self.assertNotIn("private-provider-token", serialized)
        self.assertNotIn("private_value", serialized)

    def test_preintegrate_report_is_bounded_redacted_and_fail_closed(self) -> None:
        report = proof.build_preintegrate_report(
            stub_call_counts={
                "module_stitcher.safety_review": proof.MAX_COUNTER + 10,
                "module_stitcher.travel_narration": -1,
                "provider_secret": "secret",
            },
            egress_attempts=[
                {
                    "host_class": "non_loopback",
                    "port": 443,
                    "host": "private.example",
                    "token": "private-token",
                }
            ],
            registered_modules=["Capture_Arena", "private module name"],
            detect_new_modules_after=[],
            active_combat_encounter_after="private-encounter-id",
            seed_checks={
                "registry_has_no_unregistered_modules": True,
                "no_active_combat": True,
                "no_history_user_messages": True,
                "provider_free_startup_seed": True,
            },
            router_calls=0,
            provider_function_calls=0,
            update_check_calls=0,
            ledger_reservations=0,
            ledger_valid=True,
        )
        self.assertEqual(report["verdict"], "FAIL")
        self.assertEqual(report["stub_call_counts"]["module_stitcher.safety_review"], proof.MAX_COUNTER)
        self.assertEqual(report["stub_call_counts"]["module_stitcher.travel_narration"], 0)
        self.assertEqual(report["registered_modules"], ["Capture_Arena"])
        self.assertEqual(report["active_combat_encounter_after"], "present")
        serialized = json.dumps(report, ensure_ascii=True, sort_keys=True)
        self.assertTrue(serialized.isascii())
        for private_value in (
            "private.example",
            "private-token",
            "private module name",
            "private-encounter-id",
            "provider_secret",
        ):
            self.assertNotIn(private_value, serialized)

    def test_preintegrate_cli_mode_defaults_and_explicit_selection(self) -> None:
        self.assertEqual(proof._parse_args([]).mode, "prove")
        self.assertEqual(proof._parse_args(["--mode", "preintegrate"]).mode, "preintegrate")
        for flag in ("--expect-startup-narration", "--require-priced-route"):
            with self.subTest(flag=flag), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    proof._parse_args(["--mode", "preintegrate", flag])

    def test_sandbox_rejects_symlink_missing_and_outside_tmp_paths(self) -> None:
        target = self.scratch / "target"
        target.mkdir()
        link = self.scratch / "link"
        link.symlink_to(target, target_is_directory=True)
        with self.assertRaises(ValueError):
            proof.validate_sandbox_root(link)
        with self.assertRaises(ValueError):
            proof.validate_sandbox_root(self.scratch / "missing")
        with self.assertRaises(ValueError):
            proof.validate_sandbox_root(proof.REPO_ROOT / "scripts")

    def test_fake_real_run_path_never_opens_config_text_or_exposes_payloads(self) -> None:
        sandbox = self._fake_sandbox()
        importer = FakeHostImporter(sandbox)
        opened_paths: list[str] = []
        real_open = builtins.open

        def recording_open(file: Any, *args: Any, **kwargs: Any) -> Any:
            path_text = os.fspath(file)
            opened_paths.append(path_text)
            if Path(path_text).name == "config.py":
                raise AssertionError("the proof tool attempted to open config.py")
            return real_open(file, *args, **kwargs)

        output = self.scratch / "proof.json"
        with patch("builtins.open", recording_open):
            report = proof.run_proof(
                sandbox_root=sandbox.relative_to(proof.REPO_ROOT),
                run_id="fake-run-1",
                output_dir=output,
                startup_timeout=0.2,
                settle_seconds=0.01,
                host_importer=importer,
            )
        self.assertEqual(report["verdict"], "PASS")
        self.assertEqual(report["egress_attempts"], [])
        self.assertEqual(report["ledger_reservations"], 0)
        self.assertEqual(report["update_check_calls"], 1)
        self.assertIn("read-only update check", report["notes"])
        self.assertEqual(report["observed_events"], {"game_output": 1, "status_update": 1})
        self.assertEqual(importer.web_module.socketio.seen_origin, proof.PROOF_ORIGIN)
        self.assertIn("web.web_interface", importer.names)
        self.assertNotIn("main", importer.names)
        self.assertLess(
            max(
                index
                for index, name in enumerate(importer.names)
                if name.startswith("openai.resources.")
            ),
            importer.names.index("web.web_interface"),
        )
        self.assertTrue(all(Path(path).name != "config.py" for path in opened_paths))
        serialized = output.read_text(encoding="ascii")
        self.assertNotIn("private-status", serialized)
        self.assertNotIn("private-output", serialized)

    def test_pre_start_handler_error_is_blocked_without_exposing_payload(self) -> None:
        sandbox = self._fake_sandbox()
        importer = FakeHostImporter(sandbox)
        importer.web_module.handler_error = True
        output = self.scratch / "blocked-proof.json"
        report = proof.run_proof(
            sandbox_root=sandbox,
            run_id="fake-blocked-1",
            output_dir=output,
            startup_timeout=0.2,
            settle_seconds=0.01,
            host_importer=importer,
        )
        self.assertEqual(report["verdict"], "BLOCKED")
        self.assertEqual(report["game_thread_alive"], False)
        self.assertTrue(report["blocked_reason"].startswith("RuntimeError: "))
        self.assertNotIn("private-handler-error", output.read_text(encoding="ascii"))

    def test_proof_setup_blocked_reason_is_written_without_sensitive_text(self) -> None:
        sandbox = self._fake_sandbox()
        importer = FakeHostImporter(sandbox, fail_name="web.web_interface")
        output = self.scratch / "blocked-proof-setup.json"
        report = proof.run_proof(
            sandbox_root=sandbox,
            run_id="fake-proof-setup-blocked",
            output_dir=output,
            startup_timeout=0.2,
            settle_seconds=0.01,
            host_importer=importer,
        )
        blocked_reason = report["blocked_reason"]
        self.assertEqual(report["verdict"], "BLOCKED")
        self.assertTrue(blocked_reason.startswith("RuntimeError: "))
        self.assertLessEqual(len(blocked_reason), proof.MAX_BLOCKED_REASON_LENGTH)
        self.assertTrue(blocked_reason.isascii())
        serialized = output.read_text(encoding="ascii")
        for private_value in (
            "/outside/repo",
            "config",
            "API_KEY",
            "private-value",
        ):
            self.assertNotIn(private_value, serialized)

    def test_output_path_and_run_id_are_bounded_to_repository_tmp(self) -> None:
        with self.assertRaises(ValueError):
            proof.validate_run_id("../bad")
        with self.assertRaises(ValueError):
            proof.resolve_output_file(proof.REPO_ROOT / "scripts" / "proof.json", "safe")
        output = proof.resolve_output_file(None, "safe-run")
        self.assertEqual(
            output,
            proof.REPO_ROOT
            / "tmp"
            / "router-rollout"
            / "v2-network"
            / "n3"
            / "start-game-proof"
            / "safe-run"
            / "proof.json",
        )


if __name__ == "__main__":
    unittest.main()
