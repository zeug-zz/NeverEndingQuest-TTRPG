# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Apply a completed deterministic enemy batch in the established write order."""

from __future__ import annotations

import copy
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Optional

import model_config
from core.combat.enemy_narration import NarrationResult
from core.combat.enemy_resolution import (
    CombatantIdentity,
    EnemyCoverUpdate,
    EnemyDeparture,
    EnemyResolutionLedger,
)
from utils.encoding_utils import safe_json_load
from utils.file_operations import safe_write_json
from utils import combat_latency_trace
from core.combat.persistence import _bounded_encounter_hp_projection
from core.combat.turn_commit import (
    TurnCharacterEffect,
    TurnCommitError,
    build_accepted_input_record,
    commit_combat_turn,
    compute_applied_id,
    history_with_combat_turn_manifest,
    read_character_applied_id,
)
from core.combat.ally_controller import mark_ally_directives_consumed


_FAILURE_STAGES = frozenset({
    "preflight", "history", "pc_read", "pc_write", "pc_sync", "encounter",
})
_FAILURE_REASONS = frozenset({
    "invalid_input", "invalid_ledger", "invalid_narration", "history_cleanup_failed",
    "path_resolution_failed", "pc_read_failed", "write_failed", "manager_sync_failed",
    "encounter_projection_invalid",
})


class EnemyBatchApplyError(RuntimeError):
    """Bounded failure raised when a batch application stage cannot complete."""

    def __init__(self, stage: str, reason_code: str):
        self.stage = stage if stage in _FAILURE_STAGES else "preflight"
        self.reason_code = reason_code if reason_code in _FAILURE_REASONS else "invalid_input"
        super().__init__(
            "enemy_batch_apply_failed:stage=%s:reason=%s"
            % (self.stage, self.reason_code)
        )


@dataclass(frozen=True)
class EnemyBatchApplyResult:
    """Committed in-memory projections and the physical write count."""

    conversation_history: list
    encounter_projection: dict
    applied_id: str
    changed_pc_names: tuple[str, ...]
    write_count: int
    exit_completed: bool = False


@dataclass(frozen=True)
class _PcFinalState:
    name: str
    hit_points: int
    status: str


@dataclass(frozen=True)
class _EnemyFinalState:
    name: str
    hit_points: int
    status: str


def is_deterministic_enemy_resolution_enabled() -> bool:
    """Read the rollback flag without creating an enabled-by-default fallback."""
    return getattr(model_config, "DETERMINISTIC_ENEMY_RESOLUTION_ENABLED", False) is True


def is_combat_tactical_brain_enabled() -> bool:
    """Require both default-off rollout gates for synchronous commander plans."""
    return (
        is_deterministic_enemy_resolution_enabled()
        and getattr(model_config, "COMBAT_TACTICAL_BRAIN_ENABLED", False) is True
    )


def is_combat_tactical_prefetch_enabled() -> bool:
    """Require resolver, tactical-brain, and independent prefetch rollout gates."""
    return (
        is_combat_tactical_brain_enabled()
        and getattr(model_config, "COMBAT_TACTICAL_PREFETCH_ENABLED", False) is True
    )


def is_ally_controller_enabled() -> bool:
    """Require deterministic enemy resolution and explicit ally-controller opt-in."""
    return (
        is_deterministic_enemy_resolution_enabled()
        and getattr(model_config, "COMBAT_ALLY_CONTROLLER_ENABLED", False) is True
    )


def is_ally_prefetch_enabled() -> bool:
    """Require the ally controller and explicit ally-prefetch opt-in."""
    return (
        is_ally_controller_enabled()
        and getattr(model_config, "COMBAT_ALLY_PREFETCH_ENABLED", False) is True
    )


def _canonical_name(value: Any) -> str:
    return " ".join(value.split()).casefold() if isinstance(value, str) else ""


