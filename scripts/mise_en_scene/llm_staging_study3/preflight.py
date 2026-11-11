# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Synthetic approval/accounting checks and the exact-SHA readiness CLI.

The reusable functions validate synthetic in-memory snapshots only: they do
not create a ledger, reserve an attempt, load credentials, or send HTTP. The
explicit ``--exact-sha-readiness`` CLI delegates to readiness.py, which reports
a fail-closed provenance blocker before GitHub CLI, credentials, or local
preflight gates are touched. Synthetic decisions and the CLI result are
metadata, never a dispatch token.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
import sys
from typing import Any

from . import protocol
from .newrequest import build_request, request_transport_metadata
from .sizing import (
    HARD_CEILING_USD,
    SizingBlocked,
    _fresh_preflight_sizing_report,
    validate_actual_cost_accounting,
)


STUDY3_ROOT_RELATIVE = (
    "tmp/router-rollout/mapping-pilot/mise-en-scene-offline/llm-staging-study3"
)
LEDGER_SCHEMA = "neq.llm_staging_study3_synthetic_ledger.v1"
ACCOUNTING_SCHEMA = "neq.llm_staging_study3_synthetic_actual_accounting.v1"
STANDING_AUTHORITY_RULING_ID = "neq-standing-authority-20261110"
CAP_APPROVAL_RULING_ID = "neq-study3-pre-approved-20261110"
_ZERO_HASH = "0" * 64
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_IDENTITY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_UPSTREAM_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._/-]{0,127}$")
_MAX_RECORD_BYTES = 131072
_MAX_RULING_BYTES = 262144
_USAGE_FIELDS = ("prompt_tokens", "completion_tokens", "reasoning_tokens")


class PreflightBlocked(ValueError):
    """A metadata-only, fail-closed synthetic preflight refusal."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ApprovalPins:
    """Host-supplied immutable expectations, never derived from evidence JSON."""

    study_id: str
    manifest_sha256: str
    generation_config_sha256: str
    standing_authority_ruling_id: str
    standing_authority_sha256: str
    cap_approval_ruling_id: str
    cap_approval_sha256: str
    cap_envelope_sha256: str


@dataclass(frozen=True)
class DispatchPins:
    """Separate host pins for post-review READY and explicit dispatch authority."""

    study_id: str
    manifest_sha256: str
    generation_config_sha256: str
    cap_approval_sha256: str
    readiness_ruling_id: str
    readiness_sha256: str
    dispatch_ruling_id: str
    dispatch_sha256: str


@dataclass(frozen=True)
class SyntheticLedgerSnapshot:
    """In-memory fixture only; its chain is structural, not storage authority."""

    records: tuple[bytes, ...]
    actual_accounting: bytes | None = None


@dataclass(frozen=True)
class PreflightDecision:
    """Metadata-only result; deliberately carries no callable dispatch capability."""

    status: str
    study_id: str
    scene_id: str
    next_attempt_number: int
    consumed_slots: int
    remaining_slots: int
    conservative_cost_usd_estimate: str
    actual_cost_usd: str
    manifest_sha256: str
    generation_config_sha256: str
    cap_approval_ruling_id: str
    standing_authority_sha256: str
    cap_approval_sha256: str
    cap_envelope_sha256: str
    readiness_ruling_id: str
    readiness_sha256: str
    dispatch_ruling_id: str
    dispatch_sha256: str
    synthetic_only: bool = True
    reservation_created: bool = False
    credentials_loaded: bool = False
    http_sent: bool = False
    live_dispatch_permitted: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Return bounded decision metadata only, never request or response content."""

        return {
            "status": self.status,
            "study_id": self.study_id,
            "scene_id": self.scene_id,
            "next_attempt_number": self.next_attempt_number,
            "consumed_slots": self.consumed_slots,
            "remaining_slots": self.remaining_slots,
            "conservative_cost_usd_estimate": self.conservative_cost_usd_estimate,
            "actual_cost_usd": self.actual_cost_usd,
            "manifest_sha256": self.manifest_sha256,
            "generation_config_sha256": self.generation_config_sha256,
            "cap_approval_ruling_id": self.cap_approval_ruling_id,
            "standing_authority_sha256": self.standing_authority_sha256,
            "cap_approval_sha256": self.cap_approval_sha256,
            "cap_envelope_sha256": self.cap_envelope_sha256,
            "readiness_ruling_id": self.readiness_ruling_id,
            "readiness_sha256": self.readiness_sha256,
            "dispatch_ruling_id": self.dispatch_ruling_id,
            "dispatch_sha256": self.dispatch_sha256,
            "synthetic_only": self.synthetic_only,
            "reservation_created": self.reservation_created,
            "credentials_loaded": self.credentials_loaded,
            "http_sent": self.http_sent,
            "live_dispatch_permitted": self.live_dispatch_permitted,
        }


