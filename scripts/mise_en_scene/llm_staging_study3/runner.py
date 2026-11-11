# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Study 3-only reserved runner and local OpenRouter policy adapter.

The real, non-injectable run path requires fresh exact-SHA readiness before it
constructs the real ledger, HTTP client, or provider credential loader.
Synthetic execution shares the reserved-attempt engine with injected fake-only
seams.
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

from ..llm_staging.transport import (
    MAX_REQUEST_BYTES,
    MAX_RESPONSE_BYTES,
    OPENROUTER_ENDPOINT,
    OpenRouterTransport as _OpenRouterTransport,
    OpenRouterTransportError,
    _ReservedDispatchContext,
    _UrllibHTTP,
    _canonical_bytes as _transport_canonical_bytes,
    _create_reserved_dispatch_context,
    _load_config as _load_transport_config,
)
from . import newhydration, protocol, readiness
from . import newrequest
from .ledger import (
    PREP_ROOT_RELATIVE,
    Study3Completion,
    Study3Ledger,
    Study3LedgerError,
    Study3Reservation,
)


_MAX_COST_DECIMAL_PLACES = 12
_USAGE_KEY_RE = re.compile(r"^[a-z_]{1,40}$")
_COST_RE = re.compile(r"^(?:0|[1-9][0-9]*)(?:\.[0-9]{1,12})?$")
_PROVIDER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._/-]{0,127}$")
_GENERATION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_ROOT_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)
_FILE_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
DEFAULT_RESPONSE_ROOT = (
    protocol.REPO_ROOT / PREP_ROOT_RELATIVE / "study3-private-evidence" / "responses"
)


class Study3RunnerBlocked(RuntimeError):
    """Metadata-only runner refusal."""

    def __init__(self, code: str, reason_codes: tuple[str, ...] = ()) -> None:
        self.code = code
        self.reason_codes = reason_codes
        super().__init__(code)


@dataclass(frozen=True)
class Study3TransportResult:
    """Sanitized result produced only from one bounded HTTP response."""

    http_status: int
    body: bytes
    returned_model_id: str
    upstream_provider: str
    generation_id: str
    usage: dict[str, int]


@dataclass(frozen=True)
class Study3AttemptResult:
    """Metadata-only view of one consumed Study 3 reservation."""

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
    metadata_relative_path: str | None
    returned_model_id: str | None
    upstream_provider: str | None
    generation_id: str | None
    usage: tuple[tuple[str, int], ...]
    actual_cost_status: str
    actual_cost_usd: str | None


@dataclass(frozen=True)
class Study3RunResult:
    """Metadata-only run summary; raw output is never returned."""

    study_id: str
    status: str
    attempts: tuple[Study3AttemptResult, ...]
    remaining_scenes: tuple[str, ...]
    synthetic_only: bool


class _Study3DeadlineHTTP:
    """Apply the approved Study 3 deadline over the shared one-shot transport."""

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
            or allow_redirects is not False
            or type(timeout) not in {int, float}
            or timeout <= 0
        ):
            raise OpenRouterTransportError("Study 3 transport policy rejected the dispatch")
        post = getattr(self._delegate, "post", None)
        if not callable(post):
            raise OpenRouterTransportError("Study 3 HTTP adapter is unavailable")
        # The shared transport's frozen timeout is not the Study 3 profile.
        # Override only at the HTTP boundary; redirects remain disabled.
        return post(
            url=OPENROUTER_ENDPOINT,
            headers=headers,
            body=body,
            timeout=720.0,
            allow_redirects=False,
        )