def _collect_pc_final_states(ledger: EnemyResolutionLedger) -> list[_PcFinalState]:
    states: dict[str, _PcFinalState] = {}
    for entry in ledger.entries:
        if entry.target.kind != "player":
            continue
        key = _canonical_name(entry.target.name)
        if not key or not isinstance(entry.target_hp_before, int) or isinstance(entry.target_hp_before, bool):
            raise EnemyBatchApplyError("preflight", "invalid_ledger")
        if not isinstance(entry.target_hp_after, int) or isinstance(entry.target_hp_after, bool):
            raise EnemyBatchApplyError("preflight", "invalid_ledger")
        if not isinstance(entry.target_status_after, str) or not entry.target_status_after.strip():
            raise EnemyBatchApplyError("preflight", "invalid_ledger")

        previous = states.get(key)
        if previous is not None and previous.hit_points != entry.target_hp_before:
            raise EnemyBatchApplyError("preflight", "invalid_ledger")
        states[key] = _PcFinalState(
            name=previous.name if previous is not None else entry.target.name,
            hit_points=entry.target_hp_after,
            status=entry.target_status_after.strip(),
        )
    return list(states.values())


def _collect_enemy_final_states(
    ledger: EnemyResolutionLedger,
) -> list[_EnemyFinalState]:
    states: dict[str, _EnemyFinalState] = {}
    for entry in ledger.entries:
        if entry.target.kind != "enemy":
            continue
        key = _canonical_name(entry.target.name)
        if (
            not key
            or not isinstance(entry.target_hp_before, int)
            or isinstance(entry.target_hp_before, bool)
            or entry.target_hp_before < 0
            or not isinstance(entry.target_hp_after, int)
            or isinstance(entry.target_hp_after, bool)
            or entry.target_hp_after < 0
            or not isinstance(entry.target_status_after, str)
            or not entry.target_status_after.strip()
        ):
            raise EnemyBatchApplyError("preflight", "invalid_ledger")
        previous = states.get(key)
        if previous is not None and previous.hit_points != entry.target_hp_before:
            raise EnemyBatchApplyError("preflight", "invalid_ledger")
        states[key] = _EnemyFinalState(
            name=previous.name if previous is not None else entry.target.name,
            hit_points=entry.target_hp_after,
            status=entry.target_status_after.strip(),
        )
    return list(states.values())