@dataclass(frozen=True)
class ProviderIdentity:
    """Verified response identity and scope; no model-generated content is retained."""

    study_id: str
    scene_id: str
    attempt_number: int
    response_sha256: str
    returned_model_id: str
    upstream_provider: str
    generation_id: str


@dataclass(frozen=True)
class OutcomeDecision:
    """Outcome classification for an already-consumed reservation."""

    classification: str
    attempt_consumed: bool
    stop_study: bool
    next_scene_allowed: bool
    remaining_attempts_unspent: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "classification": self.classification,
            "attempt_consumed": self.attempt_consumed,
            "stop_study": self.stop_study,
            "next_scene_allowed": self.next_scene_allowed,
            "remaining_attempts_unspent": self.remaining_attempts_unspent,
        }


def synthetic_preflight(
    *,
    scene_id: object,
    approval_pins: object,
    standing_authority_source: object,
    cap_approval_source: object,
    cap_envelope_record: object,
    dispatch_pins: object,
    readiness_record: object,
    dispatch_authorization_record: object,
    manifest_bytes: object,
    ledger_snapshot: object,
) -> PreflightDecision:
    """Validate synthetic in-memory approval and state before any possible effect.

    Approval source documents are opaque hash-bound bytes. The separately pinned
    envelope record supplies typed identity and cap fields. Both the cap approval
    and post-review READY/dispatch records must have independently supplied pins.
    """

    verified_approval = _verify_approval(
        approval_pins,
        standing_authority_source,
        cap_approval_source,
        cap_envelope_record,
        manifest_bytes,
    )
    verified_dispatch = _verify_dispatch_authority(
        verified_approval,
        dispatch_pins,
        readiness_record,
        dispatch_authorization_record,
    )
    config_sha256 = _verify_fixed_generation_envelope(verified_approval)
    try:
        sizing_report, full_conservative_cost = _fresh_preflight_sizing_report()
    except SizingBlocked as error:
        raise PreflightBlocked("SIZING_UNPRICED_OR_UNSAFE") from error
    if full_conservative_cost >= HARD_CEILING_USD:
        raise PreflightBlocked("CONSERVATIVE_COST_REACHES_HARD_CEILING")

    consumed, actual_cost = _validate_ledger_snapshot(
        ledger_snapshot,
        verified_approval,
        verified_dispatch,
        config_sha256,
        scene_id,
    )
    remaining_conservative = sum(
        (
            Decimal(row["conservative_cost_usd_estimate"])
            for row in sizing_report["scenes"][consumed:]
        ),
        Decimal(0),
    )
    projected_cost = actual_cost + remaining_conservative
    if projected_cost >= HARD_CEILING_USD:
        raise PreflightBlocked("PROJECTED_COST_REACHES_HARD_CEILING")
    next_attempt = consumed + 1
    return PreflightDecision(
        status="SYNTHETIC_PREFLIGHT_ACCEPTED",
        study_id=protocol.STUDY_ID,
        scene_id=scene_id,
        next_attempt_number=next_attempt,
        consumed_slots=consumed,
        remaining_slots=len(protocol.SCENE_ORDER) - consumed,
        conservative_cost_usd_estimate=str(projected_cost),
        actual_cost_usd=str(actual_cost),
        manifest_sha256=verified_approval.manifest_sha256,
        generation_config_sha256=config_sha256,
        cap_approval_ruling_id=verified_approval.cap_approval_ruling_id,
        standing_authority_sha256=verified_approval.standing_authority_sha256,
        cap_approval_sha256=verified_approval.cap_approval_sha256,
        cap_envelope_sha256=verified_approval.cap_envelope_sha256,
        readiness_ruling_id=verified_dispatch.readiness_ruling_id,
        readiness_sha256=verified_dispatch.readiness_sha256,
        dispatch_ruling_id=verified_dispatch.dispatch_ruling_id,
        dispatch_sha256=verified_dispatch.dispatch_sha256,
    )


