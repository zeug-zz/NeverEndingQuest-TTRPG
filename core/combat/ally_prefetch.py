# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Bounded PC-phase prefetch lifecycle for conditional allied-NPC orders."""

from __future__ import annotations

import re
import threading
from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Optional

from core.combat.ally_controller import (
    ALLY_STANDING_ORDER_PARSE_FAILURE_CODES,
    AllyMenus,
    build_ally_menus,
    build_ally_standing_orders_messages,
    compile_ally_standing_orders,
    parse_ally_standing_orders_response_with_reason,
    rule_default_ally_plan,
    validate_ally_plan,
)
from core.combat.enemy_batch_apply import is_ally_prefetch_enabled
from core.combat.tactical_prefetch import (
    DEFAULT_PREFETCH_DEADLINE_SECONDS,
    TacticalPrefetchResult,
    TacticalPrefetchParseOutcome,
    TacticalPrefetchSubmission,
    consume_tactical_prefetch,
    has_tactical_prefetch_replan_submission,
    has_tactical_prefetch_submission,
    invalidate_tactical_prefetch,
    submit_tactical_prefetch,
    tactical_prefetch_replan_needed,
    tactical_roster_identity,
)
from utils import combat_latency_trace


MAX_ALLY_PREFETCH_BATCH_ID_CHARS = 64
MAX_ALLY_PREFETCH_TRACKED_BATCHES = 256
_ENCOUNTER_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,128}")
_BATCH_TRACKING_LOCK = threading.RLock()
_SELECTED_BATCHES: OrderedDict[tuple[str, str], None] = OrderedDict()
_REPLAN_BATCHES: OrderedDict[tuple[str, str], None] = OrderedDict()


@dataclass(frozen=True)
class AllyPrefetchSelection:
    """A selected background path and its no-wait, current-menu plan result."""

    selected: bool
    status: str
    plan: Any = None
    receipt_correlation_id: Optional[str] = None
    plan_origin: Optional[str] = None
    request_kind: Optional[str] = None
    prefetch_resolution: Optional[str] = None
    prefetch_rejection_reason: Optional[str] = None


def ally_prefetch_batch_id(encounter_id: Any, round_number: Any) -> Optional[str]:
    """Build an encounter/round identity distinct from the hostile batch ID."""
    if (
        not isinstance(encounter_id, str)
        or _ENCOUNTER_ID_RE.fullmatch(encounter_id) is None
        or not isinstance(round_number, int)
        or isinstance(round_number, bool)
        or round_number < 1
        or len(str(round_number)) > 12
    ):
        return None
    safe_id = encounter_id
    suffix = "-r%d-ally" % round_number
    prefix_limit = max(0, MAX_ALLY_PREFETCH_BATCH_ID_CHARS - len(suffix))
    bounded_id = safe_id[:prefix_limit].strip("_")
    return (bounded_id or "combat") + suffix


def _canonical_name(value: str) -> str:
    return " ".join(value.split()).casefold()


def _active_creature(creature: Mapping[str, Any]) -> bool:
    hp = creature.get("currentHitPoints", creature.get("hitPoints"))
    status = creature.get("status", "alive")
    departure = creature.get("defeatReason", creature.get("departureReason"))
    return (
        isinstance(hp, int)
        and not isinstance(hp, bool)
        and hp > 0
        and isinstance(status, str)
        and bool(status.strip())
        and status.strip().casefold() not in {
            "dead", "defeated", "departed", "fled", "surrendered",
            "inactive", "unconscious", "incapacitated", "stable",
        }
        and not (
            isinstance(departure, str)
            and departure.strip().casefold() in {"departed", "fled", "surrendered"}
        )
        and creature.get("active") is not False
        and creature.get("isActive") is not False
    )


