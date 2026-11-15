# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Offline tests for the N3 start_game provider-free proof tool."""

from __future__ import annotations

import builtins
import contextlib
import errno
import importlib.machinery
import importlib.util
import io
import json
import os
import queue
import shutil
import socket
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock as unittest_mock


_DNS_RESOLVER_NAMES = (
    "getaddrinfo",
    "gethostbyname",
    "gethostbyname_ex",
    "gethostbyaddr",
    "getfqdn",
    "getnameinfo",
)


class _OfflineDnsFence:
    """Refuse resolver calls before they can reach the system resolver."""

    _AUDIT_EVENTS = {
        "socket.getaddrinfo",
        "socket.gethostbyname",
        "socket.gethostbyaddr",
        "socket.getnameinfo",
    }

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._lookup_count = 0
        self._audit_count = 0
        self._wrappers: dict[str, Any] = {}
        self._originals: dict[str, Any] = {}
        self._last_originals: dict[str, Any] = {}
        self._audit_hook_installed = False
        self._active = False

    @staticmethod
    def _refusal() -> socket.gaierror:
        return socket.gaierror(
            getattr(socket, "EAI_NONAME", -2),
            "offline test resolver refused name lookup",
        )

    def install(self) -> None:
        if self._active:
            return
        for name in _DNS_RESOLVER_NAMES:
            if not callable(getattr(socket, name, None)):
                continue
            self._originals[name] = getattr(socket, name)

            def refuse(*args: Any, _name: str = name, **kwargs: Any) -> Any:
                del args, kwargs, _name
                with self._lock:
                    self._lookup_count += 1
                raise self._refusal()

            refuse.__name__ = "offline_test_" + name
            self._wrappers[name] = refuse
            setattr(socket, name, refuse)
        if not self._audit_hook_installed:
            sys.addaudithook(self._audit)
            self._audit_hook_installed = True
        with self._lock:
            self._active = True

    def _audit(self, event: str, args: tuple[Any, ...]) -> None:
        del args
        if event in self._AUDIT_EVENTS:
            with self._lock:
                if not self._active:
                    return
                self._audit_count += 1
            raise self._refusal()

    def lookup_count(self) -> int:
        with self._lock:
            return self._lookup_count

    def audit_count(self) -> int:
        with self._lock:
            return self._audit_count

    def is_active(self) -> bool:
        with self._lock:
            active = self._active
        return active and all(
            getattr(socket, name, None) is wrapper
            for name, wrapper in self._wrappers.items()
        )

    def originals_snapshot(self) -> dict[str, Any]:
        return dict(self._originals or self._last_originals)

    def forget_restored_originals(self) -> None:
        self._last_originals = {}

    def restore(self) -> None:
        with self._lock:
            self._active = False
        originals = dict(self._originals)
        for name, original in reversed(tuple(self._originals.items())):
            setattr(socket, name, original)
        self._last_originals = originals
        self._originals = {}

    def assert_active(self) -> None:
        if not self.is_active():
            raise AssertionError("offline DNS resolver fence was replaced")

        before = self.audit_count()
        try:
            sys.audit(
                "socket.getaddrinfo",
                "offline-fence-probe.example.invalid",
                443,
                socket.AF_UNSPEC,
                socket.SOCK_STREAM,
                0,
            )
        except socket.gaierror:
            pass
        else:
            raise AssertionError("offline DNS audit fence was removed")
        if self.audit_count() != before + 1:
            raise AssertionError("offline DNS audit fence did not run")


_OFFLINE_DNS_FENCE = _OfflineDnsFence()


def _reject_resolver_patch(target: Any, attribute: Any = None) -> None:
    if (
        target is socket and attribute in _DNS_RESOLVER_NAMES
    ) or (
        isinstance(target, str)
        and target.rsplit(".", 1)[0] == "socket"
        and target.rsplit(".", 1)[-1] in _DNS_RESOLVER_NAMES
    ):
        raise AssertionError(
            "DNS resolver entry points cannot be replaced by test mocks"
        )


class _GuardedPatchFactory:
    """Keep unittest.mock from replacing the resolver fence in nested tests."""

    def __init__(self, patch_factory: Any) -> None:
        self._patch = patch_factory
        self._patch_object = patch_factory.object
        self._patch_dict = patch_factory.dict
        self._patch_multiple = patch_factory.multiple

    def __call__(self, target: Any, *args: Any, **kwargs: Any) -> Any:
        _reject_resolver_patch(target)
        return self._patch(target, *args, **kwargs)

    def object(
        self, target: Any, attribute: Any, *args: Any, **kwargs: Any
    ) -> Any:
        _reject_resolver_patch(target, attribute)
        return self._patch_object(target, attribute, *args, **kwargs)

    def dict(self, in_dict: Any, *args: Any, **kwargs: Any) -> Any:
        values = args[0] if args else kwargs.get("values", {})
        if in_dict is socket.__dict__ and any(
            name in values for name in _DNS_RESOLVER_NAMES
        ):
            raise AssertionError(
                "DNS resolver entry points cannot be replaced by test mocks"
            )
        return self._patch_dict(in_dict, *args, **kwargs)

    def multiple(self, target: Any, *args: Any, **kwargs: Any) -> Any:
        if isinstance(target, str) and target == "socket":
            if any(name in kwargs for name in _DNS_RESOLVER_NAMES):
                raise AssertionError(
                    "DNS resolver entry points cannot be replaced by test mocks"
                )
        if target is socket and any(
            name in kwargs for name in _DNS_RESOLVER_NAMES
        ):
            raise AssertionError(
                "DNS resolver entry points cannot be replaced by test mocks"
            )
        return self._patch_multiple(target, *args, **kwargs)


_RAW_PATCH_FACTORY = unittest_mock.patch
_RAW_PATCH_OBJECT = unittest_mock.patch.object
_MOCK_PATCH_STATE: dict[str, Any] | None = None
_RESTORED_MOCK_PATCH_STATE: dict[str, Any] | None = None


def _guard_nested_patch_enter(patcher: Any) -> Any:
    _reject_resolver_patch(patcher.getter(), getattr(patcher, "attribute", None))
    if _MOCK_PATCH_STATE is None:
        raise AssertionError("nested mock guard is outside the test suite")
    return _MOCK_PATCH_STATE["patch_enter"](patcher)


def _guard_nested_patch_dict_enter(patcher: Any) -> Any:
    values = getattr(patcher, "values", {})
    keys = set(values) if isinstance(values, dict) else set()
    keys.update(getattr(patcher, "kwargs", {}).keys())
    if (
        getattr(patcher, "in_dict", None) is socket.__dict__
        and keys.intersection(_DNS_RESOLVER_NAMES)
    ):
        raise AssertionError(
            "DNS resolver entry points cannot be replaced by test mocks"
        )
    if _MOCK_PATCH_STATE is None:
        raise AssertionError("nested mock guard is outside the test suite")
    return _MOCK_PATCH_STATE["patch_dict_enter"](patcher)


patch = _GuardedPatchFactory(_RAW_PATCH_FACTORY)


def _restore_test_harness() -> None:
    global _MOCK_PATCH_STATE, _RESTORED_MOCK_PATCH_STATE
    _OFFLINE_DNS_FENCE.restore()
    if _MOCK_PATCH_STATE is not None:
        unittest_mock._patch.__enter__ = _MOCK_PATCH_STATE["patch_enter"]
        unittest_mock._patch_dict.__enter__ = _MOCK_PATCH_STATE[
            "patch_dict_enter"
        ]
        _RESTORED_MOCK_PATCH_STATE = dict(_MOCK_PATCH_STATE)
        _MOCK_PATCH_STATE = None


def _assert_test_harness_restored() -> None:
    global _RESTORED_MOCK_PATCH_STATE
    state = _RESTORED_MOCK_PATCH_STATE
    try:
        if _OFFLINE_DNS_FENCE.is_active():
            raise AssertionError("offline DNS fence remained active after the suite")
        if state is None:
            raise AssertionError("unittest.mock state snapshot was not retained")
        for name, original in _OFFLINE_DNS_FENCE.originals_snapshot().items():
            if getattr(socket, name, None) is not original:
                raise AssertionError("socket resolver was not restored: " + name)
        if unittest_mock._patch.__enter__ is not state["patch_enter"]:
            raise AssertionError("unittest.mock patch entry was not restored")
        if unittest_mock._patch_dict.__enter__ is not state["patch_dict_enter"]:
            raise AssertionError("unittest.mock dict patch entry was not restored")
        if unittest_mock.patch is not state["patch_factory"]:
            raise AssertionError("unittest.mock.patch was replaced")
        if unittest_mock.patch.object is not state["patch_object"]:
            raise AssertionError("unittest.mock.patch.object was replaced")

        marker = SimpleNamespace(value="original")
        with unittest_mock.patch.object(marker, "value", "patched"):
            if marker.value != "patched":
                raise AssertionError("unrelated mock behavior was not restored")
        if marker.value != "original":
            raise AssertionError(
                "unrelated mock behavior did not restore its target"
            )
        if socket.inet_aton("127.0.0.1") != bytes((127, 0, 0, 1)):
            raise AssertionError("unrelated socket behavior changed")

        audit_count = _OFFLINE_DNS_FENCE.audit_count()
        sys.audit(
            "socket.getaddrinfo",
            "post-suite-fence-probe.example.invalid",
            443,
            socket.AF_UNSPEC,
            socket.SOCK_STREAM,
            0,
        )
        if _OFFLINE_DNS_FENCE.audit_count() != audit_count:
            raise AssertionError("offline DNS audit hook was not disabled")
    finally:
        _OFFLINE_DNS_FENCE.forget_restored_originals()
        _RESTORED_MOCK_PATCH_STATE = None