def classify_attempt_outcome(
    *,
    attempt_number: object,
    scene_id: object,
    http_status: object,
    transport_error: object,
    provider_identity: object,
    output_status: object,
) -> OutcomeDecision:
    """Classify one already-reserved attempt without inspecting output prose."""

    if (
        type(attempt_number) is not int
        or not 1 <= attempt_number <= len(protocol.SCENE_ORDER)
        or type(scene_id) is not str
        or scene_id != protocol.SCENE_ORDER[attempt_number - 1]
        or type(transport_error) is not bool
    ):
        raise PreflightBlocked("OUTCOME_SCOPE_INVALID")
    remaining = len(protocol.SCENE_ORDER) - attempt_number
    if transport_error:
        return _stopped_outcome("STOP_TRANSPORT_FAILURE", remaining)
    if type(http_status) is not int or not 100 <= http_status <= 599:
        return _stopped_outcome("STOP_HTTP_STATUS_INVALID", remaining)
    if http_status != 200:
        return _stopped_outcome("STOP_NON_200", remaining)
    if not _valid_provider_identity(provider_identity, scene_id, attempt_number):
        return _stopped_outcome("STOP_IDENTITY_FAILURE", remaining)
    if output_status == "PASS":
        classification = "ACCEPTED"
    else:
        classification = "CONTRACT_FAILURE"
    return OutcomeDecision(
        classification=classification,
        attempt_consumed=True,
        stop_study=False,
        next_scene_allowed=remaining > 0,
        remaining_attempts_unspent=remaining,
    )


def _stopped_outcome(classification: str, remaining: int) -> OutcomeDecision:
    return OutcomeDecision(
        classification=classification,
        attempt_consumed=True,
        stop_study=True,
        next_scene_allowed=False,
        remaining_attempts_unspent=remaining,
    )


def _valid_provider_identity(
    value: object, scene_id: str, attempt_number: int
) -> bool:
    if type(value) is not ProviderIdentity:
        return False
    provider = value.upstream_provider
    return (
        value.study_id == protocol.STUDY_ID
        and value.scene_id == scene_id
        and type(value.attempt_number) is int
        and value.attempt_number == attempt_number
        and type(value.response_sha256) is str
        and _SHA256_RE.fullmatch(value.response_sha256) is not None
        and value.returned_model_id == protocol.MODEL_ID
        and type(provider) is str
        and _UPSTREAM_RE.fullmatch(provider) is not None
        and provider.casefold() not in {"unknown", "none", "n/a", "unset"}
        and type(value.generation_id) is str
        and _IDENTITY_RE.fullmatch(value.generation_id) is not None
    )


def _verify_approval(
    pins: object,
    standing_authority_source: object,
    cap_approval_source: object,
    cap_envelope_record: object,
    manifest_bytes: object,
) -> ApprovalPins:
    if type(pins) is not ApprovalPins:
        raise PreflightBlocked("TRUSTED_APPROVAL_PINS_REQUIRED")
    if (
        pins.study_id != protocol.STUDY_ID
        or pins.manifest_sha256 != protocol.STUDY3_MANIFEST_SHA256
        or pins.standing_authority_ruling_id != STANDING_AUTHORITY_RULING_ID
        or pins.cap_approval_ruling_id != CAP_APPROVAL_RULING_ID
        or any(
            type(value) is not str or _SHA256_RE.fullmatch(value) is None
            for value in (
                pins.manifest_sha256,
                pins.generation_config_sha256,
                pins.standing_authority_sha256,
                pins.cap_approval_sha256,
                pins.cap_envelope_sha256,
            )
        )
    ):
        raise PreflightBlocked("APPROVAL_PIN_IDENTITY_MISMATCH")

    standing_hash = _verify_source_bytes(
        standing_authority_source,
        pins.standing_authority_sha256,
        STANDING_AUTHORITY_RULING_ID,
    )
    cap_hash = _verify_source_bytes(
        cap_approval_source,
        pins.cap_approval_sha256,
        CAP_APPROVAL_RULING_ID,
    )
    if STANDING_AUTHORITY_RULING_ID.encode("ascii") not in cap_approval_source:
        raise PreflightBlocked("CAP_APPROVAL_STANDING_AUTHORITY_REFERENCE_MISSING")
    if (
        type(manifest_bytes) is not bytes
        or hashlib.sha256(manifest_bytes).hexdigest() != pins.manifest_sha256
    ):
        raise PreflightBlocked("MANIFEST_PIN_MISMATCH")
    manifest = _parse_json(manifest_bytes, "MANIFEST_INVALID", require_canonical=False)
    if (
        type(manifest) is not dict
        or manifest.get("study_id") != protocol.STUDY_ID
        or manifest.get("scene_order") != list(protocol.SCENE_ORDER)
    ):
        raise PreflightBlocked("MANIFEST_BINDING_MISMATCH")
    envelope = _parse_canonical_object(cap_envelope_record, "CAP_ENVELOPE_INVALID")
    expected_envelope = _approved_cap_envelope(
        pins,
        standing_hash=standing_hash,
        cap_hash=cap_hash,
    )
    if (
        hashlib.sha256(cap_envelope_record).hexdigest() != pins.cap_envelope_sha256
        or _canonical_json(envelope) != _canonical_json(expected_envelope)
    ):
        raise PreflightBlocked("CAP_ENVELOPE_PIN_OR_FIELDS_MISMATCH")
    return pins


