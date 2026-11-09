# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

#!/usr/bin/env python3
"""Provider-transport-injected, one-attempt-per-scene study client.

This module prepares exact requests and controls study-local attempt accounting.
It contains no provider SDK, config import, credential lookup, or network
transport. A separately approved execution adapter may inject one dispatch.
"""

from __future__ import annotations

from dataclasses import dataclass
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Any, Callable

from .output_gates import OutputDiagnostic, OutputGateReport, extract_model_content, validate_model_output


REPO_ROOT = Path(__file__).resolve().parents[3]
STAGING_ROOT = REPO_ROOT / "tmp/router-rollout/mapping-pilot/mise-en-scene-offline/llm-staging"
FROZEN_ROOT = REPO_ROOT / "openspec/changes/v2-mise-en-scene-authoring-projection-evaluation/llm-staging-protocol"
MANIFEST_PATH = FROZEN_ROOT / "staging-manifest.json"
PROMPT_PATH = FROZEN_ROOT / "system-prompt.txt"
TASK_PROMPT_PATH = FROZEN_ROOT / "task-prompt.txt"
SCHEMA_PATH = FROZEN_ROOT / "output-contract.schema.json"
PARAMETERS_PATH = FROZEN_ROOT / "generation-parameters.json"
STUDY_LEDGER_PATH = STAGING_ROOT / "study-attempt-ledger.jsonl"
MODEL_ID = "openai/gpt-6-luna"
SCENE_ORDER = (
    "into_the_deepvault:scene:ha003-i02",
    "into_the_deepvault:scene:sd005-i03",
    "xhalruuns_masquerade:scene:tsu001-ao02",
)
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_LEDGER_BYTES = 64 * 1024
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_LEDGER_SCHEMA_VERSION = 2
_BINDING_HASH_FIELDS = (
    "manifest_sha256",
    "execution_approval_sha256",
    "availability_attestation_sha256",
)
_STUDY_BINDING_FIELDS = frozenset((*_BINDING_HASH_FIELDS, "run_id", "run_root_relative"))


class StagingError(RuntimeError):
    """Raised when a frozen input or attempt boundary is invalid."""