def _ally_state_snapshot(
    encounter_data: Mapping[str, Any],
    ally_roster: list[str],
    pc_states: Any = None,
) -> Optional[dict[str, Any]]:
    """Retain only bounded roster, injury-band, commander, and PC state edges."""
    creatures = encounter_data.get("creatures")
    if (
        not isinstance(creatures, list)
        or len(creatures) > 128
        or (pc_states is not None and (
            not isinstance(pc_states, Mapping) or len(pc_states) > 32
        ))
    ):
        return None
    enemies: dict[str, dict[str, bool]] = {}
    pcs: dict[str, dict[str, bool]] = {}
    enemy_roster = []
    commander_rows = []
    targeted_pcs = []
    for creature in creatures:
        if not isinstance(creature, Mapping):
            return None
        name = creature.get("name")
        kind = creature.get("type")
        if not isinstance(name, str) or not name.strip() or len(name) > 128:
            continue
        key = _canonical_name(name)
        hp = creature.get("currentHitPoints", creature.get("hitPoints"))
        maximum = creature.get("maxHitPoints")
        if isinstance(hp, bool) or not isinstance(hp, int):
            hp = 0
        if isinstance(maximum, bool) or not isinstance(maximum, int) or maximum < 0:
            maximum = 0
        active = _active_creature(creature)
        if kind == "enemy":
            if key in enemies:
                return None
            enemies[key] = {
                "active": active,
                "bloodied": active and maximum > 0 and hp * 2 <= maximum,
                "near_death": active and maximum > 0 and hp * 4 <= maximum,
            }
            if active:
                enemy_roster.append(key)
            if creature.get("leader") is True and creature.get("tactics", "rule") == "commander":
                commander_rows.append(active)
        elif kind == "player":
            if key in pcs:
                return None
            pc_state = None
            if isinstance(pc_states, Mapping):
                matching_pc_states = [
                    value for pc_name, value in pc_states.items()
                    if isinstance(pc_name, str) and _canonical_name(pc_name) == key
                ]
                if len(matching_pc_states) > 1:
                    return None
                if matching_pc_states:
                    pc_state = matching_pc_states[0]
            pc_hp = (
                pc_state.get("current_hp", pc_state.get("hitPoints", hp))
                if isinstance(pc_state, Mapping)
                else getattr(pc_state, "current_hp", hp)
            )
            if isinstance(pc_hp, bool) or not isinstance(pc_hp, int):
                pc_hp = hp
            pcs[key] = {"active": active, "zero_hp": pc_hp <= 0}
            if active:
                targeted_pcs.append(key)

    if len(ally_roster) > 32 or len(enemy_roster) > 32 or len(pcs) > 32:
        return None
    if len(set(ally_roster)) != len(ally_roster):
        return None
    return {
        "roster": sorted(_canonical_name(name) for name in ally_roster),
        "enemy_roster": sorted(enemy_roster),
        "enemies": enemies,
        "pcs": pcs,
        "commander_active": len(commander_rows) == 1 and commander_rows[0],
        "targeted_pcs": sorted(targeted_pcs),
    }


def _track_batch(
    target: OrderedDict[tuple[str, str], None], key: tuple[str, str]
) -> None:
    target[key] = None
    target.move_to_end(key)
    while len(target) > MAX_ALLY_PREFETCH_TRACKED_BATCHES:
        target.popitem(last=False)


def has_ally_prefetch_submission(encounter_id: Any, batch_id: Any) -> bool:
    """Retain selection through invalidation so the caller cannot sync-replan."""
    if not isinstance(encounter_id, str) or not isinstance(batch_id, str):
        return False
    key = (encounter_id, batch_id)
    with _BATCH_TRACKING_LOCK:
        if key in _SELECTED_BATCHES:
            return True
    return has_tactical_prefetch_submission(encounter_id, batch_id)


def has_ally_prefetch_replan_submission(encounter_id: Any, batch_id: Any) -> bool:
    """Report an already-submitted re-plan for D5 command rejection."""
    if not isinstance(encounter_id, str) or not isinstance(batch_id, str):
        return False
    key = (encounter_id, batch_id)
    with _BATCH_TRACKING_LOCK:
        if key in _REPLAN_BATCHES:
            return True
    return has_tactical_prefetch_replan_submission(encounter_id, batch_id)


def _prefetch_router_call(
    llm_call: Callable[..., Any],
    receipt_observer_factory: Optional[Callable[..., Any]],
    *,
    usage_tracking_available: bool,
    combat_main_model: str,
    trace_batch_id: Optional[str],
    request_kind: str,
) -> Callable[..., Any]:
    observer = None
    if callable(receipt_observer_factory):
        observer = receipt_observer_factory(
            trace_site="combat_tactical_prefetch",
            track_usage=usage_tracking_available,
            legacy_context={
                "purpose": "combat_ally_standing_orders",
                "legacy_context_model": combat_main_model,
                "batch_id": trace_batch_id,
                "request_kind": request_kind,
                "request_site": "combat_tactical_prefetch",
            },
        )

    def call(task: str, messages: Any, **kwargs: Any) -> Any:
        if observer is not None:
            kwargs["observer"] = observer
        return llm_call(task, messages, **kwargs)

    return call