def _verify_source_bytes(value: object, expected_sha256: str, ruling_id: str) -> str:
    if (
        type(value) is not bytes
        or not 1 <= len(value) <= _MAX_RULING_BYTES
        or hashlib.sha256(value).hexdigest() != expected_sha256
        or ruling_id.encode("ascii") not in value
    ):
        raise PreflightBlocked("APPROVAL_SOURCE_HASH_OR_RULING_ID_MISMATCH")
    return expected_sha256


def _approved_cap_envelope(
    pins: ApprovalPins, *, standing_hash: str, cap_hash: str
) -> dict[str, Any]:
    return {
        "schema": "neq.llm_staging_study3_cap_approval_binding.v1",
        "standing_authority_ruling_id": STANDING_AUTHORITY_RULING_ID,
        "standing_authority_source_sha256": standing_hash,
        "cap_approval_ruling_id": CAP_APPROVAL_RULING_ID,
        "cap_approval_source_sha256": cap_hash,
        "study_id": protocol.STUDY_ID,
        "manifest_sha256": pins.manifest_sha256,
        "generation_config_sha256": pins.generation_config_sha256,
        "approved_by_role": "overseer",
        "acting_for": "owner",
        "attempt_cap": 3,
        "attempts_per_scene": 1,
        "scene_order": list(protocol.SCENE_ORDER),
        "provider": "openrouter",
        "endpoint": "https://openrouter.ai/api/v1/chat/completions",
        "model_id": "openai/gpt-6-luna",
        "allow_fallbacks": False,
        "retries": 0,
        "reruns": 0,
        "tools": [],
        "redirects": False,
        "streaming": False,
        "continuation": False,
        "temperature": 1.0,
        "top_p": 1.0,
        "frequency_penalty": 0.0,
        "presence_penalty": 0.0,
        "max_tokens": 16384,
        "response_format": {"type": "json_object"},
        "timeout_seconds": 720,
        "tool_choice": "none",
        "expected_cost_usd_approx": "0.01",
        "conservative_cost_usd_approx": "0.03",
        "hard_ceiling_usd": "0.05",
        "approval_kind": "CAP_ONLY_NOT_READINESS_OR_DISPATCH",
    }


