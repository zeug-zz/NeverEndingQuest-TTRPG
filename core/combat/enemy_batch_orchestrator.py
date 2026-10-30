# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Gate and execute the deterministic enemy-batch runtime path."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import time
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from typing import Any, Optional

import model_config
from utils.enhanced_logger import debug
from core.combat.enemy_batch_apply import (
    EnemyBatchApplyResult,
    apply_enemy_batch,
    is_ally_controller_enabled,
    is_ally_prefetch_enabled,
    is_combat_tactical_brain_enabled,
    is_deterministic_enemy_resolution_enabled,
    is_combat_tactical_prefetch_enabled,
    project_combat_resolution_ledger,
)
from core.combat.enemy_narration import NarrationResult, narrate_enemy_batch
from core.combat.enemy_resolution import (
    CombatantIdentity,
    DECLINE_REASON_CODES,
    EnemyAttackLedgerEntry,
    EnemyDeparture,
    EnemyCoverUpdate,
    EnemyResolutionDecline,
    EnemyResolutionLedger,
    plan_enemy_batch,
)
from core.combat.ally_controller import (
    AllyMenuBuildFailure,
    AllyMenus,
    ValidatedAllyPlan,
    build_ally_menus,
    build_ally_plan_messages,
    latest_ally_directives_from_history,
    rule_default_ally_plan,
    select_active_allies,
    validate_ally_plan,
)
from core.combat.ally_narration import narrate_ally_batch
from core.combat.ally_prefetch import (
    ally_prefetch_batch_id,
    has_ally_prefetch_submission,
    select_ally_prefetch_plan,
)
from core.combat.ally_resolution import resolve_ally_batch
from core.combat.tactical_brain import (
    TacticalMenuBuildFailure,
    TacticalMenus,
    ValidatedTacticalChoice,
    ValidatedTacticalPlan,
    STANDING_ORDER_DEFAULT_REASON,
    build_standing_orders_messages,
    build_commander_plan_messages,
    build_tactical_menus,
    compile_standing_orders,
    parse_standing_orders_response,
    rule_default_tactical_plan,
    standing_orders_intent,
    validate_commander_plan,
)
from core.combat.tactical_prefetch import (
    DEFAULT_PREFETCH_DEADLINE_SECONDS,
    TacticalPrefetchResult,
    consume_tactical_prefetch,
    has_tactical_prefetch_submission,
    invalidate_tactical_prefetch,
    submit_tactical_prefetch,
    tactical_batch_id,
    tactical_prefetch_replan_needed,
    tactical_roster_identity,
)
from core.combat.turn import (
    CombatActionTraceDependencies,
    CombatActionTraceInputs,
    RoundTransitionDependencies,
    capture_pre_round_transition_combat_context,
    stage_combat_turn_snapshot,
    sync_committed_combat_turn,
    trace_combat_action_batch_metadata,
)
from core.combat.turn_commit import compute_applied_id, read_character_applied_id
from utils import combat_latency_trace


@dataclass(frozen=True)
class EnemyBatchFallback:
    """Bounded reason why the unchanged legacy path should run instead."""

    reason_code: str


@dataclass(frozen=True)
class EnemyBatchExecution:
    """Completed deterministic batch and its persisted runtime projections."""

    ledger: EnemyResolutionLedger
    narration: NarrationResult
    conversation_history: list
    encounter_data: dict
    application: EnemyBatchApplyResult
    lifecycle_case: str
    logical_turn: Optional[int] = None


@dataclass(frozen=True)
class _AllyBatchStage:
    """Read-only ally outcome plus its in-memory encounter projection."""

    ledger: EnemyResolutionLedger
    narration: Optional[NarrationResult]
    encounter_projection: dict
    menus: AllyMenus
    plan: ValidatedAllyPlan
    plan_request_kind: str
    prefetch_resolution: Optional[str] = None
    prefetch_rejection_reason: Optional[str] = None


class _AllyBatchUnsupported(ValueError):
    """The enabled ally batch cannot be safely projected from current facts."""


class _AllyBatchNarrationError(RuntimeError):
    """Preserve provider/narration failures through the preflight fallback guard."""

    def __init__(self, error: Exception):
        self.error = error
        super().__init__("ally_batch_narration_failed")


def _active_enemy_window(
    encounter: Mapping[str, Any], turn_order: list[CombatantIdentity]
) -> list[dict[str, str]]:
    """Return living hostile actors in the runtime initiative order."""
    creatures = encounter.get("creatures")
    if not isinstance(creatures, list):
        raise ValueError("malformed_encounter")
    rows = {}
    for creature in creatures:
        if not isinstance(creature, Mapping):
            raise ValueError("malformed_encounter")
        if str(creature.get("type", "")).strip().casefold() != "enemy":
            continue
        name = creature.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("malformed_encounter")
        key = _canonical_identity_key(CombatantIdentity(name, "enemy"))
        if key in rows:
            raise ValueError("ambiguous_enemy_identity")
        rows[key] = creature

    result = []
    seen = set()
    inactive = {
        "dead", "defeated", "departed", "fled", "surrendered", "inactive",
        "unconscious", "incapacitated", "stable",
    }
    for identity in turn_order:
        if identity.kind != "enemy":
            continue
        key = _canonical_identity_key(identity)
        row = rows.get(key)
        if row is None or key in seen:
            continue
        hp = row.get("currentHitPoints", row.get("hitPoints"))
        status = row.get("status", "alive")
        departure = row.get("defeatReason", row.get("departureReason"))
        if (
            not isinstance(hp, int)
            or isinstance(hp, bool)
            or hp <= 0
            or not isinstance(status, str)
            or status.strip().casefold() in inactive
            or (isinstance(departure, str) and departure.strip().casefold() in {
                "departed", "fled", "surrendered",
            })
        ):
            continue
        result.append({"name": identity.name, "kind": "enemy"})
        seen.add(key)
    return result


def _ally_batch_identity(encounter_id: str, round_number: int) -> str:
    candidate = ally_prefetch_batch_id(encounter_id, round_number)
    if candidate is not None:
        return candidate
    suffix = f"-r{round_number}-ally"
    safe_id = re.sub(r"[^A-Za-z0-9_-]", "_", encounter_id).strip("_")
    return (safe_id[: max(0, 128 - len(suffix))].strip("_") or "combat") + suffix


def _run_ally_batch(
    encounter: Mapping[str, Any],
    *,
    encounter_id: str,
    turn_order: list[CombatantIdentity],
    history: list,
    scene_context: Any,
    dependencies: EnemyBatchOrchestrationDependencies,
    trace_batch_id: Optional[str] = None,
    trace_actor_ids: Optional[Mapping[tuple[str, str], str]] = None,
) -> Optional[_AllyBatchStage]:
    """Plan, resolve, and project one eligible ally batch without committing it."""
    # TABLETOP MODE: The allied side remains a separate choice and narration
    # batch, with only its projection passed forward to the next initiative slot.
    scheduled_allies = select_active_allies(encounter, turn_order)
    if not scheduled_allies:
        return None
    round_number = encounter.get("combat_round", encounter.get("current_round", 1))
    if not isinstance(round_number, int) or isinstance(round_number, bool) or round_number < 1:
        raise ValueError("malformed_encounter")
    world_context = scene_context if isinstance(scene_context, Mapping) else {}
    menus = build_ally_menus(
        encounter,
        _ally_batch_identity(encounter_id, round_number),
        npc_profiles=world_context.get("npc_profiles"),
        scheduled_allies=scheduled_allies,
        turn_order=turn_order,
        tactical_features=_tactical_features(scene_context),
    )
    if isinstance(menus, AllyMenuBuildFailure):
        if menus.reason_code in {"no_legal_target", "no_legal_attack"}:
            return None
        raise _AllyBatchUnsupported("ally_menu_" + menus.reason_code)
    if not isinstance(menus, AllyMenus) or not menus.actor_menus:
        return None

    prefetch_selected = (
        is_ally_prefetch_enabled()
        and has_ally_prefetch_submission(encounter_id, menus.batch_id)
    )
    plan_request_kind: Optional[str] = "synchronous"
    prefetch_resolution: Optional[str] = None
    prefetch_rejection_reason: Optional[str] = None
    if prefetch_selected:
        selection = select_ally_prefetch_plan(
            encounter_id,
            menus,
            encounter,
        )
        plan = selection.plan
        plan_request_kind = selection.request_kind
        prefetch_resolution = selection.prefetch_resolution
        prefetch_rejection_reason = selection.prefetch_rejection_reason
        if not isinstance(plan, ValidatedAllyPlan):
            plan = rule_default_ally_plan(menus, "MISSING_CHOICE")
    else:
        try:
            messages = build_ally_plan_messages(menus, history)
            observer = dependencies.receipt_observer_factory(
                trace_site="combat_main",
                track_usage=dependencies.usage_tracking_available,
                legacy_context={
                    "purpose": "combat_ally_batch_plan",
                    "legacy_context_model": dependencies.combat_main_model,
                },
            )
            response = dependencies.llm_call(
                "combat_main",
                messages,
                json_output=False,
                max_tokens=1200,
                observer=observer,
                json_contract=True,
            )
            plan = validate_ally_plan(response, menus)
        except Exception as exc:
            if _is_terminal_router_error(exc):
                raise
            plan = validate_ally_plan(None, menus)

    ledger = resolve_ally_batch(
        menus,
        plan,
        encounter,
        active_encounter_id=world_context.get("active_encounter_id"),
        combat_in_progress=world_context.get("combat_in_progress") is True,
        tactical_features=_tactical_features(scene_context),
    )
    if not isinstance(ledger, EnemyResolutionLedger):
        raise _AllyBatchUnsupported(
            "ally_resolution_" + getattr(ledger, "reason_code", "failed")
        )
    _trace_ally_cover_selections(
        menus,
        plan,
        batch_id=trace_batch_id,
        actor_ids=trace_actor_ids,
    )

    projected = project_combat_resolution_ledger(ledger, encounter)
    return _AllyBatchStage(
        ledger=ledger,
        narration=None,
        encounter_projection=projected,
        menus=menus,
        plan=plan,
        plan_request_kind=plan_request_kind,
        prefetch_resolution=prefetch_resolution,
        prefetch_rejection_reason=prefetch_rejection_reason,
    )


def _narrate_ally_stage(
    stage: _AllyBatchStage,
    history: list,
    dependencies: EnemyBatchOrchestrationDependencies,
) -> _AllyBatchStage:
    """Narrate an ally result only after the combined batch passes preflight."""
    try:
        observer = dependencies.receipt_observer_factory(
            trace_site="combat_main",
            track_usage=dependencies.usage_tracking_available,
            legacy_context={
                "purpose": "combat_ally_batch_narration",
                "legacy_context_model": dependencies.combat_main_model,
            },
        )
        narration = narrate_ally_batch(
            stage.ledger,
            history,
            dependencies.llm_call,
            receipt_observer=observer,
        )
    except Exception as exc:
        raise _AllyBatchNarrationError(exc) from exc
    return replace(stage, narration=narration)


