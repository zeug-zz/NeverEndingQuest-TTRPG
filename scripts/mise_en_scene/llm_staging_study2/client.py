# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Study 2 frozen-request client and approval-before-reservation fence."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
from typing import Any

from .contract import (
    FrozenSceneBinding,
    load_frozen_bindings,
)
from .ledger import (
    LEDGER_NAME,
    SCENE_ORDER,
    STUDY2_ROOT_RELATIVE,
    STUDY_ID,
    Study2Ledger,
    Study2LedgerError,
)
from .transport import (
    MODEL_ID,
    OPENROUTER_ENDPOINT,
    MAX_RESPONSE_BYTES,
    OpenRouterTransport,
    Study2TransportError,
    _create_reserved_dispatch_context,
    _extract_response_metadata,
    _validate_generation_config,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
STUDY2_PROTOCOL_RELATIVE = (
    "openspec/changes/v2-mise-en-scene-authoring-projection-evaluation/"
    "llm-staging-study2/protocol"
)
STUDY1_PROTOCOL_RELATIVE = (
    "openspec/changes/v2-mise-en-scene-authoring-projection-evaluation/"
    "llm-staging-protocol"
)
STUDY2_ROOT = REPO_ROOT / STUDY2_ROOT_RELATIVE
STUDY2_PROTOCOL_ROOT = REPO_ROOT / STUDY2_PROTOCOL_RELATIVE
MANIFEST_NAME = "staging-manifest.json"
HISTORICAL_RAW_LISTING_PATH = (
    "tmp/router-rollout/mapping-pilot/mise-en-scene-offline/llm-staging/"
    "availability-check/model-listing.json"
)
HISTORICAL_RAW_LISTING_SHA256 = "d94d8370997bb6a32c8265d0c5368d98c121355ebed0c51698539d81e32bdc13"
PREPARATION_ONLY_AUTHORITY_ID = "neq-study2-plan-confirmed-20261109"
MAX_FROZEN_FILE_BYTES = 4 * 1024 * 1024
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_AUTHORITY_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_MANIFEST_FIELDS = frozenset(
    {
        "schema",
        "study_id",
        "protocol_version",
        "status",
        "scene_order",
        "attempt_cap",
        "endpoint",
        "model_id",
        "availability",
        "artifacts",
        "scenes",
    }
)
_ARTIFACT_ROLES = (
    "protocol",
    "input_bindings",
    "output_schema",
    "system_prompt",
    "task_prompt",
    "generation_config",
    "availability_attestation",
)
_APPROVAL_FIELDS = frozenset(
    {
        "schema",
        "status",
        "review_status",
        "study_id",
        "attempt_cap",
        "model_id",
        "endpoint",
        "manifest_sha256",
        "protocol_version",
        "protocol_sha256",
        "availability_attestation_sha256",
        "availability_raw_listing_sha256",
        "scene_order",
        "study_root_relative",
        "authority_record_id",
        "approved_by",
        "approved_at_utc",
    }
)
class Study2ExecutionError(RuntimeError):
    """A bounded failure; exception text never contains input or provider data."""


@dataclass(frozen=True)
class ApprovalPins:
    """Hashes and ruling ID independently verified from a primary authority record.

    The JSON records being checked are not their own authority. The orchestrator
    supplies these pins only after reviewing the primary owner/Overseer record.
    """

    owner_approval_sha256: str
    overseer_approval_sha256: str
    authority_record_id: str


@dataclass(frozen=True)
class Study2TransportResult:
    """Credential-free transport receipt derived from the actual response body."""

    http_status: int
    body: bytes
    returned_model_id: str
    upstream_provider: str
    generation_id: str
    usage: dict[str, Any] | None


@dataclass(frozen=True)
class Study2AttemptReceipt:
    """Persisted raw-response hash and validated, actual provider receipt."""

    study_id: str
    scene_id: str
    attempt_number: int
    response_path: str
    response_sha256: str
    returned_model_id: str
    upstream_provider: str
    generation_id: str
    usage: dict[str, Any]


@dataclass(frozen=True)
class _FrozenBundle:
    manifest: dict[str, Any]
    manifest_bytes: bytes
    manifest_sha256: str
    artifact_bytes: dict[str, bytes]
    artifact_hashes: dict[str, str]
    scene_bindings: dict[str, FrozenSceneBinding]
    generation_config: dict[str, Any]
    generation_config_bytes: bytes
    availability_attestation_sha256: str


class Study2Client:
    """Run exactly one approved scene through the fixed Study 2 ledger."""

    def __init__(self, run_id: str, approval_pins: ApprovalPins | None = None) -> None:
        if type(run_id) is not str or _RUN_ID_RE.fullmatch(run_id) is None or run_id in (".", ".."):
            raise Study2ExecutionError("RUN_ID_INVALID")
        self.run_id = run_id
        self.approval_pins = approval_pins
        self._transport_owner_token = object()

    @property
    def run_root_relative(self) -> str:
        return STUDY2_ROOT_RELATIVE + "/runs/" + self.run_id

    @property
    def run_dir(self) -> Path:
        return STUDY2_ROOT / "runs" / self.run_id

    @property
    def ledger_path(self) -> Path:
        return STUDY2_ROOT / LEDGER_NAME

    def build_request(self, scene_id: str) -> dict[str, Any]:
        """Build a request only from the hash-bound Study 2 manifest inputs."""

        bundle = self._load_frozen_bundle()
        return self._build_request(bundle, scene_id)[0]

    def initialize_ledger(self) -> None:
        """Explicitly initialize once, only after both externally pinned approvals."""

        bundle = self._load_frozen_bundle()
        owner_hash, overseer_hash = self._verify_approvals(bundle)
        binding = self._ledger_binding(bundle, owner_hash, overseer_hash)
        try:
            Study2Ledger().initialize(binding)
        except Study2LedgerError as error:
            raise Study2ExecutionError(error.args[0]) from None

    def send_once(
        self,
        scene_id: str,
        *,
        transport: OpenRouterTransport | None = None,
    ) -> Study2AttemptReceipt:
        """Reserve durably, then make one guarded dispatch; never retry."""

        if scene_id not in SCENE_ORDER:
            raise Study2ExecutionError("SCENE_NOT_APPROVED")
        adapter = transport if transport is not None else OpenRouterTransport()
        if type(adapter) is not OpenRouterTransport:
            raise Study2ExecutionError("OPENROUTER_TRANSPORT_REQUIRED")

        bundle = self._load_frozen_bundle()
        owner_hash, overseer_hash = self._verify_approvals(bundle)
        request, config_hash = self._build_request(bundle, scene_id)
        request_hash = _sha256(_canonical_bytes(request))
        binding = self._ledger_binding(bundle, owner_hash, overseer_hash)
        ledger = Study2Ledger()
        try:
            attempt_number = ledger.reserve(
                binding,
                scene_id=scene_id,
                run_id=self.run_id,
                run_root_relative=self.run_root_relative,
                request_sha256=request_hash,
            )
        except Study2LedgerError as error:
            raise Study2ExecutionError(error.args[0]) from None

        context = _create_reserved_dispatch_context(
            self._transport_owner_token,
            attempt_number=attempt_number,
            scene_id=scene_id,
            run_id=self.run_id,
            request_sha256=request_hash,
            config_sha256=config_hash,
        )
        dispatch_failed = False
        try:
            result = adapter._dispatch_reserved(
                context,
                OPENROUTER_ENDPOINT,
                request,
                bundle.generation_config_bytes,
                owner_token=self._transport_owner_token,
            )
        except Exception:
            dispatch_failed = True
        if dispatch_failed:
            self._complete_failure(
                ledger,
                binding,
                attempt_number,
                scene_id,
                request_hash,
                reason="transport_failure",
                stop_study=True,
            )
            raise Study2ExecutionError("TRANSPORT_FAILED; allocation consumed") from None

        response_path: str | None = None
        response_hash: str | None = None
        if type(result) is Study2TransportResult and type(result.body) is bytes and len(result.body) <= MAX_RESPONSE_BYTES:
            try:
                response_path, response_hash = self._preserve_response(
                    result.body,
                    attempt_number=attempt_number,
                    scene_id=scene_id,
                )
            except Study2ExecutionError:
                self._complete_failure(
                    ledger,
                    binding,
                    attempt_number,
                    scene_id,
                    request_hash,
                    reason="response_persist_failed",
                    stop_study=True,
                    http_status=result.http_status if type(result.http_status) is int else None,
                )
                raise

        failure = self._receipt_failure(result)
        if failure is not None:
            reason, stop_study = failure
            actual_receipt = self._receipt_fields(result)
            try:
                ledger.complete(
                    binding,
                    attempt_number=attempt_number,
                    scene_id=scene_id,
                    run_id=self.run_id,
                    run_root_relative=self.run_root_relative,
                    request_sha256=request_hash,
                    outcome="failed",
                    failure_reason=reason,
                    stop_study=stop_study,
                    http_status=result.http_status if type(result) is Study2TransportResult else None,
                    response_path=response_path,
                    response_sha256=response_hash,
                    returned_model_id=actual_receipt["returned_model_id"],
                    upstream_provider=actual_receipt["upstream_provider"],
                    generation_id=actual_receipt["generation_id"],
                    usage=actual_receipt["usage"],
                )
            except Study2LedgerError as error:
                raise Study2ExecutionError(error.args[0]) from None
            raise Study2ExecutionError(reason.upper() + "; allocation consumed")

        assert type(result) is Study2TransportResult
        assert response_path is not None and response_hash is not None
        try:
            ledger.complete(
                binding,
                attempt_number=attempt_number,
                scene_id=scene_id,
                run_id=self.run_id,
                run_root_relative=self.run_root_relative,
                request_sha256=request_hash,
                outcome="succeeded",
                failure_reason=None,
                stop_study=False,
                http_status=result.http_status,
                response_path=response_path,
                response_sha256=response_hash,
                returned_model_id=result.returned_model_id,
                upstream_provider=result.upstream_provider,
                generation_id=result.generation_id,
                usage=result.usage,
            )
        except Study2LedgerError as error:
            raise Study2ExecutionError(error.args[0]) from None
        return Study2AttemptReceipt(
            study_id=STUDY_ID,
            scene_id=scene_id,
            attempt_number=attempt_number,
            response_path=response_path,
            response_sha256=response_hash,
            returned_model_id=result.returned_model_id,
            upstream_provider=result.upstream_provider,
            generation_id=result.generation_id,
            usage=dict(result.usage or {}),
        )

    def _complete_failure(
        self,
        ledger: Study2Ledger,
        binding: dict[str, Any],
        attempt_number: int,
        scene_id: str,
        request_hash: str,
        *,
        reason: str,
        stop_study: bool,
        http_status: int | None = None,
    ) -> None:
        try:
            ledger.complete(
                binding,
                attempt_number=attempt_number,
                scene_id=scene_id,
                run_id=self.run_id,
                run_root_relative=self.run_root_relative,
                request_sha256=request_hash,
                outcome="failed",
                failure_reason=reason,
                stop_study=stop_study,
                http_status=http_status,
                response_path=None,
                response_sha256=None,
                returned_model_id=None,
                upstream_provider=None,
                generation_id=None,
                usage=None,
            )
        except Study2LedgerError as error:
            raise Study2ExecutionError(error.args[0]) from None

    def _receipt_failure(self, result: object) -> tuple[str, bool] | None:
        if type(result) is not Study2TransportResult:
            return "transport_receipt_invalid", True
        if type(result.body) is not bytes or len(result.body) > MAX_RESPONSE_BYTES:
            return "response_missing_or_oversized", True
        body_model, body_provider, body_generation, body_usage = _extract_response_metadata(result.body)
        if (
            not result.returned_model_id
            or not result.upstream_provider
            or not result.generation_id
            or result.usage is None
        ):
            return "returned_identity_or_usage_missing", True
        if (
            body_model != result.returned_model_id
            or body_provider != result.upstream_provider
            or body_generation != result.generation_id
            or body_usage != result.usage
        ):
            return "receipt_does_not_match_raw_response", True
        if result.returned_model_id != MODEL_ID:
            return "returned_model_mismatch", True
        if type(result.http_status) is not int or not 100 <= result.http_status <= 599:
            return "http_status_invalid", True
        if result.http_status != 200:
            return "http_status_error", True
        return None

    @staticmethod
    def _receipt_fields(result: object) -> dict[str, Any]:
        if type(result) is not Study2TransportResult:
            return {
                "returned_model_id": None,
                "upstream_provider": None,
                "generation_id": None,
                "usage": None,
            }
        return {
            "returned_model_id": result.returned_model_id or None,
            "upstream_provider": result.upstream_provider or None,
            "generation_id": result.generation_id or None,
            "usage": result.usage,
        }

    def _preserve_response(
        self,
        body: bytes,
        *,
        attempt_number: int,
        scene_id: str,
    ) -> tuple[str, str]:
        if type(body) is not bytes or len(body) > MAX_RESPONSE_BYTES:
            raise Study2ExecutionError("response_persist_failed")
        response_root = self.run_dir / "responses"
        _ensure_directory_chain(STUDY2_ROOT, response_root)
        name = "%02d_" % attempt_number + scene_id.replace(":", "__") + ".provider-response.json"
        path = response_root / name
        _verify_path_under(path, STUDY2_ROOT)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags, 0o600)
        except OSError:
            raise Study2ExecutionError("response_persist_failed") from None
        try:
            offset = 0
            while offset < len(body):
                written = os.write(descriptor, body[offset:])
                if written <= 0:
                    raise Study2ExecutionError("response_persist_failed")
                offset += written
            os.fsync(descriptor)
            opened = os.fstat(descriptor)
            named = os.lstat(path)
            if (
                not stat.S_ISREG(opened.st_mode)
                or stat.S_ISLNK(named.st_mode)
                or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)
            ):
                raise Study2ExecutionError("response_persist_failed")
        except OSError:
            raise Study2ExecutionError("response_persist_failed") from None
        finally:
            os.close(descriptor)
        _fsync_directory(response_root)
        relative = path.relative_to(STUDY2_ROOT).as_posix()
        return relative, _sha256(body)

    def _build_request(
        self,
        bundle: _FrozenBundle,
        scene_id: str,
    ) -> tuple[dict[str, Any], str]:
        if scene_id not in SCENE_ORDER:
            raise Study2ExecutionError("SCENE_NOT_APPROVED")
        binding = bundle.scene_bindings.get(scene_id)
        if type(binding) is not FrozenSceneBinding:
            raise Study2ExecutionError("SCENE_BINDING_MISSING")
        scene_record = next(row for row in bundle.manifest["scenes"] if row["scene_id"] == scene_id)
        source_bytes = _read_project_file(scene_record["source_packet"]["path"])
        expected_bytes = _read_project_file(scene_record["expected_bundle"]["path"])
        if (
            _sha256(source_bytes) != scene_record["source_packet"]["sha256"]
            or _sha256(expected_bytes) != scene_record["expected_bundle"]["sha256"]
        ):
            raise Study2ExecutionError("FROZEN_SCENE_INPUT_HASH_MISMATCH")
        schema_bytes = bundle.artifact_bytes["output_schema"]
        system_prompt = _decode_utf8(bundle.artifact_bytes["system_prompt"])
        task_template = _decode_utf8(bundle.artifact_bytes["task_prompt"])
        substitutions = {
            "{{SCENE_ID}}": scene_id,
            "{{INPUT_REFS_JSON}}": _canonical_bytes(binding.input_refs()).decode("ascii"),
            "{{SOURCE_PACKET_JSON}}": source_bytes.decode("utf-8"),
            "{{EXPECTED_BUNDLE_JSON}}": expected_bytes.decode("utf-8"),
            "{{OUTPUT_SCHEMA_JSON}}": schema_bytes.decode("utf-8"),
        }
        for placeholder, value in substitutions.items():
            if task_template.count(placeholder) != 1:
                raise Study2ExecutionError("TASK_PROMPT_PLACEHOLDER_INVALID")
            task_template = task_template.replace(placeholder, value)
        if re.search(r"\{\{[A-Z][A-Z0-9_]*\}\}", task_template):
            raise Study2ExecutionError("TASK_PROMPT_PLACEHOLDER_UNRESOLVED")
        config = bundle.generation_config
        request = {
            "model": MODEL_ID,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": task_template},
            ],
            "temperature": config["temperature"],
            "top_p": config["top_p"],
            "frequency_penalty": config["frequency_penalty"],
            "presence_penalty": config["presence_penalty"],
            "max_tokens": config["max_tokens"],
            "stream": config["stream"],
            "response_format": config["response_format"],
            "tools": config["tools"],
            "tool_choice": config["tool_choice"],
            "provider": config["provider"],
        }
        return request, bundle.artifact_hashes[
            bundle.manifest["artifacts"]["generation_config"]["path"]
        ]

    def _load_frozen_bundle(self) -> _FrozenBundle:
        manifest_relative = STUDY2_PROTOCOL_RELATIVE + "/" + MANIFEST_NAME
        manifest_bytes = _read_project_file(manifest_relative)
        manifest = _parse_json_object(manifest_bytes, "STUDY2_MANIFEST_INVALID")
        if set(manifest) != _MANIFEST_FIELDS:
            raise Study2ExecutionError("STUDY2_MANIFEST_SCHEMA_INVALID")
        if (
            manifest.get("schema") != "neq.llm_staging_study2_manifest.v1"
            or manifest.get("study_id") != STUDY_ID
            or manifest.get("protocol_version") != "neq.llm_staging_study2_delta.v1"
            or manifest.get("status") != "FROZEN_FOR_REVIEW"
            or manifest.get("scene_order") != list(SCENE_ORDER)
            or type(manifest.get("attempt_cap")) is not int
            or manifest.get("attempt_cap") != len(SCENE_ORDER)
            or manifest.get("endpoint") != OPENROUTER_ENDPOINT
            or manifest.get("model_id") != MODEL_ID
        ):
            raise Study2ExecutionError("STUDY2_MANIFEST_BINDING_INVALID")

        artifact_records = manifest.get("artifacts")
        if type(artifact_records) is not dict or set(artifact_records) != set(_ARTIFACT_ROLES):
            raise Study2ExecutionError("STUDY2_MANIFEST_ARTIFACTS_INVALID")
        expected_artifact_paths = _expected_artifact_paths()
        artifact_bytes: dict[str, bytes] = {}
        artifact_hashes: dict[str, str] = {}
        for role in _ARTIFACT_ROLES:
            record = artifact_records[role]
            if type(record) is not dict or set(record) != {"path", "sha256"}:
                raise Study2ExecutionError("STUDY2_MANIFEST_ARTIFACTS_INVALID")
            path = record.get("path")
            digest = record.get("sha256")
            if path != expected_artifact_paths[role] or type(digest) is not str or _SHA256_RE.fullmatch(digest) is None:
                raise Study2ExecutionError("STUDY2_MANIFEST_ARTIFACTS_INVALID")
            contents = _read_project_file(path)
            if _sha256(contents) != digest:
                raise Study2ExecutionError("FROZEN_ARTIFACT_HASH_MISMATCH")
            artifact_bytes[role] = contents
            artifact_hashes[path] = digest

        try:
            bindings = load_frozen_bindings()
        except Exception:
            raise Study2ExecutionError("FROZEN_SCENE_BINDINGS_INVALID") from None
        scene_records = manifest.get("scenes")
        if type(scene_records) is not list or len(scene_records) != len(SCENE_ORDER):
            raise Study2ExecutionError("STUDY2_SCENE_BINDINGS_INVALID")
        if tuple(row.get("scene_id") for row in scene_records if type(row) is dict) != SCENE_ORDER:
            raise Study2ExecutionError("STUDY2_SCENE_BINDINGS_INVALID")
        for row in scene_records:
            if type(row) is not dict or set(row) != {"scene_id", "source_packet", "expected_bundle"}:
                raise Study2ExecutionError("STUDY2_SCENE_BINDINGS_INVALID")
            binding = bindings.get(row.get("scene_id"))
            if type(binding) is not FrozenSceneBinding:
                raise Study2ExecutionError("FROZEN_SCENE_BINDING_MISSING")
            expected_refs = {
                "source_packet": {"path": binding.source_packet.identifier, "sha256": binding.source_packet.sha256},
                "expected_bundle": {"path": binding.expected_bundle.identifier, "sha256": binding.expected_bundle.sha256},
            }
            for reference_name, expected_reference in expected_refs.items():
                reference = row.get(reference_name)
                if type(reference) is not dict or set(reference) != {"path", "sha256"} or reference != expected_reference:
                    raise Study2ExecutionError("STUDY2_SCENE_BINDINGS_INVALID")
                artifact_hashes[reference["path"]] = reference["sha256"]

        availability = manifest.get("availability")
        expected_availability = {
            "raw_listing_path": HISTORICAL_RAW_LISTING_PATH,
            "raw_listing_sha256": HISTORICAL_RAW_LISTING_SHA256,
            "attestation_path": expected_artifact_paths["availability_attestation"],
            "attestation_sha256": artifact_records["availability_attestation"]["sha256"],
        }
        if type(availability) is not dict or set(availability) != set(expected_availability) or availability != expected_availability:
            raise Study2ExecutionError("HISTORICAL_AVAILABILITY_BINDING_INVALID")
        attestation = _parse_json_object(
            artifact_bytes["availability_attestation"],
            "HISTORICAL_AVAILABILITY_ATTESTATION_INVALID",
        )
        if (
            attestation.get("schema") != "neq.openrouter_model_availability.v1"
            or attestation.get("verdict") != "CONFIRMED"
            or attestation.get("requested_model_id") != MODEL_ID
            or attestation.get("raw_listing_sha256") != HISTORICAL_RAW_LISTING_SHA256
            or attestation.get("generation_calls") != 0
            or attestation.get("authenticated") is not False
            or attestation.get("request_count") != 1
        ):
            raise Study2ExecutionError("HISTORICAL_AVAILABILITY_ATTESTATION_INVALID")
        config = _parse_json_object(
            artifact_bytes["generation_config"],
            "GENERATION_CONFIG_INVALID",
        )
        try:
            config = _validate_generation_config(config)
        except Study2TransportError as error:
            raise Study2ExecutionError(error.args[0]) from None
        if not _decode_utf8(artifact_bytes["system_prompt"]).strip() or not _decode_utf8(artifact_bytes["task_prompt"]).strip():
            raise Study2ExecutionError("FROZEN_PROMPT_EMPTY")

        return _FrozenBundle(
            manifest=manifest,
            manifest_bytes=manifest_bytes,
            manifest_sha256=_sha256(manifest_bytes),
            artifact_bytes=artifact_bytes,
            artifact_hashes=artifact_hashes,
            scene_bindings=dict(bindings),
            generation_config=config,
            generation_config_bytes=artifact_bytes["generation_config"],
            availability_attestation_sha256=artifact_records["availability_attestation"]["sha256"],
        )

    def _verify_approvals(self, bundle: _FrozenBundle) -> tuple[str, str]:
        pins = self.approval_pins
        if type(pins) is not ApprovalPins:
            raise Study2ExecutionError("EXTERNAL_APPROVAL_PINS_REQUIRED")
        if (
            type(pins.owner_approval_sha256) is not str
            or _SHA256_RE.fullmatch(pins.owner_approval_sha256) is None
            or type(pins.overseer_approval_sha256) is not str
            or _SHA256_RE.fullmatch(pins.overseer_approval_sha256) is None
            or type(pins.authority_record_id) is not str
            or _AUTHORITY_ID_RE.fullmatch(pins.authority_record_id) is None
            or pins.authority_record_id == PREPARATION_ONLY_AUTHORITY_ID
        ):
            raise Study2ExecutionError("EXTERNAL_APPROVAL_PINS_INVALID")
        owner_path = STUDY2_ROOT / "owner-cap-approval.json"
        overseer_path = STUDY2_ROOT / "overseer-step-a-approval.json"
        owner_bytes = _read_runtime_file(owner_path, STUDY2_ROOT)
        overseer_bytes = _read_runtime_file(overseer_path, STUDY2_ROOT)
        owner_hash = _sha256(owner_bytes)
        overseer_hash = _sha256(overseer_bytes)
        if owner_hash != pins.owner_approval_sha256 or overseer_hash != pins.overseer_approval_sha256:
            raise Study2ExecutionError("EXTERNAL_APPROVAL_HASH_MISMATCH")
        owner = _parse_json_object(owner_bytes, "OWNER_APPROVAL_INVALID")
        overseer = _parse_json_object(overseer_bytes, "OVERSEER_APPROVAL_INVALID")
        if set(owner) != _APPROVAL_FIELDS or set(overseer) != _APPROVAL_FIELDS:
            raise Study2ExecutionError("APPROVAL_SCHEMA_INVALID")
        common_expected = {
            "study_id": STUDY_ID,
            "attempt_cap": len(SCENE_ORDER),
            "model_id": MODEL_ID,
            "endpoint": OPENROUTER_ENDPOINT,
            "manifest_sha256": bundle.manifest_sha256,
            "protocol_version": bundle.manifest["protocol_version"],
            "protocol_sha256": bundle.manifest["artifacts"]["protocol"]["sha256"],
            "availability_attestation_sha256": bundle.availability_attestation_sha256,
            "availability_raw_listing_sha256": HISTORICAL_RAW_LISTING_SHA256,
            "scene_order": list(SCENE_ORDER),
            "study_root_relative": STUDY2_ROOT_RELATIVE,
            "authority_record_id": pins.authority_record_id,
        }
        if any(owner.get(key) != value or overseer.get(key) != value for key, value in common_expected.items()):
            raise Study2ExecutionError("APPROVAL_BINDING_MISMATCH")
        if (
            owner.get("schema") != "neq.llm_staging_study2_owner_cap_approval.v1"
            or owner.get("status") != "APPROVED_STUDY2_CAP"
            or owner.get("review_status") != "OWNER_APPROVED"
            or overseer.get("schema") != "neq.llm_staging_study2_overseer_step_a_approval.v1"
            or overseer.get("status") != "APPROVED_STEP_A"
            or overseer.get("review_status") != "PASS"
            or not _valid_approver(owner.get("approved_by"))
            or overseer.get("approved_by") != "overseer"
            or not _valid_approver(overseer.get("approved_by"))
            or not _valid_timestamp(owner.get("approved_at_utc"))
            or not _valid_timestamp(overseer.get("approved_at_utc"))
        ):
            raise Study2ExecutionError("APPROVAL_STATUS_INVALID")
        return owner_hash, overseer_hash

    def _ledger_binding(
        self,
        bundle: _FrozenBundle,
        owner_hash: str,
        overseer_hash: str,
    ) -> dict[str, Any]:
        authority_id = self.approval_pins.authority_record_id if self.approval_pins is not None else ""
        return {
            "study_id": STUDY_ID,
            "manifest_sha256": bundle.manifest_sha256,
            "protocol_version": bundle.manifest["protocol_version"],
            "protocol_sha256": bundle.manifest["artifacts"]["protocol"]["sha256"],
            "artifact_hashes": dict(sorted(bundle.artifact_hashes.items())),
            "model_id": MODEL_ID,
            "endpoint": OPENROUTER_ENDPOINT,
            "availability_attestation_sha256": bundle.availability_attestation_sha256,
            "availability_raw_listing_sha256": HISTORICAL_RAW_LISTING_SHA256,
            "owner_approval_sha256": owner_hash,
            "overseer_approval_sha256": overseer_hash,
            "authority_record_id": authority_id,
            "study_root_relative": STUDY2_ROOT_RELATIVE,
        }


