# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Combat Decision Stages - Provider-free combat decision boundaries.
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

This software is free for non-commercial and educational use.
Commercial competing use is prohibited for 2 years from release.
See LICENSE file for full terms.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, Optional, Tuple


class PCActionDecisionStatus(str, Enum):
    """Outcome of the deterministic PC-action decision stage."""

    HANDLED = "handled"
    DECLINED = "declined"
    UNAVAILABLE = "unavailable"


ParseResult = Dict[str, Any]
ParserFunctions = Tuple[Callable[..., ParseResult], Callable[..., bool]]


@dataclass(frozen=True)
class PCActionDecisionResult:
    """Typed stage output; declined and unavailable both fall through to LLM."""

    status: PCActionDecisionStatus
    actor_name: str
    parse_result: Optional[ParseResult] = None
    import_error: Optional[ImportError] = None


def resolve_pc_action_actor(
    input_actor_name: Optional[str],
    multi_pc_manager: Any,
    party_tracker_data: Dict[str, Any],
) -> str:
    """Keep the established explicit-input, manager, tracker actor precedence."""
    return (
        input_actor_name
        or (multi_pc_manager.current_pc_name if multi_pc_manager else None)
        or party_tracker_data.get("active_character", "Player")
    )


def pc_action_decision_eligible(
    *,
    enabled: bool,
    multi_pc_manager: Any,
    clean_input: str,
    cmd: str,
) -> bool:
    """Apply the existing flag, slash, backslash, and PC_PHASE eligibility gate."""
    return bool(
        multi_pc_manager
        and enabled
        and not clean_input.startswith("/")
        and not cmd.startswith("\\")
        and multi_pc_manager.combat_phase == "PC_PHASE"
    )


def _load_pc_action_parser() -> ParserFunctions:
    """Resolve parser dependencies only when an eligible decision is requested."""
    from utils.combat_pc_action_parser import (
        apply_pc_phase_parse_result,
        parse_pc_phase_action,
    )

    return parse_pc_phase_action, apply_pc_phase_parse_result


def run_pc_action_decision(
    *,
    eligible: bool,
    clean_input: str,
    encounter_data: Dict[str, Any],
    party_tracker_data: Dict[str, Any],
    actor_name: str,
    multi_pc_manager: Any,
    encounter_id: Optional[str],
    decision_started_at: float,
    trace_decision: Callable[..., Any],
    parser_loader: Callable[[], ParserFunctions] = _load_pc_action_parser,
) -> PCActionDecisionResult:
    """Run the existing local parser/apply path or return an explicit fallthrough.

    This boundary makes no model/provider request. ImportError retains the
    existing debug/fallback behavior; all other unexpected exceptions propagate.
    """
    if not eligible:
        return PCActionDecisionResult(
            PCActionDecisionStatus.UNAVAILABLE, actor_name
        )

    try:
        parse_action, apply_result = parser_loader()
        parse_result = parse_action(
            clean_input,
            encounter_data,
            party_tracker_data,
            actor_name=actor_name,
        )
        if not parse_result.get("handled"):
            trace_decision(
                "pc_phase_parser",
                "llm_fallback",
                decision_started_at,
                False,
                outcome="miss",
                llm_fallback=True,
            )
            return PCActionDecisionResult(
                PCActionDecisionStatus.DECLINED, actor_name, parse_result
            )

        if not apply_result(
            parse_result,
            multi_pc_manager,
            encounter_data,
            encounter_id,
            actor_name,
        ):
            trace_decision(
                "pc_phase_parser",
                "llm_fallback",
                decision_started_at,
                False,
                outcome="false_positive",
                llm_fallback=True,
            )
            return PCActionDecisionResult(
                PCActionDecisionStatus.DECLINED, actor_name, parse_result
            )

        trace_decision(
            "pc_phase_parser",
            "deterministic",
            decision_started_at,
            True,
            outcome="hit",
            llm_fallback=False,
        )
        return PCActionDecisionResult(
            PCActionDecisionStatus.HANDLED, actor_name, parse_result
        )
    except ImportError as exc:
        trace_decision(
            "pc_phase_parser",
            "llm_fallback",
            decision_started_at,
            False,
            outcome="unavailable",
            llm_fallback=True,
        )
        return PCActionDecisionResult(
            PCActionDecisionStatus.UNAVAILABLE,
            actor_name,
            import_error=exc,
        )