def _build_encounter_projection(
    ledger: EnemyResolutionLedger,
    encounter_projection: Any,
    pc_states: list[_PcFinalState],
) -> dict:
    if not isinstance(encounter_projection, Mapping):
        raise EnemyBatchApplyError("preflight", "encounter_projection_invalid")
    projection = copy.deepcopy(dict(encounter_projection))
    projection_id = projection.get("encounterId", projection.get("id"))
    if projection_id is not None and str(projection_id) != ledger.encounter_id:
        raise EnemyBatchApplyError("preflight", "encounter_projection_invalid")
    creatures = projection.get("creatures")
    if not isinstance(creatures, list):
        raise EnemyBatchApplyError("preflight", "encounter_projection_invalid")
    if not isinstance(ledger.departures, tuple):
        raise EnemyBatchApplyError("preflight", "invalid_ledger")
    if (
        not isinstance(ledger.cover_updates, tuple)
        or len(ledger.cover_updates) > 32
    ):
        raise EnemyBatchApplyError("preflight", "invalid_ledger")

    for pc in pc_states:
        matches = [
            creature for creature in creatures
            if isinstance(creature, dict)
            and str(creature.get("type", "")).strip().lower() in {"player", "pc"}
            and _canonical_name(creature.get("name")) == _canonical_name(pc.name)
        ]
        if len(matches) != 1:
            raise EnemyBatchApplyError("preflight", "encounter_projection_invalid")
        matches[0]["currentHitPoints"] = pc.hit_points
        matches[0]["status"] = pc.status

    for enemy in _collect_enemy_final_states(ledger):
        matches = [
            creature for creature in creatures
            if isinstance(creature, dict)
            and str(creature.get("type", "")).strip().casefold() == "enemy"
            and _canonical_name(creature.get("name")) == _canonical_name(enemy.name)
        ]
        if len(matches) != 1:
            raise EnemyBatchApplyError("preflight", "encounter_projection_invalid")
        matches[0]["currentHitPoints"] = enemy.hit_points
        matches[0]["status"] = enemy.status

    departure_keys = set()
    for departure in ledger.departures:
        if (
            not isinstance(departure, EnemyDeparture)
            or not isinstance(departure.enemy, CombatantIdentity)
            or departure.enemy.kind != "enemy"
            or departure.reason not in {"fled", "surrendered"}
        ):
            raise EnemyBatchApplyError("preflight", "invalid_ledger")
        key = _canonical_name(departure.enemy.name)
        if not key or key in departure_keys:
            raise EnemyBatchApplyError("preflight", "invalid_ledger")
        departure_keys.add(key)
        matches = [
            creature for creature in creatures
            if isinstance(creature, dict)
            and str(creature.get("type", "")).strip().casefold() == "enemy"
            and _canonical_name(creature.get("name")) == key
        ]
        if len(matches) != 1:
            raise EnemyBatchApplyError("preflight", "invalid_ledger")
        creature = matches[0]
        status = str(creature.get("status", "alive")).strip().casefold()
        hit_points = creature.get("currentHitPoints", 0)
        if (
            status in {"dead", "defeated"}
            or not isinstance(hit_points, int)
            or isinstance(hit_points, bool)
            or hit_points <= 0
        ):
            raise EnemyBatchApplyError("preflight", "invalid_ledger")
        creature["status"] = "defeated"
        creature["defeatReason"] = departure.reason

    cover_update_keys = set()
    for update in ledger.cover_updates:
        if (
            not isinstance(update, EnemyCoverUpdate)
            or not isinstance(update.enemy, CombatantIdentity)
            or not isinstance(update.enemy.kind, str)
            or update.enemy.kind not in {"enemy", "player", "npc"}
        ):
            raise EnemyBatchApplyError("preflight", "invalid_ledger")
        key = (update.enemy.kind, _canonical_name(update.enemy.name))
        if not key[1] or key in cover_update_keys:
            raise EnemyBatchApplyError("preflight", "invalid_ledger")
        cover_update_keys.add(key)
        if (update.feature_id is None) != (update.cover_type is None):
            raise EnemyBatchApplyError("preflight", "invalid_ledger")
        if update.feature_id is not None and (
            not isinstance(update.feature_id, str)
            or not update.feature_id.strip()
            or len(update.feature_id) > 128
            or not isinstance(update.cover_type, str)
            or update.cover_type not in {"half", "three_quarters"}
        ):
            raise EnemyBatchApplyError("preflight", "invalid_ledger")
        matches = [
            creature for creature in creatures
            if isinstance(creature, dict)
            and str(creature.get("type", "")).strip().lower() == update.enemy.kind
            and _canonical_name(creature.get("name")) == key[1]
        ]
        if len(matches) != 1:
            raise EnemyBatchApplyError("preflight", "invalid_ledger")
        creature = matches[0]
        hp = creature.get("currentHitPoints", 0)
        status = str(creature.get("status", "alive")).strip().casefold()
        if (
            update.feature_id is None
            or status in {"dead", "defeated"}
            or isinstance(hp, bool)
            or not isinstance(hp, int)
            or hp <= 0
        ):
            creature.pop("coverFeatureId", None)
            creature.pop("coverType", None)
        else:
            creature["coverFeatureId"] = update.feature_id
            creature["coverType"] = update.cover_type

    for creature in creatures:
        if not isinstance(creature, dict):
            continue
        hp = creature.get("currentHitPoints", 0)
        status = str(creature.get("status", "alive")).strip().casefold()
        if (
            status in {"dead", "defeated"}
            or isinstance(hp, bool)
            or not isinstance(hp, int)
            or hp <= 0
        ):
            creature.pop("coverFeatureId", None)
            creature.pop("coverType", None)
    return projection


def project_combat_resolution_ledger(
    ledger: EnemyResolutionLedger,
    encounter_projection: Mapping[str, Any],
) -> dict:
    """Build a non-durable encounter snapshot for initiative-ordered staging."""
    if not isinstance(ledger, EnemyResolutionLedger):
        raise EnemyBatchApplyError("preflight", "invalid_ledger")
    pc_states = _collect_pc_final_states(ledger)
    return _build_encounter_projection(ledger, encounter_projection, pc_states)


