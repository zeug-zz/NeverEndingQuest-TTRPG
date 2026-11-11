# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Exact-head-gated Study 3b reserved-run policy adapter.

The live path requires a fresh task 3.1 readiness proof before initializing the
Study 3b ledger. The synthetic path exercises the original one-shot transport
only after a synthetic ledger has durably reserved the matching request.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import types
from typing import Any

from ..llm_staging.client import TransportResult
from ..llm_staging.transport import (
    MAX_REQUEST_BYTES,
    MAX_RESPONSE_BYTES,
    OPENROUTER_ENDPOINT,
    REQUEST_TIMEOUT_SECONDS,
    OpenRouterTransport as _OpenRouterTransport,
    OpenRouterTransportError,
    _ReservedDispatchContext,
    _UrllibHTTP,
    _canonical_bytes as _transport_canonical_bytes,
    _create_reserved_dispatch_context,
)
from . import hydration, newrequest, preflight, protocol
from . import ledger as study3b_ledger
from . import isolation
from .isolation import PriorStudyMutationDenied, assert_study3b_write_target
from .ledger import Study3bLedger, Study3bLedgerError, Study3bReservation


SYNTHETIC_CREDENTIAL = "SYNTHETIC_STUDY3B_CREDENTIAL_NOT_SECRET"
_COST_RE = re.compile(r"^(?:0|[1-9][0-9]*)(?:\.[0-9]{1,12})?$")
_GENERATION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_PROVIDER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._/-]{0,127}$")
_USAGE_KEY_RE = re.compile(r"^[a-z_]{1,40}$")