def _combine_side_ledgers(
    hostile: EnemyResolutionLedger,
    ally: Optional[_AllyBatchStage],
    *,
    ally_first: bool,
) -> EnemyResolutionLedger:
    if ally is None:
        return hostile
    side_entries = (
        (*ally.ledger.entries, *hostile.entries)
        if ally_first else (*hostile.entries, *ally.ledger.entries)
    )
    cover_updates = {}
    for update in (*hostile.cover_updates, *ally.ledger.cover_updates):
        key = _canonical_identity_key(update.enemy)
        cover_updates[key] = update
    return replace(
        hostile,
        entries=tuple(side_entries),
        cover_updates=tuple(cover_updates[key] for key in sorted(cover_updates)),
    )


def _combine_side_narration(
    hostile: Optional[NarrationResult],
    ally: Optional[_AllyBatchStage],
    *,
    ally_first: bool,
) -> NarrationResult:
    if ally is not None and ally.narration is None:
        raise ValueError("ally_batch_narration_missing")
    results = ([ally.narration] if ally is not None and ally_first else [])
    if hostile is not None:
        results.append(hostile)
    if ally is not None and not ally_first:
        results.append(ally.narration)
    source = "llm" if any(result.source == "llm" for result in results) else "template"
    return NarrationResult(
        text="\n".join(result.text.strip() for result in results if result.text.strip()),
        source=source,
        reason_code=(
            next((result.reason_code for result in results if result.reason_code), None)
        ),
    )


@dataclass(frozen=True)
class EnemyBatchExitCompletion:
    """Result of routing a completed enemy batch through the AUTO_EXIT path."""

    encounter_data: dict
    finalization: Any = None


@dataclass(frozen=True)
class EnemyBatchOrchestrationDependencies:
    """Runtime bindings kept injectable for provider-free orchestration tests."""

    read_json: Callable[[str], Any]
    write_json: Callable[[str, Any], Any]
    round_transition_dependencies: RoundTransitionDependencies
    llm_call: Callable[..., Any]
    receipt_observer_factory: Callable[..., Any]
    publish_narration: Callable[..., Any]
    usage_tracking_available: bool
    combat_main_model: str
    clean_old_dm_notes: Optional[Callable[[list], Any]] = None
    clean_combat_state_blocks: Optional[Callable[[list], Any]] = None
    plan: Callable[..., Any] = plan_enemy_batch
    narrate: Callable[..., NarrationResult] = narrate_enemy_batch
    apply: Callable[..., EnemyBatchApplyResult] = apply_enemy_batch
    apply_round_transition: Callable[..., Any] = stage_combat_turn_snapshot
    resolve_self_preservation: Optional[Callable[..., Any]] = None
    calculate_xp_for_encounter: Optional[Callable[..., Any]] = None
    check_all_monsters_defeated: Optional[Callable[..., bool]] = None
    validate_character: Optional[Callable[..., Any]] = None
    session: Any = None


def complete_deterministic_enemy_batch_exit(
    encounter_data: dict,
    *,
    check_all_monsters_defeated: Callable[[Any], bool],
    process_action_batch: Callable[..., Any],
    action_dependencies: Any,
    encounter_id: str,
    conversation_history: list,
    conversation_history_file: str,
    multi_pc_manager: Any,
    party_tracker_data: dict,
    apply_final_character_updates: Callable[..., Any],
    finalize_combat_session: Callable[..., Any],
    finalization_inputs: Any,
    finalization_dependencies: Any,
    precommitted_exit: bool = False,
) -> EnemyBatchExitCompletion:
    """Run the established AUTO_EXIT/XP path after a terminal enemy batch."""
    if not check_all_monsters_defeated(encounter_data):
        return EnemyBatchExitCompletion(encounter_data)

    if precommitted_exit:
        finalization = finalize_combat_session(
            finalization_inputs,
            finalization_dependencies,
        )
        return EnemyBatchExitCompletion(encounter_data, finalization)

    exit_batch = process_action_batch(
        [{"action": "exit"}],
        encounter_data,
        {},
        encounter_id=encounter_id,
        conversation_history=conversation_history,
        conversation_history_file=conversation_history_file,
        multi_pc_manager=multi_pc_manager,
        party_tracker_data=party_tracker_data,
        is_combat_ending=False,
        dependencies=action_dependencies,
    )
    updated_encounter = exit_batch.encounter_data
    if not exit_batch.is_combat_ending:
        return EnemyBatchExitCompletion(updated_encounter)

    apply_final_character_updates(exit_batch.final_character_updates, multi_pc_manager)
    finalization = finalize_combat_session(
        finalization_inputs,
        finalization_dependencies,
    )
    return EnemyBatchExitCompletion(updated_encounter, finalization)


def _fallback(reason_code: str, dependencies: EnemyBatchOrchestrationDependencies) -> EnemyBatchFallback:
    bounded_reason = reason_code if reason_code in DECLINE_REASON_CODES | {
        "round_transition_unsupported",
        "preflight_error",
        "malformed_result",
        "malformed_pc_state",
    } else "preflight_error"
    dependencies.round_transition_dependencies.log_debug(
        f"DETERMINISTIC_ENEMY_BATCH: Declined; reason={bounded_reason}",
        category="combat_events",
    )
    return EnemyBatchFallback(bounded_reason)


def _lifecycle_case(encounter_data: Any, multi_pc_manager: Any) -> Optional[str]:
    if not isinstance(encounter_data, dict) or multi_pc_manager is None:
        return None
    if getattr(multi_pc_manager, "combat_phase", None) != "ENEMY_PHASE":
        return None

    opening_pending = encounter_data.get("openingEnemyBatchPending", False)
    if not isinstance(opening_pending, bool):
        return None
    round_starts_with = encounter_data.get("roundStartsWith")
    if opening_pending and round_starts_with == "dmGroup":
        return "opening_batch"
    if not opening_pending and round_starts_with in (None, "pcGroup"):
        return "pc_phase_end"
    return None


def _batch_id(encounter_id: str, round_number: int) -> str:
    suffix = f"-r{round_number}-enemy_phase"
    safe_id = re.sub(r"[^A-Za-z0-9_-]", "_", encounter_id).strip("_")
    prefix_limit = max(0, 64 - len(suffix))
    bounded_id = safe_id[:prefix_limit].strip("_")
    batch_id = f"{bounded_id or 'combat'}{suffix}"
    return batch_id if len(batch_id) <= 64 else batch_id[-64:]


def _trace_batch_id(encounter_data: Any) -> Optional[str]:
    if not isinstance(encounter_data, Mapping):
        return None
    round_number = encounter_data.get("combat_round", encounter_data.get("current_round", 1))
    return combat_latency_trace.build_work_unit_trace_context(
        round_number, "ENEMY_PHASE", None
    ).get("batch_id")


def _turn_order(multi_pc_manager: Any) -> list[CombatantIdentity]:
    queue_manager = getattr(multi_pc_manager, "_turns", None)
    queue = getattr(queue_manager, "turn_queue", None)
    if not isinstance(queue, list):
        raise ValueError("turn_queue_unavailable")

    result = []
    for combatant in queue:
        name = getattr(combatant, "name", None)
        raw_kind = getattr(combatant, "type", None)
        kind = getattr(raw_kind, "value", raw_kind)
        if not isinstance(name, str) or not isinstance(kind, str):
            raise ValueError("malformed_turn_order")
        result.append(CombatantIdentity(name=name, kind=kind))
    return result


def _pc_states(
    encounter_data: Mapping[str, Any],
    path_manager: Any,
    read_json: Callable[[str], Any],
    applied_id: Optional[str] = None,
) -> dict[str, Any]:
    result = {}
    for creature in encounter_data.get("creatures", []):
        if not isinstance(creature, Mapping):
            raise ValueError("malformed_encounter")
        if str(creature.get("type", "")).strip().lower() != "player":
            continue
        name = creature.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("malformed_pc_state")
        path = path_manager.get_character_path(name)
        if not isinstance(path, str) or not path:
            raise ValueError("malformed_pc_state")
        character_data = read_json(path)
        if not isinstance(character_data, Mapping):
            raise ValueError("malformed_pc_state")
        projected_state = copy.deepcopy(dict(character_data))
        if applied_id is not None and read_character_applied_id(projected_state) == applied_id:
            matching_rows = [
                row for row in encounter_data.get("creatures", [])
                if isinstance(row, Mapping)
                and str(row.get("type", "")).strip().casefold() in {"player", "pc"}
                and isinstance(row.get("name"), str)
                and " ".join(row["name"].split()).casefold()
                == " ".join(name.split()).casefold()
            ]
            if len(matching_rows) != 1:
                raise ValueError("malformed_pc_state")
            encounter_pc = matching_rows[0]
            encounter_hp = encounter_pc.get("currentHitPoints")
            encounter_status = encounter_pc.get("status")
            if (
                not isinstance(encounter_hp, int)
                or isinstance(encounter_hp, bool)
                or encounter_hp < 0
                or not isinstance(encounter_status, str)
                or not encounter_status.strip()
            ):
                raise ValueError("malformed_pc_state")
            # A matching character marker means this turn's HP/status write
            # may have landed while the encounter receipt did not. Re-plan
            # from the still-durable encounter snapshot, not that partial write.
            projected_state["hitPoints"] = encounter_hp
            projected_state["status"] = encounter_status
        result[name] = projected_state
    return result


def _standing_order_state_snapshot(
    encounter_data: Mapping[str, Any], party_states: Mapping[str, Any]
) -> dict[str, Any]:
    """Project only the bounded D6 state edges used to trigger one re-plan."""
    creatures = encounter_data.get("creatures")
    if not isinstance(creatures, list):
        raise ValueError("malformed_encounter")
    enemies: dict[str, dict[str, bool]] = {}
    pcs: dict[str, dict[str, bool]] = {}
    roster = []
    commander_rows = []
    for creature in creatures:
        if not isinstance(creature, Mapping):
            continue
        name = creature.get("name")
        kind = creature.get("type")
        if not isinstance(name, str) or not name.strip():
            continue
        key = " ".join(name.split()).casefold()
        hp = creature.get("currentHitPoints")
        max_hp = creature.get("maxHitPoints")
        if (
            isinstance(hp, bool) or not isinstance(hp, int)
            or isinstance(max_hp, bool) or not isinstance(max_hp, int)
            or max_hp < 0
        ):
            hp = 0
            max_hp = 0
        status = creature.get("status", "alive")
        active = (
            hp > 0
            and isinstance(status, str)
            and status.strip().casefold() not in {"dead", "defeated"}
        )
        if kind == "enemy":
            if key in enemies:
                raise ValueError("ambiguous_enemy_identity")
            enemies[key] = {
                "active": active,
                "bloodied": active and hp * 2 <= max_hp,
                "near_death": active and hp * 4 <= max_hp,
            }
            if active:
                roster.append(key)
            if creature.get("leader") is True and creature.get("tactics", "rule") == "commander":
                commander_rows.append(active)
        elif kind == "player":
            character_state = next((
                value for pc_name, value in party_states.items()
                if isinstance(pc_name, str)
                and " ".join(pc_name.split()).casefold() == key
            ), None)
            pc_hp = (
                character_state.get("hitPoints", character_state.get("current_hp"))
                if isinstance(character_state, Mapping) else hp
            )
            if isinstance(pc_hp, bool) or not isinstance(pc_hp, int):
                pc_hp = hp
            pcs[key] = {
                "active": active,
                "zero_hp": pc_hp <= 0,
            }

    roster = sorted(set(roster))
    targeted_pcs = sorted(name for name, state in pcs.items() if state["active"])
    return {
        "roster": roster,
        "enemies": enemies,
        "pcs": pcs,
        "commander_active": len(commander_rows) == 1 and commander_rows[0],
        "targeted_pcs": targeted_pcs,
    }