def setUpModule() -> None:
    global _MOCK_PATCH_STATE, proof
    if _MOCK_PATCH_STATE is not None:
        raise AssertionError("test harness setup is already active")
    _MOCK_PATCH_STATE = {
        "patch_factory": unittest_mock.patch,
        "patch_object": unittest_mock.patch.object,
        "patch_enter": unittest_mock._patch.__enter__,
        "patch_dict_enter": unittest_mock._patch_dict.__enter__,
    }
    try:
        _OFFLINE_DNS_FENCE.install()
        unittest_mock._patch.__enter__ = _guard_nested_patch_enter
        unittest_mock._patch_dict.__enter__ = _guard_nested_patch_dict_enter
        from scripts import n3_start_game_offline_proof as proof
    except BaseException:
        _restore_test_harness()
        raise


def tearDownModule() -> None:
    _restore_test_harness()
    _assert_test_harness_restored()


class FakeSocket:
    family = socket.AF_INET


class FakeIPv6Socket:
    family = socket.AF_INET6


class FakeInputQueue:
    def __init__(self, web_module: Any) -> None:
        self.web_module = web_module
        self.values: list[Any] = []

    def put(self, value: Any) -> None:
        self.values.append(value)
        self.web_module.alive = False


class FakeCompletions:
    @staticmethod
    def create(*args: Any, **kwargs: Any) -> None:
        del args, kwargs


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
        if getattr(self.web_module, "startup_diagnostic", False):
            self.web_module.alive = True
            try:
                for task in self.web_module.diagnostic_router_tasks:
                    self.web_module.router.call(
                        task=task,
                        messages=[{"role": "user", "content": "private-prompt-value"}],
                        model_tier="simple",
                    )
                if getattr(self.web_module, "process_launch", False):
                    process_args = getattr(
                        self.web_module, "process_launch_args", (["must-not-run"],)
                    )
                    process_kwargs = getattr(
                        self.web_module, "process_launch_kwargs", {}
                    )
                    proof.subprocess.run(*process_args, **process_kwargs)
                if getattr(self.web_module, "diagnostic_provider_call", False):
                    self.web_module.chat_completions.Completions.create(
                        model="private-model", prompt="private-sdk-prompt"
                    )
                egress_host = getattr(self.web_module, "egress_host", None)
                if isinstance(egress_host, str):
                    socket.getaddrinfo(egress_host, 443)
                self.web_module.game_output_queue.put(
                    {"type": "narration", "content": "private-startup-output"}
                )
                self.web_module.add_to_message_cache(
                    {"type": "narration", "content": "private-startup-output"}
                )
                self.web_module.dm_main.save_conversation_history(
                    [{"role": "assistant", "content": "private-startup-output"}]
                )
                with open("debug/quality_control/model_results.jsonl", "a", encoding="ascii") as stream:
                    stream.write("private-prompt-value private-startup-output")
                self.web_module.send_output_to_clients()
                self.web_module.socketio.emit(
                    "game_started", {"message": "private-started-message"}
                )
            except BaseException:
                self.web_module.alive = False
                raise
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
        self.active_client: FakeClient | None = None
        self.latest_version_result: Any = None

    def test_client(self, app: Any, headers: dict[str, str]) -> FakeClient:
        del app
        self.seen_origin = headers.get("Origin")
        self.latest_version_result = self.version_module.get_latest_remote_version(
            "fake/repo", "main", silent=True
        )
        self.active_client = FakeClient(self.web_module)
        return self.active_client

    def emit(self, name: str, *args: Any, **kwargs: Any) -> None:
        payload = args[0] if args else kwargs.get("data")
        if self.active_client is not None:
            self.active_client.events.append({"name": name, "args": [payload]})


