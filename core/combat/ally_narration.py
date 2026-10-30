# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Constrained narration for one completed allied-NPC batch."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any, Optional

from core.combat.ally_controller import latest_ally_directives_from_history
from core.combat.enemy_narration import (
    NarrationResult,
    _check_narration,
    _ledger_payload,
    _log_rejected_narration,
    _response_text,
    build_enemy_batch_template_narration,
)
from core.combat.enemy_resolution import EnemyResolutionLedger


_MAX_ALLY_NARRATION_CONTENT_CHARS = 32000
_ALLY_NARRATION_SYSTEM_PROMPT = (
    "You narrate one completed allied-NPC combat batch. The authoritative "
    "ledger in the user message is final. Narrate only its actors, targets, "
    "actions, rolls, and outcomes, in ledger order. Describe every state-"
    "changing outcome and do not add combatants, mechanics, hit points, or "
    "effects absent from the ledger. A named directive is guidance only; you "
    "may include a brief in-character reply from that named ally, but it must "
    "not claim that the directive forced an action or that an unapplied effect "
    "occurred. Do not quote directive text. Write concise natural prose only."
)


def _template_result(ledger: EnemyResolutionLedger, reason: str) -> NarrationResult:
    text = build_enemy_batch_template_narration(ledger)
    return NarrationResult(
        text=text or "The allies hold their ground.",
        source="template",
        reason_code="template_fallback",
        reason_detail=reason,
    )


def build_ally_batch_narration_messages(
    ledger: EnemyResolutionLedger,
    history: Any,
) -> list[dict[str, str]]:
    """Build a bounded narration request from only the applied ally ledger."""
    if not isinstance(ledger, EnemyResolutionLedger):
        raise TypeError("ledger must be a completed EnemyResolutionLedger")
    actors = tuple(
        dict.fromkeys(entry.actor.name for entry in ledger.entries)
    ) + tuple(
        update.enemy.name for update in ledger.cover_updates
        if update.enemy.name not in {
            entry.actor.name for entry in ledger.entries
        }
    )
    directives = latest_ally_directives_from_history(
        history,
        active_allies=actors,
    )
    user_payload = {
        "authoritative_ledger": _ledger_payload(ledger),
        "named_ally_directives": [
            {"actor": name, "directive": directive}
            for name, directive in directives.items()
        ],
    }
    content = json.dumps(
        user_payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    )
    if len(content) > _MAX_ALLY_NARRATION_CONTENT_CHARS:
        raise ValueError("ally_narration_payload_too_large")
    return [
        {"role": "system", "content": _ALLY_NARRATION_SYSTEM_PROMPT},
        {"role": "user", "content": content},
    ]


def narrate_ally_batch(
    ledger: EnemyResolutionLedger,
    history: Any,
    llm_call: Callable[..., Any],
    *,
    receipt_observer: Optional[Callable[..., Any]] = None,
) -> NarrationResult:
    """Make at most one narration request and accept only ledger-consistent prose."""
    if not isinstance(ledger, EnemyResolutionLedger):
        raise TypeError("ledger must be a completed EnemyResolutionLedger")
    try:
        messages = build_ally_batch_narration_messages(ledger, history)
    except ValueError as exc:
        if str(exc) == "enemy_narration_ledger_too_large":
            return _template_result(ledger, "ledger_too_large")
        if str(exc) == "ally_narration_payload_too_large":
            return _template_result(ledger, "payload_too_large")
        raise

    response = llm_call(
        "combat_main",
        messages,
        json_output=False,
        observer=receipt_observer,
    )
    text, parse_reason = _response_text(response)
    if parse_reason:
        _log_rejected_narration(response, parse_reason)
        return _template_result(ledger, parse_reason)
    reason = _check_narration(text or "", ledger, {})
    if reason:
        _log_rejected_narration(text or "", reason)
        return _template_result(ledger, reason)
    return NarrationResult(text=text or "", source="llm")