def _prepare_history(
    conversation_history: Any,
    user_input_text: Any,
    turn_id: Any,
    narration: NarrationResult,
    clean_old_dm_notes: Optional[Callable[[list], Any]],
    clean_combat_state_blocks: Optional[Callable[[list], Any]],
    xp_narrative: Optional[str] = None,
) -> list:
    if not isinstance(conversation_history, list) or not isinstance(user_input_text, str):
        raise EnemyBatchApplyError("preflight", "invalid_input")
    try:
        history = copy.deepcopy(conversation_history)
        for cleaner in (clean_old_dm_notes, clean_combat_state_blocks):
            if cleaner is None:
                continue
            cleaned = cleaner(history)
            if cleaned is not None:
                history = cleaned
            if not isinstance(history, list):
                raise TypeError("history cleaner must preserve a list")
        history.append(build_accepted_input_record(user_input_text, turn_id=turn_id))
        history.append({"role": "assistant", "content": narration.text})
        if xp_narrative is not None:
            history.append({
                "role": "user",
                "content": "XP Awarded: %s" % xp_narrative,
            })
        return history
    except EnemyBatchApplyError:
        raise
    except Exception:
        raise EnemyBatchApplyError("preflight", "history_cleanup_failed") from None


def _xp_participant_names(party_tracker: Mapping[str, Any]) -> list[str]:
    players = party_tracker.get("partyMembers")
    npcs = party_tracker.get("partyNPCs")
    if not isinstance(players, list) or not isinstance(npcs, list):
        raise EnemyBatchApplyError("preflight", "invalid_input")
    names = []
    seen = set()
    for participant in list(players) + list(npcs):
        name = participant.get("name") if isinstance(participant, Mapping) else participant
        if not isinstance(name, str) or not name.strip():
            raise EnemyBatchApplyError("preflight", "invalid_input")
        key = _canonical_name(name)
        if key not in seen:
            seen.add(key)
            names.append(name)
    return names


def _atomic_write(
    write_json: Callable[[str, Any], Any],
    path: str,
    payload: Any,
    stage: str,
) -> None:
    try:
        succeeded = write_json(path, payload)
    except Exception:
        raise EnemyBatchApplyError(stage, "write_failed") from None
    if not succeeded:
        raise EnemyBatchApplyError(stage, "write_failed")


def _trace_batch_write(ledger: EnemyResolutionLedger, target_kind: str, path: str) -> None:
    """Observe a successful physical write without affecting persistence."""
    try:
        if not combat_latency_trace.trace_enabled():
            return
        trace_batch_id = combat_latency_trace.build_work_unit_trace_context(
            ledger.round_number, "ENEMY_PHASE", None
        ).get("batch_id")
        if trace_batch_id is not None:
            combat_latency_trace.trace_batch_file_write(
                trace_batch_id,
                target_kind,
                path,
            )
    except Exception:
        pass


def _trace_apply_result(ledger: EnemyResolutionLedger, **fields: Any) -> None:
    """Emit one legacy-shaped apply observation without affecting persistence."""
    try:
        if not combat_latency_trace.trace_enabled():
            return
        batch_id = combat_latency_trace.build_work_unit_trace_context(
            ledger.round_number, "ENEMY_PHASE", None
        ).get("batch_id")
        if batch_id:
            fields.setdefault("batch_id", batch_id)
        fields.setdefault("source", "deterministic_enemy_batch")
        combat_latency_trace.trace_combat_observation("combat_apply_result", **fields)
    except Exception:
        pass


def _encounter_rows_by_identity(projection: Any) -> dict[tuple[str, str], Mapping[str, Any]]:
    creatures = projection.get("creatures") if isinstance(projection, Mapping) else None
    if not isinstance(creatures, list):
        return {}
    rows: dict[tuple[str, str], Mapping[str, Any]] = {}
    ambiguous = set()
    for creature in creatures:
        if not isinstance(creature, Mapping):
            continue
        kind = creature.get("type")
        name = creature.get("name")
        if not isinstance(kind, str) or not isinstance(name, str) or not name.strip():
            continue
        normalized_kind = kind.strip().casefold()
        if normalized_kind == "pc":
            normalized_kind = "player"
        key = (normalized_kind, _canonical_name(name))
        if key in rows:
            rows.pop(key, None)
            ambiguous.add(key)
        elif key not in ambiguous:
            rows[key] = creature
    return rows