def _expected_artifact_paths() -> dict[str, str]:
    return {
        "protocol": STUDY2_PROTOCOL_RELATIVE + "/protocol.md",
        "input_bindings": STUDY2_PROTOCOL_RELATIVE + "/input-bindings.json",
        "output_schema": STUDY2_PROTOCOL_RELATIVE + "/output-contract.schema.json",
        "system_prompt": STUDY2_PROTOCOL_RELATIVE + "/system-prompt.txt",
        "task_prompt": STUDY2_PROTOCOL_RELATIVE + "/task-prompt.txt",
        "generation_config": STUDY2_PROTOCOL_RELATIVE + "/generation-config.json",
        "availability_attestation": STUDY1_PROTOCOL_RELATIVE + "/availability-check.json",
    }


def _read_project_file(relative_path: object) -> bytes:
    if type(relative_path) is not str:
        raise Study2ExecutionError("FROZEN_PATH_INVALID")
    try:
        pure = PurePosixPath(relative_path)
        if pure.is_absolute() or not pure.parts or any(part in ("", ".", "..") for part in pure.parts):
            raise Study2ExecutionError("FROZEN_PATH_INVALID")
        candidate = REPO_ROOT.joinpath(*pure.parts)
        _verify_path_under(candidate, REPO_ROOT)
        metadata = candidate.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_FROZEN_FILE_BYTES:
            raise Study2ExecutionError("FROZEN_FILE_INVALID")
        return candidate.read_bytes()
    except Study2ExecutionError:
        raise
    except OSError:
        raise Study2ExecutionError("FROZEN_FILE_UNAVAILABLE") from None


