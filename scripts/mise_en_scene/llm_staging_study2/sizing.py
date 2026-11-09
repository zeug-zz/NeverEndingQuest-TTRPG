# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Offline, deterministic size and cost calculations for Study 2."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
import json
from typing import Any


def approximate_tokens(text: str) -> int:
    """Conservatively approximate tokens as ceil(UTF-8 bytes / 3)."""
    size = len(text.encode("utf-8"))
    return (size + 2) // 3


def sizing_proposal(estimates: dict[str, int]) -> dict[str, int]:
    if len(estimates) != 3 or any(type(value) is not int or value < 0 for value in estimates.values()):
        raise ValueError("exactly three nonnegative integer estimates required")
    largest = max(estimates.values())
    maximum = 1024 * ((3 * largest + 2048 + 1023) // 1024)
    timeout = 60 * (((maximum + 24) // 25 + 60 + 59) // 60)
    return {"largest_estimate": largest, "max_tokens": maximum, "timeout_seconds": timeout}


def cost_estimate(input_tokens: int, output_tokens: int, prompt_rate: str, completion_rate: str) -> Decimal:
    """Return exact Decimal arithmetic from historical per-token USD rates."""
    try:
        if type(input_tokens) is not int or type(output_tokens) is not int:
            raise ValueError
        if input_tokens < 0 or output_tokens < 0:
            raise ValueError
        if type(prompt_rate) is not str or type(completion_rate) is not str:
            raise ValueError
        prompt = Decimal(prompt_rate)
        completion = Decimal(completion_rate)
        if not prompt.is_finite() or not completion.is_finite() or prompt < 0 or completion < 0:
            raise ValueError
        result = Decimal(input_tokens) * prompt + Decimal(output_tokens) * completion
        if not result.is_finite():
            raise ValueError
        return result
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("UNPRICED/BLOCKED: invalid token count or historical unit rate") from None


def json_bytes(value: Any) -> bytes:
    """Canonical report JSON serialization with NaN/Infinity forbidden."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