def _parse_ally_orders_for_prefetch(response: Any) -> TacticalPrefetchParseOutcome:
    """Preserve only the parser's allowlisted failure category in the receipt."""
    orders, rejection_reason = parse_ally_standing_orders_response_with_reason(response)
    if rejection_reason not in ALLY_STANDING_ORDER_PARSE_FAILURE_CODES:
        rejection_reason = None
    return TacticalPrefetchParseOutcome(orders, rejection_reason)


def submit_ally_prefetch(
    encounter_data: Any,
    *,
    encounter_id: Any,
    multi_pc_manager: Any,
    active_encounter_id: Any,
    npc_profiles: Any = None,
    history: Any = None,
    tactical_features: Any = None,
    llm_call: Callable[..., Any],
    trigger: str = "initial",
    deadline_seconds: Any = None,
    clock: Callable[[], float] | None = None,
    executor: Optional[Callable[[Callable[[], None]], Any]] = None,
    receipt_observer_factory: Optional[Callable[..., Any]] = None,
    usage_tracking_available: bool = False,
    combat_main_model: str = "combat_main",
) -> Optional[TacticalPrefetchSubmission]:
    """Submit initial orders or one directive/state-edge re-plan during PC play."""
    if not is_ally_prefetch_enabled():
        return None
    if (
        not isinstance(encounter_data, Mapping)
        or getattr(multi_pc_manager, "combat_phase", None) != "PC_PHASE"
        or not callable(llm_call)
    ):
        return None
    resolved_encounter_id = encounter_data.get("encounterId", encounter_data.get("id"))
    if (
        not isinstance(resolved_encounter_id, str)
        or resolved_encounter_id != encounter_id
        or active_encounter_id != resolved_encounter_id
        or trigger not in {"initial", "state_edge", "directive"}
    ):
        return None
    raw_round = encounter_data.get(
        "combat_round", encounter_data.get("current_round", 1)
    )
    batch_id = ally_prefetch_batch_id(resolved_encounter_id, raw_round)
    if batch_id is None:
        return None

    request_kind = "initial" if trigger == "initial" else "replan"
    trace_batch_id = combat_latency_trace.build_work_unit_trace_context(
        raw_round, "ENEMY_PHASE", None
    ).get("batch_id")
    if request_kind == "initial" and has_ally_prefetch_submission(
        resolved_encounter_id, batch_id
    ):
        return TacticalPrefetchSubmission(False, "already_submitted")
    if request_kind == "replan" and not has_ally_prefetch_submission(
        resolved_encounter_id, batch_id
    ):
        return TacticalPrefetchSubmission(False, "no_initial_request")

    try:
        built_menus = build_ally_menus(
            encounter_data,
            batch_id,
            npc_profiles=npc_profiles if isinstance(npc_profiles, Mapping) else None,
            tactical_features=tactical_features,
        )
        if not isinstance(built_menus, AllyMenus) or not built_menus.actor_menus:
            return None
        roster_members = [menu.actor.name for menu in built_menus.actor_menus]
        state_snapshot = _ally_state_snapshot(
            encounter_data,
            roster_members,
            getattr(multi_pc_manager, "pc_states", None),
        )
        if state_snapshot is None or tactical_roster_identity(roster_members) is None:
            return None
        if request_kind == "replan" and trigger == "state_edge":
            if not tactical_prefetch_replan_needed(
                resolved_encounter_id, batch_id, state_snapshot
            ):
                status = (
                    "request_cap_reached"
                    if has_ally_prefetch_replan_submission(resolved_encounter_id, batch_id)
                    else "no_major_change"
                )
                return TacticalPrefetchSubmission(False, status)
        messages = build_ally_standing_orders_messages(built_menus, history)
        background_call = _prefetch_router_call(
            llm_call,
            receipt_observer_factory,
            usage_tracking_available=usage_tracking_available,
            combat_main_model=combat_main_model,
            trace_batch_id=(
                trace_batch_id if isinstance(trace_batch_id, str) else None
            ),
            request_kind=request_kind,
        )
        submit_kwargs: dict[str, Any] = {
            "llm_call": background_call,
            "request_kind": request_kind,
            "response_parser": _parse_ally_orders_for_prefetch,
            "deadline_seconds": (
                DEFAULT_PREFETCH_DEADLINE_SECONDS
                if deadline_seconds is None
                else deadline_seconds
            ),
            "executor": executor,
        }
        if trigger != "initial":
            submit_kwargs["trigger_kind"] = trigger
        if clock is not None:
            submit_kwargs["clock"] = clock
        submission = submit_tactical_prefetch(
            resolved_encounter_id,
            batch_id,
            roster_members,
            messages,
            state_snapshot,
            **submit_kwargs,
        )
        if submission.submitted:
            key = (resolved_encounter_id, batch_id)
            with _BATCH_TRACKING_LOCK:
                _track_batch(_SELECTED_BATCHES, key)
                if request_kind == "replan":
                    _track_batch(_REPLAN_BATCHES, key)
            try:
                if combat_latency_trace.trace_enabled():
                    request_id = submission.receipt_correlation_id
                    if isinstance(trace_batch_id, str) and isinstance(request_id, str):
                        combat_latency_trace.trace_ally_prefetch_submission(
                            trace_batch_id,
                            request_id,
                            request_kind,
                        )
            except Exception:
                # Optional evidence must not change the accepted background submission.
                pass
        return submission
    except Exception:
        # Prompt or receipt failures never delay player input or /end.
        return None


