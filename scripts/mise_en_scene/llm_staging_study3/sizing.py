# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free Study 3 sizing, historical pricing, and fail-closed checks."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import stat
from typing import Any

from . import protocol
from .newrequest import build_request


RATE_LISTING_PATH = (
    "tmp/router-rollout/mapping-pilot/mise-en-scene-offline/llm-staging/"
    "availability-check/model-listing.json"
)
RATE_LISTING_BYTES = 829400
RATE_LISTING_SHA256 = "d94d8370997bb6a32c8265d0c5368d98c121355ebed0c51698539d81e32bdc13"
PROMPT_RATE = "0.0000001"
COMPLETION_RATE = "0.0000005"
HARD_CEILING_USD = Decimal("0.05")
MAX_TOKENS = 16384
EXPECTED_COMPLETION_TOKENS = (3042, 3777, 2575)
STUDY2_USAGE_SOURCE_PATH = (
    "tmp/router-rollout/mapping-pilot/mise-en-scene-offline/llm-staging-study2/"
    "runs/study2-20261109T210130Z/primary-audit.json"
)
STUDY2_USAGE_SOURCE_SHA256 = "598a2291f5829ffbc68e4f2806d8ade66de16cbf6ceb8f217a8a6d06f69d5f51"


class SizingBlocked(ValueError):
    """Pricing or cost validation is unavailable or unsafe."""


def _safe_local_read(relative_path: str) -> bytes:
    """Read a project-relative regular file without traversing symlink paths."""

    path = Path(relative_path)
    if path.is_absolute() or path.as_posix() != relative_path or any(
        part in ("", ".", "..") for part in relative_path.split("/")
    ):
        raise SizingBlocked("UNPRICED/BLOCKED: invalid local path")
    root = protocol.REPO_ROOT.resolve(strict=True)
    current = root
    try:
        for part in path.parts:
            current = current / part
            if stat.S_ISLNK(current.lstat().st_mode):
                raise SizingBlocked("UNPRICED/BLOCKED: symlink path")
        resolved = current.resolve(strict=True)
        resolved.relative_to(root)
        if not stat.S_ISREG(resolved.stat().st_mode):
            raise SizingBlocked("UNPRICED/BLOCKED: not a regular file")
        return resolved.read_bytes()
    except SizingBlocked:
        raise
    except (OSError, RuntimeError, ValueError):
        raise SizingBlocked("UNPRICED/BLOCKED: historical rates unavailable") from None


def _parse_rate_listing(raw: bytes) -> tuple[str, str]:
    if len(raw) != RATE_LISTING_BYTES:
        raise SizingBlocked("UNPRICED/BLOCKED: historical rate listing size mismatch")
    if hashlib.sha256(raw).hexdigest() != RATE_LISTING_SHA256:
        raise SizingBlocked("UNPRICED/BLOCKED: historical rate hash mismatch")
    try:
        document = json.loads(raw.decode("utf-8"), parse_constant=_reject_constant)
        rows = [row for row in document["data"] if row.get("id") == protocol.MODEL_ID]
        if len(rows) != 1:
            raise ValueError
        pricing = rows[0]["pricing"]
        prompt, completion = pricing["prompt"], pricing["completion"]
        if type(prompt) is not str or type(completion) is not str:
            raise ValueError
        _decimal_rate(prompt)
        _decimal_rate(completion)
        if prompt != PROMPT_RATE or completion != COMPLETION_RATE:
            raise ValueError
        return prompt, completion
    except (UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError, RecursionError):
        raise SizingBlocked("UNPRICED/BLOCKED: historical rate record invalid") from None


def _reject_constant(_value: str) -> None:
    raise ValueError("non-finite JSON")


def _decimal_rate(value: object) -> Decimal:
    if type(value) is not str:
        raise SizingBlocked("UNPRICED/BLOCKED: rates must be decimal strings")
    try:
        result = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        raise SizingBlocked("UNPRICED/BLOCKED: invalid decimal rate") from None
    if not result.is_finite() or result < 0:
        raise SizingBlocked("UNPRICED/BLOCKED: invalid decimal rate")
    return result