def _verify_dispatch_authority(
    approval_pins: ApprovalPins,
    pins: object,
    readiness_record: object,
    dispatch_authorization_record: object,
) -> DispatchPins:
    if type(pins) is not DispatchPins:
        raise PreflightBlocked("POST_REVIEW_READY_AND_DISPATCH_PINS_REQUIRED")
    if (
        pins.study_id != protocol.STUDY_ID
        or pins.manifest_sha256 != approval_pins.manifest_sha256
        or pins.generation_config_sha256 != approval_pins.generation_config_sha256
        or pins.cap_approval_sha256 != approval_pins.cap_approval_sha256
        or not _valid_ruling_id(pins.readiness_ruling_id)
        or not _valid_ruling_id(pins.dispatch_ruling_id)
        or any(
            type(value) is not str or _SHA256_RE.fullmatch(value) is None
            for value in (
                pins.readiness_sha256,
                pins.dispatch_sha256,
                pins.manifest_sha256,
                pins.generation_config_sha256,
                pins.cap_approval_sha256,
            )
        )
    ):
        raise PreflightBlocked("POST_REVIEW_PIN_BINDING_MISMATCH")
    readiness = _parse_canonical_object(readiness_record, "READINESS_RECORD_INVALID")
    dispatch = _parse_canonical_object(
        dispatch_authorization_record, "DISPATCH_RECORD_INVALID"
    )
    if hashlib.sha256(readiness_record).hexdigest() != pins.readiness_sha256:
        raise PreflightBlocked("READINESS_RECORD_HASH_MISMATCH")
    if hashlib.sha256(dispatch_authorization_record).hexdigest() != pins.dispatch_sha256:
        raise PreflightBlocked("DISPATCH_RECORD_HASH_MISMATCH")
    expected_readiness = {
        "schema": "neq.llm_staging_study3_synthetic_software_readiness.v1",
        "ruling_id": pins.readiness_ruling_id,
        "study_id": protocol.STUDY_ID,
        "manifest_sha256": approval_pins.manifest_sha256,
        "generation_config_sha256": approval_pins.generation_config_sha256,
        "cap_approval_ruling_id": approval_pins.cap_approval_ruling_id,
        "cap_approval_sha256": approval_pins.cap_approval_sha256,
        "reviewed_by_role": "overseer",
        "software_preparation_review": "APPROVED",
        "software_preparation_readiness": "READY",
    }
    expected_dispatch = {
        "schema": "neq.llm_staging_study3_synthetic_dispatch_authorization.v1",
        "ruling_id": pins.dispatch_ruling_id,
        "study_id": protocol.STUDY_ID,
        "manifest_sha256": approval_pins.manifest_sha256,
        "generation_config_sha256": approval_pins.generation_config_sha256,
        "cap_approval_ruling_id": approval_pins.cap_approval_ruling_id,
        "cap_approval_sha256": approval_pins.cap_approval_sha256,
        "readiness_ruling_id": pins.readiness_ruling_id,
        "readiness_sha256": pins.readiness_sha256,
        "authorized_by_role": "overseer",
        "authorized_action": "DISPATCH_STUDY3",
        "attempt_cap": 3,
        "scene_order": list(protocol.SCENE_ORDER),
    }
    if (
        _canonical_json(readiness) != _canonical_json(expected_readiness)
        or _canonical_json(dispatch) != _canonical_json(expected_dispatch)
    ):
        raise PreflightBlocked("POST_REVIEW_READY_OR_DISPATCH_FIELDS_MISMATCH")
    return pins


def _valid_ruling_id(value: object) -> bool:
    return (
        type(value) is str
        and len(value) <= 128
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]*", value) is not None
    )


def _verify_fixed_generation_envelope(pins: ApprovalPins) -> str:
    for scene_id in protocol.SCENE_ORDER:
        try:
            metadata = request_transport_metadata(scene_id)
            request = build_request(scene_id)
        except (OSError, ValueError, KeyError, TypeError):
            raise PreflightBlocked("GENERATION_ENVELOPE_UNAVAILABLE") from None
        if (
            metadata.get("study_id") != protocol.STUDY_ID
            or metadata.get("provider") != "openrouter"
            or metadata.get("endpoint") != "https://openrouter.ai/api/v1/chat/completions"
            or type(metadata.get("timeout_seconds")) is not int
            or metadata["timeout_seconds"] != 720
            or metadata.get("transport_constraints")
            != {"retries": 0, "reruns": 0, "redirects": False, "continuation": False}
            or metadata.get("attempt_cap_identity") != protocol.STUDY_ID
            or type(metadata.get("attempt_cap")) is not int
            or metadata["attempt_cap"] != 3
            or type(metadata.get("attempts_per_scene")) is not int
            or metadata["attempts_per_scene"] != 1
            or metadata.get("scene_order") != protocol.SCENE_ORDER
            or metadata.get("generation_config_sha256")
            != pins.generation_config_sha256
            or request.get("model") != protocol.MODEL_ID
            or type(request.get("temperature")) is not float
            or request["temperature"] != 1.0
            or type(request.get("top_p")) is not float
            or request["top_p"] != 1.0
            or type(request.get("frequency_penalty")) is not float
            or request["frequency_penalty"] != 0.0
            or type(request.get("presence_penalty")) is not float
            or request["presence_penalty"] != 0.0
            or type(request.get("max_tokens")) is not int
            or request["max_tokens"] != 16384
            or request.get("provider") != {"allow_fallbacks": False}
            or request.get("stream") is not False
            or request.get("response_format") != {"type": "json_object"}
            or request.get("tools") != []
            or request.get("tool_choice") != "none"
        ):
            raise PreflightBlocked("GENERATION_ENVELOPE_PIN_OR_FIELDS_MISMATCH")
    return pins.generation_config_sha256