class _Study3PolicyAdapter(_OpenRouterTransport):
    """Study 3-local 16,384-token profile over the shared reservation seam."""

    def __init__(self, *, http: object, config_loader: object) -> None:
        super().__init__(
            http=_Study3DeadlineHTTP(http),
            config_loader=config_loader,
        )

    @staticmethod
    def _validate_request(endpoint: object, request: object) -> bytes:
        if endpoint != OPENROUTER_ENDPOINT:
            raise OpenRouterTransportError("Study 3 endpoint mismatch")
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
            raise OpenRouterTransportError("Study 3 request shape mismatch")
        expected = {
            "model": protocol.MODEL_ID,
            "temperature": 1.0,
            "top_p": 1.0,
            "frequency_penalty": 0.0,
            "presence_penalty": 0.0,
            "max_tokens": 16384,
            "stream": False,
            "response_format": {"type": "json_object"},
            "tools": [],
            "tool_choice": "none",
            "provider": {"allow_fallbacks": False},
        }
        for field, expected_value in expected.items():
            actual = request.get(field)
            if type(actual) is not type(expected_value) or actual != expected_value:
                raise OpenRouterTransportError("Study 3 request envelope mismatch")
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
            raise OpenRouterTransportError("Study 3 messages mismatch")
        try:
            body = _transport_canonical_bytes(request)
        except (TypeError, ValueError, RecursionError):
            raise OpenRouterTransportError("Study 3 request serialization failed") from None
        if len(body) > MAX_REQUEST_BYTES:
            raise OpenRouterTransportError("Study 3 request exceeded its size limit")
        return body

    @staticmethod
    def _transport_result(
        status: int,
        body: bytes,
        model_id: str,
        provider: str,
        generation_id: str,
        usage: dict[str, int],
    ) -> Study3TransportResult:
        return Study3TransportResult(
            http_status=status,
            body=body,
            returned_model_id=model_id,
            upstream_provider=provider,
            generation_id=generation_id,
            usage=usage,
        )


class Study3SyntheticHTTP:
    """Fixed no-network fake used only with an initialized synthetic ledger."""

    def __init__(
        self,
        ledger: Study3Ledger,
        responses: list[tuple[int, bytes] | None],
        *,
        credential: str = "study3-synthetic-credential",
    ) -> None:
        if type(ledger) is not Study3Ledger or ledger._synthetic is not True:
            raise Study3RunnerBlocked("SYNTHETIC_LEDGER_REQUIRED")
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
            raise Study3RunnerBlocked("SYNTHETIC_HTTP_FIXTURE_INVALID")
        if (
            type(credential) is not str
            or len(credential) <= len("[REDACTED]")
            or not credential.isascii()
        ):
            raise Study3RunnerBlocked("SYNTHETIC_CREDENTIAL_INVALID")
        self._ledger = ledger
        self._responses = list(responses)
        self._credential = credential
        self.credential_reads = 0
        self.reservation_visible_at_credential_read: list[bool] = []
        self.calls: list[dict[str, object]] = []

    def load_config(self) -> object:
        self.credential_reads += 1
        try:
            records = [
                json.loads(line)
                for line in self._ledger.path.read_bytes().splitlines()
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
        return types.SimpleNamespace(OPENROUTER_API_KEY=self._credential)

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
                "body": body,
                "timeout": timeout,
                "allow_redirects": allow_redirects,
                "bearer_present": headers.get("Authorization")
                == "Bearer " + self._credential,
            }
        )
        if not self._responses:
            raise RuntimeError("synthetic HTTP fixture exhausted")
        response = self._responses.pop(0)
        if response is None:
            raise RuntimeError("synthetic HTTP failure")
        return response


