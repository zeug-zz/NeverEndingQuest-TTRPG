# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Combat Bootstrap - Startup state and narrative preparation.
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

This software is free for non-commercial and educational use.
Commercial competing use is prohibited for 2 years from release.
See LICENSE file for full terms.
"""

from __future__ import annotations

import json
import copy
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple
from core.combat.debug_dumps import combat_debug_dumps_enabled
# TABLETOP MODE: Keep persisted turn identity out of startup provider messages.
from core.combat.turn_commit import (
    COMBAT_TURN_COMMIT_MANIFEST_KEY,
    CombatTurnManifestError,
    _validate_committed_character,
    build_turn_receipt,
    conversation_history_for_prompt,
    read_character_applied_id,
    read_turn_receipts,
    validate_combat_turn_commit_manifest,
    with_turn_receipt,
)



@dataclass(frozen=True)
class CombatHistoryDependencies:
    """Explicit legacy operations used while preparing fresh/resumed history."""

    exists: Callable[[str], bool]
    getsize: Callable[[str], int]
    load_json: Callable[[str], Any]
    read_prompt: Callable[[str], str]
    save_json: Callable[[str, Any], Any]
    format_character: Callable[..., str]
    format_npc: Callable[[Dict[str, Any], str], str]
    filter_dynamic_fields: Callable[[Any], Any]
    filter_encounter: Callable[[Dict[str, Any]], Dict[str, Any]]
    log_structure: Callable[[List[Dict[str, Any]]], Any]
    debug: Callable[..., Any]
    error: Callable[..., Any]
    emit: Callable[[str], Any]
    remove: Callable[[str], Any]


@dataclass(frozen=True)
class CombatHistoryResult:
    """State returned to the legacy owner after history startup is complete."""

    history: List[Dict[str, Any]]
    is_resuming: bool
    return_early: bool = False
    return_value: Optional[Tuple[Any, Any]] = None


@dataclass(frozen=True)
class CombatInitializationInputs:
    """Arguments entering the pre-history, pre-narration startup boundary."""

    encounter_id: str
    party_tracker_data: Dict[str, Any]
    location_info: Dict[str, Any]
    session: Any = None


@dataclass(frozen=True)
class CombatInitializationDependencies:
    """Explicit current-owner bindings for startup reads, state, and diagnostics."""

    module_path_manager_factory: Callable[..., Any]
    safe_json_load: Callable[[str], Any]
    session_factory: Callable[..., Any]
    multi_pc_combat_available: bool
    is_multi_pc_enabled: Callable[[], bool]
    normalize_phase1_initiative: Callable[..., Tuple[Any, bool, Any]]
    save_json: Callable[[str, Any], Any]
    get_combat_manager: Callable[[], Any]
    create_combat_manager: Callable[[Dict[str, Any]], Any]
    history_file: str
    second_model_history_file: str
    third_model_history_file: str
    history_dependencies: Any
    normalize_character_name: Callable[[str], str]
    load_npc_with_fuzzy_match: Callable[..., Tuple[Optional[Dict[str, Any]], Any]]
    file_exists: Callable[[str], bool]
    list_directory: Callable[[str], List[str]]
    print_exception: Callable[[], Any]
    emit: Callable[[str], Any]
    debug: Callable[..., Any]
    info: Callable[..., Any]
    warning: Callable[..., Any]
    error: Callable[..., Any]
    write_json: Optional[Callable[[str, Any], Any]] = None
    validate_character: Optional[Callable[[str, Dict[str, Any]], Any]] = None
    publish_narration: Optional[Callable[..., Any]] = None


@dataclass(frozen=True)
class CombatBaseInitialization:
    """Typed result from path/encounter/session normalization and manager setup."""

    json_file_path: str
    path_manager: Any
    disk_party_tracker: Any
    encounter_data: Dict[str, Any]
    session: Any
    multi_pc_manager: Any
    return_early: bool = False
    return_value: Optional[Tuple[Any, Any]] = None


@dataclass(frozen=True)
class CombatTurnRecoveryResult:
    """Committed disk snapshot and bootstrap recovery outcome."""

    encounter_data: Dict[str, Any]
    party_tracker_data: Dict[str, Any]
    recovered: bool = False
    applied_id: Optional[str] = None


class CombatTurnRecoveryError(RuntimeError):
    """Explicit fail-closed error raised by pending turn recovery."""

    def __init__(self, reason: str):
        super().__init__("combat_turn_recovery_failed:%s" % reason)


@dataclass(frozen=True)
class CombatantTemplateInitialization:
    """Loaded player/monster/NPC templates plus the legacy player-file handoff."""

    player_info: Any
    player_file: Optional[str]
    monster_templates: Dict[str, Any]
    npc_templates: Dict[str, Any]
    return_early: bool = False
    return_value: Optional[Tuple[Any, Any]] = None


@dataclass(frozen=True)
class CombatInitializationResult:
    """All startup state handed to the continuing legacy owner explicitly."""

    json_file_path: str
    path_manager: Any
    module_path_manager_factory: Callable[..., Any]
    safe_json_load: Callable[[str], Any]
    disk_party_tracker: Any
    encounter_data: Dict[str, Any]
    session: Any
    multi_pc_manager: Any
    conversation_history: List[Dict[str, Any]]
    history_dependencies: Any
    is_resuming: bool
    is_multipc: Optional[bool]
    player_info: Any
    player_file: Optional[str]
    monster_templates: Dict[str, Any]
    npc_templates: Dict[str, Any]
    return_early: bool = False
    return_value: Optional[Tuple[Any, Any]] = None
    recovered_pending_turn: bool = False


def load_encounter_and_bind_session(
    inputs: CombatInitializationInputs,
    dependencies: CombatInitializationDependencies,
) -> CombatBaseInitialization:
    """Keep disk party/encounter reads, normalization and manager setup in order."""
    disk_party_tracker = {}
    try:
        disk_party_tracker = dependencies.safe_json_load("party_tracker.json")
        current_module = disk_party_tracker.get("module", "").replace(" ", "_") if disk_party_tracker else None
        path_manager = dependencies.module_path_manager_factory(current_module)
    except Exception as exc:
        dependencies.warning(
            f"FILE_OP: Could not resolve combat module from party tracker: {exc}",
            category="file_operations",
        )
        path_manager = dependencies.module_path_manager_factory()

    json_file_path = f"modules/encounters/encounter_{inputs.encounter_id}.json"
    dependencies.emit(f"[COMBAT_MANAGER] Loading encounter file: {json_file_path}")
    try:
        encounter_data = dependencies.safe_json_load(json_file_path)
        if not encounter_data:
            dependencies.emit("[COMBAT_MANAGER] Failed to load encounter file")
            dependencies.error(f"FAILURE: Failed to load encounter file {json_file_path}", category="file_operations")
            return CombatBaseInitialization(
                json_file_path, path_manager, disk_party_tracker, {}, inputs.session, None,
                return_early=True, return_value=(None, None),
            )
        dependencies.emit(
            f"[COMBAT_MANAGER] Encounter loaded: {len(encounter_data.get('creatures', []))} creatures"
        )
    except Exception as exc:
        dependencies.emit(f"[COMBAT_MANAGER] Exception loading encounter: {str(exc)}")
        dependencies.error(
            f"FAILURE: Failed to load encounter file {json_file_path}",
            exception=exc,
            category="file_operations",
        )
        return CombatBaseInitialization(
            json_file_path, path_manager, disk_party_tracker, {}, inputs.session, None,
            return_early=True, return_value=(None, None),
        )

    session = inputs.session
    if session is None:
        session = dependencies.session_factory(
            encounter=encounter_data,
            active_pc=inputs.party_tracker_data.get("active_character"),
            encounter_id=str(inputs.encounter_id),
        )
    session.bind_encounter(encounter_data)

    if dependencies.multi_pc_combat_available and dependencies.is_multi_pc_enabled():
        encounter_data, encounter_changed, mirror_payload = dependencies.normalize_phase1_initiative(
            encounter_data, disk_party_tracker
        )
        session.bind_encounter(encounter_data)
        if encounter_changed:
            dependencies.save_json(json_file_path, encounter_data)
            dependencies.debug("STATE_SYNC: Normalized Phase 1 initiative state", category="combat_events")
        if mirror_payload:
            disk_party_tracker.setdefault("worldConditions", {})["combatInitiative"] = mirror_payload
            inputs.party_tracker_data.setdefault("worldConditions", {})["combatInitiative"] = mirror_payload
            dependencies.save_json("party_tracker.json", disk_party_tracker)
            dependencies.debug("STATE_SYNC: Updated party tracker combatInitiative mirror", category="combat_events")

    multi_pc_manager = session.multi_pc_manager
    if dependencies.multi_pc_combat_available and dependencies.is_multi_pc_enabled():
        multi_pc_manager = multi_pc_manager or dependencies.get_combat_manager()
        if not multi_pc_manager:
            dependencies.debug("[COMBAT_MANAGER] Re-initializing MultiPCCombatManager", category="combat_events")
            multi_pc_manager = dependencies.create_combat_manager(inputs.party_tracker_data)
        session.multi_pc_manager = multi_pc_manager
        if multi_pc_manager:
            multi_pc_manager.initialize_turn_queue(encounter_data)
            phase = multi_pc_manager.sync_committed_turn_state(encounter_data)
            session.set_phase(phase)
            dependencies.info(
                "STATE_SYNC: Combat phase/round synchronized from committed encounter snapshot",
                category="combat_events",
            )
        else:
            persisted_phase = encounter_data.get("combat_phase", session.phase)
            if persisted_phase in ("PC_PHASE", "ENEMY_PHASE"):
                session.set_phase(persisted_phase)
    return CombatBaseInitialization(
        json_file_path=json_file_path,
        path_manager=path_manager,
        disk_party_tracker=disk_party_tracker,
        encounter_data=encounter_data,
        session=session,
        multi_pc_manager=multi_pc_manager,
    )


def load_combatant_templates(
    *,
    encounter_data: Dict[str, Any],
    path_manager: Any,
    dependencies: CombatInitializationDependencies,
) -> CombatantTemplateInitialization:
    """Load active PC, unique monster types, and fuzzy-matched NPC templates."""
    player_info = None
    player_file = None
    monster_templates = {}
    npc_templates = {}
    for creature in encounter_data["creatures"]:
        if creature["type"] == "player":
            player_name = dependencies.normalize_character_name(creature["name"])
            player_file = path_manager.get_character_path(player_name)
            dependencies.emit(f"[COMBAT_MANAGER] Loading player: {creature['name']} from {player_file}")
            try:
                player_info = dependencies.safe_json_load(player_file)
                if not player_info:
                    dependencies.emit("[COMBAT_MANAGER] Failed to load player file")
                    dependencies.error(f"FAILURE: Failed to load player file: {player_file}", category="file_operations")
                    return CombatantTemplateInitialization(
                        player_info, player_file, monster_templates, npc_templates,
                        return_early=True, return_value=(None, None),
                    )
                dependencies.emit("[COMBAT_MANAGER] Player loaded successfully")
            except Exception as exc:
                dependencies.emit(f"[COMBAT_MANAGER] Exception loading player: {str(exc)}")
                dependencies.error(
                    f"FAILURE: Failed to load player file {player_file}",
                    exception=exc,
                    category="file_operations",
                )
                return CombatantTemplateInitialization(
                    player_info, player_file, monster_templates, npc_templates,
                    return_early=True, return_value=(None, None),
                )
        elif creature["type"] == "enemy":
            monster_type = creature["monsterType"]
            if monster_type not in monster_templates:
                monster_file = path_manager.get_monster_path(monster_type)
                dependencies.emit(f"[COMBAT_MANAGER] Loading monster: {creature['name']} (type: {monster_type})")
                dependencies.debug(f"FILE_OP: Attempting to load monster file: {monster_file}", category="file_operations")
                try:
                    monster_data = dependencies.safe_json_load(monster_file)
                    if monster_data:
                        monster_templates[monster_type] = monster_data
                        dependencies.emit(f"[COMBAT_MANAGER] Monster loaded successfully: {monster_type}")
                        dependencies.debug(f"SUCCESS: Successfully loaded monster: {monster_type}", category="file_operations")
                    else:
                        dependencies.emit("[COMBAT_MANAGER] Failed to load monster file")
                        dependencies.error(f"FILE_OP: Failed to load monster file: {monster_file}", category="file_operations")
                except FileNotFoundError as exc:
                    dependencies.error(f"FAILURE: Monster file not found: {monster_file}", category="file_operations")
                    dependencies.error(f"FAILURE: {str(exc)}", category="file_operations")
                    monster_dir = f"{path_manager.module_dir}/monsters"
                    if dependencies.file_exists(monster_dir):
                        dependencies.debug(f"FILE_OP: Available monster files in {monster_dir}:", category="file_operations")
                        for filename in dependencies.list_directory(monster_dir):
                            dependencies.debug(f"  - {filename}", category="combat_validation")
                    return CombatantTemplateInitialization(
                        player_info, player_file, monster_templates, npc_templates,
                        return_early=True, return_value=(None, None),
                    )
                except json.JSONDecodeError as exc:
                    dependencies.error(
                        f"FAILURE: Invalid JSON in monster file {monster_file}",
                        exception=exc,
                        category="file_operations",
                    )
                    return CombatantTemplateInitialization(
                        player_info, player_file, monster_templates, npc_templates,
                        return_early=True, return_value=(None, None),
                    )
                except Exception as exc:
                    dependencies.error(
                        f"FAILURE: Failed to load monster file {monster_file}",
                        exception=exc,
                        category="file_operations",
                    )
                    dependencies.error(f"FAILURE: Exception type: {type(exc).__name__}", category="file_operations")
                    dependencies.print_exception()
                    return CombatantTemplateInitialization(
                        player_info, player_file, monster_templates, npc_templates,
                        return_early=True, return_value=(None, None),
                    )
        elif creature["type"] == "npc":
            npc_data, matched_filename = dependencies.load_npc_with_fuzzy_match(creature["name"], path_manager)
            if npc_data and matched_filename:
                if matched_filename not in npc_templates:
                    npc_templates[matched_filename] = npc_data
            else:
                dependencies.error(f"FAILURE: Failed to load NPC file for: {creature['name']}", category="file_operations")
    return CombatantTemplateInitialization(player_info, player_file, monster_templates, npc_templates)


def initialize_combat_session(
    inputs: CombatInitializationInputs,
    dependencies: CombatInitializationDependencies,
) -> CombatInitializationResult:
    """Perform the ordered pre-history combat bootstrap and typed handoff."""
    base = load_encounter_and_bind_session(inputs, dependencies)
    if base.return_early:
        return CombatInitializationResult(
            json_file_path=base.json_file_path,
            path_manager=base.path_manager,
            module_path_manager_factory=dependencies.module_path_manager_factory,
            safe_json_load=dependencies.safe_json_load,
            disk_party_tracker=base.disk_party_tracker,
            encounter_data=base.encounter_data,
            session=base.session,
            multi_pc_manager=base.multi_pc_manager,
            conversation_history=[],
            history_dependencies=dependencies.history_dependencies,
            is_resuming=False,
            is_multipc=None,
            player_info=None,
            player_file=None,
            monster_templates={},
            npc_templates={},
            return_early=True, return_value=base.return_value,
        )

    history_selection = select_combat_history(
        encounter_id=inputs.encounter_id,
        history_file=dependencies.history_file,
        dependencies=dependencies.history_dependencies,
    )
    conversation_history = history_selection.history
    is_resuming = history_selection.is_resuming
    encounter_data = base.encounter_data
    disk_party_tracker = base.disk_party_tracker
    recovered_pending_turn = False
    if is_resuming:
        recovery = recover_pending_combat_turn(
            encounter_id=inputs.encounter_id,
            encounter_path=base.json_file_path,
            history=conversation_history,
            path_manager=base.path_manager,
            encounter_data=encounter_data,
            party_tracker_data=disk_party_tracker,
            session=base.session,
            multi_pc_manager=base.multi_pc_manager,
            dependencies=dependencies,
        )
        encounter_data = recovery.encounter_data
        disk_party_tracker = recovery.party_tracker_data
        recovered_pending_turn = recovery.recovered
    is_multipc = None
    if not is_resuming:
        is_multipc = dependencies.multi_pc_combat_available and dependencies.is_multi_pc_enabled()
        conversation_history = build_fresh_combat_history(
            encounter_id=inputs.encounter_id,
            encounter_data=encounter_data,
            party_tracker_data=inputs.party_tracker_data,
            multi_pc=is_multipc,
            dependencies=dependencies.history_dependencies,
        )

    base.session.bind_history(conversation_history)
    base.session.active_pc = inputs.party_tracker_data.get("active_character") or base.session.active_pc
    dependencies.save_json(dependencies.second_model_history_file, [])
    dependencies.save_json(dependencies.third_model_history_file, [])
    templates = load_combatant_templates(
        encounter_data=encounter_data,
        path_manager=base.path_manager,
        dependencies=dependencies,
    )
    return CombatInitializationResult(
        json_file_path=base.json_file_path,
        path_manager=base.path_manager,
        module_path_manager_factory=dependencies.module_path_manager_factory,
        safe_json_load=dependencies.safe_json_load,
        disk_party_tracker=disk_party_tracker,
        encounter_data=encounter_data,
        session=base.session,
        multi_pc_manager=base.multi_pc_manager,
        conversation_history=conversation_history,
        history_dependencies=dependencies.history_dependencies,
        is_resuming=is_resuming,
        is_multipc=is_multipc,
        player_info=templates.player_info,
        player_file=templates.player_file,
        monster_templates=templates.monster_templates,
        npc_templates=templates.npc_templates,
        return_early=templates.return_early,
        return_value=templates.return_value,
        recovered_pending_turn=recovered_pending_turn,
    )


@dataclass(frozen=True)
class CombatStartupNarrativeInputs:
    """Inputs captured immediately before fresh-scene or resume narration."""

    history: List[Dict[str, Any]]
    history_file: str
    is_resuming: bool
    encounter_data: Dict[str, Any]
    party_tracker_data: Dict[str, Any]
    multi_pc_manager: Any
    dynamic_state: str
    preroll_text: str
    session: Any
    temperature_used: Any = None
    recovered_pending_turn: bool = False


@dataclass(frozen=True)
class CombatStartupNarrativeDependencies:
    """Current owner-bound provider, validation, I/O and output callbacks."""

    client: Any
    resume_config: Callable[[], Tuple[bool, str]]
    combat_main_model: str
    completion_params: Callable[..., Dict[str, Any]]
    get_temperature: Callable[..., Any]
    get_initiative_order: Callable[[Dict[str, Any]], str]
    get_multi_pc_initiative_narrative: Callable[[Any], str]
    modify_prompt_for_multi_pc: Callable[[str, Any, Any], str]
    is_valid_json: Callable[[str], bool]
    validate_response: Callable[..., Any]
    save_json: Callable[[str, Any], Any]
    export_open: Callable[..., Any]
    perf_counter: Callable[[], float]
    trace_stage: Callable[..., Any]
    trace_provider_call: Callable[..., Any]
    usage_tracking_available: bool
    track_usage: Callable[[Any], Any]
    log_api_call: Callable[..., Any]
    emit: Callable[[str], Any]
    flush: Callable[[], Any]
    debug: Callable[..., Any]
    info: Callable[..., Any]
    warning: Callable[..., Any]
    error: Callable[..., Any]
    publish_narration: Callable[..., Any]
    publish_output: Callable[..., Any]
    debug_dumps_enabled: Callable[[], bool] = combat_debug_dumps_enabled
    llm_call: Optional[Callable[..., str]] = None
    receipt_observer_factory: Optional[Callable[..., Any]] = None


@dataclass(frozen=True)
class CombatStartupNarrativeResult:
    """Explicit locals handed back to the continuing combat owner."""

    history: List[Dict[str, Any]]
    is_resuming: bool
    session: Any = None
    is_fast_lane: bool = False
    initiative_order: Optional[str] = None
    initial_prompt_text: Optional[str] = None
    initial_response: Optional[str] = None
    narration: Optional[str] = None
    temperature_used: Any = None
    initial_conversation_length: Optional[int] = None
    retry_feedback_note: Optional[str] = None
    return_early: bool = False
    return_value: Optional[Tuple[Any, Any]] = None


def select_combat_history(
    *,
    encounter_id: str,
    history_file: str,
    dependencies: CombatHistoryDependencies,
) -> CombatHistoryResult:
    """Load history and retain only a history belonging to this encounter."""
    if dependencies.exists(history_file) and dependencies.getsize(history_file) > 100:
        history = dependencies.load_json(history_file)
        history_encounter_id = None
        for message in history[:3]:
            if message.get("role") == "system" and "Current Combat Encounter:" in message.get("content", ""):
                history_encounter_id = message["content"].replace("Current Combat Encounter:", "").strip()
                break
        if history_encounter_id == encounter_id:
            dependencies.emit(f"[COMBAT_MANAGER] Resuming existing combat session for encounter {encounter_id}.")
            return CombatHistoryResult(history=history, is_resuming=True)
        dependencies.emit(
            f"[COMBAT_MANAGER] Found stale history for encounter '{history_encounter_id}', starting fresh for '{encounter_id}'."
        )
        return CombatHistoryResult(history=[], is_resuming=False)
    return CombatHistoryResult(history=[], is_resuming=False)


def recover_pending_combat_turn(
    *,
    encounter_id: str,
    encounter_path: str,
    history: List[Dict[str, Any]],
    path_manager: Any,
    encounter_data: Dict[str, Any],
    party_tracker_data: Dict[str, Any],
    session: Any,
    multi_pc_manager: Any,
    dependencies: CombatInitializationDependencies,
) -> CombatTurnRecoveryResult:
    """Complete the newest unreceipted manifest before normal resume startup."""
    if not isinstance(history, list) or not isinstance(encounter_data, dict):
        raise CombatTurnRecoveryError("invalid_bootstrap_state")
    if not isinstance(encounter_id, str) or not encounter_id.strip():
        raise CombatTurnRecoveryError("invalid_encounter_id")

    try:
        durable_encounter = dependencies.safe_json_load(encounter_path)
        if not isinstance(durable_encounter, dict):
            raise ValueError("encounter_read_failed")
        durable_id = durable_encounter.get("encounterId", durable_encounter.get("id"))
        if durable_id != encounter_id:
            raise ValueError("encounter_identity_mismatch")
        receipts = read_turn_receipts(durable_encounter)
        receipt_ids = {receipt["applied_id"] for receipt in receipts}

        pending_manifest = None
        for message in reversed(history):
            if not isinstance(message, dict) or COMBAT_TURN_COMMIT_MANIFEST_KEY not in message:
                continue
            manifest = validate_combat_turn_commit_manifest(
                message[COMBAT_TURN_COMMIT_MANIFEST_KEY]
            )
            if (
                message.get("role") != "user"
                or message.get("turn_id") != manifest["turn_id"]
                or manifest["encounter_id"] != encounter_id
            ):
                raise CombatTurnManifestError(
                    "combat_turn_manifest_invalid:history_identity"
                )
            if manifest["applied_id"] not in receipt_ids:
                pending_manifest = manifest
                break
    except CombatTurnManifestError as exc:
        raise CombatTurnRecoveryError(str(exc)) from exc
    except Exception as exc:
        raise CombatTurnRecoveryError("manifest_scan") from exc

    if pending_manifest is None:
        return CombatTurnRecoveryResult(
            encounter_data=durable_encounter,
            party_tracker_data=party_tracker_data,
        )

    if not callable(dependencies.write_json):
        raise CombatTurnRecoveryError("write_dependency_unavailable")
    if not callable(dependencies.publish_narration):
        raise CombatTurnRecoveryError("publication_dependency_unavailable")

    applied_id = pending_manifest["applied_id"]
    character_writes = []
    try:
        for effect in pending_manifest["character_effects"]:
            name = effect["character_name"]
            path = path_manager.get_character_path(name)
            if not isinstance(path, str) or not path:
                raise ValueError("character_path_unavailable")
            current = dependencies.safe_json_load(path)
            if not isinstance(current, dict):
                raise ValueError("character_read_failed")
            marker = read_character_applied_id(current)
            if marker == applied_id:
                continue
            payload = copy.deepcopy(effect["payload"])
            _validate_committed_character(
                name, payload, dependencies.validate_character
            )
            character_writes.append((path, payload))

        final_projection = copy.deepcopy(pending_manifest["encounter_projection"])
        if "turn_receipts" in durable_encounter:
            final_projection["turn_receipts"] = copy.deepcopy(
                durable_encounter["turn_receipts"]
            )
        else:
            final_projection.pop("turn_receipts", None)
        read_turn_receipts(final_projection)
        build_turn_receipt(
            encounter_id,
            pending_manifest["turn_id"],
            pending_manifest["receipt"]["combat_round"],
            "2000-01-01T00:00:00.000000Z",
        )
        projection_before_receipt = copy.deepcopy(final_projection)
    except CombatTurnManifestError as exc:
        raise CombatTurnRecoveryError(str(exc)) from exc
    except Exception as exc:
        raise CombatTurnRecoveryError("preflight") from exc

    for path, payload in character_writes:
        try:
            if dependencies.write_json(path, payload) is False:
                raise ValueError("character_write_failed")
        except Exception as exc:
            raise CombatTurnRecoveryError("character_write") from exc

    try:
        receipt = build_turn_receipt(
            encounter_id,
            pending_manifest["turn_id"],
            pending_manifest["receipt"]["combat_round"],
            datetime.now(timezone.utc).isoformat(timespec="microseconds").replace(
                "+00:00", "Z"
            ),
        )
        final_projection = with_turn_receipt(projection_before_receipt, receipt)
        if dependencies.write_json(encounter_path, final_projection) is False:
            raise ValueError("encounter_write_failed")
    except Exception as exc:
        raise CombatTurnRecoveryError("encounter_write") from exc

    from core.combat.turn import sync_committed_combat_turn

    try:
        sync_committed_combat_turn(final_projection, multi_pc_manager, session)
        dependencies.publish_narration(
            pending_manifest["success_narration"]["text"],
            applied_id=applied_id,
        )
    except Exception as exc:
        raise CombatTurnRecoveryError("post_commit") from exc

    return CombatTurnRecoveryResult(
        encounter_data=final_projection,
        party_tracker_data=party_tracker_data,
        recovered=True,
        applied_id=applied_id,
    )


def build_fresh_combat_history(
    *,
    encounter_id: str,
    encounter_data: Dict[str, Any],
    party_tracker_data: Dict[str, Any],
    multi_pc: bool,
    dependencies: CombatHistoryDependencies,
) -> List[Dict[str, Any]]:
    """Build the initial prompt/history header with its original ordering."""
    prompt_file = "combat/combat_sim_prompt.txt"
    if multi_pc:
        prompt_file = "combat/combat_sim_prompt_multipc_compressed.txt"
        dependencies.debug(
            f"[COMBAT_MANAGER] Loading Multi-PC system prompt: {prompt_file}",
            category="combat_events",
        )
    system_prompt = dependencies.read_prompt(prompt_file)
    if multi_pc:
        pc_names = [
            creature.get("name", "Unknown PC")
            for creature in encounter_data.get("creatures", [])
            if creature.get("type") == "player"
        ]
        pc_list_str = ", ".join(pc_names)
        system_prompt = system_prompt.replace("[PC_LIST]", pc_list_str)
        dependencies.debug(
            f"[COMBAT_MANAGER] Replaced Multi-PC placeholders: PC_LIST={pc_list_str}",
            category="combat_events",
        )
    history = [
        {"role": "system", "content": system_prompt},
        {"role": "system", "content": f"Current Combat Encounter: {encounter_id}"},
        {"role": "system", "content": ""},
        {"role": "system", "content": ""},
        {"role": "system", "content": ""},
    ]
    dependencies.emit(
        f"[COMBAT_MANAGER] Starting new combat session (Mode: {'Multi-PC' if 'multipc' in prompt_file else 'Single-PC'})."
    )
    return history


def _initial_head_context(
    *, player_info: Dict[str, Any], multi_pc_manager: Any, dependencies: CombatHistoryDependencies
) -> str:
    if multi_pc_manager:
        return multi_pc_manager.format_multi_pc_head_context()
    formatted_player = dependencies.format_character(player_info, char_type="player")
    return f"Here's the player character data:\n\n{formatted_player}\n"


def _npc_messages(
    npc_templates: Dict[str, Any], party_tracker_data: Dict[str, Any], dependencies: CombatHistoryDependencies
) -> List[Tuple[str, Dict[str, str]]]:
    party_npcs = party_tracker_data.get("partyNPCs", [])
    npc_roles = {npc["name"]: npc.get("role", "Adventurer") for npc in party_npcs}
    messages = []
    for npc_data in npc_templates.values():
        npc_role = npc_roles.get(npc_data.get("name", ""), "Adventurer")
        formatted_data = dependencies.format_npc(npc_data, npc_role)
        messages.append((
            npc_data["name"],
            {"role": "system", "content": f"Here's the NPC data for {npc_data['name']}:\n\n{formatted_data}\n"},
        ))
    return messages


def hydrate_fresh_combat_history(
    *,
    history: List[Dict[str, Any]],
    encounter_id: str,
    encounter_data: Dict[str, Any],
    player_info: Dict[str, Any],
    monster_templates: Dict[str, Any],
    npc_templates: Dict[str, Any],
    party_tracker_data: Dict[str, Any],
    location_info: Dict[str, Any],
    multi_pc_manager: Any,
    history_file: str,
    session: Any,
    dependencies: CombatHistoryDependencies,
) -> bool:
    """Hydrate and persist fresh history at the legacy startup write point."""
    dependencies.emit("[COMBAT_MANAGER] Starting new combat - clearing compression caches")
    for cache_file in (
        "modules/conversation_history/combat_compression_cache.json",
    ):
        if dependencies.exists(cache_file):
            try:
                dependencies.remove(cache_file)
                dependencies.emit(f"[COMBAT_MANAGER] Cleared cache: {cache_file}")
            except Exception as exc:
                dependencies.emit(f"[COMBAT_MANAGER] Warning: Could not clear cache {cache_file}: {exc}")

    head_context = _initial_head_context(
        player_info=player_info, multi_pc_manager=multi_pc_manager, dependencies=dependencies
    )
    location_for_combat = {
        key: value for key, value in location_info.items() if key not in ["adventureSummary", "encounters"]
    }
    session.apply_history_payloads(
        session.history_payloads(
            head_context=head_context,
            monster_templates=monster_templates,
            location=location_for_combat,
            filter_dynamic_fields=dependencies.filter_dynamic_fields,
        )
    )
    if not monster_templates and any(creature["type"] == "enemy" for creature in encounter_data["creatures"]):
        dependencies.error("FAILURE: No monster templates were loaded!", category="file_operations")
        return False

    history.extend(message for _, message in _npc_messages(npc_templates, party_tracker_data, dependencies))
    history.append({
        "role": "system",
        "content": f"Encounter Details:\n{json.dumps(dependencies.filter_encounter(encounter_data), indent=2)}",
    })
    dependencies.log_structure(history)
    dependencies.save_json(history_file, history)
    return True


def refresh_resumed_combat_history(
    *,
    history: List[Dict[str, Any]],
    player_info: Dict[str, Any],
    monster_templates: Dict[str, Any],
    npc_templates: Dict[str, Any],
    party_tracker_data: Dict[str, Any],
    multi_pc_manager: Any,
    history_file: str,
    location_info: Dict[str, Any],
    session: Any,
    dependencies: CombatHistoryDependencies,
) -> None:
    """Refresh known player/NPC payloads while retaining unrelated history."""
    dependencies.emit("[COMBAT_MANAGER] Updating player and NPC templates to new format during resume...")
    resumed_head_context = _initial_head_context(
        player_info=player_info, multi_pc_manager=multi_pc_manager, dependencies=dependencies
    )
    resumed_location = {
        key: value for key, value in location_info.items() if key not in ["adventureSummary", "encounters"]
    }
    session.apply_history_payloads(
        session.history_payloads(
            head_context=resumed_head_context,
            monster_templates=monster_templates,
            location=resumed_location,
            filter_dynamic_fields=dependencies.filter_dynamic_fields,
        )
    )
    for index, message in enumerate(history):
        content = message.get("content", "")
        is_player_data = "Player Character:" in content or "Here's the player character data:" in content
        is_multipc_data = "=== AUTHORITATIVE MULTI-PC STATE (JSON) ===" in content
        if message.get("role") == "system" and (is_player_data or is_multipc_data):
            dependencies.emit(f"[COMBAT_MANAGER] Updating head context at index {index}")
            message["content"] = _initial_head_context(
                player_info=player_info, multi_pc_manager=multi_pc_manager, dependencies=dependencies
            )
            break

    for index in range(len(history) - 1, -1, -1):
        message = history[index]
        if message.get("role") == "system" and "NPC Templates:" in message.get("content", ""):
            dependencies.emit(f"[COMBAT_MANAGER] Removing old NPC Templates at index {index}")
            history.pop(index)
            break
    indices_to_remove = [
        index for index in range(len(history) - 1, -1, -1)
        if history[index].get("role") == "system"
        and "Here's the NPC data for" in history[index].get("content", "")
    ]
    for index in sorted(indices_to_remove, reverse=True):
        dependencies.emit(f"[COMBAT_MANAGER] Removing old NPC message at index {index}")
        history.pop(index)

    insert_index = -1
    for index, message in enumerate(history):
        if message.get("role") == "system" and "Location:" in message.get("content", ""):
            insert_index = index + 1
            break
    if insert_index == -1:
        insert_index = min(5, len(history))
    for npc_name, npc_message in _npc_messages(npc_templates, party_tracker_data, dependencies):
        history.insert(insert_index, npc_message)
        insert_index += 1
        dependencies.emit(f"[COMBAT_MANAGER] Added NPC {npc_name} in new format at index {insert_index - 1}")
    dependencies.save_json(history_file, history)
    dependencies.emit("[COMBAT_MANAGER] NPC templates updated to new format")


def _startup_provider_call(
    messages: List[Dict[str, Any]],
    *,
    dependencies: CombatStartupNarrativeDependencies,
    model: str,
    context: str,
    legacy_branch: Optional[str] = None,
    temperature_used: Any = None,
) -> str:
    """Preserve the established export, timing, request, and trace sequence."""
    from core.combat.turn_commit import conversation_history_for_prompt

    messages = conversation_history_for_prompt(messages)
    if dependencies.debug_dumps_enabled():
        with dependencies.export_open(
            "debug/api_captures/combat_messages_to_api.json", "w", encoding="utf-8"
        ) as handle:
            json.dump(messages, handle, indent=2, ensure_ascii=False)
        dependencies.emit(
            "DEBUG: [COMBAT] Exported compressed messages to debug/api_captures/combat_messages_to_api.json"
        )
    trace_start = dependencies.perf_counter()
    if dependencies.llm_call is None or dependencies.receipt_observer_factory is None:
        raise RuntimeError("combat startup router dependencies are unavailable")
    legacy_context = {
        "branch": legacy_branch or ("gpt5" if model.startswith("gpt-5") else "gpt4.1"),
        "context": "re-engage",
        "legacy_context_model": model,
    }
    if temperature_used is not None:
        legacy_context["temperature"] = temperature_used
    observer = dependencies.receipt_observer_factory(
        messages=messages,
        legacy_context=legacy_context,
        trace_site="combat_reengage" if context == "re-engage" else "combat_main",
        endpoint_name="combat" if context == "re-engage" else None,
        api_logger=dependencies.log_api_call if context == "re-engage" else None,
        api_log_before_tracker=True,
        track_usage=dependencies.usage_tracking_available,
    )
    options = {"temperature": temperature_used} if temperature_used is not None else {}
    return dependencies.llm_call("combat_main", messages, json_output=False, observer=observer, **options)


def _raise_if_terminal_provider_error(error: Exception) -> None:
    """Resolve the facade type only on an error path, preserving guarded imports."""
    from utils.llm_router import GameLLMTerminalError
    if isinstance(error, GameLLMTerminalError):
        raise error


def _run_resume_narrative(
    inputs: CombatStartupNarrativeInputs,
    dependencies: CombatStartupNarrativeDependencies,
) -> CombatStartupNarrativeResult:
    """Run the legacy single-shot resume narration and fallback sequence."""
    history = inputs.history
    temperature_used = inputs.temperature_used
    if inputs.recovered_pending_turn:
        dependencies.debug(
            "RESUME: Pending turn recovery already published stored narration; skipping re-engagement",
            category="combat_events",
        )
        dependencies.emit(
            "DEBUG: [RESUME] Pending turn recovery already published stored narration; "
            "skipping re-engagement"
        )
        return CombatStartupNarrativeResult(
            history=history,
            is_resuming=True,
            session=inputs.session,
            temperature_used=temperature_used,
        )
    dependencies.emit("[COMBAT_MANAGER] Injecting 'player has returned' message to re-engage AI.")
    dependencies.debug("RESUME: Starting combat resume flow", category="combat_events")
    dependencies.emit("DEBUG: [RESUME] Starting combat resume flow")
    resume_prompt = (
        "Dungeon Master Note: The game session is resuming after a pause. The player has returned. "
        "Please provide a brief narration to re-establish the scene and prompt the player for their next action, "
        "based on the last known state from the conversation history."
    )
    if not history or history[-1].get("content") != resume_prompt:
        dependencies.debug("RESUME: Adding resume prompt to conversation history", category="combat_events")
        dependencies.emit("DEBUG: [RESUME] Adding resume prompt to conversation history")
        history.append({"role": "user", "content": resume_prompt})
        dependencies.save_json(inputs.history_file, history)
    else:
        dependencies.debug("RESUME: Resume prompt already exists, skipping", category="combat_events")
        dependencies.emit("DEBUG: [RESUME] Resume prompt already exists, skipping")

    narration = None
    try:
        dependencies.emit("[COMBAT_MANAGER] Getting re-engagement narration from AI...")
        dependencies.debug("RESUME: Requesting AI re-engagement response", category="combat_events")
        dependencies.emit("DEBUG: [RESUME] About to call AI for re-engagement")
        use_gpt5_models, gpt5_mini_model = dependencies.resume_config()
        if use_gpt5_models:
            dependencies.emit(f"DEBUG: [COMBAT RE-ENGAGE] Using GPT-5 model: {gpt5_mini_model}")
            messages_to_send = list(history)
            response = _startup_provider_call(
                messages_to_send,
                dependencies=dependencies,
                model=gpt5_mini_model,
                context="re-engage",
                legacy_branch="gpt5",
            )
        else:
            temperature_used = dependencies.get_temperature(inputs.encounter_data, validation_attempt=0)
            dependencies.emit(
                f"DEBUG: [COMBAT RE-ENGAGE] Using GPT-4.1 model: {dependencies.combat_main_model} "
                f"(temp: {temperature_used})"
            )
            messages_to_send = list(history)
            response = _startup_provider_call(
                messages_to_send,
                dependencies=dependencies,
                model=dependencies.combat_main_model,
                context="re-engage",
                legacy_branch="gpt4.1",
                temperature_used=temperature_used,
            )
        resume_response_content = response.strip()
        dependencies.debug(
            f"RESUME: Got AI response, length: {len(resume_response_content)}", category="combat_events"
        )
        dependencies.emit(f"DEBUG: [RESUME] Got AI response, length: {len(resume_response_content)}")
        history.append({"role": "assistant", "content": resume_response_content})
        dependencies.save_json(inputs.history_file, history)
        parsed_response = json.loads(resume_response_content)
        narration = parsed_response.get("narration", "The battle continues! What do you do?")
        dependencies.publish_narration(narration, emit=dependencies.emit, flush=dependencies.flush)
        dependencies.debug("RESUME: Successfully displayed re-engagement narration", category="combat_events")
        dependencies.emit("DEBUG: [RESUME] Successfully displayed re-engagement narration and flushed output")
    except Exception as exc:
        _raise_if_terminal_provider_error(exc)
        dependencies.error("FAILURE: Could not get re-engagement narration.", exception=exc, category="combat_events")
        dependencies.emit(f"DEBUG: [RESUME] Error getting re-engagement: {str(exc)}")
        dependencies.publish_output(
            "Dungeon Master: The battle continues! What will you do next?",
            emit=dependencies.emit,
            flush=dependencies.flush,
        )
        dependencies.debug(f"RESUME: Using fallback narration due to error: {str(exc)}", category="combat_events")
    return CombatStartupNarrativeResult(
        history=history,
        is_resuming=True,
        session=inputs.session,
        narration=narration,
        temperature_used=temperature_used,
    )


def _build_initial_scene_prompt(
    inputs: CombatStartupNarrativeInputs,
    dependencies: CombatStartupNarrativeDependencies,
) -> Tuple[str, str, str]:
    """Construct the original initial-scene request text without changing bytes."""
    initiative_order = dependencies.get_initiative_order(inputs.encounter_data)
    initiative_narrative = ""
    if inputs.multi_pc_manager:
        combat_initiative = inputs.party_tracker_data.get("worldConditions", {}).get("combatInitiative")
        if not combat_initiative:
            normalized_rolls = inputs.encounter_data.get("initiativeRolls", {})
            normalized_winner = inputs.encounter_data.get("initiativeWinner")
            combat_initiative = {
                "partyRoll": normalized_rolls.get("pcGroup"),
                "enemyRoll": normalized_rolls.get("dmGroup"),
                "partyGoesFirst": (
                    normalized_winner == "pcGroup"
                    if normalized_winner in ("pcGroup", "dmGroup")
                    else True
                ),
            }
            inputs.party_tracker_data.setdefault("worldConditions", {})["combatInitiative"] = combat_initiative
        dependencies.debug(f"[COMBAT_MANAGER] Using group initiative state: {combat_initiative}", category="combat_events")
        inputs.multi_pc_manager.party_initiative = combat_initiative.get("partyRoll", 0) or 0
        inputs.multi_pc_manager.enemy_initiative = combat_initiative.get("enemyRoll", 0) or 0
        inputs.multi_pc_manager.party_goes_first = combat_initiative.get("partyGoesFirst", True)
        initiative_narrative = dependencies.get_multi_pc_initiative_narrative(inputs.multi_pc_manager)

    initial_prompt_text = (
        "The setup scene for the combat has already been given and described to the party. Now, "
        "describe the combat situation and ONLY the enemies listed in the VALID TARGETS & ACTORS "
        "(IMMUTABLE) roster that the party faces."
    )
    if initiative_narrative:
        initial_prompt_text = f"{initiative_narrative}\n\n{initial_prompt_text}"
    initial_prompt = f"""Dungeon Master Note: Respond with valid JSON containing a 'narration' field, 'combat_round' field, and an 'actions' array. This is the start of combat, so describe the scene using ONLY creatures from the VALID TARGETS & ACTORS (IMMUTABLE) roster and set initiative order, but don't take any actions yet. Start off by hooking the player and engaging them for the start of combat the way any world class dungeon master would.