def _read_runtime_file(path: Path, root: Path) -> bytes:
    _verify_path_under(path, root)
    try:
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode) or metadata.st_size > 64 * 1024:
            raise Study2ExecutionError("APPROVAL_FILE_INVALID")
        return path.read_bytes()
    except Study2ExecutionError:
        raise
    except OSError:
        raise Study2ExecutionError("REQUIRED_APPROVAL_MISSING") from None


def _verify_path_under(path: Path, root: Path) -> None:
    try:
        repo_root = Path(__file__).resolve().parents[3]
        root_resolved = Path(os.path.abspath(root))
        candidate = Path(os.path.abspath(path))
        root_relative = root_resolved.relative_to(repo_root)
        relative = candidate.relative_to(root_resolved)
        current = repo_root
        for part in (*root_relative.parts, *relative.parts):
            current = current / part
            try:
                metadata = current.lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(metadata.st_mode):
                raise Study2ExecutionError("UNSAFE_PATH")
        candidate.resolve(strict=False).relative_to(root_resolved.resolve(strict=False))
    except Study2ExecutionError:
        raise
    except (OSError, ValueError):
        raise Study2ExecutionError("PATH_ESCAPE") from None


def _ensure_directory_chain(root: Path, target: Path) -> None:
    _verify_path_under(target, root)
    try:
        root_resolved = Path(os.path.abspath(root))
        relative = Path(os.path.abspath(target)).relative_to(root_resolved)
        current = root_resolved
        for part in relative.parts:
            current = current / part
            try:
                metadata = current.lstat()
            except FileNotFoundError:
                current.mkdir(mode=0o700)
                metadata = current.lstat()
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                raise Study2ExecutionError("UNSAFE_PATH")
    except Study2ExecutionError:
        raise
    except OSError:
        raise Study2ExecutionError("RUN_DIRECTORY_UNAVAILABLE") from None