class Study3bRunnerBlocked(RuntimeError):
    """Metadata-only refusal from the Study 3b runner."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class Study3bAttemptResult:
    """Metadata-only view of one consumed reservation."""

    scene_id: str
    attempt_number: int
    outcome: str
    stop_study: bool
    reason_code: str | None
    http_status: int | None
    request_sha256: str
    transport_request_sha256: str
    response_sha256: str | None
    response_relative_path: str | None
    returned_model_id: str | None
    upstream_provider: str | None
    generation_id: str | None
    usage: tuple[tuple[str, int], ...]
    actual_cost_status: str
    actual_cost_usd: str | None


@dataclass(frozen=True)
class Study3bRunResult:
    """Metadata-only run summary; generated content is never returned."""

    study_id: str
    status: str
    attempts: tuple[Study3bAttemptResult, ...]
    remaining_scenes: tuple[str, ...]
    synthetic_only: bool


class _Study3bDeadlineHTTP:
    """Apply the pinned 720-second profile at the HTTP boundary."""

    def __init__(self, delegate: object) -> None:
        self._delegate = delegate

    def post(
        self,
        *,
        url: str,
        headers: dict[str, str],
        body: bytes,
        timeout: float,
        allow_redirects: bool,
    ) -> tuple[int, bytes]:
        if (
            url != OPENROUTER_ENDPOINT
            or type(timeout) not in {int, float}
            or timeout != REQUEST_TIMEOUT_SECONDS
            or allow_redirects is not False
        ):
            raise OpenRouterTransportError("Study 3b transport policy rejected dispatch")
        post = getattr(self._delegate, "post", None)
        if not callable(post):
            raise OpenRouterTransportError("Study 3b HTTP adapter is unavailable")
        return post(
            url=OPENROUTER_ENDPOINT,
            headers=headers,
            body=body,
            timeout=720.0,
            allow_redirects=False,
        )


class _Study3bPolicyAdapter(_OpenRouterTransport):
    """Study 3b request policy over the original reserved one-shot transport."""

    def __init__(self, *, http: object, config_loader: object) -> None:
        super().__init__(
            http=_Study3bDeadlineHTTP(http),
            config_loader=config_loader,
        )

    @staticmethod
    def _validate_request(endpoint: object, request: object) -> bytes:
        if endpoint != OPENROUTER_ENDPOINT:
            raise OpenRouterTransportError("Study 3b endpoint mismatch")
        config = protocol.load_generation_config()
        expected_fields = {
            "model",
            "messages",
            "temperature",
            "top_p",
            "frequency_penalty",
            "presence_penalty",
            "max_tokens",
            "stream",
            "response_format",
            "tools",
            "tool_choice",
            "provider",
        }
        if type(request) is not dict or set(request) != expected_fields:
            raise OpenRouterTransportError("Study 3b request shape mismatch")
        expected = {
            "model": config["model_id"],
            "temperature": config["temperature"],
            "top_p": config["top_p"],
            "frequency_penalty": config["frequency_penalty"],
            "presence_penalty": config["presence_penalty"],
            "max_tokens": config["max_tokens"],
            "stream": config["stream"],
            "response_format": config["response_format"],
            "tools": config["tools"],
            "tool_choice": config["tool_choice"],
            "provider": config["provider_options"],
        }
        if not _same_json_value(request, {**expected, "messages": request.get("messages")}):
            raise OpenRouterTransportError("Study 3b request envelope mismatch")
        messages = request.get("messages")
        if (
            type(messages) is not list
            or len(messages) != 2
            or any(
                type(message) is not dict
                or set(message) != {"role", "content"}
                or type(message.get("content")) is not str
                for message in messages
            )
            or messages[0].get("role") != "system"
            or messages[1].get("role") != "user"
        ):
            raise OpenRouterTransportError("Study 3b messages mismatch")
        try:
            body = _transport_canonical_bytes(request)
        except (TypeError, ValueError, RecursionError):
            raise OpenRouterTransportError("Study 3b request serialization failed") from None
        if len(body) > MAX_REQUEST_BYTES:
            raise OpenRouterTransportError("Study 3b request exceeded its size limit")
        return body


class Study3bSyntheticHTTP:
    """Fixed fake HTTP/credential seam; cannot be configured with real secrets."""

    def __init__(
        self,
        ledger: Study3bLedger,
        responses: list[tuple[int, bytes] | None],
    ) -> None:
        if type(ledger) is not Study3bLedger or ledger._synthetic is not True:
            raise Study3bRunnerBlocked("SYNTHETIC_LEDGER_REQUIRED")
        if type(responses) is not list or any(
            response is not None
            and (
                type(response) is not tuple
                or len(response) != 2
                or type(response[0]) is not int
                or type(response[1]) is not bytes
            )
            for response in responses
        ):
            raise Study3bRunnerBlocked("SYNTHETIC_HTTP_FIXTURE_INVALID")
        self._ledger = ledger
        self._responses = list(responses)
        self.credential_reads = 0
        self.reservation_visible_at_credential_read: list[bool] = []
        self.calls: list[dict[str, object]] = []

    def load_config(self) -> object:
        self.credential_reads += 1
        try:
            records = [
                json.loads(line)
                for line in _read_synthetic_ledger_bytes(self._ledger).splitlines()
            ]
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
            records = []
        reservations = [
            record
            for record in records
            if type(record) is dict and record.get("event") == "reservation"
        ]
        visible = (
            len(reservations) == self.credential_reads
            and bool(records)
            and type(records[-1]) is dict
            and records[-1].get("event") == "reservation"
            and records[-1].get("attempt_number") == self.credential_reads
        )
        self.reservation_visible_at_credential_read.append(visible)
        if not visible:
            raise RuntimeError("synthetic reservation is not durable")
        return types.SimpleNamespace(OPENROUTER_API_KEY=SYNTHETIC_CREDENTIAL)

    def post(
        self,
        *,
        url: str,
        headers: dict[str, str],
        body: bytes,
        timeout: float,
        allow_redirects: bool,
    ) -> tuple[int, bytes]:
        self.calls.append(
            {
                "url": url,
                "request_sha256": hashlib.sha256(body).hexdigest(),
                "timeout": timeout,
                "allow_redirects": allow_redirects,
                "synthetic_bearer_present": headers.get("Authorization")
                == "Bearer " + SYNTHETIC_CREDENTIAL,
            }
        )
        if not self._responses:
            raise TimeoutError("synthetic transport fixture exhausted")
        response = self._responses.pop(0)
        if response is None:
            raise TimeoutError("synthetic transport timeout")
        return response


class Study3bRunner:
    """Exact-head-gated runner plus an isolated provider-free fake path."""

    def run(
        self,
        *,
        expected_head_sha: str | None = None,
        ci_evidence_path: str | None = None,
        ci_evidence_sha256: str | None = None,
        dispatch_ruling_id: str | None = None,
    ) -> Study3bRunResult:
        """Run only after fresh exact-head readiness and explicit ruling opt-in.

        No argument defaults to live readiness. The exact existing ruling ID is
        a required explicit opt-in; this method always performs preflight before
        constructing or initializing the real Study 3b ledger.
        """

        if (
            expected_head_sha is None
            or ci_evidence_path is None
            or ci_evidence_sha256 is None
            or dispatch_ruling_id is None
        ):
            raise Study3bRunnerBlocked("STUDY3B_EXPLICIT_EXACT_HEAD_OPT_IN_REQUIRED")
        try:
            readiness = preflight.verify_live_readiness(
                expected_head_sha=expected_head_sha,
                ci_evidence_path=ci_evidence_path,
                ci_evidence_sha256=ci_evidence_sha256,
                dispatch_ruling_id=dispatch_ruling_id,
            )
            if not preflight.is_verified_readiness(readiness):
                code = (
                    readiness.reason_codes[0]
                    if type(readiness) is preflight.ReadinessVerification
                    and readiness.reason_codes
                    else "LIVE_PREFLIGHT_NOT_READY"
                )
                raise Study3bRunnerBlocked(code)
            preflight.assert_dispatch_readiness_current(readiness)
        except preflight.ReadinessBlocked as error:
            raise Study3bRunnerBlocked(error.code) from None

        actual_ledger = Study3bLedger()
        try:
            actual_ledger.initialize()
        except Study3bLedgerError as error:
            raise Study3bRunnerBlocked(error.code) from None
        adapter = _Study3bPolicyAdapter(
            http=_UrllibHTTP(),
            config_loader=None,
        )
        return _execute_reserved_scenes(
            actual_ledger,
            adapter,
            synthetic_only=False,
        )

    def run_synthetic(
        self,
        ledger: Study3bLedger,
        fake_http: Study3bSyntheticHTTP,
    ) -> Study3bRunResult:
        """Exercise the shared transport only with a synthetic ledger and fake."""

        if (
            type(ledger) is not Study3bLedger
            or ledger._synthetic is not True
            or ledger._initialized is not True
            or type(fake_http) is not Study3bSyntheticHTTP
            or fake_http._ledger is not ledger
        ):
            raise Study3bRunnerBlocked("SYNTHETIC_EXECUTION_SEAM_REQUIRED")
        adapter = _Study3bPolicyAdapter(
            http=fake_http,
            config_loader=fake_http.load_config,
        )
        return _execute_reserved_scenes(ledger, adapter, synthetic_only=True)


def _execute_reserved_scenes(
    ledger: Study3bLedger,
    adapter: _Study3bPolicyAdapter,
    *,
    synthetic_only: bool,
) -> Study3bRunResult:
    owner_token = object()
    attempts: list[Study3bAttemptResult] = []
    remaining = list(protocol.SCENE_ORDER)
    for scene_id in protocol.SCENE_ORDER:
        try:
            request = newrequest.build_request(scene_id)
            newrequest.audit_request_parity(scene_id, request)
            _validate_transport_metadata(
                scene_id, newrequest.request_transport_metadata(scene_id)
            )
            request_sha256 = study3b_ledger.request_sha256_for_scene(scene_id)
            # The ledger's UTF-8 request binding also sizes the prompt; the
            # shared transport hashes its canonical ASCII wire bytes. Both
            # hashes are derived from this parity-audited immutable request.
            transport_request_sha256 = hashlib.sha256(
                _transport_canonical_bytes(request)
            ).hexdigest()
            reservation = ledger.reserve(
                scene_id=scene_id,
                request_sha256=request_sha256,
            )
        except Study3bLedgerError as error:
            raise Study3bRunnerBlocked(error.code) from None
        except Study3bRunnerBlocked:
            raise
        except Exception:
            raise Study3bRunnerBlocked("STUDY3B_PRE_DISPATCH_CHECK_FAILED") from None

        attempts.append(
            _run_reserved_attempt(
                ledger,
                adapter,
                owner_token,
                reservation,
                request,
                request_sha256,
                transport_request_sha256,
            )
        )
        remaining.pop(0)
        if attempts[-1].stop_study:
            return Study3bRunResult(
                study_id=protocol.STUDY_ID,
                status="STOPPED",
                attempts=tuple(attempts),
                remaining_scenes=tuple(remaining),
                synthetic_only=synthetic_only,
            )
    return Study3bRunResult(
        study_id=protocol.STUDY_ID,
        status="COMPLETE",
        attempts=tuple(attempts),
        remaining_scenes=(),
        synthetic_only=synthetic_only,
    )


def _validate_transport_metadata(scene_id: str, metadata: object) -> None:
    if type(metadata) is not dict:
        raise Study3bRunnerBlocked("STUDY3B_TRANSPORT_METADATA_INVALID")
    constraints = {
        "retries": 0,
        "reruns": 0,
        "fallback": False,
        "availability_get": False,
        "redirects": False,
        "continuation": False,
    }
    if (
        metadata.get("study_id") != protocol.STUDY_ID
        or metadata.get("scene_id") != scene_id
        or metadata.get("provider") != "openrouter"
        or metadata.get("endpoint") != OPENROUTER_ENDPOINT
        or metadata.get("model_id") != protocol.MODEL_ID
        or type(metadata.get("timeout_seconds")) is not int
        or metadata.get("timeout_seconds") != 720
        or metadata.get("dispatch_authorized") is not False
        or metadata.get("attempt_cap_identity") != protocol.STUDY_ID
        or type(metadata.get("attempt_cap")) is not int
        or metadata.get("attempt_cap") != len(protocol.SCENE_ORDER)
        or type(metadata.get("attempts_per_scene")) is not int
        or metadata.get("attempts_per_scene") != 1
        or metadata.get("scene_order") != protocol.SCENE_ORDER
        or metadata.get("manifest_sha256") != protocol.MANIFEST_SHA256
        or metadata.get("generation_config_sha256")
        != protocol.GENERATION_CONFIG_SHA256
        or metadata.get("transport_constraints") != constraints
    ):
        raise Study3bRunnerBlocked("STUDY3B_TRANSPORT_METADATA_INVALID")


def _run_reserved_attempt(
    ledger: Study3bLedger,
    adapter: _Study3bPolicyAdapter,
    owner_token: object,
    reservation: Study3bReservation,
    request: dict[str, Any],
    request_sha256: str,
    transport_request_sha256: str,
) -> Study3bAttemptResult:
    if (
        type(reservation) is not Study3bReservation
        or reservation.study_id != protocol.STUDY_ID
        or reservation.scene_id not in protocol.SCENE_ORDER
        or reservation.request_sha256 != request_sha256
        or reservation.attempt_number != protocol.SCENE_ORDER.index(reservation.scene_id) + 1
    ):
        raise Study3bRunnerBlocked("RESERVATION_HANDLE_INVALID")

    result: TransportResult | None = None
    response_hash: str | None = None
    response_path: str | None = None
    receipt: object = None
    safe_metadata: dict[str, Any] | None = None
    reason_code: str | None = None
    forced_stop = False

    try:
        context = _create_reserved_dispatch_context(
            owner_token,
            attempt_number=reservation.attempt_number,
            scene_id=reservation.scene_id,
            request_sha256=transport_request_sha256,
        )
        if type(context) is not _ReservedDispatchContext:
            raise OpenRouterTransportError("reserved dispatch context invalid")
        raw_result = adapter._dispatch_reserved(
            context,
            OPENROUTER_ENDPOINT,
            request,
            owner_token=owner_token,
        )
        if type(raw_result) is not TransportResult:
            raise OpenRouterTransportError("transport result invalid")
        result = raw_result
    except Exception:
        reason_code = "TRANSPORT_FAILED"
        forced_stop = True

    if result is not None:
        if type(result.body) is not bytes or not 1 <= len(result.body) <= MAX_RESPONSE_BYTES:
            reason_code = "RESPONSE_MISSING_OR_OVERSIZED"
            forced_stop = True
        else:
            response_hash = hashlib.sha256(result.body).hexdigest()
            try:
                response_path = _write_private_response(
                    ledger,
                    _synthetic_response_root(ledger),
                    reservation,
                    result.body,
                )
            except Study3bRunnerBlocked:
                reason_code = "PRIVATE_RESPONSE_PERSIST_FAILED"
                forced_stop = True
            if result.http_status == 200:
                _document, receipt, safe_metadata = _response_bound_receipt(
                    result,
                    reservation,
                    response_hash,
                )
                if receipt is None:
                    reason_code = _receipt_failure_code(result, safe_metadata)
                    forced_stop = True
            else:
                reason_code = "HTTP_STATUS_NOT_200"
                forced_stop = True

    if result is None:
        outcome = "STOPPED"
        http_status = None
    else:
        http_status = result.http_status if type(result.http_status) is int else None
        if forced_stop:
            outcome = "STOPPED"
        else:
            try:
                document = _parse_provider_json(result.body)
                delta_bytes = _extract_delta_bytes(document)
                hydration.hydrate_delta_output(delta_bytes, scene_id=reservation.scene_id)
            except Exception:
                outcome = "CONTRACT_FAILURE"
                reason_code = "STUDY3B_OUTPUT_PROTOCOL_DEFECT"
            else:
                outcome = "ACCEPTED"

    try:
        completion = ledger.complete(
            reservation,
            outcome=outcome,
            cost_receipt=receipt,
        )
    except Study3bLedgerError as error:
        raise Study3bRunnerBlocked(error.code) from None

    if completion.actual_cost_status != "RECONCILED":
        reason_code = reason_code or "ACTUAL_COST_UNRESOLVED"
    elif completion.stop_study and outcome != "STOPPED":
        reason_code = reason_code or "REMAINING_BUDGET_UNSAFE"
    usage = (
        tuple(sorted(safe_metadata["usage"].items()))
        if safe_metadata is not None
        else ()
    )
    return Study3bAttemptResult(
        scene_id=reservation.scene_id,
        attempt_number=reservation.attempt_number,
        outcome=outcome,
        stop_study=completion.stop_study or forced_stop,
        reason_code=reason_code,
        http_status=http_status,
        request_sha256=request_sha256,
        transport_request_sha256=transport_request_sha256,
        response_sha256=response_hash,
        response_relative_path=response_path,
        returned_model_id=(
            safe_metadata.get("returned_model_id")
            if safe_metadata is not None
            else None
        ),
        upstream_provider=(
            safe_metadata.get("upstream_provider")
            if safe_metadata is not None
            else None
        ),
        generation_id=(
            safe_metadata.get("generation_id")
            if safe_metadata is not None
            else None
        ),
        usage=usage,
        actual_cost_status=completion.actual_cost_status,
        actual_cost_usd=completion.actual_cost_usd,
    )


def _response_bound_receipt(
    result: TransportResult,
    reservation: Study3bReservation,
    response_sha256: str,
) -> tuple[dict[str, Any] | None, object | None, dict[str, Any] | None]:
    try:
        document = _parse_provider_json(result.body)
    except (UnicodeError, ValueError, json.JSONDecodeError, RecursionError, OverflowError):
        return None, None, None
    if type(document) is not dict or result.http_status != 200:
        return None, None, None
    usage = document.get("usage")
    if type(usage) is not dict:
        return document, None, None
    returned_model = document.get("model")
    upstream_provider = document.get("provider")
    generation_id = document.get("id")
    transport_usage = {
        key: value
        for key, value in usage.items()
        if type(key) is str
        and _USAGE_KEY_RE.fullmatch(key) is not None
        and type(value) is int
        and 0 <= value <= 2_147_483_647
    }
    if (
        type(result.returned_model_id) is not str
        or type(result.upstream_provider) is not str
        or type(result.generation_id) is not str
        or returned_model != result.returned_model_id
        or upstream_provider != result.upstream_provider
        or generation_id != result.generation_id
        or type(result.usage) is not dict
        or result.usage != transport_usage
    ):
        return document, None, None
    if (
        returned_model != protocol.MODEL_ID
        or type(upstream_provider) is not str
        or _PROVIDER_RE.fullmatch(upstream_provider) is None
        or upstream_provider.casefold() in {"unknown", "none", "n/a", "unset"}
        or type(generation_id) is not str
        or _GENERATION_ID_RE.fullmatch(generation_id) is None
        or re.fullmatch(r"[0-9a-f]{64}", response_sha256) is None
    ):
        return document, None, None

    safe_usage = {
        key: transport_usage[key]
        for key in (
            "prompt_tokens",
            "completion_tokens",
            "reasoning_tokens",
            "total_tokens",
        )
        if key in transport_usage
    }
    safe_metadata = {
        "returned_model_id": returned_model,
        "upstream_provider": upstream_provider,
        "generation_id": generation_id,
        "usage": safe_usage,
    }
    prompt_tokens = usage.get("prompt_tokens")
    completion_tokens = usage.get("completion_tokens")
    reasoning_flat = usage.get("reasoning_tokens")
    completion_details = usage.get("completion_tokens_details")
    reasoning_nested = (
        completion_details.get("reasoning_tokens")
        if type(completion_details) is dict
        else None
    )
    if reasoning_flat is not None and reasoning_nested is not None and reasoning_flat != reasoning_nested:
        return document, None, safe_metadata
    reasoning_tokens = reasoning_flat if reasoning_flat is not None else reasoning_nested
    cost_string = _provider_cost_string(usage.get("cost"))
    if (
        cost_string is None
        or type(prompt_tokens) is not int
        or not 0 <= prompt_tokens <= 2_147_483_647
        or type(completion_tokens) is not int
        or not 0 <= completion_tokens <= 2_147_483_647
        or type(reasoning_tokens) is not int
        or not 0 <= reasoning_tokens <= 2_147_483_647
        or reasoning_tokens > completion_tokens
    ):
        return document, None, safe_metadata

    try:
        receipt = study3b_ledger._make_verified_cost_receipt(reservation, result)
    except Study3bLedgerError:
        return document, None, safe_metadata
    return document, receipt, safe_metadata


def _receipt_failure_code(
    result: TransportResult, safe_metadata: dict[str, Any] | None
) -> str:
    if (
        result.returned_model_id != protocol.MODEL_ID
        or type(result.upstream_provider) is not str
        or _PROVIDER_RE.fullmatch(result.upstream_provider) is None
        or result.upstream_provider.casefold() in {"unknown", "none", "n/a", "unset"}
        or type(result.generation_id) is not str
        or _GENERATION_ID_RE.fullmatch(result.generation_id) is None
    ):
        return "PROVIDER_IDENTITY_MISMATCH"
    if safe_metadata is None:
        return "PROVIDER_RESPONSE_INVALID"
    return "COST_RECEIPT_MISSING_OR_INCONSISTENT"


def _provider_cost_string(value: object) -> str | None:
    if type(value) is int:
        amount = Decimal(value)
    elif type(value) is Decimal:
        amount = value
    else:
        return None
    if not amount.is_finite() or amount < 0:
        return None
    parts = amount.as_tuple()
    if (
        type(parts.exponent) is not int
        or max(0, -parts.exponent) > 12
        or len(parts.digits) + max(0, parts.exponent) > 64
    ):
        return None
    normalized = format(amount, "f")
    if len(normalized) > 64:
        return None
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    if not normalized:
        normalized = "0"
    return normalized if _COST_RE.fullmatch(normalized) is not None else None


def _parse_provider_json(raw: bytes) -> Any:
    if type(raw) is not bytes or not 1 <= len(raw) <= MAX_RESPONSE_BYTES:
        raise ValueError("response size")
    return json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=_reject_duplicate_keys,
        parse_int=int,
        parse_float=Decimal,
        parse_constant=_reject_nonfinite,
    )


def _extract_delta_bytes(document: object) -> bytes:
    if type(document) is not dict:
        return b""
    choices = document.get("choices")
    if type(choices) is not list or len(choices) != 1 or type(choices[0]) is not dict:
        return b""
    message = choices[0].get("message")
    if type(message) is not dict or type(message.get("content")) is not str:
        return b""
    try:
        return message["content"].encode("utf-8")
    except UnicodeEncodeError:
        return b""


def _synthetic_response_root(ledger: Study3bLedger) -> Path:
    if ledger._synthetic is True:
        return ledger.root.parent / (ledger.root.name + "-private-responses")
    return protocol.REPO_ROOT / (
        "tmp/router-rollout/mapping-pilot/mise-en-scene-offline/"
        "llm-staging-study3b-prep/primary-private-responses"
    )


def _write_private_response(
    ledger: Study3bLedger,
    response_root: Path,
    reservation: Study3bReservation,
    body: bytes,
) -> str:
    expected_root = _synthetic_response_root(ledger)
    if (
        not isinstance(response_root, Path)
        or response_root != expected_root
        or type(reservation) is not Study3bReservation
        or reservation.study_id != protocol.STUDY_ID
        or reservation.scene_id not in protocol.SCENE_ORDER
        or type(body) is not bytes
        or not 1 <= len(body) <= MAX_RESPONSE_BYTES
    ):
        raise Study3bRunnerBlocked("PRIVATE_RESPONSE_PATH_OR_BODY_INVALID")
    name = (
        "%02d_" % reservation.attempt_number
        + reservation.scene_id.replace(":", "__")
        + ".response.json"
    )
    path = response_root / name
    root_fd: int | None = None
    directory_fd: int | None = None
    descriptor: int | None = None
    created = False
    try:
        response_parts = isolation._absolute_relative_parts(
            protocol.REPO_ROOT, response_root
        )
        root_fd = isolation._open_root_directory(protocol.REPO_ROOT)
        directory_fd = isolation._make_directory_parts(
            root_fd, response_parts, mode=0o700
        )
        _assert_write_target(response_root, "write")
        _assert_no_symlink_path(response_root, allow_missing_leaf=False)
        _assert_write_target(path, "write")
        descriptor = os.open(
            name,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            0o600,
            dir_fd=directory_fd,
        )
        created = True
        opened = os.fstat(descriptor)
        named = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if (
            not stat.S_ISREG(opened.st_mode)
            or stat.S_ISLNK(named.st_mode)
            or opened.st_nlink != 1
            or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)
        ):
            raise OSError("private response is not regular")
        offset = 0
        while offset < len(body):
            written = os.write(descriptor, body[offset:])
            if written <= 0:
                raise OSError("short private response write")
            offset += written
        after = os.fstat(descriptor)
        named_after = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if (
            after.st_dev != opened.st_dev
            or after.st_ino != opened.st_ino
            or after.st_size != len(body)
            or after.st_mtime_ns < opened.st_mtime_ns
            or stat.S_ISLNK(named_after.st_mode)
            or (named_after.st_dev, named_after.st_ino)
            != (after.st_dev, after.st_ino)
        ):
            raise OSError("private response changed while writing")
        _assert_write_target(path, "append")
        os.fsync(descriptor)
        os.fsync(directory_fd)
        os.close(descriptor)
        descriptor = None
        return path.relative_to(protocol.REPO_ROOT).as_posix()
    except Study3bRunnerBlocked:
        if descriptor is not None:
            os.close(descriptor)
            descriptor = None
        raise
    except (OSError, ValueError, isolation.BaselineScopeError):
        if descriptor is not None:
            os.close(descriptor)
            descriptor = None
        if created and directory_fd is not None:
            try:
                os.unlink(name, dir_fd=directory_fd)
                os.fsync(directory_fd)
            except OSError:
                pass
        raise Study3bRunnerBlocked("PRIVATE_RESPONSE_WRITE_FAILED") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if directory_fd is not None:
            os.close(directory_fd)
        if root_fd is not None:
            os.close(root_fd)


def _assert_no_symlink_path(path: Path, *, allow_missing_leaf: bool) -> None:
    try:
        parts = isolation._absolute_relative_parts(protocol.REPO_ROOT, path)
        isolation._assert_no_symlink_path(
            protocol.REPO_ROOT, parts, allow_missing_leaf=allow_missing_leaf
        )
    except (ValueError, OSError, isolation.BaselineScopeError):
        raise Study3bRunnerBlocked("PRIVATE_RESPONSE_PATH_INVALID") from None


def _assert_write_target(path: Path, action: str) -> None:
    try:
        assert_study3b_write_target(
            path,
            repository_root=protocol.REPO_ROOT,
            action=action,
        )
    except (PriorStudyMutationDenied, ValueError, OSError):
        raise Study3bRunnerBlocked("STUDY3B_WRITE_BOUNDARY_REJECTED") from None


def _read_synthetic_ledger_bytes(ledger: Study3bLedger) -> bytes:
    if ledger._synthetic is not True:
        raise Study3bRunnerBlocked("SYNTHETIC_LEDGER_REQUIRED")
    root_fd: int | None = None
    descriptor: int | None = None
    try:
        root_fd = study3b_ledger._open_root_directory(ledger._root_parts)
        descriptor = os.open(
            study3b_ledger.LEDGER_NAME,
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NONBLOCK", 0),
            dir_fd=root_fd,
        )
        before = os.fstat(descriptor)
        study3b_ledger._verify_named_regular_file(
            root_fd, study3b_ledger.LEDGER_NAME, descriptor
        )
        raw = study3b_ledger._read_descriptor(
            descriptor, study3b_ledger.MAX_LEDGER_BYTES + 1
        )
        after = os.fstat(descriptor)
        study3b_ledger._verify_named_regular_file(
            root_fd, study3b_ledger.LEDGER_NAME, descriptor
        )
        if (
            len(raw) > study3b_ledger.MAX_LEDGER_BYTES
            or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        ):
            raise OSError("synthetic ledger changed while reading")
        return raw
    except (OSError, Study3bLedgerError):
        raise Study3bRunnerBlocked("SYNTHETIC_LEDGER_UNAVAILABLE") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if root_fd is not None:
            os.close(root_fd)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _reject_nonfinite(_value: str) -> None:
    raise ValueError("non-finite value")


def _same_json_value(left: Any, right: Any) -> bool:
    if type(left) is dict and type(right) is dict:
        return set(left) == set(right) and all(
            _same_json_value(left[key], right[key]) for key in right
        )
    if type(left) is list and type(right) is list:
        return len(left) == len(right) and all(
            _same_json_value(a, b) for a, b in zip(left, right)
        )
    return type(left) is type(right) and left == right


__all__ = [
    "SYNTHETIC_CREDENTIAL",
    "Study3bAttemptResult",
    "Study3bRunResult",
    "Study3bRunner",
    "Study3bRunnerBlocked",
    "Study3bSyntheticHTTP",
]