def _prefetch_router_call(
    llm_call: Callable[..., Any],
    receipt_observer_factory: Optional[Callable[..., Any]],
    *,
    usage_tracking_available: bool,
    combat_main_model: str,
    trace_batch_id: Optional[str],
    request_kind: str,
) -> Callable[..., Any]:
    """Wrap the existing router call with distinct background site attribution."""
    observer = None
    if callable(receipt_observer_factory):
        observer = receipt_observer_factory(
            trace_site="combat_tactical_prefetch",
            track_usage=usage_tracking_available,
            legacy_context={
                "purpose": "combat_enemy_batch_standing_orders",
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


def _creature_descriptions(
    encounter_data: Mapping[str, Any], monster_definitions: Mapping[str, Any]
) -> dict[str, str]:
    descriptions = {}
    for creature in encounter_data.get("creatures", []):
        if not isinstance(creature, Mapping):
            continue
        if str(creature.get("type", "")).strip().lower() != "enemy":
            continue
        name = creature.get("name")
        monster_type = creature.get("monsterType")
        if not isinstance(name, str) or not isinstance(monster_type, str):
            continue
        definition = next((
            value for key, value in monster_definitions.items()
            if isinstance(key, str) and key.casefold() == monster_type.casefold()
        ), None)
        description = creature.get("description")
        if not isinstance(description, str) or not description.strip():
            description = definition.get("description") if isinstance(definition, Mapping) else None
        if isinstance(description, str) and description.strip():
            descriptions[name] = description.strip()
    return descriptions


def _canonical_identity_key(identity: CombatantIdentity) -> tuple[str, str]:
    return identity.kind, " ".join(identity.name.split()).casefold()


def _has_living_commander(encounter: Any) -> bool:
    """Allow the near-death exception only for one living commander leader."""
    if not isinstance(encounter, Mapping) or not isinstance(encounter.get("creatures"), list):
        return False
    leaders = []
    for creature in encounter["creatures"]:
        if not isinstance(creature, Mapping) or creature.get("type") != "enemy":
            continue
        leader = creature.get("leader", False)
        if not isinstance(leader, bool):
            return False
        if leader:
            leaders.append(creature)
    if len(leaders) != 1:
        return False
    commander = leaders[0]
    hit_points = commander.get("currentHitPoints")
    status = commander.get("status", "alive")
    return (
        commander.get("tactics", "rule") == "commander"
        and isinstance(hit_points, int)
        and not isinstance(hit_points, bool)
        and hit_points > 0
        and isinstance(status, str)
        and status.strip().casefold() not in {"dead", "defeated"}
    )


def _tactical_features(scene_context: Any) -> Any:
    if not isinstance(scene_context, Mapping):
        return None
    location = scene_context.get("location")
    return location.get("tacticalFeatures") if isinstance(location, Mapping) else None


def submit_tactical_prefetch_for_enemy_batch(
    encounter_data: Any,
    *,
    encounter_id: Any,
    multi_pc_manager: Any,
    monster_definitions: Any,
    path_manager: Any,
    read_json: Callable[[str], Any],
    scene_context: Any,
    llm_call: Callable[..., Any],
    executor: Optional[Callable[[Callable[[], None]], Any]] = None,
    replan: bool = False,
    receipt_observer_factory: Optional[Callable[..., Any]] = None,
    usage_tracking_available: bool = False,
    combat_main_model: str = "combat_main",
) -> Any:
    """Prepare initial standing orders or one event-triggered re-plan.

    All combat reads and menu construction happen on the caller thread. The
    background worker receives only the bounded message snapshot and router
    callable, never mutable encounter state or persistence callbacks.
    """
    # TABLETOP MODE: /end remains human-owned; this helper is called only from
    # explicit PC-phase-start or authoritative PC-state-transition hooks.
    if not is_combat_tactical_prefetch_enabled():
        return None
    if (not isinstance(encounter_data, Mapping)
            or getattr(multi_pc_manager, "combat_phase", None) != "PC_PHASE"
            or not isinstance(monster_definitions, Mapping)):
        return None
    resolved_encounter_id = encounter_data.get("encounterId", encounter_data.get("id"))
    if not isinstance(resolved_encounter_id, str) or str(encounter_id) != resolved_encounter_id:
        return None
    raw_round = encounter_data.get("combat_round", encounter_data.get("current_round", 1))
    batch_id = tactical_batch_id(encounter_id, raw_round)
    if batch_id is None:
        return None
    if replan and not has_tactical_prefetch_submission(encounter_id, batch_id):
        return None

    try:
        party_states = _pc_states(encounter_data, path_manager, read_json)
        turn_order = _turn_order(multi_pc_manager)
        enemy_names = multi_pc_manager.get_remaining_enemies_for_round()
        if not isinstance(enemy_names, list):
            return None
        state_snapshot = _standing_order_state_snapshot(encounter_data, party_states)
        roster_members = state_snapshot["roster"]
        if not roster_members:
            return None
        if replan and not tactical_prefetch_replan_needed(
            resolved_encounter_id, batch_id, state_snapshot
        ):
            return None
        world_context = scene_context if isinstance(scene_context, Mapping) else {}
        built_menus = build_tactical_menus(
            encounter_data,
            party_states,
            monster_definitions,
            turn_order,
            batch_id=batch_id,
            batch_kind="enemy_phase",
            fixture_seed=None,
            enemy_turn_window=[{"name": name} for name in enemy_names],
            tactical_features=_tactical_features(scene_context),
            active_encounter_id=world_context.get("active_encounter_id"),
            combat_in_progress=world_context.get("combat_in_progress") is True,
            allow_commander_down=replan,
        )
        if not isinstance(built_menus, TacticalMenus):
            return None
        messages = build_standing_orders_messages(
            built_menus,
            party_states,
            actor_dispositions=_creature_descriptions(
                encounter_data, monster_definitions
            ),
        )
        request_kind = "replan" if replan else "initial"
        background_call = _prefetch_router_call(
            llm_call,
            receipt_observer_factory,
            usage_tracking_available=usage_tracking_available,
            combat_main_model=combat_main_model,
            trace_batch_id=_trace_batch_id(encounter_data),
            request_kind=request_kind,
        )
        submission = submit_tactical_prefetch(
            encounter_id,
            batch_id,
            roster_members,
            messages,
            state_snapshot,
            llm_call=background_call,
            request_kind=request_kind,
            deadline_seconds=getattr(
                model_config,
                "COMBAT_TACTICAL_PREFETCH_DEADLINE_SECONDS",
                DEFAULT_PREFETCH_DEADLINE_SECONDS,
            ),
            executor=executor,
        )
        if submission.submitted:
            trace_batch_id = _trace_batch_id(encounter_data)
            _trace_tactical_prefetch_status(
                trace_batch_id,
                "prefetch_none",
                submission.receipt_correlation_id,
                standing_orders_outcome=(
                    "replan_submitted" if replan else "submitted"
                ),
                request_kind=request_kind,
            )
        return submission
    except Exception:
        # A failed prefetch preparation remains eligible for the one existing
        # synchronous plan request because no receipt was submitted.
        return None


def _is_terminal_router_error(error: BaseException) -> bool:
    """Recognize router terminal classes without importing the provider facade."""
    terminal_names = {"GameLLMTerminalError", "LLMJSONError"}
    return any(cls.__name__ in terminal_names for cls in type(error).__mro__)


def _tactical_default_reasons(
    plan: ValidatedTacticalPlan,
    actor_ids: Optional[Mapping[tuple[str, str], str]] = None,
) -> list[dict[str, str]]:
    reasons = []
    for index, choice in enumerate(plan.choices[:32], start=1):
        if choice.default_reason:
            actor_id = (
                actor_ids.get(_canonical_identity_key(choice.actor))
                if actor_ids is not None else None
            )
            if actor_id is None:
                actor_id = f"actor_{index}"
            reasons.append({
                "actor_id": actor_id,
                "reason_code": choice.default_reason,
            })
    return reasons


def _tactical_plan_intent(
    plan: ValidatedTacticalPlan,
    ledger: EnemyResolutionLedger,
) -> list[dict[str, str]]:
    departure_reasons = {
        _canonical_identity_key(item.enemy): item.reason
        for item in ledger.departures
    }
    intents = []
    emitted = set()
    for choice in plan.choices[:32]:
        key = _canonical_identity_key(choice.actor)
        departure_reason = departure_reasons.get(key)
        if departure_reason:
            intent = "flee" if departure_reason == "fled" else "surrender"
            row = {
                "actor": choice.actor.name,
                "intent": intent,
                "defeat_reason": departure_reason,
            }
        elif choice.kind in {"attack", "hold", "take_cover", "flee", "surrender"}:
            row = {
                "actor": choice.actor.name,
                "intent": "rule_default" if choice.default_reason else choice.kind,
            }
            if choice.default_reason:
                row["default_reason"] = choice.default_reason
        else:
            continue
        intents.append(row)
        emitted.add(key)
    for departure in ledger.departures:
        key = _canonical_identity_key(departure.enemy)
        if key in emitted:
            continue
        intents.append({
            "actor": departure.enemy.name,
            "intent": "flee" if departure.reason == "fled" else "surrender",
            "defeat_reason": departure.reason,
        })
        emitted.add(key)
        if len(intents) >= 32:
            break
    return intents[:32]


def _attack_target_overrides(
    menus: TacticalMenus,
    plan: ValidatedTacticalPlan,
) -> tuple[dict[tuple[str, str], tuple[CombatantIdentity, ...]], bool, bool]:
    """Resolve validated opaque IDs to targets, never passing model fields onward."""
    options_by_id = {option.option_id: option for option in menus.all_options}
    actor_menus = {
        _canonical_identity_key(menu.actor): menu for menu in menus.actor_menus
    }
    overrides: dict[tuple[str, str], tuple[CombatantIdentity, ...]] = {}
    changed = False
    departed_keys = {
        _canonical_identity_key(identity) for identity in plan.departed_creatures
    }
    if plan.side_surrender:
        return overrides, changed, False
    unsupported_choice = False
    for choice in plan.choices:
        actor_key = _canonical_identity_key(choice.actor)
        if choice.defeat_reason in {"fled", "surrendered"}:
            continue
        if choice.kind in {"hold", "take_cover"} and choice.action_consumed and choice.no_attack:
            continue
        actor_menu = actor_menus.get(actor_key)
        if actor_menu is None or choice.kind != "attack":
            unsupported_choice = True
            continue
        selected = [options_by_id.get(option_id) for option_id in choice.option_ids]
        if (
            len(selected) != len(actor_menu.attack_slots)
            or any(option is None or option.kind != "attack" or option.target is None
                   for option in selected)
        ):
            unsupported_choice = True
            continue
        target_identities = tuple(option.target for option in selected if option is not None)
        if (
            len(target_identities) != len(selected)
            or any(_canonical_identity_key(target) in departed_keys for target in target_identities)
        ):
            unsupported_choice = True
            continue
        overrides[actor_key] = target_identities
        changed = changed or choice.option_ids != actor_menu.default_option_ids
    return overrides, changed, unsupported_choice


def _default_unapplied_choices(
    plan: ValidatedTacticalPlan,
    menus: TacticalMenus,
) -> Optional[ValidatedTacticalPlan]:
    """Keep accepted departures while defaulting unsupported non-attack choices."""
    actor_menus = {
        _canonical_identity_key(menu.actor): menu for menu in menus.actor_menus
    }
    departed_menus = menus.without_departed(plan.departed_creatures)
    remaining_actor_menus = {
        _canonical_identity_key(menu.actor): menu for menu in departed_menus.actor_menus
    }
    options_by_id = {option.option_id: option for option in menus.all_options}
    departed_keys = {
        _canonical_identity_key(identity) for identity in plan.departed_creatures
    }
    choices = []
    replaced_any = False
    for choice in plan.choices:
        if choice.defeat_reason:
            choices.append(choice)
            continue
        menu = actor_menus.get(_canonical_identity_key(choice.actor))
        remaining_menu = remaining_actor_menus.get(_canonical_identity_key(choice.actor))
        if menu is None or remaining_menu is None:
            return None
        if choice.kind == "attack":
            selected = [options_by_id.get(option_id) for option_id in choice.option_ids]
            valid = (
                len(selected) == len(menu.attack_slots)
                and all(
                    option is not None
                    and option.target is not None
                    and _canonical_identity_key(option.target) not in departed_keys
                    for option in selected
                )
            )
            if valid and not choice.default_reason:
                choices.append(choice)
                continue
            legal_defaults = []
            if len(remaining_menu.attack_slots) != len(menu.attack_slots):
                return None
            for slot in remaining_menu.attack_slots:
                if not slot:
                    return None
                legal_defaults.append(slot[0].option_id)
            if not legal_defaults:
                return None
            choices.append(ValidatedTacticalChoice(
                actor=menu.actor,
                kind="attack",
                option_ids=tuple(legal_defaults),
                action_consumed=True,
                no_attack=False,
                default_reason=choice.default_reason or "INVALID_CHOICE",
            ))
            replaced_any = True
            continue
        if (
            len(remaining_menu.default_option_ids) == len(menu.attack_slots)
            and remaining_menu.default_option_ids
        ):
            legal_defaults = list(remaining_menu.default_option_ids)
        else:
            legal_defaults = []
            for slot in remaining_menu.attack_slots:
                if not slot:
                    return None
                legal_defaults.append(slot[0].option_id)
            if len(legal_defaults) != len(menu.attack_slots) or not legal_defaults:
                return None
        choices.append(ValidatedTacticalChoice(
            actor=menu.actor,
            kind="attack",
            option_ids=tuple(legal_defaults),
            action_consumed=True,
            no_attack=False,
            default_reason="INVALID_CHOICE",
        ))
        replaced_any = True
    if not replaced_any:
        return plan
    reasons = tuple(dict.fromkeys((*plan.rejected_reason_codes, "INVALID_CHOICE")))
    return replace(
        plan,
        status="partially_defaulted",
        choices=tuple(choices),
        rejected_reason_codes=reasons,
    )


def _departure_projection(
    plan: ValidatedTacticalPlan,
    menus: TacticalMenus,
) -> Optional[tuple[EnemyDeparture, ...]]:
    """Turn validated self-preservation selections into bounded ledger facts."""
    catalog = {
        _canonical_identity_key(identity): identity
        for identity in menus.target_catalog
    }
    reasons: dict[tuple[str, str], str] = {}
    for choice in plan.choices:
        if choice.defeat_reason is None:
            continue
        expected = {"flee": "fled", "surrender": "surrendered"}.get(choice.kind)
        key = _canonical_identity_key(choice.actor)
        if (
            expected is None
            or choice.defeat_reason != expected
            or key not in catalog
        ):
            return None
        reasons[key] = expected
    if plan.side_surrender:
        reasons = {key: "surrendered" for key in catalog}
    expected_keys = {
        _canonical_identity_key(identity) for identity in plan.departed_creatures
    }
    if set(reasons) != expected_keys or len(reasons) > 32:
        return None
    return tuple(
        EnemyDeparture(enemy=catalog[key], reason=reasons[key])
        for key in sorted(reasons)
    )


def _task_3_2_self_preservation_hook(
    plan: ValidatedTacticalPlan,
    menus: TacticalMenus,
    default_ledger: EnemyResolutionLedger,
    dependencies: EnemyBatchOrchestrationDependencies,
    resolver_arguments: tuple[Any, ...],
    resolver_options: Mapping[str, Any],
    attack_target_overrides: Mapping[tuple[str, str], tuple[CombatantIdentity, ...]],
    nonattacking_actors: Optional[set[tuple[str, str]]] = None,
) -> Optional[EnemyResolutionLedger]:
    """Resolve departures and the remaining attacks into one immutable ledger."""
    hook = dependencies.resolve_self_preservation
    if callable(hook):
        result = hook(plan, menus, default_ledger)
        return result if isinstance(result, EnemyResolutionLedger) else None

    departures = _departure_projection(plan, menus)
    if not departures:
        return None
    departed_keys = {_canonical_identity_key(item.enemy) for item in departures}
    remaining_window = [
        {"name": menu.actor.name, "kind": menu.actor.kind}
        for menu in menus.actor_menus
        if (
            _canonical_identity_key(menu.actor) not in departed_keys
            and _canonical_identity_key(menu.actor) not in (nonattacking_actors or set())
        )
    ]
    if not remaining_window:
        return replace(default_ledger, entries=(), departures=departures)

    final_options = dict(resolver_options)
    final_options["enemy_turn_window"] = remaining_window
    final_options["allow_near_death"] = True
    try:
        final_ledger = dependencies.plan(
            *resolver_arguments,
            **final_options,
            attack_target_overrides=dict(attack_target_overrides),
        )
    except Exception:
        return None
    if not isinstance(final_ledger, EnemyResolutionLedger):
        return None
    if (
        final_ledger.encounter_id != default_ledger.encounter_id
        or final_ledger.batch_id != default_ledger.batch_id
        or final_ledger.round_number != default_ledger.round_number
        or final_ledger.batch_kind != default_ledger.batch_kind
    ):
        return None
    return replace(final_ledger, departures=departures)


def _nonattacking_actor_keys(
    plan: ValidatedTacticalPlan,
) -> set[tuple[str, str]]:
    return {
        _canonical_identity_key(choice.actor)
        for choice in plan.choices
        if choice.kind in {"hold", "take_cover"}
        and choice.action_consumed
        and choice.no_attack
    }


def _apply_tactical_choices_to_ledger(
    ledger: EnemyResolutionLedger,
    plan: Optional[ValidatedTacticalPlan],
    menus: Optional[TacticalMenus],
) -> Optional[EnemyResolutionLedger]:
    """Project accepted non-attack choices and cover lifetime into one ledger."""
    cover_updates: dict[tuple[str, str], EnemyCoverUpdate] = {
        _canonical_identity_key(update.enemy): update
        for update in ledger.cover_updates
        if isinstance(update, EnemyCoverUpdate)
    }
    no_attack: set[tuple[str, str]] = set()
    if plan is not None:
        if menus is None:
            return None
        options_by_id = {option.option_id: option for option in menus.all_options}
        actor_menus = {
            _canonical_identity_key(menu.actor): menu for menu in menus.actor_menus
        }
        for choice in plan.choices:
            actor_key = _canonical_identity_key(choice.actor)
            if choice.kind == "hold":
                if (
                    len(choice.option_ids) != 1
                    or options_by_id.get(choice.option_ids[0]) is None
                    or options_by_id[choice.option_ids[0]].kind != "hold"
                    or actor_key not in actor_menus
                ):
                    return None
                no_attack.add(actor_key)
            elif choice.kind == "take_cover":
                selected = (
                    options_by_id.get(choice.option_ids[0])
                    if len(choice.option_ids) == 1 else None
                )
                if (
                    selected is None
                    or selected.kind != "take_cover"
                    or not selected.feature_id
                    or not isinstance(selected.cover_type, str)
                    or selected.cover_type not in {"half", "three_quarters"}
                    or actor_key not in actor_menus
                ):
                    return None
                no_attack.add(actor_key)
                cover_updates[actor_key] = EnemyCoverUpdate(
                    enemy=choice.actor,
                    feature_id=selected.feature_id,
                    cover_type=selected.cover_type,
                )
            elif choice.kind == "attack" and choice.cover_option_id is not None:
                selected = options_by_id.get(choice.cover_option_id)
                actor_menu = actor_menus.get(actor_key)
                selected_attacks = [
                    next((option for option in slot
                          if option.option_id == option_id), None)
                    for slot, option_id in zip(
                        actor_menu.attack_slots if actor_menu is not None else (),
                        choice.option_ids,
                    )
                ]
                if (
                    selected is None
                    or selected.kind != "take_cover"
                    or not selected.feature_id
                    or selected.cover_type not in {"half", "three_quarters"}
                    or selected.feature_id != choice.cover_feature_id
                    or selected.cover_type != choice.cover_type
                    or actor_menu is None
                    or len(selected_attacks) != len(actor_menu.attack_slots)
                    or any(option is None or option.attack_is_ranged is not True
                           for option in selected_attacks)
                ):
                    return None
                cover_updates[actor_key] = EnemyCoverUpdate(
                    enemy=choice.actor,
                    feature_id=selected.feature_id,
                    cover_type=selected.cover_type,
                )
            elif choice.defeat_reason in {"fled", "surrendered"}:
                cover_updates[actor_key] = EnemyCoverUpdate(enemy=choice.actor)

    entries = tuple(
        entry for entry in ledger.entries
        if _canonical_identity_key(entry.actor) not in no_attack
    )
    for entry in entries:
        if not entry.action_is_ranged:
            cover_updates[_canonical_identity_key(entry.actor)] = EnemyCoverUpdate(
                enemy=entry.actor
            )
    for departure in ledger.departures:
        cover_updates[_canonical_identity_key(departure.enemy)] = EnemyCoverUpdate(
            enemy=departure.enemy
        )
    return replace(
        ledger,
        entries=entries,
        cover_updates=tuple(cover_updates[key] for key in sorted(cover_updates)),
    )


def _tactical_choice_is_issued(
    choice: ValidatedTacticalChoice,
    actor_menu: Any,
    plan: ValidatedTacticalPlan,
) -> bool:
    """Re-check selected option membership against the immutable actor menu."""
    option_ids = choice.option_ids
    if not isinstance(option_ids, tuple) or not option_ids:
        return False
    if choice.kind == "attack":
        if len(option_ids) != len(actor_menu.attack_slots):
            return False
        issued_attacks = all(
            any(option.option_id == option_id and option.kind == "attack"
                for option in slot)
            for option_id, slot in zip(option_ids, actor_menu.attack_slots)
        )
        if not issued_attacks:
            return False
        if choice.cover_option_id is None:
            return True
        cover = next(
            (option for option in actor_menu.choices
             if option.option_id == choice.cover_option_id
             and option.kind == "take_cover"),
            None,
        )
        selected_attacks = [
            next((option for option in slot if option.option_id == option_id), None)
            for option_id, slot in zip(option_ids, actor_menu.attack_slots)
        ]
        return bool(
            cover is not None
            and all(option is not None and option.attack_is_ranged is True
                    for option in selected_attacks)
            and cover.feature_id == choice.cover_feature_id
            and cover.cover_type == choice.cover_type
        )
    if len(option_ids) != 1:
        return False
    selected = next(
        (option for option in actor_menu.choices
         if option.option_id == option_ids[0] and option.kind == choice.kind),
        None,
    )
    if selected is None:
        return False
    return not (
        selected.conditional_on == "withdrawal_order"
        and not plan.withdrawal_order_issued
    )


def _tactical_choice_ledger_outcome(
    choice: ValidatedTacticalChoice,
    ledger: EnemyResolutionLedger,
    actor_menu: Any,
) -> tuple[bool, bool]:
    """Return (applied, followed) using only final-ledger outcomes.

    A projected departure counts as both applied and followed regardless of
    which accepted per-actor choice produced it. Other choices must match the
    final ledger; the independent menu check still rejects forged option IDs.
    """
    actor_key = _canonical_identity_key(choice.actor)
    actor_entries = [
        entry for entry in ledger.entries
        if _canonical_identity_key(entry.actor) == actor_key
    ]
    departures = {
        _canonical_identity_key(departure.enemy): departure.reason
        for departure in ledger.departures
    }
    cover_updates = {
        _canonical_identity_key(update.enemy): update
        for update in ledger.cover_updates
    }

    # The final ledger can replace any selected per-actor option with that
    # actor's projected departure, including side surrender. The matching
    # departure is authoritative regardless of which choice triggered it.
    if departures.get(actor_key) in {"fled", "surrendered"}:
        return True, True

    if choice.kind == "attack":
        if not actor_entries:
            return False, False
        selected_options = []
        if isinstance(choice.option_ids, tuple) and len(choice.option_ids) == len(actor_menu.attack_slots):
            for option_id, slot in zip(choice.option_ids, actor_menu.attack_slots):
                option = next((item for item in slot if item.option_id == option_id), None)
                if option is None:
                    selected_options = []
                    break
                selected_options.append(option)
        if not selected_options:
            return True, False
        expected = Counter(
            (
                " ".join(str(option.action_name or "").split()).casefold(),
                _canonical_identity_key(option.target),
            )
            for option in selected_options
            if option.target is not None
        )
        actual = Counter(
            (
                " ".join(str(entry.action_name or "").split()).casefold(),
                _canonical_identity_key(entry.target),
            )
            for entry in actor_entries
        )
        attacks_followed = bool(expected) and expected == actual
        if choice.cover_option_id is None:
            return True, attacks_followed
        update = cover_updates.get(actor_key)
        cover_followed = bool(
            update is not None
            and update.feature_id == choice.cover_feature_id
            and update.cover_type == choice.cover_type
        )
        return True, attacks_followed and cover_followed

    if choice.kind == "hold":
        applied = not actor_entries and actor_key not in departures
        return applied, applied
    if choice.kind == "take_cover":
        update = cover_updates.get(actor_key)
        applied = update is not None and update.feature_id is not None
        followed = bool(
            applied
            and update.feature_id == choice.cover_feature_id
            and update.cover_type == choice.cover_type
        )
        return bool(applied), followed
    if choice.kind in {"flee", "surrender"}:
        expected_reason = "fled" if choice.kind == "flee" else "surrendered"
        applied = departures.get(actor_key) == expected_reason
        return applied, applied and choice.defeat_reason == expected_reason
    return False, False


def _trace_tactical_application_outcomes(
    plan: Optional[ValidatedTacticalPlan],
    menus: Optional[TacticalMenus],
    ledger: EnemyResolutionLedger,
    *,
    batch_id: Optional[str],
    plan_requested: bool,
) -> None:
    """Trace accepted tactical choices against the immutable final ledger."""
    if (not plan_requested or plan is None or menus is None
            or not combat_latency_trace.trace_enabled()):
        return
    try:
        actor_menus = {
            _canonical_identity_key(menu.actor): menu for menu in menus.actor_menus
        }
        accepted = [choice for choice in plan.choices if choice.default_reason is None]
        applied_count = 0
        legal_applied_count = 0
        followed_count = 0
        for choice in accepted:
            actor_menu = actor_menus.get(_canonical_identity_key(choice.actor))
            if actor_menu is None:
                continue
            applied, followed = _tactical_choice_ledger_outcome(
                choice, ledger, actor_menu
            )
            if not applied:
                continue
            applied_count += 1
            if _tactical_choice_is_issued(choice, actor_menu, plan):
                legal_applied_count += 1
            if followed:
                followed_count += 1

        combat_latency_trace.trace_commander_squad_follows_orders(
            batch_id,
            len(accepted),
            applied_count,
            bool(accepted) and followed_count == len(accepted),
        )
        if applied_count > 0:
            combat_latency_trace.trace_applied_choice_legality(
                batch_id, applied_count, legal_applied_count
            )
    except Exception:
        # Trace construction is observational and must not alter the ledger.
        pass


def _ally_choice_is_issued(choice: Any, menu: Any) -> bool:
    """Check an ally choice against the immutable menu used for its plan."""
    if choice.kind == "take_cover":
        return any(
            option.kind == "take_cover"
            and option.option_id in choice.option_ids
            and len(choice.option_ids) == 1
            and option.feature_id == choice.cover_feature_id
            and option.cover_type == choice.cover_type
            for option in menu.options
        )
    if choice.kind == "attack":
        selected = [
            next((option for option in menu.options
                  if option.option_id == option_id), None)
            for option_id in choice.option_ids
        ]
        attacks = [option for option in selected if option is not None and option.kind == "attack"]
        covers = [option for option in selected if option is not None and option.kind == "take_cover"]
        return bool(
            len(selected) in (1, 2)
            and all(option is not None for option in selected)
            and len(attacks) == 1
            and len(covers) == len(selected) - 1
            and attacks[0].attack == choice.action
            and attacks[0].target == choice.target
            and (not covers or (
                attacks[0].attack.is_ranged is True
                and covers[0].feature_id == choice.cover_feature_id
                and covers[0].cover_type == choice.cover_type
            ))
        )
    return False


def _ally_choice_was_applied(choice: Any, stage: _AllyBatchStage,
                             committed_encounter: Mapping[str, Any]) -> bool:
    """Confirm an ally action in the ledger or authored cover in committed state."""
    actor_key = _canonical_identity_key(choice.actor)
    if choice.kind == "take_cover":
        creatures = committed_encounter.get("creatures")
        matches = [
            row for row in creatures if isinstance(row, Mapping)
            and str(row.get("type", "")).strip().casefold() == "npc"
            and _canonical_identity_key(CombatantIdentity(
                str(row.get("name", "")), "npc"
            )) == actor_key
        ] if isinstance(creatures, list) else []
        return bool(
            len(matches) == 1
            and matches[0].get("coverFeatureId") == choice.cover_feature_id
            and matches[0].get("coverType") == choice.cover_type
        )
    if choice.kind == "attack":
        return any(
            isinstance(entry, EnemyAttackLedgerEntry)
            and _canonical_identity_key(entry.actor) == actor_key
            for entry in stage.ledger.entries
        )
    return False


def _trace_ally_cover_selections(
    menus: Any,
    plan: Any,
    *,
    batch_id: Optional[str],
    actor_ids: Optional[Mapping[tuple[str, str], str]],
) -> None:
    """Trace issued ally cover choices before projection and persistence."""
    if (not isinstance(menus, AllyMenus) or not isinstance(plan, ValidatedAllyPlan)
            or batch_id is None or actor_ids is None
            or not combat_latency_trace.trace_enabled()):
        return
    try:
        menus_by_actor = {
            _canonical_identity_key(menu.actor): menu
            for menu in menus.actor_menus
        }
        for choice in plan.choices:
            if choice.kind != "take_cover":
                continue
            actor_key = _canonical_identity_key(choice.actor)
            actor_id = actor_ids.get(actor_key)
            menu = menus_by_actor.get(actor_key)
            if actor_id is None or menu is None or not _ally_choice_is_issued(choice, menu):
                continue
            combat_latency_trace.trace_tactical_cover_outcome(
                batch_id,
                actor_id,
                choice.cover_feature_id,
                choice.cover_type,
                "selected",
            )
    except Exception:
        # Selection telemetry is observational and cannot alter ally resolution.
        pass


def _trace_ally_choice_commit_results(
    stage: Optional[_AllyBatchStage],
    committed_encounter: Mapping[str, Any],
    history: Any,
    *,
    batch_id: Optional[str],
    actor_ids: Optional[Mapping[tuple[str, str], str]],
) -> None:
    """Hash-link pending directives to issued choices and their persisted effects."""
    if (stage is None or batch_id is None or actor_ids is None
            or not combat_latency_trace.trace_enabled()):
        return
    try:
        directives = latest_ally_directives_from_history(
            history,
            active_allies=tuple(menu.actor for menu in stage.menus.actor_menus),
        )
        directives_by_actor = {
            " ".join(name.split()).casefold(): text
            for name, text in directives.items()
            if isinstance(name, str) and isinstance(text, str)
        }
        menus_by_actor = {
            _canonical_identity_key(menu.actor): menu
            for menu in stage.menus.actor_menus
        }
        for choice in stage.plan.choices:
            actor_key = _canonical_identity_key(choice.actor)
            actor_id = actor_ids.get(actor_key)
            if actor_id is None:
                continue
            menu = menus_by_actor.get(actor_key)
            choice_legal = menu is not None and _ally_choice_is_issued(choice, menu)
            choice_applied = _ally_choice_was_applied(
                choice, stage, committed_encounter
            )
            directive = directives_by_actor.get(actor_key[1])
            directive_sha256 = (
                hashlib.sha256(directive.encode("utf-8")).hexdigest()
                if directive is not None else None
            )
            prefetch_rejection_reason = getattr(
                stage, "prefetch_rejection_reason", None
            )
            prefetch_trace_kwargs = {}
            if prefetch_rejection_reason is not None:
                prefetch_trace_kwargs["prefetch_rejection_reason"] = (
                    prefetch_rejection_reason
                )
            combat_latency_trace.trace_ally_choice_commit_result(
                batch_id,
                actor_id,
                choice.kind,
                choice_legal,
                choice.default_reason is not None,
                choice_applied,
                cover_feature_id=choice.cover_feature_id,
                directive_sha256=directive_sha256,
                directive_request_kind=(
                    stage.plan_request_kind if directive_sha256 is not None else None
                ),
                prefetch_resolution=getattr(stage, "prefetch_resolution", None),
                **prefetch_trace_kwargs,
            )
            if choice.kind == "take_cover" and choice_legal and choice_applied:
                # The ally projection is already present in the encounter passed
                # to apply_enemy_batch, so its before/after diff cannot prove this
                # effect. Emit applied only after the committed encounter confirms
                # the authored feature and cover type for this NPC.
                combat_latency_trace.trace_tactical_cover_outcome(
                    batch_id,
                    actor_id,
                    choice.cover_feature_id,
                    choice.cover_type,
                    "applied",
                )
    except Exception:
        # The receipt/commit path is authoritative; optional evidence is fail-open.
        pass


def _trace_tactical_plan_result(
    plan: ValidatedTacticalPlan,
    *,
    batch_id: Optional[str],
    menus: TacticalMenus,
    actor_ids: Optional[Mapping[tuple[str, str], str]] = None,
    prefetch_status: str = "prefetch_none",
    receipt_correlation_id: Optional[str] = None,
    plan_origin: Optional[str] = None,
    standing_orders_outcome: Optional[str] = None,
) -> None:
    try:
        plan_correlation_id = ("plan-" + menus.batch_id)[:80]
        menu_actor_ids = []
        menu_target_ids = []
        if actor_ids is not None:
            for actor_menu in menus.actor_menus:
                actor_id = actor_ids.get(_canonical_identity_key(actor_menu.actor))
                if actor_id is not None:
                    menu_actor_ids.append(actor_id)
            for target in menus.target_catalog:
                actor_id = actor_ids.get(_canonical_identity_key(target))
                if actor_id is not None:
                    menu_target_ids.append(actor_id)
        combat_latency_trace.trace_tactical_plan_result(
            batch_id=batch_id,
            plan_correlation_id=plan_correlation_id,
            tactical_plan_outcome=plan.status,
            default_reasons=_tactical_default_reasons(plan, actor_ids),
            prefetch_status=prefetch_status,
            actor_ids=menu_actor_ids,
            target_ids=menu_target_ids,
            plan_origin=plan_origin,
            standing_orders_outcome=standing_orders_outcome,
        )
        prefetch_trace_kwargs = {}
        if receipt_correlation_id is not None:
            prefetch_trace_kwargs["receipt_correlation_id"] = receipt_correlation_id
        if standing_orders_outcome is not None:
            prefetch_trace_kwargs["standing_orders_outcome"] = standing_orders_outcome
        if plan_origin is not None:
            prefetch_trace_kwargs["plan_origin"] = plan_origin
        combat_latency_trace.trace_tactical_prefetch_status(
            batch_id, plan_correlation_id, prefetch_status, **prefetch_trace_kwargs
        )
        for choice in plan.choices:
            if choice.kind != "take_cover" and choice.cover_option_id is None:
                continue
            actor_id = (
                actor_ids.get(_canonical_identity_key(choice.actor))
                if actor_ids is not None else None
            )
            if actor_id is None:
                continue
            combat_latency_trace.trace_tactical_cover_outcome(
                batch_id,
                actor_id,
                choice.cover_feature_id,
                choice.cover_type,
                "selected",
            )
    except Exception:
        pass


def _trace_tactical_prefetch_status(
    batch_id: Optional[str],
    prefetch_status: Optional[str],
    receipt_correlation_id: Optional[str] = None,
    *,
    standing_orders_outcome: Optional[str] = None,
    request_kind: Optional[str] = None,
) -> None:
    """Emit one bounded prefetch lifecycle status without affecting resolution."""
    if batch_id is None:
        return
    try:
        trace_kwargs = {}
        if receipt_correlation_id is not None:
            trace_kwargs["receipt_correlation_id"] = receipt_correlation_id
        if standing_orders_outcome is not None:
            trace_kwargs["standing_orders_outcome"] = standing_orders_outcome
        if request_kind is not None:
            trace_kwargs["request_kind"] = request_kind
            trace_kwargs["request_site"] = "combat_tactical_prefetch"
        combat_latency_trace.trace_tactical_prefetch_status(
            batch_id,
            ("plan-" + batch_id)[:80],
            prefetch_status,
            **trace_kwargs,
        )
    except Exception:
        pass


def try_execute_deterministic_enemy_batch(
    encounter_data: Any,
    conversation_history: Any,
    user_input_text: Any,
    *,
    initial_conversation_length: int,
    encounter_id: Any,
    conversation_history_file: str,
    path_manager: Any,
    multi_pc_manager: Any,
    monster_definitions: Any,
    scene_context: Any,
    dependencies: EnemyBatchOrchestrationDependencies,
    logical_turn: Optional[int] = None,
    party_tracker_data: Optional[Mapping[str, Any]] = None,
) -> Optional[EnemyBatchExecution | EnemyBatchFallback]:
    """Execute only recognized enemy batches; otherwise leave legacy untouched.

    Planning and lifecycle classification are read-only. A resolver decline or
    preflight error returns a bounded fallback outcome before narration, lifecycle
    mutation, or persistence. Provider terminal errors and apply failures remain
    visible to the existing combat/router owner and are not replayed as legacy.
    """
    if not isinstance(user_input_text, str) or user_input_text.strip() != "Enemies turn.":
        return None

    decision_started_at = time.perf_counter()
    trace_batch_id = _trace_batch_id(encounter_data)
    trace_actor_ids = combat_latency_trace.build_run_local_actor_ids(
        encounter_data.get("creatures") if isinstance(encounter_data, Mapping) else None
    )
    batch_logical_turn = (
        logical_turn + 1
        if isinstance(logical_turn, int) and not isinstance(logical_turn, bool) and logical_turn >= 0
        else None
    )
    raw_prefetch_round = (
        encounter_data.get("combat_round", encounter_data.get("current_round", 1))
        if isinstance(encounter_data, Mapping) else None
    )
    prefetch_batch_id = tactical_batch_id(encounter_id, raw_prefetch_round)
    tactical_prefetch_status = "prefetch_none"
    tactical_prefetch_correlation_id: Optional[str] = None
    standing_orders_outcome: Optional[str] = None
    tactical_plan_origin: Optional[str] = None
    standing_order_intent: Optional[str] = None
    try:
        work_unit_context = combat_latency_trace.build_work_unit_trace_context(
            encounter_data.get("combat_round", encounter_data.get("current_round", 1))
            if isinstance(encounter_data, Mapping) else None,
            "ENEMY_PHASE",
            None,
        )
        if trace_batch_id is not None and work_unit_context.get("batch_id") == trace_batch_id:
            trace_context = {
                "mode": "mp" if multi_pc_manager is not None else "one_pc",
                "phase": "ENEMY_PHASE",
                **work_unit_context,
            }
            if isinstance(encounter_data, Mapping):
                raw_round = encounter_data.get("combat_round", encounter_data.get("current_round", 1))
                if isinstance(raw_round, int) and not isinstance(raw_round, bool):
                    trace_context["combat_round"] = raw_round
            combat_latency_trace.set_trace_context(**trace_context)
    except Exception:
        # Batch attribution is observational and must never affect the resolver.
        pass

    def record_decision(
        outcome: str,
        reason: str,
        *,
        decision_source: Optional[str] = None,
        tactical_plan: Optional[ValidatedTacticalPlan] = None,
    ) -> None:
        if trace_batch_id is None:
            return
        try:
            trace_kwargs: dict[str, Any] = {"logical_turn": batch_logical_turn}
            if decision_source is not None:
                trace_kwargs["decision_source"] = decision_source
            if tactical_plan is not None:
                trace_kwargs["tactical_plan_outcome"] = tactical_plan.status
                trace_kwargs["default_reasons"] = _tactical_default_reasons(
                    tactical_plan, trace_actor_ids
                )
                trace_kwargs["prefetch_status"] = tactical_prefetch_status
            if tactical_plan_origin is not None:
                trace_kwargs["plan_origin"] = tactical_plan_origin
            if standing_orders_outcome is not None:
                trace_kwargs["standing_orders_outcome"] = standing_orders_outcome
            combat_latency_trace.trace_enemy_batch_decision(
                outcome, reason, trace_batch_id, decision_started_at, **trace_kwargs
            )
        except Exception:
            pass

    def fallback(reason_code: str) -> EnemyBatchFallback:
        nonlocal tactical_prefetch_status, tactical_prefetch_correlation_id
        result = _fallback(reason_code, dependencies)
        invalidated = (
            invalidate_tactical_prefetch(str(encounter_id), prefetch_batch_id)
            if prefetch_batch_id is not None else TacticalPrefetchResult("prefetch_none")
        )
        if invalidated.status == "prefetch_stale":
            tactical_prefetch_status = invalidated.status
            tactical_prefetch_correlation_id = invalidated.receipt_correlation_id
            _trace_tactical_prefetch_status(
                trace_batch_id,
                tactical_prefetch_status,
                tactical_prefetch_correlation_id,
                standing_orders_outcome="invalidated",
            )
        record_decision("whole_batch_fallback", result.reason_code)
        return result

    tactical_brain_enabled = is_combat_tactical_brain_enabled()
    ally_controller_enabled = is_ally_controller_enabled()
    if not is_deterministic_enemy_resolution_enabled():
        record_decision("resolver_disabled", "resolver_disabled")
        return None

    lifecycle_case = _lifecycle_case(encounter_data, multi_pc_manager)
    if lifecycle_case is None:
        return fallback("round_transition_unsupported")

    try:
        if not isinstance(encounter_data, dict) or not isinstance(conversation_history, list):
            raise ValueError("malformed_input")
        if not isinstance(initial_conversation_length, int) or isinstance(initial_conversation_length, bool):
            raise ValueError("malformed_input")
        if initial_conversation_length != len(conversation_history) or initial_conversation_length < 1:
            raise ValueError("malformed_input")

        current_user_message = conversation_history[initial_conversation_length - 1]
        if (not isinstance(current_user_message, Mapping)
                or current_user_message.get("role") != "user"
                or not isinstance(current_user_message.get("content"), str)):
            raise ValueError("malformed_input")
        turn_id = current_user_message.get("turn_id")
        history_before_user = conversation_history[:initial_conversation_length - 1]

        resolved_encounter_id = encounter_data.get("encounterId", encounter_data.get("id"))
        if (not isinstance(resolved_encounter_id, str) or not resolved_encounter_id.strip()
                or str(encounter_id) != resolved_encounter_id):
            raise ValueError("malformed_encounter")
        applied_id = compute_applied_id(resolved_encounter_id, turn_id)
        raw_round = encounter_data.get("combat_round", encounter_data.get("current_round", 1))
        if not isinstance(raw_round, int) or isinstance(raw_round, bool) or raw_round < 1:
            raise ValueError("malformed_encounter")
        round_number = raw_round

        if not isinstance(monster_definitions, Mapping):
            raise ValueError("malformed_monster_definitions")
        party_states = _pc_states(
            encounter_data,
            path_manager,
            dependencies.read_json,
            applied_id=applied_id,
        )
        turn_order = _turn_order(multi_pc_manager)
        working_encounter = encounter_data
        ally_first = (
            ally_controller_enabled
            and encounter_data.get("roundStartsWith") != "dmGroup"
        )
        ally_stage: Optional[_AllyBatchStage] = None
        if ally_first:
            ally_stage = _run_ally_batch(
                working_encounter,
                encounter_id=resolved_encounter_id,
                turn_order=turn_order,
                history=conversation_history,
                scene_context=scene_context,
                dependencies=dependencies,
                trace_batch_id=trace_batch_id,
                trace_actor_ids=trace_actor_ids,
            )
            if ally_stage is not None:
                working_encounter = ally_stage.encounter_projection

        if ally_controller_enabled:
            enemy_window = _active_enemy_window(working_encounter, turn_order)
        else:
            enemy_names = multi_pc_manager.get_remaining_enemies_for_round()
            if not isinstance(enemy_names, list):
                raise ValueError("malformed_turn_order")
            enemy_window = [{"name": name} for name in enemy_names]
        batch_id = _batch_id(resolved_encounter_id, round_number)
        standing_orders_path_selected = (
            is_combat_tactical_prefetch_enabled()
            and has_tactical_prefetch_submission(resolved_encounter_id, batch_id)
        )
        resolver_arguments = (
            working_encounter,
            party_states,
            monster_definitions,
            turn_order,
        )
        resolver_options = {
            "batch_id": batch_id,
            "batch_kind": "enemy_phase",
            "fixture_seed": None,
            "enemy_turn_window": enemy_window,
            "active_encounter_id": (
                scene_context.get("active_encounter_id")
                if isinstance(scene_context, Mapping) else None
            ),
            "combat_in_progress": (
                scene_context.get("combat_in_progress") is True
                if isinstance(scene_context, Mapping) else False
            ),
            "tactical_features": _tactical_features(scene_context),
            # Only a uniquely designated living commander may replace 4b's
            # near-death whole-batch decline with tactical self-preservation.
            "allow_near_death": tactical_brain_enabled and (
                _has_living_commander(working_encounter)
                or standing_orders_path_selected
            ),
        }
        if ally_controller_enabled and ally_first and ally_stage is not None and not enemy_window:
            planned = EnemyResolutionLedger(
                encounter_id=resolved_encounter_id,
                round_number=round_number,
                batch_id=batch_id,
                batch_kind="enemy_phase",
                seed=ally_stage.ledger.seed,
                entries=(),
                bloodied=(),
            )
        else:
            planned = dependencies.plan(*resolver_arguments, **resolver_options)
    except _AllyBatchNarrationError as exc:
        raise exc.error from exc
    except Exception:
        return fallback("preflight_error")

    if isinstance(planned, EnemyResolutionDecline):
        reason = planned.reason_code
        return fallback(reason)
    if not isinstance(planned, EnemyResolutionLedger):
        return fallback("malformed_result")
    default_ledger = planned

    tactical_plan: Optional[ValidatedTacticalPlan] = None
    tactical_plan_intent = None
    tactical_decision_source: Optional[str] = None
    menus = None
    if tactical_brain_enabled:
        try:
            built_menus = build_tactical_menus(
                working_encounter,
                party_states,
                monster_definitions,
                turn_order,
                batch_id=batch_id,
                batch_kind="enemy_phase",
                fixture_seed=None,
                enemy_turn_window=enemy_window,
                tactical_features=_tactical_features(scene_context),
                active_encounter_id=resolver_options["active_encounter_id"],
                combat_in_progress=resolver_options["combat_in_progress"],
                allow_commander_down=standing_orders_path_selected,
            )
            if isinstance(built_menus, TacticalMenus):
                menus = built_menus
        except Exception:
            # The default resolver ledger remains complete and authoritative.
            menus = None

        if menus is not None:
            plan_submitted = False
            plan_response: Any = None
            prefetch_result = TacticalPrefetchResult("prefetch_none")
            if standing_orders_path_selected:
                try:
                    current_snapshot = _standing_order_state_snapshot(
                        working_encounter, party_states
                    )
                    prefetch_result = consume_tactical_prefetch(
                        resolved_encounter_id,
                        batch_id,
                        current_roster_members=current_snapshot["roster"],
                    )
                except Exception:
                    # The selected asynchronous path never creates a /end request.
                    prefetch_result = TacticalPrefetchResult(
                        "standing_orders_unavailable"
                    )
                tactical_prefetch_status = prefetch_result.status
                tactical_prefetch_correlation_id = prefetch_result.receipt_correlation_id
                if prefetch_result.error is not None:
                    if _is_terminal_router_error(prefetch_result.error):
                        raise prefetch_result.error
                if prefetch_result.status == "prefetch_hit":
                    parsed_orders = parse_standing_orders_response(
                        prefetch_result.result
                    )
                    plan_response = compile_standing_orders(
                        parsed_orders,
                        menus,
                        working_encounter,
                        ally_departed=prefetch_result.ally_departed,
                    ) if parsed_orders is not None else None
                    if plan_response is None:
                        standing_orders_outcome = "standing_orders_unavailable"
                        tactical_prefetch_status = "standing_orders_unavailable"
                        tactical_plan = rule_default_tactical_plan(
                            menus, STANDING_ORDER_DEFAULT_REASON
                        )
                    else:
                        plan_submitted = True
                        tactical_plan_origin = "standing_orders"
                        standing_orders_outcome = "standing_orders"
                        standing_order_intent = standing_orders_intent(parsed_orders)
                        tactical_plan = validate_commander_plan(plan_response, menus)
                else:
                    standing_orders_outcome = "standing_orders_unavailable"
                    tactical_prefetch_status = "standing_orders_unavailable"
                    tactical_plan = rule_default_tactical_plan(
                        menus, STANDING_ORDER_DEFAULT_REASON
                    )
                if standing_orders_outcome == "standing_orders_unavailable":
                    _trace_tactical_prefetch_status(
                        trace_batch_id,
                        "standing_orders_unavailable",
                        tactical_prefetch_correlation_id,
                        standing_orders_outcome="standing_orders_unavailable",
                    )
            else:
                try:
                    plan_messages = build_commander_plan_messages(
                        menus,
                        party_states,
                        actor_dispositions=_creature_descriptions(
                            working_encounter, monster_definitions
                        ),
                    )
                    plan_observer = dependencies.receipt_observer_factory(
                        trace_site="combat_main",
                        track_usage=dependencies.usage_tracking_available,
                        legacy_context={
                            "purpose": "combat_enemy_batch_commander_plan",
                            "legacy_context_model": dependencies.combat_main_model,
                        },
                    )
                    plan_submitted = True
                    # TABLETOP MODE: The tactical commander plan is validated as a JSON object.
                    plan_response = dependencies.llm_call(
                        "combat_main",
                        plan_messages,
                        # Keep the synchronous request contract unchanged.
                        json_output=False,
                        max_tokens=1200,
                        observer=plan_observer,
                        json_contract=True,
                    )
                    tactical_plan = validate_commander_plan(plan_response, menus)
                except Exception as exc:
                    if _is_terminal_router_error(exc):
                        raise
                    tactical_plan = validate_commander_plan(None, menus)

            if tactical_plan.status != "accepted":
                try:
                    try:
                        compact_plan = json.dumps(
                            plan_response,
                            ensure_ascii=True,
                            separators=(",", ":"),
                            default=str,
                        )
                    except Exception:
                        compact_plan = "<unserializable>"
                    if len(compact_plan) > 1000:
                        compact_plan = compact_plan[:997] + "..."
                    default_reasons = sorted({
                        choice.default_reason for choice in tactical_plan.choices
                        if choice.default_reason
                    })
                    debug(
                        "COMMANDER_PLAN_REJECTED batch_id=%s status=%s "
                        "default_reasons=%s plan=%s" % (
                            batch_id,
                            tactical_plan.status,
                            ",".join(default_reasons) or "none",
                            compact_plan,
                        ),
                        category="combat_events",
                    )
                except Exception:
                    # Diagnostics must never affect the authoritative fallback.
                    pass

            if plan_submitted:
                tactical_decision_source = "llm_tactical"

            has_self_preservation = bool(
                tactical_plan.side_surrender
                or any(choice.defeat_reason for choice in tactical_plan.choices)
            )
            overrides, changed_targets, unsupported_choice = _attack_target_overrides(
                menus, tactical_plan
            )
            if unsupported_choice:
                if has_self_preservation:
                    defaulted_plan = _default_unapplied_choices(tactical_plan, menus)
                    if defaulted_plan is not None:
                        tactical_plan = defaulted_plan
                        overrides, changed_targets, unsupported_choice = _attack_target_overrides(
                            menus, tactical_plan
                        )
                    else:
                        unsupported_choice = True
                if unsupported_choice:
                    tactical_plan = validate_commander_plan(None, menus)
                    overrides, changed_targets, _ = _attack_target_overrides(menus, tactical_plan)
                    has_self_preservation = False

            if has_self_preservation and not unsupported_choice:
                hooked_ledger = _task_3_2_self_preservation_hook(
                    tactical_plan,
                    menus,
                    default_ledger,
                    dependencies,
                    resolver_arguments,
                    resolver_options,
                    overrides,
                    nonattacking_actors=_nonattacking_actor_keys(tactical_plan),
                )
                if hooked_ledger is None:
                    tactical_plan = validate_commander_plan(None, menus)
                    planned = default_ledger
                else:
                    planned = hooked_ledger
            elif changed_targets and not unsupported_choice:
                try:
                    final_ledger = dependencies.plan(
                        *resolver_arguments,
                        **resolver_options,
                        attack_target_overrides=overrides,
                    )
                except Exception:
                    final_ledger = None
                if isinstance(final_ledger, EnemyResolutionLedger):
                    planned = final_ledger
                else:
                    # A stale or unusable candidate cannot create a partial
                    # prefix; restore the complete deterministic rule ledger.
                    planned = dependencies.plan(*resolver_arguments, **resolver_options)
                    tactical_plan = validate_commander_plan(None, menus)

            tactical_plan_intent = _tactical_plan_intent(tactical_plan, planned)
            if standing_order_intent:
                for intent_row in tactical_plan_intent:
                    intent_row["standing_order_intent"] = standing_order_intent
            _trace_tactical_plan_result(
                tactical_plan,
                batch_id=trace_batch_id,
                menus=menus,
                actor_ids=trace_actor_ids,
                prefetch_status=tactical_prefetch_status,
                receipt_correlation_id=tactical_prefetch_correlation_id,
                plan_origin=tactical_plan_origin,
                standing_orders_outcome=standing_orders_outcome,
            )
        elif standing_orders_path_selected:
            tactical_prefetch_status = "standing_orders_unavailable"
            standing_orders_outcome = "standing_orders_unavailable"
            _trace_tactical_prefetch_status(
                trace_batch_id,
                tactical_prefetch_status,
                standing_orders_outcome=standing_orders_outcome,
            )
        elif is_combat_tactical_prefetch_enabled():
            # A submitted plan cannot outlive a batch for which current menus
            # could not be constructed; its late completion is discarded.
            invalidated = invalidate_tactical_prefetch(resolved_encounter_id, batch_id)
            if invalidated.status == "prefetch_stale":
                tactical_prefetch_status = invalidated.status
                tactical_prefetch_correlation_id = invalidated.receipt_correlation_id
                _trace_tactical_prefetch_status(
                    trace_batch_id,
                    tactical_prefetch_status,
                    tactical_prefetch_correlation_id,
                )

    projected_ledger = _apply_tactical_choices_to_ledger(
        planned, tactical_plan, menus
    )
    if projected_ledger is None:
        if menus is not None:
            tactical_plan = validate_commander_plan(None, menus)
        projected_ledger = _apply_tactical_choices_to_ledger(
            default_ledger, tactical_plan, menus
        )
    if projected_ledger is None:
        projected_ledger = _apply_tactical_choices_to_ledger(
            default_ledger, None, None
        )
    if projected_ledger is None:
        return fallback("malformed_result")
    planned = projected_ledger
    if ally_controller_enabled:
        working_encounter = project_combat_resolution_ledger(
            planned,
            working_encounter,
        )
    _trace_tactical_application_outcomes(
        tactical_plan,
        menus,
        planned,
        batch_id=trace_batch_id,
        plan_requested=tactical_decision_source == "llm_tactical",
    )

    if ally_controller_enabled and not ally_first:
        try:
            ally_stage = _run_ally_batch(
                working_encounter,
                encounter_id=resolved_encounter_id,
                turn_order=turn_order,
                history=conversation_history,
                scene_context=scene_context,
                dependencies=dependencies,
                trace_batch_id=trace_batch_id,
                trace_actor_ids=trace_actor_ids,
            )
        except _AllyBatchUnsupported:
            return fallback("preflight_error")
        except _AllyBatchNarrationError as exc:
            raise exc.error from exc
        if ally_stage is not None:
            working_encounter = ally_stage.encounter_projection

    narration: Optional[NarrationResult] = None
    if ally_first and ally_stage is not None:
        try:
            ally_stage = _narrate_ally_stage(
                ally_stage, conversation_history, dependencies
            )
        except _AllyBatchNarrationError as exc:
            raise exc.error from exc

    if planned.entries or planned.departures or planned.cover_updates:
        observer = dependencies.receipt_observer_factory(
            trace_site="combat_main",
            track_usage=dependencies.usage_tracking_available,
            legacy_context={
                "purpose": "combat_enemy_batch_narration",
                "legacy_context_model": dependencies.combat_main_model,
            },
        )
        try:
            narration = dependencies.narrate(
                planned,
                scene_context,
                _creature_descriptions(working_encounter, monster_definitions),
                dependencies.llm_call,
                receipt_observer=observer,
                tactical_plan_intent=tactical_plan_intent,
            )
        except Exception:
            record_decision(
                "resolver_supported",
                "ledger_supported",
                decision_source=tactical_decision_source,
                tactical_plan=tactical_plan,
            )
            raise
        decision_reason = "ledger_supported"
        if (getattr(narration, "source", None) == "template"
                and isinstance(getattr(narration, "reason_code", None), str)):
            decision_reason = narration.reason_code
        record_decision(
            "resolver_supported",
            decision_reason,
            decision_source=tactical_decision_source,
            tactical_plan=tactical_plan,
        )

    if not ally_first and ally_stage is not None:
        try:
            ally_stage = _narrate_ally_stage(
                ally_stage, conversation_history, dependencies
            )
        except _AllyBatchNarrationError as exc:
            raise exc.error from exc

    combined_ledger = _combine_side_ledgers(
        planned,
        ally_stage,
        ally_first=ally_first,
    )
    combined_narration = (
        _combine_side_narration(narration, ally_stage, ally_first=ally_first)
        if ally_stage is not None else narration
    )
    if combined_narration is None:
        return fallback("malformed_result")

    pre_action_context = None
    if batch_logical_turn is not None:
        try:
            parsed_lifecycle_response = (
                {"combat_round": round_number + 1}
                if lifecycle_case == "pc_phase_end" else {}
            )
            pre_action_context = capture_pre_round_transition_combat_context(
                encounter_data,
                multi_pc_manager,
                parsed_lifecycle_response,
                True,
                batch_logical_turn,
            )
            if pre_action_context is not None:
                traced_actions = []
                for entry in planned.entries:
                    target_field = (
                        "characterName" if entry.target.kind == "player" else "targetName"
                    )
                    operation = {
                        "op": "hp_delta",
                        "delta": entry.target_hp_after - entry.target_hp_before,
                    }
                    if entry.target.kind != "player":
                        operation["creature"] = entry.target.name
                    traced_actions.append({
                        "action": (
                            "updateCharacterInfo" if entry.target.kind == "player"
                            else "updateEncounter"
                        ),
                        "parameters": {
                            "actorName": entry.actor.name,
                            target_field: entry.target.name,
                            "ops": [operation],
                        },
                    })
                trace_combat_action_batch_metadata(
                    CombatActionTraceInputs(
                        actions=traced_actions,
                        encounter_data=encounter_data,
                        encounter_id=resolved_encounter_id,
                        pre_action_context=pre_action_context,
                        validation_accepted=True,
                        batch_id=trace_batch_id,
                    ),
                    CombatActionTraceDependencies(
                        trace_enabled=combat_latency_trace.trace_enabled,
                        trace_observation=combat_latency_trace.trace_combat_observation,
                    ),
                )
        except Exception:
            # Evidence collection is observational and must not change resolution.
            pre_action_context = None

    if narration is not None:
        try:
            combat_latency_trace.trace_combat_observation(
                "combat_batch_narration_result",
                batch_id=trace_batch_id,
                logical_turn=batch_logical_turn,
                source=narration.source,
                reason_code=narration.reason_code,
                reason_detail=narration.reason_detail,
            )
        except Exception:
            pass

    lifecycle_encounter = working_encounter
    if lifecycle_case == "pc_phase_end":
        transition = dependencies.apply_round_transition(
            lifecycle_encounter,
            history_before_user,
            phase_before="ENEMY_PHASE",
            phase_after="PC_PHASE",
            enemy_batch_completed=True,
            opening_batch_pending_before=False,
            dependencies=dependencies.round_transition_dependencies,
        )
        history_before_user = transition.conversation_history
        lifecycle_encounter = transition.encounter_data
    elif lifecycle_case == "opening_batch":
        transition = dependencies.apply_round_transition(
            lifecycle_encounter,
            history_before_user,
            phase_before="ENEMY_PHASE",
            phase_after="PC_PHASE",
            enemy_batch_completed=True,
            opening_batch_pending_before=True,
            dependencies=dependencies.round_transition_dependencies,
        )
        history_before_user = transition.conversation_history
        lifecycle_encounter = transition.encounter_data

    apply_kwargs = {}
    if ally_stage is not None:
        apply_kwargs["ally_directive_actors"] = tuple(
            menu.actor for menu in ally_stage.menus.actor_menus
        )
    application = dependencies.apply(
        combined_ledger,
        combined_narration,
        user_input_text=current_user_message["content"],
        conversation_history=history_before_user,
        conversation_history_file=conversation_history_file,
        encounter_projection=lifecycle_encounter,
        path_manager=path_manager,
        multi_pc_manager=multi_pc_manager,
        clean_old_dm_notes=dependencies.clean_old_dm_notes,
        clean_combat_state_blocks=dependencies.clean_combat_state_blocks,
        read_json=dependencies.read_json,
        write_json=dependencies.write_json,
        turn_id=turn_id,
        party_tracker_data=party_tracker_data,
        calculate_xp_for_encounter=dependencies.calculate_xp_for_encounter,
        check_all_monsters_defeated=dependencies.check_all_monsters_defeated,
        validate_character=dependencies.validate_character,
        **apply_kwargs,
    )
    dependencies.round_transition_dependencies.log_info(
        f"DETERMINISTIC_ENEMY_BATCH: Applied batch_id={combined_ledger.batch_id} "
        f"lifecycle={lifecycle_case} writes={application.write_count}",
        category="combat_events",
    )
    _trace_ally_choice_commit_results(
        ally_stage,
        application.encounter_projection,
        conversation_history,
        batch_id=trace_batch_id,
        actor_ids=trace_actor_ids,
    )
    sync_committed_combat_turn(
        application.encounter_projection,
        multi_pc_manager,
        dependencies.session,
    )
    dependencies.publish_narration(
        combined_narration.text,
        applied_id=application.applied_id,
    )
    try:
        if batch_logical_turn is not None:
            combat_latency_trace.trace_combat_observation(
                "combat_logical_batch_completed",
                batch_id=trace_batch_id,
                logical_turn=batch_logical_turn,
                validation_accepted=True,
                accepted_batch=True,
                phase_before_round_transition=(pre_action_context or {}).get("phase"),
                phase_after_processing=getattr(multi_pc_manager, "combat_phase", None),
                round_before=(pre_action_context or {}).get("combat_round", round_number),
                round_after=application.encounter_projection.get(
                    "combat_round", application.encounter_projection.get("current_round")
                ),
                opening_pending_before=(pre_action_context or {}).get(
                    "opening_batch_pending", encounter_data.get("openingEnemyBatchPending")
                ),
                opening_pending_after=application.encounter_projection.get("openingEnemyBatchPending"),
                eligible_non_pc_cohort=(pre_action_context or {}).get("eligible_non_pc_cohort", []),
                is_combat_ending=False,
            )
    except Exception:
        pass
    invalidated = invalidate_tactical_prefetch(resolved_encounter_id, batch_id)
    if invalidated.status == "prefetch_stale":
        _trace_tactical_prefetch_status(
            trace_batch_id,
            "prefetch_stale",
            invalidated.receipt_correlation_id,
            standing_orders_outcome="invalidated",
        )
    if (
        is_combat_tactical_prefetch_enabled()
        and getattr(multi_pc_manager, "combat_phase", None) == "PC_PHASE"
    ):
        active_encounter_id = (
            scene_context.get("active_encounter_id")
            if isinstance(scene_context, Mapping) else None
        )
        submit_tactical_prefetch_for_enemy_batch(
            application.encounter_projection,
            encounter_id=resolved_encounter_id,
            multi_pc_manager=multi_pc_manager,
            monster_definitions=monster_definitions,
            path_manager=path_manager,
            read_json=dependencies.read_json,
            scene_context={
                "location": (
                    scene_context.get("location")
                    if isinstance(scene_context, Mapping) else None
                ),
                "active_encounter_id": active_encounter_id,
                "combat_in_progress": True,
            },
            llm_call=dependencies.llm_call,
            receipt_observer_factory=dependencies.receipt_observer_factory,
            usage_tracking_available=dependencies.usage_tracking_available,
            combat_main_model=dependencies.combat_main_model,
        )
    if getattr(multi_pc_manager, "combat_phase", None) == "PC_PHASE":
        try:
            from core.combat.ally_prefetch import submit_ally_prefetch

            world_context = scene_context if isinstance(scene_context, Mapping) else {}
            submit_ally_prefetch(
                application.encounter_projection,
                encounter_id=resolved_encounter_id,
                multi_pc_manager=multi_pc_manager,
                active_encounter_id=world_context.get("active_encounter_id"),
                npc_profiles=world_context.get("npc_profiles"),
                history=application.conversation_history,
                tactical_features=_tactical_features(scene_context),
                llm_call=dependencies.llm_call,
                trigger="initial",
                receipt_observer_factory=dependencies.receipt_observer_factory,
                usage_tracking_available=dependencies.usage_tracking_available,
                combat_main_model=dependencies.combat_main_model,
            )
        except Exception:
            # PC-phase ally prefetch is optional and cannot affect the commit.
            pass
    return EnemyBatchExecution(
        ledger=combined_ledger,
        narration=combined_narration,
        conversation_history=application.conversation_history,
        encounter_data=application.encounter_projection,
        application=application,
        lifecycle_case=lifecycle_case,
        logical_turn=batch_logical_turn,
    )