def select_ally_prefetch_plan(
    encounter_id: Any,
    menus: Any,
    encounter_data: Any,
    *,
    clock: Callable[[], float] | None = None,
) -> AllyPrefetchSelection:
    """Consume a selected prefetch without waiting or creating a sync repair path."""
    if not isinstance(menus, AllyMenus) or not isinstance(encounter_id, str):
        return AllyPrefetchSelection(False, "prefetch_none")
    batch_id = menus.batch_id
    if not has_ally_prefetch_submission(encounter_id, batch_id):
        return AllyPrefetchSelection(False, "prefetch_none")
    current_roster = [menu.actor.name for menu in menus.actor_menus]
    consume_kwargs: dict[str, Any] = {"current_roster_members": current_roster}
    if clock is not None:
        consume_kwargs["clock"] = clock
    result = consume_tactical_prefetch(encounter_id, batch_id, **consume_kwargs)
    terminal_error = result.error if result.error is not None and any(
        cls.__name__ in {"GameLLMTerminalError", "LLMJSONError"}
        for cls in type(result.error).__mro__
    ) else None
    plan = None
    plan_origin = None
    prefetch_resolution = "prefetch_unavailable"
    prefetch_rejection_reason = None
    status = result.status
    if result.status == "prefetch_hit":
        candidate = compile_ally_standing_orders(
            result.result,
            menus,
            encounter_data,
            ally_departed=result.ally_departed,
        )
        if candidate is None:
            status = "standing_orders_unavailable"
            plan = rule_default_ally_plan(menus, "INVALID_PLAN")
            prefetch_resolution = "compiler_unusable"
        else:
            plan = validate_ally_plan(candidate, menus)
            plan_origin = "standing_orders"
            prefetch_resolution = (
                "current_menu_default"
                if any(choice.default_reason is not None for choice in plan.choices)
                else "current_menu_selected"
            )
    else:
        status = "standing_orders_unavailable"
        plan = rule_default_ally_plan(menus, "MISSING_CHOICE")
        if result.receipt_status == "invalid":
            prefetch_resolution = "response_rejected"
            if result.parse_rejection_reason in ALLY_STANDING_ORDER_PARSE_FAILURE_CODES:
                prefetch_rejection_reason = result.parse_rejection_reason

    # A consumed batch has no later planning path; cancel pending workers so
    # late responses cannot become available after the ally boundary.
    invalidate_tactical_prefetch(encounter_id, batch_id)
    key = (encounter_id, batch_id)
    with _BATCH_TRACKING_LOCK:
        _SELECTED_BATCHES.pop(key, None)
        _REPLAN_BATCHES.pop(key, None)
    if terminal_error is not None:
        raise terminal_error
    return AllyPrefetchSelection(
        True,
        status,
        plan,
        result.receipt_correlation_id,
        plan_origin,
        result.request_kind,
        prefetch_resolution,
        prefetch_rejection_reason,
    )


def invalidate_ally_prefetch(
    encounter_id: Optional[str],
    batch_id: str,
    *,
    clear_selection: bool = False,
) -> TacticalPrefetchResult:
    """Invalidate worker receipts, retaining selection until the ally boundary."""
    result = invalidate_tactical_prefetch(encounter_id, batch_id)
    if clear_selection and isinstance(encounter_id, str):
        key = (encounter_id, batch_id)
        with _BATCH_TRACKING_LOCK:
            _SELECTED_BATCHES.pop(key, None)
            _REPLAN_BATCHES.pop(key, None)
    return result


def _reset_ally_prefetch_for_tests() -> None:
    """Clear bounded sticky path accounting between provider-free tests."""
    with _BATCH_TRACKING_LOCK:
        _SELECTED_BATCHES.clear()
        _REPLAN_BATCHES.clear()