def _validate_ledger_snapshot(
    value: object,
    approval_pins: ApprovalPins,
    dispatch_pins: DispatchPins,
    config_sha256: str,
    scene_id: object,
) -> tuple[int, Decimal]:
    if type(value) is not SyntheticLedgerSnapshot:
        raise PreflightBlocked("SYNTHETIC_LEDGER_STATE_MISSING")
    payloads = _parse_hash_chain(value.records)
    expected_header = _ledger_header(approval_pins, dispatch_pins, config_sha256)
    if _canonical_json(payloads[0]) != _canonical_json(expected_header):
        raise PreflightBlocked("SYNTHETIC_LEDGER_HEADER_MISMATCH")

    reservations: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    pending: dict[str, Any] | None = None
    stopped = False
    for payload in payloads[1:]:
        if type(payload) is not dict or payload.get("study_id") != protocol.STUDY_ID:
            raise PreflightBlocked("SYNTHETIC_LEDGER_CORRUPT")
        event = payload.get("event")
        if event == "reservation":
            if pending is not None or stopped:
                raise PreflightBlocked("SYNTHETIC_LEDGER_CORRUPT")
            expected_number = len(reservations) + 1
            if expected_number > len(protocol.SCENE_ORDER):
                raise PreflightBlocked("SYNTHETIC_LEDGER_CAP_EXCEEDED")
            expected_fields = {
                "event", "study_id", "attempt_number", "scene_id", "run_id"
            }
            if (
                set(payload) != expected_fields
                or type(payload.get("attempt_number")) is not int
                or payload["attempt_number"] != expected_number
                or payload.get("scene_id") != protocol.SCENE_ORDER[expected_number - 1]
                or not _valid_run_id(payload.get("run_id"))
            ):
                raise PreflightBlocked("SYNTHETIC_LEDGER_SCENE_OR_RUN_MISMATCH")
            reservations.append(payload)
            pending = payload
            continue
        if event != "result" or pending is None:
            raise PreflightBlocked("SYNTHETIC_LEDGER_CORRUPT")
        result_fields = {
            "event", "study_id", "attempt_number", "scene_id", "run_id",
            "outcome", "stop_study", "receipt",
        }
        if (
            set(payload) != result_fields
            or type(payload.get("attempt_number")) is not int
            or payload.get("attempt_number") != pending["attempt_number"]
            or payload.get("scene_id") != pending["scene_id"]
            or payload.get("run_id") != pending["run_id"]
            or type(payload.get("stop_study")) is not bool
            or payload.get("outcome") not in {"ACCEPTED", "CONTRACT_FAILURE", "STOPPED"}
        ):
            raise PreflightBlocked("SYNTHETIC_LEDGER_RESULT_MISMATCH")
        outcome = payload["outcome"]
        if (outcome == "STOPPED") != payload["stop_study"]:
            raise PreflightBlocked("SYNTHETIC_LEDGER_RESULT_MISMATCH")
        receipt = payload.get("receipt")
        if outcome in {"ACCEPTED", "CONTRACT_FAILURE"}:
            _validate_receipt(receipt, pending)
        elif receipt is not None:
            _validate_receipt(receipt, pending)
        results.append(payload)
        stopped = outcome == "STOPPED"
        pending = None

    if pending is not None:
        raise PreflightBlocked("SYNTHETIC_LEDGER_PENDING_RESERVATION")
    if stopped:
        raise PreflightBlocked("SYNTHETIC_LEDGER_STUDY_STOPPED")
    consumed = len(reservations)
    if type(scene_id) is not str or scene_id not in protocol.SCENE_ORDER:
        raise PreflightBlocked("SCENE_NOT_APPROVED")
    if consumed < len(protocol.SCENE_ORDER) and scene_id != protocol.SCENE_ORDER[consumed]:
        raise PreflightBlocked("SCENE_ORDER_OR_REPEAT_MISMATCH")

    if not results:
        if value.actual_accounting is not None:
            raise PreflightBlocked("ACCOUNTING_PRESENT_WITHOUT_COMPLETED_ATTEMPTS")
        if consumed >= len(protocol.SCENE_ORDER):
            raise PreflightBlocked("SYNTHETIC_LEDGER_CAP_EXHAUSTED")
        return consumed, Decimal(0)
    accounting = _parse_canonical_object(
        value.actual_accounting, "ACTUAL_COST_STOP_MISSING_OR_PENDING"
    )
    expected_receipts = [row["receipt"] for row in results]
    expected_simplified = [
        {
            "receipt_id": row["generation_id"],
            "cost_usd": row["cost_usd"],
            "prompt_tokens": row["prompt_tokens"],
            "completion_tokens": row["completion_tokens"],
            "reasoning_tokens": row["reasoning_tokens"],
        }
        for row in expected_receipts
    ]
    accounting_fields = {
        "schema", "status", "study_id", "accounted_attempt_count", "attempt_cap",
        "scene_ids", "receipts", "reported_total_usd",
    }
    if (
        set(accounting) != accounting_fields
        or accounting.get("schema") != ACCOUNTING_SCHEMA
        or accounting.get("status") != "COMPLETE"
        or accounting.get("study_id") != protocol.STUDY_ID
        or type(accounting.get("accounted_attempt_count")) is not int
        or accounting["accounted_attempt_count"] != len(results)
        or type(accounting.get("attempt_cap")) is not int
        or accounting["attempt_cap"] != 3
        or accounting.get("scene_ids") != list(protocol.SCENE_ORDER[:len(results)])
        or accounting.get("receipts") != expected_simplified
    ):
        raise PreflightBlocked("ACTUAL_COST_STOP_PENDING_OR_MISMATCHED")
    try:
        total = validate_actual_cost_accounting(expected_receipts, accounting)
    except SizingBlocked as error:
        raise PreflightBlocked("ACTUAL_COST_STOP_PENDING_OR_MISMATCHED") from error
    if consumed >= len(protocol.SCENE_ORDER):
        raise PreflightBlocked("SYNTHETIC_LEDGER_CAP_EXHAUSTED")
    return consumed, total