def _trace_tactical_apply_outcomes(
    ledger: EnemyResolutionLedger,
    before: Mapping[str, Any],
    after: Mapping[str, Any],
) -> None:
    """Trace only state changes confirmed in the successfully written projection."""
    try:
        if not combat_latency_trace.trace_enabled():
            return
        batch_id = combat_latency_trace.build_work_unit_trace_context(
            ledger.round_number, "ENEMY_PHASE", None
        ).get("batch_id")
        if not batch_id:
            return
        before_creatures = before.get("creatures")
        actor_ids = combat_latency_trace.build_run_local_actor_ids(before_creatures)
        before_rows = _encounter_rows_by_identity(before)
        after_rows = _encounter_rows_by_identity(after)

        for departure in ledger.departures:
            if not isinstance(departure, EnemyDeparture):
                continue
            key = (departure.enemy.kind, _canonical_name(departure.enemy.name))
            actor_id = actor_ids.get(key)
            persisted = after_rows.get(key)
            if (
                actor_id is not None
                and departure.reason in {"fled", "surrendered"}
                and isinstance(persisted, Mapping)
                and persisted.get("status") == "defeated"
                and persisted.get("defeatReason") == departure.reason
            ):
                combat_latency_trace.trace_tactical_self_preservation_outcome(
                    batch_id, actor_id, departure.reason
                )

        all_keys = set(before_rows) | set(after_rows)
        for key in all_keys:
            actor_id = actor_ids.get(key)
            previous = before_rows.get(key)
            current = after_rows.get(key)
            if actor_id is None or previous is None or current is None:
                continue
            old_has_cover = "coverFeatureId" in previous or "coverType" in previous
            new_has_cover = "coverFeatureId" in current or "coverType" in current
            old_feature = previous.get("coverFeatureId")
            old_type = previous.get("coverType")
            new_feature = current.get("coverFeatureId")
            new_type = current.get("coverType")
            if (old_feature, old_type) == (new_feature, new_type):
                continue
            if old_has_cover:
                combat_latency_trace.trace_tactical_cover_outcome(
                    batch_id, actor_id, old_feature, old_type, "expired"
                )
            if new_has_cover:
                combat_latency_trace.trace_tactical_cover_outcome(
                    batch_id, actor_id, new_feature, new_type, "applied"
                )
    except Exception:
        # Trace failures are strictly observational and never affect an applied batch.
        pass


def _encounter_hp_operations(before: Mapping[str, Any], after: Mapping[str, Any]) -> list[dict]:
    """Describe only PC HP/status mutations mirrored into the encounter write."""
    before_rows = before.get("creatures")
    after_rows = after.get("creatures")
    if not isinstance(before_rows, list) or not isinstance(after_rows, list):
        return []
    before_by_name = {
        _canonical_name(row.get("name")): row
        for row in before_rows
        if isinstance(row, Mapping) and str(row.get("type", "")).casefold() in {"player", "pc"}
    }
    operations = []
    for row in after_rows:
        if not isinstance(row, Mapping) or str(row.get("type", "")).casefold() not in {"player", "pc"}:
            continue
        name = row.get("name")
        previous = before_by_name.get(_canonical_name(name))
        if previous is None or not isinstance(name, str):
            continue
        old_hp, new_hp = previous.get("currentHitPoints"), row.get("currentHitPoints")
        if (isinstance(old_hp, int) and not isinstance(old_hp, bool)
                and isinstance(new_hp, int) and not isinstance(new_hp, bool)
                and new_hp != old_hp):
            operations.append({"op": "hp_delta", "creature": name, "delta": new_hp - old_hp})
        old_status, new_status = previous.get("status"), row.get("status")
        if isinstance(new_status, str) and new_status != old_status:
            operations.append({"op": "set_status", "creature": name, "status": new_status})
    return operations