class Study3Runner:
    """Public real-run entrypoint; no dependency injection is accepted."""

    def run(
        self,
        *,
        expected_sha: str | None = None,
        ci_evidence_path: str | None = None,
        ci_evidence_sha256: str | None = None,
        source_repository: str | None = None,
        pr_number: int | None = None,
        dispatch_ruling_id: str | None = None,
    ) -> Study3RunResult:
        """Run only after a fresh exact-head preflight and explicit ruling opt-in.

        The raw public CheckRuns JSON and its hash must be supplied from a direct
        primary retrieval. The readiness helper revalidates that input and runs
        all provider-free gates immediately before the real ledger is created.
        """

        try:
            verification = readiness.verify_readiness_evidence(
                expected_sha=expected_sha,
                ci_evidence_path=ci_evidence_path,
                ci_evidence_sha256=ci_evidence_sha256,
                source_repository=source_repository,
                pr_number=pr_number,
                dispatch_ruling_id=dispatch_ruling_id,
            )
        except Exception:
            raise Study3RunnerBlocked("READINESS_VERIFICATION_FAILED") from None
        if type(verification) is not readiness.ReadinessVerification:
            raise Study3RunnerBlocked("READINESS_VERIFICATION_INVALID")
        if verification.status != "READY":
            raise Study3RunnerBlocked(
                "READINESS_BLOCKED",
                verification.reason_codes,
            )
        if not readiness.is_verified_readiness(verification):
            raise Study3RunnerBlocked("READINESS_PROOF_INVALID")
        if (
            verification.live_dispatch_permitted is not True
            or verification.external_provenance_verified is not True
            or verification.dispatch_ruling_id != readiness.DISPATCH_RULING_ID
            or dispatch_ruling_id != readiness.DISPATCH_RULING_ID
        ):
            raise Study3RunnerBlocked("READINESS_DISPATCH_NOT_PERMITTED")

        try:
            ledger = Study3Ledger()
            ledger.initialize()
        except Study3LedgerError as error:
            raise Study3RunnerBlocked(error.code) from None
        except Exception:
            raise Study3RunnerBlocked("REAL_LEDGER_INITIALIZATION_FAILED") from None

        adapter = _Study3PolicyAdapter(
            http=_UrllibHTTP(),
            config_loader=_load_transport_config,
        )
        return _execute_reserved_scenes(
            ledger,
            adapter,
            response_root=DEFAULT_RESPONSE_ROOT,
            synthetic_only=False,
        )

    def run_synthetic(
        self,
        ledger: Study3Ledger,
        fake_http: Study3SyntheticHTTP,
    ) -> Study3RunResult:
        """Exercise the runner only with the non-network fake and synthetic ledger."""

        if (
            type(ledger) is not Study3Ledger
            or ledger._synthetic is not True
            or type(fake_http) is not Study3SyntheticHTTP
            or fake_http._ledger is not ledger
        ):
            raise Study3RunnerBlocked("SYNTHETIC_EXECUTION_SEAM_REQUIRED")
        adapter = _Study3PolicyAdapter(
            http=fake_http,
            config_loader=fake_http.load_config,
        )
        response_root = ledger.root.parent / (ledger.root.name + "-evidence")
        return _execute_reserved_scenes(
            ledger,
            adapter,
            response_root=response_root,
            synthetic_only=True,
        )


def _execute_reserved_scenes(
    ledger: Study3Ledger,
    adapter: _Study3PolicyAdapter,
    *,
    response_root: Path,
    synthetic_only: bool,
) -> Study3RunResult:
    """Shared scene-order/reservation/dispatch engine for real and fake runs."""

    owner_token = object()
    attempts: list[Study3AttemptResult] = []
    remaining = list(protocol.SCENE_ORDER)
    for scene_id in protocol.SCENE_ORDER:
        try:
            request = newrequest.build_request(scene_id)
            newrequest.audit_request_parity(scene_id, request)
            metadata = newrequest.request_transport_metadata(scene_id)
            if (
                metadata.get("provider") != "openrouter"
                or metadata.get("endpoint") != OPENROUTER_ENDPOINT
                or metadata.get("timeout_seconds") != 720
                or metadata.get("transport_constraints")
                != {
                    "retries": 0,
                    "reruns": 0,
                    "redirects": False,
                    "continuation": False,
                }
                or metadata.get("scene_order") != protocol.SCENE_ORDER
            ):
                raise Study3RunnerBlocked("STUDY3_TRANSPORT_METADATA_INVALID")
            request_sha256 = hashlib.sha256(_canonical_request_bytes(request)).hexdigest()
            transport_request_sha256 = hashlib.sha256(
                _transport_canonical_bytes(request)
            ).hexdigest()
            reservation = ledger.reserve(
                scene_id=scene_id,
                request_sha256=request_sha256,
            )
        except Study3LedgerError as error:
            raise Study3RunnerBlocked(error.code) from None
        except Study3RunnerBlocked:
            raise
        except Exception:
            raise Study3RunnerBlocked("STUDY3_PRE_DISPATCH_CHECK_FAILED") from None

        attempts.append(
            _run_reserved_attempt(
                ledger,
                adapter,
                owner_token,
                reservation,
                request,
                request_sha256,
                transport_request_sha256,
                response_root,
            )
        )
        remaining.pop(0)
        if attempts[-1].stop_study:
            return Study3RunResult(
                study_id=protocol.STUDY_ID,
                status="STOPPED",
                attempts=tuple(attempts),
                remaining_scenes=tuple(remaining),
                synthetic_only=synthetic_only,
            )
    return Study3RunResult(
        study_id=protocol.STUDY_ID,
        status="COMPLETE",
        attempts=tuple(attempts),
        remaining_scenes=(),
        synthetic_only=synthetic_only,
    )