def _validate_receipt(receipt: object, reservation: dict[str, Any]) -> None:
    receipt_fields = {
        "receipt_id", "study_id", "scene_id", "attempt_number", "response_sha256",
        "returned_model_id", "upstream_provider", "generation_id", "cost_usd",
        "prompt_tokens", "completion_tokens", "reasoning_tokens",
    }
    if (
        type(receipt) is not dict
        or set(receipt) != receipt_fields
        or receipt.get("study_id") != protocol.STUDY_ID
        or receipt.get("scene_id") != reservation["scene_id"]
        or type(receipt.get("attempt_number")) is not int
        or receipt.get("attempt_number") != reservation["attempt_number"]
        or type(receipt.get("response_sha256")) is not str
        or _SHA256_RE.fullmatch(receipt["response_sha256"]) is None
        or receipt.get("returned_model_id") != protocol.MODEL_ID
        or type(receipt.get("upstream_provider")) is not str
        or _UPSTREAM_RE.fullmatch(receipt["upstream_provider"]) is None
        or receipt["upstream_provider"].casefold() in {"unknown", "none", "n/a", "unset"}
        or type(receipt.get("generation_id")) is not str
        or _IDENTITY_RE.fullmatch(receipt["generation_id"]) is None
        or receipt.get("receipt_id") != receipt.get("generation_id")
        or type(receipt.get("cost_usd")) is not str
        or any(type(receipt.get(field)) is not int or receipt[field] < 0 for field in _USAGE_FIELDS)
        or receipt["reasoning_tokens"] > receipt["completion_tokens"]
    ):
        raise PreflightBlocked("SYNTHETIC_LEDGER_RECEIPT_INVALID")
    try:
        amount = Decimal(receipt["cost_usd"])
    except (InvalidOperation, TypeError, ValueError):
        raise PreflightBlocked("SYNTHETIC_LEDGER_RECEIPT_INVALID") from None
    if not amount.is_finite() or amount < 0:
        raise PreflightBlocked("SYNTHETIC_LEDGER_RECEIPT_INVALID")


def _valid_run_id(value: object) -> bool:
    return type(value) is str and _RUN_ID_RE.fullmatch(value) is not None


