# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free no-network tripwire suite for the runtime author adapter
(task 3.4 of toolkit-llm-adaptation-runtime-unification).

The suite arms a strict tripwire around every provider/network/socket surface
the adaptation runtime could reach (``create_chat_client``, the OpenAI SDK,
``requests``, ``urllib``, ``http.client``, ``socket``, and ``socketio``) and
proves the shared runtime author adapter -- both the upload and the
text-description entry points -- succeeds and fails ONLY through injected
fake clients, runners, and parameter resolvers:

  * success, refusal, and provider-failure paths run with the tripwire armed
    and assert that no live client or network surface was touched;
  * a missing injection seam is intercepted by the tripwire: the adapter
    fails closed with bounded provider-infrastructure diagnostics instead of
    ever contacting a provider;
  * direct guarded invocations raise AssertionError, proving the tripwire
    actually guards the SDK, HTTP, socket, and socketio surfaces.

The suite also source-scans the provider-free route test files (route
contract, route eligibility, upload handoff, text workspace, authoring
adapter, and author provider contract) with the AST so every provider-free
route test provably uses injected seams: no provider/network imports, no
live client/network/OS-temp call shapes, and no host lifecycle calls.

No network or provider call is ever made. All fixtures and scratch live
under the project-local root ``tmp/toolkit_adaptation_author_tripwire/<uuid>/``
removed via addCleanup. No OS temp directory is used.
"""

import ast
import hashlib
import http.client
import json
import openai
import requests
import shutil
import socket
import socketio
import sys
import unittest
import urllib.request
import uuid
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import utils.ai_client_factory as ai_client_factory
import utils.toolkit_adaptation_author as author_module
import web.extensions.toolkit_adaptation_runtime as runtime
from utils.toolkit_adaptation_dossier import RIGHTS_CLASS_USER_AUTHORED
from utils.toolkit_homebrew_upload_contract import (
    REVIEW_DECISION_APPROVE,
    SOURCE_RIGHTS_USER_AUTHORED,
    build_review_snapshot,
    ensure_workspace_placeholders,
    get_workspace_files,
    persist_normalized_packet_artifact,
    persist_review_snapshot_artifact,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRATCH_ROOT = REPO_ROOT / "tmp" / "toolkit_adaptation_author_tripwire"
FIXTURE_PATH = REPO_ROOT / "scripts" / "fixtures" / "toolkit_adaptation_dossier_valid.json"
RUNTIME_MODULE_PATH = (
    REPO_ROOT / "web" / "extensions" / "toolkit_adaptation_runtime.py"
)

FIXTURE_TEXT = (
    "# Sunken Lighthouse\n\n"
    "Room 1: The keeper's quarters with a rusted spyglass.\n"
    "Room 2: The flooded stairs descending into the dark.\n"
    "Room 3: The drowned bell chamber.\n"
)
FIXTURE_HASH = hashlib.sha256(FIXTURE_TEXT.encode("utf-8")).hexdigest()

PACKET_LOCATIONS = [
    {"name": "Keeper's Quarters", "location": "tower", "description": "Rusted spyglass."},
    {"name": "Flooded Stairs", "location": "stairs", "description": "Dark water."},
]

# The provider-free route test files scanned by this suite. Every one of them
# must prove that it only ever reaches provider behavior through injected
# clients/runners/resolvers and never touches a live client, the network, OS
# temp scratch, or the host lifecycle.
ROUTE_TEST_FILES = (
    "scripts/test_toolkit_adaptation_runtime_route_contract.py",
    "scripts/test_toolkit_adaptation_route_eligibility.py",
    "scripts/test_toolkit_upload_adaptation_handoff.py",
    "scripts/test_toolkit_text_description_attempt_workspace.py",
    "scripts/test_toolkit_adaptation_authoring_adapter.py",
    "scripts/test_toolkit_adaptation_author_provider_contract.py",
)

# Provider/network/host-import roots that no provider-free route test may use.
_FORBIDDEN_IMPORT_ROOTS = frozenset(
    {
        "openai",
        "httpx",
        "requests",
        "socketio",
        "urllib",
        "http",
        "socket",
        "aiohttp",
        "websockets",
        "tempfile",
    }
)

# Exact call names that would invoke a live provider, network surface, OS
# temp API, or host lifecycle entry point.
_FORBIDDEN_CALL_NAMES = frozenset(
    {
        "create_chat_client",
        "OpenAI",
        "urlopen",
        "urlretrieve",
        "mkdtemp",
        "mkstemp",
        "mktemp",
        "NamedTemporaryFile",
        "TemporaryDirectory",
        "gettempdir",
        "start_build",
        "simulate_build_process",
    }
)

# Attribute-call suffixes that would invoke a live provider, network surface,
# or host socket surface. Matched against the dotted attribute path.
_FORBIDDEN_CALL_SUFFIXES = (
    ".requests.get",
    ".requests.post",
    ".requests.request",
    ".urllib.request.urlopen",
    ".urllib.request.urlretrieve",
    ".http.client.HTTPConnection",
    ".http.client.HTTPSConnection",
    ".socket.socket",
    ".socket.create_connection",
    ".socketio.emit",
    ".socketio.send",
    ".completions.create",
    ".chat.completions.create",
)


def _load_fixture() -> Dict[str, Any]:
    with FIXTURE_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _dossier_for_attempt(attempt_metadata: Dict[str, Any]) -> Dict[str, Any]:
    """Build a schema-valid dossier whose Python-owned identity matches the
    attempt metadata produced by the authoring preflight."""
    dossier = deepcopy(_load_fixture())
    dossier["source_hash"] = attempt_metadata["source_hash"]
    dossier["source_title"] = attempt_metadata["source_title"]
    dossier["source_profile"] = attempt_metadata["source_profile"]
    dossier["rights_class"] = attempt_metadata["rights_class"]
    dossier["rights_basis"] = attempt_metadata["rights_basis"]
    dossier["rights_review_required"] = attempt_metadata["rights_review_required"]
    dossier["rights_review_status"] = attempt_metadata["rights_review_status"]
    dossier["adaptation_mode"] = "llm_adaptation"
    return dossier


def _fake_resolver(task_id: str, model: str) -> Dict[str, Any]:
    """Deterministic injected chat-parameter resolver (no provider access)."""
    return {
        "model": model,
        "reasoning_effort": "medium",
        "verbosity": "medium",
    }


class FakeAuthorRunner:
    """Deterministic injectable author runner (never touches a provider)."""

    def __init__(
        self,
        *,
        dossier_builder: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
        error: Optional[Exception] = None,
        refused: bool = False,
        failure_class: Optional[str] = None,
        invalid_dossier: bool = False,
    ) -> None:
        self.calls: List[tuple] = []
        self.dossier_builder = dossier_builder
        self.error = error
        self.refused = refused
        self.failure_class = failure_class
        self.invalid_dossier = invalid_dossier

    def __call__(
        self, source_context: Any, attempt_metadata: Optional[Dict[str, Any]] = None, **kwargs: Any
    ) -> Dict[str, Any]:
        self.calls.append(
            (
                deepcopy(dict(source_context)) if isinstance(source_context, dict) else source_context,
                deepcopy(dict(attempt_metadata or {})),
                dict(kwargs),
            )
        )
        if self.error is not None:
            raise self.error
        if self.refused:
            return {
                "status": "refused",
                "outcome": "explicit_refusal",
                "ok": False,
                "failure_class": self.failure_class or "refusal",
                "diagnostics": [
                    {"code": "dossier_refused", "message": "adaptation author refused the source"}
                ],
                "dossier": None,
            }
        if self.invalid_dossier:
            return {
                "status": "success",
                "outcome": "valid",
                "ok": True,
                "failure_class": "none",
                "dossier": {"status": "ready", "adapted_title": "not a real dossier"},
                "diagnostics": [],
            }
        dossier = self.dossier_builder(dict(attempt_metadata or {})) if self.dossier_builder else None
        return {
            "status": "success",
            "outcome": "valid",
            "ok": True,
            "failure_class": "none",
            "dossier": dossier,
            "diagnostics": [],
            "response_metadata": {"model": "mock-adaptation-model", "request_id": "req-tripwire-1"},
            "params_used": {"reasoning_effort": "medium"},
        }


class EchoClient:
    """Fake provider client that returns a valid dossier echoing the
    Python-owned attempt metadata carried inside the request. Never performs a
    network or provider call."""

    def __init__(
        self,
        *,
        refuse: bool = False,
        malformed: bool = False,
        error: Optional[Exception] = None,
    ) -> None:
        self.calls: List[Dict[str, Any]] = []
        self.refuse = refuse
        self.malformed = malformed
        self.error = error
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        if self.refuse:
            message = SimpleNamespace(content=None, refusal="policy")
            choice = SimpleNamespace(message=message, finish_reason="refusal")
            return SimpleNamespace(choices=[choice], model="mock-model", id="req-tripwire-1")
        metadata: Dict[str, Any] = {}
        for item in kwargs.get("messages") or []:
            content = item.get("content", "") if isinstance(item, Mapping) else ""
            if isinstance(content, str) and content.startswith("ADAPTATION_AUTHOR_INPUT:"):
                try:
                    payload = json.loads(content.split("\n", 1)[1])
                    candidate = payload.get("attempt_metadata")
                    if isinstance(candidate, Mapping):
                        metadata = dict(candidate)
                except (ValueError, IndexError):
                    metadata = {}
                break
        if self.malformed:
            content = "not-json-at-all"
        else:
            dossier = _load_fixture()
            dossier["source_hash"] = metadata.get("source_hash") or FIXTURE_HASH
            dossier["source_title"] = metadata.get("source_title") or "Sunken Lighthouse"
            dossier["source_profile"] = metadata.get("source_profile") or "catalogue"
            for field in (
                "rights_class",
                "rights_basis",
                "rights_review_required",
                "rights_review_status",
            ):
                if metadata.get(field) is not None:
                    dossier[field] = metadata[field]
            dossier["adaptation_mode"] = "llm_adaptation"
            content = json.dumps(dossier)
        message = SimpleNamespace(content=content, refusal=None)
        choice = SimpleNamespace(message=message, finish_reason="stop")
        return SimpleNamespace(choices=[choice], model="mock-adaptation-model", id="req-tripwire-1")


class _ProviderTripwire:
    """Context manager that arms every provider/network/socket tripwire.

    Any unexpected ``create_chat_client``, provider SDK construction, HTTP,
    socket, or socketio invocation inside the guarded block raises
    AssertionError. Tests using injected seams assert the tripwire mocks were
    never called; the missing-seam test asserts the author client funnel WAS
    intercepted and the adapter failed closed without network access.
    """

    def __init__(self) -> None:
        self.mocks: Dict[str, Any] = {}
        self._patchers: Dict[str, Any] = {}

    def _arm(self, key: str, target: str) -> None:
        try:
            patcher = mock.patch(
                target,
                side_effect=AssertionError("provider tripwire: unexpected " + key),
            )
            self._patchers[key] = patcher
            self.mocks[key] = patcher.start()
        except Exception:
            self._patchers[key] = None
            self.mocks[key] = None

    def __enter__(self) -> "_ProviderTripwire":
        # The live client funnel used by the adaptation author runner, plus
        # the shared factory behind it.
        self._arm("factory_create_chat_client", "utils.ai_client_factory.create_chat_client")
        self._arm("author_create_chat_client", "utils.toolkit_adaptation_author.create_chat_client")
        # Provider SDK construction (defense in depth behind the factory).
        self._arm("openai_sdk_construction", "openai.OpenAI")
        # Network/HTTP surfaces.
        self._arm("requests_get", "requests.get")
        self._arm("requests_post", "requests.post")
        self._arm("urllib_urlopen", "urllib.request.urlopen")
        self._arm("http_connection", "http.client.HTTPConnection")
        # Socket creation of any kind.
        self._arm("socket_socket", "socket.socket")
        # Host lifecycle socketio emit/send surfaces.
        self._arm("socketio_emit", "socketio.Server.emit")
        self._arm("socketio_send", "socketio.Server.send")
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        for patcher in self._patchers.values():
            if patcher is not None:
                try:
                    patcher.stop()
                except Exception:
                    pass
        return False

    def assert_no_provider_or_network_calls(self, case: unittest.TestCase) -> None:
        """Every armed surface must stay untouched (no live client/network)."""
        for key, guard in self.mocks.items():
            if guard is not None:
                with case.subTest(tripwire=key):
                    guard.assert_not_called()


def _packet(*, source_hash: str = FIXTURE_HASH, title: str = "Sunken Lighthouse") -> Dict[str, Any]:
    return {
        "packet_version": "v1",
        "normalization_state": "normalized",
        "source_path": "uploads/fixture.md",
        "source_hash": source_hash,
        "title": title,
        "author": "",
        "description": "A bounded adventure about a sunken lighthouse.",
        "adventure_summary": "The keeper's quarters and the flooded stairs.",
        "module_tone": "haunted",
        "acts": [{"name": "Descent", "summary": "Into the dark."}],
        "locations": PACKET_LOCATIONS,
        "npc_seeds": [],
        "encounter_seeds": [],
        "assumptions": ["Fixture packet for the author tripwire tests."],
        "source_rights_class": SOURCE_RIGHTS_USER_AUTHORED,
    }


def _make_workspace(scratch: Path, *, text: str = FIXTURE_TEXT) -> Path:
    workspace = scratch / "workspace"
    ensure_workspace_placeholders(workspace)
    files = get_workspace_files(workspace)
    files["source_original"].write_text(text, encoding="utf-8")
    packet = _packet()
    persist_normalized_packet_artifact(workspace, packet)
    snapshot = build_review_snapshot(
        job_id="job-1",
        decision=REVIEW_DECISION_APPROVE,
        packet=packet,
        source_rights_class=SOURCE_RIGHTS_USER_AUTHORED,
    )
    persist_review_snapshot_artifact(workspace, snapshot)
    return workspace


def _dotted_call_name(node: Any) -> str:
    parts: List[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _import_roots(source: str) -> set:
    tree = ast.parse(source)
    roots: set = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                roots.add(node.module.split(".")[0])
    return roots


def _forbidden_call_names(
    source: str,
    excluded_range: Optional[Tuple[int, int]] = None,
) -> List[str]:
    tree = ast.parse(source)
    found: List[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if excluded_range is not None and excluded_range[0] <= node.lineno <= excluded_range[1]:
            continue
        name = _dotted_call_name(node.func)
        if name in _FORBIDDEN_CALL_NAMES:
            found.append(name)
        for suffix in _FORBIDDEN_CALL_SUFFIXES:
            if name.endswith(suffix):
                found.append(name)
                break
    return sorted(set(found))


class _ProjectLocalScratchMixin:
    """Provide a unique project-local scratch dir removed after each test."""

    def setUp(self) -> None:
        self.scratch = SCRATCH_ROOT / str(uuid.uuid4())
        self.scratch.mkdir(parents=True, exist_ok=True)
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)

    def _assert_no_module_side_effects(self) -> None:
        """No completed module, registry, or campaign artifact anywhere."""
        modules_dir = self.scratch / "modules"
        self.assertFalse(modules_dir.exists())
        for sentinel in ("world_registry.json", "campaign.json"):
            self.assertFalse(
                (self.scratch / sentinel).exists(),
                f"{sentinel} must not be created by authoring",
            )
        self.assertFalse((REPO_ROOT / "modules" / "Sunken_Lighthouse").exists())

    def _assert_bounded_diagnostics(self, result: Dict[str, Any]) -> None:
        for item in result["authoring"]["diagnostics"]:
            self.assertLessEqual(len(item.get("message", "")), 320)
        self.assertLessEqual(len(result["authoring"]["diagnostics"]), 12)


class TestTripwireGuardsProviderSurfaces(unittest.TestCase):
    """The armed tripwire makes every unexpected provider/network/socket
    surface raise instead of reaching a live service."""

    def test_factory_create_chat_client_tripwire_raises(self) -> None:
        with _ProviderTripwire():
            with self.assertRaises(AssertionError):
                ai_client_factory.create_chat_client()

    def test_author_create_chat_client_tripwire_raises(self) -> None:
        with _ProviderTripwire():
            with self.assertRaises(AssertionError):
                author_module.create_chat_client()

    def test_openai_sdk_construction_tripwire_raises(self) -> None:
        with _ProviderTripwire():
            with self.assertRaises(AssertionError):
                openai.OpenAI()

    def test_requests_get_tripwire_raises(self) -> None:
        with _ProviderTripwire():
            with self.assertRaises(AssertionError):
                requests.get("https://example.invalid/")

    def test_urllib_urlopen_tripwire_raises(self) -> None:
        with _ProviderTripwire():
            with self.assertRaises(AssertionError):
                urllib.request.urlopen("https://example.invalid/")

    def test_http_connection_tripwire_raises(self) -> None:
        with _ProviderTripwire():
            with self.assertRaises(AssertionError):
                http.client.HTTPConnection("example.invalid")

    def test_socket_creation_tripwire_raises(self) -> None:
        with _ProviderTripwire():
            with self.assertRaises(AssertionError):
                socket.socket()

    def test_socketio_emit_tripwire_raises(self) -> None:
        with _ProviderTripwire():
            server = socketio.Server()
            with self.assertRaises(AssertionError):
                server.emit("module_complete", {"ok": True})


class TestUploadAdapterThroughInjectedSeams(_ProjectLocalScratchMixin, unittest.TestCase):
    """The upload adapter entry point only succeeds/fails through injected
    clients, runners, and resolvers; the tripwire never fires."""

    def _ready_handoff(self, **overrides: Any) -> Dict[str, Any]:
        workspace = _make_workspace(self.scratch)
        options: Dict[str, Any] = {
            "source_kind": "markdown",
            "source_rights_class": SOURCE_RIGHTS_USER_AUTHORED,
            "review_state": "approved_for_build",
            "job_id": "job-1",
        }
        options.update(overrides)
        handoff = runtime.build_upload_adaptation_handoff(workspace, **options)
        self.assertEqual(handoff["status"], runtime.HANDOFF_STATUS_READY)
        return handoff

    def test_upload_success_only_through_injected_fake_client(self) -> None:
        with _ProviderTripwire() as tripwire:
            handoff = self._ready_handoff()
            client = EchoClient()
            result = runtime.run_upload_adaptation_authoring(
                handoff,
                client=client,
                parameter_resolver=_fake_resolver,
                model="gpt-5.6-luna",
            )
        self.assertEqual(result["status"], runtime.AUTHORING_ADAPTER_STATUS_READY)
        self.assertTrue(result["ok"])
        self.assertIsNotNone(result["dossier"])
        self.assertEqual(len(client.calls), 1)
        request = client.calls[0]
        self.assertEqual(request["response_format"]["type"], "json_schema")
        tripwire.assert_no_provider_or_network_calls(self)
        self._assert_no_module_side_effects()

    def test_upload_success_only_through_injected_author_runner(self) -> None:
        with _ProviderTripwire() as tripwire:
            handoff = self._ready_handoff()
            runner = FakeAuthorRunner(dossier_builder=_dossier_for_attempt)
            result = runtime.run_upload_adaptation_authoring(
                handoff,
                author_runner=runner,
                model="mock-adaptation-model",
            )
        self.assertEqual(result["status"], runtime.AUTHORING_ADAPTER_STATUS_READY)
        self.assertTrue(result["ok"])
        self.assertIsNotNone(result["dossier"])
        self.assertEqual(len(runner.calls), 1)
        # The injected runner bypasses the provider client funnel entirely.
        tripwire.assert_no_provider_or_network_calls(self)
        self._assert_no_module_side_effects()

    def test_upload_refusal_only_through_injected_runner_blocks_bounded(self) -> None:
        with _ProviderTripwire() as tripwire:
            handoff = self._ready_handoff()
            runner = FakeAuthorRunner(dossier_builder=_dossier_for_attempt, refused=True)
            result = runtime.run_upload_adaptation_authoring(
                handoff,
                author_runner=runner,
                model="mock-adaptation-model",
            )
        self.assertEqual(result["status"], runtime.AUTHORING_ADAPTER_STATUS_BLOCKED)
        self.assertFalse(result["ok"])
        self.assertIsNone(result["dossier"])
        self.assertEqual(result["authoring"]["safe_class"], "author_policy_refusal")
        self.assertEqual(result["authoring"]["reason_code"], "dossier_refused")
        self.assertEqual(len(runner.calls), 1)
        self.assertFalse(result["guards"]["module_builder_allowed"])
        self.assertFalse(result["guards"]["module_builder_started"])
        self._assert_bounded_diagnostics(result)
        tripwire.assert_no_provider_or_network_calls(self)
        self._assert_no_module_side_effects()

    def test_upload_api_refusal_only_through_injected_client_blocks(self) -> None:
        with _ProviderTripwire() as tripwire:
            handoff = self._ready_handoff()
            client = EchoClient(refuse=True)
            result = runtime.run_upload_adaptation_authoring(
                handoff,
                client=client,
                parameter_resolver=_fake_resolver,
                model="gpt-5.6-luna",
            )
        self.assertEqual(result["status"], runtime.AUTHORING_ADAPTER_STATUS_BLOCKED)
        self.assertFalse(result["ok"])
        self.assertIsNone(result["dossier"])
        self.assertEqual(result["authoring"]["safe_class"], "api_refusal")
        self.assertEqual(result["authoring"]["reason_code"], "provider_api_refusal")
        self.assertEqual(len(client.calls), 1)
        self._assert_bounded_diagnostics(result)
        tripwire.assert_no_provider_or_network_calls(self)
        self._assert_no_module_side_effects()

    def test_upload_provider_failure_only_through_injected_client_blocks(self) -> None:
        with _ProviderTripwire() as tripwire:
            handoff = self._ready_handoff()
            client = EchoClient(error=TimeoutError("timed out"))
            result = runtime.run_upload_adaptation_authoring(
                handoff,
                client=client,
                parameter_resolver=_fake_resolver,
                model="gpt-5.6-luna",
            )
        self.assertEqual(result["status"], runtime.AUTHORING_ADAPTER_STATUS_BLOCKED)
        self.assertFalse(result["ok"])
        self.assertIsNone(result["dossier"])
        self.assertEqual(result["authoring"]["safe_class"], "timeout")
        self.assertEqual(len(client.calls), 1)
        self._assert_bounded_diagnostics(result)
        tripwire.assert_no_provider_or_network_calls(self)
        self._assert_no_module_side_effects()

    def test_upload_invalid_dossier_only_through_injected_runner_blocks(self) -> None:
        with _ProviderTripwire() as tripwire:
            handoff = self._ready_handoff()
            runner = FakeAuthorRunner(invalid_dossier=True)
            result = runtime.run_upload_adaptation_authoring(
                handoff,
                author_runner=runner,
                model="mock-adaptation-model",
            )
        self.assertEqual(result["status"], runtime.AUTHORING_ADAPTER_STATUS_BLOCKED)
        self.assertIsNone(result["dossier"])
        self.assertTrue(result["authoring"]["failure_artifact_persisted"])
        self._assert_bounded_diagnostics(result)
        tripwire.assert_no_provider_or_network_calls(self)
        self._assert_no_module_side_effects()

    def test_upload_missing_injection_seam_trips_and_fails_closed(self) -> None:
        # With no injected client/runner/resolver the author runner would
        # create a live client; the tripwire intercepts it, the adapter fails
        # closed with bounded provider-infrastructure diagnostics, and no
        # network surface is ever touched.
        with _ProviderTripwire() as tripwire:
            handoff = self._ready_handoff()
            result = runtime.run_upload_adaptation_authoring(
                handoff,
                model="gpt-5.6-luna",
            )
        self.assertEqual(result["status"], runtime.AUTHORING_ADAPTER_STATUS_BLOCKED)
        self.assertFalse(result["ok"])
        self.assertIsNone(result["dossier"])
        author_tripwire = tripwire.mocks.get("author_create_chat_client")
        self.assertIsNotNone(author_tripwire)
        self.assertEqual(author_tripwire.call_count, 1)
        self.assertEqual(result["authoring"]["safe_class"], "provider_infrastructure")
        self.assertEqual(result["authoring"]["reason_code"], "provider_client_init_failed")
        self.assertFalse(result["guards"]["module_builder_allowed"])
        self._assert_bounded_diagnostics(result)
        for key, guard in tripwire.mocks.items():
            if key == "author_create_chat_client":
                continue
            if guard is not None:
                guard.assert_not_called()
        self._assert_no_module_side_effects()


class TestTextDescriptionAdapterThroughInjectedSeams(_ProjectLocalScratchMixin, unittest.TestCase):
    """The text-description adapter entry point only succeeds/fails through
    injected clients, runners, and resolvers; the tripwire never fires."""

    def _ready_manifest(self, **overrides: Any) -> Dict[str, Any]:
        options: Dict[str, Any] = {
            "module_name": "Sunken_Lighthouse",
            "concept": FIXTURE_TEXT,
            "job_id": "text-job-1",
            "workspace_root": "tmp/toolkit_adaptation_author_tripwire"
            + "/"
            + self.scratch.name
            + "/text_workspaces",
        }
        options.update(overrides)
        manifest = runtime.build_text_description_attempt_workspace(**options)
        self.assertEqual(manifest["status"], runtime.TEXT_DESCRIPTION_WORKSPACE_STATUS_READY)
        return manifest

    def test_text_success_only_through_injected_fake_client(self) -> None:
        with _ProviderTripwire() as tripwire:
            manifest = self._ready_manifest()
            client = EchoClient()
            result = runtime.run_text_description_adaptation_authoring(
                manifest,
                client=client,
                parameter_resolver=_fake_resolver,
                model="gpt-5.6-luna",
            )
        self.assertEqual(result["status"], runtime.AUTHORING_ADAPTER_STATUS_READY)
        self.assertTrue(result["ok"])
        self.assertIsNotNone(result["dossier"])
        self.assertEqual(result["rights"]["rights_class"], RIGHTS_CLASS_USER_AUTHORED)
        self.assertEqual(len(client.calls), 1)
        tripwire.assert_no_provider_or_network_calls(self)
        self.assertFalse((REPO_ROOT / "modules" / "Sunken_Lighthouse").exists())

    def test_text_success_only_through_injected_author_runner(self) -> None:
        with _ProviderTripwire() as tripwire:
            manifest = self._ready_manifest()
            runner = FakeAuthorRunner(dossier_builder=_dossier_for_attempt)
            result = runtime.run_text_description_adaptation_authoring(
                manifest,
                author_runner=runner,
                model="mock-adaptation-model",
            )
        self.assertEqual(result["status"], runtime.AUTHORING_ADAPTER_STATUS_READY)
        self.assertTrue(result["ok"])
        self.assertIsNotNone(result["dossier"])
        self.assertEqual(len(runner.calls), 1)
        tripwire.assert_no_provider_or_network_calls(self)
        self.assertFalse((REPO_ROOT / "modules" / "Sunken_Lighthouse").exists())

    def test_text_refusal_only_through_injected_runner_blocks(self) -> None:
        with _ProviderTripwire() as tripwire:
            manifest = self._ready_manifest()
            runner = FakeAuthorRunner(dossier_builder=_dossier_for_attempt, refused=True)
            result = runtime.run_text_description_adaptation_authoring(
                manifest,
                author_runner=runner,
                model="mock-adaptation-model",
            )
        self.assertEqual(result["status"], runtime.AUTHORING_ADAPTER_STATUS_BLOCKED)
        self.assertIsNone(result["dossier"])
        self.assertEqual(result["authoring"]["safe_class"], "author_policy_refusal")
        self.assertFalse(result["guards"]["module_builder_allowed"])
        self.assertTrue(result["authoring"]["failure_artifact_persisted"])
        self._assert_bounded_diagnostics(result)
        tripwire.assert_no_provider_or_network_calls(self)
        self.assertFalse((REPO_ROOT / "modules" / "Sunken_Lighthouse").exists())

    def test_text_provider_failure_only_through_injected_runner_blocks(self) -> None:
        with _ProviderTripwire() as tripwire:
            manifest = self._ready_manifest()
            runner = FakeAuthorRunner(
                dossier_builder=_dossier_for_attempt,
                error=RuntimeError("provider unavailable"),
            )
            result = runtime.run_text_description_adaptation_authoring(
                manifest,
                author_runner=runner,
                model="mock-adaptation-model",
            )
        self.assertEqual(result["status"], runtime.AUTHORING_ADAPTER_STATUS_BLOCKED)
        self.assertIsNone(result["dossier"])
        self.assertEqual(result["authoring"]["safe_class"], "provider_infrastructure")
        self._assert_bounded_diagnostics(result)
        tripwire.assert_no_provider_or_network_calls(self)
        self.assertFalse((REPO_ROOT / "modules" / "Sunken_Lighthouse").exists())

    def test_text_missing_injection_seam_trips_and_fails_closed(self) -> None:
        with _ProviderTripwire() as tripwire:
            manifest = self._ready_manifest()
            result = runtime.run_text_description_adaptation_authoring(
                manifest,
                model="gpt-5.6-luna",
            )
        self.assertEqual(result["status"], runtime.AUTHORING_ADAPTER_STATUS_BLOCKED)
        self.assertFalse(result["ok"])
        self.assertIsNone(result["dossier"])
        author_tripwire = tripwire.mocks.get("author_create_chat_client")
        self.assertIsNotNone(author_tripwire)
        self.assertEqual(author_tripwire.call_count, 1)
        self.assertEqual(result["authoring"]["safe_class"], "provider_infrastructure")
        self.assertEqual(result["authoring"]["reason_code"], "provider_client_init_failed")
        self._assert_bounded_diagnostics(result)
        for key, guard in tripwire.mocks.items():
            if key == "author_create_chat_client":
                continue
            if guard is not None:
                guard.assert_not_called()
        self.assertFalse((REPO_ROOT / "modules" / "Sunken_Lighthouse").exists())


class TestProviderFreeRouteTestSourceScan(unittest.TestCase):
    """AST source scan proving every provider-free route test uses injected
    provider seams and never accidentally invokes a live client, network
    surface, OS temp API, or host lifecycle entry point."""

    def test_route_tests_never_import_provider_or_network_modules(self) -> None:
        for relative in ROUTE_TEST_FILES:
            source = (REPO_ROOT / relative).read_text(encoding="utf-8")
            roots = _import_roots(source)
            with self.subTest(file=relative):
                self.assertEqual(
                    roots.intersection(_FORBIDDEN_IMPORT_ROOTS),
                    set(),
                    "provider/network imports must never appear in route tests",
                )

    def test_route_tests_never_call_live_client_or_network_surfaces(self) -> None:
        for relative in ROUTE_TEST_FILES:
            source = (REPO_ROOT / relative).read_text(encoding="utf-8")
            forbidden = _forbidden_call_names(source)
            with self.subTest(file=relative):
                self.assertEqual(
                    forbidden,
                    [],
                    "live provider/network/host call shapes must never appear",
                )

    def test_route_tests_never_use_os_temp_apis(self) -> None:
        for relative in ROUTE_TEST_FILES:
            source = (REPO_ROOT / relative).read_text(encoding="utf-8")
            forbidden = _forbidden_call_names(source)
            temp_calls = [
                name
                for name in forbidden
                if name in _FORBIDDEN_CALL_NAMES
                or any(token in name for token in ("mkdtemp", "mkstemp", "mktemp", "TemporaryDirectory", "NamedTemporaryFile", "gettempdir"))
            ]
            with self.subTest(file=relative):
                self.assertEqual(temp_calls, [], "OS temp APIs must never be called")

    def test_route_test_files_stay_ascii_with_spdx_headers(self) -> None:
        for relative in ROUTE_TEST_FILES:
            source = (REPO_ROOT / relative).read_text(encoding="utf-8")
            with self.subTest(file=relative):
                self.assertTrue(source.isascii(), "route test file must stay ASCII")
                self.assertIn("SPDX-FileCopyrightText", source[:160])
                self.assertIn("SPDX-License-Identifier", source[:160])

    def test_tripwire_adapter_tests_only_use_injected_seams(self) -> None:
        # Everything outside the direct guarded-invocation proof class must
        # never contain a live provider/network/OS-temp call shape; adapter
        # tests only pass injected seams and patch-target strings.
        own_source = Path(__file__).read_text(encoding="utf-8")
        tree = ast.parse(own_source)
        guard = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef)
            and node.name == "TestTripwireGuardsProviderSurfaces"
        )
        forbidden = _forbidden_call_names(
            own_source, excluded_range=(guard.lineno, guard.end_lineno or guard.lineno)
        )
        self.assertEqual(
            forbidden,
            [],
            "adapter tests must only reach provider behavior through injected seams",
        )

    def test_tripwire_suite_os_temp_and_scratch_hygiene(self) -> None:
        own_source = Path(__file__).read_text(encoding="utf-8")
        # Scan only the code before the forbidden-token set definitions so the
        # assertion is not self-referential.
        scan = own_source.split("_FORBIDDEN_IMPORT_ROOTS = frozenset(", 1)[0]
        for token in ("tempfile", "TemporaryDirectory", "/tmp", "/var/folders"):
            with self.subTest(token=token):
                self.assertNotIn(token, scan)
        self.assertTrue(own_source.isascii())
        self.assertIn("SPDX-FileCopyrightText", own_source[:160])
        self.assertIn("SPDX-License-Identifier", own_source[:160])
        scratch = SCRATCH_ROOT / str(uuid.uuid4())
        scratch.mkdir(parents=True, exist_ok=True)
        self.addCleanup(shutil.rmtree, scratch, ignore_errors=True)
        self.assertTrue(str(scratch).startswith(str(REPO_ROOT / "tmp")))
        self.assertFalse(str(scratch).startswith("/tmp/"))
        # The authoring adapters stay provider-free. The separate production
        # convergence callback is the explicitly permitted provider boundary
        # for task 1.2 and is excluded by its precise AST function range.
        runtime_source = RUNTIME_MODULE_PATH.read_text(encoding="utf-8")
        runtime_tree = ast.parse(runtime_source)
        convergence_callback = next(
            node
            for node in ast.walk(runtime_tree)
            if isinstance(node, ast.FunctionDef)
            and node.name == "adaptation_convergence_callback"
        )
        forbidden = _forbidden_call_names(
            runtime_source,
            excluded_range=(
                convergence_callback.lineno,
                convergence_callback.end_lineno or convergence_callback.lineno,
            ),
        )
        self.assertEqual(
            forbidden,
            [],
            "the runtime author adapter must never invoke provider surfaces itself",
        )


if __name__ == "__main__":
    unittest.main()