def _run_reserved_attempt(
    ledger: Study3Ledger,
    adapter: _Study3PolicyAdapter,
    owner_token: object,
    reservation: object,
    request: dict[str, Any],
    request_sha256: str,
    transport_request_sha256: str,
    response_root: Path,
) -> Study3AttemptResult:
    if type(reservation) is not Study3Reservation:
        raise Study3RunnerBlocked("RESERVATION_HANDLE_INVALID")
    scene_id = reservation.scene_id
    response_path: str | None = None
    response_sha256: str | None = None
    result: Study3TransportResult | None = None
    receipt: dict[str, Any] | None = None
    response_document: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    reason_code: str | None = None
    forced_stop = False

    try:
        context = _create_reserved_dispatch_context(
            owner_token,
            attempt_number=reservation.attempt_number,
            scene_id=scene_id,
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
        if type(raw_result) is not Study3TransportResult:
            raise OpenRouterTransportError("transport result invalid")
        result = raw_result
    except Exception:
        reason_code = "TRANSPORT_FAILED"
        forced_stop = True

    if result is not None:
        if type(result.body) is not bytes or len(result.body) > MAX_RESPONSE_BYTES:
            reason_code = "RESPONSE_MISSING_OR_OVERSIZED"
            forced_stop = True
        else:
            response_sha256 = hashlib.sha256(result.body).hexdigest()
            try:
                response_path = _write_private_response(
                    response_root,
                    attempt_number=reservation.attempt_number,
                    scene_id=scene_id,
                    body=result.body,
                )
            except Study3RunnerBlocked:
                reason_code = "RESPONSE_PERSIST_FAILED"
                forced_stop = True
            response_document, receipt, metadata = _response_bound_receipt(
                result,
                reservation,
                response_sha256,
            )

    if result is None:
        outcome = "STOPPED"
        http_status = None
        model_id = None
        provider = None
        generation_id = None
        usage: tuple[tuple[str, int], ...] = ()
    else:
        http_status = result.http_status if type(result.http_status) is int else None
        model_id = metadata.get("returned_model_id") if metadata else None
        provider = metadata.get("upstream_provider") if metadata else None
        generation_id = metadata.get("generation_id") if metadata else None
        usage = tuple(sorted((metadata.get("usage") or {}).items())) if metadata else ()
        if forced_stop:
            outcome = "STOPPED"
        elif http_status != 200:
            outcome = "STOPPED"
            reason_code = "HTTP_STATUS_NOT_200"
        elif not _valid_provider_identity(metadata):
            outcome = "STOPPED"
            reason_code = "PROVIDER_IDENTITY_OR_USAGE_INVALID"
        else:
            try:
                delta_bytes = _extract_delta_bytes(response_document)
                gate_report = newhydration.validate_delta_output(
                    delta_bytes,
                    scene_id=scene_id,
                )
                gate_passed = gate_report.deterministic_status == "PASS"
            except Exception:
                gate_passed = False
            if gate_passed:
                outcome = "ACCEPTED"
            else:
                outcome = "CONTRACT_FAILURE"
                reason_code = "OUTPUT_CONTRACT_FAILURE"

    attempt_result = Study3AttemptResult(
        scene_id=scene_id,
        attempt_number=reservation.attempt_number,
        outcome=outcome,
        stop_study=forced_stop or outcome == "STOPPED",
        reason_code=reason_code,
        http_status=http_status,
        request_sha256=request_sha256,
        transport_request_sha256=transport_request_sha256,
        response_sha256=response_sha256,
        response_relative_path=response_path,
        metadata_relative_path=None,
        returned_model_id=model_id,
        upstream_provider=provider,
        generation_id=generation_id,
        usage=usage,
        actual_cost_status="PENDING",
        actual_cost_usd=None,
    )
    metadata_path = _write_attempt_metadata(response_root, attempt_result)
    if metadata_path is None:
        outcome = "STOPPED"
        reason_code = "ATTEMPT_METADATA_PERSIST_FAILED"

    try:
        completion: Study3Completion = ledger.complete(
            reservation,
            outcome=outcome,
            reported_cost_usd=receipt["cost_usd"] if receipt is not None else None,
            cost_receipt=receipt,
        )
    except Study3LedgerError as error:
        raise Study3RunnerBlocked(error.code) from None

    if completion.actual_cost_status != "RECONCILED":
        reason_code = reason_code or "ACTUAL_COST_UNRESOLVED"
    elif completion.stop_study and outcome != "STOPPED":
        reason_code = reason_code or "REMAINING_BUDGET_UNSAFE"
    if completion.stop_study and outcome == "CONTRACT_FAILURE" and reason_code is None:
        reason_code = "CONTRACT_FAILURE_STOPPED"

    return Study3AttemptResult(
        **{
            **attempt_result.__dict__,
            "outcome": outcome,
            "stop_study": completion.stop_study,
            "reason_code": reason_code,
            "actual_cost_status": completion.actual_cost_status,
            "actual_cost_usd": completion.actual_cost_usd,
            "metadata_relative_path": metadata_path,
        }
    )


def _response_bound_receipt(
    result: Study3TransportResult,
    reservation: object,
    response_sha256: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None]:
    try:
        document = _parse_provider_json(result.body)
    except (UnicodeError, ValueError, json.JSONDecodeError, RecursionError):
        return None, None, None
    if type(document) is not dict:
        return document if type(document) is dict else None, None, None
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
        and value >= 0
    }
    if (
        type(returned_model) is not str
        or type(upstream_provider) is not str
        or type(generation_id) is not str
        or returned_model != result.returned_model_id
        or upstream_provider != result.upstream_provider
        or generation_id != result.generation_id
        or type(result.usage) is not dict
        or result.usage != transport_usage
    ):
        return document, None, None
    if (
        returned_model != protocol.MODEL_ID
        or _PROVIDER_RE.fullmatch(upstream_provider) is None
        or upstream_provider.casefold() in {"unknown", "none", "n/a", "unset"}
        or _GENERATION_ID_RE.fullmatch(generation_id) is None
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
    if any(value > 2_147_483_647 for value in safe_usage.values()):
        return document, None, None
    safe_metadata = {
        "returned_model_id": returned_model,
        "upstream_provider": upstream_provider,
        "generation_id": generation_id,
        "usage": safe_usage,
    }
    cost_string = _provider_cost_string(usage.get("cost"))
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
    if (
        cost_string is None
        or type(prompt_tokens) is not int
        or prompt_tokens < 0
        or type(completion_tokens) is not int
        or completion_tokens < 0
        or type(reasoning_tokens) is not int
        or reasoning_tokens < 0
        or reasoning_tokens > completion_tokens
    ):
        return document, None, safe_metadata

    receipt = {
        "receipt_id": generation_id,
        "study_id": protocol.STUDY_ID,
        "manifest_sha256": reservation.manifest_sha256,
        "scene_id": reservation.scene_id,
        "attempt_number": reservation.attempt_number,
        "request_sha256": reservation.request_sha256,
        "response_sha256": response_sha256,
        "returned_model_id": returned_model,
        "upstream_provider": upstream_provider,
        "generation_id": generation_id,
        "cost_usd": cost_string,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "reasoning_tokens": reasoning_tokens,
    }
    return document, receipt, safe_metadata


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
        or max(0, -parts.exponent) > _MAX_COST_DECIMAL_PLACES
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


def _valid_provider_identity(value: object) -> bool:
    if type(value) is not dict:
        return False
    provider = value.get("upstream_provider")
    generation_id = value.get("generation_id")
    usage = value.get("usage")
    return (
        value.get("returned_model_id") == protocol.MODEL_ID
        and type(provider) is str
        and _PROVIDER_RE.fullmatch(provider) is not None
        and provider.casefold() not in {"unknown", "none", "n/a", "unset"}
        and type(generation_id) is str
        and _GENERATION_ID_RE.fullmatch(generation_id) is not None
        and type(usage) is dict
    )


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
    if type(choices) is not list or not choices or type(choices[0]) is not dict:
        return b""
    message = choices[0].get("message")
    if type(message) is not dict or type(message.get("content")) is not str:
        return b""
    return message["content"].encode("utf-8")


def _write_private_response(
    response_root: Path,
    *,
    attempt_number: int,
    scene_id: str,
    body: bytes,
) -> str:
    name = "%02d_" % attempt_number + scene_id.replace(":", "__") + ".response.json"
    return _write_private_artifact(response_root, name, body)


def _write_attempt_metadata(
    response_root: Path,
    attempt: Study3AttemptResult,
) -> str | None:
    name = "%02d_" % attempt.attempt_number + attempt.scene_id.replace(":", "__") + ".metadata.json"
    record = {
        "schema": "neq.llm_staging_study3_attempt_metadata.v1",
        "study_id": protocol.STUDY_ID,
        "scene_id": attempt.scene_id,
        "attempt_number": attempt.attempt_number,
        "outcome": attempt.outcome,
        "reason_code": attempt.reason_code,
        "http_status": attempt.http_status,
        "request_sha256": attempt.request_sha256,
        "transport_request_sha256": attempt.transport_request_sha256,
        "response_sha256": attempt.response_sha256,
        "response_relative_path": attempt.response_relative_path,
        "returned_model_id": attempt.returned_model_id,
        "upstream_provider": attempt.upstream_provider,
        "generation_id": attempt.generation_id,
        "usage": {key: value for key, value in attempt.usage},
    }
    try:
        raw = json.dumps(
            record,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
        return _write_private_artifact(response_root, name, raw)
    except (TypeError, ValueError, UnicodeEncodeError, Study3RunnerBlocked):
        return None


def _write_private_artifact(response_root: Path, name: str, body: bytes) -> str:
    root_fd = _open_private_directory(response_root)
    descriptor: int | None = None
    try:
        descriptor = os.open(
            name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | _FILE_NOFOLLOW,
            0o600,
            dir_fd=root_fd,
        )
        os.fchmod(descriptor, 0o600)
        _verify_private_file(root_fd, name, descriptor)
        _write_all(descriptor, body)
        os.fsync(descriptor)
        _verify_private_file(root_fd, name, descriptor)
        os.fsync(root_fd)
    except FileExistsError:
        raise Study3RunnerBlocked("RESPONSE_ARTIFACT_ALREADY_EXISTS") from None
    except Study3RunnerBlocked:
        raise
    except OSError:
        raise Study3RunnerBlocked("RESPONSE_PERSIST_FAILED") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(root_fd)
    return (response_root / name).relative_to(protocol.REPO_ROOT).as_posix()


def _open_private_directory(path: Path) -> int:
    try:
        candidate = Path(os.path.abspath(path))
        relative = candidate.relative_to(protocol.REPO_ROOT)
        prep_parts = tuple(PREP_ROOT_RELATIVE.split("/"))
        if (
            relative.parts[: len(prep_parts)] != prep_parts
            or len(relative.parts) <= len(prep_parts)
            or any(part in ("", ".", "..") for part in relative.parts)
        ):
            raise Study3RunnerBlocked("RESPONSE_ROOT_OUTSIDE_STUDY3_PREP")
    except (OSError, ValueError, TypeError):
        raise Study3RunnerBlocked("RESPONSE_ROOT_INVALID") from None

    descriptor = os.open(protocol.REPO_ROOT, _ROOT_FLAGS)
    try:
        if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise Study3RunnerBlocked("RESPONSE_ROOT_INVALID")
        for index, part in enumerate(relative.parts):
            try:
                before = os.stat(part, dir_fd=descriptor, follow_symlinks=False)
            except FileNotFoundError:
                try:
                    os.mkdir(part, 0o700, dir_fd=descriptor)
                    os.fsync(descriptor)
                    before = os.stat(part, dir_fd=descriptor, follow_symlinks=False)
                except OSError:
                    raise Study3RunnerBlocked("RESPONSE_ROOT_CREATE_FAILED") from None
            if stat.S_ISLNK(before.st_mode) or not stat.S_ISDIR(before.st_mode):
                raise Study3RunnerBlocked("RESPONSE_ROOT_UNSAFE")
            try:
                child = os.open(part, _ROOT_FLAGS, dir_fd=descriptor)
            except OSError:
                raise Study3RunnerBlocked("RESPONSE_ROOT_UNSAFE") from None
            try:
                opened = os.fstat(child)
                named = os.stat(part, dir_fd=descriptor, follow_symlinks=False)
            except OSError:
                os.close(child)
                raise Study3RunnerBlocked("RESPONSE_ROOT_UNSAFE") from None
            if (
                not stat.S_ISDIR(opened.st_mode)
                or stat.S_ISLNK(named.st_mode)
                or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)
            ):
                os.close(child)
                raise Study3RunnerBlocked("RESPONSE_ROOT_UNSAFE")
            if hasattr(os, "geteuid") and opened.st_uid != os.geteuid():
                os.close(child)
                raise Study3RunnerBlocked("RESPONSE_ROOT_OWNER_INVALID")
            if index == len(relative.parts) - 1:
                try:
                    os.fchmod(child, 0o700)
                except OSError:
                    os.close(child)
                    raise Study3RunnerBlocked(
                        "RESPONSE_ROOT_PERMISSIONS_INVALID"
                    ) from None
                final_mode = os.fstat(child).st_mode
                if final_mode & 0o077 or final_mode & 0o700 != 0o700:
                    os.close(child)
                    raise Study3RunnerBlocked("RESPONSE_ROOT_PERMISSIONS_INVALID")
            os.close(descriptor)
            descriptor = child
        return descriptor
    except Study3RunnerBlocked:
        os.close(descriptor)
        raise
    except OSError:
        os.close(descriptor)
        raise Study3RunnerBlocked("RESPONSE_ROOT_UNSAFE") from None
    except BaseException:
        os.close(descriptor)
        raise


def _verify_private_file(root_fd: int, name: str, descriptor: int) -> None:
    opened = os.fstat(descriptor)
    try:
        named = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
    except OSError:
        raise Study3RunnerBlocked("RESPONSE_FILE_UNSAFE") from None
    if (
        not stat.S_ISREG(opened.st_mode)
        or stat.S_ISLNK(named.st_mode)
        or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)
        or opened.st_nlink != 1
        or opened.st_mode & 0o077
        or opened.st_mode & 0o600 != 0o600
        or (hasattr(os, "geteuid") and opened.st_uid != os.geteuid())
    ):
        raise Study3RunnerBlocked("RESPONSE_FILE_UNSAFE")


def _write_all(descriptor: int, body: bytes) -> None:
    position = 0
    while position < len(body):
        written = os.write(descriptor, body[position:])
        if written <= 0:
            raise OSError("short response write")
        position += written


def _canonical_request_bytes(request: dict[str, Any]) -> bytes:
    try:
        return json.dumps(
            request,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError, UnicodeEncodeError):
        raise Study3RunnerBlocked("STUDY3_REQUEST_SERIALIZATION_INVALID") from None


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate response key")
        result[key] = value
    return result


def _reject_nonfinite(_value: str) -> None:
    raise ValueError("non-finite response number")


__all__ = [
    "Study3AttemptResult",
    "Study3RunResult",
    "Study3Runner",
    "Study3RunnerBlocked",
    "Study3SyntheticHTTP",
    "Study3TransportResult",
]