def _ledger_header(
    approval_pins: ApprovalPins,
    dispatch_pins: DispatchPins,
    config_sha256: str,
) -> dict[str, Any]:
    return {
        "event": "header",
        "schema": LEDGER_SCHEMA,
        "study_id": protocol.STUDY_ID,
        "allocation_scope": "studywide",
        "root_relative": STUDY3_ROOT_RELATIVE,
        "attempt_cap": 3,
        "scene_order": list(protocol.SCENE_ORDER),
        "manifest_sha256": approval_pins.manifest_sha256,
        "generation_config_sha256": config_sha256,
        "approval_pin_binding": {
            "standing_authority_ruling_id": approval_pins.standing_authority_ruling_id,
            "standing_authority_sha256": approval_pins.standing_authority_sha256,
            "cap_approval_ruling_id": approval_pins.cap_approval_ruling_id,
            "cap_approval_sha256": approval_pins.cap_approval_sha256,
            "cap_envelope_sha256": approval_pins.cap_envelope_sha256,
        },
        "dispatch_pin_binding": {
            "readiness_ruling_id": dispatch_pins.readiness_ruling_id,
            "readiness_sha256": dispatch_pins.readiness_sha256,
            "dispatch_ruling_id": dispatch_pins.dispatch_ruling_id,
            "dispatch_sha256": dispatch_pins.dispatch_sha256,
        },
    }


def _parse_hash_chain(records: object) -> list[dict[str, Any]]:
    if type(records) is not tuple or not 1 <= len(records) <= 7:
        raise PreflightBlocked("SYNTHETIC_LEDGER_STATE_MISSING_OR_CORRUPT")
    payloads: list[dict[str, Any]] = []
    previous = _ZERO_HASH
    for raw in records:
        outer = _parse_canonical_object(raw, "SYNTHETIC_LEDGER_CORRUPT")
        if set(outer) != {"payload", "previous_record_sha256", "record_sha256"}:
            raise PreflightBlocked("SYNTHETIC_LEDGER_CORRUPT")
        payload = outer["payload"]
        if (
            type(payload) is not dict
            or outer["previous_record_sha256"] != previous
            or type(outer["record_sha256"]) is not str
            or _SHA256_RE.fullmatch(outer["record_sha256"]) is None
        ):
            raise PreflightBlocked("SYNTHETIC_LEDGER_CORRUPT")
        body = {
            "payload": payload,
            "previous_record_sha256": previous,
        }
        digest = hashlib.sha256(_canonical_json(body)).hexdigest()
        if digest != outer["record_sha256"]:
            raise PreflightBlocked("SYNTHETIC_LEDGER_CORRUPT")
        payloads.append(payload)
        previous = digest
    return payloads


def _parse_canonical_object(value: object, code: str) -> dict[str, Any]:
    if type(value) is not bytes or not 1 <= len(value) <= _MAX_RECORD_BYTES:
        raise PreflightBlocked(code)
    parsed = _parse_json(value, code, require_canonical=True)
    if type(parsed) is not dict:
        raise PreflightBlocked(code)
    return parsed


def _parse_json(value: bytes, code: str, *, require_canonical: bool) -> Any:
    try:
        parsed = json.loads(
            value.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_nonfinite_constant,
        )
        if require_canonical and _canonical_json(parsed) != value:
            raise ValueError("non-canonical record")
        return parsed
    except (UnicodeError, json.JSONDecodeError, ValueError, TypeError, RecursionError, OverflowError):
        raise PreflightBlocked(code) from None


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _reject_nonfinite_constant(_value: str) -> None:
    raise ValueError("non-finite value")


def _canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError):
        raise PreflightBlocked("SYNTHETIC_STATE_SERIALIZATION_INVALID") from None


def main(argv: list[str] | None = None) -> int:
    """Run fresh exact-SHA readiness; no saved evidence arguments are accepted."""

    arguments = sys.argv[1:] if argv is None else argv
    if arguments != ["--exact-sha-readiness"]:
        print(
            '{"reason_codes":["READINESS_ARGUMENTS_NOT_ACCEPTED"],'
            '"status":"BLOCKED"}'
        )
        return 2
    from . import readiness

    verification = readiness.verify_readiness_evidence()
    result = {
        "status": verification.status,
        "reason_codes": list(verification.reason_codes),
        "current_head_sha": verification.current_head_sha,
        "ci_check_count": verification.ci_check_count,
        "preflight_gate_count": verification.preflight_gate_count,
        "external_provenance_verified": verification.external_provenance_verified,
        "live_dispatch_permitted": verification.live_dispatch_permitted,
    }
    print(
        json.dumps(
            result,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    )
    return 0 if readiness.is_verified_readiness(verification) else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ApprovalPins",
    "DispatchPins",
    "OutcomeDecision",
    "PreflightBlocked",
    "PreflightDecision",
    "ProviderIdentity",
    "SyntheticLedgerSnapshot",
    "classify_attempt_outcome",
    "main",
    "synthetic_preflight",
]