def _cost(input_tokens: int, output_tokens: int, prompt_rate: str, completion_rate: str) -> Decimal:
    if type(input_tokens) is not int or type(output_tokens) is not int or min(input_tokens, output_tokens) < 0:
        raise SizingBlocked("UNPRICED/BLOCKED: invalid token counts")
    return Decimal(input_tokens) * _decimal_rate(prompt_rate) + Decimal(output_tokens) * _decimal_rate(completion_rate)


def _canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, RecursionError):
        raise SizingBlocked("UNPRICED/BLOCKED: request cannot be serialized") from None


def _sizing_rows() -> tuple[list[dict[str, Any]], str, str]:
    prompt_rate, completion_rate = _parse_rate_listing(_safe_local_read(RATE_LISTING_PATH))
    manifest = protocol._load_manifest()
    refs = {row["scene_id"]: row for row in manifest["references"]}
    rows = []
    for scene_id, completion_tokens in zip(protocol.SCENE_ORDER, EXPECTED_COMPLETION_TOKENS):
        request = build_request(scene_id)
        messages = request["messages"]
        message_bytes = sum(len(message["content"].encode("utf-8")) for message in messages)
        wire = _canonical_json(request)
        # Approximation only: ceil complete rendered wire bytes / 3; not tokenizer output.
        prompt_tokens = (len(wire) + 2) // 3
        conservative_prompt_proxy = (len(wire) + 2) // 3
        expected = _cost(prompt_tokens, completion_tokens, prompt_rate, completion_rate)
        conservative = _cost(conservative_prompt_proxy, MAX_TOKENS, prompt_rate, completion_rate)
        reference = refs[scene_id]
        reference_bytes = _safe_local_read(reference["path"])
        if hashlib.sha256(reference_bytes).hexdigest() != reference["sha256"]:
            raise SizingBlocked("UNPRICED/BLOCKED: reference hash mismatch")
        rows.append({
            "scene_id": scene_id,
            "request_message_utf8_bytes": message_bytes,
            "canonical_request_wire_utf8_bytes": len(wire),
            "request_sha256": hashlib.sha256(wire).hexdigest(),
            "reference_path": reference["path"],
            "reference_utf8_bytes": len(reference_bytes),
            "reference_sha256": reference["sha256"],
            "expected_prompt_tokens_approx": prompt_tokens,
            "expected_completion_tokens_observed_study2": completion_tokens,
            "conservative_input_tokens_approx": conservative_prompt_proxy,
            "conservative_output_tokens": MAX_TOKENS,
            "expected_cost_usd_estimate": str(expected),
            "conservative_cost_usd_estimate": str(conservative),
        })
    return rows, prompt_rate, completion_rate


def build_sizing_report() -> dict[str, Any]:
    rows, prompt_rate, completion_rate = _sizing_rows()
    expected_total = sum((Decimal(row["expected_cost_usd_estimate"]) for row in rows), Decimal(0))
    conservative_total = sum((Decimal(row["conservative_cost_usd_estimate"]) for row in rows), Decimal(0))
    return {
        "schema": "neq.llm_staging_study3_sizing_report.v1",
        "status": "ESTIMATE",
        "study_id": protocol.STUDY_ID,
        "scene_order": list(protocol.SCENE_ORDER),
        "rates": {
            "source_path": RATE_LISTING_PATH,
            "source_sha256": RATE_LISTING_SHA256,
            "model_id": protocol.MODEL_ID,
            "prompt_usd_per_token_historical": prompt_rate,
            "completion_usd_per_token_historical": completion_rate,
            "attestation_performed_utc": "2026-11-09T03:48:13Z",
            "historical_not_current_availability": True,
        },
        "expected_completion_usage_provenance": {
            "source_path": STUDY2_USAGE_SOURCE_PATH,
            "source_sha256": STUDY2_USAGE_SOURCE_SHA256,
            "classification": "FROZEN_STUDY2_RECORDED_OBSERVATIONS_NOT_LIVE_UNIT_RATES",
            "completion_tokens_in_scene_order": list(EXPECTED_COMPLETION_TOKENS),
            "reasoning_tokens_are_included_in_completion_tokens": True,
            "verification": "Pinned metadata provenance only; no runtime audit read is required.",
        },
        "formula": {
            "expected": "ceil(canonical_request_wire_utf8_bytes / 3) * historical prompt rate + Study 2 primary-audit per-scene completion_tokens * historical completion rate; reasoning is included in completion_tokens",
            "conservative": "ceil(canonical_request_wire_utf8_bytes / 3) input-token proxy + 16384 output tokens, at historical rates; proxy is not a guaranteed tokenizer upper bound",
            "tokenizer": "APPROXIMATE ceil(bytes/3); no tokenizer was invoked",
            "limitations": ["Historical rates may change; this is not a quote or price guarantee.", "Byte/token proxies are estimates and do not account for provider-specific framing/tokenization with certainty."],
        },
        "generation_envelope": {"attempt_cap": 3, "max_tokens_per_attempt": MAX_TOKENS, "timeout_seconds": 720},
        "scenes": rows,
        "expected_total_usd_estimate": str(expected_total),
        "conservative_total_usd_estimate": str(conservative_total),
        "hard_ceiling_usd": "0.05",
        "future_preflight": "STRICTLY_BELOW_HARD_CEILING_REQUIRED",
        "actual_study3_cost_usd": None,
        "actual_study3_spend_usd": "0",
        "actual_cost_accounting": "NOT_APPLICABLE_NO_STUDY3_ATTEMPTS",
    }