Important Character Field Definitions:
- 'status' field: Overall life/death state - ONLY use 'alive', 'dead', 'unconscious', or 'defeated' (lowercase)
- 'condition' field: 5e status conditions - use 'none' when no conditions, or valid 5e conditions like 'blinded', 'charmed', 'poisoned', etc.
- NEVER set condition to 'alive' - that goes in the status field
- NEVER set status to 'none' - use 'alive' for conscious characters

Combat Round Tracking:
- MANDATORY: Include "combat_round": 1 in your response (this is round 1)
- Track rounds throughout combat and increment when all creatures have acted

Current dynamic state for all creatures:
{inputs.dynamic_state}

Initiative Order: {initiative_order}

{inputs.preroll_text}

Player: {initial_prompt_text}"""
    if inputs.multi_pc_manager:
        active_pc = inputs.party_tracker_data.get("active_character") or inputs.multi_pc_manager.current_pc_name
        initial_prompt = dependencies.modify_prompt_for_multi_pc(
            initial_prompt, active_pc, inputs.multi_pc_manager
        )
    return initiative_order, initial_prompt_text, initial_prompt


def _run_initial_scene_generation(
    inputs: CombatStartupNarrativeInputs,
    dependencies: CombatStartupNarrativeDependencies,
) -> CombatStartupNarrativeResult:
    """Run the legacy three-attempt initial scene generation/validation loop."""
    history = inputs.history
    initiative_order, initial_prompt_text, initial_prompt = _build_initial_scene_prompt(inputs, dependencies)
    history.append({"role": "user", "content": initial_prompt})
    dependencies.save_json(inputs.history_file, history)

    max_retries = 3
    initial_response = None
    initial_conversation_length = len(history)
    retry_feedback_note = None
    temperature_used = inputs.temperature_used
    for attempt in range(max_retries):
        try:
            temperature_used = dependencies.get_temperature(inputs.encounter_data, validation_attempt=attempt)
            retry_local_history = list(history)
            if retry_feedback_note:
                retry_local_history.append({"role": "user", "content": retry_feedback_note})
            retry_local_history = conversation_history_for_prompt(retry_local_history)
            prompt_prep_start = dependencies.perf_counter()
            messages_to_send = list(retry_local_history)
            if dependencies.debug_dumps_enabled():
                with dependencies.export_open(
                    "debug/api_captures/combat_messages_to_api.json", "w", encoding="utf-8"
                ) as handle:
                    json.dump(messages_to_send, handle, indent=2, ensure_ascii=False)
            dependencies.trace_stage("prompt_prep", prompt_prep_start)
            if dependencies.debug_dumps_enabled():
                dependencies.emit(
                    "DEBUG: [COMBAT] Exported messages to debug/api_captures/combat_messages_to_api.json"
                )
            trace_start = dependencies.perf_counter()
            if dependencies.llm_call is None or dependencies.receipt_observer_factory is None:
                raise RuntimeError("combat startup router dependencies are unavailable")
            observer = dependencies.receipt_observer_factory(
                messages=messages_to_send,
                legacy_context={"context": "initial", "attempt": attempt + 1,
                                "temperature": temperature_used},
                trace_site="combat_main",
                track_usage=dependencies.usage_tracking_available,
            )
            response_text = dependencies.llm_call(
                "combat_main", messages_to_send, json_output=False, observer=observer,
                temperature=temperature_used,
            )
            initial_response = response_text.strip()
            retry_validation_history = list(retry_local_history)
            retry_validation_history.append({"role": "assistant", "content": initial_response})
            if not dependencies.is_valid_json(initial_response):
                if attempt < max_retries - 1:
                    retry_feedback_note = "Invalid JSON format. Please try again."
                    continue
                break

            validation_stage_start = dependencies.perf_counter()
            validation_result = dependencies.validate_response(
                initial_response,
                inputs.encounter_data,
                initial_prompt_text,
                retry_validation_history,
                multi_pc_manager=inputs.multi_pc_manager,
            )
            dependencies.trace_stage("validation", validation_stage_start)
            if validation_result is True:
                retry_feedback_note = None
                break
            if attempt < max_retries - 1:
                retry_feedback_note = validation_result
                continue
            break
        except Exception as exc:
            _raise_if_terminal_provider_error(exc)
            dependencies.error(
                f"FAILURE: AI call for initial scene failed on attempt {attempt + 1}",
                exception=exc,
                category="combat_events",
            )
            if attempt >= max_retries - 1:
                break

    history = history[:initial_conversation_length]
    inputs.session.bind_history(history)
    narration = None
    if initial_response:
        history.append({"role": "assistant", "content": initial_response})
        dependencies.save_json(inputs.history_file, history)
        try:
            parsed_response = json.loads(initial_response)
            narration = parsed_response["narration"]
            dependencies.publish_narration(narration, emit=dependencies.emit, flush=dependencies.flush)
        except (json.JSONDecodeError, KeyError):
            dependencies.publish_output(
                f"Dungeon Master: {initial_response}", emit=dependencies.emit, flush=dependencies.flush
            )
    else:
        dependencies.error("FAILURE: Could not get a valid initial scene from AI.", category="combat_events")
        return CombatStartupNarrativeResult(
            history=history,
            is_resuming=False,
            session=inputs.session,
            initiative_order=initiative_order,
            initial_prompt_text=initial_prompt_text,
            initial_response=initial_response,
            temperature_used=temperature_used,
            initial_conversation_length=initial_conversation_length,
            retry_feedback_note=retry_feedback_note,
            return_early=True,
            return_value=(None, None),
        )
    return CombatStartupNarrativeResult(
        history=history,
        is_resuming=False,
        session=inputs.session,
        initiative_order=initiative_order,
        initial_prompt_text=initial_prompt_text,
        initial_response=initial_response,
        narration=narration,
        temperature_used=temperature_used,
        initial_conversation_length=initial_conversation_length,
        retry_feedback_note=retry_feedback_note,
    )


def run_startup_narrative(
    inputs: CombatStartupNarrativeInputs,
    dependencies: CombatStartupNarrativeDependencies,
) -> CombatStartupNarrativeResult:
    """Dispatch one startup narration branch and return all owner handoffs."""
    if inputs.is_resuming:
        return _run_resume_narrative(inputs, dependencies)
    is_fast_lane = (
        inputs.multi_pc_manager is not None
        and inputs.encounter_data.get("awaitingPcGroupRoll", False) is True
    )
    if is_fast_lane:
        dependencies.info("COMBAT_INIT: Using fast-lane path (skipping initial-scene LLM call)", category="combat_events")
        dependencies.emit(
            "[skipTTS][prefill:/init ] Dungeon Master: [SYSTEM] Combat initiated. Initiative pending. "
            "Enter /init <1-20> to begin combat."
        )
        dependencies.flush()
        dependencies.debug("COMBAT_INIT: Fast-lane startup complete; deferring narration until phase starts", category="combat_events")
        return CombatStartupNarrativeResult(
            history=inputs.history,
            is_resuming=False,
            session=inputs.session,
            is_fast_lane=True,
            temperature_used=inputs.temperature_used,
        )
    dependencies.debug("AI_CALL: Getting initial scene description...", category="combat_events")
    return _run_initial_scene_generation(inputs, dependencies)