class FakeHostImporter:
    def __init__(self, sandbox: Path, fail_name: str | None = None) -> None:
        self.names: list[str] = []
        self.fail_name = fail_name
        self.egress_during_web_import = False
        self.ledger_module = SimpleNamespace(
            __file__=str(sandbox / "utils" / "provider_attempt_budget.py"),
            activate_provider_attempt_budget=self.activate_budget
        )
        self.router_module = SimpleNamespace(
            __file__=str(sandbox / "utils" / "llm_router.py"),
            llm=SimpleNamespace(call=self.unused, decide=self.unused),
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
        self.factory_module = SimpleNamespace(
            __file__=str(sandbox / "utils" / "ai_client_factory.py"),
            create_chat_client=self.unused,
            create_image_client=self.unused,
            create_tts_client=self.unused,
            create_video_client=self.unused,
        )
        self.saved_histories: list[Any] = []
        self.cached_messages: list[Any] = []
        self.main_module = SimpleNamespace(
            __file__=str(sandbox / "main.py"),
            get_ai_response=self.unused,
            save_conversation_history=self.save_history,
        )
        self.version_module = SimpleNamespace(
            __file__=str(sandbox / "utils" / "version_checker.py"),
            _run_git_command=self.unused,
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
            startup_diagnostic=False,
            diagnostic_router_tasks=["action_prediction", "dm_main"],
            diagnostic_provider_call=False,
            process_launch=False,
            process_launch_args=(["must-not-run"],),
            process_launch_kwargs={},
        )
        self.web_module.user_input_queue = FakeInputQueue(self.web_module)
        self.web_module.game_output_queue = queue.Queue()
        self.web_module.send_output_to_clients = self.unused
        self.web_module.add_to_message_cache = self.cache_message
        self.chat_completions = SimpleNamespace(Completions=FakeCompletions)
        self.web_module.chat_completions = self.chat_completions
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

    def save_history(self, value: Any) -> None:
        self.saved_histories.append(value)

    def cache_message(self, value: Any) -> None:
        self.cached_messages.append(value)

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
        if name == "web.web_interface" and self.egress_during_web_import:
            socket.getaddrinfo("diagnostic-private.invalid", 443)
        if name == self.fail_name:
            raise RuntimeError(
                "setup failed at /outside/repo/config.py config API_KEY=private-value"
            )
        modules = {
            "utils.provider_attempt_budget": self.ledger_module,
            "utils.llm_router": self.router_module,
            "utils.ai_client_factory": self.factory_module,
            "utils.version_checker": self.version_module,
            "model_config": self.model_config_module,
            "web.web_interface": self.web_module,
        }
        if name in modules:
            return modules[name]
        if name == "openai.resources.chat.completions":
            return self.chat_completions
        if name.startswith("openai.resources."):
            raise ImportError("optional SDK module is unavailable in fake host")
        raise AssertionError("unexpected import request: " + name)


class IPv6ProbeHostImporter(FakeHostImporter):
    """Exercise an urllib3-style capability probe without real socket binds."""

    def __init__(
        self,
        sandbox: Path,
        *,
        fail_name: str | None = None,
        attempt_guarded_operations: bool = False,
    ) -> None:
        super().__init__(sandbox, fail_name=fail_name)
        self.has_ipv6_during_import: list[bool] = []
        self.probe_socket_created = False
        self.probe_bind_attempts: list[Any] = []
        self.attempt_guarded_operations = attempt_guarded_operations
        self.guarded_bind_error: str | None = None
        self.guarded_connect_error: str | None = None
        self.process_launch_blocked = False
        self._guarded_operations_attempted = False

    def _urllib3_style_ipv6_probe(self) -> None:
        if not socket.has_ipv6:
            return

        self.probe_socket_created = True

        class ProbeSocket:
            def bind(inner_self: Any, address: Any) -> None:
                del inner_self
                self.probe_bind_attempts.append(address)

        ProbeSocket().bind(("::1", 0))

    def _attempt_guarded_operations(self) -> None:
        try:
            socket.socket.bind(FakeIPv6Socket(), ("::1", 0))
        except OSError as exc:
            self.guarded_bind_error = type(exc).__name__

        try:
            socket.socket.connect(FakeSocket(), ("198.51.100.20", 9443))
        except ConnectionRefusedError as exc:
            self.guarded_connect_error = type(exc).__name__

        try:
            proof.subprocess.run(["must-not-run"])
        except proof.ProviderCallBlocked:
            self.process_launch_blocked = True

    def __call__(self, name: str) -> Any:
        self.has_ipv6_during_import.append(socket.has_ipv6)
        self._urllib3_style_ipv6_probe()
        if (
            self.attempt_guarded_operations
            and not self._guarded_operations_attempted
        ):
            self._guarded_operations_attempted = True
            self._attempt_guarded_operations()
        return super().__call__(name)


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


class _TemporarySnippetLoader(importlib.machinery.SourceFileLoader):
    """Load source from a test temp file with a controlled traceback filename."""

    def __init__(
        self, fullname: str, snippet_path: Path, frame_filename: str
    ) -> None:
        super().__init__(fullname, os.fspath(snippet_path))
        self._snippet_path = snippet_path
        self._frame_filename = frame_filename

    def get_filename(self, fullname: str) -> str:
        del fullname
        return self._frame_filename

    def get_data(self, path: str) -> bytes:
        if os.fspath(path) != self._frame_filename:
            raise OSError("temporary snippet bytecode is unavailable")
        return self._snippet_path.read_bytes()

    def path_stats(self, path: str) -> dict[str, int]:
        if os.fspath(path) != self._frame_filename:
            raise OSError("temporary snippet source is unavailable")
        stat = self._snippet_path.stat()
        return {"mtime": int(stat.st_mtime), "size": stat.st_size}

    def set_data(
        self, path: str, data: bytes, *, _mode: int = 0o666
    ) -> None:
        del path, data, _mode


class N3StartGameOfflineProofTests(unittest.TestCase):
    def setUp(self) -> None:
        _OFFLINE_DNS_FENCE.assert_active()
        self._audit_count_at_start = _OFFLINE_DNS_FENCE.audit_count()
        self._lookup_count_at_start = _OFFLINE_DNS_FENCE.lookup_count()
        self._expected_dns_audit_events = 0
        self._expected_offline_dns_refusals = 0
        self.scratch_parent = proof.REPO_ROOT / "tmp"
        self.scratch_parent.mkdir(parents=True, exist_ok=True)
        self.scratch = Path(
            tempfile.mkdtemp(prefix="n3-start-game-proof-tests-", dir=self.scratch_parent)
        )
        self._snippet_index = 0

    def _load_temporary_snippet(
        self,
        source: str,
        *,
        frame_filename: str,
        initial_globals: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._snippet_index += 1
        snippet_dir = self.scratch / "snippets"
        snippet_dir.mkdir(parents=True, exist_ok=True)
        snippet_path = snippet_dir / ("snippet-%d.py" % self._snippet_index)
        snippet_path.write_text(source, encoding="utf-8")
        module_name = "_n3_offline_snippet_%d" % self._snippet_index
        loader = _TemporarySnippetLoader(
            module_name, snippet_path, frame_filename
        )
        spec = importlib.util.spec_from_file_location(
            module_name, snippet_path, loader=loader
        )
        if spec is None or spec.loader is not loader:
            raise AssertionError("temporary snippet loader setup failed")
        module = importlib.util.module_from_spec(spec)
        if initial_globals is not None:
            module.__dict__.update(initial_globals)
        loader.exec_module(module)
        return module.__dict__

    def tearDown(self) -> None:
        try:
            _OFFLINE_DNS_FENCE.assert_active()
            self.assertEqual(
                _OFFLINE_DNS_FENCE.audit_count(),
                self._audit_count_at_start + self._expected_dns_audit_events + 1,
                "a test path reached the resolver audit boundary",
            )
            self.assertEqual(
                _OFFLINE_DNS_FENCE.lookup_count(),
                self._lookup_count_at_start + self._expected_offline_dns_refusals,
                "a guarded test path fell through to the harness resolver fence",
            )
        finally:
            shutil.rmtree(self.scratch, ignore_errors=True)

    def test_offline_diagnostic_config_has_explicit_inert_defaults(self) -> None:
        imported_config_names: list[str] = []
        original_import = builtins.__import__

        def reject_real_config_import(
            name: str, *args: Any, **kwargs: Any
        ) -> Any:
            if name == "config" or name.startswith("config."):
                imported_config_names.append(name)
                raise AssertionError("offline defaults must not import config.py")
            return original_import(name, *args, **kwargs)

        with patch.object(
            builtins, "__import__", side_effect=reject_real_config_import
        ):
            config = proof._offline_diagnostic_config_module()

        self.assertEqual(imported_config_names, [])
        self.assertEqual(config.__file__, "<offline-diagnostic-config>")
        self.assertNotIn("__getattr__", config.__dict__)
        with self.assertRaises(AttributeError):
            getattr(config, "UNDECLARED_OFFLINE_SETTING")
        self.assertEqual(config.OPENAI_API_KEY, "")
        self.assertEqual(config.OPENROUTER_API_KEY, "")
        for name in (
            "DM_MAIN_MODEL",
            "PLAYER_INFO_UPDATE_MODEL",
            "NPC_INFO_UPDATE_MODEL",
            "COMBAT_MAIN_MODEL",
            "COMBAT_DIALOGUE_SUMMARY_MODEL",
            "DM_SUMMARIZATION_MODEL",
            "DM_VALIDATION_MODEL",
            "DM_MINI_MODEL",
            "DM_FULL_MODEL",
            "GPT5_MINI_MODEL",
            "GPT5_FULL_MODEL",
            "LEVEL_UP_MODEL",
        ):
            with self.subTest(model=name):
                self.assertEqual(getattr(config, name), "offline-diagnostic")
        self.assertFalse(config.ENABLE_INTELLIGENT_ROUTING)
        self.assertFalse(config.USE_GPT5_MODELS)
        self.assertFalse(config.GPT5_USE_HIGH_REASONING_ON_RETRY)
        self.assertFalse(config.MULTIPLAYER_MODE)

    def _fake_sandbox(self) -> Path:
        sandbox = self.scratch / "combat_capture"
        for relative in (
            "main.py",
            "web/web_interface.py",
            "utils/llm_router.py",
            "utils/ai_client_factory.py",
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

        fence_lookup_count = _OFFLINE_DNS_FENCE.lookup_count()
        fence_audit_count = _OFFLINE_DNS_FENCE.audit_count()
        with (
            patch.object(socket.socket, "connect") as connect_spy,
            patch.object(socket.socket, "connect_ex") as connect_ex_spy,
            patch.object(socket, "create_connection") as create_connection_spy,
        ):
            guard = proof.EgressGuard()
            with guard:
                with self.assertRaises(ConnectionRefusedError) as connect_error:
                    socket.socket.connect(FakeSocket(), ("198.51.100.20", 9443))
                self.assertEqual(connect_error.exception.errno, errno.ECONNREFUSED)
                with self.assertRaises(ConnectionRefusedError):
                    socket.socket.connect_ex(
                        FakeSocket(), ("198.51.100.23", 9446)
                    )
                with self.assertRaises(ConnectionRefusedError):
                    socket.create_connection(("198.51.100.21", 9444))
                with self.assertRaises(socket.gaierror):
                    socket.getaddrinfo("198.51.100.22", 9445)
                with self.assertRaises(socket.gaierror):
                    socket.gethostbyname("denied-name.example")
                with self.assertRaises(socket.gaierror):
                    socket.gethostbyname("localhost")

            for network_spy in (
                connect_spy,
                connect_ex_spy,
                create_connection_spy,
            ):
                network_spy.assert_not_called()
        self.assertEqual(_OFFLINE_DNS_FENCE.lookup_count(), fence_lookup_count)
        self.assertEqual(_OFFLINE_DNS_FENCE.audit_count(), fence_audit_count)

        self.assertEqual(
            guard.snapshot(),
            [
                {"host_class": "non_loopback", "port": 9443},
                {"host_class": "non_loopback", "port": 9446},
                {"host_class": "non_loopback", "port": 9444},
                {"host_class": "non_loopback", "port": 9445},
                {"host_class": "non_loopback", "port": None},
                {"host_class": "non_loopback", "port": None},
            ],
        )
        refusals, refusal_count = guard.refusal_snapshot()
        self.assertEqual(refusal_count, 6)
        self.assertEqual(len(refusals), refusal_count)
        self.assertEqual(refusals[0]["hostname"], "198.51.100.20")
        self.assertEqual(refusals[0]["port"], 9443)
        self.assertEqual(refusals[-1]["hostname"], "localhost")
        self.assertEqual(refusals[-1]["port"], "unavailable")

    def test_refusal_attribution_is_exact_and_secret_safe(self) -> None:
        unsafe_url = (
            "https://private-user:private-password@example.invalid/path?token=private-value"
        )
        token_like_host = "sk-" + ("a" * 24) + ".example.invalid"
        fence_lookup_count = _OFFLINE_DNS_FENCE.lookup_count()
        fence_audit_count = _OFFLINE_DNS_FENCE.audit_count()
        guard = proof.EgressGuard()
        guard.set_sandbox_root(proof.REPO_ROOT)
        with guard:
            with self.assertRaises(socket.gaierror):
                socket.getaddrinfo("Exact.Example.invalid.", 9443)
            with self.assertRaises(socket.gaierror):
                socket.getaddrinfo(unsafe_url, 9444)
            with self.assertRaises(socket.gaierror):
                socket.getaddrinfo(token_like_host, 9445)
        self.assertEqual(_OFFLINE_DNS_FENCE.lookup_count(), fence_lookup_count)
        self.assertEqual(_OFFLINE_DNS_FENCE.audit_count(), fence_audit_count)

        refusals, refusal_count = guard.refusal_snapshot()
        self.assertEqual(refusal_count, 3)
        self.assertEqual(len(refusals), 3)
        exact = refusals[0]
        self.assertEqual(exact["hostname"], "Exact.Example.invalid.")
        self.assertEqual(exact["port"], 9443)
        self.assertEqual(exact["thread_id"], proof.threading.get_ident())
        self.assertEqual(exact["thread_class"], "main")
        self.assertRegex(
            exact["call_site"],
            r"^scripts/test_n3_start_game_offline_proof.py:[1-9][0-9]*$",
        )
        self.assertEqual(refusals[1]["hostname"], "unavailable")
        self.assertEqual(refusals[2]["hostname"], "unavailable")
        serialized = json.dumps(refusals, ensure_ascii=True, sort_keys=True)
        for secret in (
            "private-user",
            "private-password",
            "private-value",
            token_like_host,
            "https://",
        ):
            self.assertNotIn(secret, serialized)
        self.assertEqual(
            set(exact),
            {
                "hostname",
                "port",
                "thread_id",
                "thread_class",
                "call_site",
                "sequence",
            },
        )

    def test_offline_resolver_fence_refuses_unguarded_lookup_and_nested_mocks(
        self,
    ) -> None:
        host = "api.openrouter.ai"
        lookups = (
            ("getaddrinfo", lambda: socket.getaddrinfo(host, 443)),
            ("gethostbyname", lambda: socket.gethostbyname(host)),
            ("gethostbyname_ex", lambda: socket.gethostbyname_ex(host)),
            ("gethostbyaddr", lambda: socket.gethostbyaddr(host)),
            ("getfqdn", lambda: socket.getfqdn(host)),
            ("getnameinfo", lambda: socket.getnameinfo((host, 443), 0)),
        )
        fence_audit_count = _OFFLINE_DNS_FENCE.audit_count()
        for resolver_name, lookup in lookups:
            with self.subTest(resolver=resolver_name):
                fence_lookup_count = _OFFLINE_DNS_FENCE.lookup_count()
                continued_after_refusal = False
                try:
                    lookup()
                except socket.gaierror:
                    continued_after_refusal = True

                self.assertTrue(continued_after_refusal)
                self.assertEqual(
                    _OFFLINE_DNS_FENCE.lookup_count(), fence_lookup_count + 1
                )
        self.assertEqual(_OFFLINE_DNS_FENCE.audit_count(), fence_audit_count)
        self._expected_offline_dns_refusals += len(lookups)

        with patch.object(socket, "create_connection"):
            with self.assertRaisesRegex(AssertionError, "cannot be replaced"):
                with patch.object(socket, "getaddrinfo"):
                    pass
            with self.assertRaisesRegex(AssertionError, "cannot be replaced"):
                with patch("socket.getaddrinfo"):
                    pass
            with self.assertRaisesRegex(AssertionError, "cannot be replaced"):
                with _RAW_PATCH_OBJECT(socket, "getaddrinfo"):
                    pass

        audit_count = _OFFLINE_DNS_FENCE.audit_count()
        with self.assertRaises(socket.gaierror):
            sys.audit(
                "socket.getaddrinfo",
                "api.openrouter.ai",
                443,
                socket.AF_UNSPEC,
                socket.SOCK_STREAM,
                0,
            )
        self.assertEqual(_OFFLINE_DNS_FENCE.audit_count(), audit_count + 1)
        self._expected_dns_audit_events += 1

    def test_startup_diagnostic_stubs_ordered_tasks_and_records_nested_call_sites(self) -> None:
        sandbox = self._fake_sandbox()
        importer = FakeHostImporter(sandbox)
        recorder = proof.ProviderCallRecorder(diagnostic_mode=True)
        frame = SimpleNamespace(
            f_code=SimpleNamespace(
                co_filename=str(sandbox / "core" / "nested" / "startup.py")
            ),
            f_lineno=73,
            f_back=None,
        )
        responses = []
        for task in ("action_prediction", "dm_main"):
            responses.append(
                recorder.diagnostic_router_call(
                    (),
                    {
                        "task": task,
                        "messages": [
                            {"role": "user", "content": "private-prompt-value"}
                        ],
                        "model_tier": "simple",
                    },
                    model_config=importer.model_config_module,
                    sandbox_root=sandbox,
                    caller_frame=frame,
                )
            )

        events, stub_counts, failure, overflow = recorder.diagnostic_snapshot()
        self.assertEqual(responses, [proof.DIAGNOSTIC_STUB_RESPONSES[task] for task in proof.DIAGNOSTIC_TASKS])
        self.assertEqual([event["task"] for event in events], list(proof.DIAGNOSTIC_TASKS))
        self.assertEqual([event["sequence"] for event in events], [1, 2])
        self.assertEqual(
            [event["call_site"] for event in events],
            ["core/nested/startup.py:73", "core/nested/startup.py:73"],
        )
        self.assertEqual([event["profile"] for event in events], ["proof-profile"] * 2)
        self.assertEqual(
            [event["thread_id"] for event in events], [proof.threading.get_ident()] * 2
        )
        self.assertEqual([event["thread_class"] for event in events], ["main"] * 2)
        self.assertEqual(stub_counts, {"action_prediction": 1, "dm_main": 1})
        self.assertIsNone(failure)
        self.assertFalse(overflow)
        serialized = json.dumps(events, ensure_ascii=True, sort_keys=True)
        self.assertNotIn("private-prompt-value", serialized)
        self.assertEqual(
            set(events[0]),
            {"task", "profile", "call_site", "thread_id", "thread_class", "sequence"},
        )

    def test_startup_diagnostic_unknown_extra_and_overflow_calls_fail_closed(self) -> None:
        sandbox = self._fake_sandbox()
        importer = FakeHostImporter(sandbox)

        def invoke(recorder: Any, task: str) -> Any:
            return recorder.diagnostic_router_call(
                (),
                {"task": task},
                model_config=importer.model_config_module,
                sandbox_root=sandbox,
                caller_frame=SimpleNamespace(
                    f_code=SimpleNamespace(
                        co_filename=str(sandbox / "utils" / "llm_router.py")
                    ),
                    f_lineno=42,
                    f_back=None,
                ),
            )

        unknown = proof.ProviderCallRecorder(diagnostic_mode=True)
        with self.assertRaises(proof.ProviderCallBlocked):
            invoke(unknown, "unexpected_task")
        self.assertEqual(unknown.diagnostic_snapshot()[2], "unrecognized startup router task")

        extra = proof.ProviderCallRecorder(diagnostic_mode=True)
        invoke(extra, "action_prediction")
        with self.assertRaises(proof.ProviderCallBlocked):
            invoke(extra, "action_prediction")
        self.assertEqual(extra.diagnostic_snapshot()[2], "extra startup router call")

        overflow = proof.ProviderCallRecorder(
            diagnostic_mode=True, diagnostic_call_limit=2
        )
        invoke(overflow, "action_prediction")
        invoke(overflow, "dm_main")
        with self.assertRaises(proof.ProviderCallBlocked):
            invoke(overflow, "action_prediction")
        self.assertEqual(overflow.diagnostic_snapshot()[3], True)

    def test_startup_diagnostic_rejects_loopback_egress(self) -> None:
        guard = proof.EgressGuard(deny_loopback=True)
        with guard:
            with self.assertRaises(proof.EgressBlocked):
                guard._record("127.0.0.1", 8360, record_loopback=False)
            with self.assertRaises(proof.EgressBlocked):
                socket.socket.sendto(FakeSocket(), b"x", ("127.0.0.1", 8360))
            with self.assertRaises(proof.EgressBlocked):
                socket.socket.send(FakeSocket(), b"x")
            with self.assertRaises(socket.gaierror):
                socket.gethostbyname("example.invalid")
            with self.assertRaises(socket.gaierror):
                socket.getaddrinfo("127.0.0.1", 8360)
            with self.assertRaises(proof.EgressBlocked):
                socket.socket.bind(FakeSocket(), ("127.0.0.1", 8360))
            with self.assertRaises(proof.EgressBlocked):
                socket.socket.listen(FakeSocket(), 1)
            with self.assertRaises(ConnectionRefusedError):
                socket.socket.connect(FakeSocket(), ("198.51.100.24", 8361))
        self.assertEqual(guard.attempt_count(), 8)

    def test_ipv6_loopback_bind_probe_raises_oserror_without_binding(self) -> None:
        guard = proof.EgressGuard(deny_loopback=True)
        with patch.object(socket.socket, "bind") as bind_spy:
            with guard:
                continued_after_refusal = False
                try:
                    socket.socket.bind(FakeIPv6Socket(), ("::1", 0))
                except OSError as exc:
                    continued_after_refusal = True
                    self.assertEqual(exc.errno, errno.EPERM)

                self.assertTrue(continued_after_refusal)
            bind_spy.assert_not_called()

        self.assertEqual(guard.attempt_count(), 1)
        self.assertEqual(
            guard.snapshot(),
            [{"host_class": "loopback", "port": 0}],
        )
        refusals, refusal_count = guard.refusal_snapshot()
        self.assertEqual(refusal_count, 1)
        self.assertEqual(len(refusals), 1)
        refusal = refusals[0]
        self.assertEqual(refusal["hostname"], "::1")
        self.assertEqual(refusal["port"], 0)
        self.assertEqual(refusal["thread_id"], proof.threading.get_ident())
        self.assertEqual(refusal["thread_class"], "main")
        self.assertRegex(
            refusal["call_site"],
            r"^scripts/test_n3_start_game_offline_proof.py:[1-9][0-9]*$",
        )

        report_args = {
            "call_events": [],
            "stub_call_counts": {},
            "router_calls": 0,
            "provider_calls": 0,
            "network_attempts": 1,
            "ledger_reservations": 0,
            "ledger_valid": True,
            "startup_output_delivered": False,
            "game_started": False,
            "startup_thread_stopped": True,
            "diagnostic_failure": None,
            "call_overflow": False,
            "router_call_guard": True,
            "router_decide_guard": True,
            "sdk_tripwire_count": 1,
            "egress_guard_active": True,
            "process_launch_guard": True,
            "host_imports_verified": True,
            "startup_boundary_guard_active": True,
            "egress_refusals": refusals,
            "egress_refusal_count": refusal_count,
        }
        complete_report = proof._startup_diagnostic_report(**report_args)
        self.assertTrue(complete_report["egress_refusal_coverage_complete"])
        self.assertTrue(complete_report["coverage_established"])

        incomplete_refusal = dict(refusal, call_site="unavailable")
        report_args["egress_refusals"] = [incomplete_refusal]
        incomplete_report = proof._startup_diagnostic_report(**report_args)
        self.assertFalse(incomplete_report["egress_refusal_coverage_complete"])
        self.assertFalse(incomplete_report["coverage_established"])

    def test_startup_worker_environment_drops_ambient_credentials_and_path(self) -> None:
        with patch.dict(
            os.environ,
            {
                "PATH": "/private/tool-path",
                "LANG": "C",
                "OPENAI_API_KEY": "test-secret-value",
                "HTTP_PROXY": "http://proxy.invalid",
                "NEQ_PROVIDER_ATTEMPT_LEDGER": "private-ledger-path",
                "PYTHONPATH": "private-python-path",
            },
            clear=True,
        ):
            environment = proof._startup_diagnostic_worker_environment()

        self.assertEqual(environment["PATH"], "")
        self.assertEqual(environment["PYTHONPATH"], str(proof.REPO_ROOT))
        self.assertEqual(environment["NEQ_OPEN_BROWSER"], "0")
        self.assertNotIn("OPENAI_API_KEY", environment)
        self.assertNotIn("HTTP_PROXY", environment)
        self.assertNotIn("NEQ_PROVIDER_ATTEMPT_LEDGER", environment)
        self.assertNotIn("private-tool-path", json.dumps(environment))

    def test_sensitive_prompt_and_model_log_paths_are_discarded(self) -> None:
        sandbox = self._fake_sandbox()
        self.assertTrue(
            proof._is_sensitive_diagnostic_log_path(
                sandbox / "debug" / "quality_control" / "model_results.jsonl",
                sandbox,
            )
        )
        self.assertTrue(
            proof._is_sensitive_diagnostic_log_path(
                Path(tempfile.gettempdir()) / "temp_conversation_for_api.json",
                sandbox,
            )
        )

    def test_startup_diagnostic_observes_fake_start_game_without_claiming_real_coverage(self) -> None:
        sandbox = self._fake_sandbox()
        importer = FakeHostImporter(sandbox)
        importer.web_module.startup_diagnostic = True
        report = proof.run_startup_diagnostic(
            sandbox_root=sandbox,
            run_id="startup-diagnostic-success",
            output_dir=self.scratch / "startup-diagnostic-success",
            startup_timeout=0.5,
            host_importer=importer,
        )

        self.assertEqual(report["verdict"], "BLOCKED")
        self.assertTrue(report["startup_output_delivered"])
        self.assertTrue(report["game_started"])
        self.assertTrue(report["startup_thread_stopped"])
        self.assertFalse(report["coverage_established"])
        self.assertFalse(report["tripwire_coverage"]["real_host_imports"])
        self.assertTrue(report["tripwire_coverage"]["process_launch"])
        self.assertEqual(
            report["reason"],
            "complete real sandbox host imports were not verified",
        )
        self.assertTrue(report["tripwire_coverage"]["startup_boundaries"])
        self.assertEqual(
            [item["task"] for item in report["call_trace"]],
            ["action_prediction", "dm_main"],
        )
        self.assertEqual([item["sequence"] for item in report["call_trace"]], [1, 2])
        self.assertTrue(
            all(item["call_site"].startswith("scripts/test_n3_start_game_offline_proof.py:")
                for item in report["call_trace"])
        )
        self.assertEqual(importer.web_module.user_input_queue.values, ["/quit"])
        self.assertEqual(importer.saved_histories, [])
        self.assertEqual(importer.cached_messages, [])
        self.assertNotIn("config", importer.names)
        self.assertFalse(
            (sandbox / "debug" / "quality_control" / "model_results.jsonl").exists()
        )
        serialized = json.dumps(report, ensure_ascii=True, sort_keys=True)
        for private_value in (
            "private-prompt-value",
            "private-startup-output",
            "private-started-message",
            "private-sdk-prompt",
            "private-model",
        ):
            self.assertNotIn(private_value, serialized)
        written = json.loads(
            (
                self.scratch
                / "startup-diagnostic-success"
                / "startup-diagnostic.json"
            ).read_text(encoding="ascii")
        )
        self.assertEqual(written, report)

    def test_startup_diagnostic_skips_ipv6_capability_bind_probe(self) -> None:
        sandbox = self._fake_sandbox()
        importer = IPv6ProbeHostImporter(sandbox)
        importer.web_module.startup_diagnostic = True
        original_has_ipv6 = socket.has_ipv6

        with patch.object(socket, "has_ipv6", True):
            report = proof.run_startup_diagnostic(
                sandbox_root=sandbox,
                run_id="startup-diagnostic-no-ipv6-probe",
                output_dir=self.scratch / "startup-diagnostic-no-ipv6-probe",
                startup_timeout=0.5,
                host_importer=importer,
            )
            self.assertIs(socket.has_ipv6, True)

        self.assertIs(socket.has_ipv6, original_has_ipv6)
        self.assertTrue(importer.has_ipv6_during_import)
        self.assertTrue(all(value is False for value in importer.has_ipv6_during_import))
        self.assertFalse(importer.probe_socket_created)
        self.assertEqual(importer.probe_bind_attempts, [])
        self.assertEqual(report["network_attempt_count"], 0)
        self.assertEqual(report["provider_call_count"], 0)
        self.assertEqual(report["ledger_reservation_count"], 0)
        self.assertEqual(
            [event["task"] for event in report["call_trace"]],
            ["action_prediction", "dm_main"],
        )
        self.assertTrue(report["startup_output_delivered"])
        self.assertTrue(report["game_started"])
        self.assertNotEqual(report["verdict"], "PASS")

    def test_startup_diagnostic_restores_ipv6_capability_after_import_error(self) -> None:
        sandbox = self._fake_sandbox()
        importer = IPv6ProbeHostImporter(
            sandbox, fail_name="utils.provider_attempt_budget"
        )
        original_has_ipv6 = socket.has_ipv6

        with patch.object(socket, "has_ipv6", True):
            report = proof.run_startup_diagnostic(
                sandbox_root=sandbox,
                run_id="startup-diagnostic-ipv6-probe-import-error",
                output_dir=self.scratch / "startup-diagnostic-ipv6-probe-import-error",
                startup_timeout=0.2,
                host_importer=importer,
            )
            self.assertIs(socket.has_ipv6, True)

        self.assertIs(socket.has_ipv6, original_has_ipv6)
        self.assertEqual(importer.has_ipv6_during_import, [False])
        self.assertFalse(importer.probe_socket_created)
        self.assertEqual(importer.probe_bind_attempts, [])
        self.assertEqual(report["verdict"], "BLOCKED")
        self.assertEqual(report["network_attempt_count"], 0)

    def test_ipv6_probe_suppression_keeps_network_and_process_guards_active(
        self,
    ) -> None:
        sandbox = self._fake_sandbox()
        importer = IPv6ProbeHostImporter(
            sandbox, attempt_guarded_operations=True
        )
        importer.web_module.startup_diagnostic = True
        original_has_ipv6 = socket.has_ipv6

        with patch.object(socket, "has_ipv6", True), patch.object(
            proof.subprocess, "run"
        ) as underlying_spawn:
            report = proof.run_startup_diagnostic(
                sandbox_root=sandbox,
                run_id="startup-diagnostic-ipv6-guard-invariants",
                output_dir=self.scratch / "startup-diagnostic-ipv6-guard-invariants",
                startup_timeout=0.5,
                host_importer=importer,
            )
            self.assertIs(socket.has_ipv6, True)
            underlying_spawn.assert_not_called()

        self.assertIs(socket.has_ipv6, original_has_ipv6)
        self.assertTrue(all(value is False for value in importer.has_ipv6_during_import))
        self.assertFalse(importer.probe_socket_created)
        self.assertEqual(importer.probe_bind_attempts, [])
        self.assertEqual(importer.guarded_bind_error, "PermissionError")
        self.assertEqual(importer.guarded_connect_error, "ConnectionRefusedError")
        self.assertTrue(importer.process_launch_blocked)
        self.assertEqual(report["verdict"], "BLOCKED")
        self.assertEqual(report["network_attempt_count"], 2)
        self.assertTrue(report["egress_refusal_coverage_complete"])
        self.assertTrue(report["tripwire_coverage"]["process_launch"])

    def test_startup_diagnostic_stubs_git_probe_and_blocks_other_process_launches(
        self,
    ) -> None:
        from utils import version_checker

        sandbox = self._fake_sandbox()
        importer = FakeHostImporter(sandbox)
        importer.web_module.startup_diagnostic = True
        importer.web_module.process_launch = True
        importer.version_module = version_checker
        socketio = importer.web_module.socketio
        socketio.version_module = version_checker
        original_test_client = socketio.test_client
        original_git_probe = version_checker._run_git_command
        original_latest_version = version_checker.get_latest_remote_version
        original_subprocess_run = proof.subprocess.run

        def check_for_updates_before_connect(
            app: Any, headers: dict[str, str]
        ) -> FakeClient:
            socketio.check_for_updates_result = version_checker.check_for_updates(
                silent=True
            )
            return original_test_client(app, headers)

        with (
            patch.object(
                version_checker,
                "__file__",
                str(sandbox / "utils" / "version_checker.py"),
            ),
            patch.object(
                socketio,
                "test_client",
                side_effect=check_for_updates_before_connect,
            ),
            patch.object(proof.subprocess, "run") as underlying_spawn,
        ):
            report = proof.run_startup_diagnostic(
                sandbox_root=sandbox,
                run_id="startup-diagnostic-git-probe-refusal",
                output_dir=self.scratch / "startup-diagnostic-git-probe-refusal",
                startup_timeout=0.5,
                host_importer=importer,
            )

            underlying_spawn.assert_not_called()
            self.assertIs(proof.subprocess.run, underlying_spawn)
            self.assertIs(version_checker._run_git_command, original_git_probe)
            self.assertIs(
                version_checker.get_latest_remote_version, original_latest_version
            )

        self.assertIs(proof.subprocess.run, original_subprocess_run)
        self.assertEqual(
            socketio.check_for_updates_result[:3],
            ("unknown", "0.0.0", None),
        )
        self.assertIn(
            "Could not resolve fork update source",
            socketio.check_for_updates_result[3],
        )
        self.assertIsNone(socketio.latest_version_result)
        self.assertEqual(report["verdict"], "BLOCKED")
        self.assertEqual(report["failure_category"], "process_launch_blocked")
        self.assertTrue(report["tripwire_coverage"]["process_launch"])
        self.assertEqual(report["process_launch_refusal"]["status"], "redacted")
        self.assertIs(socketio.test_client.__func__, FakeSocketIO.test_client)

    def test_host_import_failure_reports_safe_source_and_line_only(self) -> None:
        sandbox = self._fake_sandbox()
        base_importer = FakeHostImporter(sandbox)
        sentinel_secret = "N3-IMPORT-SECRET-SENTINEL"
        message_reads: list[bool] = []

        class HostileImportError(ImportError):
            def __str__(self) -> str:
                message_reads.append(True)
                return sentinel_secret

        def host_importer(name: str) -> Any:
            if name == "web.web_interface":
                self._load_temporary_snippet(
                    "raise HostileImportError(secret)\n",
                    frame_filename=str(sandbox / "web" / "web_interface.py"),
                    initial_globals={
                        "HostileImportError": HostileImportError,
                        "secret": sentinel_secret,
                    },
                )
            return base_importer(name)

        report = proof.run_startup_diagnostic(
            sandbox_root=sandbox,
            run_id="startup-diagnostic-safe-import-origin",
            output_dir=self.scratch / "startup-diagnostic-safe-import-origin",
            startup_timeout=0.2,
            host_importer=host_importer,
        )

        self.assertEqual(report["failure_exception_class"], "HostileImportError")
        self.assertEqual(report["failure_category"], "host_import_failed")
        origin = report["failure_origin"]
        self.assertEqual(origin["status"], "identified")
        self.assertIn(
            {"source": "web/web_interface.py", "line": 1},
            origin["frames"],
        )
        self.assertLessEqual(len(origin["frames"]), proof.MAX_FAILURE_ORIGIN_FRAMES)
        self.assertEqual(message_reads, [])
        serialized = json.dumps(report, ensure_ascii=True, sort_keys=True)
        self.assertNotIn(sentinel_secret, serialized)
        self.assertNotIn(str(sandbox), serialized)
        self.assertNotIn("config.py", serialized)

    def test_exception_origin_redacts_hostile_paths_and_bounds_fallbacks(self) -> None:
        sandbox = self._fake_sandbox()
        sentinel_secret = "N3-TRACEBACK-SECRET-SENTINEL"

        def origin_for_only_frame(filename: str) -> dict[str, Any]:
            try:
                self._load_temporary_snippet(
                    "raise ImportError(secret)\n",
                    frame_filename=filename,
                    initial_globals={"secret": sentinel_secret},
                )
            except ImportError as exc:
                tb = exc.__traceback__
                while tb is not None and tb.tb_next is not None:
                    tb = tb.tb_next
                exc.__traceback__ = tb
                return proof._exception_failure_origin(exc, sandbox)
            raise AssertionError("synthetic import error did not occur")

        hostile_path = "/untrusted/" + sentinel_secret + "/config.py"
        redacted = origin_for_only_frame(hostile_path)
        self.assertEqual(redacted, {"status": "redacted", "frames": []})
        serialized_redacted = json.dumps(redacted, ensure_ascii=True)
        self.assertNotIn(sentinel_secret, serialized_redacted)
        self.assertNotIn("/untrusted", serialized_redacted)
        self.assertNotIn("config.py", serialized_redacted)

        for identifier in (
            "core/combat/__init__.py",
            "core/combat/combat_manager.py",
        ):
            identified = origin_for_only_frame(identifier)
            self.assertEqual(
                identified,
                {
                    "status": "identified",
                    "frames": [{"source": identifier, "line": 1}],
                },
            )

        unknown_alphanumeric = origin_for_only_frame(
            "UnknownOrigin731.py"
        )
        self.assertEqual(
            unknown_alphanumeric, {"status": "redacted", "frames": []}
        )

        sandbox_filename_sentinel = "N3OpaqueOrigin731"
        sandbox_origin = origin_for_only_frame(
            str(sandbox / (sandbox_filename_sentinel + ".py"))
        )
        self.assertEqual(sandbox_origin, {"status": "redacted", "frames": []})

        installed_roots = proof._known_installed_package_roots()
        package_origin: dict[str, Any] | None = None
        if installed_roots:
            package_origin = origin_for_only_frame(
                str(Path(installed_roots[0]) / (sandbox_filename_sentinel + ".py"))
            )
            self.assertEqual(
                package_origin, {"status": "redacted", "frames": []}
            )

        for origin in (sandbox_origin, package_origin):
            if origin is None:
                continue
            serialized_origin = json.dumps(origin, ensure_ascii=True)
            self.assertNotIn(sandbox_filename_sentinel, serialized_origin)
            safe_report = proof._startup_diagnostic_report(
                call_events=[],
                stub_call_counts={},
                router_calls=0,
                provider_calls=0,
                network_attempts=0,
                ledger_reservations=0,
                ledger_valid=True,
                startup_output_delivered=False,
                game_started=False,
                startup_thread_stopped=True,
                diagnostic_failure=None,
                call_overflow=False,
                router_call_guard=True,
                router_decide_guard=True,
                sdk_tripwire_count=1,
                egress_guard_active=True,
                failure_exception_class="ImportError",
                failure_category="host_import_failed",
                failure_origin=origin,
            )
            self.assertNotIn(
                sandbox_filename_sentinel,
                json.dumps(safe_report, ensure_ascii=True, sort_keys=True),
            )

        unknown = proof._exception_failure_origin(
            ImportError(sentinel_secret), sandbox
        )
        self.assertEqual(unknown, {"status": "unknown", "frames": []})

        next_frame: Any = None
        allowed_sources = (
            "main.py",
            "web/web_interface.py",
            "utils/llm_router.py",
            "utils/ai_client_factory.py",
            "utils/provider_attempt_budget.py",
            "utils/version_checker.py",
            "model_config.py",
        )
        frame_count = proof.MAX_FAILURE_ORIGIN_FRAMES + 4
        for index in range(frame_count):
            identifier = allowed_sources[index % len(allowed_sources)]
            source_path = sandbox.joinpath(*identifier.split("/"))
            namespace: dict[str, Any] = {"secret": sentinel_secret}
            statement = "raise ImportError(secret)"
            if next_frame is not None:
                namespace["next_frame"] = next_frame
                statement = "next_frame()"
            source = "def frame():\n    " + statement + "\n"
            loaded = self._load_temporary_snippet(
                source,
                frame_filename=str(source_path),
                initial_globals=namespace,
            )
            next_frame = loaded["frame"]

        try:
            next_frame()
        except ImportError as exc:
            bounded = proof._exception_failure_origin(exc, sandbox)
        else:
            raise AssertionError("bounded synthetic import error did not occur")
        self.assertEqual(bounded["status"], "identified")
        self.assertEqual(
            len(bounded["frames"]), proof.MAX_FAILURE_ORIGIN_FRAMES
        )
        self.assertTrue(
            all(
                not frame["source"].startswith("/")
                and frame["source"].endswith(".py")
                for frame in bounded["frames"]
            )
        )
        self.assertLessEqual(len(json.dumps(bounded, ensure_ascii=True)), 1400)

        oversized = proof._safe_failure_origin(
            {
                "status": "identified",
                "frames": [
                    {"source": "a" * 178 + ".py", "line": 1},
                    {"source": "safe.py", "line": proof.MAX_COUNTER + 1},
                ],
            }
        )
        self.assertEqual(oversized, {"status": "redacted", "frames": []})

    def test_exception_origin_accepts_fixed_package_identifiers_only(self) -> None:
        installed_roots = proof._known_installed_package_roots()
        if not installed_roots:
            self.skipTest("interpreter has no configured package installation root")

        sandbox = self._fake_sandbox()
        package_filename = str(
            Path(installed_roots[0]) / "flask" / "app.py"
        )
        try:
            self._load_temporary_snippet(
                "raise ImportError('synthetic')\n",
                frame_filename=package_filename,
            )
        except ImportError as exc:
            tb = exc.__traceback__
            while tb is not None and tb.tb_next is not None:
                tb = tb.tb_next
            exc.__traceback__ = tb
            origin = proof._exception_failure_origin(exc, sandbox)
        else:
            raise AssertionError("synthetic package import error did not occur")

        self.assertEqual(origin["status"], "identified")
        self.assertEqual(
            origin["frames"],
            [
                {
                    "source": "site-packages/flask/app.py",
                    "line": 1,
                }
            ],
        )
        self.assertNotIn(
            installed_roots[0], json.dumps(origin, ensure_ascii=True)
        )

    def test_non_import_startup_failure_has_no_exception_origin(self) -> None:
        sandbox = self._fake_sandbox()
        importer = FakeHostImporter(sandbox)
        importer.web_module.startup_diagnostic = True
        importer.web_module.diagnostic_router_tasks = [
            "action_prediction",
            "unexpected_task",
        ]

        report = proof.run_startup_diagnostic(
            sandbox_root=sandbox,
            run_id="startup-diagnostic-non-import-failure",
            output_dir=self.scratch / "startup-diagnostic-non-import-failure",
            startup_timeout=0.3,
            host_importer=importer,
        )

        self.assertEqual(report["failure_exception_class"], "ProviderCallBlocked")
        self.assertEqual(report["failure_category"], "router_call_blocked")
        self.assertIsNone(report["failure_origin"])

    def test_early_startup_failure_preserves_individual_tripwire_status(self) -> None:
        sandbox = self._fake_sandbox()
        importer = FakeHostImporter(sandbox, fail_name="web.web_interface")
        report = proof.run_startup_diagnostic(
            sandbox_root=sandbox,
            run_id="startup-diagnostic-early-failure",
            output_dir=self.scratch / "startup-diagnostic-early-failure",
            startup_timeout=0.2,
            host_importer=importer,
        )

        self.assertEqual(report["verdict"], "BLOCKED")
        self.assertFalse(report["coverage_established"])
        self.assertTrue(report["tripwire_coverage"]["router_call"])
        self.assertTrue(report["tripwire_coverage"]["router_decide"])
        self.assertTrue(report["tripwire_coverage"]["process_launch"])
        self.assertEqual(report["tripwire_coverage"]["sdk_method_count"], 1)
        self.assertFalse(report["tripwire_coverage"]["real_host_imports"])
        self.assertFalse(report["tripwire_coverage"]["startup_boundaries"])
        self.assertEqual(report["failure_exception_class"], "RuntimeError")
        self.assertEqual(report["failure_category"], "host_import_failed")
        serialized = json.dumps(report, ensure_ascii=True, sort_keys=True)
        self.assertNotIn("private-value", serialized)
        self.assertNotIn("/outside/repo/config.py", serialized)

    def test_host_import_egress_reports_class_and_fixed_category_only(self) -> None:
        sandbox = self._fake_sandbox()
        importer = FakeHostImporter(sandbox)
        importer.egress_during_web_import = True
        report = proof.run_startup_diagnostic(
            sandbox_root=sandbox,
            run_id="startup-diagnostic-import-egress",
            output_dir=self.scratch / "startup-diagnostic-import-egress",
            startup_timeout=0.2,
            host_importer=importer,
        )

        self.assertEqual(report["verdict"], "BLOCKED")
        self.assertEqual(report["network_attempt_count"], 1)
        self.assertEqual(report["failure_exception_class"], "gaierror")
        self.assertEqual(
            report["failure_category"], "host_import_egress_blocked"
        )
        self.assertEqual(
            report["egress_refusals"][0]["hostname"],
            "diagnostic-private.invalid",
        )
        self.assertTrue(report["egress_refusal_coverage_complete"])
        serialized = json.dumps(report, ensure_ascii=True, sort_keys=True)
        self.assertNotIn("private-value", serialized)

    def test_startup_report_includes_only_sanitized_network_attribution(self) -> None:
        sandbox = self._fake_sandbox()
        importer = FakeHostImporter(sandbox)
        importer.web_module.egress_host = "startup-private.example.invalid"
        with patch.object(
            proof,
            "_collect_egress_origin",
            return_value=(
                ["web/web_interface.py:handle_start_game"],
                [],
            ),
        ):
            report = proof.run_startup_diagnostic(
                sandbox_root=sandbox,
                run_id="startup-diagnostic-egress-attribution",
                output_dir=self.scratch / "startup-diagnostic-egress-attribution",
                startup_timeout=0.3,
                host_importer=importer,
            )

        self.assertEqual(report["network_attempt_count"], 1)
        attributions = report["network_attempt_attributions"]
        self.assertEqual(len(attributions), 1)
        self.assertEqual(attributions[0]["hostname_class"], "other")
        self.assertEqual(attributions[0]["thread_classes"], ["background"])
        project_frames = attributions[0]["origin"]["project_frames"]
        self.assertTrue(project_frames)
        self.assertTrue(
            all(not frame.startswith("/") for frame in project_frames)
        )
        refusals = report["egress_refusals"]
        self.assertEqual(len(refusals), 1)
        self.assertEqual(refusals[0]["hostname"], "startup-private.example.invalid")
        self.assertEqual(refusals[0]["port"], 443)
        self.assertTrue(refusals[0]["thread_id"])
        self.assertTrue(
            refusals[0]["call_site"].startswith(
                "scripts/test_n3_start_game_offline_proof.py:"
            )
        )
        serialized = json.dumps(report, ensure_ascii=True, sort_keys=True)
        self.assertNotIn(str(proof.REPO_ROOT), serialized)
        self.assertNotIn("private-prompt-value", serialized)

    def test_startup_diagnostic_blocks_direct_sdk_unknown_router_and_egress(self) -> None:
        cases = (
            ("sdk", {"diagnostic_provider_call": True}, 0, 1),
            ("process", {"process_launch": True}, 0, 0),
            (
                "unknown",
                {"diagnostic_router_tasks": ["action_prediction", "unknown_task"]},
                0,
                0,
            ),
            ("egress", {"egress_host": "127.0.0.1"}, 1, 0),
        )
        for case_name, updates, network_count, provider_count in cases:
            with self.subTest(case=case_name):
                sandbox = self._fake_sandbox()
                importer = FakeHostImporter(sandbox)
                importer.web_module.startup_diagnostic = True
                for name, value in updates.items():
                    setattr(importer.web_module, name, value)
                report = proof.run_startup_diagnostic(
                    sandbox_root=sandbox,
                    run_id="startup-diagnostic-" + case_name,
                    output_dir=self.scratch / ("startup-diagnostic-" + case_name),
                    startup_timeout=0.5,
                    host_importer=importer,
                )
                self.assertEqual(report["verdict"], "BLOCKED")
                self.assertFalse(report["startup_output_delivered"])
                self.assertEqual(report["network_attempt_count"], network_count)
                self.assertEqual(report["provider_call_count"], provider_count)
                serialized = json.dumps(report, ensure_ascii=True, sort_keys=True)
                for private_value in (
                    "private-prompt-value",
                    "private-sdk-prompt",
                    "private-model",
                ):
                    self.assertNotIn(private_value, serialized)

    def test_startup_diagnostic_process_refusal_never_spawns_or_exposes_args(
        self,
    ) -> None:
        sandbox = self._fake_sandbox()
        importer = FakeHostImporter(sandbox)
        importer.web_module.startup_diagnostic = True
        importer.web_module.process_launch = True
        importer.web_module.process_launch_args = (
            [
                "N3_COMMAND_SECRET_SENTINEL",
                "N3_ARGUMENT_SECRET_SENTINEL",
            ],
        )
        importer.web_module.process_launch_kwargs = {
            "cwd": "/N3_PATH_SECRET_SENTINEL",
            "env": {"PRIVATE_KEY": "N3_ENV_SECRET_SENTINEL"},
        }

        with patch.object(proof.subprocess, "run") as underlying_spawn:
            report = proof.run_startup_diagnostic(
                sandbox_root=sandbox,
                run_id="startup-diagnostic-process-refusal",
                output_dir=self.scratch / "startup-diagnostic-process-refusal",
                startup_timeout=0.5,
                host_importer=importer,
            )
            underlying_spawn.assert_not_called()

        self.assertEqual(report["verdict"], "BLOCKED")
        self.assertEqual(report["failure_category"], "process_launch_blocked")
        self.assertEqual(
            report["failure_exception_class"], "ProviderCallBlocked"
        )
        self.assertEqual(report["router_call_count"], 2)
        self.assertEqual(report["provider_call_count"], 0)
        self.assertEqual(report["network_attempt_count"], 0)
        self.assertEqual(report["process_launch_refusal"], {
            "status": "redacted",
            "frames": [],
        })
        self.assertTrue(report["tripwire_coverage"]["process_launch"])

        serialized = json.dumps(report, ensure_ascii=True, sort_keys=True)
        self.assertNotIn(str(sandbox), serialized)
        for private_value in (
            "N3_COMMAND_SECRET_SENTINEL",
            "N3_ARGUMENT_SECRET_SENTINEL",
            "N3_PATH_SECRET_SENTINEL",
            "N3_ENV_SECRET_SENTINEL",
            "PRIVATE_KEY",
            "native child-process launch blocked",
        ):
            self.assertNotIn(private_value, serialized)

    def test_process_launch_tripwire_attributes_only_fixed_allowlisted_source(
        self,
    ) -> None:
        sandbox = self._fake_sandbox()
        recorder = proof.ProviderCallRecorder(diagnostic_mode=True)
        patches = proof.AttributePatches()
        command = ["N3_COMMAND_SECRET_SENTINEL", "N3_ARGUMENT_SECRET_SENTINEL"]
        spawn_spy = unittest_mock.Mock()
        with patch.object(proof.subprocess, "run", spawn_spy):
            proof._install_process_launch_tripwires(patches, recorder, sandbox)
            try:
                with self.assertRaises(proof.ProviderCallBlocked):
                    self._load_temporary_snippet(
                        "subprocess.run(command, cwd=working_directory, env=environment)\n",
                        frame_filename=str(
                            sandbox / "web" / "web_interface.py"
                        ),
                        initial_globals={
                            "subprocess": proof.subprocess,
                            "command": command,
                            "working_directory": "/N3_PATH_SECRET_SENTINEL",
                            "environment": {
                                "PRIVATE_KEY": "N3_ENV_SECRET_SENTINEL"
                            },
                        },
                    )
                refusal = recorder.process_launch_refusal_snapshot()
                self.assertEqual(
                    refusal,
                    {
                        "status": "identified",
                        "frames": [
                            {"source": "web/web_interface.py", "line": 1}
                        ],
                    },
                )
                report = proof._startup_diagnostic_report(
                    call_events=[],
                    stub_call_counts={},
                    router_calls=0,
                    provider_calls=0,
                    network_attempts=0,
                    ledger_reservations=0,
                    ledger_valid=True,
                    startup_output_delivered=False,
                    game_started=False,
                    startup_thread_stopped=True,
                    diagnostic_failure=(
                        "native child-process launch was attempted"
                    ),
                    call_overflow=False,
                    router_call_guard=True,
                    router_decide_guard=True,
                    sdk_tripwire_count=1,
                    egress_guard_active=True,
                    process_launch_guard=True,
                    host_imports_verified=True,
                    startup_boundary_guard_active=True,
                    egress_refusals=[],
                    egress_refusal_count=0,
                    process_launch_refusal=refusal,
                )
                self.assertEqual(report["verdict"], "BLOCKED")
                self.assertEqual(
                    report["process_launch_refusal"],
                    {
                        "status": "identified",
                        "frames": [
                            {"source": "web/web_interface.py", "line": 1}
                        ],
                    },
                )
            finally:
                patches.restore()
            spawn_spy.assert_not_called()

        serialized = json.dumps(report, ensure_ascii=True, sort_keys=True)
        self.assertNotIn(str(sandbox), serialized)
        for private_value in (
            "N3_COMMAND_SECRET_SENTINEL",
            "N3_ARGUMENT_SECRET_SENTINEL",
            "N3_PATH_SECRET_SENTINEL",
            "N3_ENV_SECRET_SENTINEL",
            "PRIVATE_KEY",
        ):
            self.assertNotIn(private_value, serialized)

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
            with guard:
                for host in (
                    "api.openrouter.ai",
                    "api.openrouter.ai",
                    "github.com",
                ):
                    with self.assertRaises(ConnectionRefusedError):
                        socket.create_connection((host, 443))

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
        self.assertTrue(report["egress_refusal_coverage_complete"])
        self.assertEqual(
            report["egress_refusals"][0]["hostname"], "api.openrouter.ai"
        )
        serialized = json.dumps(report, ensure_ascii=True, sort_keys=True)
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
                "egress_refusals",
                "egress_refusal_coverage_complete",
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
            "egress_refusals": [
                {
                    "hostname": "api.exchange.example",
                    "port": 443,
                    "thread_id": 123,
                    "thread_class": "background",
                    "call_site": "utils/llm_usage_tracker.py:42",
                    "sequence": 1,
                }
            ],
            "egress_refusal_count": 1,
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
        self.assertTrue(accepted["egress_refusal_coverage_complete"])
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

        unavailable = dict(base)
        unavailable["egress_refusals"] = [
            dict(base["egress_refusals"][0], hostname="unavailable")
        ]
        unavailable_report = proof.build_report(**unavailable)
        self.assertEqual(unavailable_report["verdict"], "FAIL")
        self.assertFalse(unavailable_report["egress_refusal_coverage_complete"])

        mixed = dict(base)
        mixed["egress_attempts"] = [
            {"host_class": "non_loopback", "port": 443},
            {"host_class": "non_loopback", "port": 443},
        ]
        mixed["egress_refusals"] = [
            dict(base["egress_refusals"][0]),
            {
                "hostname": "github.com",
                "port": 443,
                "thread_id": 123,
                "thread_class": "background",
                "call_site": "utils/llm_router.py:88",
                "sequence": 2,
            },
        ]
        mixed["egress_refusal_count"] = 2
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
        self.assertIn(
            "egress refusal attribution incomplete",
            unattributed_report["reason"],
        )
        self.assertIn("unexpected egress origin", unattributed_report["reason"])

        orphaned_attribution = dict(base)
        orphaned_attribution["egress_attempts"] = []
        orphaned_report = proof.build_report(**orphaned_attribution)
        self.assertEqual(orphaned_report["verdict"], "FAIL")
        self.assertIn(
            "egress refusal attribution incomplete",
            orphaned_report["reason"],
        )
        self.assertIn("unexpected egress origin", orphaned_report["reason"])

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
            egress_refusals=[
                {
                    "hostname": "api.openrouter.ai",
                    "port": 443,
                    "thread_id": 123,
                    "thread_class": "background",
                    "call_site": "utils/llm_usage_tracker.py:42",
                    "sequence": 1,
                }
            ],
            egress_refusal_count=1,
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