def apply_enemy_batch(
    ledger: EnemyResolutionLedger,
    narration: NarrationResult,
    *,
    user_input_text: str,
    turn_id: str,
    conversation_history: list,
    conversation_history_file: str,
    encounter_projection: Mapping[str, Any],
    path_manager: Any,
    multi_pc_manager: Any = None,
    clean_old_dm_notes: Optional[Callable[[list], Any]] = None,
    clean_combat_state_blocks: Optional[Callable[[list], Any]] = None,
    read_json: Callable[[str], Any] = safe_json_load,
    write_json: Callable[[str, Any], Any] = safe_write_json,
    party_tracker_data: Optional[Mapping[str, Any]] = None,
    calculate_xp_for_encounter: Optional[Callable[[Mapping[str, Any], Mapping[str, Any]], Any]] = None,
    check_all_monsters_defeated: Optional[Callable[[Mapping[str, Any]], bool]] = None,
    validate_character: Optional[Callable[[str, Mapping[str, Any]], Any]] = None,
    ally_directive_actors: Optional[Sequence[Any]] = None,
) -> EnemyBatchApplyResult:
    """Persist history once, marked characters once each, then the encounter receipt.

    ``encounter_projection`` is the caller's already-computed in-memory
    lifecycle projection. This function only reconciles ledger HP/status and
    does not calculate phases, rounds, initiative, or opening markers.
    """
    if not isinstance(ledger, EnemyResolutionLedger):
        raise EnemyBatchApplyError("preflight", "invalid_ledger")
    if (not isinstance(narration, NarrationResult) or narration.source not in {"llm", "template"}
            or not isinstance(narration.text, str) or not narration.text.strip()):
        raise EnemyBatchApplyError("preflight", "invalid_narration")
    if (not isinstance(user_input_text, str) or not isinstance(turn_id, str)
            or not conversation_history_file
            or path_manager is None or not callable(read_json) or not callable(write_json)):
        raise EnemyBatchApplyError("preflight", "invalid_input")

    try:
        applied_id = compute_applied_id(ledger.encounter_id, turn_id)
    except Exception:
        raise EnemyBatchApplyError("preflight", "invalid_input") from None

    pc_final_states = _collect_pc_final_states(ledger)
    final_encounter = _build_encounter_projection(
        ledger, encounter_projection, pc_final_states
    )

    try:
        history_path = str(conversation_history_file)
        encounter_path = str(path_manager.get_encounter_path_from_id(ledger.encounter_id))
        pc_paths = {
            _canonical_name(pc.name): str(path_manager.get_character_path(pc.name))
            for pc in pc_final_states
        }
        if not history_path or not encounter_path or any(not path for path in pc_paths.values()):
            raise ValueError("empty persistence path")
    except Exception:
        raise EnemyBatchApplyError("preflight", "path_resolution_failed") from None

    terminal_batch = False
    xp_narrative = None
    xp_awarded = 0
    if callable(check_all_monsters_defeated) and check_all_monsters_defeated(final_encounter):
        terminal_batch = callable(calculate_xp_for_encounter) and isinstance(
            party_tracker_data, Mapping
        )
        if terminal_batch:
            try:
                xp_narrative, xp_awarded = calculate_xp_for_encounter(
                    final_encounter, party_tracker_data
                )
                if (
                    not isinstance(xp_narrative, str)
                    or not isinstance(xp_awarded, int)
                    or isinstance(xp_awarded, bool)
                    or xp_awarded < 0
                ):
                    raise ValueError("invalid XP projection")
            except Exception:
                raise EnemyBatchApplyError("preflight", "invalid_input") from None

    reward_names = []
    if terminal_batch and xp_awarded > 0:
        try:
            reward_names = _xp_participant_names(party_tracker_data)
        except EnemyBatchApplyError:
            raise

    pc_before_payloads: dict[str, dict] = {}
    pc_changed_keys = set()
    for pc in pc_final_states:
        key = _canonical_name(pc.name)
        try:
            current = read_json(pc_paths[key])
        except Exception:
            raise EnemyBatchApplyError("pc_read", "pc_read_failed") from None
        if not isinstance(current, Mapping):
            raise EnemyBatchApplyError("pc_read", "pc_read_failed")
        current_payload = copy.deepcopy(dict(current))
        pc_before_payloads[key] = copy.deepcopy(current_payload)
        current_hit_points = current_payload.get("hitPoints")
        current_status = current_payload.get("status")
        already_final = (
            isinstance(current_hit_points, int)
            and not isinstance(current_hit_points, bool)
            and current_hit_points == pc.hit_points
            and isinstance(current_status, str)
            and current_status.strip().casefold() == pc.status.casefold()
        )
        try:
            marker_matches = read_character_applied_id(current_payload) == applied_id
        except Exception:
            raise EnemyBatchApplyError("pc_read", "pc_read_failed") from None
        if marker_matches and not already_final:
            raise EnemyBatchApplyError("pc_read", "pc_read_failed")
        if not already_final:
            pc_changed_keys.add(key)

    character_specs: dict[str, tuple[str, str, Optional[_PcFinalState], int]] = {}
    for pc in pc_final_states:
        key = _canonical_name(pc.name)
        if key in pc_changed_keys:
            character_specs[key] = (pc.name, pc_paths[key], pc, 0)
    if reward_names:
        try:
            for name in reward_names:
                key = _canonical_name(name)
                previous = character_specs.get(key)
                path = (
                    previous[1]
                    if previous is not None
                    else str(path_manager.get_character_path(name))
                )
                if not path:
                    raise ValueError("empty reward character path")
                character_specs[key] = (
                    previous[0] if previous is not None else name,
                    path,
                    previous[2] if previous is not None else None,
                    xp_awarded,
                )
        except Exception:
            raise EnemyBatchApplyError("preflight", "path_resolution_failed") from None

    if multi_pc_manager is not None and not callable(getattr(multi_pc_manager, "update_pc_hp", None)):
        raise EnemyBatchApplyError("preflight", "invalid_input")
    sync_non_pc = (
        getattr(multi_pc_manager, "sync_non_pc_queue_state", None)
        if multi_pc_manager is not None else None
    )
    if ledger.departures and multi_pc_manager is not None and not callable(sync_non_pc):
        raise EnemyBatchApplyError("preflight", "invalid_input")

    history_payload = _prepare_history(
        conversation_history,
        user_input_text,
        turn_id,
        narration,
        clean_old_dm_notes,
        clean_combat_state_blocks,
        xp_narrative if terminal_batch else None,
    )
    if ally_directive_actors:
        try:
            history_payload = mark_ally_directives_consumed(
                history_payload,
                ally_directive_actors,
                applied_id,
            )
        except Exception:
            raise EnemyBatchApplyError("preflight", "invalid_input") from None
    encounter_ops = _encounter_hp_operations(encounter_projection, final_encounter)
    staged_rewards = [
        {
            "character_name": name,
            "experience_points_delta": award,
        }
        for name, _path, _pc_state, award in character_specs.values()
        if award > 0
    ]

    effects = []
    for key, (name, path, pc_state, award) in character_specs.items():
        def stage(current, hp_state=pc_state, xp_delta=award):
            updated = copy.deepcopy(dict(current))
            if hp_state is not None:
                updated["hitPoints"] = hp_state.hit_points
                updated["status"] = hp_state.status
            if xp_delta:
                current_xp = updated.get("experience_points", 0)
                if (
                    not isinstance(current_xp, int)
                    or isinstance(current_xp, bool)
                    or current_xp < 0
                ):
                    raise ValueError("invalid current experience_points")
                updated["experience_points"] = current_xp + xp_delta
            return updated

        effects.append(TurnCharacterEffect(name, path, stage))

    history_written = False

    def persist_history(manifest):
        nonlocal history_written
        history_payload_with_manifest = history_with_combat_turn_manifest(
            history_payload, turn_id, manifest
        )
        _atomic_write(
            write_json, history_path, history_payload_with_manifest, "history"
        )
        _trace_batch_write(ledger, "history", history_path)
        history_payload[:] = history_payload_with_manifest
        conversation_history[:] = history_payload_with_manifest
        history_written = True
        return True

    try:
        commit_result = commit_combat_turn(
            ledger.encounter_id,
            turn_id,
            encounter_path,
            final_encounter,
            effects,
            read_json=read_json,
            write_json=write_json,
            validate_character=validate_character,
            manifest_details={
                "path": "enemy_batch",
                "staged_rewards": staged_rewards,
                "success_narration": narration.text,
            },
            manifest_writer=persist_history,
            character_write_observer=lambda _name, path: _trace_batch_write(
                ledger, "character", path
            ),
            encounter_write_observer=lambda path: _trace_batch_write(
                ledger, "encounter", path
            ),
        )
    except TurnCommitError as exc:
        mapped_stage = {
            "character_read": "pc_read",
            "character_write": "pc_write",
            "encounter_write": "encounter",
            "history": "history",
            "manifest": "history",
        }.get(exc.stage, "preflight")
        if exc.stage == "character_write":
            _trace_apply_result(
                ledger,
                domain="character",
                operation="update_character_info_ops",
                target=exc.target or "unknown",
                changes="",
                ops=[],
                applied=False,
                failure="write_failed",
            )
        elif exc.stage == "encounter_write":
            _trace_apply_result(
                ledger,
                domain="encounter",
                operation="update_encounter",
                target=ledger.encounter_id,
                changes="",
                ops=encounter_ops,
                applied=False,
                failure="write_failed",
            )
        raise EnemyBatchApplyError(mapped_stage, "write_failed" if mapped_stage in {
            "pc_write", "encounter", "history"
        } else "invalid_input") from None

    if history_written:
        changed_pc_names = tuple(
            name for name in commit_result.changed_characters
            if _canonical_name(name) in {_canonical_name(pc.name) for pc in pc_final_states}
        )
        for name in commit_result.changed_characters:
            old_payload = pc_before_payloads.get(_canonical_name(name), {})
            new_payload = commit_result.character_payloads.get(name, {})
            operations = []
            old_hp, new_hp = old_payload.get("hitPoints"), new_payload.get("hitPoints")
            if (isinstance(old_hp, int) and not isinstance(old_hp, bool)
                    and isinstance(new_hp, int) and not isinstance(new_hp, bool)
                    and old_hp != new_hp):
                operations.append({"op": "hp_delta", "delta": new_hp - old_hp})
            old_status, new_status = old_payload.get("status"), new_payload.get("status")
            if isinstance(new_status, str) and new_status != old_status:
                operations.append({"op": "set_status", "status": new_status})
            _trace_apply_result(
                ledger,
                domain="character",
                operation="update_character_info_ops",
                target=name,
                changes="",
                ops=operations,
                applied=True,
                failure=None,
            )
    else:
        changed_pc_names = ()

    final_encounter = commit_result.encounter_data
    _trace_tactical_apply_outcomes(ledger, encounter_projection, final_encounter)
    try:
        if combat_latency_trace.trace_enabled():
            _trace_apply_result(
                ledger,
                **_encounter_apply_trace_fields(
                    ledger, encounter_projection, final_encounter, encounter_ops
                ),
            )
    except Exception:
        pass
    if isinstance(encounter_projection, dict):
        encounter_projection.clear()
        encounter_projection.update(final_encounter)

    return EnemyBatchApplyResult(
        conversation_history=conversation_history,
        encounter_projection=dict(final_encounter),
        applied_id=commit_result.applied_id,
        changed_pc_names=tuple(changed_pc_names),
        write_count=(1 + commit_result.write_count) if history_written else 0,
        exit_completed=terminal_batch,
    )