def future_host_preflight(report: object) -> Decimal:
    """Rebuild from pinned local facts; never trust a caller-provided cost."""
    expected = build_sizing_report()
    if type(report) is not dict or report != expected:
        raise SizingBlocked("PREFLIGHT_BLOCKED: sizing report missing or mismatched")
    return _validate_preflight_sizing_report(expected)


def _fresh_preflight_sizing_report() -> tuple[dict[str, Any], Decimal]:
    """Build one report from pinned local inputs for incremental budget checks."""

    report = build_sizing_report()
    return report, _validate_preflight_sizing_report(report)


def _validate_preflight_sizing_report(report: object) -> Decimal:
    """Check report identity, per-scene estimates, and the full-envelope ceiling."""

    if (
        type(report) is not dict
        or report.get("schema") != "neq.llm_staging_study3_sizing_report.v1"
        or report.get("status") != "ESTIMATE"
        or report.get("study_id") != protocol.STUDY_ID
        or report.get("scene_order") != list(protocol.SCENE_ORDER)
        or report.get("hard_ceiling_usd") != str(HARD_CEILING_USD)
        or report.get("future_preflight") != "STRICTLY_BELOW_HARD_CEILING_REQUIRED"
        or report.get("generation_envelope")
        != {"attempt_cap": 3, "max_tokens_per_attempt": MAX_TOKENS, "timeout_seconds": 720}
    ):
        raise SizingBlocked("PREFLIGHT_BLOCKED: sizing report identity mismatch")
    rates = report.get("rates")
    if (
        type(rates) is not dict
        or rates.get("source_path") != RATE_LISTING_PATH
        or rates.get("source_sha256") != RATE_LISTING_SHA256
        or rates.get("model_id") != protocol.MODEL_ID
        or rates.get("prompt_usd_per_token_historical") != PROMPT_RATE
        or rates.get("completion_usd_per_token_historical") != COMPLETION_RATE
        or rates.get("historical_not_current_availability") is not True
    ):
        raise SizingBlocked("PREFLIGHT_BLOCKED: sizing report rate pins mismatch")
    rows = report.get("scenes")
    if type(rows) is not list or len(rows) != len(protocol.SCENE_ORDER):
        raise SizingBlocked("PREFLIGHT_BLOCKED: per-scene estimates unavailable")
    per_scene: list[Decimal] = []
    for scene_id, row in zip(protocol.SCENE_ORDER, rows):
        if type(row) is not dict or row.get("scene_id") != scene_id:
            raise SizingBlocked("PREFLIGHT_BLOCKED: per-scene estimate identity mismatch")
        amount = _decimal_rate(row.get("conservative_cost_usd_estimate"))
        per_scene.append(amount)
    conservative = sum(per_scene, Decimal(0))
    if (
        type(report.get("conservative_total_usd_estimate")) is not str
        or _decimal_rate(report["conservative_total_usd_estimate"]) != conservative
        or conservative >= HARD_CEILING_USD
    ):
        raise SizingBlocked("PREFLIGHT_BLOCKED: conservative total is not strictly below ceiling")
    return conservative