def _fsync_directory(path: Path) -> None:
    descriptor = -1
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        os.fsync(descriptor)
    except OSError:
        raise Study2ExecutionError("RESPONSE_DIRECTORY_SYNC_FAILED") from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _parse_json_object(contents: bytes, error_code: str) -> dict[str, Any]:
    try:
        value = json.loads(
            contents.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_float=_parse_finite_float,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError):
        raise Study2ExecutionError(error_code) from None
    if type(value) is not dict:
        raise Study2ExecutionError(error_code)
    return value


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate key")
        value[key] = item
    return value


def _reject_constant(value: str) -> None:
    raise ValueError("non-finite JSON constant")


def _parse_finite_float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("non-finite JSON number")
    return result


def _decode_utf8(value: bytes) -> str:
    try:
        return value.decode("utf-8")
    except UnicodeDecodeError:
        raise Study2ExecutionError("FROZEN_TEXT_INVALID") from None


def _valid_approver(value: object) -> bool:
    return (
        type(value) is str
        and 1 <= len(value) <= 128
        and value.isascii()
        and not any(ord(character) < 32 or ord(character) == 127 for character in value)
    )


def _valid_timestamp(value: object) -> bool:
    return type(value) is str and re.fullmatch(r"20[0-9]{2}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z", value) is not None


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
    except (TypeError, ValueError, RecursionError):
        raise Study2ExecutionError("REQUEST_JSON_INVALID") from None


def _sha256(contents: bytes) -> str:
    return hashlib.sha256(contents).hexdigest()


__all__ = [
    "ApprovalPins",
    "Study2AttemptReceipt",
    "Study2Client",
    "Study2ExecutionError",
    "Study2TransportResult",
]