def _encounter_apply_trace_fields(
    ledger: EnemyResolutionLedger,
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    operations: list[dict],
) -> dict[str, Any]:
    """Build the established encounter apply-result fields with bounded HP state."""
    before_projection = _bounded_encounter_hp_projection(dict(before), "preloaded_context")
    after_projection = _bounded_encounter_hp_projection(dict(after), "returned_persisted_state")
    returned_state = {
        "encounterId": after.get("encounterId", after.get("id")),
        "combat_round": after.get("combat_round", after.get("current_round")),
        "creatures": [
            {"name": row.get("name"), "currentHitPoints": row.get("currentHitPoints")}
            for row in after.get("creatures", [])[:12]
            if isinstance(row, Mapping)
        ] if isinstance(after.get("creatures"), list) else [],
    }
    return {
        "domain": "encounter",
        "operation": "update_encounter",
        "target": ledger.encounter_id,
        "changes": "",
        "ops": operations,
        "applied": True,
        "returned_state": returned_state,
        "hp_before": before_projection.get("hp_rows", "[]"),
        "hp_before_status": before_projection.get("hp_status", "incomplete"),
        "hp_before_count": before_projection.get("hp_count", 0),
        "hp_before_truncated": before_projection.get("hp_truncated", False),
        "hp_before_source": before_projection.get("hp_source", "preloaded_context"),
        "hp_after": after_projection.get("hp_rows", "[]"),
        "hp_after_status": after_projection.get("hp_status"),
        "hp_after_count": after_projection.get("hp_count"),
        "hp_after_truncated": after_projection.get("hp_truncated"),
        "hp_after_source": after_projection.get("hp_source"),
        "failure": None,
    }