class _TransportReceiptError(Exception):
    """A transport receipt failed validation for a bounded safe reason."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


@dataclass(frozen=True)
class TransportResult:
    """Safe, credential-free receipt returned by one injected HTTP dispatch."""

    http_status: int
    body: bytes
    returned_model_id: str
    upstream_provider: str
    generation_id: str
    usage: dict[str, int]


@dataclass(frozen=True)
class AttemptReceipt:
    """Safe result metadata; raw response content remains in its run file."""

    scene_id: str
    attempt_number: int
    outcome: str
    response_path: str
    response_sha256: str
    returned_model_id: str
    upstream_provider: str
    generation_id: str
    usage: dict[str, int]


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")


def _sha256(contents: bytes) -> str:
    return hashlib.sha256(contents).hexdigest()


def _safe_path(path_value: str | Path, *, root: Path) -> Path:
    path = Path(path_value)
    if not path.is_absolute():
        path = root / path
    root_resolved = root.resolve(strict=True)
    lexical = Path(os.path.abspath(path))
    try:
        relative = lexical.relative_to(root_resolved)
    except ValueError as exc:
        raise StagingError("study path escapes its project-local root") from exc
    current = root_resolved
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise StagingError("study paths must not traverse symlinks")
    resolved = lexical.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise StagingError("study path resolves outside its project-local root") from exc
    return resolved


def _read_bytes(path: Path, *, root: Path) -> bytes:
    safe = _safe_path(path, root=root)
    try:
        file_stat = safe.lstat()
    except OSError as exc:
        raise StagingError("a frozen study artifact is missing") from exc
    if not stat.S_ISREG(file_stat.st_mode) or safe.is_symlink():
        raise StagingError("a frozen study artifact is not a regular file")
    try:
        return safe.read_bytes()
    except OSError as exc:
        raise StagingError("a frozen study artifact cannot be read") from exc


def _read_json(path: Path, *, root: Path) -> tuple[dict[str, Any], bytes]:
    contents = _read_bytes(path, root=root)
    value, _parsed_contents = _parse_json_object(contents)
    return value, contents


def _parse_json_object(contents: bytes) -> tuple[dict[str, Any], bytes]:
    try:
        value = json.loads(contents.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StagingError("a frozen study artifact is not valid JSON") from exc
    if type(value) is not dict:
        raise StagingError("a frozen study artifact must be a JSON object")
    return value, contents


def _private_create(path: Path, contents: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is not None:
        flags |= nofollow
    descriptor = os.open(path, flags, 0o600)
    try:
        offset = 0
        while offset < len(contents):
            offset += os.write(descriptor, contents[offset:])
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _validate_usage(value: object) -> dict[str, int]:
    if type(value) is not dict or not value:
        raise _TransportReceiptError("usage_receipt_missing_or_invalid")
    result: dict[str, int] = {}
    for key, amount in value.items():
        if type(key) is not str or not re.fullmatch(r"[a-z_]{1,40}", key):
            raise _TransportReceiptError("usage_receipt_missing_or_invalid")
        if type(amount) is not int or amount < 0:
            raise _TransportReceiptError("usage_receipt_missing_or_invalid")
        result[key] = amount
    return result


def _safe_identity(value: object, reason_code: str, max_length: int = 256) -> str:
    if type(value) is not str or not value or len(value) > max_length or not value.isascii():
        raise _TransportReceiptError(reason_code)
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise _TransportReceiptError(reason_code)
    return value


class StagingClient:
    """Prepare requests and enforce the frozen three-scene attempt allocation."""

    def __init__(
        self,
        run_id: str,
        availability_attestation_path: str | Path,
        execution_approval_path: str | Path,
        *,
        manifest_path: str | Path = MANIFEST_PATH,
        run_root: str | Path = STAGING_ROOT / "runs",
    ) -> None:
        if type(run_id) is not str or not _RUN_ID_RE.fullmatch(run_id) or run_id in (".", ".."):
            raise StagingError("run ID is invalid")
        self.run_id = run_id
        self.staging_root = STAGING_ROOT.resolve(strict=True)
        self.manifest_path = _safe_path(manifest_path, root=REPO_ROOT)
        self.availability_attestation_path = _safe_path(availability_attestation_path, root=REPO_ROOT)
        self.execution_approval_path = _safe_path(execution_approval_path, root=self.staging_root)
        self.run_root = _safe_path(run_root, root=self.staging_root)
        self.run_dir = _safe_path(self.run_root / run_id, root=self.staging_root)
        self.run_root_relative = self.run_root.relative_to(self.staging_root).as_posix()
        self.ledger_path = _safe_path(STUDY_LEDGER_PATH, root=self.staging_root)
        self._transport_owner_token = object()
        self._manifest, self._manifest_bytes = _read_json(self.manifest_path, root=REPO_ROOT)
        self._validate_manifest()
        self._base_study_binding = {
            "manifest_sha256": _sha256(self._manifest_bytes),
            "run_id": self.run_id,
            "run_root_relative": self.run_root_relative,
        }

    def _validate_manifest(self) -> None:
        manifest = self._manifest
        if manifest.get("schema") != "neq.llm_staging_manifest.v1":
            raise StagingError("study manifest schema mismatch")
        if manifest.get("status") != "FROZEN_FOR_OVERSEER_REVIEW":
            raise StagingError("study manifest is not frozen for review")
        if manifest.get("execution_status") != "NOT_STARTED" or manifest.get("execution_authorized") is not False or manifest.get("calls_made") != 0:
            raise StagingError("study manifest records prior execution")
        ruling = manifest.get("owner_ruling")
        if type(ruling) is not dict or ruling.get("model") != MODEL_ID or ruling.get("generation_attempt_cap") != 3:
            raise StagingError("owner-approved route or cap does not match")
        if ruling.get("selected_scene_ids") != list(SCENE_ORDER) or manifest.get("attempt_order") != list(SCENE_ORDER):
            raise StagingError("owner-approved scene selection or order does not match")
        if ruling.get("other_27_attempts_authorized") is not False or ruling.get("fallbacks_retries_tools_disabled") is not True:
            raise StagingError("attempt or fallback authorization is invalid")

        artifacts = manifest.get("artifacts")
        if type(artifacts) is not dict or not artifacts:
            raise StagingError("manifest artifact hashes are missing")
        for relative, expected_hash in artifacts.items():
            if type(relative) is not str or type(expected_hash) is not str or not _SHA256_RE.fullmatch(expected_hash):
                raise StagingError("manifest contains an invalid artifact hash")
            actual = _sha256(_read_bytes(REPO_ROOT / relative, root=REPO_ROOT))
            if actual != expected_hash:
                raise StagingError("a frozen artifact hash changed")

        scenes = manifest.get("scenes")
        if type(scenes) is not list or [row.get("scene_id") for row in scenes if type(row) is dict] != list(SCENE_ORDER):
            raise StagingError("manifest scene records do not match the approved order")
        for row in scenes:
            source_contents = _read_bytes(REPO_ROOT / row["source_file_path"], root=REPO_ROOT)
            if _sha256(source_contents) != row["source_file_sha256"]:
                raise StagingError("a selected module source file changed")
            for path_key, hash_key in (
                ("source_packet_path", "source_packet_sha256"),
                ("expected_inputs_path", "expected_inputs_sha256"),
            ):
                contents = _read_bytes(REPO_ROOT / row[path_key], root=REPO_ROOT)
                if _sha256(contents) != row[hash_key]:
                    raise StagingError("a per-scene source or reference hash changed")

    def _verify_live_frozen_inputs(self) -> None:
        current_manifest = _read_bytes(self.manifest_path, root=REPO_ROOT)
        if current_manifest != self._manifest_bytes:
            raise StagingError("frozen study manifest changed after client initialization")
        self._validate_manifest()

    def _read_frozen_bytes(self, relative_path: str) -> bytes:
        artifacts = self._manifest.get("artifacts")
        expected_hash = artifacts.get(relative_path) if type(artifacts) is dict else None
        if type(expected_hash) is not str or not _SHA256_RE.fullmatch(expected_hash):
            raise StagingError("requested input is not bound by the frozen manifest")
        contents = _read_bytes(REPO_ROOT / relative_path, root=REPO_ROOT)
        if _sha256(contents) != expected_hash:
            raise StagingError("a frozen study input changed after client initialization")
        return contents

    def _scene(self, scene_id: str) -> dict[str, Any]:
        if scene_id not in SCENE_ORDER:
            raise StagingError("scene is not owner-approved")
        return next(row for row in self._manifest["scenes"] if row["scene_id"] == scene_id)

    def build_request(self, scene_id: str) -> dict[str, Any]:
        """Build one exact request payload without credentials or network I/O."""

        self._verify_live_frozen_inputs()
        scene = self._scene(scene_id)
        parameters, _parameters_bytes = _parse_json_object(
            self._read_frozen_bytes(str(PARAMETERS_PATH.relative_to(REPO_ROOT)))
        )
        if parameters.get("provider") != "openrouter" or parameters.get("model") != MODEL_ID:
            raise StagingError("frozen provider or model mismatch")
        request_parameters = parameters.get("parameters")
        transport_policy = parameters.get("transport_policy")
        if type(request_parameters) is not dict or type(transport_policy) is not dict:
            raise StagingError("frozen request parameters are malformed")
        if request_parameters.get("provider") != {"allow_fallbacks": False}:
            raise StagingError("OpenRouter fallbacks are not explicitly disabled")
        if request_parameters.get("tools") != [] or request_parameters.get("tool_choice") != "none":
            raise StagingError("tools are not explicitly disabled")
        if request_parameters.get("response_format") != {"type": "json_object"}:
            raise StagingError("frozen JSON response format is missing")
        reasoning_policy = parameters.get("reasoning_policy")
        if type(reasoning_policy) is not dict or any(
            reasoning_policy.get(key) != value
            for key, value in {
                "request_field_sent": False,
                "setting": "model_default",
            }.items()
        ) or type(reasoning_policy.get("justification")) is not str or not reasoning_policy["justification"].strip():
            raise StagingError("reasoning policy is not explicit and fail-closed")
        if transport_policy.get("automatic_retries") != 0 or transport_policy.get("generation_dispatches_per_scene") != 1:
            raise StagingError("transport policy is not one-shot")

        packet_bytes = self._read_frozen_bytes(scene["source_packet_path"])
        expected_inputs_bytes = self._read_frozen_bytes(scene["expected_inputs_path"])
        schema = self._read_frozen_bytes(str(SCHEMA_PATH.relative_to(REPO_ROOT))).decode("utf-8")
        system_prompt = self._read_frozen_bytes(str(PROMPT_PATH.relative_to(REPO_ROOT))).decode("utf-8")
        task_template = self._read_frozen_bytes(str(TASK_PROMPT_PATH.relative_to(REPO_ROOT))).decode("utf-8")
        task_prompt = task_template
        substitutions = {
            "{{SCENE_ID}}": scene_id,
            "{{SOURCE_PACKET_JSON}}": packet_bytes.decode("utf-8"),
            "{{EXPECTED_INPUTS_JSON}}": expected_inputs_bytes.decode("utf-8"),
            "{{OUTPUT_SCHEMA_JSON}}": schema,
        }
        for placeholder, value in substitutions.items():
            if placeholder not in task_prompt:
                raise StagingError("prompt template is missing a required placeholder")
            task_prompt = task_prompt.replace(placeholder, value)
        if re.search(r"\{\{[A-Z][A-Z0-9_]*\}\}", task_prompt):
            raise StagingError("prompt template contains an unresolved placeholder")

        request: dict[str, Any] = {
            "model": MODEL_ID,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": task_prompt},
            ],
        }
        request.update(request_parameters)
        return request

    def endpoint(self) -> str:
        parameters, _contents = _parse_json_object(
            self._read_frozen_bytes(str(PARAMETERS_PATH.relative_to(REPO_ROOT)))
        )
        endpoint = parameters.get("endpoint")
        if endpoint != "https://openrouter.ai/api/v1/chat/completions":
            raise StagingError("frozen endpoint mismatch")
        return endpoint

    def _verify_availability(self) -> str:
        attestation, _attestation_bytes = _read_json(self.availability_attestation_path, root=REPO_ROOT)
        required = {
            "schema": "neq.openrouter_model_availability.v1",
            "method": "GET",
            "url": "https://openrouter.ai/api/v1/models",
            "requested_model_id": MODEL_ID,
            "exact_model_id_present": True,
            "request_count": 1,
            "authenticated": False,
            "redirects_followed": False,
            "verdict": "CONFIRMED",
            "generation_calls": 0,
        }
        if any(attestation.get(key) != value for key, value in required.items()) or attestation.get("http_status") != 200:
            raise StagingError("exact model availability is not confirmed")
        raw_path = attestation.get("raw_listing_path")
        raw_hash = attestation.get("raw_listing_sha256")
        if type(raw_path) is not str or type(raw_hash) is not str or not _SHA256_RE.fullmatch(raw_hash):
            raise StagingError("availability evidence binding is malformed")
        raw_bytes = _read_bytes(self.staging_root / raw_path, root=self.staging_root)
        if _sha256(raw_bytes) != raw_hash:
            raise StagingError("availability listing hash mismatch")
        try:
            listing = json.loads(raw_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise StagingError("availability listing is malformed") from exc
        rows = listing.get("data") if type(listing) is dict else None
        if type(rows) is not list or not any(type(row) is dict and row.get("id") == MODEL_ID for row in rows):
            raise StagingError("exact model ID is absent from the preserved listing")
        return _sha256(_attestation_bytes)

    def _verify_execution_approval(self) -> str:
        approval, approval_bytes = _read_json(self.execution_approval_path, root=self.staging_root)
        protocol_path = "openspec/changes/v2-mise-en-scene-authoring-projection-evaluation/llm-staging-protocol/protocol.md"
        expected = {
            "schema": "neq.llm_staging_execution_approval.v1",
            "status": "APPROVED_STEP_B",
            "manifest_sha256": _sha256(self._manifest_bytes),
            "protocol_sha256": self._manifest["artifacts"].get(protocol_path),
            "approved_scene_ids": list(SCENE_ORDER),
            "generation_attempt_cap": 3,
            "approved_by": "overseer",
            "package_review": "PASS",
            "manual_lineage_review": "COMPLETE",
            "lineage_reviewed_scene_ids": list(SCENE_ORDER),
            "reviewed_source_packet_sha256": {
                row["scene_id"]: row["source_packet_sha256"]
                for row in self._manifest["scenes"]
            },
        }
        if any(approval.get(key) != value for key, value in expected.items()):
            raise StagingError("separate step (b) execution approval is missing or mismatched")
        approved_at = approval.get("approved_at_utc")
        if type(approved_at) is not str or not approved_at.endswith("Z"):
            raise StagingError("step (b) approval timestamp is missing")
        return _sha256(approval_bytes)

    def send_once(
        self,
        scene_id: str,
        transport: Callable[[str, dict[str, Any]], TransportResult],
    ) -> AttemptReceipt:
        """Reserve once, call one injected transport once, and never retry."""

        if not callable(transport):
            raise StagingError("a one-shot transport must be explicitly injected")
        return self._send_once(scene_id, injected_transport=transport)

    def send_once_with_openrouter(
        self,
        scene_id: str,
        *,
        transport: object | None = None,
    ) -> AttemptReceipt:
        """Use OpenRouter only through this client's reserved ledger path."""

        from .transport import OpenRouterTransport

        adapter = transport if transport is not None else OpenRouterTransport()
        if type(adapter) is not OpenRouterTransport:
            raise StagingError("a study OpenRouter transport is required")
        return self._send_once(scene_id, openrouter_transport=adapter)

    def _send_once(
        self,
        scene_id: str,
        *,
        injected_transport: Callable[[str, dict[str, Any]], TransportResult] | None = None,
        openrouter_transport: object | None = None,
    ) -> AttemptReceipt:
        if (injected_transport is None) == (openrouter_transport is None):
            raise StagingError("exactly one one-shot transport path is required")

        request = self.build_request(scene_id)
        endpoint = self.endpoint()
        if endpoint != "https://openrouter.ai/api/v1/chat/completions":
            raise StagingError("frozen endpoint mismatch")
        availability_hash = self._verify_availability()
        approval_hash = self._verify_execution_approval()
        self._verify_live_frozen_inputs()
        request_hash = _sha256(_canonical_bytes(request))
        _safe_path(self.run_dir, root=self.staging_root)
        study_binding = dict(self._base_study_binding)
        study_binding.update({
            "execution_approval_sha256": approval_hash,
            "availability_attestation_sha256": availability_hash,
        })
        attempt_number = self._append_ledger_event({
            "event": "reservation",
            "scene_id": scene_id,
            "request_sha256": request_hash,
            "study_binding": study_binding,
        })

        self._prepare_run_directory()
        try:
            if openrouter_transport is not None:
                from .transport import _create_reserved_dispatch_context

                context = _create_reserved_dispatch_context(
                    self._transport_owner_token,
                    attempt_number,
                    scene_id,
                    request_hash,
                )
                result = openrouter_transport._dispatch_reserved(
                    context,
                    endpoint,
                    request,
                    owner_token=self._transport_owner_token,
                )
            else:
                result = injected_transport(endpoint, request)
        except Exception:
            self._append_ledger_event({
                "event": "result",
                "attempt_number": attempt_number,
                "scene_id": scene_id,
                "outcome": "failed",
                "failure_reason": "transport_exception",
                "study_binding": study_binding,
            })
            raise StagingError("one-shot transport failed; allocation consumed and no retry is permitted") from None

        response_record = self._preserve_raw_response(result, attempt_number, scene_id)
        try:
            receipt = self._validate_transport_result(result)
        except _TransportReceiptError as exc:
            record = {
                "event": "result",
                "attempt_number": attempt_number,
                "scene_id": scene_id,
                "outcome": "failed",
                "failure_reason": exc.reason_code,
                "stop_run": True,
                "study_binding": study_binding,
            }
            if response_record is not None:
                record.update(response_record)
            if type(result) is TransportResult and type(result.http_status) is int and 100 <= result.http_status <= 599:
                record["http_status"] = result.http_status
            self._append_ledger_event(record)
            raise StagingError("provider receipt failed validation; allocation consumed, stop") from None

        response_path = response_record["response_path"] if response_record is not None else None
        response_hash = response_record["response_sha256"] if response_record is not None else None
        if response_record is None:
            # _validate_transport_result only accepts bounded byte responses.
            raise StagingError("response preservation failed; allocation remains consumed") from None

        outcome = "succeeded"
        record = {
            "event": "result",
            "attempt_number": attempt_number,
            "scene_id": scene_id,
            "outcome": outcome,
            "http_status": result.http_status,
            "response_path": response_path,
            "response_sha256": response_hash,
            "returned_model_id": receipt["returned_model_id"],
            "upstream_provider": receipt["upstream_provider"],
            "generation_id": receipt["generation_id"],
            "usage": receipt["usage"],
            "study_binding": study_binding,
        }
        if result.http_status != 200:
            outcome = "failed"
            record["outcome"] = outcome
            record["failure_reason"] = "http_status_not_200"
        if receipt["returned_model_id"] != MODEL_ID:
            outcome = "failed"
            record["outcome"] = outcome
            record["failure_reason"] = "returned_model_id_mismatch"
            record["stop_run"] = True
        self._append_ledger_event(record)

        if outcome != "succeeded":
            if record.get("stop_run") is True:
                raise StagingError("provider status or returned model identity failed; allocation consumed, stop")
            raise StagingError("provider status failed; allocation consumed and no retry is permitted")
        return AttemptReceipt(
            scene_id=scene_id,
            attempt_number=attempt_number,
            outcome=outcome,
            response_path=response_path,
            response_sha256=str(response_hash),
            returned_model_id=receipt["returned_model_id"],
            upstream_provider=receipt["upstream_provider"],
            generation_id=receipt["generation_id"],
            usage=receipt["usage"],
        )

    def _prepare_run_directory(self) -> None:
        _safe_path(self.run_root, root=self.staging_root)
        self.run_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        _safe_path(self.run_dir, root=self.staging_root)
        self.run_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.run_dir.is_symlink():
            raise StagingError("run directory must not be a symlink")
        try:
            os.chmod(self.run_dir, 0o700)
        except OSError as exc:
            raise StagingError("run directory permissions could not be restricted") from exc

    def _preserve_raw_response(
        self,
        result: object,
        attempt_number: int,
        scene_id: str,
    ) -> dict[str, str] | None:
        if type(result) is not TransportResult or type(result.body) is not bytes or len(result.body) > _MAX_RESPONSE_BYTES:
            return None
        response_path = self.run_dir / "responses" / (
            "%02d_" % attempt_number + scene_id.replace(":", "__") + ".provider-response.json"
        )
        _safe_path(response_path, root=self.staging_root)
        _private_create(response_path, result.body)
        return {
            "response_path": str(response_path.relative_to(self.staging_root)),
            "response_sha256": _sha256(result.body),
        }

    def validate_attempt(self, receipt: AttemptReceipt) -> OutputGateReport:
        """Preserve one exact model artifact, then run deterministic offline gates."""

        self._verify_live_frozen_inputs()
        if type(receipt) is not AttemptReceipt or receipt.scene_id not in SCENE_ORDER:
            raise StagingError("output validation requires a receipt from this study")
        if receipt.outcome != "succeeded" or not _SHA256_RE.fullmatch(receipt.response_sha256):
            raise StagingError("output validation requires a successful bound response")
        response_path = _safe_path(self.staging_root / receipt.response_path, root=self.staging_root)
        response_bytes = _read_bytes(response_path, root=self.staging_root)
        if _sha256(response_bytes) != receipt.response_sha256:
            raise StagingError("provider response hash does not match its receipt")
        records = self._verify_ledger(
            _read_bytes(self.ledger_path, root=self.staging_root),
            expected_binding=self._base_study_binding,
        )
        matching = [
            row for row in records
            if row.get("event") == "result"
            and row.get("attempt_number") == receipt.attempt_number
            and row.get("scene_id") == receipt.scene_id
            and row.get("outcome") == receipt.outcome
            and row.get("response_path") == receipt.response_path
            and row.get("response_sha256") == receipt.response_sha256
            and row.get("returned_model_id") == receipt.returned_model_id
            and row.get("upstream_provider") == receipt.upstream_provider
            and row.get("generation_id") == receipt.generation_id
            and row.get("usage") == receipt.usage
        ]
        if len(matching) != 1:
            raise StagingError("provider response is not bound to exactly one ledger result")

        attempt_prefix = "%02d_" % receipt.attempt_number + receipt.scene_id.replace(":", "__")
        artifact_path = self.run_dir / "artifacts" / (attempt_prefix + ".json")
        report_path = self.run_dir / "gates" / (attempt_prefix + ".json")
        _safe_path(artifact_path, root=self.staging_root)
        _safe_path(report_path, root=self.staging_root)
        if artifact_path.exists() or report_path.exists():
            raise StagingError("output artifact or gate report already exists; refusing overwrite")

        try:
            artifact_bytes = extract_model_content(
                response_bytes,
                expected_model_id=receipt.returned_model_id,
                expected_generation_id=receipt.generation_id,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            report = OutputGateReport(
                scene_id=receipt.scene_id,
                artifact_sha256=None,
                deterministic_status="FAIL",
                semantic_review_status="PENDING",
                owner_rating_status="PENDING",
                scene_status="FAIL",
                diagnostics=(OutputDiagnostic("PROVIDER_CONTENT_INVALID", "schema", "$.provider_response"),),
            )
            artifact_relative: str | None = None
        else:
            _private_create(artifact_path, artifact_bytes)
            scene = self._scene(receipt.scene_id)
            expected_inputs, _expected_bytes = _parse_json_object(
                self._read_frozen_bytes(scene["expected_inputs_path"])
            )
            schema, _schema_bytes = _parse_json_object(
                self._read_frozen_bytes(str(SCHEMA_PATH.relative_to(REPO_ROOT)))
            )
            report = validate_model_output(artifact_bytes, expected_inputs, receipt.scene_id, schema)
            artifact_relative = str(artifact_path.relative_to(self.staging_root))

        report_record = report.to_dict()
        report_record.update({
            "provider_response_path": receipt.response_path,
            "provider_response_sha256": receipt.response_sha256,
            "artifact_path": artifact_relative,
        })
        _private_create(
            report_path,
            (json.dumps(report_record, sort_keys=True, indent=2) + "\n").encode("ascii"),
        )
        return report

    def _validate_transport_result(self, result: object) -> dict[str, Any]:
        if type(result) is not TransportResult:
            raise _TransportReceiptError("transport_receipt_missing_or_invalid")
        if type(result.http_status) is not int or not 100 <= result.http_status <= 599:
            raise _TransportReceiptError("http_status_missing_or_invalid")
        if type(result.body) is not bytes or len(result.body) > _MAX_RESPONSE_BYTES:
            raise _TransportReceiptError("raw_response_missing_or_oversized")
        return {
            "returned_model_id": _safe_identity(
                result.returned_model_id, "returned_model_id_missing_or_invalid"
            ),
            "upstream_provider": _safe_identity(
                result.upstream_provider, "upstream_provider_missing_or_invalid", 128
            ),
            "generation_id": _safe_identity(
                result.generation_id, "generation_id_missing_or_invalid"
            ),
            "usage": _validate_usage(result.usage),
        }

    def _append_ledger_event(self, event: dict[str, Any]) -> int:
        _safe_path(self.ledger_path, root=self.staging_root)
        if event.get("event") not in ("reservation", "result"):
            raise StagingError("attempt ledger event type is invalid")
        study_binding = event.get("study_binding")
        if type(study_binding) is not dict:
            raise StagingError("study allocation identity is missing")
        self._validate_study_binding(study_binding)
        flags = os.O_RDWR | os.O_APPEND | os.O_CREAT
        nofollow = getattr(os, "O_NOFOLLOW", None)
        if nofollow is not None:
            flags |= nofollow
        descriptor = os.open(self.ledger_path, flags, 0o600)
        try:
            os.fchmod(descriptor, 0o600)
            file_stat = os.fstat(descriptor)
            path_stat = os.lstat(self.ledger_path)
            if not stat.S_ISREG(file_stat.st_mode) or (file_stat.st_dev, file_stat.st_ino) != (path_stat.st_dev, path_stat.st_ino):
                raise StagingError("attempt ledger is not a stable regular file")
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            contents = self._read_descriptor(descriptor)
            records = self._verify_ledger(contents, expected_binding=study_binding)
            if not records:
                header = {
                    "event": "header",
                    "schema_version": _LEDGER_SCHEMA_VERSION,
                    "allocation_scope": "study",
                    "scene_order": list(SCENE_ORDER),
                    "attempt_cap": len(SCENE_ORDER),
                    "previous_sha256": None,
                }
                records.append(self._hash_record(header))
                self._write_record(descriptor, records[-1])

            reservation_count = sum(row["event"] == "reservation" for row in records)
            results = [row for row in records if row["event"] == "result"]
            pending = reservation_count > len(results)
            stopped = any(row.get("stop_run") is True for row in results)
            next_attempt = reservation_count + 1
            if event["event"] == "reservation":
                if (
                    pending
                    or stopped
                    or next_attempt > len(SCENE_ORDER)
                    or SCENE_ORDER[reservation_count] != event.get("scene_id")
                ):
                    raise StagingError("scene allocation is exhausted, pending, or out of approved order")
                payload = dict(event)
                payload.update({"attempt_number": next_attempt, "schema_version": _LEDGER_SCHEMA_VERSION})
                record = self._hash_record(payload, records[-1]["record_sha256"])
                self._write_record(descriptor, record)
                return next_attempt

            if event["event"] != "result" or not pending:
                raise StagingError("result has no pending reserved attempt")
            reservation = next(row for row in reversed(records) if row["event"] == "reservation")
            if (
                event.get("attempt_number") != reservation["attempt_number"]
                or event.get("scene_id") != reservation["scene_id"]
                or study_binding != reservation.get("study_binding")
            ):
                raise StagingError("result does not match its reserved attempt")
            payload = dict(event)
            payload.update({"schema_version": _LEDGER_SCHEMA_VERSION})
            record = self._hash_record(payload, records[-1]["record_sha256"])
            self._write_record(descriptor, record)
            return int(reservation["attempt_number"])
        finally:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            except OSError:
                pass
            os.close(descriptor)

    @staticmethod
    def _read_descriptor(descriptor: int) -> bytes:
        size = os.fstat(descriptor).st_size
        if size > _MAX_LEDGER_BYTES:
            raise StagingError("attempt ledger exceeded its size bound")
        os.lseek(descriptor, 0, os.SEEK_SET)
        chunks: list[bytes] = []
        remaining = size
        while remaining:
            chunk = os.read(descriptor, min(remaining, 65536))
            if not chunk:
                raise StagingError("attempt ledger changed while locked")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def _verify_ledger(
        self,
        contents: bytes,
        *,
        expected_binding: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        if not contents:
            return []
        if not contents.endswith(b"\n"):
            raise StagingError("attempt ledger has an incomplete record")
        try:
            records = [json.loads(line.decode("ascii")) for line in contents.splitlines()]
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise StagingError("attempt ledger is malformed") from exc
        if not records or type(records[0]) is not dict:
            raise StagingError("attempt ledger header is missing")
        for index, record in enumerate(records):
            if type(record) is not dict or record.get("schema_version") != _LEDGER_SCHEMA_VERSION:
                raise StagingError("attempt ledger schema mismatch")
            record_hash = record.get("record_sha256")
            if type(record_hash) is not str or not _SHA256_RE.fullmatch(record_hash):
                raise StagingError("attempt ledger hash is malformed")
            unhashed = dict(record)
            del unhashed["record_sha256"]
            if _sha256(_canonical_bytes(unhashed)) != record_hash:
                raise StagingError("attempt ledger record hash mismatch")
            expected_previous = None if index == 0 else records[index - 1]["record_sha256"]
            if record.get("previous_sha256") != expected_previous:
                raise StagingError("attempt ledger hash chain mismatch")
        header = records[0]
        if (
            header.get("event") != "header"
            or header.get("allocation_scope") != "study"
            or header.get("scene_order") != list(SCENE_ORDER)
            or header.get("attempt_cap") != len(SCENE_ORDER)
        ):
            raise StagingError("attempt ledger header is invalid")
        reservations: list[dict[str, Any]] = []
        results: list[dict[str, Any]] = []
        bound_identity: dict[str, Any] | None = None
        stop_run = False
        for record in records[1:]:
            if record.get("event") == "reservation":
                expected_number = len(reservations) + 1
                if (
                    stop_run
                    or expected_number > len(SCENE_ORDER)
                    or record.get("attempt_number") != expected_number
                    or record.get("scene_id") != SCENE_ORDER[expected_number - 1]
                ):
                    raise StagingError("attempt ledger reservation sequence is invalid")
                if len(reservations) != len(results):
                    raise StagingError("attempt ledger has an unresolved earlier reservation")
                identity = record.get("study_binding")
                self._validate_study_binding(identity)
                if bound_identity is None:
                    bound_identity = identity
                elif identity != bound_identity:
                    raise StagingError("study allocation identity changed after reservation")
                if expected_binding is not None and any(
                    identity.get(key) != value for key, value in expected_binding.items()
                ):
                    raise StagingError("study allocation is bound to another run identity")
                if not _SHA256_RE.fullmatch(str(record.get("request_sha256", ""))):
                    raise StagingError("attempt ledger reservation hashes are invalid")
                reservations.append(record)
            elif record.get("event") == "result":
                if len(results) >= len(reservations) or not reservations:
                    raise StagingError("attempt ledger result has no reservation")
                reservation = reservations[len(results)]
                if record.get("attempt_number") != reservation["attempt_number"] or record.get("scene_id") != reservation["scene_id"]:
                    raise StagingError("attempt ledger result identity mismatch")
                if record.get("study_binding") != reservation.get("study_binding"):
                    raise StagingError("attempt ledger result study identity mismatch")
                if record.get("outcome") not in ("succeeded", "failed"):
                    raise StagingError("attempt ledger result outcome is invalid")
                if "stop_run" in record and type(record["stop_run"]) is not bool:
                    raise StagingError("attempt ledger stop marker is invalid")
                failure_reason = record.get("failure_reason")
                if failure_reason is not None and (
                    type(failure_reason) is not str or not re.fullmatch(r"[a-z_]{1,64}", failure_reason)
                ):
                    raise StagingError("attempt ledger failure reason is invalid")
                has_response_path = "response_path" in record
                has_response_hash = "response_sha256" in record
                if has_response_path != has_response_hash:
                    raise StagingError("attempt ledger response binding is incomplete")
                if has_response_hash and (
                    type(record["response_path"]) is not str
                    or not _SHA256_RE.fullmatch(str(record["response_sha256"]))
                ):
                    raise StagingError("attempt ledger response binding is invalid")
                results.append(record)
                stop_run = stop_run or record.get("stop_run") is True
            else:
                raise StagingError("attempt ledger contains an unknown event")
        return records

    @staticmethod
    def _validate_study_binding(value: object) -> None:
        if type(value) is not dict or set(value) != _STUDY_BINDING_FIELDS:
            raise StagingError("study allocation identity is malformed")
        for field in _BINDING_HASH_FIELDS:
            digest = value.get(field)
            if type(digest) is not str or not _SHA256_RE.fullmatch(digest):
                raise StagingError("study allocation hash binding is malformed")
        run_id = value.get("run_id")
        if type(run_id) is not str or not _RUN_ID_RE.fullmatch(run_id) or run_id in (".", ".."):
            raise StagingError("study allocation run identity is malformed")
        run_root_relative = value.get("run_root_relative")
        if (
            type(run_root_relative) is not str
            or not run_root_relative
            or not run_root_relative.isascii()
            or any(ord(character) < 32 or ord(character) == 127 for character in run_root_relative)
        ):
            raise StagingError("study allocation root identity is malformed")
        root_path = Path(run_root_relative)
        if root_path.is_absolute() or any(part == ".." for part in root_path.parts):
            raise StagingError("study allocation root identity is malformed")

    @staticmethod
    def _hash_record(payload: dict[str, Any], previous_sha256: str | None = None) -> dict[str, Any]:
        record = dict(payload)
        record["previous_sha256"] = previous_sha256
        record["record_sha256"] = _sha256(_canonical_bytes(record))
        return record

    @staticmethod
    def _write_record(descriptor: int, record: dict[str, Any]) -> None:
        contents = _canonical_bytes(record) + b"\n"
        offset = 0
        while offset < len(contents):
            offset += os.write(descriptor, contents[offset:])
        os.fsync(descriptor)


__all__ = ["AttemptReceipt", "StagingClient", "StagingError", "TransportResult"]