def validate_actual_cost_accounting(expected_receipts: object, actual_accounting: object) -> Decimal:
    """Validate all completed synthetic receipts, without maintaining a real ledger."""
    if (
        type(expected_receipts) is not list
        or len(expected_receipts) > 3
        or type(actual_accounting) is not dict
    ):
        raise SizingBlocked("ACTUAL_COST_STOP: missing or pending accounting")
    if not expected_receipts:
        if (
            actual_accounting.get("status") != "NOT_APPLICABLE_NO_STUDY3_ATTEMPTS"
            or actual_accounting.get("receipts") != []
            or actual_accounting.get("reported_total_usd") != "0"
        ):
            raise SizingBlocked("ACTUAL_COST_STOP: empty accounting is not an unattempted study")
        return Decimal(0)
    if actual_accounting.get("status") != "COMPLETE" or type(actual_accounting.get("receipts")) is not list:
        raise SizingBlocked("ACTUAL_COST_STOP: missing or pending accounting")
    trusted: dict[str, tuple[Decimal, tuple[int, int, int] | None]] = {}
    usage_fields = {"prompt_tokens", "completion_tokens", "reasoning_tokens"}
    for item in expected_receipts:
        if (
            type(item) is not dict
            or type(item.get("receipt_id")) is not str
            or not item["receipt_id"]
            or item["receipt_id"] in trusted
            or type(item.get("cost_usd")) is not str
        ):
            raise SizingBlocked("ACTUAL_COST_STOP: malformed trusted receipt")
        expected_cost = _decimal_rate(item["cost_usd"])
        present = usage_fields.intersection(item)
        expected_usage = None
        if present:
            if present != usage_fields or any(
                type(item[field]) is not int or item[field] < 0 for field in usage_fields
            ) or item["reasoning_tokens"] > item["completion_tokens"]:
                raise SizingBlocked("ACTUAL_COST_STOP: malformed trusted usage")
            expected_usage = (
                item["prompt_tokens"], item["completion_tokens"], item["reasoning_tokens"]
            )
        trusted[item["receipt_id"]] = (expected_cost, expected_usage)
    receipts = actual_accounting["receipts"]
    if len(trusted) != len(expected_receipts) or len(receipts) != len(expected_receipts):
        raise SizingBlocked("ACTUAL_COST_STOP: incomplete receipt set")
    total = Decimal(0)
    seen: set[str] = set()
    for receipt in receipts:
        if type(receipt) is not dict or type(receipt.get("receipt_id")) is not str or receipt["receipt_id"] in seen:
            raise SizingBlocked("ACTUAL_COST_STOP: receipt identity mismatch")
        if receipt["receipt_id"] not in trusted or type(receipt.get("cost_usd")) is not str:
            raise SizingBlocked("ACTUAL_COST_STOP: receipt identity mismatch")
        present_usage = usage_fields.intersection(receipt)
        if present_usage:
            if present_usage != usage_fields or any(
                type(receipt[field]) is not int or receipt[field] < 0
                for field in usage_fields
            ) or receipt["reasoning_tokens"] > receipt["completion_tokens"]:
                raise SizingBlocked("ACTUAL_COST_STOP: invalid or double-counted usage")
            # Reasoning tokens are a subset of completion_tokens, never an added charge.
        amount = _decimal_rate(receipt["cost_usd"])
        expected_amount, expected_usage = trusted[receipt["receipt_id"]]
        actual_usage = None
        if present_usage:
            actual_usage = (
                receipt["prompt_tokens"], receipt["completion_tokens"], receipt["reasoning_tokens"]
            )
        if amount != expected_amount or actual_usage != expected_usage:
            raise SizingBlocked("ACTUAL_COST_STOP: receipt cost or usage mismatch")
        seen.add(receipt["receipt_id"])
        total += amount
    if seen != set(trusted) or type(actual_accounting.get("reported_total_usd")) is not str:
        raise SizingBlocked("ACTUAL_COST_STOP: receipt set mismatch")
    reported = _decimal_rate(actual_accounting["reported_total_usd"])
    if total != reported:
        raise SizingBlocked("ACTUAL_COST_STOP: actual total mismatch")
    if total >= HARD_CEILING_USD:
        raise SizingBlocked("ACTUAL_COST_STOP: actual total reaches or exceeds hard ceiling")
    return total


__all__ = ["SizingBlocked", "build_sizing_report", "future_host_preflight", "validate_actual_cost_accounting"]
