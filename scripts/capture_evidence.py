# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Small, fail-closed evidence helpers for named Capture_Arena runs.

Snapshots contain only selected mechanical fields and hashes from whitelisted
sandbox records. They are read-only and never inspect configuration files.
"""

from __future__ import annotations

import hashlib
import ast
import json
import math
import os
import re
import sqlite3
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import unquote_to_bytes


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROJECT_TMP = PROJECT_ROOT / "tmp"
if not __package__ and str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
RUN_ROOT = PROJECT_TMP / "router-rollout" / "g3"
G4_RUN_ROOT = PROJECT_TMP / "router-rollout" / "g4"
G5_RUN_ROOT = PROJECT_TMP / "router-rollout" / "g5"
G5R_RUN_ROOT = PROJECT_TMP / "router-rollout" / "g5r"
G5T_RUN_ROOT = PROJECT_TMP / "router-rollout" / "g5t"
G5A_RUN_ROOT = PROJECT_TMP / "router-rollout" / "g5a"
G7_RUN_ROOT = PROJECT_TMP / "router-rollout" / "g7"
G9_RUN_ROOT = PROJECT_TMP / "router-rollout" / "g9"
G10_RUN_ROOT = PROJECT_TMP / "router-rollout" / "g10"
G10_OWNERSHIP_METHOD = "macos_proc_pidinfo_parent_pid_and_cwd"
G10_LISTENER_SOURCE = "strict_lsof_listener_set"
G10_LISTENER_SET_VALIDATION = "strict_lsof_stable_before_and_after"
G10_PROCESS_IDENTITY_VALIDATION = "stable_after_revalidation"
_G5_ACTION_ID_RE = re.compile(r"pc:r[0-9]{1,43}:[a-z0-9_]{1,32}")
_G5_BATCH_ID_RE = re.compile(r"enemy:r[0-9]{1,73}")
_G5_ACTOR_ID_RE = re.compile(r"actor_(?:[1-9]|[12][0-9]|3[0-2])")
_G5_TRACE_RUN_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,79}")
_ROUTER_TASK_ID_RE = re.compile(r"[a-z][a-z0-9_]{0,79}")
_G5_DRIVER_UNIT_ID_RE = re.compile(r"(?:action|batch|control)-step-[0-9]{3}")
_ROUTER_RECEIPT_IDENTITY_FIELDS = (
    "call_id", "attempt_id", "attempt_number", "task", "tier", "profile",
    "provider", "observed_upstream_provider", "requested_model", "resolved_model",
    "retry", "retry_tier", "fallback", "outcome", "error_type",
)
SCENARIO_VERSION = "g3-capture-v1"
G4_REQUIRED_KEYS = (
    "narrator-dialogue-travel:p1", "narrator-dialogue-travel:p4",
    "combat-smoke:p1", "combat-smoke:p4",
)
REQUIRED_KEYS = tuple(
    ["%s:p%d" % (scenario, party)
     for scenario in ("combat-smoke", "combat-smoke-allied-inactive", "initiative-pc",
                      "initiative-dm-tie", "death-save") for party in (1, 4)]
    + ["surrender-exit:%s:p%d" % (branch, party)
       for branch in ("surrender", "explicit-exit") for party in (1, 4)]
    + ["resume-replay:%s:p%d" % (phase, party)
       for phase in ("complete", "replay") for party in (1, 4)]
)
G7_BOUNDARY_NONE = "none"
G7_PHASES = ("interrupt", "recover", "complete", "replay")
G7_PATHS = ("normal", "enemy_batch")
_G7_TURN_MANIFEST_KEY = "_combat_turn_commit_manifest"


def _json_digest(value: Any) -> Optional[str]:
    """Hash a JSON-compatible value without exposing its potentially private body."""
    try:
        encoded = json.dumps(value, ensure_ascii=True, sort_keys=True,
                             separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        return None
    return hashlib.sha256(encoded).hexdigest()


def _g7_character_resource_projection(character: Dict[str, Any]) -> Dict[str, Any]:
    spellcasting = character.get("spellcasting")
    slots = spellcasting.get("spellSlots") if isinstance(spellcasting, dict) else None
    feature_uses = []
    for feature in character.get("classFeatures", []) if isinstance(character.get("classFeatures"), list) else []:
        if isinstance(feature, dict) and isinstance(feature.get("usage"), dict):
            feature_uses.append({"name": feature.get("name"), **feature["usage"]})
    equipment_resources = []
    for item in character.get("equipment", []) if isinstance(character.get("equipment"), list) else []:
        if isinstance(item, dict) and (item.get("item_type") == "ammunition" or
                                       item.get("consumable") is True or
                                       item.get("charges") is not None):
            equipment_resources.append({key: item.get(key) for key in
                ("item_name", "item_type", "quantity", "charges", "consumable")})
    return {
        "spellSlots": slots,
        "spellSlots_provenance": "spellcasting.spellSlots" if isinstance(spellcasting, dict) and
            "spellSlots" in spellcasting else "absent_in_record",
        "ammunition": character.get("ammunition"),
        "ammunition_provenance": "top_level_ammunition" if "ammunition" in character else "absent_in_record",
        "classFeatureUses": feature_uses,
        "equipmentResources": equipment_resources,
    }


def _g7_effect_projection(payload: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(payload, dict):
        return None
    return {
        "name": payload.get("name"),
        "hitPoints": payload.get("hitPoints"),
        "maxHitPoints": payload.get("maxHitPoints"),
        "status": payload.get("status"),
        "condition": payload.get("condition"),
        "condition_affected": payload.get("condition_affected"),
        "deathSaves": payload.get("deathSaves"),
        "resource_state": _g7_character_resource_projection(payload),
        "experience_points": payload.get("experience_points"),
        "experiencePoints": payload.get("experiencePoints"),
        "currency": payload.get("currency"),
        "last_combat_applied_id": payload.get("last_combat_applied_id"),
    }


def _g7_encounter_projection(payload: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(payload, dict):
        return None
    creature_fields = (
        "name", "type", "npcType", "status", "currentHitPoints", "maxHitPoints",
        "armorClass", "defeatReason", "coverFeatureId", "coverType", "deathSaves",
        "conditions", "actions", "experience_points", "experiencePoints",
        "last_combat_applied_id",
    )
    return {
        "encounterId": payload.get("encounterId"),
        "current_round": payload.get("current_round"),
        "combat_round": payload.get("combat_round"),
        "combat_phase": payload.get("combat_phase"),
        "pcPhaseComplete": payload.get("pcPhaseComplete"),
        "openingEnemyBatchPending": payload.get("openingEnemyBatchPending"),
        "turn_receipts": payload.get("turn_receipts", []),
        "creatures": [
            {field: row.get(field) for field in creature_fields}
            for row in payload.get("creatures", []) if isinstance(row, dict)
        ] if isinstance(payload.get("creatures"), list) else None,
    }


def _inside(path: Path, root: Path) -> bool:
    try:
        resolved, resolved_root = path.resolve(), root.resolve()
        return resolved == resolved_root or resolved_root in resolved.parents
    except (OSError, RuntimeError):
        return False


def _has_symlink_component(path: Path, root: Path) -> bool:
    try:
        relative = path.absolute().relative_to(root.absolute())
    except ValueError:
        return True
    current = root.absolute()
    if current.is_symlink():
        return True
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return True
    return False


def validate_evidence_paths(run_dir: Any, state_root: Any, gate: str = "g3") -> tuple[Path, Path]:
    """Validate the unique run directory and sandbox root before transport."""
    run = Path(str(run_dir))
    state = Path(str(state_root))
    run_roots = {"g3": RUN_ROOT, "g4": G4_RUN_ROOT, "g5": G5_RUN_ROOT,
                 "g5r": G5R_RUN_ROOT, "g5t": G5T_RUN_ROOT, "g5a": G5A_RUN_ROOT,
                 "g7": G7_RUN_ROOT,
                 "g9": G9_RUN_ROOT, "g10": G10_RUN_ROOT}
    if gate not in run_roots:
        raise ValueError("capture gate must be g3, g4, g5, g5r, g5t, g5a, g7, g9, or g10")
    run_root = run_roots[gate]
    if not _inside(run, run_root) or run.resolve() == run_root.resolve():
        raise ValueError("--run-dir must be a child of project tmp/router-rollout/%s/" % gate)
    if _has_symlink_component(run, PROJECT_TMP):
        raise ValueError("--run-dir must not traverse symlinks")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", run.name):
        raise ValueError("--run-dir must end in a simple run id")
    if run.exists() or run.is_symlink():
        raise ValueError("--run-dir must be a unique, not-yet-existing directory")
    if not _inside(state, PROJECT_TMP) or state.resolve() == PROJECT_TMP.resolve():
        raise ValueError("--state-root must resolve below project tmp/")
    if _has_symlink_component(state, PROJECT_TMP):
        raise ValueError("--state-root must not contain symlink path components")
    if not state.is_dir():
        raise ValueError("--state-root must be an existing sandbox directory")
    return run, state


def _safe_read_bytes(path: Path, root: Path) -> tuple[Optional[bytes], Optional[str]]:
    if not _inside(path, root) or _has_symlink_component(path, root):
        return None, "unsafe_path"
    try:
        raw = path.read_bytes()
        if not _inside(path.resolve(), root.resolve()):
            return None, "outside_sandbox"
        return raw, None
    except OSError as error:
        return None, "unreadable:%s" % type(error).__name__


def _safe_json(path: Path, root: Path) -> tuple[Optional[Dict[str, Any]], Optional[str], Optional[str]]:
    raw, error = _safe_read_bytes(path, root)
    if error:
        return None, None, error
    try:
        assert raw is not None
        parsed = json.loads(raw.decode("utf-8"))
        if not isinstance(parsed, dict):
            return None, None, "malformed:not_object"
        return parsed, hashlib.sha256(raw).hexdigest(), None
    except (UnicodeError, ValueError):
        return None, None, "malformed:json"


def _history_semantics(path: Path, raw: bytes) -> Dict[str, Any]:
    try:
        if path.suffix.lower() == ".txt":
            return {"semantic_message_count": None, "semantic_message_identities": None,
                    "identity_status": "unsupported_text_history"}
        if path.suffix.lower() == ".jsonl":
            messages = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
        else:
            value = json.loads(raw.decode("utf-8"))
            messages = value if isinstance(value, list) else next(
                (value.get(key) for key in ("messages", "conversation_history", "history", "entries")
                 if isinstance(value, dict) and isinstance(value.get(key), list)), None)
        if not isinstance(messages, list):
            return {"semantic_message_count": None, "semantic_message_identities": None,
                    "identity_status": "unsupported_history_schema"}
        identities: List[Dict[str, Any]] = []
        excluded: Dict[str, int] = {}
        for index, message in enumerate(messages):
            if isinstance(message, dict) and message.get("role") == "system":
                excluded["system_role_context"] = excluded.get("system_role_context", 0) + 1
                continue
            if not isinstance(message, dict) or message.get("role") not in ("user", "assistant") or not isinstance(message.get("content"), str):
                reason = "non_user_assistant_or_malformed_message"
                excluded[reason] = excluded.get(reason, 0) + 1
                continue
            content = message["content"]
            content_start = content.lstrip()
            marker = next((prefix for prefix in ("Encounter Details:", "NPC Templates:",
                                                   "Dungeon Master Note:", "System:")
                           if content_start.startswith(prefix)), None)
            if marker:
                excluded["known_dynamic_context:" + marker] = excluded.get("known_dynamic_context:" + marker, 0) + 1
                continue
            digest = hashlib.sha256((message["role"] + "\0" + content).encode("utf-8")).hexdigest()
            identities.append({"index": index, "role": message["role"], "sha256": digest})
        commit_manifests = []
        for index, message in enumerate(messages):
            if not isinstance(message, dict) or _G7_TURN_MANIFEST_KEY not in message:
                continue
            manifest = message.get(_G7_TURN_MANIFEST_KEY)
            if not isinstance(manifest, dict):
                commit_manifests.append({"message_index": index, "status": "invalid"})
                continue
            projection = manifest.get("encounter_projection")
            effects = manifest.get("character_effects")
            receipt = manifest.get("receipt")
            commit_manifests.append({
                "message_index": index,
                "status": "ok",
                "schema_version": manifest.get("schema_version"),
                "turn_id": manifest.get("turn_id"),
                "history_turn_id": message.get("turn_id"),
                "applied_id": manifest.get("applied_id"),
                "encounter_id": manifest.get("encounter_id"),
                "path": manifest.get("path"),
                "character_effects": [
                    {"character_name": effect.get("character_name"),
                     "payload_sha256": _json_digest(effect.get("payload")),
                     "effect_projection": _g7_effect_projection(effect.get("payload"))}
                    for effect in effects if isinstance(effect, dict)
                ] if isinstance(effects, list) else None,
                "encounter_projection_sha256": _json_digest(projection),
                "encounter_projection": _g7_encounter_projection(projection),
                "combat_round": (projection.get("combat_round", projection.get("current_round"))
                                 if isinstance(projection, dict) else None),
                "combat_phase": projection.get("combat_phase") if isinstance(projection, dict) else None,
                "receipt": dict(receipt) if isinstance(receipt, dict) else None,
                "staged_rewards_sha256": _json_digest(manifest.get("staged_rewards")),
                "success_narration_sha256": _json_digest(manifest.get("success_narration")),
            })
        return {"semantic_message_count": len(identities), "semantic_message_identities": identities,
                "combat_turn_commit_manifests": commit_manifests,
                "excluded_message_counts": excluded, "identity_status": "ok"}
    except (UnicodeError, ValueError):
        return {"semantic_message_count": None, "semantic_message_identities": None,
                "identity_status": "malformed_history"}


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _has_router_attempt_identity(event: Dict[str, Any]) -> bool:
    """Identify router-shaped traces so legacy compression stays shape-specific."""
    return any(key in event for key in _ROUTER_RECEIPT_IDENTITY_FIELDS)


def _configured_router_task_ids() -> Optional[frozenset]:
    """Return only task IDs registered by the production sampling-policy map."""
    try:
        from model_config import TASK_POLICY_SAMPLING
    except (ImportError, SyntaxError):
        return None
    if not isinstance(TASK_POLICY_SAMPLING, dict):
        return None
    task_ids = frozenset(
        task_id for task_id in TASK_POLICY_SAMPLING
        if isinstance(task_id, str) and _ROUTER_TASK_ID_RE.fullmatch(task_id)
    )
    return task_ids or None


def _state_projection(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    records = snapshot.get("records", {})
    party = records.get("party_tracker.json", {})
    encounter = records.get("selected_encounter", {})
    characters = {key: value for key, value in records.items() if key.startswith("characters/")}
    return {
        "partyMembers": party.get("partyMembers"),
        "activeCombatEncounter": (party.get("worldConditions") or {}).get("activeCombatEncounter"),
        "encounterId": encounter.get("encounterId"),
        "current_round": encounter.get("current_round"),
        "combat_round": encounter.get("combat_round"),
        "combat_phase": encounter.get("combat_phase"),
        "pcPhaseComplete": encounter.get("pcPhaseComplete"),
        "openingEnemyBatchPending": encounter.get("openingEnemyBatchPending"),
        "creatures": encounter.get("creatures"),
        "turn_receipts": encounter.get("turn_receipts", []),
        "characters": {key: {
            name: value.get(name) for name in ("name", "hitPoints", "maxHitPoints", "status",
                "condition", "condition_affected", "deathSaves", "resource_state",
                "experience_points", "currency", "last_combat_applied_id")
        } for key, value in sorted(characters.items())},
    }


def _g10_item_rows(value: Any) -> List[Dict[str, Any]]:
    """Project bounded item identity/count fields without retaining descriptions."""
    rows: List[Dict[str, Any]] = []
    fields = ("item_name", "name", "item_id", "id", "item_type", "quantity", "count",
              "charges", "equipped")

    def add(row: Any, fallback_name: Optional[str] = None) -> None:
        if len(rows) >= 256:
            return
        if isinstance(row, dict):
            projected = {key: row[key] for key in fields if key in row and
                         (isinstance(row[key], (str, int, float, bool, type(None))) or
                          (isinstance(row[key], dict) and all(
                              isinstance(k, str) and isinstance(v, (str, int, float, bool, type(None)))
                              for k, v in row[key].items()
                          )))}
            if fallback_name and not any(key in projected for key in ("item_name", "name", "item_id", "id")):
                projected["name"] = fallback_name[:120]
            if projected:
                rows.append(projected)
        elif isinstance(row, str):
            rows.append({"name": row[:120]})
        elif isinstance(row, (int, float)) and not isinstance(row, bool):
            rows.append({"quantity": row})

    if isinstance(value, list):
        for item in value[:256]:
            add(item)
    elif isinstance(value, dict):
        if any(key in value for key in fields):
            add(value)
        else:
            for name, item in sorted(value.items(), key=lambda pair: str(pair[0]))[:256]:
                add(item, str(name))
    return rows


def _g10_reward_projection(records: Dict[str, Any]) -> Dict[str, Any]:
    characters = {}
    for path, row in sorted(records.items()):
        if not path.startswith("characters/") or not isinstance(row, dict):
            continue
        characters[path] = {
            "currency": row.get("currency"),
            "experience_points": row.get("experience_points"),
            "experiencePoints": row.get("experiencePoints"),
            "items": row.get("g10_reward_items", []),
        }
    encounter = records.get("selected_encounter", {})
    return {
        "characters": characters,
        "encounter_rewards": [
            {key: creature.get(key) for key in ("name", "experience_points", "experiencePoints")}
            for creature in encounter.get("creatures", []) if isinstance(creature, dict)
        ] if isinstance(encounter, dict) and isinstance(encounter.get("creatures"), list) else [],
    }


def _g10_snapshot_projections_match(snapshot: Dict[str, Any]) -> bool:
    """Check that retained projections are reproducible from their bounded records."""
    records = snapshot.get("records")
    if (not isinstance(records, dict) or
            not isinstance(snapshot.get("mechanical_projection"), dict) or
            not isinstance(snapshot.get("g10_reward_projection"), dict)):
        return False
    try:
        return (snapshot["mechanical_projection"] == _state_projection(snapshot) and
                snapshot["g10_reward_projection"] == _g10_reward_projection(records))
    except (AttributeError, KeyError, TypeError, ValueError):
        return False


def _snapshot_numeric_errors(snapshot: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    records = snapshot.get("records", {})
    encounter = records.get("selected_encounter", {})
    creatures = encounter.get("creatures")
    for row in creatures if isinstance(creatures, list) else []:
        for name in ("currentHitPoints", "maxHitPoints", "experience_points", "experiencePoints"):
            value = row.get(name)
            if value is not None and not _finite_number(value):
                errors.append("creature:%s:%s" % (row.get("name", "unknown"), name))
        saves = row.get("deathSaves")
        for name in ("successes", "failures") if isinstance(saves, dict) else ():
            if saves.get(name) is not None and not _finite_number(saves[name]):
                errors.append("creature:%s:deathSaves:%s" % (row.get("name", "unknown"), name))
    for path, row in records.items():
        if not path.startswith("characters/") or not isinstance(row, dict):
            continue
        for name in ("hitPoints", "maxHitPoints", "experience_points", "experiencePoints"):
            value = row.get(name)
            if value is not None and not _finite_number(value):
                errors.append("%s:%s" % (path, name))
        saves = row.get("deathSaves")
        for name in ("successes", "failures") if isinstance(saves, dict) else ():
            if saves.get(name) is not None and not _finite_number(saves[name]):
                errors.append("%s:deathSaves:%s" % (path, name))
        resource_state = row.get("resource_state") or {}
        slots = resource_state.get("spellSlots")
        if isinstance(slots, dict):
            for level, value in slots.items():
                for field in ("current", "max") if isinstance(value, dict) else ():
                    if value.get(field) is not None and not _finite_number(value[field]):
                        errors.append("%s:spellSlots:%s:%s" % (path, level, field))
        for field in ("ammunition", "classFeatureUses", "equipmentResources"):
            for index, item in enumerate(resource_state.get(field, []) or []):
                if not isinstance(item, dict):
                    continue
                for amount_name in ("quantity", "current", "max"):
                    amount = item.get(amount_name)
                    if amount is not None and not _finite_number(amount):
                        errors.append("%s:%s:%d:%s" % (path, field, index, amount_name))
                charges = item.get("charges")
                if isinstance(charges, dict):
                    for amount_name in ("current", "max"):
                        if charges.get(amount_name) is not None and not _finite_number(charges[amount_name]):
                            errors.append("%s:%s:%d:charges.%s" % (path, field, index, amount_name))
        currency = row.get("currency")
        if isinstance(currency, dict):
            for name, value in currency.items():
                if value is not None and not _finite_number(value):
                    errors.append("%s:currency:%s" % (path, name))
    return errors


def snapshot_state(state_root: Path, label: str, encounter_id: Optional[str] = None,
                   observation: Optional[Dict[str, Any]] = None, *,
                   include_g10_rewards: Optional[bool] = None) -> Dict[str, Any]:
    """Read a strict allowlist of sandbox party/encounter/character/history/save state."""
    root = Path(state_root)
    if not _inside(root, PROJECT_TMP) or _has_symlink_component(root, PROJECT_TMP):
        raise ValueError("snapshot root is not a safe project tmp sandbox")
    if include_g10_rewards is None:
        marker_path = root / ".g10-capture.json"
        include_g10_rewards = marker_path.is_file() and not _has_symlink_component(marker_path, root)
    tracked: Dict[str, Any] = {}
    extra_errors: List[str] = []
    party_path = root / "party_tracker.json"
    party, party_hash, party_error = _safe_json(party_path, root)
    tracked["party_tracker.json"] = {
        "status": "ok" if party else (party_error or "missing"),
        "sha256": party_hash,
        "partyMembers": (party or {}).get("partyMembers"),
        "active_character": (party or {}).get("active_character"),
        "worldConditions": {
            key: (party or {}).get("worldConditions", {}).get(key)
            for key in ("activeCombatEncounter", "activeEncounter", "currentLocation", "currentLocationId")
        } if isinstance((party or {}).get("worldConditions"), dict) else None,
    }
    if encounter_id is None and isinstance(party, dict) and isinstance(party.get("worldConditions"), dict):
        encounter_id = party["worldConditions"].get("activeCombatEncounter")
    encounter = None
    encounter_status = "missing_id"
    if isinstance(encounter_id, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,80}", encounter_id):
        rel = "modules/encounters/encounter_%s.json" % encounter_id
        encounter, encounter_hash, encounter_error = _safe_json(root / rel, root)
        encounter_status = "ok" if encounter else (encounter_error or "missing")
        creatures = encounter.get("creatures", []) if encounter else []
        tracked["selected_encounter"] = {
            "status": encounter_status, "path": rel, "sha256": encounter_hash,
            "encounterId": (encounter or {}).get("encounterId"),
            "encounterSummary": (encounter or {}).get("encounterSummary"),
            "combat_round": (encounter or {}).get("combat_round"),
            "initiativeMode": (encounter or {}).get("initiativeMode"),
            "initiativeRolls": (encounter or {}).get("initiativeRolls"),
            "initiativeWinner": (encounter or {}).get("initiativeWinner"),
            "roundStartsWith": (encounter or {}).get("roundStartsWith"),
            "awaitingPcGroupRoll": (encounter or {}).get("awaitingPcGroupRoll"),
            "openingEnemyBatchPending": (encounter or {}).get("openingEnemyBatchPending"),
            "current_round": (encounter or {}).get("current_round"),
            "combat_phase": (encounter or {}).get("combat_phase"),
            "pcPhaseComplete": (encounter or {}).get("pcPhaseComplete"),
            "turn_receipts": (encounter or {}).get("turn_receipts", []),
            "creatures": [
                {key: row.get(key) for key in ("name", "type", "npcType", "status", "currentHitPoints",
                                                "maxHitPoints", "armorClass", "defeatReason",
                                                "coverFeatureId", "coverType", "deathSaves", "conditions", "actions",
                                                "experience_points", "experiencePoints",
                                                "last_combat_applied_id")}
                for row in creatures if isinstance(row, dict)
            ] if isinstance(creatures, list) else None,
        }
    else:
        tracked["selected_encounter"] = {"status": encounter_status, "path": None}
    names = (party or {}).get("partyMembers", []) if isinstance(party, dict) else []
    npc_names = [row.get("name") for row in (party or {}).get("partyNPCs", [])
                 if isinstance(row, dict)] if isinstance(party, dict) else []
    for name in list(names) + npc_names:
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9 _-]{1,80}", name):
            continue
        rel = "characters/%s.json" % name.lower().replace(" ", "_")
        character, digest, char_error = _safe_json(root / rel, root)
        spellcasting = character.get("spellcasting") if isinstance(character, dict) else None
        slots = spellcasting.get("spellSlots") if isinstance(spellcasting, dict) else None
        feature_uses = []
        for feature in (character or {}).get("classFeatures", []) if isinstance(character, dict) else []:
            if isinstance(feature, dict) and isinstance(feature.get("usage"), dict):
                feature_uses.append({"name": feature.get("name"), **feature["usage"]})
        equipment_resources = []
        for item in (character or {}).get("equipment", []) if isinstance(character, dict) else []:
            if isinstance(item, dict) and (item.get("item_type") == "ammunition" or
                                           item.get("consumable") is True or item.get("charges") is not None):
                equipment_resources.append({key: item.get(key) for key in
                    ("item_name", "item_type", "quantity", "charges", "consumable")})
        resource_state = {
            "spellSlots": slots,
            "spellSlots_provenance": "spellcasting.spellSlots" if isinstance(spellcasting, dict) and "spellSlots" in spellcasting else "absent_in_record",
            "ammunition": character.get("ammunition") if isinstance(character, dict) and "ammunition" in character else None,
            "ammunition_provenance": "top_level_ammunition" if isinstance(character, dict) and "ammunition" in character else "absent_in_record",
            "classFeatureUses": feature_uses,
            "equipmentResources": equipment_resources,
        }
        tracked[rel] = {
            "read_status": "ok" if character else (char_error or "missing"),
            "sha256": digest,
            **{key: (character or {}).get(key) for key in
                ("name", "type", "character_type", "hitPoints", "maxHitPoints", "status",
                 "condition", "condition_affected", "deathSaves", "resource_state",
                 "last_combat_applied_id",
                "currency", "experience_points", "experiencePoints")},
            "resource_state": resource_state,
        }
        if include_g10_rewards and isinstance(character, dict):
            reward_items: List[Dict[str, Any]] = []
            for source_name in ("inventory", "equipment", "items"):
                for item in _g10_item_rows(character.get(source_name)):
                    reward_items.append({"source": source_name, **item})
                    if len(reward_items) >= 256:
                        break
                if len(reward_items) >= 256:
                    break
            tracked[rel]["g10_reward_items"] = reward_items
    for rel in ("modules/conversation_history", "save_games"):
        directory = root / rel
        entries = []
        if not directory.is_dir() or not _inside(directory, root) or _has_symlink_component(directory, root):
            extra_errors.append(rel + ":missing_or_unsafe_directory")
        else:
            try:
                directory_entries = sorted(directory.iterdir())
            except OSError:
                directory_entries = []
                extra_errors.append(rel + ":unreadable_directory")
            if len(directory_entries) > 200:
                extra_errors.append(rel + ":entry_limit_exceeded")
            for item in directory_entries[:200]:
                if item.is_file() and item.suffix.lower() in (".json", ".jsonl", ".txt"):
                    raw, error = _safe_read_bytes(item, root)
                    entry = {"path": rel + "/" + item.name,
                                    "sha256": hashlib.sha256(raw).hexdigest() if raw is not None else None,
                                    "bytes": len(raw) if raw is not None else None,
                                    "status": "ok" if raw is not None else error}
                    if raw is not None and rel == "modules/conversation_history":
                        entry.update(_history_semantics(item, raw))
                    entries.append(entry)
        tracked[rel] = entries
    errors = [key for key, item in tracked.items()
              if isinstance(item, dict) and item.get("read_status", item.get("status")) not in (None, "ok")]
    errors.extend(entry.get("path", rel) for rel in ("modules/conversation_history", "save_games")
                  for entry in tracked.get(rel, []) if entry.get("status") != "ok")
    errors.extend(extra_errors)
    party_projection = tracked.get("party_tracker.json", {})
    world_projection = party_projection.get("worldConditions") or {}
    result = {"label": label, "captured_at": _now(), "state_root": "sandbox-relative",
            "selected_encounter_id": encounter_id, "observation": observation or {},
            "errors": errors, "numeric_errors": _snapshot_numeric_errors({"records": tracked}),
            "records": tracked, "mechanical_projection": _state_projection({"records": tracked}),
            "g4_read_only_projection": {
                "currentLocation": world_projection.get("currentLocation"),
                "currentLocationId": world_projection.get("currentLocationId"),
                "partyMembers": party_projection.get("partyMembers"),
                "active_character": party_projection.get("active_character"),
            }}
    if include_g10_rewards:
        result["g10_reward_projection"] = _g10_reward_projection(tracked)
    return result


def g10_save_directories(state_root: Path) -> List[str]:
    """Return safe, bounded G10 save-folder identities in the isolated sandbox."""
    root = Path(state_root)
    if (not _inside(root, PROJECT_TMP) or _has_symlink_component(root, PROJECT_TMP) or
            root.resolve() == PROJECT_TMP.resolve()):
        raise ValueError("G10 save inventory requires a safe project tmp sandbox")
    found: List[str] = []
    for relative_root in ("modules/Capture_Arena/saved_games", "saved_games"):
        directory = root / relative_root
        if not directory.exists():
            continue
        if not directory.is_dir() or _has_symlink_component(directory, root):
            raise ValueError("G10 save directory is unsafe")
        for entry in sorted(directory.iterdir(), key=lambda item: item.name):
            if entry.name.startswith("save_") and entry.is_dir():
                if _has_symlink_component(entry, root):
                    raise ValueError("G10 save folder must not traverse symlinks")
                found.append(relative_root + "/" + entry.name)
                if len(found) > 200:
                    raise ValueError("G10 save inventory exceeds its entry bound")
    return found


def _g10_saved_state_hashes(save_dir: Path, snapshot: Dict[str, Any],
                           metadata_digest: str) -> Dict[str, str]:
    """Build the bounded file-identity map for one save snapshot."""
    file_hashes: Dict[str, str] = {}
    records = snapshot.get("records", {})
    if not isinstance(records, dict):
        return file_hashes
    for name, row in records.items():
        if name == "selected_encounter" or name == "party_tracker.json" or name.startswith("characters/"):
            digest = row.get("sha256") if isinstance(row, dict) else None
            source_path = (row.get("path") if name == "selected_encounter" and
                           isinstance(row, dict) else name)
            if isinstance(source_path, str) and isinstance(digest, str):
                file_hashes[source_path] = digest
        elif name == "modules/conversation_history" and isinstance(row, list):
            for item in row:
                if isinstance(item, dict) and isinstance(item.get("path"), str) and isinstance(
                        item.get("sha256"), str):
                    file_hashes[item["path"]] = item["sha256"]
    file_hashes["save_metadata.json"] = metadata_digest
    return file_hashes


def _valid_g10_uuid(value: Any) -> bool:
    """Accept only canonical UUID strings used by the save manager."""
    if not isinstance(value, str):
        return False
    try:
        return str(uuid.UUID(value)) == value.lower()
    except ValueError:
        return False


def _g10_diary_identifier_projection(database_path: Path,
                                     sandbox_root: Path) -> Dict[str, Any]:
    """Read only diary identity/range columns from one bounded SQLite database."""
    path = Path(database_path)
    root = Path(sandbox_root)
    if (not _inside(path, root) or _has_symlink_component(path, root) or
            not path.is_file()):
        return {"status": "BLOCKED", "reason": "diary_identifier_database_missing"}
    try:
        if path.stat().st_size > 64 * 1024 * 1024:
            return {"status": "BLOCKED", "reason": "diary_identifier_database_exceeds_bound"}
        connection = sqlite3.connect(
            "file:%s?mode=ro" % path.resolve(), uri=True, timeout=1.0
        )
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA query_only = ON")
            connection.execute("BEGIN")
            required_entry_columns = {
                "diary_id", "status", "save_id", "draft_key",
                "source_start_event_id", "source_end_event_id",
                "checkpoint_type", "checkpoint_id",
            }
            required_state_columns = {
                "state_id", "last_draft_event_id", "last_confirmed_event_id",
                "last_confirmed_save_id", "last_draft_key",
            }
            entry_columns = {row["name"] for row in connection.execute(
                'PRAGMA table_info("session_diary_entries")'
            )}
            state_columns = {row["name"] for row in connection.execute(
                'PRAGMA table_info("session_diary_state")'
            )}
            if (not required_entry_columns.issubset(entry_columns) or
                    not required_state_columns.issubset(state_columns)):
                return {"status": "BLOCKED", "reason": "diary_identifier_schema_missing"}
            entry_count = connection.execute(
                "SELECT COUNT(*) FROM session_diary_entries"
            ).fetchone()[0]
            state_count = connection.execute(
                "SELECT COUNT(*) FROM session_diary_state"
            ).fetchone()[0]
            if (not isinstance(entry_count, int) or entry_count > 10000 or
                    not isinstance(state_count, int) or state_count > 10):
                return {"status": "BLOCKED", "reason": "diary_identifier_row_count_invalid"}
            entries = [dict(row) for row in connection.execute(
                "SELECT diary_id, status, save_id, draft_key, "
                "source_start_event_id, source_end_event_id, checkpoint_type, checkpoint_id "
                "FROM session_diary_entries ORDER BY diary_id"
            )]
            states = [dict(row) for row in connection.execute(
                "SELECT state_id, last_draft_event_id, last_confirmed_event_id, "
                "last_confirmed_save_id, last_draft_key "
                "FROM session_diary_state ORDER BY state_id"
            )]
        finally:
            connection.close()
    except (OSError, RuntimeError, sqlite3.Error, ValueError):
        return {"status": "BLOCKED", "reason": "diary_identifier_database_unreadable"}

    projection = {"entries": entries, "state": states}
    for row in entries:
        if (not isinstance(row.get("diary_id"), int) or isinstance(row.get("diary_id"), bool) or
                row.get("diary_id") <= 0 or row.get("status") not in ("confirmed", "draft") or
                any(row.get(key) is not None and not isinstance(row.get(key), str)
                    for key in ("save_id", "draft_key", "checkpoint_type", "checkpoint_id")) or
                (row.get("save_id") is not None and not _valid_g10_uuid(row.get("save_id"))) or
                row.get("draft_key") not in (None, "active_draft") or
                row.get("checkpoint_type") not in (None, "save") or
                (row.get("checkpoint_id") is not None and
                 not _valid_g10_uuid(row.get("checkpoint_id"))) or
                any(not isinstance(row.get(key), int) or isinstance(row.get(key), bool) or
                    row.get(key) <= 0 for key in
                    ("source_start_event_id", "source_end_event_id")) or
                row["source_start_event_id"] > row["source_end_event_id"]):
            return {"status": "BLOCKED", "reason": "diary_identifier_entry_malformed"}
    for row in states:
        if (not isinstance(row.get("state_id"), int) or isinstance(row.get("state_id"), bool) or
                row.get("state_id") <= 0 or
                any(not isinstance(row.get(key), int) or isinstance(row.get(key), bool) or
                    row.get(key) < 0 for key in
                    ("last_draft_event_id", "last_confirmed_event_id")) or
                (row.get("last_confirmed_save_id") is not None and
                 not _valid_g10_uuid(row.get("last_confirmed_save_id"))) or
                row.get("last_draft_key") not in (None, "active_draft")):
            return {"status": "BLOCKED", "reason": "diary_identifier_state_malformed"}
    if len({row["diary_id"] for row in entries}) != len(entries):
        return {"status": "BLOCKED", "reason": "diary_identifier_entry_id_duplicated"}
    if len({row["state_id"] for row in states}) != len(states):
        return {"status": "BLOCKED", "reason": "diary_identifier_state_id_duplicated"}
    event_ranges = sorted((row["source_start_event_id"], row["source_end_event_id"])
                          for row in entries)
    if any(current[0] <= previous[1]
           for previous, current in zip(event_ranges, event_ranges[1:])):
        return {"status": "BLOCKED", "reason": "diary_identifier_event_range_overlapping"}
    return {"status": "ok", "projection": projection,
            "projection_sha256": hashlib.sha256(json.dumps(
                projection, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")).hexdigest()}


def _valid_g10_save_directory(save_directory: Any) -> bool:
    """Accept only the fixed Capture_Arena essential-save directory shape."""
    save_parts = Path(save_directory).parts if isinstance(save_directory, str) else ()
    return bool(
        isinstance(save_directory, str) and save_directory and
        not Path(save_directory).is_absolute() and ".." not in save_parts and
        len(save_parts) == 4 and
        save_parts[:3] == ("modules", "Capture_Arena", "saved_games") and
        re.fullmatch(r"save_[0-9]{8}_[0-9]{6}", save_parts[-1]) is not None
    )


def _g10_diary_projection_digest(projection: Dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(
        projection, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()


def _validate_g10_diary_projection(projection: Any) -> Optional[str]:
    """Reject non-minimal or malformed identity-only diary projections."""
    entry_keys = {
        "diary_id", "status", "save_id", "draft_key", "source_start_event_id",
        "source_end_event_id", "checkpoint_type", "checkpoint_id",
    }
    state_keys = {
        "state_id", "last_draft_event_id", "last_confirmed_event_id",
        "last_confirmed_save_id", "last_draft_key",
    }
    if (not isinstance(projection, dict) or set(projection) != {"entries", "state"} or
            not isinstance(projection.get("entries"), list) or
            not isinstance(projection.get("state"), list) or
            len(projection["entries"]) > 10000 or len(projection["state"]) > 10):
        return "g10_diary_identifier_projection_schema_invalid"
    entries, states = projection["entries"], projection["state"]
    for row in entries:
        if (not isinstance(row, dict) or set(row) != entry_keys or
                type(row.get("diary_id")) is not int or row["diary_id"] <= 0 or
                row.get("status") not in ("confirmed", "draft") or
                any(row.get(key) is not None and not isinstance(row.get(key), str)
                    for key in ("save_id", "draft_key", "checkpoint_type", "checkpoint_id")) or
                (row.get("save_id") is not None and not _valid_g10_uuid(row.get("save_id"))) or
                row.get("draft_key") not in (None, "active_draft") or
                row.get("checkpoint_type") not in (None, "save") or
                (row.get("checkpoint_id") is not None and
                 not _valid_g10_uuid(row.get("checkpoint_id"))) or
                type(row.get("source_start_event_id")) is not int or
                type(row.get("source_end_event_id")) is not int or
                row["source_start_event_id"] <= 0 or row["source_end_event_id"] <= 0 or
                row["source_start_event_id"] > row["source_end_event_id"]):
            return "g10_diary_identifier_projection_schema_invalid"
    for row in states:
        if (not isinstance(row, dict) or set(row) != state_keys or
                type(row.get("state_id")) is not int or row["state_id"] <= 0 or
                any(type(row.get(key)) is not int or row[key] < 0 for key in
                    ("last_draft_event_id", "last_confirmed_event_id")) or
                (row.get("last_confirmed_save_id") is not None and
                 not _valid_g10_uuid(row.get("last_confirmed_save_id"))) or
                row.get("last_draft_key") not in (None, "active_draft")):
            return "g10_diary_identifier_projection_schema_invalid"
    if len({row["diary_id"] for row in entries}) != len(entries):
        return "g10_diary_identifier_entry_id_duplicated"
    if len({row["state_id"] for row in states}) != len(states):
        return "g10_diary_identifier_state_id_duplicated"
    event_ranges = sorted((row["source_start_event_id"], row["source_end_event_id"])
                          for row in entries)
    if any(current[0] <= previous[1]
           for previous, current in zip(event_ranges, event_ranges[1:])):
        return "g10_diary_identifier_event_range_overlapping"
    return None


def _g10_diary_projection_record(database_path: Path, sandbox_root: Path,
                                 source_database: str) -> Dict[str, Any]:
    projected = _g10_diary_identifier_projection(database_path, sandbox_root)
    if projected.get("status") != "ok":
        return {"status": "BLOCKED", "source_database": source_database,
                "reason": projected.get("reason", "diary_identifier_projection_unavailable")}
    return {"status": "captured", "source_database": source_database,
            "projection": projected["projection"],
            "projection_sha256": projected["projection_sha256"]}


def _capture_g10_diary_identifier_evidence(root: Path, save_dir: Path,
                                           save_directory: str, save_id: str,
                                           phase: str) -> Dict[str, Any]:
    """Retain only bounded identity/range columns before the sandbox is discarded."""
    saved_record = _g10_diary_projection_record(
        save_dir / "memory_db_package" / "memory.db", root,
        "memory_db_package/memory.db",
    )
    if phase == "resume":
        resumed_record = _g10_diary_projection_record(
            root / "data" / "memory.db", root, "data/memory.db"
        )
    else:
        resumed_record = {"status": "not_applicable", "source_database": "data/memory.db"}
    return {
        "schema_version": 1,
        "status": ("captured" if saved_record.get("status") == "captured" and
                   (phase != "resume" or resumed_record.get("status") == "captured")
                   else "BLOCKED"),
        "phase": phase,
        "save_id": save_id,
        "save_directory": save_directory,
        "saved_checkpoint": saved_record,
        "resumed_state": resumed_record,
    }


def _g10_diary_phase_validation(save_state: Any, expected_phase: str) -> Dict[str, Any]:
    """Validate one retained phase projection without consulting a live sandbox."""
    missing = {"status": "BLOCKED", "failures": [],
               "problems": ["g10_diary_identifier_evidence_missing"]}
    if not isinstance(save_state, dict):
        return missing
    evidence = save_state.get("diary_identifier_evidence")
    evidence_keys = {"schema_version", "status", "phase", "save_id", "save_directory",
                     "saved_checkpoint", "resumed_state"}
    if not isinstance(evidence, dict):
        return missing
    if set(evidence) != evidence_keys:
        return {"status": "FAIL", "failures": ["g10_diary_identifier_schema_invalid"],
                "problems": []}
    if (type(evidence.get("schema_version")) is not int or evidence["schema_version"] != 1 or
            evidence.get("phase") != expected_phase or
            evidence.get("save_id") != save_state.get("save_id") or
            not _valid_g10_uuid(evidence.get("save_id")) or
            evidence.get("save_directory") != save_state.get("save_directory") or
            not _valid_g10_save_directory(evidence.get("save_directory"))):
        return {"status": "FAIL", "failures": ["g10_diary_identifier_phase_identity_mismatch"],
                "problems": []}
    if evidence.get("status") != "captured":
        return {"status": "BLOCKED", "failures": [],
                "problems": ["g10_diary_identifier_evidence_missing"]}

    def validate_record(record: Any, source_database: str) -> Dict[str, Any]:
        if not isinstance(record, dict):
            return {"status": "BLOCKED", "failures": [],
                    "problems": ["g10_diary_identifier_evidence_missing"]}
        if record.get("status") != "captured":
            return {"status": "BLOCKED", "failures": [],
                    "problems": ["g10_diary_identifier_evidence_missing"]}
        if set(record) != {"status", "source_database", "projection", "projection_sha256"}:
            return {"status": "FAIL", "failures": ["g10_diary_identifier_schema_invalid"],
                    "problems": []}
        if record.get("source_database") != source_database:
            return {"status": "FAIL", "failures": ["g10_diary_identifier_source_mismatch"],
                    "problems": []}
        projection = record.get("projection")
        reason = _validate_g10_diary_projection(projection)
        if reason:
            return {"status": "FAIL", "failures": ["g10_diary_identifier_projection_contradictory"],
                    "problems": []}
        digest = record.get("projection_sha256")
        if (not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest) or
                digest != _g10_diary_projection_digest(projection)):
            return {"status": "FAIL", "failures": ["g10_diary_identifier_projection_hash_mismatch"],
                    "problems": []}
        return {"status": "ok", "projection": projection, "projection_sha256": digest,
                "failures": [], "problems": []}

    saved = validate_record(evidence.get("saved_checkpoint"), "memory_db_package/memory.db")
    if saved.get("status") != "ok":
        return saved
    resumed_record = evidence.get("resumed_state")
    if expected_phase == "complete":
        if (not isinstance(resumed_record, dict) or
                resumed_record != {"status": "not_applicable", "source_database": "data/memory.db"}):
            return {"status": "FAIL", "failures": ["g10_diary_identifier_phase_evidence_mismatch"],
                    "problems": []}
        projection = saved["projection"]
        entries, states = projection["entries"], projection["state"]
        confirmed = [row for row in entries if row.get("status") == "confirmed"]
        if (len(entries) != 1 or len(confirmed) != 1 or len(states) != 1):
            return {"status": "FAIL", "failures": ["g10_saved_diary_checkpoint_missing_or_duplicated"],
                    "problems": []}
        checkpoint, state = confirmed[0], states[0]
        if (state.get("state_id") != 1 or checkpoint.get("save_id") != evidence["save_id"] or
                checkpoint.get("draft_key") is not None or
                checkpoint.get("checkpoint_id") != evidence["save_id"] or
                checkpoint.get("checkpoint_type") != "save" or
                state.get("last_confirmed_save_id") != evidence["save_id"] or
                state.get("last_confirmed_event_id") != checkpoint.get("source_end_event_id") or
                state.get("last_draft_event_id") != checkpoint.get("source_end_event_id") or
                state.get("last_draft_key") is not None):
            return {"status": "FAIL", "failures": ["g10_saved_diary_checkpoint_identity_mismatch"],
                    "problems": []}
        return {"status": "ok", "failures": [], "problems": [],
                "save_id": evidence["save_id"], "save_directory": evidence["save_directory"],
                "saved_checkpoint": saved["projection"],
                "saved_projection_sha256": saved["projection_sha256"]}
    if expected_phase != "resume":
        return {"status": "FAIL", "failures": ["g10_diary_identifier_phase_identity_mismatch"],
                "problems": []}
    resumed = validate_record(resumed_record, "data/memory.db")
    if resumed.get("status") != "ok":
        return resumed
    saved_projection, resumed_projection = saved["projection"], resumed["projection"]
    saved_entries, saved_states = saved_projection["entries"], saved_projection["state"]
    resumed_entries, resumed_states = resumed_projection["entries"], resumed_projection["state"]
    saved_confirmed = [row for row in saved_entries if row.get("status") == "confirmed"]
    resumed_confirmed = [row for row in resumed_entries if row.get("status") == "confirmed"]
    resumed_drafts = [row for row in resumed_entries if row.get("status") == "draft"]
    failures: List[str] = []
    if (len(saved_entries) != 1 or len(saved_confirmed) != 1 or len(saved_states) != 1):
        failures.append("g10_saved_diary_checkpoint_missing_or_duplicated")
    if (len(resumed_entries) != 2 or len(resumed_confirmed) != 1 or
            len(resumed_drafts) != 1 or len(resumed_states) != 1):
        failures.append("g10_resumed_diary_checkpoint_or_draft_duplicated")
    confirmed = saved_confirmed[0] if len(saved_confirmed) == 1 else {}
    saved_state = saved_states[0] if len(saved_states) == 1 else {}
    resumed_checkpoint = resumed_confirmed[0] if len(resumed_confirmed) == 1 else {}
    draft = resumed_drafts[0] if len(resumed_drafts) == 1 else {}
    resumed_state = resumed_states[0] if len(resumed_states) == 1 else {}
    if (confirmed.get("save_id") != evidence["save_id"] or
            confirmed.get("draft_key") is not None or
            confirmed.get("checkpoint_id") != evidence["save_id"] or
            confirmed.get("checkpoint_type") != "save" or
            saved_state.get("state_id") != 1 or
            saved_state.get("last_confirmed_save_id") != evidence["save_id"] or
            saved_state.get("last_confirmed_event_id") != confirmed.get("source_end_event_id") or
            saved_state.get("last_draft_event_id") != confirmed.get("source_end_event_id") or
            saved_state.get("last_draft_key") is not None):
        failures.append("g10_saved_diary_checkpoint_identity_mismatch")
    if resumed_checkpoint != confirmed:
        failures.append("g10_resumed_diary_checkpoint_semantics_changed")
    if (resumed_state.get("state_id") != saved_state.get("state_id") or
            draft.get("diary_id") == confirmed.get("diary_id") or
            draft.get("save_id") is not None or draft.get("checkpoint_id") is not None or
            draft.get("checkpoint_type") is not None or
            draft.get("draft_key") != "active_draft" or
            draft.get("source_start_event_id", 0) <= confirmed.get("source_end_event_id", 0) or
            draft.get("source_end_event_id", 0) < draft.get("source_start_event_id", 0) or
            resumed_state.get("last_confirmed_save_id") != evidence["save_id"] or
            resumed_state.get("last_confirmed_event_id") != confirmed.get("source_end_event_id") or
            resumed_state.get("last_draft_event_id") != draft.get("source_end_event_id") or
            resumed_state.get("last_draft_key") != draft.get("draft_key")):
        failures.append("g10_resumed_diary_draft_not_semantically_distinct")
    if failures:
        return {"status": "FAIL", "failures": sorted(set(failures)), "problems": []}
    return {"status": "ok", "failures": [], "problems": [],
            "save_id": evidence["save_id"], "save_directory": evidence["save_directory"],
            "saved_checkpoint": saved_projection, "resumed_projection": resumed_projection,
            "saved_projection_sha256": saved["projection_sha256"],
            "resumed_projection_sha256": resumed["projection_sha256"]}


def validate_g10_diary_restart_evidence(complete_save_state: Any,
                                        resume_save_state: Any) -> Dict[str, Any]:
    """Compare hash-bound phase projections without reading a live sandbox."""
    complete = _g10_diary_phase_validation(complete_save_state, "complete")
    resume = _g10_diary_phase_validation(resume_save_state, "resume")
    failures = list(complete.get("failures", [])) + list(resume.get("failures", []))
    problems = list(complete.get("problems", [])) + list(resume.get("problems", []))
    if complete.get("status") != "ok" or resume.get("status") != "ok":
        return {"status": "FAIL" if failures else "BLOCKED",
                "failures": sorted(set(failures)), "problems": sorted(set(problems))}
    if (complete.get("save_id") != resume.get("save_id") or
            complete.get("save_directory") != resume.get("save_directory") or
            complete.get("saved_checkpoint") != resume.get("saved_checkpoint")):
        failures.append("g10_complete_resume_diary_checkpoint_mismatch")
    if failures:
        return {"status": "FAIL", "failures": sorted(set(failures)), "problems": []}
    resumed_projection = resume["resumed_projection"]
    confirmed = complete["saved_checkpoint"]["entries"][0]
    draft = next(row for row in resumed_projection["entries"] if row.get("status") == "draft")
    return {"status": "ok", "failures": [], "problems": [],
            "saved_projection_sha256": complete.get("saved_projection_sha256"),
            "resumed_projection_sha256": resume.get("resumed_projection_sha256"),
            "confirmed_checkpoint": {
                "diary_id": confirmed.get("diary_id"), "save_id": confirmed.get("save_id"),
                "checkpoint_id": confirmed.get("checkpoint_id"),
                "source_start_event_id": confirmed.get("source_start_event_id"),
                "source_end_event_id": confirmed.get("source_end_event_id"),
            },
            "resume_draft": {
                "diary_id": draft.get("diary_id"), "draft_key": draft.get("draft_key"),
                "source_start_event_id": draft.get("source_start_event_id"),
                "source_end_event_id": draft.get("source_end_event_id"),
                "save_id": draft.get("save_id"), "checkpoint_id": draft.get("checkpoint_id"),
            }}


def _g10_save_metadata_matches(metadata: Dict[str, Any],
                               expected_roster: List[str]) -> bool:
    """Validate canonical save identity without treating its label as identity."""
    game_state = metadata.get("game_state")
    return (
        isinstance(metadata.get("description"), str) and
        metadata.get("save_mode") == "essential" and
        metadata.get("module") == "Capture_Arena" and
        _valid_g10_uuid(metadata.get("save_id")) and
        _valid_g10_uuid(metadata.get("worldline_id")) and
        isinstance(game_state, dict) and
        game_state.get("module") == "Capture_Arena" and
        game_state.get("party_members") == expected_roster
    )


def capture_g10_save_state(state_root: Path, run_dir: Path, before_saves: List[str],
                           expected_roster: List[str], encounter_id: Optional[str], *,
                           phase: str, complete_run_dir: Optional[Path] = None,
                           expected_chain_id: Optional[str] = None,
                           save_confirmation_directory: Optional[str] = None) -> Dict[str, Any]:
    """Project a new save or verify the original save survived a process restart."""
    root = Path(state_root)
    after_saves = g10_save_directories(root)
    if phase == "resume":
        if after_saves != before_saves or not isinstance(complete_run_dir, Path):
            return {"status": "BLOCKED", "reason": "retained_save_identity_missing_or_changed",
                    "save_directories_before": before_saves,
                    "save_directories_after": after_saves, "saved_state_files": []}
        complete_run = complete_run_dir
        if (not _inside(complete_run, G10_RUN_ROOT) or
                complete_run.resolve() == G10_RUN_ROOT.resolve() or
                _has_symlink_component(complete_run, PROJECT_TMP)):
            return {"status": "BLOCKED", "reason": "complete_bundle_path_unsafe",
                    "save_directories_before": before_saves,
                    "save_directories_after": after_saves, "saved_state_files": []}
        complete_manifest, manifest_error = load_bundle_json(complete_run, "manifest.json")
        complete_g10 = (complete_manifest.get("g10")
                        if isinstance(complete_manifest, dict) else None)
        complete_scenario = (complete_manifest.get("scenario", {})
                             if isinstance(complete_manifest, dict) else {})
        complete_party = (complete_manifest.get("party", {})
                          if isinstance(complete_manifest, dict) else {})
        complete_seed = (complete_manifest.get("seed", {})
                         if isinstance(complete_manifest, dict) else {})
        complete_hashes = (complete_manifest.get("artifact_sha256", {})
                           if isinstance(complete_manifest, dict) else {})
        complete_artifacts = (complete_manifest.get("artifacts", {})
                              if isinstance(complete_manifest, dict) else {})
        complete_ref = (complete_artifacts.get("g10_save_state")
                        if isinstance(complete_artifacts, dict) else None)
        complete_save_path, complete_save_path_error = _bundle_file(complete_run, complete_ref)
        complete_save_raw, complete_save_read_error = (
            _safe_read_bytes(complete_save_path, complete_run)
            if complete_save_path is not None else (None, complete_save_path_error)
        )
        if (manifest_error or not isinstance(complete_manifest, dict) or
                complete_manifest.get("gate") != "g10" or
                not isinstance(complete_scenario, dict) or complete_scenario.get("phase") != "complete" or
                complete_manifest.get("chain_id") != expected_chain_id or
                not isinstance(complete_party, dict) or complete_party.get("roster") != expected_roster or
                not isinstance(complete_seed, dict) or
                not isinstance(complete_g10, dict) or complete_g10.get("phase") != "complete" or
                complete_g10.get("chain_id") != expected_chain_id or
                complete_g10.get("seed_id") != complete_seed.get("seed_id") or
                complete_g10.get("sandbox_id") != complete_manifest.get("sandbox_id") or
                complete_manifest.get("sandbox_id") != hashlib.sha256(
                    str(root.resolve()).encode("utf-8")).hexdigest() or
                not isinstance(complete_hashes, dict) or
                complete_save_read_error or complete_save_raw is None or
                complete_hashes.get(complete_ref) !=
                hashlib.sha256(complete_save_raw).hexdigest()):
            return {"status": "BLOCKED", "reason": "complete_bundle_identity_invalid",
                    "save_directories_before": before_saves,
                    "save_directories_after": after_saves, "saved_state_files": []}
        expected_save, save_error = load_bundle_json(complete_run, complete_ref)
        if (save_error or not isinstance(expected_save, dict) or
                expected_save.get("status") != "captured"):
            return {"status": "BLOCKED", "reason": "complete_save_evidence_missing",
                    "save_directories_before": before_saves,
                    "save_directories_after": after_saves, "saved_state_files": []}
        save_relative = expected_save.get("save_directory")
        if not isinstance(save_relative, str) or save_relative not in after_saves:
            return {"status": "BLOCKED", "reason": "retained_save_directory_missing",
                    "save_directories_before": before_saves,
                    "save_directories_after": after_saves, "saved_state_files": []}
        save_dir = root / save_relative
        if _has_symlink_component(save_dir, root):
            return {"status": "BLOCKED", "reason": "retained_save_path_unsafe",
                    "save_directories_before": before_saves,
                    "save_directories_after": after_saves, "saved_state_files": []}
        metadata, metadata_digest, metadata_error = _safe_json(
            save_dir / "save_metadata.json", root
        )
        if (metadata_error or not isinstance(metadata, dict) or
                metadata_digest != expected_save.get("save_metadata_sha256") or
                not _g10_save_metadata_matches(metadata, expected_roster) or
                metadata.get("save_id") != expected_save.get("save_id") or
                metadata.get("worldline_id") != expected_save.get("worldline_id")):
            return {"status": "BLOCKED", "reason": "retained_save_metadata_mismatch",
                    "save_directories_before": before_saves,
                    "save_directories_after": after_saves, "saved_state_files": []}
        current_snapshot = snapshot_state(save_dir, "g10-resumed-saved-state",
                                         encounter_id=encounter_id,
                                         include_g10_rewards=True)
        snapshot_errors = [error for error in current_snapshot.get("errors", [])
                           if error != "save_games:missing_or_unsafe_directory"]
        if (snapshot_errors or current_snapshot.get("numeric_errors") or
                not isinstance(current_snapshot.get("g10_reward_projection"), dict) or
                current_snapshot.get("mechanical_projection") !=
                expected_save.get("saved_state_projection")):
            return {"status": "BLOCKED", "reason": "retained_save_projection_mismatch",
                    "errors": snapshot_errors,
                    "numeric_errors": current_snapshot.get("numeric_errors"),
                    "save_directories_before": before_saves,
                    "save_directories_after": after_saves, "saved_state_files": []}
        current_hashes = _g10_saved_state_hashes(save_dir, current_snapshot, metadata_digest)
        expected_hashes = expected_save.get("saved_state_sha256")
        if not isinstance(expected_hashes, dict) or current_hashes != expected_hashes:
            return {"status": "BLOCKED", "reason": "retained_save_file_hash_mismatch",
                    "save_directories_before": before_saves,
                    "save_directories_after": after_saves, "saved_state_files": []}
        result = {"status": "retained", "save_directory": save_relative,
                  "save_metadata_sha256": metadata_digest, "save_id": metadata.get("save_id"),
                  "worldline_id": metadata.get("worldline_id"),
                  "save_timestamp": metadata.get("save_timestamp"),
                  "party_size": len(expected_roster), "party_roster": expected_roster,
                  "encounter_id": encounter_id,
                  "saved_state_projection": current_snapshot.get("mechanical_projection"),
                  "saved_state_snapshot": current_snapshot,
                  "save_directories_before": before_saves,
                  "save_directories_after": after_saves,
                  "saved_state_files": sorted(current_hashes),
                  "saved_state_sha256": current_hashes,
                  "raw_saved_state_copied": False, "unchanged": True}
        result["diary_identifier_evidence"] = _capture_g10_diary_identifier_evidence(
            root, save_dir, save_relative, metadata.get("save_id"), phase
        )
        return result
    if not isinstance(save_confirmation_directory, str) or not save_confirmation_directory:
        return {"status": "BLOCKED", "reason": "save_completion_confirmation_missing",
                "save_directories_before": before_saves,
                "save_directories_after": after_saves, "saved_state_files": []}
    new_saves = sorted(set(after_saves) - set(before_saves))
    if (len(new_saves) != 1 or len(after_saves) != len(before_saves) + 1 or
            new_saves[0] != save_confirmation_directory):
        return {"status": "BLOCKED", "reason": "save_confirmation_new_save_mismatch",
                "save_directories_before": before_saves,
                "save_directories_after": after_saves, "saved_state_files": []}
    save_relative = new_saves[0]
    save_dir = root / save_relative
    metadata, metadata_digest, metadata_error = _safe_json(save_dir / "save_metadata.json", root)
    if metadata_error or not isinstance(metadata, dict):
        return {"status": "BLOCKED", "reason": "save_metadata_%s" % (metadata_error or "missing"),
                "save_directories_before": before_saves,
                "save_directories_after": after_saves, "saved_state_files": []}
    if not _g10_save_metadata_matches(metadata, expected_roster):
        return {"status": "BLOCKED", "reason": "save_metadata_identity_mismatch",
                "save_directories_before": before_saves,
                "save_directories_after": after_saves, "saved_state_files": []}
    saved_snapshot = snapshot_state(save_dir, "g10-saved-state", encounter_id=encounter_id,
                                    include_g10_rewards=True)
    allowed_errors = [error for error in saved_snapshot.get("errors", [])
                      if error != "save_games:missing_or_unsafe_directory"]
    if (saved_snapshot.get("records", {}).get("party_tracker.json", {}).get("partyMembers") !=
            expected_roster):
        allowed_errors.append("saved_party_roster_mismatch")
    if (allowed_errors or saved_snapshot.get("numeric_errors") or
            not isinstance(saved_snapshot.get("g10_reward_projection"), dict)):
        return {"status": "BLOCKED", "reason": "saved_state_snapshot_incomplete",
                "errors": allowed_errors, "numeric_errors": saved_snapshot.get("numeric_errors"),
                "save_directories_before": before_saves,
                "save_directories_after": after_saves, "saved_state_files": []}
    file_hashes = _g10_saved_state_hashes(save_dir, saved_snapshot, metadata_digest)
    result = {"status": "captured", "save_directory": save_relative,
              "save_metadata_sha256": metadata_digest, "save_id": metadata.get("save_id"),
              "worldline_id": metadata.get("worldline_id"),
              "save_timestamp": metadata.get("save_timestamp"),
              "party_size": len(expected_roster), "party_roster": expected_roster,
              "encounter_id": encounter_id,
              "saved_state_projection": saved_snapshot.get("mechanical_projection"),
              "saved_state_snapshot": saved_snapshot,
              "save_directories_before": before_saves,
              "save_directories_after": after_saves,
              "saved_state_files": sorted(file_hashes), "saved_state_sha256": file_hashes,
              "raw_saved_state_copied": False}
    result["diary_identifier_evidence"] = _capture_g10_diary_identifier_evidence(
        root, save_dir, save_relative, metadata.get("save_id"), phase
    )
    return result


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def snapshot_digest(snapshot: Dict[str, Any]) -> str:
    """Hash normalized selected state records, excluding capture-time labels."""
    payload = json.dumps(snapshot.get("mechanical_projection", {}), ensure_ascii=True, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _write_new(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=True, sort_keys=True, indent=2)
        handle.write("\n")


def _bundle_file(run_dir: Path, reference: Any) -> tuple[Optional[Path], Optional[str]]:
    if not isinstance(reference, str) or not reference or Path(reference).is_absolute():
        return None, "invalid_reference"
    relative = Path(reference)
    if any(part in ("", ".", "..") for part in relative.parts):
        return None, "invalid_reference"
    candidate = run_dir / relative
    if not _inside(candidate, run_dir) or _has_symlink_component(candidate, run_dir):
        return None, "unsafe_reference"
    if not candidate.is_file():
        return None, "missing_file"
    return candidate, None


def load_bundle_json(run_dir: Path, reference: Any) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
    candidate, error = _bundle_file(Path(run_dir), reference)
    if error:
        return None, error
    raw, read_error = _safe_read_bytes(candidate, Path(run_dir))
    if read_error or raw is None:
        return None, read_error or "unreadable"
    try:
        value = json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict):
            return None, "not_object"
        return value, None
    except (UnicodeError, ValueError):
        return None, "malformed_json"


def _load_hash_bound_g10_save_state(run_dir: Path, manifest: Dict[str, Any]
                                    ) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Load the G10 save-state artifact only when its retained manifest hash matches."""
    artifacts = manifest.get("artifacts")
    hashes = manifest.get("artifact_sha256")
    reference = artifacts.get("g10_save_state") if isinstance(artifacts, dict) else None
    if (reference != "g10_save_state.json" or not isinstance(hashes, dict)):
        return None, "artifact_reference_or_hash_missing"
    path, path_error = _bundle_file(Path(run_dir), reference)
    if path_error or path is None:
        return None, path_error or "artifact_missing"
    raw, read_error = _safe_read_bytes(path, Path(run_dir))
    if read_error or raw is None:
        return None, read_error or "artifact_unreadable"
    expected_hash = hashes.get(reference)
    if (not isinstance(expected_hash, str) or
            not re.fullmatch(r"[0-9a-f]{64}", expected_hash) or
            hashlib.sha256(raw).hexdigest() != expected_hash):
        return None, "artifact_hash_mismatch"
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError):
        return None, "malformed_json"
    if not isinstance(value, dict):
        return None, "not_object"
    return value, None


def _snapshot_required_errors(snapshot: Dict[str, Any], manifest: Dict[str, Any]) -> List[str]:
    errors = list(snapshot.get("errors", [])) if isinstance(snapshot.get("errors"), list) else ["malformed_errors"]
    scenario = manifest.get("scenario", {})
    encounter = snapshot.get("records", {}).get("selected_encounter", {})
    g4_narrator = manifest.get("gate") == "g4" and scenario.get("id") == "narrator-dialogue-travel"
    g9_narrator = manifest.get("gate") == "g9" and scenario.get("id") == "narrator-auto"
    if ((g4_narrator or g9_narrator) and
            encounter.get("status") == "missing_id"):
        errors = [error for error in errors if error != "selected_encounter"]
    return errors


def trace_check_inputs(
    positioned: List[Dict[str, Any]],
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Return the shared observation and provider views used by capture checks."""
    observations = [
        row for row in positioned
        if row.get("event_type") == "combat_observation"
        or (row.get("event_type") == "decision" and row.get("decision_point") in {
            "combat_command_fast_path", "enemy_batch_resolution"
        })
    ]
    providers = [row for row in positioned if row.get("event_type") == "provider"]
    return observations, providers


def _artifact_integrity(run_dir: Path, manifest: Dict[str, Any], artifacts: Dict[str, Any]) -> Dict[str, Any]:
    failures: List[str] = []
    loaded: Dict[str, Any] = {}
    expected_refs = ("transcript", "server_log", "trace", "report", "before_snapshot", "after_snapshot", "checks")
    if manifest.get("gate") == "g9":
        expected_refs += ("server_lifecycle",)
        if (manifest.get("scenario", {}).get("id") == "preferred-openai-rollback"):
            expected_refs += ("rollback_server_log",)
        elif artifacts.get("rollback_server_log") is not None:
            failures.append("rollback_server_log:unexpected_for_non_rollback_row")
    if manifest.get("gate") == "g10":
        expected_refs += ("server_lifecycle", "g10_usage", "g10_marker", "g10_save_state",
                          "g10_tracker_telemetry")
    hashes = manifest.get("artifact_sha256", {})
    start_offset = manifest.get("trace_start_offset", {})
    trace_span_manifest = manifest.get("trace_span", {})
    if (start_offset.get("status") != "captured" or
            not isinstance(start_offset.get("source_byte_offset"), int) or
            isinstance(start_offset.get("source_byte_offset"), bool) or
            start_offset.get("source_byte_offset") != trace_span_manifest.get("offset_before_bytes")):
        failures.append("trace_start_offset:missing_or_inconsistent")
    scenario = manifest.get("scenario", {})
    empty_trace_candidate = (
        (scenario.get("id") == "resume-replay" and scenario.get("phase") == "replay" and
         artifacts.get("trace_applicability", {}).get("declared_before_run") is True) or
        (manifest.get("gate") == "g10" and scenario.get("phase") == "resume" and
         artifacts.get("trace_applicability", {}).get("declared_before_run") is True)
    )
    if artifacts.get("copy_errors"):
        failures.extend("copy_error:%s" % item for item in artifacts["copy_errors"])
    trace_copy = artifacts.get("trace_copy", {})
    if trace_copy.get("status") != "copied" or trace_copy.get("source_records") != trace_copy.get("destination_records"):
        failures.append("trace_copy:%s" % trace_copy.get("status", "missing"))
    for name in expected_refs:
        reference = artifacts.get(name)
        candidate, error = _bundle_file(run_dir, reference)
        if error:
            failures.append("%s:%s" % (name, error))
            continue
        raw, read_error = _safe_read_bytes(candidate, run_dir)
        if read_error or raw is None or (not raw and not (name == "trace" and empty_trace_candidate)):
            failures.append("%s:%s" % (name, read_error or "empty"))
            continue
        observed_hash = hashlib.sha256(raw).hexdigest()
        if name != "checks" and hashes.get(reference) != observed_hash:
            failures.append("%s:hash_mismatch" % name)
        if name in ("report", "before_snapshot", "after_snapshot", "checks",
                    "g10_usage", "g10_marker", "g10_save_state",
                    "g10_tracker_telemetry"):
            loaded[name], error = load_bundle_json(run_dir, reference)
            if error:
                failures.append("%s:%s" % (name, error))
        if name == "trace":
            try:
                records = []
                for line_number, line in enumerate(raw.decode("ascii").splitlines(), 1):
                    if not line.strip():
                        continue
                    record = json.loads(line)
                    if not isinstance(record, dict) or record.get("event_type") not in {
                        "stage", "provider", "compression", "file_operation", "decision", "combat_observation"
                    }:
                        failures.append("trace:invalid_record:%d" % line_number)
                    else:
                        records.append(record)
                loaded["trace_records"] = records
            except (UnicodeError, ValueError):
                failures.append("trace:malformed")
    expected_steps = manifest.get("counts", {}).get("steps_sent")
    step_refs = artifacts.get("step_snapshots")
    missing_step_refs = artifacts.get("missing_step_snapshots")
    steps_well_typed = isinstance(expected_steps, int) and not isinstance(expected_steps, bool) and expected_steps >= 0
    expected_step_refs = (["snapshots/step-%03d-%s.json" % (index, edge)
                           for index in range(1, expected_steps + 1) for edge in ("before", "after")]
                          if steps_well_typed else [])
    if (not steps_well_typed or step_refs != expected_step_refs or missing_step_refs):
        failures.append("step_snapshots:incomplete_or_unexpected")
    else:
        for reference in expected_step_refs:
            snapshot, error = load_bundle_json(run_dir, reference)
            if error or snapshot is None:
                failures.append("%s:%s" % (reference, error or "invalid"))
            else:
                loaded[reference] = snapshot
                if manifest.get("gate") in ("g9", "g10"):
                    snapshot_path, snapshot_error = _bundle_file(run_dir, reference)
                    snapshot_raw, snapshot_read_error = (
                        _safe_read_bytes(snapshot_path, run_dir)
                        if snapshot_path is not None else (None, snapshot_error)
                    )
                    if (snapshot_read_error or snapshot_raw is None or
                            hashes.get(reference) != hashlib.sha256(snapshot_raw).hexdigest()):
                        failures.append("%s:hash_mismatch" % reference)
                if _snapshot_required_errors(snapshot, manifest):
                    failures.append("%s:required_state_missing" % reference)
                if snapshot.get("numeric_errors"):
                    failures.append("%s:nonfinite_or_malformed_numeric_state" % reference)
    if loaded.get("report"):
        report = loaded["report"]
        trace_records = loaded.get("trace_records", [])
        trace_is_empty = len(trace_records) == 0
        non_applicable = _non_applicable_replay_trace(manifest, artifacts, loaded)
        non_applicable_g10 = _non_applicable_g10_trace(manifest, artifacts, loaded)
        if ((report.get("status") != "ok" and not (
                report.get("status") == "degraded" and (non_applicable or non_applicable_g10))) or
                report.get("input", {}).get("malformed_count") != 0):
            failures.append("report:degraded")
        if trace_is_empty and not (non_applicable or non_applicable_g10):
            failures.append("trace:empty_required_span")
        if report.get("input", {}).get("total_records") != len(trace_records):
            failures.append("report:trace_count_mismatch")
        observed = report.get("combat_observations")
        expected_observed = [record for record in trace_records if record.get("event_type") == "combat_observation"]
        if observed != expected_observed:
            failures.append("report:observation_mismatch")
        span_offset = manifest.get("trace_span", {}).get("offset_before_bytes")
        trace_reference = artifacts.get("trace")
        if isinstance(trace_reference, str):
            positioned, position_errors = parse_trace_positions(
                Path(run_dir) / trace_reference, span_offset
                if isinstance(span_offset, int) and not isinstance(span_offset, bool) else 0
            )
        else:
            positioned, position_errors = [], ["trace_reference_missing"]
        if position_errors:
            failures.extend(position_errors)
        loaded["trace_position_errors"] = position_errors
        loaded["observations"], loaded["trace_provider_events"] = trace_check_inputs(positioned)
        loaded["trace_positions"] = positioned
    transcript_path, transcript_error = _bundle_file(run_dir, artifacts.get("transcript"))
    if not transcript_error and transcript_path is not None:
        try:
            transcript = transcript_path.read_text(encoding="utf-8")
            starts = len(re.findall(r"\[driver\] step=\d+ start ", transcript))
            completed = len(re.findall(r"\[driver\] step=\d+ done ", transcript))
            counts = manifest.get("counts", {})
            if starts < counts.get("steps_sent", -1) or completed != counts.get("steps_sent", -1):
                failures.append("transcript:step_count_mismatch")
        except (OSError, UnicodeError):
            failures.append("transcript:unreadable")
    for name in ("before_snapshot", "after_snapshot"):
        snapshot = loaded.get(name)
        if snapshot is not None and _snapshot_required_errors(snapshot, manifest):
            failures.append("%s:required_state_missing" % name)
        if snapshot is not None and snapshot.get("numeric_errors"):
            failures.append("%s:nonfinite_or_malformed_numeric_state" % name)
    return {"valid": not failures, "failures": failures, "loaded": loaded}


def hash_artifacts(run_dir: Path, artifacts: Dict[str, Any]) -> Dict[str, str]:
    hashes: Dict[str, str] = {}
    refs = [artifacts.get(name) for name in
             ("transcript", "server_log", "trace", "report", "before_snapshot", "after_snapshot",
              "server_lifecycle", "rollback_server_log", "g10_usage", "g10_marker",
              "g10_save_state", "g10_tracker_telemetry")]
    refs.extend(artifacts.get("step_snapshots", []))
    for reference in refs:
        path, error = _bundle_file(Path(run_dir), reference)
        if error:
            continue
        raw, error = _safe_read_bytes(path, Path(run_dir))
        if raw is not None and not error:
            hashes[str(reference)] = hashlib.sha256(raw).hexdigest()
    return hashes


def _non_applicable_replay_trace(manifest: Dict[str, Any], artifacts: Dict[str, Any],
                                 loaded: Dict[str, Any]) -> bool:
    """Permit only a fresh empty trace span for a fully observed resume-only replay."""
    scenario = manifest.get("scenario", {})
    declared = artifacts.get("trace_applicability", {})
    span = manifest.get("trace_span", {})
    runtime = manifest.get("sandbox_runtime", {})
    readiness = artifacts.get("startup_readiness", {})
    health = readiness.get("health", {}) if isinstance(readiness, dict) else {}
    report = loaded.get("report", {})
    trace_records = loaded.get("trace_records", [])
    before, after = loaded.get("before_snapshot"), loaded.get("after_snapshot")
    histories = []
    for snapshot in (before, after):
        if not isinstance(snapshot, dict) or snapshot.get("errors") or snapshot.get("numeric_errors"):
            return False
        files = snapshot.get("records", {}).get("modules/conversation_history", [])
        semantic = [entry for entry in files if entry.get("identity_status") == "ok" and
                    entry.get("semantic_message_identities")]
        if not semantic:
            return False
        histories.append(semantic)
    gate = runtime.get("trace_gate", {})
    inp = report.get("input", {}) if isinstance(report, dict) else {}
    return bool(
        scenario.get("id") == "resume-replay" and scenario.get("phase") == "replay" and
        declared.get("status") == "non_applicable" and declared.get("declared_before_run") is True and
        declared.get("reason") == "resume replay is observation-only" and
        gate.get("status") == "ok" and gate.get("enabled") is True and
        span.get("status") == "copied" and span.get("span_bytes") == 0 and
        span.get("start_status") == "captured" and
        isinstance(span.get("offset_before_bytes"), int) and not isinstance(span.get("offset_before_bytes"), bool) and
        isinstance(span.get("prefix_sha256"), str) and re.fullmatch(r"[0-9a-f]{64}", span.get("prefix_sha256", "")) and
        span.get("source_records") == 0 and span.get("destination_records") == 0 and
        span.get("source_exists_after") is True and
        span.get("source_reset_detected") is False and span.get("prefix_changed") is False and
        readiness.get("status") == "ready" and readiness.get("processing_idle") is True and
        readiness.get("idle_status_observed") is True and
        readiness.get("output_count", 0) > 0 and health.get("status") == "ok" and
        health.get("http_status") == 200 and health.get("roster_matches") is True and
        report.get("status") == "degraded" and inp.get("total_records") == 0 and
        inp.get("malformed_count") == 0 and trace_records == [] and len(histories) == 2
    )


def _non_applicable_g10_trace(manifest: Dict[str, Any], artifacts: Dict[str, Any],
                               loaded: Dict[str, Any]) -> bool:
    """Allow an empty trace only for the bounded observation-only G10 resume phase."""
    scenario = manifest.get("scenario", {})
    declared = artifacts.get("trace_applicability", {})
    span = manifest.get("trace_span", {})
    gate = (manifest.get("sandbox_runtime") or {}).get("trace_gate", {})
    report = loaded.get("report", {})
    report_input = report.get("input", {}) if isinstance(report, dict) else {}
    before = loaded.get("snapshots/step-001-before.json")
    after = loaded.get("snapshots/step-001-after.json")
    before_obs = before.get("observation", {}) if isinstance(before, dict) else {}
    after_obs = after.get("observation", {}) if isinstance(after, dict) else {}
    before_trace = before_obs.get("runtimeTrace", {})
    after_trace = after_obs.get("runtimeTrace", {})
    usage = loaded.get("g10_usage", {})
    usage_projection = usage.get("observed", {}) if isinstance(usage, dict) else {}
    return bool(
        manifest.get("gate") == "g10" and scenario.get("id") == "full-session" and
        scenario.get("phase") == "resume" and
        declared.get("status") == "non_applicable" and
        declared.get("declared_before_run") is True and
        declared.get("reason") == "G10 retained-state resume is observation-only" and
        gate.get("status") == "ok" and gate.get("enabled") is True and
        span.get("status") == "copied" and span.get("span_bytes") == 0 and
        span.get("start_status") == "captured" and
        isinstance(span.get("offset_before_bytes"), int) and
        not isinstance(span.get("offset_before_bytes"), bool) and
        isinstance(span.get("prefix_sha256"), str) and
        re.fullmatch(r"[0-9a-f]{64}", span.get("prefix_sha256", "")) and
        span.get("source_records") == 0 and span.get("destination_records") == 0 and
        span.get("source_exists_after") is True and span.get("source_reset_detected") is False and
        span.get("prefix_changed") is False and
        manifest.get("counts", {}).get("steps_sent") == 1 and
        before_obs.get("input") == "/usage" and after_obs.get("input") == "/usage" and
        before_trace.get("status") == "captured" and after_trace.get("status") == "captured" and
        before_trace.get("offset_bytes") == after_trace.get("offset_bytes") and
        report.get("status") == "degraded" and report_input.get("total_records") == 0 and
        report_input.get("malformed_count") == 0 and loaded.get("trace_records") == [] and
        usage.get("status") == "ok" and usage_projection.get("status") == "ok" and
        usage.get("router_receipts", {}).get("status") == "none_observed" and
        not usage.get("router_receipt_reconciliation_problems")
    )


def write_step_snapshot(run_dir: Path, state_root: Path, step: int, when: str,
                        encounter_id: Optional[str] = None,
                        observation: Optional[Dict[str, Any]] = None) -> str:
    snapshot = snapshot_state(state_root, "%s-step-%03d" % (when, step),
                              encounter_id=encounter_id, observation=observation)
    filename = "step-%03d-%s.json" % (step, when)
    _write_new(run_dir / "snapshots" / filename, snapshot)
    return "snapshots/" + filename


def count_observed_provider_events(path: Path) -> Optional[int]:
    try:
        count = 0
        with path.open("r", encoding="ascii") as stream:
            for line in stream:
                if not line.strip():
                    continue
                try:
                    if json.loads(line).get("event_type") == "provider":
                        count += 1
                except (ValueError, AttributeError):
                    continue
        return count
    except (OSError, UnicodeError):
        return None


def project_g5_trace(events: List[Dict[str, Any]], expected_run_id: Any,
                     parse_errors: Optional[List[str]] = None,
                     trace_windows: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Attribute trace records to driver-owned windows; runtime IDs are diagnostic only."""
    if (not isinstance(expected_run_id, str) or
            not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", expected_run_id)):
        return {"status": "BLOCKED", "reason": ["invalid_capture_run_id"], "work_units": [],
                "provider_receipts": [], "assignments": [],
                "counts": {"provider_calls": None, "file_writes": None}}

    windows = trace_windows if isinstance(trace_windows, dict) else {}
    raw_steps = windows.get("steps") if isinstance(windows.get("steps"), list) else []
    window_errors: List[str] = []
    step_windows: List[Dict[str, Any]] = []
    for row in raw_steps:
        if not isinstance(row, dict):
            window_errors.append("invalid_step_window")
            continue
        start, end = row.get("start_epoch_ms"), row.get("end_epoch_ms")
        step_number = row.get("step")
        unit_type = row.get("unit_type")
        if (unit_type not in ("action", "batch", "control") or
                not isinstance(row.get("unit_id"), str) or
                not _G5_DRIVER_UNIT_ID_RE.fullmatch(row["unit_id"]) or
                not row["unit_id"].startswith(str(unit_type) + "-step-") or
                not isinstance(step_number, int) or isinstance(step_number, bool) or step_number < 1 or
                row.get("unit_id") != "%s-step-%03d" % (unit_type, step_number) or
                not _finite_number(start) or not _finite_number(end) or start < 0 or end < start):
            window_errors.append("invalid_step_window")
            continue
        step_windows.append({**row, "start_epoch_ms": float(start), "end_epoch_ms": float(end)})
    if (len({row["unit_id"] for row in step_windows}) != len(step_windows) or
            len({row["step"] for row in step_windows}) != len(step_windows)):
        window_errors.append("duplicate_step_window_identity")
    step_windows.sort(key=lambda row: (row["start_epoch_ms"], row.get("step", 0)))
    for previous, current in zip(step_windows, step_windows[1:]):
        if current["start_epoch_ms"] < previous["end_epoch_ms"]:
            window_errors.append("overlapping_step_windows")
    windows_available = bool(step_windows) and not window_errors
    if windows.get("status") != "captured":
        window_errors.append("driver_step_windows_missing_or_invalid")
        windows_available = False

    startup = windows.get("startup") if isinstance(windows.get("startup"), dict) else {}
    teardown = windows.get("teardown") if isinstance(windows.get("teardown"), dict) else {}
    startup_start, startup_end = startup.get("start_epoch_ms"), startup.get("end_epoch_ms")
    teardown_start, teardown_end = teardown.get("start_epoch_ms"), teardown.get("end_epoch_ms")
    if windows_available and (not _finite_number(startup_start) or not _finite_number(startup_end) or
                              startup_start < 0 or startup_end < startup_start or
                              startup_end > step_windows[0]["start_epoch_ms"]):
        window_errors.append("startup_window_missing_or_invalid")
    if windows_available and (not _finite_number(teardown_start) or not _finite_number(teardown_end) or
                              teardown_start < step_windows[-1]["end_epoch_ms"] or
                              teardown_end < teardown_start):
        window_errors.append("teardown_window_missing_or_invalid")
    if window_errors:
        windows_available = False

    groups: Dict[tuple[str, str], Dict[str, Any]] = {}
    for row in step_windows:
        key = (row["unit_type"], row["unit_id"])
        groups[key] = {"type": row["unit_type"], "id": row["unit_id"],
                       "round": row.get("round"), "step": row.get("step"),
                       "provider_calls": 0, "legacy_provider_calls": 0,
                       "legacy_provider_elapsed_ms": 0.0, "file_writes": 0}
    buckets = {name: {"records": 0, "provider_calls": 0,
                      "legacy_provider_calls": 0, "legacy_provider_elapsed_ms": 0.0,
                      "file_writes": 0}
               for name in ("startup", "step", "between_steps", "teardown", "unattributed")}
    provider_receipts: List[Dict[str, Any]] = []
    assignments: List[Dict[str, Any]] = []
    providers, models = set(), set()
    observed_rounds, observed_batches = set(), set()
    provider_count = legacy_provider_count = file_write_count = run_id_mismatches = 0
    legacy_provider_elapsed_ms = 0.0
    unattributed_records = unattributed_provider_calls = unattributed_file_writes = 0
    unplaced_provider_in_span = unplaced_write_in_span = 0

    for record_index, event in enumerate(events):
        if not isinstance(event, dict):
            continue
        run_id_mismatch = event.get("run_id") != expected_run_id
        if run_id_mismatch:
            run_id_mismatches += 1
        event_type = event.get("event_type")
        timestamp = event.get("recorded_at_ms")
        timestamp_valid = _finite_number(timestamp)
        matching = ([row for window_index, row in enumerate(step_windows)
                     if timestamp_valid and row["start_epoch_ms"] <= float(timestamp) and
                     (float(timestamp) < row["end_epoch_ms"] or
                      window_index == len(step_windows) - 1 and float(timestamp) == row["end_epoch_ms"])]
                    if windows_available and not run_id_mismatch else [])
        unit_type = unit_id = None
        unit_round = step_number = None
        inside_measured_span = bool(
            windows_available and timestamp_valid and
            step_windows[0]["start_epoch_ms"] <= float(timestamp) <= step_windows[-1]["end_epoch_ms"]
        )
        reason = None
        if run_id_mismatch:
            bucket, reason = "unattributed", "run_id_missing_or_mismatched"
        elif len(matching) == 1:
            matched = matching[0]
            bucket = "step"
            unit_type, unit_id = matched["unit_type"], matched["unit_id"]
            unit_round, step_number = matched.get("round"), matched.get("step")
        elif len(matching) > 1:
            bucket, reason, inside_measured_span = "unattributed", "overlapping_step_windows", True
        elif not timestamp_valid:
            bucket, reason = "unattributed", "recorded_at_ms_missing_or_invalid"
        elif windows_available and float(timestamp) < step_windows[0]["start_epoch_ms"]:
            bucket = "startup"
            reason = None if startup_start <= timestamp <= startup_end else "outside_startup_bounds"
        elif windows_available and float(timestamp) > step_windows[-1]["end_epoch_ms"]:
            bucket = "teardown"
            reason = None if teardown_start <= timestamp <= teardown_end else "outside_teardown_bounds"
        elif windows_available:
            bucket, reason, inside_measured_span = "between_steps", "outside_step_windows_between_steps", True
        else:
            bucket, reason = "unattributed", "driver_step_windows_unavailable"

        buckets[bucket]["records"] += 1
        is_write = event_type == "file_operation" and event.get("category") == "write"
        if event_type == "provider":
            provider_count += 1
            buckets[bucket]["provider_calls"] += 1
            is_legacy_compression = (
                event.get("site") == "combat_compression"
                and not _has_router_attempt_identity(event)
            )
            if is_legacy_compression:
                legacy_provider_count += 1
                buckets[bucket]["legacy_provider_calls"] += 1
                elapsed = event.get("elapsed_ms")
                if _finite_number(elapsed) and elapsed >= 0:
                    legacy_provider_elapsed_ms += float(elapsed)
                    buckets[bucket]["legacy_provider_elapsed_ms"] += float(elapsed)
            if unit_type and unit_id:
                groups[(unit_type, unit_id)]["provider_calls"] += 1
                if is_legacy_compression:
                    groups[(unit_type, unit_id)]["legacy_provider_calls"] += 1
                    if _finite_number(elapsed) and elapsed >= 0:
                        groups[(unit_type, unit_id)]["legacy_provider_elapsed_ms"] += float(elapsed)
            elif bucket in ("unattributed", "between_steps"):
                unattributed_provider_calls += 1
                if inside_measured_span:
                    unplaced_provider_in_span += 1
        elif is_write:
            file_write_count += 1
            buckets[bucket]["file_writes"] += 1
            if unit_type and unit_id:
                groups[(unit_type, unit_id)]["file_writes"] += 1
            elif bucket in ("unattributed", "between_steps"):
                unattributed_file_writes += 1
                if inside_measured_span:
                    unplaced_write_in_span += 1

        if unit_type in ("action", "batch"):
            if isinstance(unit_round, int) and not isinstance(unit_round, bool):
                observed_rounds.add(unit_round)
            if unit_type == "batch" and isinstance(unit_id, str):
                observed_batches.add(unit_id)

        if event_type == "provider":
            receipt: Dict[str, Any] = {
                "run_id": expected_run_id,
                "work_unit_type": unit_type or bucket,
                "work_unit_id": unit_id or bucket,
                "window_bucket": bucket,
                "step": step_number,
            }
            if is_legacy_compression:
                receipt.update({
                    "classification": "known_unmigrated_compression_observation",
                    "identity_status": "no_router_attempt_identity",
                })
            for source_key in ("provider", "requested_model", "resolved_model", "task", "site"):
                value = event.get(source_key)
                if isinstance(value, str) and value and len(value) <= 120:
                    receipt[source_key] = value
            if receipt.get("provider"):
                providers.add(receipt["provider"])
            if receipt.get("resolved_model"):
                models.add(receipt["resolved_model"])
            action_id, batch_id = event.get("action_id"), event.get("batch_id")
            if isinstance(action_id, str) and _G5_ACTION_ID_RE.fullmatch(action_id):
                receipt["runtime_action_id"] = action_id
            if isinstance(batch_id, str) and _G5_BATCH_ID_RE.fullmatch(batch_id):
                receipt["runtime_batch_id"] = batch_id
            if len(provider_receipts) < 512:
                provider_receipts.append(receipt)

        if bucket in ("unattributed", "between_steps"):
            unattributed_records += 1
        assignments.append({"record_index": record_index, "event_type": event_type,
                            "recorded_at_ms": float(timestamp) if timestamp_valid else None,
                            "bucket": bucket, "reason": reason,
                            "work_unit_type": unit_type, "work_unit_id": unit_id,
                            "step": step_number, "round": unit_round,
                            "inside_measured_span": inside_measured_span})

    reasons: List[str] = []
    if not events:
        reasons.append("trace_events_missing")
    if not windows_available:
        reasons.append("driver_step_windows_missing_or_invalid")
    reasons.extend(window_errors)
    if parse_errors:
        reasons.append("trace_parse_errors")
    if unplaced_provider_in_span or unplaced_write_in_span:
        reasons.append("provider_or_file_write_unattributed_inside_measured_span")
    status = "PASS" if events and not reasons else "BLOCKED"
    return {
        "status": status, "reason": None if not reasons else sorted(set(reasons)),
        "run_id": expected_run_id, "run_id_mismatches": run_id_mismatches,
        "window_errors": sorted(set(window_errors)),
        "unattributed_record_count": unattributed_records,
        "unattributed_record_reasons": {
            key: sum(1 for row in assignments if row.get("reason") == key)
            for key in sorted({row.get("reason") for row in assignments if row.get("reason")})
        },
        "counts": {
            "provider_calls": provider_count, "file_writes": file_write_count,
            "legacy_provider_observations": legacy_provider_count,
            "legacy_provider_elapsed_ms": round(legacy_provider_elapsed_ms, 3),
            "unattributed_provider_calls": unattributed_provider_calls,
            "unattributed_file_writes": unattributed_file_writes,
            "unattributed_provider_calls_in_measured_span": unplaced_provider_in_span,
            "unattributed_file_writes_in_measured_span": unplaced_write_in_span,
            "startup_provider_calls": buckets["startup"]["provider_calls"],
            "startup_file_writes": buckets["startup"]["file_writes"],
            "teardown_provider_calls": buckets["teardown"]["provider_calls"],
            "teardown_file_writes": buckets["teardown"]["file_writes"],
            "between_step_provider_calls": buckets["between_steps"]["provider_calls"],
            "between_step_file_writes": buckets["between_steps"]["file_writes"],
        },
        "window_buckets": [{"bucket": name, **buckets[name]}
                           for name in ("startup", "step", "between_steps", "teardown", "unattributed")],
        "actual_runtime": {"providers": sorted(providers), "resolved_models": sorted(models)},
        "observed_rounds": sorted(observed_rounds) if windows_available else None,
        "observed_enemy_batches": sorted(observed_batches) if windows_available else None,
        "work_units": [groups[key] for key in sorted(groups)],
        "provider_receipts": provider_receipts,
        "assignments": assignments,
    }


def build_g5_capture_metadata(profile: Dict[str, Any], run_id: str,
                              source_identity: Dict[str, Any], seed_id: Optional[str]) -> Dict[str, Any]:
    """Build fixed G5 identity fields from capture-owned source and seed facts."""
    fixture = profile.get("fixture") if isinstance(profile, dict) else None
    if not isinstance(fixture, dict):
        raise ValueError("G5 fixture metadata is required")
    source_hashes = source_identity.get("relevant_source_sha256", {})
    source_digest = hashlib.sha256(
        json.dumps(source_hashes, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    method = fixture.get("measurement_method", {})
    return {
        "fixture": fixture,
        "identity": {
            "run_id": run_id,
            "source_head": source_identity.get("head"),
            "source_digest": source_digest,
            "seed_id": seed_id,
            "provider": "unknown",
            "model": "unknown",
            "configured_provider": None,
            "configured_model": None,
            "measurement_method": method,
        },
        "receipts": [],
        "trace_windows": {"status": "pending"},
        "trace_attribution": {"status": "pending"},
    }


def build_g5t_capture_metadata(profile: Dict[str, Any], run_id: str,
                               source_identity: Dict[str, Any], seed_id: Optional[str]) -> Dict[str, Any]:
    """Build primary G5T identity fields from the named fixture and source facts."""
    fixture = profile.get("fixture") if isinstance(profile, dict) else None
    if not isinstance(fixture, dict):
        raise ValueError("G5T fixture metadata is required")
    source_hashes = source_identity.get("relevant_source_sha256", {})
    source_digest = hashlib.sha256(
        json.dumps(source_hashes, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "fixture": fixture,
        "identity": {
            "run_id": run_id,
            "source_head": source_identity.get("head"),
            "source_digest": source_digest,
            "seed_id": seed_id,
            "provider": "unknown",
            "model": "unknown",
            "configured_provider": None,
            "configured_model": None,
            "measurement_method": fixture.get("measurement_method", {}),
        },
        "capture_mode": "primary",
        "prefetch_enabled": False,
        "receipts": [],
        "trace_windows": {"status": "pending"},
        "trace_attribution": {"status": "pending"},
    }


def build_g5a_capture_metadata(profile: Dict[str, Any], run_id: str,
                               source_identity: Dict[str, Any], seed_id: Optional[str]) -> Dict[str, Any]:
    """Build G5A fixture and source identity without claiming a live verdict."""
    fixture = profile.get("fixture") if isinstance(profile, dict) else None
    if not isinstance(fixture, dict):
        raise ValueError("G5A fixture metadata is required")
    source_hashes = source_identity.get("relevant_source_sha256", {})
    source_digest = hashlib.sha256(
        json.dumps(source_hashes, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "fixture": fixture,
        "identity": {
            "run_id": run_id,
            "source_head": source_identity.get("head"),
            "source_digest": source_digest,
            "seed_id": seed_id,
            "provider": "unknown",
            "model": "unknown",
            "configured_provider": None,
            "configured_model": None,
            "measurement_method": fixture.get("measurement_method", {}),
        },
        "capture_mode": "primary",
        "ally_prefetch_enabled": True,
        "receipts": [],
        "trace_windows": {"status": "pending"},
        "trace_attribution": {"status": "pending"},
    }


_G10_USAGE_MAX_EVENTS = 16
_G10_USAGE_MAX_DEBUG_UPDATES = 32
_G10_USAGE_MAX_REPORT_CHARS = 2048
_G10_USAGE_MAX_LINE_CHARS = 512
_G10_USAGE_MAX_VALUE = 10 ** 15
_G10_USAGE_SOURCE_ROUTE = "WebOutputCapture.game_output"
_G10_RECEIPT_SOURCE_IDS = frozenset({
    "utils/llm_router.py:llm_router.decide",
    "utils/llm_runtime.py:llm_runtime.call",
    "core/ai/adv_summary.py:adv_summary",
    "core/ai/cumulative_summary.py:cumulative_summary",
    "main.py:generate_module_summary",
    "core/memory/session_diary.py:_generate_rebuild_chapter_summary",
    "core/memory/session_diary.py:_generate_checkpoint_summary",
    "core/memory/players_diary.py:_generate_markdown_from_prompt",
    "core/memory/story_so_far_compiler.py:_generate_story_text_with_llm",
    "core/managers/campaign_manager.py:CampaignManager._generate_module_summary.summary",
    "core/managers/campaign_manager.py:CampaignManager._generate_module_summary.export_data",
    "utils/homebrewery_adventure_writer.py:_llm_intro_narrative",
    "utils/homebrewery_adventure_writer.py:_llm_plot_hook",
    "utils/homebrewery_adventure_writer.py:_llm_area_overview",
    "scripts/test_capture_g10.py:test_summary_producer",
    "tests/provider_free/test_llm_router.py:provider_free_test",
})
_G10_RESUME_STARTUP_SOURCES = {
    "session_diary_checkpoint_summary": {
        "site": "llm_router",
        "task": "summaries",
        "source_id": "core/memory/session_diary.py:_generate_checkpoint_summary",
    },
    "combat_reengage": {
        # _startup_provider_call in core/combat/bootstrap.py sets this exact
        # site only for context="re-engage" and calls task "combat_main".
        # That legacy source emits no G10 source_id; keep the pair exact.
        "site": "combat_reengage",
        "task": "combat_main",
        "source_id": None,
    },
}
_G10_TRACKER_LOG_NAME = "telemetry_log.jsonl"
_G10_TRACKER_MAX_BYTES = 8 * 1024 * 1024
_G10_TRACKER_MAX_LINES = 8192
_G10_TRACKER_MAX_LINE_BYTES = 64 * 1024
_G10_TRACKER_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,159}")
_G10_TRACKER_DIGEST_RE = re.compile(r"[0-9a-f]{64}")
_G10_USAGE_CAPTURE_ERRORS = {
    "usage_output_source_invalid", "usage_output_exceeds_bound",
    "usage_output_non_ascii", "usage_report_header_invalid",
    "usage_report_line_count_invalid", "usage_report_line_exceeds_bound",
    "usage_report_line_invalid", "usage_report_section_duplicate",
    "usage_report_section_missing", "usage_numeric_value_exceeds_bound",
    "usage_capture_error_invalid",
}


def _g10_unique_json_object(pairs: List[Tuple[str, Any]]) -> Dict[str, Any]:
    """Reject duplicate JSON keys rather than accepting json.loads last-wins."""
    result: Dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def _g10_tracker_window_days(state_root: Path) -> Optional[int]:
    """Read the tracker week-window literal from the isolated sandbox AST."""
    path = Path(state_root) / "model_config.py"
    raw, error = _safe_read_bytes(path, Path(state_root))
    if error or raw is None:
        return None
    try:
        tree = ast.parse(raw.decode("utf-8"))
    except (UnicodeError, SyntaxError):
        return None
    values = [node.value.value for node in tree.body if isinstance(node, ast.Assign)
              for target in node.targets if isinstance(target, ast.Name) and
              target.id == "USAGE_WEEK_WINDOW_DAYS" and
              isinstance(node.value, ast.Constant) and
              isinstance(node.value.value, int) and not isinstance(node.value.value, bool)]
    return values[0] if len(values) == 1 and 1 <= values[0] <= 31 else None


def _g10_tracker_timestamp(value: Any) -> Optional[Tuple[float, str]]:
    """Parse tracker ISO timestamps using the server's local-naive convention."""
    if not isinstance(value, str) or not value or len(value) > 64:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is not None:
            # The live tracker compares its naive local datetimes directly; an
            # offset-aware legacy row would be skipped during bootstrap.
            return None
        epoch = parsed.timestamp()
    except (OverflowError, OSError, TypeError, ValueError):
        return None
    if not math.isfinite(epoch) or epoch < 0 or epoch > 10 ** 12:
        return None
    return epoch, ("offset-aware" if parsed.tzinfo is not None else "local-naive")


def _g10_tracker_cost(value: Any) -> bool:
    return _g10_usage_value_bounded(value)


def _g10_tracker_project_row(row: Dict[str, Any], line_number: int,
                            raw_line: bytes) -> Tuple[Optional[Dict[str, Any]], Optional[str], float]:
    """Validate one tracker line and return only its sanitized public projection."""
    parsed_time = _g10_tracker_timestamp(row.get("timestamp"))
    if parsed_time is None:
        return None, "tracker_timestamp_invalid", 0.0
    timestamp, time_basis = parsed_time
    if row.get("type") == "spike_detected":
        tokens = row.get("tokens")
        if (not isinstance(tokens, int) or isinstance(tokens, bool) or
                tokens < 0 or tokens > _G10_USAGE_MAX_VALUE):
            return None, "tracker_spike_invalid", timestamp
        return ({"kind": "spike", "line_number": line_number,
                 "timestamp_epoch": timestamp, "timestamp_basis": time_basis,
                 "tokens": tokens}, None, timestamp)
    if row.get("type") is not None:
        return None, "tracker_event_type_unknown", timestamp

    tokens = (row.get("prompt_tokens"), row.get("completion_tokens"), row.get("total_tokens"))
    if any(not isinstance(value, int) or isinstance(value, bool) or
           value < 0 or value > _G10_USAGE_MAX_VALUE for value in tokens):
        return None, "tracker_token_counts_invalid", timestamp
    prompt, completion, sdk_total = tokens
    cost = row.get("cost_usd")
    cost_source = row.get("cost_source")
    cost_estimate = row.get("cost_estimate")
    context = row.get("context")
    if (not _g10_tracker_cost(cost) or not isinstance(cost_source, str) or
            not isinstance(cost_estimate, bool) or not isinstance(context, dict)):
        return None, "tracker_cost_or_context_invalid", timestamp

    image = row.get("image_metadata")
    source_line_digest = hashlib.sha256(raw_line).hexdigest()
    if image is not None:
        if (not isinstance(image, dict) or
                set(image) != {"model", "size", "quality"} or
                any(not isinstance(image.get(key), str) or
                    not image[key].isascii() or not image[key] or len(image[key]) > 80
                    for key in ("model", "size", "quality")) or
                (prompt, completion, sdk_total) != (0, 0, 0) or
                cost_source not in ("estimated", "unavailable") or
                cost_estimate is not True or
                (cost_source == "unavailable" and cost != 0)):
            return None, "tracker_image_event_invalid", timestamp
        event = {
            "kind": "image_cost", "line_number": line_number,
            "source_line_sha256": source_line_digest,
            "timestamp_epoch": timestamp, "timestamp_basis": time_basis,
            "prompt_tokens": 0, "completion_tokens": 0, "sdk_total_tokens": 0,
            "cost_usd": float(cost), "cost_source": cost_source,
            "cost_estimate": cost_estimate,
            "image_metadata": {key: image[key] for key in ("model", "size", "quality")},
        }
        return event, None, timestamp

    call_id = context.get("call_id")
    attempt_id = context.get("attempt_id")
    provenance = context.get("cost_provenance")
    context_cost = context.get("cost_usd")
    cost_complete = context.get("cost_complete")
    if (not isinstance(call_id, str) or not _G10_TRACKER_ID_RE.fullmatch(call_id) or
            not isinstance(attempt_id, str) or not _G10_TRACKER_ID_RE.fullmatch(attempt_id) or
            provenance not in ("actual", "estimated", "unpriced") or
            not isinstance(cost_complete, bool)):
        return None, "tracker_event_identity_unverifiable", timestamp
    source_by_provenance = {
        "actual": "provider_reported", "estimated": "estimated", "unpriced": "unpriced",
    }
    if cost_source != source_by_provenance[provenance]:
        return None, "tracker_cost_provenance_mismatch", timestamp
    if provenance == "unpriced":
        if (cost_complete or cost != 0 or context_cost is not None or
                cost_estimate is not True):
            return None, "tracker_unpriced_cost_invalid", timestamp
    elif (cost_complete is not True or not _g10_tracker_cost(context_cost) or
          abs(float(context_cost) - float(cost)) > 1e-12 or
          cost_estimate != (provenance == "estimated")):
        return None, "tracker_cost_provenance_mismatch", timestamp
    event = {
        "kind": "router_usage", "line_number": line_number,
        "source_line_sha256": source_line_digest,
        "timestamp_epoch": timestamp, "timestamp_basis": time_basis,
        "call_id": call_id, "attempt_id": attempt_id,
        "prompt_tokens": prompt, "completion_tokens": completion,
        "sdk_total_tokens": sdk_total,
        "cost_usd": float(cost), "cost_source": cost_source,
        "cost_provenance": provenance, "cost_complete": cost_complete,
        "cost_estimate": cost_estimate,
    }
    return event, None, timestamp


def _g10_tracker_parse_bytes(raw: bytes, captured_at: datetime,
                             window_days: int) -> Dict[str, Any]:
    """Parse a complete tracker snapshot; malformed rows are never skipped."""
    problems: List[str] = []
    if len(raw) > _G10_TRACKER_MAX_BYTES:
        return {"status": "BLOCKED", "problems": ["tracker_log_exceeds_bound"]}
    if raw and not raw.endswith(b"\n"):
        return {"status": "BLOCKED", "problems": ["tracker_log_unterminated_line"]}
    lines = raw.splitlines()
    if len(lines) > _G10_TRACKER_MAX_LINES:
        return {"status": "BLOCKED", "problems": ["tracker_log_line_count_exceeds_bound"]}
    cutoff = captured_at - timedelta(days=window_days)
    cutoff_epoch = cutoff.timestamp()
    captured_epoch = captured_at.timestamp()
    events: List[Dict[str, Any]] = []
    expired_lines: List[int] = []
    expired_event_refs: List[Dict[str, Any]] = []
    seen_attempts = set()
    seen_source_rows = set()
    for number, line in enumerate(lines, 1):
        if not line or len(line) > _G10_TRACKER_MAX_LINE_BYTES:
            problems.append("tracker_log_line_invalid")
            continue
        try:
            row = json.loads(line.decode("utf-8"), object_pairs_hook=_g10_unique_json_object)
        except (UnicodeError, ValueError):
            problems.append("tracker_log_malformed_json")
            continue
        if not isinstance(row, dict):
            problems.append("tracker_log_row_not_object")
            continue
        event, error, timestamp = _g10_tracker_project_row(row, number, line)
        if error:
            problems.append(error)
            continue
        if timestamp > captured_epoch + 2:
            problems.append("tracker_timestamp_in_future")
            continue
        if event is None:
            continue
        if event.get("kind") == "router_usage":
            attempt = event["attempt_id"]
            if attempt in seen_attempts:
                problems.append("tracker_duplicate_attempt_id")
            seen_attempts.add(attempt)
        if event.get("kind") in ("router_usage", "image_cost"):
            line_digest = event.get("source_line_sha256")
            if line_digest in seen_source_rows:
                problems.append("tracker_duplicate_event_row")
            seen_source_rows.add(line_digest)
        if timestamp < cutoff_epoch:
            expired_lines.append(number)
            if event.get("kind") in ("router_usage", "image_cost"):
                expired_event_refs.append({
                    "kind": event["kind"], "line_number": number,
                    "timestamp_epoch": timestamp,
                    "source_line_sha256": event["source_line_sha256"],
                })
        else:
            events.append(event)
    captured_iso = captured_at.isoformat()
    return {
        "status": "captured" if not problems else "BLOCKED",
        "problems": sorted(set(problems)),
        "captured_at_local": captured_iso,
        "captured_at_epoch": captured_epoch,
        "cutoff_local": cutoff.isoformat(),
        "cutoff_epoch": cutoff_epoch,
        "window_days": window_days,
        "line_count": len(lines),
        "expired_count": len(expired_lines),
        "expired_line_numbers": expired_lines,
        "expired_event_refs": expired_event_refs,
        "events": events,
    }


def capture_g10_tracker_snapshot(state_root: Path, *, allow_missing: bool = False,
                                 prefix_bytes: Optional[int] = None,
                                 prefix_sha256: Optional[str] = None) -> Dict[str, Any]:
    """Capture a stable, sanitized snapshot of the isolated legacy tracker log."""
    root = Path(state_root)
    path = root / _G10_TRACKER_LOG_NAME
    if (not _inside(root, PROJECT_TMP) or root.resolve() == PROJECT_TMP.resolve() or
            _has_symlink_component(root, PROJECT_TMP) or _has_symlink_component(path, root)):
        return {"status": "BLOCKED", "problems": ["tracker_path_unsafe"]}
    days = _g10_tracker_window_days(root)
    if days is None:
        return {"status": "BLOCKED", "problems": ["tracker_week_window_unverifiable"]}
    try:
        before_stat = path.stat()
        if not os.path.isfile(path) or before_stat.st_size > _G10_TRACKER_MAX_BYTES:
            return {"status": "BLOCKED", "problems": ["tracker_log_not_regular_or_exceeds_bound"]}
        raw, error = _safe_read_bytes(path, root)
        after_stat = path.stat()
        if (error or raw is None or before_stat.st_dev != after_stat.st_dev or
                before_stat.st_ino != after_stat.st_ino or before_stat.st_size != after_stat.st_size or
                before_stat.st_mtime_ns != after_stat.st_mtime_ns or len(raw) != after_stat.st_size or
                _has_symlink_component(path, root) or not os.path.isfile(path)):
            return {"status": "BLOCKED", "problems": ["tracker_snapshot_unstable"]}
        present = True
        device, inode = after_stat.st_dev, after_stat.st_ino
    except FileNotFoundError:
        if not allow_missing:
            return {"status": "BLOCKED", "problems": ["tracker_log_missing"]}
        raw, present, device, inode = b"", False, None, None
    except OSError:
        return {"status": "BLOCKED", "problems": ["tracker_snapshot_unreadable"]}
    captured_at = datetime.now()
    parsed = _g10_tracker_parse_bytes(raw, captured_at, days)
    prefix = None
    if prefix_bytes is not None:
        if (not isinstance(prefix_bytes, int) or isinstance(prefix_bytes, bool) or
                prefix_bytes < 0 or prefix_bytes > len(raw)):
            parsed["status"] = "BLOCKED"
            parsed["problems"] = sorted(set(parsed.get("problems", []) +
                                                ["tracker_prefix_invalid"]))
        else:
            observed_prefix = hashlib.sha256(raw[:prefix_bytes]).hexdigest()
            prefix = {"bytes": prefix_bytes, "sha256": observed_prefix,
                      "matches_expected": (prefix_sha256 is None or
                                           observed_prefix == prefix_sha256)}
            if prefix["matches_expected"] is not True:
                parsed["status"] = "BLOCKED"
                parsed["problems"] = sorted(set(parsed.get("problems", []) +
                                                    ["tracker_prefix_changed"]))
    return {
        **parsed,
        "source": {
            "path": _G10_TRACKER_LOG_NAME,
            "present": present,
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "device": device,
            "inode": inode,
            "prefix": prefix,
        },
    }


def capture_g10_tracker_boundary(state_root: Path, run_dir: Path, output_path: Path,
                                 phase: str, chain_id: str) -> Dict[str, Any]:
    """Capture the phase's exact pre-server tracker boundary and resume linkage."""
    root, run, output = Path(state_root), Path(run_dir), Path(output_path)
    if (phase not in ("complete", "resume") or
            not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", str(chain_id)) or
            not _inside(root, PROJECT_TMP) or root.resolve() != (PROJECT_TMP / "combat_capture").resolve() or
            _has_symlink_component(root, PROJECT_TMP) or
            not _inside(run, G10_RUN_ROOT) or run.resolve() == G10_RUN_ROOT.resolve() or
            _has_symlink_component(run, PROJECT_TMP) or
            not _inside(output, G10_RUN_ROOT) or _has_symlink_component(output, PROJECT_TMP) or
            output.exists() or output.is_symlink()):
        raise ValueError("G10 tracker boundary paths or identity are invalid")
    marker = read_sandbox_g10_marker(root)
    if (marker.get("status") != "ok" or marker.get("gate") != "g10" or
            marker.get("scenario_id") != "full-session" or marker.get("chain_id") != chain_id):
        raise ValueError("G10 tracker boundary cannot verify the seeded sandbox marker")
    try:
        sandbox_id = hashlib.sha256(str(root.resolve()).encode("utf-8")).hexdigest()
        marker_complete = Path(str(marker.get("complete_run_dir")))
        if not marker_complete.is_absolute():
            marker_complete = PROJECT_ROOT / marker_complete
        if not _inside(marker_complete, G10_RUN_ROOT) or _has_symlink_component(
                marker_complete, PROJECT_TMP):
            raise ValueError("unsafe_complete_run")
        expected_complete = str(marker_complete.resolve().relative_to(PROJECT_ROOT.resolve()))
        expected_run = str(run.resolve().relative_to(PROJECT_ROOT.resolve()))
    except (OSError, RuntimeError, ValueError) as exc:
        raise ValueError("G10 tracker boundary complete-run identity is unsafe") from exc
    if phase == "complete":
        if expected_complete != expected_run:
            raise ValueError("G10 complete tracker boundary differs from the seeded run")
        snapshot = capture_g10_tracker_snapshot(root, allow_missing=True)
        if (snapshot.get("status") != "captured" or
                snapshot.get("source", {}).get("present") is not False or
                snapshot.get("line_count") != 0 or snapshot.get("events") != []):
            raise ValueError("fresh G10 sandbox has an unexpected tracker baseline")
        prior_link = {
            "status": "fresh_sandbox_boundary",
            "baseline_source": "tracker_log_absent_after_seed",
            "baseline_numeric_totals": None,
        }
    else:
        complete_manifest, manifest_error = load_bundle_json(marker_complete, "manifest.json")
        complete_artifacts = (complete_manifest.get("artifacts")
                              if isinstance(complete_manifest, dict) else None)
        complete_ref = (complete_artifacts.get("g10_tracker_telemetry")
                        if isinstance(complete_artifacts, dict) else None)
        complete_artifact, artifact_error = load_bundle_json(marker_complete, complete_ref)
        complete_hashes = (complete_manifest.get("artifact_sha256", {})
                           if isinstance(complete_manifest, dict) else {})
        complete_artifact_path, complete_path_error = _bundle_file(
            marker_complete, complete_ref
        )
        complete_raw, complete_raw_error = (
            _safe_read_bytes(complete_artifact_path, marker_complete)
            if complete_artifact_path is not None else (None, complete_path_error)
        )
        terminal = (complete_artifact.get("post_shutdown")
                    if isinstance(complete_artifact, dict) else None)
        snapshot = capture_g10_tracker_snapshot(root)
        source = snapshot.get("source", {})
        terminal_source = terminal.get("source", {}) if isinstance(terminal, dict) else {}
        terminal_problems = _g10_tracker_snapshot_problems(terminal, "post_shutdown")
        baseline_problems = _g10_tracker_snapshot_problems(snapshot, "pre_run")
        terminal_time = terminal.get("captured_at_epoch") if isinstance(terminal, dict) else None
        baseline_time = snapshot.get("captured_at_epoch") if isinstance(snapshot, dict) else None
        if (manifest_error or artifact_error or complete_raw_error or complete_raw is None or
                not isinstance(complete_manifest, dict) or
                complete_manifest.get("gate") != "g10" or
                complete_manifest.get("run_id") != marker_complete.name or
                not isinstance(complete_artifacts, dict) or
                complete_ref != "g10_tracker_telemetry.json" or
                not isinstance(complete_artifact, dict) or
                complete_artifact.get("status") != "captured" or
                complete_hashes.get(complete_ref) != hashlib.sha256(complete_raw).hexdigest() or
                not isinstance(terminal, dict) or terminal.get("status") != "captured" or
                snapshot.get("status") != "captured" or
                terminal_problems or baseline_problems or
                terminal.get("window_days") != snapshot.get("window_days") or
                not _g10_usage_value_bounded(terminal_time, 10 ** 12) or
                not _g10_usage_value_bounded(baseline_time, 10 ** 12) or
                baseline_time < terminal_time or
                source.get("sha256") != terminal_source.get("sha256") or
                source.get("bytes") != terminal_source.get("bytes") or
                complete_artifact.get("run_id") != marker_complete.name or
                complete_artifact.get("chain_id") != chain_id or
                complete_artifact.get("seed_id") != marker.get("seed_id") or
                complete_artifact.get("sandbox_id") != sandbox_id or
                complete_artifact.get("phase") != "complete"):
            raise ValueError("G10 resume tracker baseline does not match the finalized complete log")
        prior_link = {
            "status": "linked_complete_boundary",
            "complete_run_dir": expected_complete,
            "complete_artifact": str(complete_ref),
            "complete_artifact_sha256": hashlib.sha256(complete_raw).hexdigest(),
            "complete_terminal_source_sha256": terminal_source.get("sha256"),
            "complete_terminal_source_bytes": terminal_source.get("bytes"),
        }
    boundary = {
        "status": "captured" if snapshot.get("status") == "captured" else "BLOCKED",
        "phase": phase, "run_id": run.name, "chain_id": chain_id,
        "seed_id": marker.get("seed_id"), "sandbox_id": sandbox_id,
        "party_size": marker.get("party_size"),
        "marker_sha256": marker.get("sha256"),
        "complete_run_dir": expected_complete,
        "snapshot": snapshot,
        "prior_link": prior_link,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as handle:
        json.dump(boundary, handle, ensure_ascii=True, sort_keys=True, indent=2)
        handle.write("\n")
    return boundary


def _g10_tracker_rollup(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    usage_events = [row for row in events if isinstance(row, dict) and
                    row.get("kind") in ("router_usage", "image_cost")]
    actual = sum(float(row["cost_usd"]) for row in usage_events
                 if row.get("cost_source") == "provider_reported")
    estimated = sum(float(row["cost_usd"]) for row in usage_events
                    if row.get("cost_source") == "estimated")
    unpriced = sum(1 for row in usage_events if row.get("cost_source") == "unpriced")
    incomplete = any(row.get("cost_source") in ("unpriced", "unavailable")
                     for row in usage_events)
    return {
        "tokens": sum(row["sdk_total_tokens"] for row in usage_events),
        "actual_usd": actual, "estimated_usd": estimated,
        "known_cost_usd": actual + estimated, "unpriced_calls": unpriced,
        "cost_coverage": "incomplete" if incomplete else "complete",
        "event_count": len(usage_events),
        "router_event_count": sum(row.get("kind") == "router_usage" for row in usage_events),
        "image_event_count": sum(row.get("kind") == "image_cost" for row in usage_events),
    }


def _g10_tracker_snapshot_problems(snapshot: Any, label: str) -> List[str]:
    """Validate the complete sanitized snapshot envelope before using its rows."""
    if not isinstance(snapshot, dict) or snapshot.get("status") != "captured":
        return ["g10_tracker_%s_snapshot_missing" % label]
    source = snapshot.get("source")
    problems: List[str] = []
    if (not isinstance(source, dict) or source.get("path") != _G10_TRACKER_LOG_NAME or
            snapshot.get("problems") != [] or type(source.get("present")) is not bool or
            type(source.get("bytes")) is not int or source.get("bytes") < 0 or
            source.get("bytes") > _G10_TRACKER_MAX_BYTES or
            not isinstance(source.get("sha256"), str) or
            not _G10_TRACKER_DIGEST_RE.fullmatch(source.get("sha256", "")) or
            type(snapshot.get("line_count")) is not int or
            not 0 <= snapshot.get("line_count", -1) <= _G10_TRACKER_MAX_LINES or
            type(snapshot.get("window_days")) is not int or
            not 1 <= snapshot.get("window_days", 0) <= 31 or
            not _g10_usage_value_bounded(snapshot.get("captured_at_epoch"), 10 ** 12) or
            not _g10_usage_value_bounded(snapshot.get("cutoff_epoch"), 10 ** 12) or
            not isinstance(snapshot.get("events"), list) or
            not isinstance(snapshot.get("expired_line_numbers"), list) or
            type(snapshot.get("expired_count")) is not int or
            snapshot.get("expired_count") != len(snapshot.get("expired_line_numbers", [])) or
            not isinstance(snapshot.get("expired_event_refs"), list)):
        return ["g10_tracker_%s_snapshot_invalid" % label]
    if (source.get("present") is False and
            (source.get("bytes") != 0 or snapshot.get("line_count") != 0 or
             snapshot.get("events") != [] or snapshot.get("expired_line_numbers") != [] or
             snapshot.get("expired_event_refs") != [] or
             source.get("device") is not None or source.get("inode") is not None)):
        problems.append("g10_tracker_%s_absent_source_contradictory" % label)
    if source.get("present") is True and any(
            not isinstance(source.get(field), int) or isinstance(source.get(field), bool) or
            source.get(field) < 0 for field in ("device", "inode")):
        problems.append("g10_tracker_%s_file_identity_invalid" % label)

    try:
        captured_local = datetime.fromisoformat(snapshot.get("captured_at_local", ""))
        cutoff_local = datetime.fromisoformat(snapshot.get("cutoff_local", ""))
        expected_captured = captured_local.timestamp()
        expected_cutoff = cutoff_local.timestamp()
    except (OverflowError, OSError, TypeError, ValueError):
        problems.append("g10_tracker_%s_local_time_invalid" % label)
    else:
        if (captured_local.tzinfo is not None or cutoff_local.tzinfo is not None or
                abs(expected_captured - snapshot["captured_at_epoch"]) > 0.001 or
                abs(expected_cutoff - snapshot["cutoff_epoch"]) > 0.001 or
                cutoff_local != captured_local - timedelta(days=snapshot["window_days"])):
            problems.append("g10_tracker_%s_cutoff_binding_invalid" % label)

    all_lines: List[int] = []
    seen_event_digests = set()
    seen_attempt_ids = set()
    for event in snapshot["events"]:
        if not isinstance(event, dict):
            problems.append("g10_tracker_%s_event_invalid" % label)
            continue
        kind = event.get("kind")
        line = event.get("line_number")
        timestamp = event.get("timestamp_epoch")
        timestamp_ok = (_g10_usage_value_bounded(timestamp, 10 ** 12) and
                        snapshot["cutoff_epoch"] <= timestamp <=
                        snapshot["captured_at_epoch"] + 2)
        if (not isinstance(line, int) or isinstance(line, bool) or
                not 1 <= line <= snapshot["line_count"] or not timestamp_ok or
                event.get("timestamp_basis") != "local-naive"):
            problems.append("g10_tracker_%s_event_invalid" % label)
            continue
        all_lines.append(line)
        if kind == "spike":
            if (set(event) != {"kind", "line_number", "timestamp_epoch",
                               "timestamp_basis", "tokens"} or
                    not isinstance(event.get("tokens"), int) or isinstance(event.get("tokens"), bool) or
                    not 0 <= event["tokens"] <= _G10_USAGE_MAX_VALUE):
                problems.append("g10_tracker_%s_spike_invalid" % label)
            continue
        if kind == "router_usage":
            expected_keys = {
                "kind", "line_number", "source_line_sha256", "timestamp_epoch",
                "timestamp_basis", "call_id", "attempt_id", "prompt_tokens",
                "completion_tokens", "sdk_total_tokens", "cost_usd", "cost_source",
                "cost_provenance", "cost_complete", "cost_estimate",
            }
            digest = event.get("source_line_sha256")
            attempt = event.get("attempt_id")
            tokens_ok = all(isinstance(event.get(field), int) and
                            not isinstance(event.get(field), bool) and
                            0 <= event[field] <= _G10_USAGE_MAX_VALUE
                            for field in ("prompt_tokens", "completion_tokens", "sdk_total_tokens"))
            provenance = event.get("cost_provenance")
            expected_source = ({"actual": "provider_reported", "estimated": "estimated",
                                "unpriced": "unpriced"}.get(provenance)
                               if isinstance(provenance, str) else None)
            cost_ok = (_g10_usage_value_bounded(event.get("cost_usd")) and
                       event.get("cost_source") == expected_source and
                       type(event.get("cost_complete")) is bool and
                       type(event.get("cost_estimate")) is bool)
            if (set(event) != expected_keys or not isinstance(event.get("call_id"), str) or
                    not _G10_TRACKER_ID_RE.fullmatch(event.get("call_id", "")) or
                    not isinstance(attempt, str) or not _G10_TRACKER_ID_RE.fullmatch(attempt) or
                    not isinstance(digest, str) or not _G10_TRACKER_DIGEST_RE.fullmatch(digest) or
                    not tokens_ok or not cost_ok or provenance not in ("actual", "estimated", "unpriced") or
                    (provenance == "unpriced" and
                     (event["cost_usd"] != 0 or event["cost_complete"] or
                      not event["cost_estimate"])) or
                    (provenance == "actual" and
                     (not event["cost_complete"] or event["cost_estimate"])) or
                    (provenance == "estimated" and
                     (not event["cost_complete"] or not event["cost_estimate"]))):
                problems.append("g10_tracker_%s_router_event_invalid" % label)
            if isinstance(attempt, str):
                if attempt in seen_attempt_ids:
                    problems.append("g10_tracker_%s_duplicate_attempt_id" % label)
                seen_attempt_ids.add(attempt)
        elif kind == "image_cost":
            expected_keys = {
                "kind", "line_number", "source_line_sha256", "timestamp_epoch",
                "timestamp_basis", "prompt_tokens", "completion_tokens",
                "sdk_total_tokens", "cost_usd", "cost_source", "cost_estimate",
                "image_metadata",
            }
            image = event.get("image_metadata")
            if (set(event) != expected_keys or
                    not isinstance(event.get("source_line_sha256"), str) or
                    not _G10_TRACKER_DIGEST_RE.fullmatch(event.get("source_line_sha256", "")) or
                    any(not isinstance(event.get(field), int) or
                        isinstance(event.get(field), bool) or event[field] != 0 for field in
                        ("prompt_tokens", "completion_tokens", "sdk_total_tokens")) or
                    not _g10_usage_value_bounded(event.get("cost_usd")) or
                    event.get("cost_source") not in ("estimated", "unavailable") or
                    event.get("cost_estimate") is not True or
                    (event.get("cost_source") == "unavailable" and event.get("cost_usd") != 0) or
                    not isinstance(image, dict) or set(image) != {"model", "size", "quality"} or
                    any(not isinstance(image.get(field), str) or not image[field] or
                        not image[field].isascii() or len(image[field]) > 80
                        for field in ("model", "size", "quality"))):
                problems.append("g10_tracker_%s_image_event_invalid" % label)
        else:
            problems.append("g10_tracker_%s_event_kind_invalid" % label)
        digest = event.get("source_line_sha256")
        if isinstance(digest, str) and digest in seen_event_digests:
            problems.append("g10_tracker_%s_duplicate_event_row" % label)
        if isinstance(digest, str):
            seen_event_digests.add(digest)

    expired_lines = snapshot["expired_line_numbers"]
    if (any(not isinstance(line, int) or isinstance(line, bool) or
            not 1 <= line <= snapshot["line_count"] for line in expired_lines) or
            expired_lines != sorted(set(expired_lines))):
        problems.append("g10_tracker_%s_expired_lines_invalid" % label)
        expired_lines = []
    all_lines.extend(expired_lines)
    if sorted(all_lines) != list(range(1, snapshot["line_count"] + 1)):
        problems.append("g10_tracker_%s_line_coverage_invalid" % label)

    expired_digests = set()
    for event in snapshot["expired_event_refs"]:
        if not isinstance(event, dict):
            problems.append("g10_tracker_%s_expired_event_invalid" % label)
            continue
        line, timestamp, digest = (event.get("line_number"), event.get("timestamp_epoch"),
                                   event.get("source_line_sha256"))
        if (set(event) != {"kind", "line_number", "timestamp_epoch", "source_line_sha256"} or
                event.get("kind") not in ("router_usage", "image_cost") or
                not isinstance(line, int) or isinstance(line, bool) or line not in expired_lines or
                not _g10_usage_value_bounded(timestamp, 10 ** 12) or
                timestamp >= snapshot["cutoff_epoch"] or not isinstance(digest, str) or
                not _G10_TRACKER_DIGEST_RE.fullmatch(digest) or digest in seen_event_digests or
                digest in expired_digests):
            problems.append("g10_tracker_%s_expired_event_invalid" % label)
        else:
            expired_digests.add(digest)

    prefix = source.get("prefix")
    if label == "pre_run":
        if prefix is not None:
            problems.append("g10_tracker_pre_run_prefix_unexpected")
    elif (not isinstance(prefix, dict) or
          set(prefix) != {"bytes", "sha256", "matches_expected"} or
          not isinstance(prefix.get("bytes"), int) or isinstance(prefix.get("bytes"), bool) or
          not 0 <= prefix["bytes"] <= source["bytes"] or
          not isinstance(prefix.get("sha256"), str) or
          not _G10_TRACKER_DIGEST_RE.fullmatch(prefix.get("sha256", "")) or
          prefix.get("matches_expected") is not True):
        problems.append("g10_tracker_%s_prefix_invalid" % label)
    return sorted(set(problems))


def project_g10_tracker_telemetry(artifact: Any, usage: Dict[str, Any],
                                  receipts: Dict[str, Any]) -> Dict[str, Any]:
    """Re-derive G10 session/week totals from sanitized append-only tracker evidence."""
    problems: List[str] = []
    if not isinstance(artifact, dict):
        return {"status": "BLOCKED", "problems": ["g10_tracker_artifact_missing"]}
    phase = artifact.get("phase")
    pre = artifact.get("pre_run")
    post = artifact.get("post_usage")
    terminal = artifact.get("post_shutdown")
    if (artifact.get("schema_version") != 1 or artifact.get("status") != "captured" or
            not isinstance(artifact.get("run_id"), str) or
            not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}",
                             artifact.get("run_id", "")) or
            not isinstance(artifact.get("chain_id"), str) or
            not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}",
                             artifact.get("chain_id", "")) or
            not isinstance(artifact.get("seed_id"), str) or not artifact.get("seed_id") or
            not isinstance(artifact.get("sandbox_id"), str) or
            not _G10_TRACKER_DIGEST_RE.fullmatch(artifact.get("sandbox_id", ""))):
        problems.append("g10_tracker_artifact_identity_invalid")
    if phase not in ("complete", "resume"):
        problems.append("g10_tracker_phase_invalid")
    for label, snapshot in (("pre_run", pre), ("post_usage", post),
                            ("post_shutdown", terminal)):
        problems.extend(_g10_tracker_snapshot_problems(snapshot, label))
    if problems:
        return {"status": "BLOCKED", "problems": sorted(set(problems))}

    pre_source, post_source, terminal_source = (
        pre["source"], post["source"], terminal["source"]
    )
    if (pre_source.get("present") not in (True, False) or
            (phase == "complete" and (pre_source.get("present") is not False or
                                      pre_source.get("bytes") != 0 or pre["events"] != [])) or
            (phase == "resume" and pre_source.get("present") is not True) or
            post_source.get("present") is not True or terminal_source.get("present") is not True):
        problems.append("g10_tracker_baseline_source_invalid")
    post_prefix = post_source.get("prefix")
    terminal_prefix = terminal_source.get("prefix")
    if (not isinstance(post_prefix, dict) or post_prefix.get("bytes") != pre_source.get("bytes") or
            post_prefix.get("sha256") != pre_source.get("sha256") or
            post_prefix.get("matches_expected") is not True):
        problems.append("g10_tracker_pre_run_prefix_mismatch")
    if (not isinstance(terminal_prefix, dict) or
            terminal_prefix.get("bytes") != post_source.get("bytes") or
            terminal_prefix.get("sha256") != post_source.get("sha256") or
            terminal_prefix.get("matches_expected") is not True):
        problems.append("g10_tracker_post_usage_prefix_mismatch")
    if (terminal_source.get("bytes") != post_source.get("bytes") or
            terminal_source.get("sha256") != post_source.get("sha256")):
        problems.append("g10_tracker_async_events_after_usage")
    if (pre.get("window_days") != post.get("window_days") or
            post.get("window_days") != terminal.get("window_days") or
            not pre.get("captured_at_epoch", 0) <= post.get("captured_at_epoch", 0) <=
            terminal.get("captured_at_epoch", 0)):
        problems.append("g10_tracker_snapshot_time_order_invalid")
    if (post_source.get("bytes", -1) < pre_source.get("bytes", 0) or
            terminal_source.get("bytes", -1) < post_source.get("bytes", 0) or
            post.get("line_count", -1) < pre.get("line_count", 0) or
            terminal.get("line_count", -1) < post.get("line_count", 0)):
        problems.append("g10_tracker_snapshot_not_append_only")
    if pre_source.get("present") is True and (
            post_source.get("device") != pre_source.get("device") or
            post_source.get("inode") != pre_source.get("inode") or
            terminal_source.get("device") != post_source.get("device") or
            terminal_source.get("inode") != post_source.get("inode")):
        problems.append("g10_tracker_file_identity_changed")
    prior_link = artifact.get("prior_link")
    if phase == "complete":
        if (not isinstance(prior_link, dict) or
                prior_link.get("status") != "fresh_sandbox_boundary" or
                prior_link.get("baseline_source") != "tracker_log_absent_after_seed" or
                prior_link.get("baseline_numeric_totals") is not None):
            problems.append("g10_tracker_fresh_boundary_link_invalid")
    else:
        if (not isinstance(prior_link, dict) or
                prior_link.get("status") != "linked_complete_boundary" or
                prior_link.get("complete_artifact") != "g10_tracker_telemetry.json" or
                not isinstance(prior_link.get("complete_run_dir"), str) or
                not isinstance(prior_link.get("complete_artifact_sha256"), str) or
                not _G10_TRACKER_DIGEST_RE.fullmatch(
                    prior_link.get("complete_artifact_sha256", "")) or
                prior_link.get("complete_terminal_source_sha256") != pre_source.get("sha256") or
                prior_link.get("complete_terminal_source_bytes") != pre_source.get("bytes")):
            problems.append("g10_tracker_complete_boundary_link_invalid")

    pre_lines = pre.get("line_count")
    post_events = post.get("events")
    session_events = [row for row in post_events if isinstance(row, dict) and
                      row.get("kind") in ("router_usage", "image_cost") and
                      isinstance(row.get("line_number"), int) and
                      row.get("line_number") > pre_lines]
    expired_new = [line for line in post.get("expired_line_numbers", [])
                   if isinstance(line, int) and line > pre_lines]
    if expired_new:
        problems.append("g10_tracker_new_session_event_expired")
    if any(row.get("timestamp_epoch", 0) < pre.get("captured_at_epoch", 0)
           for row in session_events):
        problems.append("g10_tracker_event_predates_baseline")
    launch_epoch = artifact.get("server_launch_epoch")
    if (not _g10_usage_value_bounded(launch_epoch, 10 ** 12) or
            not pre.get("captured_at_epoch", 0) <= launch_epoch <= post.get("captured_at_epoch", 0)):
        problems.append("g10_tracker_server_launch_time_missing_or_invalid")
    elif any(row.get("timestamp_epoch", 0) < launch_epoch
             for row in session_events):
        problems.append("g10_tracker_event_predates_server_launch")

    usage_interval = artifact.get("usage_interval")
    token_update = (usage.get("token_update") if isinstance(usage, dict) else None)
    usage_events = usage.get("usage_events", []) if isinstance(usage, dict) else []
    sent_at = usage_interval.get("command_sent_epoch") if isinstance(usage_interval, dict) else None
    output_at = usage_events[0].get("source_event_ts") if len(usage_events) == 1 and isinstance(
        usage_events[0], dict) else None
    update_at = token_update.get("ts") if isinstance(token_update, dict) else None
    if (not all(_g10_usage_value_bounded(value, 10 ** 12)
                for value in (sent_at, output_at, update_at)) or
            not sent_at <= output_at <= update_at <= post.get("captured_at_epoch", 0)):
        problems.append("g10_tracker_usage_interval_unverifiable")
    else:
        # A tracker append during /usage cannot be ordered relative to its stats read.
        if any(sent_at <= row.get("timestamp_epoch", -1) <= update_at
               for row in session_events):
            problems.append("g10_tracker_event_overlaps_usage_snapshot")
        if any(row.get("timestamp_epoch", 0) > update_at
               for row in session_events):
            problems.append("g10_tracker_event_after_usage_report")
        cutoff_start = (datetime.fromtimestamp(sent_at) -
                        timedelta(days=post["window_days"])).timestamp()
        cutoff_end = (datetime.fromtimestamp(post["captured_at_epoch"]) -
                      timedelta(days=post["window_days"])).timestamp()
        low, high = sorted((cutoff_start, cutoff_end))
        all_week_timestamps = [row.get("timestamp_epoch", -1)
                               for row in post_events if isinstance(row, dict) and
                               row.get("kind") in ("router_usage", "image_cost")]
        all_week_timestamps.extend(
            row.get("timestamp_epoch", -1)
            for row in post.get("expired_event_refs", []) if isinstance(row, dict)
        )
        if any(low <= timestamp <= high for timestamp in all_week_timestamps):
            problems.append("g10_tracker_week_cutoff_event_ambiguous")

    session_rollup = _g10_tracker_rollup(session_events)
    week_rollup = _g10_tracker_rollup(
        [row for row in post_events if isinstance(row, dict) and
         row.get("kind") in ("router_usage", "image_cost")]
    )
    sections = usage.get("sections", {}) if isinstance(usage, dict) else {}
    for label, rollup in (("session", session_rollup), ("week", week_rollup)):
        section = sections.get(label) if isinstance(sections, dict) else None
        if not isinstance(section, dict):
            problems.append("g10_tracker_%s_usage_section_missing" % label)
            continue
        if section.get("tokens") != rollup["tokens"]:
            problems.append("g10_tracker_%s_tokens_mismatch" % label)
        for field in ("actual_usd", "estimated_usd", "known_cost_usd"):
            if (not _finite_number(section.get(field)) or
                    abs(float(section[field]) - float(rollup[field])) > 0.000001):
                problems.append("g10_tracker_%s_%s_mismatch" % (label, field))
        if section.get("unpriced_calls") != rollup["unpriced_calls"]:
            problems.append("g10_tracker_%s_unpriced_calls_mismatch" % label)
        if section.get("cost_coverage") != rollup["cost_coverage"]:
            problems.append("g10_tracker_%s_cost_coverage_mismatch" % label)

    receipt_rows = receipts.get("receipts", []) if isinstance(receipts, dict) else []
    receipt_by_attempt = {row.get("attempt_id"): row for row in receipt_rows
                          if isinstance(row, dict) and row.get("outcome") == "response"}
    tracker_router_events = [row for row in session_events if row.get("kind") == "router_usage"]
    tracker_by_attempt = {row.get("attempt_id"): row for row in tracker_router_events}
    if (len(tracker_by_attempt) != len(tracker_router_events) or
            set(tracker_by_attempt) != set(receipt_by_attempt)):
        problems.append("g10_tracker_router_receipt_identity_set_mismatch")
    for attempt, event in tracker_by_attempt.items():
        receipt = receipt_by_attempt.get(attempt)
        if not isinstance(receipt, dict):
            continue
        label_to_source = {"actual": "provider_reported", "estimated": "estimated",
                           "unpriced_unknown": "unpriced"}
        if (event.get("call_id") != receipt.get("call_id") or
                event.get("prompt_tokens") != receipt.get("prompt_tokens") or
                event.get("completion_tokens") != receipt.get("completion_tokens") or
                event.get("sdk_total_tokens") != receipt.get("sdk_total_tokens") or
                event.get("cost_source") != label_to_source.get(receipt.get("cost_label")) or
                (event.get("cost_source") in ("provider_reported", "estimated") and
                 (not _finite_number(receipt.get("cost_usd")) or
                  abs(float(event.get("cost_usd")) - float(receipt["cost_usd"])) > 1e-12))):
            problems.append("g10_tracker_receipt_fields_mismatch")

    return {
        "status": "ok" if not problems else "BLOCKED",
        "problems": sorted(set(problems)),
        "pre_run_source": {key: pre_source.get(key) for key in ("present", "bytes", "sha256")},
        "post_usage_source": {key: post_source.get(key) for key in ("bytes", "sha256")},
        "post_shutdown_source": {key: terminal_source.get(key) for key in ("bytes", "sha256")},
        "session": session_rollup, "week": week_rollup,
        "session_router_attempt_ids": sorted(tracker_by_attempt),
        "receipt_attempt_ids": sorted(receipt_by_attempt),
    }


def _g10_usage_value_bounded(value: Any, maximum: float = _G10_USAGE_MAX_VALUE) -> bool:
    """Accept only finite nonnegative usage values within the evidence bound."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    if isinstance(value, int):
        return 0 <= value <= maximum
    return math.isfinite(value) and 0 <= value <= maximum


def _g10_usage_source_reference(event: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """Project a usage event's socket provenance without retaining payload text."""
    event_index = event.get("source_event_index")
    driver_step = event.get("driver_step")
    event_ts = event.get("source_event_ts")
    index_valid = (isinstance(event_index, int) and not isinstance(event_index, bool) and
                   1 <= event_index <= 10 ** 9)
    step_valid = (isinstance(driver_step, int) and not isinstance(driver_step, bool) and
                  1 <= driver_step <= 10 ** 6)
    timestamp_valid = _g10_usage_value_bounded(event_ts, maximum=10 ** 12)
    source_valid = (
        event.get("source_event") == "game_output" and
        event.get("source_route") == _G10_USAGE_SOURCE_ROUTE and
        event.get("type") == "narration" and index_valid and step_valid and timestamp_valid
    )
    reference = {
        "source_event": "game_output" if event.get("source_event") == "game_output" else "invalid",
        "source_route": (_G10_USAGE_SOURCE_ROUTE
                         if event.get("source_route") == _G10_USAGE_SOURCE_ROUTE else "invalid"),
        "source_event_index": event_index if index_valid else None,
        "type": "narration" if event.get("type") == "narration" else "invalid",
        "driver_step": driver_step if step_valid else None,
        "source_event_ts": float(event_ts) if timestamp_valid else None,
    }
    return reference, ([] if source_valid else ["usage_output_source_invalid"])


def _render_g10_usage_report(sections: Dict[str, Dict[str, Any]]) -> str:
    """Render only the validated fixed usage schema for durable evidence."""
    router = sections["router"]
    session = sections["session"]
    week = sections["week"]

    def count(value: int) -> str:
        return format(value, ",d")

    def cost(value: float) -> str:
        return "$%s USD" % format(value, ",.6f")

    return (
        "[SYSTEM] Usage:\n"
        "  Router: calls %s; tokens %s (prompt %s, cached %s, completion %s); "
        "known cost %s; unpriced calls %s; cost coverage %s.\n"
        "  Session: tokens %s; actual %s; estimated %s; known cost %s; "
        "unpriced calls %s; cost coverage %s.\n"
        "  Rolling week: tokens %s; actual %s; estimated %s; known cost %s; "
        "unpriced calls %s; cost coverage %s."
    ) % (
        count(router["calls"]), count(router["tokens"]), count(router["prompt_tokens"]),
        count(router["cached_tokens"]), count(router["completion_tokens"]),
        cost(router["known_cost_usd"]), count(router["unpriced_calls"]),
        router["cost_coverage"], count(session["tokens"]), cost(session["actual_usd"]),
        cost(session["estimated_usd"]), cost(session["known_cost_usd"]),
        count(session["unpriced_calls"]), session["cost_coverage"], count(week["tokens"]),
        cost(week["actual_usd"]), cost(week["estimated_usd"]), cost(week["known_cost_usd"]),
        count(week["unpriced_calls"]), week["cost_coverage"],
    )


def project_g10_usage_observations(debug_events: Any, token_updates: Any) -> Dict[str, Any]:
    """Parse bounded WebOutputCapture usage events and Debug cost observations."""
    count_pattern = r"(0|[1-9][0-9]{0,2}(?:,[0-9]{3})*)"
    cost_pattern = r"\$((?:0|[1-9][0-9]{0,2})(?:,[0-9]{3})*\.[0-9]{6})\s+USD"
    router_pattern = re.compile(
        r"Router:\s*calls\s+" + count_pattern + r";\s*tokens\s+" + count_pattern +
        r"\s+\(prompt\s+" + count_pattern + r",\s*cached\s+" + count_pattern +
        r",\s*completion\s+" + count_pattern + r"\);\s*known cost\s+" + cost_pattern +
        r";\s*unpriced calls\s+" + count_pattern +
        r";\s*cost coverage\s+(complete|incomplete|unknown)\.")
    session_pattern = re.compile(
        r"Session:\s*tokens\s+" + count_pattern + r";\s*actual\s+" + cost_pattern +
        r";\s*estimated\s+" + cost_pattern + r";\s*known cost\s+" + cost_pattern +
        r";\s*unpriced calls\s+" + count_pattern +
        r";\s*cost coverage\s+(complete|incomplete|unknown)\.")
    week_pattern = re.compile(
        r"Rolling week:\s*tokens\s+" + count_pattern + r";\s*actual\s+" + cost_pattern +
        r";\s*estimated\s+" + cost_pattern + r";\s*known cost\s+" + cost_pattern +
        r";\s*unpriced calls\s+" + count_pattern +
        r";\s*cost coverage\s+(complete|incomplete|unknown)\.")

    problems: List[str] = []
    sections: Dict[str, Dict[str, Any]] = {}
    sanitized_events: List[Dict[str, Any]] = []
    usage_event_count = 0
    events = debug_events if isinstance(debug_events, list) else []
    for event in events:
        if not isinstance(event, dict):
            continue
        content = event.get("content")
        stored_errors = event.get("capture_error")
        is_stored_failure = content is None and isinstance(stored_errors, list)
        if not is_stored_failure and (not isinstance(content, str) or
                                      "[SYSTEM] Usage" not in content):
            continue
        usage_event_count += 1
        if usage_event_count > _G10_USAGE_MAX_EVENTS:
            problems.append("usage_observation_exceeds_bound")
            continue

        source_ref, source_errors = _g10_usage_source_reference(event)
        event_errors = list(source_errors)
        event_sections: Dict[str, Dict[str, Any]] = {}
        if is_stored_failure:
            stored = [code for code in stored_errors if isinstance(code, str) and
                      code in _G10_USAGE_CAPTURE_ERRORS]
            if not stored or len(stored) != len(stored_errors):
                event_errors.append("usage_capture_error_invalid")
            event_errors.extend(stored)
        elif not isinstance(content, str):
            event_errors.append("usage_report_line_invalid")
        elif len(content) > _G10_USAGE_MAX_REPORT_CHARS:
            event_errors.append("usage_output_exceeds_bound")
        elif not content.isascii():
            event_errors.append("usage_output_non_ascii")
        elif not source_errors:
            lines = content.splitlines()
            if not lines or lines[0] != "[SYSTEM] Usage:":
                event_errors.append("usage_report_header_invalid")
            if len(lines) != 4:
                event_errors.append("usage_report_line_count_invalid")
            if len(lines) == 4 and lines[0] == "[SYSTEM] Usage:":
                for raw_line in lines[1:]:
                    if len(raw_line) > _G10_USAGE_MAX_LINE_CHARS:
                        event_errors.append("usage_report_line_exceeds_bound")
                        continue
                    line = raw_line.strip()
                    router = router_pattern.fullmatch(line)
                    session = session_pattern.fullmatch(line)
                    week = week_pattern.fullmatch(line)
                    matches = [
                        ("router", router), ("session", session), ("week", week),
                    ]
                    matched = [(name, match) for name, match in matches if match is not None]
                    if len(matched) != 1:
                        event_errors.append("usage_report_line_invalid")
                        continue
                    name, match = matched[0]
                    if name in event_sections:
                        event_errors.append("usage_report_section_duplicate")
                        continue
                    if name == "router":
                        row = {
                            "calls": int(match.group(1).replace(",", "")),
                            "tokens": int(match.group(2).replace(",", "")),
                            "prompt_tokens": int(match.group(3).replace(",", "")),
                            "cached_tokens": int(match.group(4).replace(",", "")),
                            "completion_tokens": int(match.group(5).replace(",", "")),
                            "known_cost_usd": float(match.group(6).replace(",", "")),
                            "unpriced_calls": int(match.group(7).replace(",", "")),
                            "cost_coverage": match.group(8).casefold(),
                        }
                        bounded_numbers = [
                            row[key] for key in (
                                "calls", "tokens", "prompt_tokens", "cached_tokens",
                                "completion_tokens", "unpriced_calls", "known_cost_usd",
                            )
                        ]
                    else:
                        row = {
                            "tokens": int(match.group(1).replace(",", "")),
                            "actual_usd": float(match.group(2).replace(",", "")),
                            "estimated_usd": float(match.group(3).replace(",", "")),
                            "known_cost_usd": float(match.group(4).replace(",", "")),
                            "unpriced_calls": int(match.group(5).replace(",", "")),
                            "cost_coverage": match.group(6).casefold(),
                        }
                        bounded_numbers = [row[key] for key in (
                            "tokens", "actual_usd", "estimated_usd", "known_cost_usd",
                            "unpriced_calls",
                        )]
                    if any(not _g10_usage_value_bounded(value) for value in bounded_numbers):
                        event_errors.append("usage_numeric_value_exceeds_bound")
                    event_sections[name] = row
                if set(event_sections) != {"router", "session", "week"}:
                    event_errors.append("usage_report_section_missing")

        if event_errors:
            event_row = dict(source_ref)
            event_row["capture_error"] = sorted(set(event_errors))
            sanitized_events.append(event_row)
            problems.extend(event_errors)
            continue

        for name, row in event_sections.items():
            if name in sections:
                problems.append("usage_report_section_duplicate")
            else:
                sections[name] = row
        event_row = dict(source_ref)
        event_row["content"] = _render_g10_usage_report(event_sections)
        sanitized_events.append(event_row)

    if usage_event_count != 1:
        problems.append("usage_output_missing_or_duplicated")
    required_sections = ("router", "session", "week")
    for name in required_sections:
        row = sections.get(name)
        if not isinstance(row, dict):
            problems.append("%s_usage_section_missing_or_incomplete" % name)
            continue
        if name != "router" and not all(key in row for key in ("actual_usd", "estimated_usd")):
            problems.append("%s_usage_cost_components_missing" % name)
        if row.get("cost_coverage") not in ("complete", "incomplete"):
            problems.append("%s_usage_cost_coverage_unknown" % name)
        if row.get("cost_coverage") == "complete" and row.get("unpriced_calls") != 0:
            problems.append("%s_usage_complete_with_unpriced_calls" % name)
        if name != "router" and all(key in row for key in (
                "known_cost_usd", "actual_usd", "estimated_usd")):
            if abs(row["known_cost_usd"] - row["actual_usd"] - row["estimated_usd"]) > 0.000001:
                problems.append("%s_usage_cost_components_do_not_reconcile" % name)
        if name == "router" and all(key in row for key in (
                "tokens", "prompt_tokens", "cached_tokens", "completion_tokens")):
            if (row["tokens"] != row["prompt_tokens"] + row["completion_tokens"] or
                    row["cached_tokens"] > row["prompt_tokens"]):
                problems.append("router_usage_token_components_do_not_reconcile")

    updates = [row for row in token_updates if isinstance(row, dict)] \
        if isinstance(token_updates, list) else []
    if len(updates) > _G10_USAGE_MAX_DEBUG_UPDATES:
        problems.append("debug_token_updates_exceed_bound")
    update = updates[0] if len(updates) == 1 else None
    if not isinstance(update, dict):
        problems.append("debug_token_update_missing_or_duplicated")
    else:
        update_index = update.get("source_event_index")
        update_ts = update.get("ts")
        usage_ts = (sanitized_events[0].get("source_event_ts")
                    if len(sanitized_events) == 1 else None)
        if (update.get("source_event") != "token_update" or
                update.get("source_route") != "socket.token_update" or
                not isinstance(update_index, int) or isinstance(update_index, bool) or
                not 1 <= update_index <= 10 ** 9 or
                not _g10_usage_value_bounded(update_ts, maximum=10 ** 12) or
                not _g10_usage_value_bounded(usage_ts, maximum=10 ** 12) or
                update_ts < usage_ts or update_ts - usage_ts > 10):
            problems.append("debug_token_update_source_invalid")
        invalid_fields = update.get("invalid_fields", [])
        if not isinstance(invalid_fields, list) or len(invalid_fields) > 10 or any(
                field not in {
                    "session_cost_actual_usd", "session_cost_estimated_usd",
                    "session_unpriced_calls", "session_cost_complete", "session_tokens",
                    "week_cost_actual_usd", "week_cost_estimated_usd",
                    "week_unpriced_calls", "week_cost_complete", "week_tokens",
                } for field in invalid_fields):
            invalid_fields = []
            problems.append("debug_token_update_invalid_field_metadata")
        invalid_set = set(invalid_fields)
        for prefix in ("session", "week"):
            amount_fields = ("%s_cost_actual_usd" % prefix, "%s_cost_estimated_usd" % prefix)
            count_field = "%s_unpriced_calls" % prefix
            complete_field = "%s_cost_complete" % prefix
            for amount_field in amount_fields:
                if amount_field in invalid_set:
                    problems.append("debug_%s_cost_components_invalid" % prefix)
                elif not _g10_usage_value_bounded(update.get(amount_field)):
                    problems.append("debug_%s_cost_components_missing" % prefix)
            count = update.get(count_field)
            if count_field in invalid_set:
                problems.append("debug_%s_unpriced_count_invalid" % prefix)
            elif (not isinstance(count, int) or isinstance(count, bool) or count < 0 or
                  count > _G10_USAGE_MAX_VALUE):
                problems.append("debug_%s_unpriced_count_missing" % prefix)
            if complete_field in invalid_set:
                problems.append("debug_%s_cost_completeness_invalid" % prefix)
            elif not isinstance(update.get(complete_field), bool):
                problems.append("debug_%s_cost_completeness_missing" % prefix)
            section = sections.get(prefix)
            token_field = "%s_tokens" % prefix
            token_count = update.get(token_field)
            token_valid = (isinstance(token_count, int) and not isinstance(token_count, bool) and
                           0 <= token_count <= _G10_USAGE_MAX_VALUE)
            if token_field in invalid_set:
                problems.append("debug_%s_token_count_invalid" % prefix)
            elif not token_valid:
                problems.append("debug_%s_token_count_missing" % prefix)
            elif isinstance(section, dict) and section.get("tokens") != token_count:
                problems.append("debug_%s_token_count_mismatch" % prefix)

            if isinstance(section, dict) and all(key in section for key in (
                    "actual_usd", "estimated_usd", "unpriced_calls", "cost_coverage")):
                if (_g10_usage_value_bounded(update.get(amount_fields[0])) and
                        abs(float(update[amount_fields[0]]) - section["actual_usd"]) > 0.000001):
                    problems.append("debug_%s_actual_cost_mismatch" % prefix)
                if (_g10_usage_value_bounded(update.get(amount_fields[1])) and
                        abs(float(update[amount_fields[1]]) - section["estimated_usd"]) > 0.000001):
                    problems.append("debug_%s_estimated_cost_mismatch" % prefix)
                if update.get(count_field) != section["unpriced_calls"]:
                    problems.append("debug_%s_unpriced_count_mismatch" % prefix)
                if update.get(complete_field) != (section["cost_coverage"] == "complete"):
                    problems.append("debug_%s_completeness_mismatch" % prefix)

    projected_update = None
    if isinstance(update, dict):
        projected_update = {
            key: update[key] for key in (
                "session_cost_actual_usd", "session_cost_estimated_usd",
                "session_unpriced_calls", "session_cost_complete", "session_tokens",
                "week_cost_actual_usd", "week_cost_estimated_usd",
                "week_unpriced_calls", "week_cost_complete", "week_tokens",
            ) if key in update
        }
        invalid_update_fields = update.get("invalid_fields")
        if isinstance(invalid_update_fields, list) and len(invalid_update_fields) <= 10:
            if all(isinstance(field, str) and field in {
                    "session_cost_actual_usd", "session_cost_estimated_usd",
                    "session_unpriced_calls", "session_cost_complete", "session_tokens",
                    "week_cost_actual_usd", "week_cost_estimated_usd",
                    "week_unpriced_calls", "week_cost_complete", "week_tokens",
            } for field in invalid_update_fields):
                projected_update["invalid_fields"] = sorted(set(invalid_update_fields))
        for key in ("source_event", "source_route"):
            if key in update:
                expected = "token_update" if key == "source_event" else "socket.token_update"
                if update[key] == expected:
                    projected_update[key] = expected
                else:
                    projected_update[key] = "invalid"
                    problems.append("debug_token_update_source_invalid")
        event_index = update.get("source_event_index")
        if "source_event_index" in update:
            if (isinstance(event_index, int) and not isinstance(event_index, bool) and
                    1 <= event_index <= 10 ** 9):
                projected_update["source_event_index"] = event_index
            else:
                problems.append("debug_token_update_source_invalid")
        timestamp = update.get("ts")
        if "ts" in update:
            if _g10_usage_value_bounded(timestamp, maximum=10 ** 12):
                projected_update["ts"] = float(timestamp)
            else:
                problems.append("debug_token_update_source_invalid")

    return {"status": "ok" if not problems else "BLOCKED",
            "problems": sorted(set(problems)), "sections": sections,
            "token_update": projected_update, "usage_events": sanitized_events,
            "source_events": [{key: event.get(key) for key in (
                "source_event", "source_route", "source_event_index", "type",
                "driver_step", "source_event_ts", "capture_error",
            ) if key in event} for event in sanitized_events],
            "usage_event_count": usage_event_count}


def project_g10_receipts(events: Any, expected_run_id: str) -> Dict[str, Any]:
    """Validate actual router response receipts observed in this G10 trace span."""
    if not isinstance(expected_run_id, str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", expected_run_id):
        return {"status": "BLOCKED", "reason": "invalid_run_id", "receipts": []}
    provider_events = [row for row in events if isinstance(row, dict) and
                       row.get("event_type") == "provider"] if isinstance(events, list) else []
    if not provider_events:
        return {"status": "none_observed", "reason": None, "receipts": []}
    projection = project_g4_receipts(provider_events, expected_run_id=expected_run_id,
                                     allow_transport_errors=True)
    receipts = projection.get("receipts", [])
    if projection.get("status") != "ok":
        return {"status": "BLOCKED", "reason": projection.get("reason") or "invalid_receipts",
                "receipts": []}
    if projection.get("legacy_observations"):
        return {"status": "BLOCKED", "reason": "legacy_provider_observation_not_receipt",
                "receipts": []}
    problems: List[str] = []
    source_by_attempt = {
        event.get("attempt_id"): event for event in provider_events
        if isinstance(event.get("attempt_id"), str)
    }
    for receipt in receipts:
        if receipt.get("run_id") != expected_run_id:
            problems.append("receipt_run_id_mismatch")
        if (not isinstance(receipt.get("call_id"), str) or
                not _G10_TRACKER_ID_RE.fullmatch(receipt.get("call_id", "")) or
                not isinstance(receipt.get("attempt_id"), str) or
                not _G10_TRACKER_ID_RE.fullmatch(receipt.get("attempt_id", ""))):
            problems.append("receipt_identity_invalid")
        source_event = source_by_attempt.get(receipt.get("attempt_id"), {})
        if "source_id" in source_event:
            source_id = source_event.get("source_id")
            if not isinstance(source_id, str) or source_id not in _G10_RECEIPT_SOURCE_IDS:
                return {"status": "BLOCKED", "reason": "invalid_g10_receipt_source_id",
                        "receipts": []}
            receipt["source_id"] = source_id
        sdk_total_tokens = source_event.get("sdk_total_tokens")
        receipt["sdk_total_tokens"] = sdk_total_tokens
        outcome = receipt.get("outcome")
        if outcome == "response":
            for field in ("prompt_tokens", "cached_tokens", "completion_tokens",
                          "sdk_total_tokens"):
                value = receipt.get(field)
                if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                    problems.append("receipt_usage_count_invalid")
            if (receipt.get("usage_available") is not True or
                    receipt.get("usage_complete") is not True):
                problems.append("receipt_usage_incomplete")
            prompt = receipt.get("prompt_tokens")
            cached = receipt.get("cached_tokens")
            if (isinstance(prompt, int) and not isinstance(prompt, bool) and
                    isinstance(cached, int) and not isinstance(cached, bool) and
                    cached > prompt):
                problems.append("receipt_usage_components_contradictory")

            cost_label = receipt.get("cost_label")
            reported_cost = receipt.get("provider_reported_cost_usd")
            cost = receipt.get("cost_usd")
            if cost_label == "actual":
                if (receipt.get("cost_provenance") != "actual" or
                        receipt.get("cost_complete") is not True or
                        not _finite_number(reported_cost) or reported_cost < 0 or
                        not _finite_number(cost) or cost < 0 or
                        abs(float(cost) - float(reported_cost)) > 1e-12):
                    problems.append("receipt_cost_provenance_contradictory")
            elif cost_label == "estimated":
                if (receipt.get("cost_provenance") != "estimated" or
                        receipt.get("cost_complete") is not True or
                        reported_cost is not None or not _finite_number(cost) or cost < 0 or
                        receipt.get("resolved_model") in (None, "", "unknown", "openrouter/auto")):
                    problems.append("receipt_cost_provenance_contradictory")
            elif cost_label == "unpriced_unknown":
                if (receipt.get("cost_provenance") not in ("unpriced", "unpriced_unknown") or
                        receipt.get("cost_complete") is not False or cost is not None or
                        reported_cost is not None):
                    problems.append("receipt_cost_provenance_contradictory")
            else:
                problems.append("receipt_cost_provenance_contradictory")
        elif outcome == "transport_error":
            if receipt.get("cost_label") != "error":
                problems.append("receipt_transport_error_cost_invalid")
        else:
            problems.append("receipt_outcome_invalid")
    return {"status": "BLOCKED" if problems else "ok",
            "reason": ";".join(sorted(set(problems))) or None,
            "receipts": receipts,
            "counts": {"response_receipts": sum(row.get("outcome") == "response" for row in receipts),
                       "transport_errors": sum(row.get("outcome") == "transport_error" for row in receipts)}}


def reconcile_g10_router_usage(usage: Dict[str, Any], receipts: Dict[str, Any],
                               tracker: Optional[Dict[str, Any]] = None) -> List[str]:
    """Reconcile router token totals and session/week tracker accounting.

    Router totals use observed prompt plus completion tokens. The legacy tracker
    uses validated SDK ``total_tokens`` values, which may differ. Week values are
    cumulative and are checked for completeness here, then for persistence across
    the linked complete/resume pair.
    """
    if not isinstance(usage, dict) or usage.get("status") != "ok":
        return ["g10_usage_not_ready"]
    if not isinstance(receipts, dict) or receipts.get("status") not in ("ok", "none_observed"):
        return ["g10_receipts_not_ready"]
    section = (usage.get("sections") or {}).get("router")
    if not isinstance(section, dict):
        return ["g10_router_usage_section_missing"]
    sections = usage.get("sections")
    session = sections.get("session") if isinstance(sections, dict) else None
    week = sections.get("week") if isinstance(sections, dict) else None
    if not isinstance(session, dict) or not isinstance(week, dict):
        return ["g10_session_week_usage_section_missing"]
    all_receipts = receipts.get("receipts", [])
    if not isinstance(all_receipts, list):
        return ["g10_receipt_list_invalid"]
    if ((receipts.get("status") == "none_observed" and all_receipts) or
            (receipts.get("status") == "ok" and not all_receipts)):
        return ["g10_receipt_status_contradictory"]
    problems: List[str] = []
    seen_attempt_ids = set()
    for row in all_receipts:
        if not isinstance(row, dict):
            problems.append("g10_receipt_invalid")
            continue
        call_id = row.get("call_id")
        attempt_id = row.get("attempt_id")
        if (not isinstance(call_id, str) or not call_id or
                not isinstance(attempt_id, str) or not attempt_id):
            problems.append("g10_receipt_identity_missing")
        elif attempt_id in seen_attempt_ids:
            problems.append("g10_duplicate_receipt_attempt_id")
        else:
            seen_attempt_ids.add(attempt_id)
    if problems:
        return sorted(set(problems))

    response_rows = [row for row in all_receipts if row.get("outcome") == "response"]
    expected_calls = len(response_rows)
    if (not isinstance(section.get("calls"), int) or isinstance(section.get("calls"), bool) or
            section.get("calls") != expected_calls):
        problems.append("g10_router_call_count_mismatch")
    prompt_total = 0
    cached_total = 0
    completion_total = 0
    sdk_total = 0
    known_cost = 0.0
    actual_cost = 0.0
    estimated_cost = 0.0
    unpriced = 0
    for row in response_rows:
        prompt = row.get("prompt_tokens")
        cached = row.get("cached_tokens")
        completion = row.get("completion_tokens")
        sdk_tokens = row.get("sdk_total_tokens")
        if any(not isinstance(value, int) or isinstance(value, bool) or value < 0
               for value in (prompt, cached, completion, sdk_tokens)):
            problems.append("g10_receipt_usage_total_missing_or_invalid")
            continue
        if (row.get("usage_available") is not True or
                row.get("usage_complete") is not True):
            problems.append("g10_receipt_usage_incomplete")
        if cached > prompt:
            problems.append("g10_receipt_usage_components_contradictory")
        prompt_total += prompt
        cached_total += cached
        completion_total += completion
        sdk_total += sdk_tokens
        cost_label = row.get("cost_label")
        provenance = row.get("cost_provenance")
        amount = row.get("cost_usd")
        reported = row.get("provider_reported_cost_usd")
        if cost_label == "unpriced_unknown":
            if (provenance not in ("unpriced", "unpriced_unknown") or
                    row.get("cost_complete") is not False or amount is not None or
                    reported is not None):
                problems.append("g10_receipt_cost_provenance_invalid")
            unpriced += 1
        elif cost_label in ("actual", "estimated"):
            if not _finite_number(amount) or amount < 0:
                problems.append("g10_receipt_cost_invalid")
            else:
                known_cost += float(amount)
                if cost_label == "actual":
                    if (provenance != "actual" or row.get("cost_complete") is not True or
                            not _finite_number(reported) or reported < 0 or
                            abs(float(reported) - float(amount)) > 1e-12):
                        problems.append("g10_receipt_cost_provenance_invalid")
                    actual_cost += float(amount)
                else:
                    if (provenance != "estimated" or row.get("cost_complete") is not True or
                            reported is not None or
                            row.get("resolved_model") in (None, "", "unknown", "openrouter/auto")):
                        problems.append("g10_receipt_cost_provenance_invalid")
                    estimated_cost += float(amount)
        else:
            problems.append("g10_receipt_cost_provenance_invalid")
    expected_tokens = prompt_total + completion_total
    for field, expected in (
            ("prompt_tokens", prompt_total), ("cached_tokens", cached_total),
            ("completion_tokens", completion_total), ("tokens", expected_tokens)):
        observed = section.get(field)
        if (not isinstance(observed, int) or isinstance(observed, bool) or
                observed != expected):
            problems.append("g10_router_token_totals_mismatch")
    if cached_total > prompt_total:
        problems.append("g10_router_token_totals_mismatch")
    if (not _finite_number(section.get("known_cost_usd")) or section.get("known_cost_usd") < 0 or
            abs(float(section["known_cost_usd"]) - known_cost) > 0.000001):
        problems.append("g10_router_known_cost_mismatch")
    if (not isinstance(section.get("unpriced_calls"), int) or
            isinstance(section.get("unpriced_calls"), bool) or
            section.get("unpriced_calls") != unpriced):
        problems.append("g10_router_unpriced_count_mismatch")
    if section.get("cost_coverage") != ("complete" if unpriced == 0 else "incomplete"):
        problems.append("g10_router_cost_coverage_mismatch")
    if (not isinstance(session.get("tokens"), int) or isinstance(session.get("tokens"), bool) or
            session.get("tokens") != sdk_total):
        problems.append("g10_session_sdk_total_tokens_mismatch")
    tracker_session = (tracker.get("session") if isinstance(tracker, dict) and
                       tracker.get("status") == "ok" else None)
    expected_session_actual = (tracker_session.get("actual_usd") if isinstance(tracker_session, dict)
                               else actual_cost)
    expected_session_estimated = (tracker_session.get("estimated_usd")
                                  if isinstance(tracker_session, dict) else estimated_cost)
    expected_session_unpriced = (tracker_session.get("unpriced_calls")
                                 if isinstance(tracker_session, dict) else unpriced)
    expected_session_coverage = (tracker_session.get("cost_coverage")
                                 if isinstance(tracker_session, dict) else
                                 ("complete" if unpriced == 0 else "incomplete"))
    for field, expected, problem in (
            ("actual_usd", expected_session_actual, "g10_session_actual_cost_mismatch"),
            ("estimated_usd", expected_session_estimated, "g10_session_estimated_cost_mismatch")):
        if (not _finite_number(session.get(field)) or
                abs(float(session[field]) - expected) > 0.000001):
            problems.append(problem)
    expected_session_known = expected_session_actual + expected_session_estimated
    if (not _finite_number(session.get("known_cost_usd")) or
            abs(float(session["known_cost_usd"]) - expected_session_known) > 0.000001):
        problems.append("g10_session_known_cost_mismatch")
    if (not isinstance(session.get("unpriced_calls"), int) or
            isinstance(session.get("unpriced_calls"), bool) or
            session.get("unpriced_calls") != expected_session_unpriced):
        problems.append("g10_session_unpriced_count_mismatch")
    if session.get("cost_coverage") != expected_session_coverage:
        problems.append("g10_session_cost_coverage_mismatch")

    week_tokens = week.get("tokens")
    week_unpriced = week.get("unpriced_calls")
    if (not isinstance(week_tokens, int) or isinstance(week_tokens, bool) or week_tokens < 0 or
            not isinstance(week_unpriced, int) or isinstance(week_unpriced, bool) or week_unpriced < 0):
        problems.append("g10_week_usage_totals_missing_or_invalid")
    week_costs = [week.get(field) for field in ("actual_usd", "estimated_usd", "known_cost_usd")]
    if any(not _finite_number(value) or value < 0 for value in week_costs):
        problems.append("g10_week_cost_components_missing_or_invalid")
    elif abs(float(week_costs[2]) - float(week_costs[0]) - float(week_costs[1])) > 0.000001:
        problems.append("g10_week_cost_components_mismatch")
    if week.get("cost_coverage") not in ("complete", "incomplete"):
        problems.append("g10_week_cost_coverage_unknown")
    elif isinstance(week_unpriced, int) and not isinstance(week_unpriced, bool) and (
            (week.get("cost_coverage") == "complete") != (week_unpriced == 0)):
        if not isinstance(tracker, dict) or tracker.get("status") != "ok":
            problems.append("g10_week_cost_coverage_mismatch")
    if isinstance(tracker, dict) and tracker.get("status") == "ok":
        expected_week = tracker.get("week", {})
        if (week_tokens != expected_week.get("tokens") or
                week_unpriced != expected_week.get("unpriced_calls") or
                week.get("cost_coverage") != expected_week.get("cost_coverage") or
                any(not _finite_number(week.get(field)) or
                    abs(float(week[field]) - float(expected_week.get(field, -1))) > 0.000001
                    for field in ("actual_usd", "estimated_usd", "known_cost_usd"))):
            problems.append("g10_week_tracker_totals_mismatch")
    return sorted(set(problems))


def _validate_g10_resume_startup_receipts(
    profile: Dict[str, Any], manifest: Dict[str, Any], step_rows: List[Dict[str, Any]],
    receipt_projection: Dict[str, Any], positioned: List[Dict[str, Any]],
    usage_receipts: Dict[str, Any], tracker_artifact: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Accept only the evidenced diary-refresh and combat-reengage startup calls."""
    if profile.get("phase") != "resume":
        return {"status": "not_applicable", "receipts": [], "problems": [], "failures": []}

    problems: List[str] = []
    failures: List[str] = []
    fixture_steps = ((profile.get("fixture") or {}).get("steps")
                     if isinstance(profile.get("fixture"), dict) else None)
    usage_steps = [index for index, row in enumerate(fixture_steps or [], 1)
                   if isinstance(row, dict) and row.get("kind") == "usage"]
    driver_observation = (manifest.get("g10", {}).get("driver_observation")
                          if isinstance(manifest.get("g10"), dict) else None)
    usage_step = (driver_observation.get("usage_step")
                  if isinstance(driver_observation, dict) else None)
    if (len(usage_steps) != 1 or usage_step != usage_steps[0] or
            len(step_rows) < usage_steps[0]):
        problems.append("g10_resume_startup_usage_step_missing_or_mismatched")
        usage_start = usage_end = None
    else:
        pair = step_rows[usage_steps[0] - 1]
        before_trace = ((pair.get("before") or {}).get("observation") or {}).get("runtimeTrace")
        after_trace = ((pair.get("after") or {}).get("observation") or {}).get("runtimeTrace")
        usage_start = before_trace.get("offset_bytes") if isinstance(before_trace, dict) else None
        usage_end = after_trace.get("offset_bytes") if isinstance(after_trace, dict) else None
        if (not isinstance(before_trace, dict) or not isinstance(after_trace, dict) or
                before_trace.get("status") != "captured" or
                after_trace.get("status") != "captured" or
                not isinstance(usage_start, int) or isinstance(usage_start, bool) or
                not isinstance(usage_end, int) or isinstance(usage_end, bool) or
                usage_end < usage_start):
            problems.append("g10_resume_startup_usage_trace_span_invalid")
            usage_start = usage_end = None

    trace_span = manifest.get("trace_span") if isinstance(manifest.get("trace_span"), dict) else {}
    trace_start = trace_span.get("offset_before_bytes")
    start_metadata = manifest.get("trace_start_offset")
    start_offset = (start_metadata.get("source_byte_offset")
                    if isinstance(start_metadata, dict) else None)
    if (not isinstance(trace_start, int) or isinstance(trace_start, bool) or trace_start < 0 or
            start_offset != trace_start or
            (usage_start is not None and usage_start < trace_start)):
        problems.append("g10_resume_startup_trace_boundary_invalid")

    if (usage_receipts.get("status") != "none_observed" or
            usage_receipts.get("receipts") != []):
        failures.append("g10_usage_command_made_or_failed_to_exclude_provider_request")
    if not isinstance(tracker_artifact, dict):
        problems.append("g10_resume_startup_tracker_missing")
        tracker_rows: Dict[str, Dict[str, Any]] = {}
        server_launch = sent_at = None
    else:
        pre_run = tracker_artifact.get("pre_run")
        post_usage = tracker_artifact.get("post_usage")
        pre_lines = pre_run.get("line_count") if isinstance(pre_run, dict) else None
        post_events = post_usage.get("events") if isinstance(post_usage, dict) else None
        usage_interval = tracker_artifact.get("usage_interval")
        server_launch = tracker_artifact.get("server_launch_epoch")
        sent_at = usage_interval.get("command_sent_epoch") if isinstance(usage_interval, dict) else None
        if (not isinstance(pre_lines, int) or isinstance(pre_lines, bool) or pre_lines < 0 or
                not isinstance(post_events, list) or
                not _g10_usage_value_bounded(server_launch, 10 ** 12) or
                not _g10_usage_value_bounded(sent_at, 10 ** 12) or
                server_launch >= sent_at):
            problems.append("g10_resume_startup_tracker_interval_invalid")
        tracker_rows = {
            row.get("attempt_id"): row for row in post_events or []
            if isinstance(row, dict) and row.get("kind") == "router_usage" and
            isinstance(row.get("line_number"), int) and not isinstance(row.get("line_number"), bool) and
            isinstance(pre_lines, int) and row.get("line_number") > pre_lines
        }

    events_by_attempt: Dict[str, List[Dict[str, Any]]] = {}
    for event in (positioned if isinstance(positioned, list) else []):
        if (isinstance(event, dict) and event.get("event_type") == "provider" and
                isinstance(event.get("attempt_id"), str)):
            events_by_attempt.setdefault(event["attempt_id"], []).append(event)
    receipts = (receipt_projection.get("receipts")
                if isinstance(receipt_projection, dict) else None)
    if (not isinstance(receipts, list) or receipt_projection.get("status") != "ok"):
        problems.append("g10_resume_startup_receipt_projection_unavailable")
        receipts = []
    response_receipts = [row for row in receipts if isinstance(row, dict)]
    if len(response_receipts) != 2:
        problems.append("g10_resume_startup_receipt_count_missing_or_duplicated")

    seen_call_ids = set()
    seen_attempt_ids = set()
    source_counts = {source: 0 for source in _G10_RESUME_STARTUP_SOURCES}
    accepted: List[Dict[str, Any]] = []
    for receipt in response_receipts:
        call_id = receipt.get("call_id")
        attempt_id = receipt.get("attempt_id")
        if (not isinstance(call_id, str) or not call_id or call_id in seen_call_ids or
                not isinstance(attempt_id, str) or not attempt_id or attempt_id in seen_attempt_ids):
            failures.append("g10_resume_startup_receipt_identity_missing_or_duplicated")
            continue
        seen_call_ids.add(call_id)
        seen_attempt_ids.add(attempt_id)
        matching_events = events_by_attempt.get(attempt_id, [])
        if len(matching_events) != 1:
            problems.append("g10_resume_startup_receipt_source_event_missing_or_duplicated")
            continue
        event = matching_events[0]
        event_start = event.get("_source_byte_start")
        event_end = event.get("_source_byte_end")
        if (not isinstance(event_start, int) or isinstance(event_start, bool) or
                not isinstance(event_end, int) or isinstance(event_end, bool) or
                event_end <= event_start):
            problems.append("g10_resume_startup_receipt_position_missing")
            continue
        if (usage_start is not None and usage_end is not None and
                event_start < usage_end and event_end > usage_start):
            failures.append("g10_usage_command_made_or_failed_to_exclude_provider_request")
            continue
        if (trace_start is None or usage_start is None or
                event_start < trace_start or event_end > usage_start):
            failures.append("g10_resume_provider_receipt_outside_startup_window")
            continue
        if (receipt.get("outcome") != "response" or receipt.get("fallback") is not False or
                receipt.get("usage_available") is not True or
                receipt.get("usage_complete") is not True):
            failures.append("g10_resume_startup_receipt_not_complete_response")
            continue

        source_kind = None
        for candidate, expected in _G10_RESUME_STARTUP_SOURCES.items():
            if (event.get("site") == expected["site"] and
                    event.get("task") == expected["task"] and
                    event.get("source_id") == expected["source_id"] and
                    event.get("endpoint") is None):
                source_kind = candidate
                break
        if source_kind is None:
            failures.append("g10_resume_startup_provider_source_unapproved_or_missing")
            continue
        source_counts[source_kind] += 1
        if source_counts[source_kind] > 1:
            failures.append("g10_resume_startup_semantic_call_duplicated")
            continue

        tracker_row = tracker_rows.get(attempt_id)
        timestamp = tracker_row.get("timestamp_epoch") if isinstance(tracker_row, dict) else None
        if (not isinstance(tracker_row, dict) or
                tracker_row.get("call_id") != call_id or
                not _g10_usage_value_bounded(timestamp, 10 ** 12)):
            problems.append("g10_resume_startup_tracker_receipt_binding_missing")
            continue
        if (not _g10_usage_value_bounded(server_launch, 10 ** 12) or
                not _g10_usage_value_bounded(sent_at, 10 ** 12) or
                timestamp < server_launch or timestamp >= sent_at):
            failures.append("g10_resume_startup_receipt_outside_server_usage_interval")
            continue
        cost_sources = {"actual": "provider_reported", "estimated": "estimated",
                        "unpriced_unknown": "unpriced"}
        if (tracker_row.get("prompt_tokens") != receipt.get("prompt_tokens") or
                tracker_row.get("completion_tokens") != receipt.get("completion_tokens") or
                tracker_row.get("sdk_total_tokens") != receipt.get("sdk_total_tokens") or
                tracker_row.get("cost_source") != cost_sources.get(receipt.get("cost_label")) or
                (receipt.get("cost_label") in ("actual", "estimated") and
                 (not _finite_number(tracker_row.get("cost_usd")) or
                  not _finite_number(receipt.get("cost_usd")) or
                  abs(float(tracker_row["cost_usd"]) - float(receipt["cost_usd"])) > 1e-12))):
            failures.append("g10_resume_startup_receipt_tracker_fields_mismatch")
            continue
        accepted.append({
            "source": source_kind, "call_id": call_id, "attempt_id": attempt_id,
            "timestamp_epoch": timestamp,
            "trace_byte_start": event_start, "trace_byte_end": event_end,
            "prompt_tokens": receipt.get("prompt_tokens"),
            "cached_tokens": receipt.get("cached_tokens"),
            "completion_tokens": receipt.get("completion_tokens"),
            "sdk_total_tokens": receipt.get("sdk_total_tokens"),
            "cost_label": receipt.get("cost_label"), "cost_usd": receipt.get("cost_usd"),
        })

    if any(count != 1 for count in source_counts.values()):
        problems.append("g10_resume_startup_required_source_missing")
    expected_attempts = {row.get("attempt_id") for row in response_receipts
                         if isinstance(row, dict)}
    if tracker_rows and set(tracker_rows) != expected_attempts:
        failures.append("g10_resume_startup_tracker_receipt_set_mismatch")
    accepted.sort(key=lambda row: (row.get("trace_byte_start", -1), row.get("attempt_id", "")))
    return {"status": "ok" if not problems and not failures else "BLOCKED",
            "receipts": accepted, "problems": sorted(set(problems)),
            "failures": sorted(set(failures))}


def revalidate_g10_usage_artifact(profile: Dict[str, Any], manifest: Dict[str, Any],
                                  step_rows: List[Dict[str, Any]],
                                  usage_artifact: Dict[str, Any],
                                  positioned: List[Dict[str, Any]],
                                  position_errors: List[str],
                                  tracker_artifact: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Re-derive usage, response receipts, and /usage trace-span receipts."""
    problems: List[str] = []
    failures: List[str] = []
    capture = usage_artifact.get("usage_capture")
    if not isinstance(capture, dict):
        capture = {}
        problems.append("g10_raw_usage_capture_missing")
    observed = project_g10_usage_observations(
        capture.get("usage_events"), capture.get("debug_token_updates")
    )
    if usage_artifact.get("observed") != observed:
        failures.append("g10_usage_projection_not_derived_from_sanitized_observations")
    if capture.get("status") != "captured":
        problems.append("g10_usage_output_not_captured")

    run_id = manifest.get("run_id")
    receipts = project_g10_receipts(positioned, run_id)
    if position_errors:
        receipts = {"status": "BLOCKED", "reason": "trace_position_parse_error", "receipts": []}
    if usage_artifact.get("router_receipts") != receipts:
        failures.append("g10_router_receipts_not_derived_from_trace")

    expected_usage_steps = [index for index, row in enumerate(
        (profile.get("fixture") or {}).get("steps", []), 1
    ) if isinstance(row, dict) and row.get("kind") == "usage"]
    g10 = manifest.get("g10") if isinstance(manifest.get("g10"), dict) else {}
    driver_observation = g10.get("driver_observation")
    if not isinstance(driver_observation, dict):
        driver_observation = {}
    usage_step = driver_observation.get("usage_step")
    if len(expected_usage_steps) != 1 or usage_step != expected_usage_steps[0]:
        problems.append("g10_usage_step_identity_missing_or_mismatched")
    source_events = observed.get("source_events") if isinstance(observed, dict) else []
    if isinstance(source_events, list):
        for source_event in source_events:
            if (not isinstance(source_event, dict) or
                    source_event.get("driver_step") != usage_step):
                problems.append("g10_usage_output_source_step_mismatch")
    usage_receipts: Dict[str, Any] = {
        "status": "BLOCKED", "reason": "usage_step_trace_span_missing", "receipts": []
    }
    if (not position_errors and len(expected_usage_steps) == 1 and
            usage_step == expected_usage_steps[0] and
            len(step_rows) >= expected_usage_steps[0]):
        usage_pair = step_rows[expected_usage_steps[0] - 1]
        before_observation = (usage_pair.get("before") or {}).get("observation", {})
        after_observation = (usage_pair.get("after") or {}).get("observation", {})
        before_trace = before_observation.get("runtimeTrace", {})
        after_trace = after_observation.get("runtimeTrace", {})
        start = before_trace.get("offset_bytes")
        end = after_trace.get("offset_bytes")
        span_valid = (
            before_trace.get("status") == "captured" and
            after_trace.get("status") == "captured" and
            isinstance(start, int) and not isinstance(start, bool) and
            isinstance(end, int) and not isinstance(end, bool) and end >= start
        )
        if span_valid:
            usage_events = [event for event in positioned
                            if isinstance(event, dict) and event.get("event_type") == "provider" and
                            start <= event.get("_source_byte_start", -1) and
                            event.get("_source_byte_end", -1) <= end]
            usage_receipts = project_g10_receipts(usage_events, run_id)
        else:
            problems.append("g10_usage_step_trace_span_invalid")
    if usage_artifact.get("usage_step_receipts") != usage_receipts:
        failures.append("g10_usage_step_receipts_not_derived_from_trace")

    tracker_projection = project_g10_tracker_telemetry(
        tracker_artifact, observed, receipts
    )
    if isinstance(tracker_artifact, dict):
        expected_tracker_identity = {
            "phase": (manifest.get("scenario") or {}).get("phase"),
            "run_id": manifest.get("run_id"),
            "chain_id": manifest.get("chain_id"),
            "seed_id": (manifest.get("seed") or {}).get("seed_id"),
            "sandbox_id": manifest.get("sandbox_id"),
        }
        if any(tracker_artifact.get(key) != value
               for key, value in expected_tracker_identity.items()):
            tracker_projection = {
                "status": "BLOCKED",
                "problems": sorted(set(tracker_projection.get("problems", []) +
                                        ["g10_tracker_manifest_identity_mismatch"])),
            }
    if usage_artifact.get("tracker_reconciliation") != tracker_projection:
        failures.append("g10_tracker_reconciliation_not_derived")
    reconciliation = reconcile_g10_router_usage(observed, receipts, tracker_projection)
    startup_validation = _validate_g10_resume_startup_receipts(
        profile, manifest, step_rows, receipts, positioned, usage_receipts, tracker_artifact
    )
    usage_problems = list(observed.get("problems", []))
    usage_problems.extend(reconciliation)
    usage_problems.extend(tracker_projection.get("problems", []))
    if usage_receipts.get("status") != "none_observed":
        usage_problems.append("g10_usage_provider_request_observed_or_unverified")
    phase = profile.get("phase")
    if phase == "resume":
        usage_problems.extend(startup_validation.get("problems", []))
        usage_problems.extend(startup_validation.get("failures", []))
        problems.extend(startup_validation.get("problems", []))
        failures.extend(startup_validation.get("failures", []))
    response_receipts = [row for row in receipts.get("receipts", [])
                         if isinstance(row, dict) and row.get("outcome") == "response"]
    if phase == "complete" and not response_receipts:
        usage_problems.append("g10_complete_provider_receipt_missing")
    if capture.get("status") != "captured":
        usage_problems.append("g10_usage_output_not_captured")
    expected_problems = sorted(set(usage_problems))
    expected_status = "ok" if not expected_problems else "BLOCKED"
    if (usage_artifact.get("router_receipt_reconciliation_problems") != reconciliation or
            usage_artifact.get("router_receipt_reconciliation_problems") != sorted(set(reconciliation))):
        failures.append("g10_usage_receipt_reconciliation_not_derived")
    legacy_resume_block = (
        phase == "resume" and expected_status == "ok" and
        startup_validation.get("status") == "ok" and
        usage_artifact.get("status") == "BLOCKED"
    )
    if usage_artifact.get("status") != expected_status and not legacy_resume_block:
        failures.append("g10_usage_status_not_derived_from_observations")
    return {"observed": observed, "receipts": receipts,
            "tracker_reconciliation": tracker_projection,
            "usage_step_receipts": usage_receipts,
            "response_receipts": response_receipts,
            "startup_receipt_validation": startup_validation,
            "reconciliation_problems": reconciliation,
            "expected_status": expected_status,
            "problems": sorted(set(problems)),
            "failures": sorted(set(failures))}


def build_g10_checks(profile: Dict[str, Any], manifest: Dict[str, Any],
                     steps: List[Dict[str, Any]], step_errors: List[str],
                     usage_artifact: Dict[str, Any], save_state: Dict[str, Any],
                     lifecycle_status: str) -> List[Dict[str, Any]]:
    """Derive bounded expected/observed G10 checks from retained evidence."""
    phase = profile.get("phase")
    fixture = profile.get("fixture") if isinstance(profile.get("fixture"), dict) else {}
    expected_rows = fixture.get("steps") if isinstance(fixture.get("steps"), list) else []
    expected_inputs = [row.get("input") for row in expected_rows if isinstance(row, dict)]
    observed_inputs = [
        ((row.get("before") or {}).get("observation") or {}).get("input")
        for row in steps
    ]
    steps_ok = (not step_errors and len(steps) == len(expected_inputs) and
                observed_inputs == expected_inputs and
                manifest.get("counts", {}).get("steps_sent") == len(expected_inputs) and
                manifest.get("counts", {}).get("timeouts") == 0)
    checks = [{
        "id": "g10_fixed_phase_inputs", "required": True,
        "expected": expected_inputs,
        "observed": {"inputs": observed_inputs, "steps_sent": manifest.get("counts", {}).get("steps_sent"),
                     "step_errors": step_errors},
        "status": "PASS" if steps_ok else "BLOCKED",
        "evidence": "fixed G10 profile and per-step before snapshots",
    }]
    diary_validation = _g10_diary_phase_validation(save_state, phase)
    diary_ok = diary_validation.get("status") == "ok"
    checks.append({
        "id": "g10_diary_identifier_projection", "required": True,
        "expected": "hash-bound minimal diary identity/range projection for this phase",
        "observed": {
            "status": diary_validation.get("status"),
            "saved_projection_sha256": diary_validation.get("saved_projection_sha256"),
            "resumed_projection_sha256": diary_validation.get("resumed_projection_sha256"),
            "failures": diary_validation.get("failures", []),
            "problems": diary_validation.get("problems", []),
        },
        "status": "PASS" if diary_ok else (
            "FAIL" if diary_validation.get("status") == "FAIL" else "BLOCKED"
        ),
        "evidence": "g10_save_state.json sanitized diary identifier projection",
    })

    snapshot_ok = bool(steps) and not step_errors
    for row in steps:
        for edge in ("before", "after"):
            snapshot = row.get(edge)
            if (not isinstance(snapshot, dict) or snapshot.get("errors") or
                    snapshot.get("numeric_errors") or
                    not isinstance(snapshot.get("mechanical_projection"), dict) or
                    not isinstance(snapshot.get("g10_reward_projection"), dict)):
                snapshot_ok = False
    checks.append({
        "id": "g10_state_snapshots", "required": True,
        "expected": "complete numeric-safe before/after state for each fixed input",
        "observed": {"step_count": len(steps), "step_errors": step_errors,
                     "reward_projection_present": all(
                         isinstance((row.get(edge) or {}).get("g10_reward_projection"), dict)
                         for row in steps for edge in ("before", "after")
                     )},
        "status": "PASS" if snapshot_ok else "BLOCKED",
        "evidence": "per-step canonical state snapshots",
    })

    if phase == "complete":
        first_after = (steps[0].get("after") or {}).get("observation", {}) if steps else {}
        narration_outputs = first_after.get("actual_backend_outputs", [])
        narration_ok = any(isinstance(row, dict) and isinstance(row.get("content"), str) and
                           row.get("content").strip() and
                           row.get("content").strip().casefold() != str(expected_inputs[0]).casefold()
                           for row in narration_outputs) if expected_inputs else False
        combat_rows = fixture.get("combat_steps", []) if isinstance(fixture.get("combat_steps"), list) else []
        combat_start = 1
        combat_end = combat_start + len(combat_rows)
        combat_observed = steps[combat_start:combat_end]
        combat_outputs = [
            bool(((row.get("after") or {}).get("observation") or {}).get("backend_output_count", 0))
            for row in combat_observed
        ]
        combat_ok = len(combat_observed) == len(combat_rows) and all(combat_outputs)
        save_ok = save_state.get("status") == "captured"
        for check_id, expected, observed, ok in (
                ("g10_narration", "one non-echo narrator response", narration_outputs, narration_ok),
                ("g10_combat", {"fixed_combat_steps": len(combat_rows)},
                 {"observed_steps": len(combat_observed), "step_outputs": combat_outputs}, combat_ok),
                ("g10_save", "one new valid essential save", save_state, save_ok)):
            checks.append({"id": check_id, "required": True, "expected": expected,
                           "observed": observed, "status": "PASS" if ok else "BLOCKED",
                           "evidence": "G10 step snapshots and save-state projection"})
    else:
        for check_id, expected in (("g10_narration", "covered by the paired complete phase"),
                                   ("g10_combat", "covered by the paired complete phase"),
                                   ("g10_save", "covered by the paired complete phase")):
            checks.append({"id": check_id, "required": False, "expected": expected,
                           "observed": "not applicable in the observation-only resume phase",
                           "status": "NOT_APPLICABLE", "evidence": "phase contract"})
        before = (steps[0].get("before") or {}) if steps else {}
        after = (steps[-1].get("after") or {}) if steps else {}
        retained_ok = (save_state.get("status") == "retained" and
                       before.get("mechanical_projection") == after.get("mechanical_projection") and
                       before.get("g10_reward_projection") == after.get("g10_reward_projection"))
        checks.append({
            "id": "g10_resume_read_only", "required": True,
            "expected": "one /usage input and no change to resumed mechanical state",
            "observed": {"inputs": observed_inputs,
                         "mechanical_state_unchanged": before.get("mechanical_projection") ==
                         after.get("mechanical_projection"),
                         "reward_state_unchanged": before.get("g10_reward_projection") ==
                         after.get("g10_reward_projection"), "save_state": save_state},
            "status": "PASS" if retained_ok and expected_inputs == ["/usage"] else "BLOCKED",
            "evidence": "retained save inventory and resume before/after snapshots",
        })

    usage_ok = usage_artifact.get("status") == "ok"
    usage_observed = usage_artifact.get("observed", {})
    checks.append({
        "id": "g10_usage_and_debug_provenance", "required": True,
        "expected": {"router_session_week": "actual, estimated, or unpriced with completeness",
                     "debug": "matching session/week provenance fields"},
        "observed": {"status": usage_observed.get("status"),
                     "problems": usage_observed.get("problems"),
                     "router_reconciliation": usage_artifact.get(
                         "router_receipt_reconciliation_problems")},
        "status": "PASS" if usage_ok else "BLOCKED",
        "evidence": "retained /usage output, Debug token_update, and router receipts",
    })
    tracker_reconciliation = usage_artifact.get("tracker_reconciliation", {})
    checks.append({
        "id": "g10_tracker_telemetry_reconciled", "required": True,
        "expected": "sanitized session events and exact rolling-week window from append-only telemetry",
        "observed": tracker_reconciliation,
        "status": "PASS" if tracker_reconciliation.get("status") == "ok" else "BLOCKED",
        "evidence": "pre-run, post-usage, post-shutdown, and linked restart snapshots",
    })
    usage_receipts = usage_artifact.get("usage_step_receipts", {})
    usage_read_only = usage_receipts.get("status") == "none_observed"
    checks.append({
        "id": "g10_usage_read_only", "required": True,
        "expected": "the /usage step issues no provider request",
        "observed": usage_receipts,
        "status": "PASS" if usage_read_only else "BLOCKED",
        "evidence": "router receipts linked to the /usage step trace span",
    })
    provider_identity = manifest.get("g10", {}).get("provider_identity", {})
    provider_identity_ok = (
        provider_identity.get("status") == "ok" and
        provider_identity.get("response_receipt_count", 0) > 0 and
        bool(provider_identity.get("providers")) and
        bool(provider_identity.get("response_models"))
    ) if phase == "complete" else provider_identity.get("status") == "none_observed"
    checks.append({
        "id": "g10_runtime_provider_identity", "required": phase == "complete",
        "expected": ("provider and resolved model derived from response receipts"
                     if phase == "complete" else "resume makes no provider request"),
        "observed": provider_identity,
        "status": "PASS" if provider_identity_ok else "BLOCKED",
        "evidence": "runtime router response receipts",
    })
    checks.append({
        "id": "g10_owned_server_lifecycle", "required": True,
        "expected": "owned port-8360 server start, capture completion, and stop bound to server.log",
        "observed": lifecycle_status,
        "status": "PASS" if lifecycle_status == "finalized" else "BLOCKED",
        "evidence": "server_lifecycle.jsonl and server.log",
    })
    return checks


def project_g4_receipts(events: List[Dict[str, Any]],
                        expected_run_id: Optional[str] = None, *,
                        allow_transport_errors: bool = False) -> Dict[str, Any]:
    """Project only newly captured router-adapter provider receipt rows.

    Do not infer runtime identity or usage from configuration, manifest declarations,
    or aggregate router counters. An attempt is usable only with its actual paired IDs.
    G6 router-migrated compression traces use the same receipt contract as other
    migrated sites. Legacy compression traces without router attempt identity keep
    their bounded legacy projection for retained bundles.
    """
    observed_run_ids = {
        event.get("run_id") for event in events
        if isinstance(event, dict) and isinstance(event.get("run_id"), str) and
        _G5_TRACE_RUN_ID_RE.fullmatch(event["run_id"])
    }
    inferred_run_id = next(iter(observed_run_ids)) if len(observed_run_ids) == 1 else None
    ambiguous_inferred_run_id = expected_run_id is None and len(observed_run_ids) > 1
    projected: List[Dict[str, Any]] = []
    legacy_observations: List[Dict[str, Any]] = []
    seen_attempts = set()
    seen_pairs = set()
    allowed_tasks = _configured_router_task_ids() or frozenset()
    for event in events:
        if event.get("event_type") != "provider":
            continue
        site = event.get("site")
        identity_fields = ("call_id", "attempt_id", "attempt_number", "task", "provider",
                           "requested_model", "resolved_model", "retry", "fallback",
                           "outcome", "error_type")
        if (site == "combat_compression" and
                not _has_router_attempt_identity(event)):
            # Pre-G6 compression observations retain their strict legacy shape;
            # G6 router-shaped compression events flow through common receipt validation.
            if (any(key in event for key in identity_fields) or
                    set(event) - {"event_type", "schema_version", "site", "mode",
                                  "combat_round", "phase", "elapsed_ms", "prompt_tokens",
                                  "completion_tokens", "total_tokens", "recorded_at_ms",
                                  "run_id", "action_id", "batch_id",
                                  "_source_byte_start", "_source_byte_end", "_source_line"} or
                    event.get("schema_version") != 1 or
                    ("run_id" in event and
                     (not isinstance(event.get("run_id"), str) or
                      not _G5_TRACE_RUN_ID_RE.fullmatch(event["run_id"]) or
                      (expected_run_id is not None and
                       (not isinstance(expected_run_id, str) or
                        not _G5_TRACE_RUN_ID_RE.fullmatch(expected_run_id) or
                        event["run_id"] != expected_run_id)) or
                      (expected_run_id is None and
                       (ambiguous_inferred_run_id or
                        (inferred_run_id is not None and event["run_id"] != inferred_run_id))))) or
                    ("action_id" in event and
                     (not isinstance(event.get("action_id"), str) or
                      not _G5_ACTION_ID_RE.fullmatch(event["action_id"]))) or
                    ("batch_id" in event and
                     (not isinstance(event.get("batch_id"), str) or
                      not _G5_BATCH_ID_RE.fullmatch(event["batch_id"]))) or
                    not _finite_number(event.get("elapsed_ms")) or event.get("elapsed_ms") < 0 or
                    any(not isinstance(event.get(key), int) or isinstance(event.get(key), bool)
                        or event.get(key) < 0 for key in
                        ("prompt_tokens", "completion_tokens", "total_tokens", "recorded_at_ms")) or
                    ("mode" in event and not isinstance(event.get("mode"), str)) or
                    ("phase" in event and not isinstance(event.get("phase"), str)) or
                    ("combat_round" in event and
                     (not isinstance(event.get("combat_round"), int) or
                      isinstance(event.get("combat_round"), bool) or event.get("combat_round") < 0)) or
                    event.get("total_tokens") != event.get("prompt_tokens") + event.get("completion_tokens")):
                return {"status": "BLOCKED", "reason": "invalid_legacy_compression_observation",
                        "receipts": [], "legacy_observations": []}
            legacy = {key: value for key, value in event.items() if not key.startswith("_source_")}
            legacy.update({"classification": "known_unmigrated_compression_observation",
                           "provider": "unknown", "model": "unknown", "cost": "unknown",
                           "identity_status": "no_router_attempt_identity"})
            legacy.update({key: value for key, value in event.items() if key.startswith("_source_")})
            legacy_observations.append(legacy)
            continue
        if (site is None and any(key in event for key in ("task", "call_id", "attempt_id"))):
            # Core-looking rows with a missing/forged site cannot be re-labelled
            # as legacy to bypass the required receipt identity contract.
            return {"status": "BLOCKED", "reason": "invalid_or_duplicate_receipt_identity",
                    "receipts": [], "legacy_observations": []}
        call_id, attempt_id = event.get("call_id"), event.get("attempt_id")
        if (not isinstance(call_id, str) or not call_id or
                not isinstance(attempt_id, str) or not attempt_id or
                attempt_id in seen_attempts or event.get("task") not in allowed_tasks or
                not isinstance(event.get("provider"), str) or not event.get("provider") or
                not isinstance(event.get("requested_model"), str) or not event.get("requested_model") or
                not isinstance(event.get("resolved_model"), str) or not event.get("resolved_model") or
                not isinstance(event.get("retry"), bool) or
                not isinstance(event.get("fallback"), bool) or
                not isinstance(event.get("usage_available"), bool) or
                not isinstance(event.get("usage_complete"), bool)):
            return {"status": "BLOCKED", "reason": "invalid_or_duplicate_receipt_identity",
                    "receipts": [], "legacy_observations": []}
        pair = (call_id, attempt_id)
        if pair in seen_pairs:
            return {"status": "BLOCKED", "reason": "invalid_or_duplicate_receipt_identity",
                    "receipts": [], "legacy_observations": []}
        seen_pairs.add(pair)
        seen_attempts.add(attempt_id)
        outcome = event.get("outcome")
        cost = event.get("provider_reported_cost_usd")
        provenance = event.get("cost_provenance")
        if allow_transport_errors and outcome == "transport_error":
            if (not isinstance(event.get("error_type"), str) or not event.get("error_type") or
                    provenance != "error" or event.get("cost_usd") is not None or cost is not None or
                    event.get("cost_complete") is not False or
                    event.get("usage_available") is not False or
                    event.get("usage_complete") is not False or
                    event.get("resolved_model") != "unknown"):
                return {"status": "BLOCKED", "reason": "invalid_transport_error_receipt",
                        "receipts": [], "legacy_observations": []}
            cost_label = "error"
        elif cost is not None:
            if not _finite_number(cost) or cost < 0 or provenance != "actual":
                return {"status": "BLOCKED", "reason": "invalid_receipt_cost", "receipts": [], "legacy_observations": []}
            cost_label = "actual"
        elif provenance == "estimated":
            if not _finite_number(event.get("cost_usd")) or event.get("cost_usd") < 0:
                return {"status": "BLOCKED", "reason": "invalid_estimated_receipt_cost", "receipts": [], "legacy_observations": []}
            cost_label = "estimated"
        elif provenance in ("unpriced", "unpriced_unknown"):
            cost_label = "unpriced_unknown"
        else:
            return {"status": "BLOCKED", "reason": "unknown_cost_not_explicitly_unpriced", "receipts": [], "legacy_observations": []}
        projected.append({key: event.get(key) for key in (
            "run_id", "call_id", "attempt_id", "attempt_number", "task", "provider",
            "observed_upstream_provider", "requested_model", "resolved_model",
            "retry", "retry_tier", "fallback", "prompt_tokens", "cached_tokens",
            "completion_tokens", "usage_complete", "usage_available",
            "provider_reported_cost_usd", "cost_usd", "cost_provenance", "cost_complete",
            "outcome", "error_type")})
        projected[-1]["cost_label"] = cost_label
    return {"status": "ok" if projected else "BLOCKED",
            "reason": None if projected else "required_actual_receipts_missing",
            "receipts": projected, "legacy_observations": legacy_observations,
            "counts": {"core_receipts": len(projected),
                       "legacy_provider_observations": len(legacy_observations),
                        "trace_provider_rows": len(projected) + len(legacy_observations)}}


def project_g9_receipts(events: List[Dict[str, Any]], expected_run_id: str) -> Dict[str, Any]:
    """Project response-derived G9 receipts; never infer from declared config."""
    if not isinstance(expected_run_id, str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", expected_run_id):
        return {"status": "BLOCKED", "reason": "invalid_g9_run_id", "receipts": []}
    projection = project_g4_receipts(
        events, expected_run_id=expected_run_id, allow_transport_errors=True
    )
    if projection.get("status") != "ok" or projection.get("legacy_observations"):
        return {"status": "BLOCKED", "reason": projection.get("reason") or
                "legacy_provider_observation_not_receipt", "receipts": []}
    receipts = projection.get("receipts", [])
    seen_attempts = set()
    for receipt in receipts:
        if not isinstance(receipt, dict):
            return {"status": "BLOCKED", "reason": "malformed_g9_receipt", "receipts": []}
        if receipt.get("run_id") != expected_run_id:
            return {"status": "BLOCKED", "reason": "receipt_run_id_mismatch", "receipts": []}
        attempt_id = receipt.get("attempt_id")
        if attempt_id in seen_attempts:
            return {"status": "BLOCKED", "reason": "duplicate_g9_attempt", "receipts": []}
        seen_attempts.add(attempt_id)
        if (receipt.get("provider") not in ("openai", "openrouter") or
                not isinstance(receipt.get("requested_model"), str) or
                not receipt.get("requested_model") or
                not isinstance(receipt.get("resolved_model"), str) or
                not isinstance(receipt.get("observed_upstream_provider"), str) or
                not receipt.get("observed_upstream_provider") or
                not isinstance(receipt.get("cost_complete"), bool) or
                not isinstance(receipt.get("usage_available"), bool) or
                not isinstance(receipt.get("usage_complete"), bool)):
            return {"status": "BLOCKED", "reason": "incomplete_g9_response_provenance",
                    "receipts": []}
        outcome = receipt.get("outcome")
        if outcome == "transport_error":
            if receipt.get("cost_label") != "error":
                return {"status": "BLOCKED", "reason": "invalid_g9_transport_error_cost",
                        "receipts": []}
            continue
        if outcome != "response":
            return {"status": "BLOCKED", "reason": "unsupported_g9_receipt_outcome",
                    "receipts": []}
        if receipt.get("cost_provenance") == "actual":
            amount = receipt.get("provider_reported_cost_usd")
            if (not _finite_number(amount) or amount < 0 or receipt.get("cost_usd") != amount or
                    receipt.get("cost_complete") is not True or receipt.get("cost_label") != "actual"):
                return {"status": "BLOCKED", "reason": "invalid_g9_reported_cost", "receipts": []}
        elif receipt.get("cost_provenance") == "estimated":
            amount = receipt.get("cost_usd")
            if (receipt.get("provider_reported_cost_usd") is not None or
                    not _finite_number(amount) or amount < 0 or
                    receipt.get("cost_complete") is not True or receipt.get("cost_label") != "estimated" or
                    receipt.get("resolved_model") in ("", "unknown", "openrouter/auto")):
                return {"status": "BLOCKED", "reason": "invalid_g9_estimated_cost", "receipts": []}
        elif receipt.get("cost_provenance") in ("unpriced", "unpriced_unknown"):
            if (receipt.get("provider_reported_cost_usd") is not None or
                    receipt.get("cost_usd") is not None or receipt.get("cost_complete") is not False or
                    receipt.get("cost_label") != "unpriced_unknown"):
                return {"status": "BLOCKED", "reason": "invalid_g9_unpriced_cost", "receipts": []}
        else:
            return {"status": "BLOCKED", "reason": "missing_g9_cost_provenance", "receipts": []}
        for name in ("prompt_tokens", "cached_tokens", "completion_tokens"):
            value = receipt.get(name)
            if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 0):
                return {"status": "BLOCKED", "reason": "invalid_g9_usage_count", "receipts": []}
        if receipt.get("usage_complete") is True and any(
                not isinstance(receipt.get(name), int) or isinstance(receipt.get(name), bool)
                or receipt.get(name) < 0
                for name in ("prompt_tokens", "cached_tokens", "completion_tokens")):
            return {"status": "BLOCKED", "reason": "incomplete_g9_usage_claim", "receipts": []}
    return {"status": "ok", "reason": None, "receipts": receipts,
            "counts": {"response_receipts": sum(row.get("outcome") == "response" for row in receipts),
                       "transport_errors": sum(row.get("outcome") == "transport_error" for row in receipts)}}


def g4_location_projection(snapshot: Any, expected_location_id: Any,
                           expected_roster: Any = None, expected_active: Any = None) -> Dict[str, Any]:
    """Compare the case-source room identity with persisted party snapshot fields."""
    records = snapshot.get("records", {}) if isinstance(snapshot, dict) else {}
    party = records.get("party_tracker.json", {}) if isinstance(records, dict) else {}
    projection = snapshot.get("g4_read_only_projection") if isinstance(snapshot, dict) else None
    observed_name = projection.get("currentLocation") if isinstance(projection, dict) else None
    observed_id = projection.get("currentLocationId") if isinstance(projection, dict) else None
    roster = projection.get("partyMembers") if isinstance(projection, dict) else None
    active = projection.get("active_character") if isinstance(projection, dict) else None
    valid = (party.get("status") == "ok" and isinstance(observed_name, str) and bool(observed_name)
             and isinstance(observed_id, str) and observed_id == expected_location_id
             and roster == expected_roster and active == expected_active)
    return {"status": "PASS" if valid else "BLOCKED", "expected_location_id": expected_location_id,
            "expected_roster": expected_roster, "expected_active_character": expected_active,
            "observed": {"currentLocation": observed_name, "currentLocationId": observed_id,
                         "partyMembers": roster, "active_character": active}}


def pair_g4_receipts(events: List[Dict[str, Any]], steps: List[Dict[str, Any]],
                     startup_span: Optional[Dict[str, Any]] = None,
                     scenario: Optional[str] = None) -> Dict[str, Any]:
    """Bind every actual adapter attempt to startup or one complete input span.

    Receipt events outside all declared spans are blockers; unlike the legacy
    generic trace linker, this G4 collector never silently drops unpaired rows.
    """
    receipts = [event for event in events if event.get("event_type") == "provider"]
    projection = project_g4_receipts(receipts)
    if projection["status"] != "ok":
        return projection
    spans = []
    if startup_span is not None:
        left, right = startup_span.get("offset_before_bytes"), startup_span.get("offset_after_bytes")
        if (startup_span.get("status") != "captured" or
                not isinstance(left, int) or isinstance(left, bool) or
                not isinstance(right, int) or isinstance(right, bool) or left < 0 or right < left):
            return {"status": "BLOCKED", "reason": "invalid_startup_receipt_span", "receipts": []}
        spans.append({"start": left, "end": right, "step": "startup", "input": None})
    for index, row in enumerate(steps, 1):
        before = (row.get("before") or {}).get("observation", {})
        after = (row.get("after") or {}).get("observation", {})
        left, right = before.get("runtimeTrace"), after.get("runtimeTrace")
        if (not isinstance(left, dict) or not isinstance(right, dict) or
                left.get("status") != "captured" or right.get("status") != "captured" or
                not isinstance(left.get("offset_bytes"), int) or isinstance(left.get("offset_bytes"), bool) or
                not isinstance(right.get("offset_bytes"), int) or isinstance(right.get("offset_bytes"), bool)):
            return {"status": "BLOCKED", "reason": "missing_step_positions", "receipts": []}
        start, end = left["offset_bytes"], right["offset_bytes"]
        if start < 0 or end < start or (spans and start < spans[-1]["end"]):
            return {"status": "BLOCKED", "reason": "invalid_or_overlapping_step_positions", "receipts": []}
        spans.append({"start": start, "end": end, "step": index, "input": before.get("input")})
    paired = []
    paired_legacy = []
    seen_positions = set()
    for event in receipts:
        start, end = event.get("_source_byte_start"), event.get("_source_byte_end")
        if (not isinstance(start, int) or isinstance(start, bool) or
                not isinstance(end, int) or isinstance(end, bool) or end <= start):
            return {"status": "BLOCKED", "reason": "missing_event_positions", "receipts": []}
        if (start, end) in seen_positions:
            return {"status": "BLOCKED", "reason": "duplicate_event_coverage", "receipts": []}
        seen_positions.add((start, end))
        matches = [span for span in spans if start >= span["start"] and end <= span["end"]]
        overlaps = [span for span in spans if start < span["end"] and end > span["start"]]
        if len(matches) != 1 or len(overlaps) != 1:
            return {"status": "BLOCKED", "reason": "receipt_unpaired_or_ambiguous", "receipts": []}
        span = matches[0]
        task = event.get("task")
        site = event.get("site")
        scenario_sites = ({"dm_main": {"main_dm", "transition_narration"},
                           "dm_validation": {"main_validation"}}
                          if scenario == "narrator-dialogue-travel" else
                          {"combat_main": {"combat_main"},
                           "combat_validation": {"combat_validation"},
                           "compression": {"combat_compression"}})
        if (site == "combat_compression" and
                not _has_router_attempt_identity(event)):
            if task is not None:
                return {"status": "BLOCKED", "reason": "core_task_spoofed_as_legacy", "receipts": []}
        elif scenario and site not in scenario_sites.get(task, set()):
            return {"status": "BLOCKED", "reason": "unknown_or_mismatched_receipt_site", "receipts": []}
        allowed_tasks = ({"dm_main", "dm_validation"} if scenario == "narrator-dialogue-travel"
                         else {"combat_main", "combat_validation", "combat_summary", "compression"})
        if scenario and site != "combat_compression" and task not in allowed_tasks:
            return {"status": "BLOCKED", "reason": "receipt_task_outside_scenario_scope", "receipts": []}
        if (site != "combat_compression" and scenario == "combat-smoke" and
                span["step"] != "startup" and
                str(span["input"] or "").lstrip().startswith(("/att", "/dmg"))):
            return {"status": "BLOCKED", "reason": "receipt_on_deterministic_combat_fast_path", "receipts": []}
        clean = {key: value for key, value in event.items() if not key.startswith("_source_")}
        if (event.get("site") == "combat_compression" and
                not _has_router_attempt_identity(event)):
            clean.update({"classification": "known_unmigrated_compression_observation",
                          "provider": "unknown", "model": "unknown", "cost": "unknown",
                          "identity_status": "no_router_attempt_identity"})
            paired_legacy.append({"step": span["step"], "observation": clean,
                                  "source_byte_start": start, "source_byte_end": end,
                                  "source_line": event.get("_source_line")})
            continue
        cost = clean.get("provider_reported_cost_usd")
        clean["cost_label"] = ("actual" if cost is not None else
                                "estimated" if clean.get("cost_provenance") == "estimated" else
                                "unpriced_unknown")
        paired.append({"step": span["step"], "receipt": clean})
    return {"status": "ok", "reason": None, "receipts": paired,
            "legacy_observations": paired_legacy,
            "counts": {"core_receipts": len(paired),
                       "legacy_provider_observations": len(paired_legacy),
                       "trace_provider_rows": len(paired) + len(paired_legacy)}}


_EXCHANGE_RATE_KEY_URL_RE = re.compile(
    rb"(?i)(?:^|[^A-Za-z0-9_.-])(?:[A-Za-z0-9-]+\.)*exchangerate-api\.com"
    rb"(?::[0-9]+)?[^\r\n]{0,1024}/v6/[^/?#\s\"']+/"
)


def _contains_exchange_rate_key_url(raw: bytes) -> bool:
    """Detect ExchangeRate-API v6 URLs whose key is embedded in a path segment."""
    candidate = raw
    for _ in range(4):
        if _EXCHANGE_RATE_KEY_URL_RE.search(candidate):
            return True
        decoded = unquote_to_bytes(candidate)
        if decoded == candidate:
            break
        candidate = decoded
    return False


def server_log_safety(path: Path) -> tuple[bool, str]:
    """Reject unsafe/unreadable logs rather than copying credential/config values."""
    raw, error = _safe_read_bytes(Path(path), PROJECT_TMP)
    if error or raw is None:
        return False, error or "unreadable"
    patterns = (
        rb"(?im)^\s*(OPENAI_API_KEY|OPENROUTER_API_KEY|LLM_PROVIDER|ACTIVE_PROFILE|COMBAT_MAIN_MODEL|DM_MAIN_MODEL)\s*[:=]",
        rb"(?i)\bBearer\s+\S+",
        rb"\bsk-[A-Za-z0-9_-]{16,}\b",
    )
    if any(re.search(pattern, raw) for pattern in patterns):
        return False, "credential_or_configuration_value_detected"
    if _contains_exchange_rate_key_url(raw):
        return False, "credential_or_configuration_value_detected"
    return True, "safe"


def _atomic_replace_evidence_file(destination: Path, raw: bytes, root: Path) -> None:
    """Replace one already-owned evidence artifact atomically below its bundle."""
    destination = Path(destination)
    root = Path(root)
    if (not _inside(destination, root) or _has_symlink_component(destination, root) or
            not _inside(destination.parent, root)):
        raise ValueError("evidence destination is outside its owned bundle")
    temporary = destination.with_name(destination.name + ".finalize")
    if temporary.exists() or temporary.is_symlink():
        raise ValueError("evidence finalization temporary already exists")
    try:
        with temporary.open("xb") as handle:
            handle.write(raw)
        os.replace(temporary, destination)
    except OSError:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise


def finalize_g9_capture_bundle(run_dir: Path, lifecycle_log: Path, server_log: Path,
                               rollback_server_log: Optional[Path] = None) -> Dict[str, Any]:
    """Bind post-stop lifecycle and complete server logs after owned teardown."""
    run_dir = Path(run_dir)
    lifecycle_log = Path(lifecycle_log)
    if (not _inside(run_dir, G9_RUN_ROOT) or run_dir.resolve() == G9_RUN_ROOT.resolve() or
            _has_symlink_component(run_dir, PROJECT_TMP) or not run_dir.is_dir()):
        raise ValueError("G9 finalization requires an existing safe run bundle")
    if not _inside(lifecycle_log, PROJECT_TMP) or _has_symlink_component(lifecycle_log, PROJECT_TMP):
        raise ValueError("G9 lifecycle log must be a non-symlink project tmp path")
    server_log = Path(server_log)
    if not _inside(server_log, PROJECT_TMP) or _has_symlink_component(server_log, PROJECT_TMP):
        raise ValueError("G9 owned server log must be a non-symlink project tmp path")
    manifest, error = load_bundle_json(run_dir, "manifest.json")
    if error or not isinstance(manifest, dict) or manifest.get("gate") != "g9":
        raise ValueError("G9 finalization requires a G9 manifest")
    lifecycle_raw, lifecycle_error = _safe_read_bytes(lifecycle_log, PROJECT_TMP)
    if lifecycle_error or lifecycle_raw is None:
        raise ValueError("G9 lifecycle log is unreadable: %s" % (lifecycle_error or "missing"))
    lifecycle_safe, lifecycle_reason = server_log_safety(lifecycle_log)
    if not lifecycle_safe:
        raise ValueError("G9 lifecycle log is unsafe: %s" % lifecycle_reason)
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict):
        raise ValueError("G9 manifest artifacts are malformed")
    lifecycle_ref = artifacts.get("server_lifecycle")
    lifecycle_path, lifecycle_ref_error = _bundle_file(run_dir, lifecycle_ref)
    if lifecycle_ref_error or lifecycle_path is None or lifecycle_ref != "server_lifecycle.jsonl":
        raise ValueError("G9 bundle has no initial lifecycle artifact")

    if artifacts.get("server_log") != "server.log":
        raise ValueError("G9 bundle has no owned server log artifact")
    server_safe, server_reason = server_log_safety(server_log)
    if not server_safe:
        raise ValueError("G9 owned server log is unsafe: %s" % server_reason)
    server_raw, server_read_error = _safe_read_bytes(server_log, PROJECT_TMP)
    if server_read_error or server_raw is None:
        raise ValueError("G9 owned server log is unreadable: %s" % (server_read_error or "missing"))
    server_path, server_ref_error = _bundle_file(run_dir, artifacts.get("server_log"))
    if server_ref_error or server_path is None:
        raise ValueError("G9 bundle server log artifact is unreadable")
    _atomic_replace_evidence_file(server_path, server_raw, run_dir)
    server_payloads = {"server.log": server_raw}

    phase = (manifest.get("scenario") or {}).get("phase")
    if phase == "rollback":
        if rollback_server_log is None:
            raise ValueError("G9 rollback finalization requires the pre-restart server log")
        rollback_server_log = Path(rollback_server_log)
        if (not _inside(rollback_server_log, PROJECT_TMP) or
                _has_symlink_component(rollback_server_log, PROJECT_TMP)):
            raise ValueError("G9 pre-restart server log must be a non-symlink project tmp path")
        safe, reason = server_log_safety(rollback_server_log)
        if not safe:
            raise ValueError("G9 pre-restart server log is unsafe: %s" % reason)
        rollback_raw, read_error = _safe_read_bytes(rollback_server_log, PROJECT_TMP)
        if read_error or rollback_raw is None:
            raise ValueError("G9 pre-restart server log is unreadable: %s" % (read_error or "missing"))
        rollback_ref = artifacts.get("rollback_server_log")
        rollback_path, rollback_ref_error = _bundle_file(run_dir, rollback_ref)
        if (rollback_ref_error or rollback_path is None or
                rollback_ref != "server_before_rollback.log"):
            raise ValueError("G9 rollback bundle has no pre-restart server log artifact")
        _atomic_replace_evidence_file(rollback_path, rollback_raw, run_dir)
        server_payloads[rollback_ref] = rollback_raw
    elif rollback_server_log is not None:
        raise ValueError("G9 pre-restart server log applies only to rollback rows")

    try:
        lifecycle_events = [json.loads(line) for line in lifecycle_raw.decode("ascii").splitlines()
                            if line.strip()]
        if any(not isinstance(event, dict) for event in lifecycle_events):
            raise ValueError("lifecycle event is not an object")
    except (UnicodeError, ValueError) as exc:
        raise ValueError("G9 lifecycle log is malformed") from exc
    expected_stop_logs = ([("server_before_rollback.log", server_payloads["server_before_rollback.log"]),
                           ("server.log", server_payloads["server.log"])] if phase == "rollback" else
                          [("server.log", server_payloads["server.log"])])
    stop_index = 0
    for event in lifecycle_events:
        if event.get("event") != "server_stopped":
            continue
        if stop_index >= len(expected_stop_logs):
            raise ValueError("G9 lifecycle has an unexpected server stop")
        log_ref, log_raw = expected_stop_logs[stop_index]
        if event.get("server_log_artifact") != log_ref:
            raise ValueError("G9 lifecycle server log binding does not match its stop")
        event["server_log_sha256"] = hashlib.sha256(log_raw).hexdigest()
        event["server_log_bytes"] = len(log_raw)
        stop_index += 1
    if stop_index != len(expected_stop_logs):
        raise ValueError("G9 lifecycle is missing a required server stop")
    lifecycle_raw = ("".join(json.dumps(event, ensure_ascii=True, sort_keys=True,
                                         separators=(",", ":")) + "\n"
                              for event in lifecycle_events).encode("ascii"))
    _atomic_replace_evidence_file(lifecycle_path, lifecycle_raw, run_dir)

    g9_metadata = manifest.get("g9")
    if not isinstance(g9_metadata, dict):
        raise ValueError("G9 manifest metadata is malformed")
    g9_metadata["lifecycle"] = {
        "status": "finalized",
        "artifact": lifecycle_ref,
        "sha256": hashlib.sha256(lifecycle_raw).hexdigest(),
    }
    hashes = hash_artifacts(run_dir, artifacts)
    manifest["artifact_sha256"] = hashes
    manifest_path = run_dir / "manifest.json"
    manifest_raw = (json.dumps(manifest, ensure_ascii=True, sort_keys=True, indent=2) + "\n").encode("utf-8")
    _atomic_replace_evidence_file(manifest_path, manifest_raw, run_dir)
    return {"status": "finalized", "run_id": run_dir.name,
            "lifecycle_sha256": hashlib.sha256(lifecycle_raw).hexdigest(),
            "server_log_sha256": hashlib.sha256(server_raw).hexdigest(),
            "artifact_count": len(hashes)}


def finalize_g10_capture_bundle(run_dir: Path, lifecycle_log: Path,
                                server_log: Path, state_root: Path) -> Dict[str, Any]:
    """Bind one complete/resume phase to its stopped, orchestrator-owned server."""
    run = Path(run_dir)
    if (not _inside(run, G10_RUN_ROOT) or run.resolve() == G10_RUN_ROOT.resolve() or
            _has_symlink_component(run, PROJECT_TMP) or not run.is_dir()):
        raise ValueError("G10 finalization requires an existing safe run bundle")
    sandbox = Path(state_root)
    expected_sandbox = PROJECT_TMP / "combat_capture"
    if (not _inside(sandbox, PROJECT_TMP) or sandbox.resolve() != expected_sandbox.resolve() or
            _has_symlink_component(sandbox, PROJECT_TMP) or not sandbox.is_dir()):
        raise ValueError("G10 finalization requires the isolated tmp/combat_capture sandbox")
    lifecycle = Path(lifecycle_log)
    server = Path(server_log)
    for label, path in (("lifecycle", lifecycle), ("server", server)):
        if not _inside(path, PROJECT_TMP) or _has_symlink_component(path, PROJECT_TMP):
            raise ValueError("G10 %s log must be a non-symlink project tmp path" % label)
    manifest, error = load_bundle_json(run, "manifest.json")
    if error or not isinstance(manifest, dict) or manifest.get("gate") != "g10":
        raise ValueError("G10 finalization requires a G10 manifest")
    artifacts = manifest.get("artifacts")
    g10 = manifest.get("g10")
    if not isinstance(artifacts, dict) or not isinstance(g10, dict):
        raise ValueError("G10 manifest metadata is malformed")
    if artifacts.get("server_lifecycle") != "server_lifecycle.jsonl" or artifacts.get("server_log") != "server.log":
        raise ValueError("G10 bundle has no expected lifecycle/server-log artifact bindings")
    captured_hashes = manifest.get("artifact_sha256")
    if not isinstance(captured_hashes, dict):
        raise ValueError("G10 capture manifest has no pre-finalization artifact hashes")
    required_hash_names = {"g10_usage", "g10_save_state", "g10_tracker_telemetry"}
    hash_names = (
        "transcript", "trace", "report", "before_snapshot", "after_snapshot",
        "g10_marker", "g10_usage", "g10_save_state", "g10_tracker_telemetry",
    )
    references = [(name, artifacts.get(name)) for name in hash_names]
    step_refs = artifacts.get("step_snapshots", [])
    if isinstance(step_refs, list):
        references.extend(("step_snapshot", reference) for reference in step_refs)
    for name, reference in references:
        if reference is None:
            if name in required_hash_names:
                raise ValueError("G10 required pre-finalization artifact reference is missing: %s" % name)
            continue
        artifact_path, artifact_path_error = _bundle_file(run, reference)
        if artifact_path_error or artifact_path is None:
            if name in required_hash_names:
                raise ValueError("G10 required pre-finalization artifact is missing: %s" % name)
            continue
        artifact_raw, artifact_read_error = _safe_read_bytes(artifact_path, run)
        if artifact_read_error or artifact_raw is None:
            if name in required_hash_names:
                raise ValueError("G10 required pre-finalization artifact is unreadable: %s" % name)
            continue
        expected_hash = captured_hashes.get(reference)
        if (not isinstance(expected_hash, str) or
                not _G10_TRACKER_DIGEST_RE.fullmatch(expected_hash) or
                hashlib.sha256(artifact_raw).hexdigest() != expected_hash):
            raise ValueError("G10 pre-finalization artifact hash mismatch: %s" % name)
    lifecycle_raw, lifecycle_error = _safe_read_bytes(lifecycle, PROJECT_TMP)
    server_raw, server_error = _safe_read_bytes(server, PROJECT_TMP)
    if lifecycle_error or lifecycle_raw is None:
        raise ValueError("G10 lifecycle log is unreadable: %s" % (lifecycle_error or "missing"))
    if server_error or server_raw is None:
        raise ValueError("G10 owned server log is unreadable: %s" % (server_error or "missing"))
    safe, reason = server_log_safety(lifecycle)
    if not safe:
        raise ValueError("G10 lifecycle log is unsafe: %s" % reason)
    safe, reason = server_log_safety(server)
    if not safe:
        raise ValueError("G10 owned server log is unsafe: %s" % reason)
    try:
        events = [json.loads(line) for line in lifecycle_raw.decode("ascii").splitlines() if line.strip()]
        if any(not isinstance(event, dict) for event in events):
            raise ValueError("not_object")
    except (UnicodeError, ValueError) as exc:
        raise ValueError("G10 lifecycle log is malformed") from exc

    scenario = manifest.get("scenario") if isinstance(manifest.get("scenario"), dict) else {}
    party = manifest.get("party") if isinstance(manifest.get("party"), dict) else {}
    row_key = g10.get("row_key")
    phase = scenario.get("phase")
    expected_events = (["prepare", "server_started", "capture_completed", "server_stopped"]
                       if phase == "complete" else
                       ["resume_server_started", "capture_completed", "server_stopped"]
                       if phase == "resume" else [])
    if not expected_events or [event.get("event") for event in events] != expected_events:
        raise ValueError("G10 lifecycle event order does not match the fixed phase contract")
    identity = {
        "gate": "g10", "row_key": row_key, "run_id": manifest.get("run_id"),
        "phase": phase, "party_size": party.get("size"),
        "chain_id": manifest.get("chain_id"), "seed_id": (manifest.get("seed") or {}).get("seed_id"),
        "sandbox_id": manifest.get("sandbox_id"),
        "source_head": (manifest.get("source") or {}).get("head"),
        "relevant_dirty_sha256": (manifest.get("source") or {}).get("relevant_dirty_sha256"),
    }
    if any(not identity.get(key) for key in ("row_key", "run_id", "chain_id", "seed_id",
                                               "source_head", "relevant_dirty_sha256")):
        raise ValueError("G10 manifest cannot bind lifecycle to source/seed/run identity")
    if any(any(event.get(key) != value for key, value in identity.items()) for event in events):
        raise ValueError("G10 lifecycle identity does not match its evidence manifest")
    start_name = "server_started" if phase == "complete" else "resume_server_started"
    start = events[1] if phase == "complete" and len(events) > 1 else events[0]
    stop = events[-1]
    launch_epoch = start.get("server_launch_epoch")
    if (start.get("event") != start_name or
            not _g10_usage_value_bounded(launch_epoch, 10 ** 12) or
            not isinstance(start.get("server_pid"), int) or
            isinstance(start.get("server_pid"), bool) or
            not isinstance(stop.get("server_pid"), int) or
            isinstance(stop.get("server_pid"), bool) or
            stop.get("server_pid") != start.get("server_pid") or
            stop.get("port") != 8360 or stop.get("remaining_listener_pids") != [] or
            stop.get("server_log_artifact") != "server.log"):
        raise ValueError("G10 lifecycle stop must bind server.log")
    stop["server_log_sha256"] = hashlib.sha256(server_raw).hexdigest()
    stop["server_log_bytes"] = len(server_raw)
    lifecycle_raw = "".join(
        json.dumps(event, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n"
        for event in events
    ).encode("ascii")
    server_target, server_ref_error = _bundle_file(run, artifacts["server_log"])
    lifecycle_target, lifecycle_ref_error = _bundle_file(run, artifacts["server_lifecycle"])
    if server_ref_error or server_target is None or lifecycle_ref_error or lifecycle_target is None:
        raise ValueError("G10 bundle log artifact is missing or unsafe")
    _atomic_replace_evidence_file(server_target, server_raw, run)
    _atomic_replace_evidence_file(lifecycle_target, lifecycle_raw, run)
    g10["lifecycle"] = {"status": "finalized", "artifact": "server_lifecycle.jsonl",
                         "sha256": hashlib.sha256(lifecycle_raw).hexdigest()}
    try:
        from scripts import combat_latency_fixtures

        profile = combat_latency_fixtures.build_gate_profile(
            "g10", scenario.get("id"), party.get("size"), phase=phase
        )
    except (TypeError, ValueError, KeyError) as exc:
        raise ValueError("G10 finalization cannot reconstruct its fixed profile") from exc
    step_rows, step_errors = load_step_snapshots(run, manifest)
    usage_artifact, usage_error = load_bundle_json(run, artifacts.get("g10_usage"))
    save_state, save_error = load_bundle_json(run, artifacts.get("g10_save_state"))
    tracker_artifact, tracker_error = load_bundle_json(
        run, artifacts.get("g10_tracker_telemetry")
    )
    if (usage_error or save_error or tracker_error or usage_artifact is None or
            save_state is None or tracker_artifact is None):
        raise ValueError("G10 finalization cannot derive checks from missing usage/save evidence")
    if (artifacts.get("g10_tracker_telemetry") != "g10_tracker_telemetry.json" or
            not isinstance(tracker_artifact, dict) or
            tracker_artifact.get("phase") != phase or
            tracker_artifact.get("run_id") != manifest.get("run_id") or
            tracker_artifact.get("chain_id") != manifest.get("chain_id") or
            tracker_artifact.get("seed_id") != (manifest.get("seed") or {}).get("seed_id") or
            tracker_artifact.get("sandbox_id") != manifest.get("sandbox_id")):
        raise ValueError("G10 tracker artifact identity does not match the phase manifest")
    pre_run = tracker_artifact.get("pre_run")
    post_usage = tracker_artifact.get("post_usage")
    post_source = post_usage.get("source") if isinstance(post_usage, dict) else None
    if (not isinstance(pre_run, dict) or not isinstance(post_usage, dict) or
            not isinstance(post_source, dict) or type(post_source.get("bytes")) is not int or
            not isinstance(post_source.get("sha256"), str) or
            not _G10_TRACKER_DIGEST_RE.fullmatch(post_source.get("sha256", ""))):
        terminal_snapshot = {"status": "BLOCKED",
                             "problems": ["tracker_post_usage_boundary_missing"]}
    else:
        terminal_snapshot = capture_g10_tracker_snapshot(
            sandbox, prefix_bytes=post_source["bytes"],
            prefix_sha256=post_source["sha256"],
        )
    tracker_artifact["post_shutdown"] = terminal_snapshot
    tracker_artifact["server_launch_epoch"] = float(launch_epoch)
    tracker_artifact["status"] = (
        "captured" if terminal_snapshot.get("status") == "captured" and
        isinstance(pre_run, dict) and pre_run.get("status") == "captured" and
        isinstance(post_usage, dict) and post_usage.get("status") == "captured"
        else "BLOCKED"
    )
    trace_path, trace_error = _bundle_file(run, artifacts.get("trace"))
    trace_span = manifest.get("trace_span", {})
    trace_offset = trace_span.get("offset_before_bytes", 0) if isinstance(trace_span, dict) else 0
    if (trace_error or trace_path is None or not isinstance(trace_offset, int) or
            isinstance(trace_offset, bool) or trace_offset < 0):
        positioned, position_errors = [], ["g10_finalizer_trace_unavailable"]
    else:
        positioned, position_errors = parse_trace_positions(trace_path, trace_offset)
    usage_capture = usage_artifact.get("usage_capture")
    observed_usage = (project_g10_usage_observations(
        usage_capture.get("usage_events"), usage_capture.get("debug_token_updates")
    ) if isinstance(usage_capture, dict) else {
        "status": "BLOCKED", "problems": ["g10_raw_usage_capture_missing"]
    })
    derived_receipts = project_g10_receipts(positioned, manifest.get("run_id", ""))
    if position_errors:
        derived_receipts = {"status": "BLOCKED", "reason": "trace_position_parse_error",
                            "receipts": []}
    tracker_projection = project_g10_tracker_telemetry(
        tracker_artifact, observed_usage, derived_receipts
    )
    usage_artifact["observed"] = observed_usage
    usage_artifact["router_receipts"] = derived_receipts
    usage_artifact["tracker_reconciliation"] = tracker_projection
    tracker_path, tracker_ref_error = _bundle_file(
        run, artifacts.get("g10_tracker_telemetry")
    )
    if tracker_ref_error or tracker_path is None:
        raise ValueError("G10 tracker telemetry artifact is unsafe")
    tracker_raw = (json.dumps(tracker_artifact, ensure_ascii=True, sort_keys=True,
                              indent=2) + "\n").encode("utf-8")
    _atomic_replace_evidence_file(tracker_path, tracker_raw, run)
    validation = revalidate_g10_usage_artifact(
        profile, manifest, step_rows, usage_artifact, positioned, position_errors,
        tracker_artifact,
    )
    usage_artifact["router_receipt_reconciliation_problems"] = validation.get(
        "reconciliation_problems", ["g10_usage_reconciliation_unavailable"]
    )
    usage_artifact["status"] = validation.get("expected_status", "BLOCKED")
    usage_artifact["finalizer_validation_problems"] = sorted(set(
        validation.get("problems", []) + validation.get("failures", [])
    ))
    usage_path, usage_ref_error = _bundle_file(run, artifacts.get("g10_usage"))
    if usage_ref_error or usage_path is None:
        raise ValueError("G10 usage artifact is unsafe")
    usage_raw = (json.dumps(usage_artifact, ensure_ascii=True, sort_keys=True,
                            indent=2) + "\n").encode("utf-8")
    _atomic_replace_evidence_file(usage_path, usage_raw, run)
    g10["usage"] = {"status": usage_artifact["status"],
                     "artifact": artifacts.get("g10_usage")}
    checks = build_g10_checks(profile, manifest, step_rows, step_errors,
                              usage_artifact, save_state, "finalized")
    checks_path, checks_error = _bundle_file(run, artifacts.get("checks"))
    if checks_error or checks_path is None:
        raise ValueError("G10 finalization cannot update the derived checks artifact")
    prior_checks, prior_checks_error = load_bundle_json(run, artifacts.get("checks"))
    if prior_checks_error or not isinstance(prior_checks, dict) or not isinstance(
            prior_checks.get("checks"), list):
        raise ValueError("G10 finalization cannot preserve the capture-time checks")
    g10_check_ids = {row.get("id") for row in checks if isinstance(row, dict)}
    retained_checks = [row for row in prior_checks["checks"]
                       if isinstance(row, dict) and row.get("id") not in g10_check_ids]
    checks_raw = (json.dumps({"checks": retained_checks + checks, "primary_verdict": "PENDING"},
                             ensure_ascii=True, sort_keys=True, indent=2) + "\n").encode("utf-8")
    _atomic_replace_evidence_file(checks_path, checks_raw, run)
    manifest["artifact_sha256"] = hash_artifacts(run, artifacts)
    manifest_raw = (json.dumps(manifest, ensure_ascii=True, sort_keys=True, indent=2) + "\n").encode("utf-8")
    _atomic_replace_evidence_file(run / "manifest.json", manifest_raw, run)
    return {"status": "finalized", "run_id": manifest.get("run_id"),
            "lifecycle_sha256": hashlib.sha256(lifecycle_raw).hexdigest(),
            "server_log_sha256": hashlib.sha256(server_raw).hexdigest(),
            "artifact_count": len(manifest["artifact_sha256"])}


def read_sandbox_trace_gate(state_root: Path) -> Dict[str, Any]:
    """Read only the public trace-gate literal from the selected sandbox AST."""
    root = Path(state_root)
    path = root / "model_config.py"
    raw, error = _safe_read_bytes(path, root)
    if error or raw is None:
        return {"status": "unknown", "enabled": None, "reason": error or "missing"}
    try:
        tree = ast.parse(raw.decode("utf-8"))
        values = []
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and
                    target.id == "ENABLE_COMBAT_TURN_TRACE" for target in node.targets):
                if isinstance(node.value, ast.Constant) and isinstance(node.value.value, bool):
                    values.append(node.value.value)
        if len(values) != 1:
            return {"status": "unknown", "enabled": None, "reason": "trace_gate_literal_not_unique"}
        return {"status": "ok", "enabled": values[0],
                "model_config_sha256": hashlib.sha256(raw).hexdigest(),
                "provenance": "sandbox model_config.py AST literal"}
    except (UnicodeError, SyntaxError):
        return {"status": "unknown", "enabled": None, "reason": "trace_gate_ast_invalid"}


def capture_trace_start(source: Path, state_root: Path) -> Dict[str, Any]:
    """Capture trace offset and prefix identity immediately before start_game."""
    source, root = Path(source), Path(state_root)
    raw, error = _safe_read_bytes(source, root)
    if error == "unreadable:FileNotFoundError":
        raw, error = b"", None
        existed = False
    elif error:
        return {"status": "invalid_source", "error": error}
    else:
        existed = True
    raw = raw or b""
    file_identity = None
    if existed:
        try:
            stat = source.stat()
            file_identity = {"device": stat.st_dev, "inode": stat.st_ino}
        except OSError:
            return {"status": "stat_failed", "offset_bytes": len(raw),
                    "prefix_sha256": hashlib.sha256(raw).hexdigest()}
    return {"status": "captured", "existed": existed, "offset_bytes": len(raw),
            "prefix_sha256": hashlib.sha256(raw).hexdigest(),
            "file_identity": file_identity,
            "source_sha256_before": hashlib.sha256(raw).hexdigest() if existed else None}


def trace_byte_offset(source: Path, state_root: Path) -> Dict[str, Any]:
    """Return the current safe source byte offset for a scripted step boundary."""
    raw, error = _safe_read_bytes(Path(source), Path(state_root))
    if error == "unreadable:FileNotFoundError":
        return {"status": "captured", "offset_bytes": 0}
    if error or raw is None:
        return {"status": "unavailable", "reason": error or "unreadable"}
    return {"status": "captured", "offset_bytes": len(raw)}


def read_trace_records_since(
    source: Path, state_root: Path, offset_bytes: int, max_bytes: int = 262144
) -> Dict[str, Any]:
    """Read a bounded JSONL trace suffix below the capture sandbox root."""
    path = Path(source)
    root = Path(state_root)
    if (isinstance(offset_bytes, bool) or not isinstance(offset_bytes, int) or
            offset_bytes < 0):
        return {"status": "unavailable", "reason": "invalid_offset",
                "records": [], "offset_bytes": 0}
    if (isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or
            max_bytes < 1 or max_bytes > 1048576):
        return {"status": "unavailable", "reason": "invalid_read_bound",
                "records": [], "offset_bytes": offset_bytes}
    if not _inside(path, root) or _has_symlink_component(path, root):
        return {"status": "unavailable", "reason": "unsafe_path",
                "records": [], "offset_bytes": offset_bytes}

    try:
        with path.open("rb") as handle:
            file_size = os.fstat(handle.fileno()).st_size
            if offset_bytes > file_size:
                return {"status": "unavailable", "reason": "offset_after_eof",
                        "records": [], "offset_bytes": offset_bytes}
            handle.seek(offset_bytes)
            chunk = handle.read(max_bytes)
        if not _inside(path.resolve(), root.resolve()) or _has_symlink_component(path, root):
            return {"status": "unavailable", "reason": "unsafe_path",
                    "records": [], "offset_bytes": offset_bytes}
    except FileNotFoundError:
        return {"status": "captured", "records": [], "offset_bytes": offset_bytes}
    except OSError as error:
        return {"status": "unavailable", "reason": "unreadable:%s" % type(error).__name__,
                "records": [], "offset_bytes": offset_bytes}

    final_newline = chunk.rfind(b"\n")
    if final_newline < 0:
        return {"status": "captured", "records": [], "offset_bytes": offset_bytes}
    complete_bytes = chunk[:final_newline + 1]
    records = []
    for line in complete_bytes.splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line.decode("utf-8"))
        except (UnicodeError, ValueError):
            continue
        if isinstance(record, dict):
            records.append(record)
    return {"status": "captured", "records": records,
            "offset_bytes": offset_bytes + len(complete_bytes)}


def parse_trace_positions(path: Path, source_offset: int = 0) -> tuple[List[Dict[str, Any]], List[str]]:
    """Parse JSONL while preserving half-open source byte spans for each record."""
    records: List[Dict[str, Any]] = []
    errors: List[str] = []
    try:
        raw = Path(path).read_bytes()
    except OSError as error:
        return [], ["trace_read:%s" % type(error).__name__]
    cursor = 0
    for line_number, line in enumerate(raw.splitlines(keepends=True), 1):
        start = cursor
        cursor += len(line)
        if not line.strip():
            continue
        try:
            event = json.loads(line.decode("ascii"))
        except (UnicodeError, ValueError):
            errors.append("trace_malformed_line:%d" % line_number)
            continue
        if not isinstance(event, dict):
            errors.append("trace_non_object_line:%d" % line_number)
            continue
        records.append({**event, "_source_byte_start": source_offset + start,
                        "_source_byte_end": source_offset + cursor,
                        "_source_line": line_number})
    if cursor != len(raw):
        errors.append("trace_span_trailing_bytes")
    return records, errors


def link_trace_events_to_steps(events: List[Dict[str, Any]], steps: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Link observations only when one complete source span lies in one step span."""
    spans = []
    for index, row in enumerate(steps, 1):
        before = (row.get("before") or {}).get("observation", {})
        after = (row.get("after") or {}).get("observation", {})
        left, right = before.get("runtimeTrace"), after.get("runtimeTrace")
        if (not isinstance(left, dict) or not isinstance(right, dict) or
                left.get("status") != "captured" or right.get("status") != "captured" or
                not isinstance(left.get("offset_bytes"), int) or isinstance(left.get("offset_bytes"), bool) or
                not isinstance(right.get("offset_bytes"), int) or isinstance(right.get("offset_bytes"), bool)):
            return {"status": "BLOCKED", "reason": "missing_step_positions", "steps": [], "events": []}
        start, end = left["offset_bytes"], right["offset_bytes"]
        if start < 0 or end < start:
            return {"status": "BLOCKED", "reason": "invalid_or_overlapping_step_positions", "steps": [], "events": []}
        if spans and start < spans[-1]["end"]:
            return {"status": "BLOCKED", "reason": "overlapping_step_positions", "steps": [], "events": []}
        spans.append({"step": index, "start": start, "end": end,
                      "actor": before.get("character"), "input": before.get("input")})
    linked = []
    seen_spans = set()
    for event in events:
        start, end = event.get("_source_byte_start"), event.get("_source_byte_end")
        if (not isinstance(start, int) or isinstance(start, bool) or
                not isinstance(end, int) or isinstance(end, bool) or end <= start):
            return {"status": "BLOCKED", "reason": "missing_event_positions", "steps": spans, "events": []}
        if (start, end) in seen_spans:
            return {"status": "BLOCKED", "reason": "duplicate_event_coverage", "steps": spans, "events": []}
        seen_spans.add((start, end))
        overlaps = [span for span in spans if start < span["end"] and end > span["start"]]
        containing = [span for span in spans if start >= span["start"] and end <= span["end"]]
        if overlaps and len(containing) != 1:
            return {"status": "BLOCKED", "reason": "partial_or_ambiguous_event_span", "steps": spans, "events": []}
        if len(containing) == 1:
            linked.append({"event": event, "step": containing[0]["step"]})
        elif _is_hp_causal_event(event):
            return {"status": "BLOCKED", "reason": "hp_event_outside_step_span", "steps": spans, "events": []}
    return {"status": "PASS", "reason": None, "steps": spans, "events": linked}


def _is_hp_causal_event(event: Dict[str, Any]) -> bool:
    """Identify only trace events capable of establishing or applying HP mutation."""
    if event.get("event_type") == "decision":
        return event.get("decision_point") == "combat_command_fast_path"
    if event.get("observation") != "combat_apply_result":
        return False
    # Apply results in character/encounter domains can mutate HP even when their
    # operation payload is missing or uses an unknown operation name.
    return event.get("domain") in ("character", "encounter")


def preserve_trace_span(source: Path, destination: Path, state_root: Path,
                        start: Dict[str, Any]) -> Dict[str, Any]:
    """Copy only the trace suffix appended since the per-run pre-start offset."""
    source, destination, root = Path(source), Path(destination), Path(state_root)
    result = {"status": "unavailable", "offset_before_bytes": start.get("offset_bytes"),
              "prefix_sha256": start.get("prefix_sha256"), "span_bytes": 0,
              "source_sha256_before": start.get("source_sha256_before"),
              "source_file_identity_before": start.get("file_identity"),
              "source_sha256_after": None, "span_sha256": None,
              "source_records": 0, "destination_records": 0,
              "start_status": start.get("status"), "source_existed_before": start.get("existed"),
              "source_reset_detected": False, "prefix_changed": False,
              "source_exists_after": None}
    raw, error = _safe_read_bytes(source, root)
    source_missing_after = (error == "unreadable:FileNotFoundError" and start.get("existed") is False)
    if source_missing_after:
        raw, error = b"", None
    if error or raw is None:
        result.update({"status": "source_missing_or_unsafe", "error": error or "missing"})
        return result
    offset = start.get("offset_bytes")
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        result["status"] = "invalid_offset"
        return result
    if start.get("existed") is True and len(raw) < offset:
        result["status"] = "source_reset_or_truncated"
        result["source_reset_detected"] = True
        result["source_bytes_after"] = len(raw)
        return result
    current_identity = None
    if start.get("existed") is True:
        try:
            stat = source.stat()
            current_identity = {"device": stat.st_dev, "inode": stat.st_ino}
        except OSError:
            result.update({"status": "source_stat_failed", "source_reset_detected": True})
            return result
        if start.get("file_identity") != current_identity:
            result.update({"status": "source_replaced", "source_reset_detected": True,
                           "source_file_identity_after": current_identity})
            return result
    elif not source_missing_after:
        try:
            stat = source.stat()
            current_identity = {"device": stat.st_dev, "inode": stat.st_ino}
        except OSError:
            result.update({"status": "source_stat_failed", "source_reset_detected": True})
            return result
    prefix = raw[:offset] if start.get("existed") is True else b""
    if hashlib.sha256(prefix).hexdigest() != start.get("prefix_sha256"):
        result["status"] = "source_prefix_changed"
        result["prefix_changed"] = True
        result["source_bytes_after"] = len(raw)
        return result
    span = raw[offset:]
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as handle:
            handle.write(span)
    except OSError as exc:
        result.update({"status": "copy_failed", "error": type(exc).__name__})
        return result
    line_count = sum(1 for line in span.splitlines() if line.strip())
    result.update({"status": "copied", "span_bytes": len(span),
                   "source_bytes_after": len(raw),
                   "source_exists_after": not source_missing_after,
                   "source_file_identity_after": current_identity,
                   "source_sha256_after": hashlib.sha256(raw).hexdigest() if not source_missing_after else None,
                   "span_sha256": hashlib.sha256(span).hexdigest(),
                   "source_records": line_count, "destination_records": line_count,
                   "empty_span": len(span) == 0})
    return result


def _source_identity() -> Dict[str, Any]:
    try:
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT,
                              check=True, capture_output=True, text=True).stdout.strip()
        roots = ("core/combat", "core/managers/combat_manager.py", "core/managers/multi_pc_combat.py",
                 "core/managers/combat_state_sync.py", "core/managers/initiative_tracker_ai.py",
                 "core/ai/action_handler.py", "main.py", "utils/combat_latency_trace.py",
                 "utils/ai_client_factory.py", "model_config.py", "scripts/capture_drive.py",
                 "scripts/capture_evidence.py", "scripts/combat_latency_report.py",
                 "scripts/combat_latency_fixtures.py", "scripts/seed_combat_capture.py")
        status = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all", "--", *roots], cwd=PROJECT_ROOT,
                                check=True, capture_output=True, text=True).stdout
        dirty_paths = sorted({line[3:] for line in status.splitlines() if len(line) > 3})
        source_paths = set(dirty_paths)
        combat_root = PROJECT_ROOT / "core" / "combat"
        if combat_root.is_dir():
            source_paths.update(path.relative_to(PROJECT_ROOT).as_posix()
                                for path in combat_root.rglob("*.py") if path.is_file())
        for value in roots:
            candidate = PROJECT_ROOT / value
            if candidate.is_file() and candidate.suffix == ".py":
                source_paths.add(value)
        hashes: Dict[str, str] = {}
        for rel in sorted(source_paths):
            candidate = PROJECT_ROOT / rel
            if _inside(candidate, PROJECT_ROOT) and candidate.is_file() and not _has_symlink_component(candidate, PROJECT_ROOT):
                hashes[rel] = hashlib.sha256(candidate.read_bytes()).hexdigest()
        digest = hashlib.sha256(json.dumps({path: hashes.get(path) for path in dirty_paths}, sort_keys=True).encode("utf-8")).hexdigest()
        return {"head": head, "relevant_dirty_paths": dirty_paths, "relevant_dirty_sha256": digest,
                "relevant_dirty_source_sha256": {path: hashes.get(path) for path in dirty_paths},
                "relevant_source_sha256": hashes}
    except (OSError, subprocess.SubprocessError):
        return {"head": None, "relevant_dirty_paths": [], "relevant_dirty_sha256": None,
                "status": "unknown"}


def _prompt_identity() -> Dict[str, Optional[str]]:
    prompt_dir = PROJECT_ROOT / "prompts" / "combat"
    result: Dict[str, Optional[str]] = {}
    for path in sorted(prompt_dir.glob("*.txt")):
        relative = path.relative_to(PROJECT_ROOT).as_posix()
        if path.is_file() and not _has_symlink_component(path, PROJECT_ROOT):
            result[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def _safe_model_config_identity() -> Dict[str, Any]:
    """Parse only public, non-secret literal/alias constants; never import config."""
    path = PROJECT_ROOT / "model_config.py"
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        assignments: Dict[str, ast.AST] = {}
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        assignments[target.id] = node.value
        def resolve(name: str, seen: Optional[set] = None) -> Optional[Any]:
            seen = set() if seen is None else seen
            if name in seen or name not in assignments:
                return None
            seen.add(name)
            node = assignments[name]
            if isinstance(node, ast.Constant) and isinstance(node.value, (str, int, float, bool)):
                return node.value
            if isinstance(node, ast.Name):
                return resolve(node.id, seen)
            return None
        names = ("OPENAI_FALLBACK_MODEL", "COMBAT_MAIN_MODEL", "ACTIVE_PROFILE", "ENABLE_COMBAT_TURN_TRACE")
        return {name: resolve(name) for name in names}
    except (OSError, UnicodeError, SyntaxError):
        return {"status": "unavailable"}


def read_sandbox_model_config_identity(state_root: Path) -> Dict[str, Any]:
    """Resolve configured combat provider/model from safe sandbox AST values only."""
    root = Path(state_root)
    path = root / "model_config.py"
    raw, error = _safe_read_bytes(path, root)
    if error or raw is None:
        return {"status": "unknown", "configured_provider": None,
                "configured_model": None, "reason": error or "missing"}
    try:
        tree = ast.parse(raw.decode("utf-8"))
        assignments: Dict[str, List[ast.AST]] = {}
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        assignments.setdefault(target.id, []).append(node.value)

        def resolve(name: str, seen: Optional[set] = None) -> Optional[str]:
            seen = set() if seen is None else seen
            if name in seen or len(assignments.get(name, [])) != 1:
                return None
            seen.add(name)
            value = assignments[name][0]
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                return value.value if value.value and len(value.value) <= 120 else None
            if isinstance(value, ast.Name):
                return resolve(value.id, seen)
            return None

        provider = resolve("LLM_PROVIDER")
        model = resolve("COMBAT_MAIN_MODEL")
        if provider is None or model is None:
            return {"status": "unknown", "configured_provider": provider,
                    "configured_model": model, "reason": "configured_identity_literal_unavailable",
                    "model_config_sha256": hashlib.sha256(raw).hexdigest(),
                    "provenance": "sandbox model_config.py AST literals"}
        return {"status": "ok", "configured_provider": provider,
                "configured_model": model,
                "model_config_sha256": hashlib.sha256(raw).hexdigest(),
                "provenance": "sandbox model_config.py AST literals"}
    except (UnicodeError, SyntaxError):
        return {"status": "unknown", "configured_provider": None,
                "configured_model": None, "reason": "model_config_ast_invalid"}


def read_sandbox_g9_identity(state_root: Path) -> Dict[str, Any]:
    """Read only the G9 provider/profile/fault literals from a sandbox copy."""
    root = Path(state_root)
    path = root / "model_config.py"
    raw, error = _safe_read_bytes(path, root)
    if error or raw is None:
        return {"status": "unknown", "reason": error or "missing"}
    names = (
        "LLM_PROVIDER", "ACTIVE_PROFILE", "OPENAI_FALLBACK_MODEL",
        "COMBAT_MAIN_MODEL", "OPENROUTER_TRANSPORT_FAULT_INJECTION_ENABLED",
    )
    try:
        tree = ast.parse(raw.decode("utf-8"))
        assignments: Dict[str, List[ast.AST]] = {}
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        assignments.setdefault(target.id, []).append(node.value)

        def resolve(name: str, seen: Optional[set] = None) -> Any:
            seen = set() if seen is None else seen
            if name in seen or len(assignments.get(name, [])) != 1:
                return None
            seen.add(name)
            value = assignments[name][0]
            if isinstance(value, ast.Constant) and type(value.value) in (str, bool):
                return value.value
            if isinstance(value, ast.Name):
                return resolve(value.id, seen)
            return None

        observed = {name: resolve(name) for name in names}
        provider = observed["LLM_PROVIDER"]
        active_profile = observed["ACTIVE_PROFILE"]
        configured_model = observed["COMBAT_MAIN_MODEL"]
        fallback_model = observed["OPENAI_FALLBACK_MODEL"]
        fault_enabled = observed["OPENROUTER_TRANSPORT_FAULT_INJECTION_ENABLED"]
        valid = (
            provider in ("openai", "openrouter") and
            isinstance(active_profile, str) and bool(active_profile) and
            isinstance(configured_model, str) and bool(configured_model) and
            configured_model == fallback_model and
            type(fault_enabled) is bool
        )
        return {
            "status": "ok" if valid else "unknown",
            "configured_provider": provider,
            "active_profile": active_profile,
            "configured_model": configured_model,
            "openai_fallback_model": fallback_model,
            "transport_fault_injection_enabled": fault_enabled,
            "reason": None if valid else "g9_config_literals_invalid_or_ambiguous",
            "model_config_sha256": hashlib.sha256(raw).hexdigest(),
            "provenance": "sandbox model_config.py AST literals",
        }
    except (UnicodeError, SyntaxError):
        return {"status": "unknown", "reason": "model_config_ast_invalid"}


def read_sandbox_g9_marker(state_root: Path) -> Dict[str, Any]:
    """Read only the non-secret G9 row and rollback fields from its sandbox marker."""
    root = Path(state_root)
    marker, digest, error = _safe_json(root / ".g9-capture.json", root)
    if error or not isinstance(marker, dict):
        return {"status": "unknown", "reason": error or "marker_missing"}
    fields = (
        "gate", "row_key", "scenario_id", "party_size", "run_dir",
        "initial_provider", "active_profile", "transport_failure_injection",
        "rollback_state", "rollback_provider", "rollback_model",
        "operator_restart_count_required", "reseed_after_rollback",
    )
    return {"status": "ok", "sha256": digest,
            **{name: marker.get(name) for name in fields},
            "provenance": "sandbox .g9-capture.json"}


def read_sandbox_g10_marker(state_root: Path) -> Dict[str, Any]:
    """Read the non-secret G10 seed, chain, and complete-run identity marker."""
    root = Path(state_root)
    marker, digest, error = _safe_json(root / ".g10-capture.json", root)
    if error or not isinstance(marker, dict):
        return {"status": "unknown", "reason": error or "marker_missing"}
    fields = ("gate", "scenario_id", "seed_scenario_id", "party_size", "chain_id",
              "complete_run_dir", "seed_id", "script_sha256")
    return {"status": "ok", "sha256": digest,
            **{name: marker.get(name) for name in fields},
            "provenance": "sandbox .g10-capture.json"}


def read_sandbox_resolver_identity(state_root: Path) -> Dict[str, Any]:
    """Read the G5R resolver flag from the sandbox model_config.py AST only."""
    root = Path(state_root)
    path = root / "model_config.py"
    raw, error = _safe_read_bytes(path, root)
    if error or raw is None:
        return {"status": "unknown", "enabled": None,
                "reason": error or "missing"}
    try:
        tree = ast.parse(raw.decode("utf-8"))
        assignments = [node.value for node in tree.body if isinstance(node, ast.Assign)
                       for target in node.targets
                       if isinstance(target, ast.Name) and
                       target.id == "DETERMINISTIC_ENEMY_RESOLUTION_ENABLED"]
        if (len(assignments) != 1 or not isinstance(assignments[0], ast.Constant) or
                not isinstance(assignments[0].value, bool)):
            return {"status": "unknown", "enabled": None,
                    "reason": "resolver_flag_not_single_boolean_literal",
                    "model_config_sha256": hashlib.sha256(raw).hexdigest(),
                    "provenance": "sandbox model_config.py AST literal"}
        return {"status": "ok", "enabled": assignments[0].value,
                "model_config_sha256": hashlib.sha256(raw).hexdigest(),
                "provenance": "sandbox model_config.py AST literal"}
    except (UnicodeError, SyntaxError):
        return {"status": "unknown", "enabled": None,
                "reason": "model_config_ast_invalid"}


def read_sandbox_tactical_identity(state_root: Path) -> Dict[str, Any]:
    """Read the G5T tactical flag from the sandbox model_config.py AST only."""
    root = Path(state_root)
    path = root / "model_config.py"
    raw, error = _safe_read_bytes(path, root)
    if error or raw is None:
        return {"status": "unknown", "enabled": None,
                "reason": error or "missing"}
    try:
        tree = ast.parse(raw.decode("utf-8"))
        assignments = [node.value for node in tree.body if isinstance(node, ast.Assign)
                       for target in node.targets
                       if isinstance(target, ast.Name) and
                       target.id == "COMBAT_TACTICAL_BRAIN_ENABLED"]
        if (len(assignments) != 1 or not isinstance(assignments[0], ast.Constant) or
                not isinstance(assignments[0].value, bool)):
            return {"status": "unknown", "enabled": None,
                    "reason": "tactical_flag_not_single_boolean_literal",
                    "model_config_sha256": hashlib.sha256(raw).hexdigest(),
                    "provenance": "sandbox model_config.py AST literal"}
        return {"status": "ok", "enabled": assignments[0].value,
                "model_config_sha256": hashlib.sha256(raw).hexdigest(),
                "provenance": "sandbox model_config.py AST literal"}
    except (UnicodeError, SyntaxError):
        return {"status": "unknown", "enabled": None,
                "reason": "model_config_ast_invalid"}


def read_sandbox_ally_controller_identity(state_root: Path) -> Dict[str, Any]:
    """Read the G5A resolver/controller/prefetch literals from sandbox AST only."""
    root = Path(state_root)
    path = root / "model_config.py"
    raw, error = _safe_read_bytes(path, root)
    if error or raw is None:
        return {"status": "unknown", "reason": error or "missing"}
    expected = {
        "DETERMINISTIC_ENEMY_RESOLUTION_ENABLED": True,
        "COMBAT_ALLY_CONTROLLER_ENABLED": True,
        "COMBAT_ALLY_PREFETCH_ENABLED": True,
    }
    try:
        tree = ast.parse(raw.decode("utf-8"))
    except (UnicodeError, SyntaxError):
        return {"status": "unknown", "reason": "model_config_ast_invalid"}
    observed: Dict[str, Any] = {}
    for name in expected:
        assignments = [node.value for node in tree.body if isinstance(node, ast.Assign)
                       for target in node.targets
                       if isinstance(target, ast.Name) and target.id == name]
        if (len(assignments) != 1 or not isinstance(assignments[0], ast.Constant) or
                not isinstance(assignments[0].value, bool)):
            return {"status": "unknown", "reason": "flag_not_single_boolean_literal:%s" % name,
                    "observed": observed,
                    "model_config_sha256": hashlib.sha256(raw).hexdigest()}
        observed[name] = assignments[0].value
    matches = observed == expected
    return {"status": "ok" if matches else "mismatch", "flags": observed,
            "expected": expected,
            "model_config_sha256": hashlib.sha256(raw).hexdigest(),
            "provenance": "sandbox model_config.py AST literals"}


def read_sandbox_g7_identity(state_root: Path) -> Dict[str, Any]:
    """Read only the fixed G7 feature literals from the isolated sandbox copy."""
    root = Path(state_root)
    path = root / "model_config.py"
    raw, error = _safe_read_bytes(path, root)
    if error or raw is None:
        return {"status": "unknown", "reason": error or "missing"}
    expected = {
        "ENABLE_COMBAT_TURN_TRACE": True,
        "COMBAT_TURN_COMMIT_FAULT_INJECTION_ENABLED": True,
        "DETERMINISTIC_ENEMY_RESOLUTION_ENABLED": True,
        "COMBAT_TACTICAL_BRAIN_ENABLED": False,
        "COMBAT_TACTICAL_PREFETCH_ENABLED": False,
    }
    try:
        tree = ast.parse(raw.decode("utf-8"))
    except (UnicodeError, SyntaxError):
        return {"status": "unknown", "reason": "model_config_ast_invalid"}
    observed: Dict[str, Any] = {}
    for name in expected:
        assignments = [node.value for node in tree.body if isinstance(node, ast.Assign)
                       for target in node.targets
                       if isinstance(target, ast.Name) and target.id == name]
        if (len(assignments) != 1 or not isinstance(assignments[0], ast.Constant) or
                not isinstance(assignments[0].value, bool)):
            return {"status": "unknown", "reason": "flag_not_single_boolean_literal:%s" % name,
                    "observed": observed,
                    "model_config_sha256": hashlib.sha256(raw).hexdigest()}
        observed[name] = assignments[0].value
    matches = observed == expected
    return {"status": "ok" if matches else "mismatch", "flags": observed,
            "expected": expected,
            "model_config_sha256": hashlib.sha256(raw).hexdigest(),
            "provenance": "sandbox model_config.py AST literals"}


def build_manifest(profile: Dict[str, Any], args: Any, session: Any,
                   seed_identity: Dict[str, Any], started_at: str) -> Dict[str, Any]:
    injected_transport = bool(getattr(session, "transport_injected", False))
    synthetic = bool(getattr(args, "synthetic", False) or injected_transport)
    profile_contract = {key: profile.get(key) for key in
                       ("scenario_id", "party_size", "branch", "phase", "seed", "applicability")}
    if profile.get("gate") is not None:
        profile_contract["gate"] = profile["gate"]
    if profile.get("gate") == "g7":
        profile_contract.update({"path": profile.get("path"), "boundary": profile.get("boundary")})
    if profile.get("gate") == "g9":
        profile_contract.update({
            "row_key": profile.get("row_key"),
            "seed_scenario_id": profile.get("seed_scenario_id"),
            "capture_kind": profile.get("capture_kind"),
            "g9_runtime": profile.get("g9_runtime"),
        })
    if profile.get("gate") == "g10":
        profile_contract.update({
            "row_key": profile.get("row_key"),
            "seed_scenario_id": profile.get("seed_scenario_id"),
            "seed_identity": profile.get("seed_identity"),
            "script_sha256": profile.get("applicability", {}).get("script_sha256"),
        })
    gate = profile.get("gate", "g3")
    manifest = {
        "evidence_kind": "synthetic" if synthetic else "live-candidate",
        "live_eligible": not synthetic,
        "gate": gate,
        "scenario": {"id": profile["scenario_id"],
                      "version": {"g4": "g4-capture-v1", "g5": "g5-capture-v1",
                                      "g5r": "g5r-capture-v1", "g5t": "g5t-capture-v1",
                                      "g5a": "g5a-ally-controller-v1",
                                      "g7": "g7-turn-commit-v1", "g9": "g9-openrouter-v1",
                                     "g10": "g10-full-session-v1"}.get(
                          gate, SCENARIO_VERSION),
                     "sha256": hashlib.sha256(json.dumps(profile_contract, sort_keys=True).encode("utf-8")).hexdigest(),
                     "branch": profile.get("branch"), "phase": profile.get("phase"),
                     "profile_contract": profile_contract},
        "party": {"size": profile["party_size"], "roster": seed_identity.get("roster")},
        "seed": seed_identity,
        "sandbox_id": hashlib.sha256(str(Path(args.state_root).resolve()).encode("utf-8")).hexdigest(),
        "source": _source_identity(),
        "prompt_identity_sha256": _prompt_identity(),
        "configuration": {
            "provenance": {"operator_declared": "CLI or safe model_config.py AST literals",
                           "actual_runtime": "response metadata only; unknown if unavailable"},
            "operator_declared": {
                "provider": getattr(args, "declared_provider", None),
                "profile": getattr(args, "declared_profile", None),
                "requested_model": getattr(args, "declared_model", None),
                "safe_model_config_literals": _safe_model_config_identity(),
            },
            "actual_runtime": {"provider": "unknown", "response_model": "unknown", "receipts": []},
        },
        "chain_id": getattr(args, "chain_id", None),
        "sandbox_runtime": {"port": 8360, "port_provenance": "validated operator URL",
                            "trace_gate": getattr(args, "trace_gate_observation", {"status": "unknown", "enabled": None}),
                            "trace_observations_present": bool(getattr(session, "trace_observations_observed", False))},
        "transport": {"url": session.url, "kind": "socket.io + local REST",
                      "client_source": "constructor_injected" if injected_transport else "socketio.Client",
                      "declared_profile": getattr(args, "declared_profile", None),
                      "declared_provider": getattr(args, "declared_provider", None),
                      "requested_model": getattr(args, "declared_model", None),
                      "resolved_response_model": "unknown"},
        "timestamps": {"started_at": started_at, "manifest_written_at": _now()},
        "bounds": {"max_steps": profile["max_steps"], "max_requests": profile["max_requests"],
                   "max_active_switches": profile["max_active_switches"],
                   "max_health_reads": profile.get("max_health_reads", 0),
                   "start_timeout_seconds": float(args.start_timeout),
                   "turn_timeout_seconds": float(args.turn_timeout),
                   "turn_quiet_seconds": float(args.turn_quiet_seconds)},
        "counts": {"step_attempts": session.step_attempts, "steps_sent": session.steps_sent,
                    "backend_output_count": getattr(session, "backend_output_count", 0),
                    "control_request_attempts": session.control_request_attempts,
                    "control_request_calls": session.control_request_calls,
                    "control_request_failures": session.control_request_failures,
                    "control_requests_sent": session.control_requests_sent,
                    "active_switch_attempts": session.active_switch_attempts,
                    "active_switch_requests_sent": session.active_switch_requests_sent,
                   "blocked_step_attempts": session.blocked_step_attempts,
                   "blocked_control_attempts": session.blocked_control_attempts,
                   "timeouts": session.timeout_count, "start_timeout": session.start_timed_out,
                   "step_caps_reached": session.step_caps_reached,
                   "idle_settle_caps_reached": session.idle_settle_caps_reached,
                    "active_switch_failures": session.active_switch_failures,
                    "health_read_attempts": session.health_read_attempts,
                    "exit_health_read_attempts": getattr(session, "exit_health_read_attempts", 0),
                   "provider_calls": {"count": None, "source": "unknown"}},
        "artifacts": {},
    }
    if gate == "g7":
        manifest["configuration"]["g7_runtime"] = read_sandbox_g7_identity(
            Path(args.state_root)
        )
    return manifest


def required_matrix_keys() -> List[str]:
    return list(REQUIRED_KEYS)


def matrix_key(scenario: str, party: int, branch: Optional[str] = None,
               phase: Optional[str] = None, path: Optional[str] = None,
    boundary: Optional[str] = None) -> str:
    if scenario == "full-session":
        return "full-session:%s:p%d" % (phase or "missing", party)
    if scenario == "surrender-exit":
        return "surrender-exit:%s:p%d" % (branch or "missing", party)
    if scenario == "resume-replay":
        return "resume-replay:%s:p%d" % (phase or "missing", party)
    if scenario == "turn-commit":
        return g7_matrix_key(party, path, boundary, phase)
    return "%s:p%d" % (scenario, party)


def required_g7_matrix_keys() -> List[str]:
    """Return the closed G7 matrix, with party-specific boundary applicability."""
    from scripts import combat_latency_fixtures

    keys: List[str] = []
    for party in (1, 4):
        for path in G7_PATHS:
            boundaries = combat_latency_fixtures.g7_commit_boundaries(party, path)
            for boundary in boundaries:
                for phase in ("interrupt", "recover"):
                    keys.append(g7_matrix_key(party, path, boundary, phase))
            for phase in ("complete", "replay"):
                keys.append(g7_matrix_key(party, path, G7_BOUNDARY_NONE, phase))
    return keys


def required_g9_row_keys() -> List[str]:
    """Return the closed G9 Auto/fallback/rollback row inventory."""
    from scripts import combat_latency_fixtures

    return list(combat_latency_fixtures.required_g9_row_keys())


def g7_matrix_key(party: int, path: Optional[str], boundary: Optional[str],
                  phase: Optional[str]) -> str:
    return "turn-commit:%s:%s:%s:p%d" % (
        path or "missing", boundary or "missing", phase or "missing", party
    )


def load_step_snapshots(run_dir: Path, manifest: Dict[str, Any]) -> tuple[List[Dict[str, Any]], List[str]]:
    rows: List[Dict[str, Any]] = []
    errors: List[str] = []
    counts = manifest.get("counts", {})
    expected = int(counts.get("steps_sent", 0))
    for index in range(1, expected + 1):
        pair: Dict[str, Any] = {}
        for edge in ("before", "after"):
            relative = "snapshots/step-%03d-%s.json" % (index, edge)
            path = Path(run_dir) / relative
            document, error = load_bundle_json(Path(run_dir), relative)
            if document is None or not isinstance(document.get("records"), dict):
                errors.append(relative + ":" + (error or "invalid_snapshot"))
            else:
                pair[edge] = document
        if len(pair) == 2:
            rows.append(pair)
    return rows, errors


def _causal_evidence_check(profile: Dict[str, Any], steps: List[Dict[str, Any]],
                           events: List[Dict[str, Any]]) -> Dict[str, Any]:
    linked = link_trace_events_to_steps(events, steps)
    if linked["status"] != "PASS":
        return {"id": "causal_trace_linkage", "required": True,
                "expected": "each relevant observation has one complete source-positioned step span",
                "observed": {"status": linked["status"], "reason": linked["reason"]},
                "status": "BLOCKED", "evidence": "trace byte offsets and step snapshots"}
    # Linkage itself is not proof of mechanics. Record only event identities and
    # step references here; the specific mechanical checks below use those spans.
    return {"id": "causal_trace_linkage", "required": True,
            "expected": "source-positioned observations link to exactly one step",
            "observed": {"status": "PASS", "linked_observations": len(linked["events"]),
                         "step_count": len(linked["steps"])},
            "status": "PASS", "evidence": "source byte spans; no target/delta identity matching"}


def _canonical_hp_state(snapshot: Any) -> tuple[Dict[Tuple[str, str], int], List[str]]:
    """Extract strictly validated character and encounter HP cells."""
    state: Dict[Tuple[str, str], int] = {}
    errors: List[str] = []
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("records"), dict):
        return {}, ["snapshot_missing"]
    records = snapshot["records"]
    encounter = records.get("selected_encounter")
    creatures = encounter.get("creatures") if isinstance(encounter, dict) else None
    if not isinstance(creatures, list):
        errors.append("encounter_missing_or_malformed")
        creatures = []
    for index, row in enumerate(creatures):
        if not isinstance(row, dict) or not isinstance(row.get("name"), str) or not row.get("name"):
            errors.append("encounter_row_identity:%d" % index)
            continue
        hp = row.get("currentHitPoints")
        if not _finite_number(hp) or int(hp) != hp:
            errors.append("encounter_hp_invalid:%s" % row["name"])
            continue
        key = ("encounter", row["name"].casefold())
        if key in state:
            errors.append("encounter_identity_ambiguous:%s" % row["name"])
        state[key] = int(hp)
    for key, row in records.items():
        if not key.startswith("characters/"):
            continue
        if not isinstance(row, dict) or row.get("read_status", "ok") != "ok":
            errors.append("character_record_unavailable:%s" % key)
            continue
        name, hp = row.get("name"), row.get("hitPoints")
        if not isinstance(name, str) or not name:
            errors.append("character_identity_invalid:%s" % key)
            continue
        if not _finite_number(hp) or int(hp) != hp:
            errors.append("character_hp_invalid:%s" % name)
            continue
        identity = ("character", name.casefold())
        if identity in state:
            errors.append("character_identity_ambiguous:%s" % name)
        state[identity] = int(hp)
    # Encounter PC/NPC rows are an explicit mirror of canonical character files.
    char_names = {name for domain, name in state if domain == "character"}
    for row in creatures:
        if not isinstance(row, dict) or row.get("type") not in ("player", "npc"):
            continue
        name = str(row.get("name", "")).casefold()
        if name not in char_names:
            errors.append("character_mirror_missing:%s" % name)
    return state, errors


def _canonical_mirror_names(snapshot: Any) -> set[str]:
    rows = _selected_encounter(snapshot).get("creatures")
    return {str(row.get("name", "")).casefold() for row in rows or []
            if isinstance(row, dict) and row.get("type") in ("player", "npc")}


def _complete_zero_hp_projection(event: Dict[str, Any], before_state: Dict[Tuple[str, str], int],
                                 encounter_id: Any) -> bool:
    """Accept only paired, provenance-matched projections equal to canonical pre-step HP."""
    if event.get("target") != encounter_id or not isinstance(encounter_id, str):
        return False
    if (event.get("hp_before_status") != "complete" or event.get("hp_after_status") != "complete" or
            event.get("hp_before_source") != "preloaded_context" or
            event.get("hp_after_source") != "returned_persisted_state" or
            event.get("hp_before_truncated") is not False or
            event.get("hp_after_truncated") is not False):
        return False
    try:
        before_rows, after_rows = json.loads(event.get("hp_before")), json.loads(event.get("hp_after"))
    except (TypeError, ValueError):
        return False
    if not isinstance(before_rows, list) or not isinstance(after_rows, list):
        return False
    def normalize(rows: List[Any], count: Any) -> Optional[Dict[str, int]]:
        if (not isinstance(count, int) or isinstance(count, bool) or count != len(rows) or
                count > 12):
            return None
        values: Dict[str, int] = {}
        for row in rows:
            if (not isinstance(row, list) or len(row) != 2 or not isinstance(row[0], str) or
                    not row[0] or len(row[0]) > 40 or not _finite_number(row[1]) or int(row[1]) != row[1]):
                return None
            identity = row[0].casefold()
            if identity in values:
                return None
            values[identity] = int(row[1])
        return values
    before = normalize(before_rows, event.get("hp_before_count"))
    after = normalize(after_rows, event.get("hp_after_count"))
    canonical = {name: hp for (domain, name), hp in before_state.items() if domain == "encounter"}
    return bool(before is not None and after is not None and before == after == canonical)


def _hp_causal_ledger(run_before: Any, steps: List[Dict[str, Any]], run_after: Any,
                      events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Reconcile HP changes, mirrors, and every timeline boundary exactly once."""
    linkage = link_trace_events_to_steps(events, steps)
    if linkage.get("status") != "PASS":
        return {"status": "BLOCKED", "reason": linkage.get("reason"), "steps": [], "boundaries": []}
    snapshot_inputs = [run_before]
    snapshots = [_canonical_hp_state(run_before)]
    for pair in steps:
        snapshot_inputs.extend((pair.get("before"), pair.get("after")))
        snapshots.extend((_canonical_hp_state(pair.get("before")),
                          _canonical_hp_state(pair.get("after"))))
    snapshot_inputs.append(run_after)
    snapshots.append(_canonical_hp_state(run_after))
    errors = ["snapshot_%d:%s" % (index, reason)
              for index, (_state, reasons) in enumerate(snapshots) for reason in reasons]
    if errors:
        return {"status": "BLOCKED", "reason": "invalid_canonical_hp_cells", "errors": errors,
                "steps": [], "boundaries": []}
    states = [state for state, _reasons in snapshots]
    mirror_names = [_canonical_mirror_names(snapshot) for snapshot in snapshot_inputs]
    boundary_cell_errors = []
    for index in range(len(states) - 1):
        if states[index].keys() != states[index + 1].keys():
            boundary_cell_errors.append("hp_cell_inventory_changed:%d" % index)
    if boundary_cell_errors:
        return {"status": "BLOCKED", "reason": "required_hp_cells_missing", "errors": boundary_cell_errors,
                "steps": [], "boundaries": []}

    def mirror_mismatches(snapshot: Any, state: Dict[Tuple[str, str], int]) -> List[Dict[str, Any]]:
        rows = _selected_encounter(snapshot).get("creatures")
        mismatches = []
        for creature in rows if isinstance(rows, list) else []:
            if not isinstance(creature, dict) or creature.get("type") not in ("player", "npc"):
                continue
            name = str(creature.get("name", "")).casefold()
            char_hp, encounter_hp = state.get(("character", name)), state.get(("encounter", name))
            if char_hp is not None and encounter_hp is not None and char_hp != encounter_hp:
                mismatches.append({"entity": name, "character_hp": char_hp, "encounter_hp": encounter_hp})
        return mismatches

    initial_mirror_mismatch = mirror_mismatches(run_before, states[0])
    final_mirror_mismatch = mirror_mismatches(run_after, states[-1])
    if initial_mirror_mismatch:
        return {"status": "FAIL", "reason": "run_start_mirror_mismatch",
                "mirror_mismatches": initial_mirror_mismatch, "steps": [], "boundaries": []}
    linked_by_step: Dict[int, List[Dict[str, Any]]] = {}
    for item in linkage["events"]:
        linked_by_step.setdefault(item["step"], []).append(item["event"])
    rows: List[Dict[str, Any]] = []
    boundaries: List[Dict[str, Any]] = []
    pending_mirrors: Dict[str, Tuple[str, int]] = {}
    failed = False
    blocked = False

    def boundary_delta(left: Dict[Tuple[str, str], int], right: Dict[Tuple[str, str], int]) -> Dict[Tuple[str, str], int]:
        return {key: right[key] - left[key] for key in left.keys() & right.keys() if right[key] != left[key]}

    # No gameplay mutation is attributable to startup or the interval before step 1.
    initial_delta = boundary_delta(states[0], states[1]) if steps else boundary_delta(states[0], states[-1])
    if initial_delta:
        failed = True
        boundaries.append({"boundary": "run_start_to_first_step", "status": "FAIL",
                           "deltas": [[key[0], key[1], value] for key, value in sorted(initial_delta.items())]})

    # Check each scripted step using only its contained actual trace events.
    for number, pair in enumerate(steps, 1):
        before_state, after_state = states[2 * number - 1], states[2 * number]
        step_mirrors = mirror_names[2 * number - 1] | mirror_names[2 * number]
        deltas = boundary_delta(before_state, after_state)
        events_in_step = linked_by_step.get(number, [])
        apply_ops: Dict[Tuple[str, str], int] = {}
        event_failures = []
        step_blockers = []
        encounter_writes = [event for event in events_in_step
                            if event.get("observation") == "combat_apply_result" and
                            event.get("domain") == "encounter" and
                            event.get("operation") == "update_encounter"]
        for event in events_in_step:
            if event.get("observation") != "combat_apply_result":
                continue
            if event.get("applied") is not True:
                continue
            operations = event.get("ops")
            if (event.get("operation") in ("update_encounter", "update_character_info_ops") and
                    not isinstance(operations, list)):
                projection_proves_zero = (
                    event.get("operation") == "update_encounter" and operations is None and
                    len(encounter_writes) == 1 and
                    _complete_zero_hp_projection(
                        event, before_state, _selected_encounter(pair.get("before")).get("encounterId")
                    )
                )
                if not projection_proves_zero:
                    step_blockers.append("structured_operation_payload_missing")
                continue
            for operation in operations or []:
                if not isinstance(operation, dict):
                    step_blockers.append("unknown_structured_mutation")
                    continue
                if operation.get("op") not in ("hp_delta", "set_hp"):
                    if operation.get("op") not in {"xp_delta", "inventory_add", "inventory_remove",
                                                    "currency_delta", "condition_add", "condition_remove",
                                                    "set_status", "death_save_delta", "resource_delta",
                                                    "set_resource"}:
                        step_blockers.append("unknown_structured_mutation")
                    continue
                domain = event.get("domain")
                identity = operation.get("creature") if domain == "encounter" else event.get("target")
                if domain not in ("encounter", "character") or not isinstance(identity, str):
                    event_failures.append("operation_identity_missing")
                    continue
                hp_key = (domain, identity.casefold())
                amount = operation.get("delta") if operation.get("op") == "hp_delta" else None
                if operation.get("op") == "set_hp":
                    new_value = operation.get("value")
                    if hp_key not in before_state or hp_key not in after_state:
                        step_blockers.append("apply_target_hp_cell_missing:%s" % identity)
                        continue
                    if not _finite_number(new_value) or int(new_value) != new_value:
                        event_failures.append("set_hp_unprovable")
                        continue
                    amount = int(new_value) - before_state[hp_key]
                if not _finite_number(amount) or int(amount) != amount:
                    event_failures.append("hp_delta_invalid")
                    continue
                apply_ops[hp_key] = apply_ops.get(hp_key, 0) + int(amount)
        observation = (pair.get("before") or {}).get("observation", {})
        damage = re.match(r"^/dmg\s+(\d+)\b", str(observation.get("input", "")), re.IGNORECASE)
        actor = observation.get("character")
        active = (_step_records(pair.get("before")).get("party_tracker.json") or {}).get("active_character")
        fast = [event for event in events_in_step if event.get("event_type") == "decision" and
                event.get("decision_point") == "combat_command_fast_path" and
                event.get("decision_source") == "deterministic" and event.get("provider_call_avoided") is True]
        deterministic_proven = bool(damage and isinstance(actor, str) and actor == active and len(fast) == 1)
        deterministic_keys = []
        if damage and not deterministic_proven:
            step_blockers.append("deterministic_fast_path_or_actor_proof_missing")
        if deterministic_proven:
            candidates = [(key, delta) for key, delta in deltas.items()
                          if key[0] == "encounter" and delta < 0]
            if len(candidates) != 1:
                blocked = True
                step_blockers.append("deterministic_target_ambiguous")
            else:
                key, amount = candidates[0]
                if amount != -int(damage.group(1)):
                    event_failures.append("deterministic_damage_mismatch")
                else:
                    deterministic_keys.append(key)

        represented = set()
        mirrors: List[Dict[str, Any]] = []
        for key, expected in apply_ops.items():
            if key not in deltas:
                if key not in before_state or key not in after_state:
                    step_blockers.append("apply_target_hp_cell_missing:%s:%s" % key)
                else:
                    event_failures.append("applied_hp_operation_not_observed:%s:%s" % key)
            elif deltas[key] != expected:
                event_failures.append("applied_hp_operation_mismatch:%s:%s" % key)
            else:
                represented.add(key)

        delayed_projections = []
        delayed_entities = set()
        for key, delta in deltas.items():
            pending = pending_mirrors.get(key[1])
            if pending == (key[0], delta) and key[1] in step_mirrors:
                represented.add(key)
                pending_mirrors.pop(key[1], None)
                delayed_entities.add(key[1])
                delayed_projections.append({"entity": key[1], "domain": key[0],
                                            "direction": "delayed_%s" % key[0], "delta": delta,
                                            "justification": "exact pending canonical mirror projection"})
        for key in deterministic_keys:
            represented.add(key)

        entities = {name for domain, name in deltas}
        for name in entities:
            char_key, enc_key = ("character", name), ("encounter", name)
            char_delta, enc_delta = deltas.get(char_key, 0), deltas.get(enc_key, 0)
            if char_delta and enc_delta and name in step_mirrors:
                if char_delta != enc_delta:
                    event_failures.append("character_encounter_mirror_mismatch:%s" % name)
                elif char_key in represented or enc_key in represented:
                    represented.update((char_key, enc_key))
                    mirrors.append({"entity": name, "direction": "same_step", "delta": char_delta,
                                    "justification": "unique character/encounter HP mirror; one logical mutation"})
            elif char_delta and char_key in represented and name in step_mirrors and name not in delayed_entities:
                pending_mirrors[name] = ("encounter", char_delta)
                represented.add(char_key)
            elif enc_delta and enc_key in represented and name in step_mirrors and name not in delayed_entities:
                pending_mirrors[name] = ("character", enc_delta)
                represented.add(enc_key)
        unexplained = [key for key in deltas if key not in represented]
        if unexplained:
            event_failures.extend("unexplained_hp:%s:%s" % key for key in unexplained)
        row_status = "FAIL" if event_failures else ("BLOCKED" if step_blockers else "PASS")
        failed = failed or bool(event_failures)
        blocked = blocked or bool(step_blockers)
        rows.append({"step": number, "status": row_status,
                     "source_deltas": [{"domain": key[0], "entity": key[1], "delta": value}
                                       for key, value in sorted(deltas.items())],
                      "structured_hp_operations": [{"domain": key[0], "entity": key[1], "delta": value}
                                                   for key, value in sorted(apply_ops.items())],
                     "mirror_projections": mirrors + delayed_projections,
                      "logical_hp_effects": [
                          {"entity": name,
                           "delta": (deltas.get(("character", name)) or
                                     deltas.get(("encounter", name))),
                           "sources": [domain for domain in ("character", "encounter")
                                       if (domain, name) in represented]}
                          for name in sorted({identity for _domain, identity in represented}
                                             - delayed_entities)
                     ],
                     "unexplained_changes": [list(key) for key in unexplained],
                     "deterministic_fast_path_proven": deterministic_proven,
                     "failures": event_failures, "blockers": step_blockers})

        # Changes between a completed step and the next pre-input snapshot are
        # allowed only as an exact pending canonical mirror projection.
        next_state = states[2 * number + 1]
        between = boundary_delta(after_state, next_state) if number < len(steps) else {}
        for (domain, name), amount in between.items():
            pending = pending_mirrors.get(name)
            is_mirror_entity = name in mirror_names[2 * number] and name in mirror_names[2 * number + 1]
            if pending == (domain, amount) and is_mirror_entity:
                boundaries.append({"boundary": "step_%d_to_next_before" % number, "status": "PASS",
                                   "entity": name, "domain": domain, "delta": amount,
                                   "justification": "exact pending mirror projection from prior proven HP mutation"})
                pending_mirrors.pop(name, None)
            else:
                failed = True
                boundaries.append({"boundary": "step_%d_to_next_before" % number, "status": "FAIL",
                                   "entity": name, "domain": domain, "delta": amount,
                                   "reason": "unexplained_inter_step_hp_change"})
    # The final run snapshot may contain only a previously authorized mirror catch-up.
    if steps:
        final_delta = boundary_delta(states[-2], states[-1])
        for (domain, name), amount in final_delta.items():
            is_mirror_entity = name in mirror_names[-2] and name in mirror_names[-1]
            if pending_mirrors.get(name) == (domain, amount) and is_mirror_entity:
                pending_mirrors.pop(name, None)
                boundaries.append({"boundary": "last_step_to_run_end", "status": "PASS",
                                   "entity": name, "domain": domain, "delta": amount,
                                   "justification": "exact delayed canonical mirror projection"})
            else:
                failed = True
                boundaries.append({"boundary": "last_step_to_run_end", "status": "FAIL",
                                   "entity": name, "domain": domain, "delta": amount,
                                   "reason": "unexplained_final_hp_change"})
    if pending_mirrors:
        blocked = True
        boundaries.append({"boundary": "unresolved_mirrors", "status": "BLOCKED",
                           "pending": {name: list(value) for name, value in sorted(pending_mirrors.items())}})
    if final_mirror_mismatch:
        failed = True
        boundaries.append({"boundary": "run_end_mirror_consistency", "status": "FAIL",
                           "mismatches": final_mirror_mismatch})
    run_totals = {}
    for key in states[0].keys() & states[-1].keys():
        start, end = states[0][key], states[-1][key]
        if start != end:
            run_totals[key] = end - start
    ledger_totals: Dict[Tuple[str, str], int] = {}
    for row in rows:
        for delta_row in row["source_deltas"]:
            key = (delta_row["domain"], delta_row["entity"])
            ledger_totals[key] = ledger_totals.get(key, 0) + delta_row["delta"]
    for row in boundaries:
        if row.get("status") == "PASS" and row.get("domain") in ("character", "encounter"):
            key = (row["domain"], row["entity"])
            ledger_totals[key] = ledger_totals.get(key, 0) + row["delta"]
    # Zero is a valid net total after fully proven opposing mutations. Keep every
    # per-step operation above, but normalize the aggregate map to its canonical
    # sparse form before comparing it with run-start/run-end totals.
    ledger_totals = {key: value for key, value in ledger_totals.items() if value != 0}
    if ledger_totals != run_totals:
        failed = True
        boundaries.append({"boundary": "run_total_reconciliation", "status": "FAIL",
                           "canonical_run_deltas_by_source": [
                               {"domain": key[0], "entity": key[1], "delta": value}
                               for key, value in sorted(run_totals.items())],
                           "proved_per_step_and_mirror_deltas": [
                               {"domain": key[0], "entity": key[1], "delta": value}
                               for key, value in sorted(ledger_totals.items())]})
    status = "FAIL" if failed else ("BLOCKED" if blocked else "PASS")
    return {"status": status, "steps": rows, "boundaries": boundaries,
            "run_start_hp": [{"domain": key[0], "entity": key[1], "hp": value}
                             for key, value in sorted(states[0].items())],
            "run_end_hp": [{"domain": key[0], "entity": key[1], "hp": value}
                           for key, value in sorted(states[-1].items())],
            "canonical_run_deltas_by_source": [{"domain": key[0], "entity": key[1], "delta": value}
                                               for key, value in sorted(run_totals.items())]}


def _step_records(snapshot: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    return snapshot.get("records", {}) if isinstance(snapshot, dict) else {}


def _g5a_snapshot_hp_state(snapshot: Optional[Dict[str, Any]]) -> Tuple[Dict[Tuple[str, str], int], Dict[Tuple[str, str], str], List[str]]:
    """Read unambiguous canonical HP cells from one persisted step snapshot."""
    records = _step_records(snapshot)
    state: Dict[Tuple[str, str], int] = {}
    names: Dict[Tuple[str, str], str] = {}
    errors: List[str] = []

    def add(domain: str, name: Any, hp: Any) -> None:
        if not isinstance(name, str) or not name.strip():
            errors.append("hp_snapshot_identity_missing")
            return
        normalized = " ".join(name.split()).casefold()
        key = (domain, normalized)
        if key in state:
            errors.append("hp_snapshot_identity_ambiguous:%s:%s" % key)
            return
        if (not _finite_number(hp) or int(hp) != hp):
            errors.append("hp_snapshot_value_missing_or_invalid:%s:%s" % key)
            return
        state[key] = int(hp)
        names[key] = name

    encounter = records.get("selected_encounter")
    creatures = encounter.get("creatures") if isinstance(encounter, dict) else None
    if (not isinstance(encounter, dict) or encounter.get("status") != "ok" or
            not isinstance(creatures, list)):
        errors.append("hp_snapshot_encounter_missing_or_invalid")
    else:
        for creature in creatures:
            if not isinstance(creature, dict):
                errors.append("hp_snapshot_creature_invalid")
                continue
            add("encounter", creature.get("name"), creature.get("currentHitPoints"))

    for path, character in records.items():
        if not isinstance(path, str) or not path.startswith("characters/"):
            continue
        if not isinstance(character, dict):
            errors.append("hp_snapshot_character_invalid")
            continue
        add("character", character.get("name"), character.get("hitPoints"))
    return state, names, errors


def _g5a_reconcile_hp_steps(
    party_size: int,
    steps: List[Dict[str, Any]],
    events: List[Dict[str, Any]],
    event_step: Dict[int, int],
    operations: Dict[Tuple[int, str, str], int],
    operation_names: Dict[Tuple[int, str, str], str],
    *,
    unpositioned_operation: bool,
    linkage_status: str,
    metadata: Optional[Dict[str, Any]],
) -> Tuple[str, List[Dict[str, Any]], List[str]]:
    """Reconcile G5A HP effects against source-linked driver snapshots.

    Structured apply deltas remain authoritative when emitted. Where the runtime
    emits only a successful transaction (or the deterministic /dmg fast path),
    the exact persisted before/after step snapshots provide the mutation values;
    incomplete or ambiguous snapshots never substitute for missing evidence.
    """
    if __package__:
        from scripts.combat_latency_fixtures import build_g5a_script_steps
    else:
        from combat_latency_fixtures import build_g5a_script_steps

    script_rows = build_g5a_script_steps(party_size)
    script_by_step = {row["step"]: row for row in script_rows}
    errors: List[str] = []
    blocked = False
    failed = False
    if linkage_status != "PASS":
        blocked = True
        errors.append("source_positioned_trace_linkage_unavailable")
    if unpositioned_operation:
        blocked = True
        errors.append("hp_operation_source_position_unavailable")

    step_states: Dict[int, Tuple[Dict[Tuple[str, str], int], Dict[Tuple[str, str], int]]] = {}
    step_deltas: Dict[int, Dict[Tuple[str, str], int]] = {}
    step_after_names: Dict[Tuple[int, str, str], str] = {}
    for step_number, pair in enumerate(steps, 1):
        if not isinstance(pair, dict):
            blocked = True
            errors.append("step_snapshot_pair_invalid:%d" % step_number)
            continue
        before_state, before_names, before_errors = _g5a_snapshot_hp_state(pair.get("before"))
        after_state, after_names, after_errors = _g5a_snapshot_hp_state(pair.get("after"))
        if before_errors or after_errors:
            blocked = True
            errors.extend("step_%d_before:%s" % (step_number, item) for item in before_errors)
            errors.extend("step_%d_after:%s" % (step_number, item) for item in after_errors)
        if set(before_state) != set(after_state):
            blocked = True
            errors.append("hp_snapshot_entities_changed_or_missing:%d" % step_number)
        step_states[step_number] = (before_state, after_state)
        for (domain, name), display_name in after_names.items():
            step_after_names[(step_number, domain, name)] = display_name
        deltas: Dict[Tuple[str, str], int] = {}
        for key in set(before_state) & set(after_state):
            delta = after_state[key] - before_state[key]
            if delta:
                deltas[key] = delta
        step_deltas[step_number] = deltas

    reconciliation: List[Dict[str, Any]] = []
    represented: set[Tuple[int, str, str]] = set()
    for key, expected_delta in sorted(operations.items()):
        step_number, domain, name = key
        states = step_states.get(step_number)
        entity_key = (domain, name)
        if states is None or entity_key not in states[0] or entity_key not in states[1]:
            blocked = True
            errors.append("hp_operation_snapshot_missing:%d:%s:%s" % key)
            continue
        observed_delta = step_deltas.get(step_number, {}).get((domain, name), 0)
        reconciliation.append({
            "step": step_number,
            "domain": domain,
            "target": operation_names.get(key, name),
            "expected_delta": expected_delta,
            "observed_delta": observed_delta,
            "evidence_source": "source_positioned_apply_operation",
        })
        represented.add(key)
        if observed_delta != expected_delta:
            failed = True
            errors.append("hp_operation_snapshot_mismatch:%d:%s:%s" % key)

    metadata_identity = metadata.get("identity") if isinstance(metadata, dict) else None
    expected_run_id = metadata_identity.get("run_id") if isinstance(metadata_identity, dict) else None
    fallback_needed = False
    for step_number, deltas in step_deltas.items():
        for domain, name in deltas:
            if (step_number, domain, name) not in operations:
                fallback_needed = True

    # A scripted /dmg can be deterministically applied without a structured HP
    # operation event. Prove each such command by its exact fixture input,
    # source-positioned fast-path decision, and canonical step snapshots.
    damage_rows = [row for row in script_rows
                   if isinstance(row.get("input"), str) and
                   row["input"].startswith("/dmg ")]
    if fallback_needed:
        for script_row in damage_rows:
            step_number = script_row["step"]
            if step_number > len(steps):
                blocked = True
                errors.append("scripted_damage_step_snapshot_missing:%d" % step_number)
                continue
            pair = steps[step_number - 1]
            after_snapshot = pair.get("after")
            after_observation = (after_snapshot.get("observation", {})
                                 if isinstance(after_snapshot, dict) else {})
            if (not isinstance(after_observation, dict) or
                    after_observation.get("input") != script_row.get("input") or
                    after_observation.get("label") != script_row.get("label")):
                blocked = True
                errors.append("scripted_damage_step_identity_missing:%d" % step_number)
                continue
            matching_decisions = [event for event in events
                                  if event_step.get(id(event)) == step_number and
                                  event.get("event_type") == "decision" and
                                  event.get("decision_point") == "combat_command_fast_path"]
            decision_valid = (
                len(matching_decisions) == 1 and
                matching_decisions[0].get("decision_source") == "deterministic" and
                matching_decisions[0].get("provider_call_avoided") is True and
                matching_decisions[0].get("run_id") == expected_run_id
            )
            if not decision_valid:
                blocked = True
                errors.append("scripted_damage_decision_missing_or_ambiguous:%d" % step_number)
                continue
            match = re.fullmatch(r"/dmg\s+([1-9][0-9]*)\s+round\s+[1-9][0-9]*",
                                 script_row["input"], re.IGNORECASE)
            target = script_row.get("target")
            if match is None or not isinstance(target, str) or not target.strip():
                blocked = True
                errors.append("scripted_damage_contract_invalid:%d" % step_number)
                continue
            target_key = ("encounter", " ".join(target.split()).casefold())
            states = step_states.get(step_number)
            if states is None or target_key not in states[0] or target_key not in states[1]:
                blocked = True
                errors.append("scripted_damage_target_snapshot_missing:%d" % step_number)
                continue
            expected_delta = -int(match.group(1))
            observed_delta = step_deltas.get(step_number, {}).get(target_key, 0)
            other_deltas = [key for key in step_deltas.get(step_number, {})
                            if key != target_key]
            if other_deltas:
                failed = True
                errors.append("unexpected_hp_delta_during_scripted_damage:%d" % step_number)
            if observed_delta != expected_delta:
                failed = True
                errors.append("scripted_damage_snapshot_mismatch:%d" % step_number)
            op_key = (step_number, "encounter", target_key[1])
            if op_key not in represented:
                reconciliation.append({
                    "step": step_number,
                    "domain": "encounter",
                    "target": target,
                    "expected_delta": expected_delta,
                    "observed_delta": observed_delta,
                    "evidence_source": "deterministic_damage_command_and_step_snapshots",
                })
                represented.add(op_key)

    # Encounter commits replace the whole projection, so their apply trace may
    # correctly have ops=[]. Reconstruct omitted values only when one successful
    # batch apply, publication, and accepted completion are all linked to the
    # same driver step and run identity.
    for step_number, deltas in step_deltas.items():
        missing = [key for key in deltas
                   if (step_number, key[0], key[1]) not in operations]
        if not missing:
            continue
        script_row = script_by_step.get(step_number)
        if not isinstance(script_row, dict) or script_row.get("unit_type") != "batch":
            # Scripted damage deltas were already checked above. Any other
            # missing apply operation is insufficiently attributed.
            if not (fallback_needed and script_row and
                    str(script_row.get("input", "")).startswith("/dmg ")):
                blocked = True
                errors.append("unattributed_hp_snapshot_delta:%d" % step_number)
            continue
        pair = steps[step_number - 1] if step_number <= len(steps) else None
        after_snapshot = pair.get("after") if isinstance(pair, dict) else None
        after_observation = (after_snapshot.get("observation", {})
                             if isinstance(after_snapshot, dict) else {})
        if (not isinstance(after_observation, dict) or
                after_observation.get("input") != script_row.get("input") or
                after_observation.get("label") != script_row.get("label")):
            blocked = True
            errors.append("batch_step_identity_missing:%d" % step_number)
            continue
        batch_id = script_row.get("trace_batch_id")
        linked = [event for event in events if event_step.get(id(event)) == step_number]
        apply_rows = [event for event in linked
                      if event.get("observation") == "combat_apply_result" and
                      event.get("domain") == "encounter" and
                      event.get("applied") is True and event.get("batch_id") == batch_id and
                      event.get("run_id") == expected_run_id]
        publication_rows = [event for event in linked
                            if event.get("observation") == "combat_turn_success_publication" and
                            event.get("batch_id") == batch_id and
                            event.get("run_id") == expected_run_id]
        completion_rows = [event for event in linked
                           if event.get("observation") == "combat_logical_batch_completed" and
                           event.get("batch_id") == batch_id and
                           event.get("run_id") == expected_run_id and
                           event.get("accepted_batch") is True and
                           event.get("validation_accepted") is True]
        if (len(apply_rows) != 1 or len(publication_rows) != 1 or
                len(completion_rows) != 1 or not expected_run_id):
            blocked = True
            errors.append("successful_batch_snapshot_proof_missing_or_ambiguous:%d" % step_number)
            continue
        for domain, name in missing:
            key = (domain, name)
            reconciliation.append({
                "step": step_number,
                "domain": domain,
                "target": step_after_names.get((step_number, domain, name), name),
                "expected_delta": deltas[key],
                "observed_delta": deltas[key],
                "evidence_source": "successful_batch_commit_and_step_snapshots",
            })
            represented.add((step_number, domain, name))

    if not steps:
        blocked = True
        errors.append("per_step_hp_snapshots_missing")
    if not reconciliation:
        blocked = True
        errors.append("hp_reconciliation_observations_missing")
    status = "FAIL" if failed else "BLOCKED" if blocked else "PASS"
    return status, reconciliation, sorted(set(errors))


def _selected_encounter(snapshot: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    return _step_records(snapshot).get("selected_encounter", {})


def _g5t_menu_actor_ids(event: Dict[str, Any], field: str) -> Optional[set[str]]:
    values = event.get(field)
    if (not isinstance(values, list) or len(values) > 32 or
            any(not isinstance(value, str) or not _G5_ACTOR_ID_RE.fullmatch(value)
                for value in values) or len(set(values)) != len(values)):
        return None
    return set(values)


def _g5t_name_set(values: Any) -> Optional[set[str]]:
    if not isinstance(values, list) or len(values) > 32:
        return None
    normalized = []
    for value in values:
        if not isinstance(value, str) or not value.strip() or len(value) > 128:
            return None
        normalized.append(" ".join(value.split()).casefold())
    if len(normalized) != len(set(normalized)):
        return None
    return set(normalized)


def _g5t_trace_record_names(event: Dict[str, Any], field: str) -> Optional[set[str]]:
    values = event.get(field)
    if not isinstance(values, list) or len(values) > 32:
        return None
    names = []
    for row in values:
        if not isinstance(row, dict):
            return None
        name = row.get("name")
        if not isinstance(name, str) or not name.strip() or len(name) > 128:
            return None
        names.append(" ".join(name.split()).casefold())
    return set(names)


def _g5t_fallback_batch_menu_removal(
    trace_events: List[Dict[str, Any]], actor_name: Any, current_round: int
) -> Optional[tuple[Optional[bool], Optional[bool], bool]]:
    """Use later validated fallback-batch cohorts when no plan result exists."""
    if not isinstance(actor_name, str) or not actor_name.strip():
        return None
    normalized_actor = " ".join(actor_name.split()).casefold()
    decisions_by_batch: Dict[str, List[Dict[str, Any]]] = {}
    for event in trace_events:
        if (not isinstance(event, dict) or event.get("event_type") != "decision" or
                event.get("decision_point") != "enemy_batch_resolution"):
            continue
        candidate_batch = event.get("batch_id")
        if (not isinstance(candidate_batch, str) or
                not _G5_BATCH_ID_RE.fullmatch(candidate_batch) or
                int(candidate_batch.split("r", 1)[1]) <= current_round):
            continue
        decisions_by_batch.setdefault(candidate_batch, []).append(event)
    if not decisions_by_batch:
        return None

    actor_removed = True
    target_removed = True
    fallback_sources = {"deterministic", "llm_fallback", "jev"}
    for candidate_batch, decisions in decisions_by_batch.items():
        if len(decisions) != 1 or decisions[0].get("decision_source") not in fallback_sources:
            return None
        action_batches = [event for event in trace_events
                          if isinstance(event, dict) and
                          event.get("event_type") == "combat_observation" and
                          event.get("observation") == "combat_action_batch" and
                          event.get("batch_id") == candidate_batch]
        validation_events = [event for event in trace_events
                             if isinstance(event, dict) and
                             event.get("event_type") == "combat_observation" and
                             event.get("observation") == "combat_validation_result" and
                             event.get("batch_id") == candidate_batch]
        if len(action_batches) != 1:
            return None
        action_batch = action_batches[0]
        if (action_batch.get("validation_accepted") is not True or
                action_batch.get("enemy_phase_batch") is not True):
            return None
        action_cohort = _g5t_name_set(action_batch.get("eligible_non_pc_cohort"))
        explicit_actors = _g5t_trace_record_names(action_batch, "explicit_actor_records")
        affected_entities = _g5t_trace_record_names(action_batch, "affected_entities")
        if action_cohort is None or explicit_actors is None or affected_entities is None:
            return None
        if decisions[0].get("decision_source") == "llm_fallback" and len(validation_events) != 1:
            return None
        if len(validation_events) > 1:
            return None
        if validation_events:
            validation = validation_events[0]
            validation_cohort = _g5t_name_set(validation.get("eligible_non_pc_cohort"))
            if (validation.get("validation_accepted") is not True or
                    validation_cohort is None or validation_cohort != action_cohort):
                return None

        if normalized_actor in action_cohort:
            actor_removed = False
            target_removed = False
        if normalized_actor in explicit_actors:
            actor_removed = False
        if normalized_actor in affected_entities:
            target_removed = False

    return actor_removed, target_removed, False


def _g5t_batch_after_snapshot_ref(
    run_dir: Optional[Path], batch: Dict[str, Any], after_snapshot_ref: Any
) -> Any:
    """Reference the per-batch after snapshot, falling back to the final snapshot."""
    index = batch.get("index")
    if (run_dir is None or not isinstance(index, int) or isinstance(index, bool) or
            index < 1):
        return after_snapshot_ref
    step_ref = "snapshots/step-%03d-after.json" % index
    candidate, error = _bundle_file(Path(run_dir), step_ref)
    return step_ref if candidate is not None and error is None else after_snapshot_ref


def _g5t_self_preservation_menu_removal(
    trace_events: List[Dict[str, Any]],
    actor_id: Any,
    batch_id: Any,
    *,
    actor_name: Any = None,
    encounter_cleared: bool,
    auto_exit_batches: set[str],
) -> tuple[Optional[bool], Optional[bool], bool]:
    """Derive menu removal from later plans or validated fallback-batch cohorts."""
    if (not isinstance(actor_id, str) or not _G5_ACTOR_ID_RE.fullmatch(actor_id) or
            not isinstance(batch_id, str) or not _G5_BATCH_ID_RE.fullmatch(batch_id)):
        return None, None, False
    current_round = int(batch_id.split("r", 1)[1])
    later_results = []
    for event in trace_events:
        if (not isinstance(event, dict) or
                event.get("observation") != "combat_tactical_plan_result"):
            continue
        candidate_batch = event.get("batch_id")
        if not isinstance(candidate_batch, str) or not _G5_BATCH_ID_RE.fullmatch(candidate_batch):
            continue
        if int(candidate_batch.split("r", 1)[1]) > current_round:
            later_results.append(event)

    satisfied_by_exit = (
        encounter_cleared and batch_id in auto_exit_batches and not later_results
    )
    if satisfied_by_exit:
        return None, None, True
    if not later_results:
        fallback_result = _g5t_fallback_batch_menu_removal(
            trace_events, actor_name,
            int(batch_id.split("r", 1)[1]),
        )
        if fallback_result is not None:
            return fallback_result
        return None, None, False

    later_actor_menus = [_g5t_menu_actor_ids(event, "actor_ids") for event in later_results]
    later_target_menus = [_g5t_menu_actor_ids(event, "target_ids") for event in later_results]
    if any(menu is None for menu in later_actor_menus + later_target_menus):
        return None, None, False
    return (
        all(actor_id not in menu for menu in later_actor_menus if menu is not None),
        all(actor_id not in menu for menu in later_target_menus if menu is not None),
        False,
    )


def _same_mechanics(before: Dict[str, Any], after: Dict[str, Any]) -> bool:
    return _state_projection(before) == _state_projection(after)


def _counter_delta(before: Any, after: Any, key: str) -> Optional[int]:
    if not isinstance(before, dict) or not isinstance(after, dict):
        return None
    left, right = before.get(key), after.get(key)
    if not _finite_number(left) or not _finite_number(right):
        return None
    return int(right - left) if right - left == int(right - left) else None


def _g5t_commander_batch_state(
    events: List[Dict[str, Any]], batch_id: Any
) -> tuple[Optional[bool], Optional[bool]]:
    """Return (commander_planned, plan_contributed_choices) for one batch."""
    decisions = [event for event in events
                 if event.get("event_type") == "decision"
                 and event.get("decision_point") == "enemy_batch_resolution"
                 and event.get("batch_id") == batch_id]
    plan_results = [event for event in events
                    if event.get("event_type") == "combat_observation"
                    and event.get("observation") == "combat_tactical_plan_result"
                    and event.get("batch_id") == batch_id]
    if len(decisions) > 1 or len(plan_results) > 1:
        return None, None
    source = decisions[0].get("decision_source") if decisions else None
    outcome = plan_results[0].get("tactical_plan_outcome") if plan_results else None
    if outcome in ("accepted", "partially_defaulted"):
        if source == "llm_tactical":
            squad_events = [event for event in events
                            if event.get("event_type") == "combat_observation"
                            and event.get("observation") == "commander_squad_follows_orders"
                            and event.get("batch_id") == batch_id]
            if len(squad_events) != 1 or not _g5t_observation_counts_valid(squad_events[0]):
                return True, None
            return True, squad_events[0].get("applied_choice_count", 0) > 0
        return None, None
    if outcome == "rejected_all":
        if source in ("deterministic", "llm_fallback", "jev"):
            return False, False
        if source != "llm_tactical":
            return None, None
        squad_events = [event for event in events
                        if event.get("event_type") == "combat_observation"
                        and event.get("observation") == "commander_squad_follows_orders"
                        and event.get("batch_id") == batch_id]
        if (len(squad_events) == 1
                and (not _g5t_observation_counts_valid(squad_events[0])
                     or squad_events[0].get("applied_choice_count", 0) != 0)):
            return True, None
        return True, False
    if source == "llm_tactical":
        # Missing plan-result evidence must not look like a no-plan deviation.
        return True, None
    if source in ("deterministic", "llm_fallback", "jev"):
        return False, False
    return None, None


def _g5t_observation_counts_valid(event: Dict[str, Any]) -> bool:
    issued = event.get("issued_choice_count")
    applied = event.get("applied_choice_count")
    return (
        isinstance(issued, int) and not isinstance(issued, bool) and 0 <= issued <= 32
        and isinstance(applied, int) and not isinstance(applied, bool)
        and 0 <= applied <= issued
    )


def observed_checks(profile: Dict[str, Any], before: Optional[Dict[str, Any]],
                    after: Dict[str, Any], artifacts: Dict[str, Any],
                    steps: Optional[List[Dict[str, Any]]] = None,
                    observations: Optional[List[Dict[str, Any]]] = None,
                    run_dir: Optional[Path] = None, *,
                    g5a_metadata: Optional[Dict[str, Any]] = None,
                    g5a_sandbox_identity: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Evaluate required checks against captured snapshots and gated runtime events."""
    step_rows = steps or []
    events = observations or []
    checks: List[Dict[str, Any]] = []

    def record(check_id: str, expected: Any, observed: Any, valid: Optional[bool], evidence: Any) -> None:
        checks.append({"id": check_id, "required": True, "expected": expected,
                       "observed": observed, "status": "BLOCKED" if valid is None else
                       ("PASS" if valid else "FAIL"), "evidence": evidence})

    scenario = profile["scenario_id"]
    party_size = profile["party_size"]
    before_records, after_records = _step_records(before), _step_records(after)
    causal_linkage = link_trace_events_to_steps(events, step_rows)
    linked_events = causal_linkage.get("events", [])
    event_step = {id(row["event"]): row["step"] for row in linked_events}
    smoke_case = scenario in ("combat-smoke", "combat-smoke-allied-inactive")
    hp_ledger = _hp_causal_ledger(before, step_rows, after, events) if smoke_case else None
    apply_events = [event for event in events if event.get("observation") == "combat_apply_result"]
    apply_failures = [event for event in apply_events if event.get("applied") is not True]
    checks.append({"id": "mechanical_apply_outcomes", "required": True,
                   "expected": "every observed encounter/character apply operation returns success",
                   "observed": [{"domain": event.get("domain"), "operation": event.get("operation"),
                                 "target": event.get("target"), "applied": event.get("applied"),
                                 "failure": event.get("failure")} for event in apply_events],
                   "status": "FAIL" if apply_failures else "PASS",
                   "evidence": "combat_apply_result trace events"})
    if smoke_case:
        causal_check = _causal_evidence_check(profile, step_rows, events)
        position_errors = artifacts.get("trace_position_errors", [])
        if position_errors and causal_check["status"] != "FAIL":
            causal_check["status"] = "BLOCKED"
            causal_check["observed"] = {"status": "BLOCKED", "reason": "trace_position_parse_errors",
                                         "errors": position_errors}
        checks.append(causal_check)
    selected_before = before_records.get("selected_encounter", {})
    selected_after = after_records.get("selected_encounter", {})
    hp_operations: Dict[Tuple[str, str], int] = {}
    g5a_step_hp_operations: Dict[Tuple[int, str, str], int] = {}
    g5a_step_hp_names: Dict[Tuple[int, str, str], str] = {}
    g5a_unpositioned_hp_operation = False
    g5a_invalid_hp_operation = False
    g5a_case = scenario in ("g5a-ally-p1", "g5a-ally-p4")
    if scenario in ("combat-smoke", "combat-smoke-allied-inactive") and causal_linkage.get("status") != "PASS":
        hp_operations = {}
    for event in apply_events:
        if event.get("applied") is not True:
            continue
        if scenario in ("combat-smoke", "combat-smoke-allied-inactive") and id(event) not in event_step:
            continue
        raw_operations = event.get("ops")
        if g5a_case and raw_operations is not None and not isinstance(raw_operations, list):
            g5a_invalid_hp_operation = True
            continue
        for operation in raw_operations or []:
            if not isinstance(operation, dict):
                if g5a_case:
                    g5a_invalid_hp_operation = True
                continue
            if operation.get("op") != "hp_delta":
                continue
            name = operation.get("creature") if event.get("domain") == "encounter" else event.get("target")
            delta = operation.get("delta")
            if isinstance(name, str) and _finite_number(delta) and int(delta) == delta:
                domain = event.get("domain")
                if g5a_case and domain not in ("character", "encounter"):
                    g5a_invalid_hp_operation = True
                    continue
                normalized_name = (
                    " ".join(name.split()).casefold() if g5a_case else name.casefold()
                )
                key = (str(domain), normalized_name)
                hp_operations[key] = hp_operations.get(key, 0) + int(delta)
                if g5a_case:
                    step_number = event_step.get(id(event))
                    if not isinstance(step_number, int) or isinstance(step_number, bool):
                        g5a_unpositioned_hp_operation = True
                    else:
                        step_key = (step_number, key[0], key[1])
                        g5a_step_hp_operations[step_key] = (
                            g5a_step_hp_operations.get(step_key, 0) + int(delta)
                        )
                        g5a_step_hp_names[step_key] = name
            elif g5a_case:
                g5a_invalid_hp_operation = True
    reconciliation_operations = dict(hp_operations)
    if scenario in ("g5t-commander-p1", "g5t-commander-p4"):
        character_hp_operations = {
            name: delta for (domain, name), delta in hp_operations.items()
            if domain == "character"
        }
        encounter_names = set()
        for snapshot in (selected_before, selected_after):
            creatures = snapshot.get("creatures") if isinstance(snapshot, dict) else None
            if not isinstance(creatures, list):
                continue
            encounter_names.update(
                str(creature.get("name", "")).casefold()
                for creature in creatures
                if isinstance(creature, dict) and isinstance(creature.get("name"), str)
            )
        for name, character_delta in character_hp_operations.items():
            if name in encounter_names:
                # The legacy fallback may persist a character HP operation and
                # update the encounter's mirrored PC HP in its final projection
                # without emitting a second encounter hp_delta apply event.
                # Compare both canonical cells to the character operation rather
                # than mistaking the missing mirror event for state divergence.
                reconciliation_operations[("encounter", name)] = character_delta
    reconciliation = []
    reconciliation_status = None
    reconciliation_errors: List[str] = []
    if g5a_case:
        reconciliation_status, reconciliation, reconciliation_errors = _g5a_reconcile_hp_steps(
            party_size,
            step_rows,
            events,
            event_step,
            g5a_step_hp_operations,
            g5a_step_hp_names,
            unpositioned_operation=(
                g5a_unpositioned_hp_operation or g5a_invalid_hp_operation
            ),
            linkage_status=causal_linkage.get("status"),
            metadata=g5a_metadata,
        )
    else:
        for (domain, name), expected_delta in reconciliation_operations.items():
            if domain == "character":
                start_rows = [row for key, row in before_records.items()
                              if key.startswith("characters/") and str(row.get("name", "")).casefold() == name]
                end_rows = [row for key, row in after_records.items()
                            if key.startswith("characters/") and str(row.get("name", "")).casefold() == name]
                start_hp = start_rows[0].get("hitPoints") if len(start_rows) == 1 else None
                end_hp = end_rows[0].get("hitPoints") if len(end_rows) == 1 else None
            else:
                start_rows = [row for row in (selected_before.get("creatures") or [])
                              if isinstance(row, dict) and str(row.get("name", "")).casefold() == name]
                end_rows = [row for row in (selected_after.get("creatures") or [])
                            if isinstance(row, dict) and str(row.get("name", "")).casefold() == name]
                start_hp = start_rows[0].get("currentHitPoints") if len(start_rows) == 1 else None
                end_hp = end_rows[0].get("currentHitPoints") if len(end_rows) == 1 else None
            observed_delta = end_hp - start_hp if _finite_number(start_hp) and _finite_number(end_hp) else None
            reconciliation.append({"domain": domain, "target": name, "expected_delta": expected_delta,
                                   "observed_delta": observed_delta})
    hp_check = {
        "id": "hp_delta_snapshot_reconciliation",
        "required": True,
        "expected": (
            "position-linked per-step HP mutations and mirror projections match canonical run totals"
            if smoke_case else
            ("applied G5A HP operations or strictly evidenced persisted per-step HP deltas reconcile"
             if g5a_case else
             ("applied character HP deltas and encounter mirrors match canonical before/after state"
              if scenario in ("g5t-commander-p1", "g5t-commander-p4") else
              "unambiguous applied hp_delta operations match canonical before/after state"))
        ),
        "observed": hp_ledger if smoke_case else reconciliation,
        "status": (
            ("FAIL" if hp_ledger["status"] == "FAIL" else
             ("BLOCKED" if artifacts.get("trace_position_errors") else hp_ledger["status"]))
            if smoke_case else
            (reconciliation_status if g5a_case else
             ("PASS" if not reconciliation else
              ("BLOCKED" if any(row["observed_delta"] is None for row in reconciliation) else
               ("PASS" if all(row["expected_delta"] == row["observed_delta"]
                              for row in reconciliation) else "FAIL"))))
        ),
        "evidence": "apply operation trace + canonical run snapshots",
    }
    if g5a_case:
        hp_check["evidence_errors"] = reconciliation_errors
    checks.append(hp_check)
    expected_names = ["Acheron"] if party_size == 1 else ["Acheron", "Merisiel", "Kira", "Vitreol"]
    party_before = before_records.get("party_tracker.json", {})
    party_members = party_before.get("partyMembers")
    record("party_roster_identity", expected_names, party_members,
           None if party_before.get("status") != "ok" else party_members == expected_names,
           "snapshots/before-run.json")

    record("selected_encounter_available", "actual seeded encounter record",
           {"id": selected_after.get("encounterId"), "read_status": selected_after.get("status")},
            None if selected_after.get("status") != "ok" else bool(selected_after.get("encounterId")),
            "snapshots/before-run.json + snapshots/after-run.json")

    validation_events = [event for event in events if event.get("observation") == "combat_validation_result"]
    validation_failures = [event for event in validation_events if event.get("validation_accepted") is not True]
    resolver_decisions = [
        event for event in events
        if event.get("event_type") == "decision"
        and event.get("decision_point") == "enemy_batch_resolution"
        and event.get("decision_outcome") == "resolver_supported"
    ]
    requires_response = (scenario in ("combat-smoke", "combat-smoke-allied-inactive",
                                      "initiative-dm-tie") or
                         (scenario == "surrender-exit" and profile.get("branch") == "surrender"))
    if resolver_decisions:
        resolver_rows = []
        resolver_valid = True
        for decision in resolver_decisions:
            batch_id = decision.get("batch_id")
            batch_id_valid = isinstance(batch_id, str) and bool(_G5_BATCH_ID_RE.fullmatch(batch_id))
            same_batch = [event for event in events if batch_id_valid and event.get("batch_id") == batch_id]
            narration_results = [
                event for event in same_batch
                if event.get("observation") == "combat_batch_narration_result"
                and event.get("source") in ("llm", "template")
            ]
            provider_trace = artifacts.get("trace_provider_events")
            if not isinstance(provider_trace, list):
                provider_trace = events
            validation_calls = [
                event for event in provider_trace
                if event.get("batch_id") == batch_id
                if event.get("event_type") == "provider"
                and (event.get("site") == "combat_validation"
                     or event.get("task") == "combat_validation"
                     or event.get("purpose") in ("combat_validation", "verify_combat_response"))
            ]
            allowed_decision_sources = {"deterministic"}
            is_named_g5t_commander = (
                profile.get("gate") == "g5t"
                and party_size in (1, 4)
                and scenario == "g5t-commander-p%d" % party_size
            )
            if is_named_g5t_commander:
                allowed_decision_sources.add("llm_tactical")
            row_valid = (
                decision.get("decision_source") in allowed_decision_sources
                and batch_id_valid
                and len(narration_results) == 1
                and not validation_calls
            )
            resolver_valid = resolver_valid and row_valid
            resolver_rows.append({
                "batch_id": batch_id,
                "logical_turn": decision.get("logical_turn"),
                "decision_source": decision.get("decision_source"),
                "narration_sources": [event.get("source") for event in narration_results],
                "validation_provider_calls": len(validation_calls),
                "status": "PASS" if row_valid else "BLOCKED",
            })
        validation_truth_status = (
            "FAIL" if validation_failures else
            "PASS" if resolver_valid and not validation_failures else "BLOCKED"
        )
        checks.append({
            "id": "final_response_validation_truth",
            "required": requires_response,
            "expected": (
                "resolver-supported batch has an allowed decision and narration result, "
                "with no combat-validation provider call"
            ),
            "observed": {"resolver_batches": resolver_rows,
                         "legacy_validation": [{
                             "logical_turn": event.get("logical_turn"),
                             "accepted": event.get("validation_accepted"),
                         } for event in validation_events]},
            "status": validation_truth_status,
            "evidence": "enemy_batch_resolution decision + combat_batch_narration_result + batch-scoped provider trace",
        })
    else:
        checks.append({"id": "final_response_validation_truth", "required": requires_response,
                       "expected": "each final combat response marked by actual retry-stage valid_response",
                       "observed": [{"logical_turn": event.get("logical_turn"),
                                     "accepted": event.get("validation_accepted")} for event in validation_events],
                       "status": "FAIL" if validation_failures else
                       ("PASS" if validation_events else "BLOCKED"),
                       "evidence": "combat_validation_result trace events"})
    accepted_batches = [event for event in events if event.get("observation") == "combat_action_batch"
                        and event.get("validation_accepted") is True]
    batch_by_turn: Dict[Any, List[Dict[str, Any]]] = {}
    completion_by_turn: Dict[Any, List[Dict[str, Any]]] = {}
    completed_batches = [event for event in events
                         if event.get("observation") == "combat_logical_batch_completed"
                         and event.get("accepted_batch") is True]
    for event in events:
        if event.get("observation") == "combat_action_batch":
            batch_by_turn.setdefault(event.get("logical_turn"), []).append(event)
        elif event.get("observation") == "combat_logical_batch_completed":
            completion_by_turn.setdefault(event.get("logical_turn"), []).append(event)
    if requires_response:
        if resolver_decisions:
            resolver_batch_rows = []
            resolver_turns = set()
            resolver_batches_valid = True
            for decision in resolver_decisions:
                batch_id = decision.get("batch_id")
                logical_turn = decision.get("logical_turn")
                valid_identity = (
                    isinstance(batch_id, str)
                    and bool(_G5_BATCH_ID_RE.fullmatch(batch_id))
                    and isinstance(logical_turn, int)
                    and not isinstance(logical_turn, bool)
                    and logical_turn > 0
                )
                decision_matches = [
                    event for event in resolver_decisions
                    if event.get("batch_id") == batch_id
                    and event.get("logical_turn") == logical_turn
                ]
                action_matches = [
                    event for event in events
                    if event.get("observation") == "combat_action_batch"
                    and event.get("batch_id") == batch_id
                    and event.get("logical_turn") == logical_turn
                ]
                completion_matches = [
                    event for event in events
                    if event.get("observation") == "combat_logical_batch_completed"
                    and event.get("batch_id") == batch_id
                    and event.get("logical_turn") == logical_turn
                ]
                row_valid = (
                    valid_identity
                    and len(decision_matches) == 1
                    and len(action_matches) == 1
                    and action_matches[0].get("validation_accepted") is True
                    and len(completion_matches) == 1
                    and completion_matches[0].get("accepted_batch") is True
                )
                resolver_batches_valid = resolver_batches_valid and row_valid
                if valid_identity:
                    resolver_turns.add(logical_turn)
                resolver_batch_rows.append({
                    "batch_id": batch_id,
                    "logical_turn": logical_turn,
                    "decision_events": len(decision_matches),
                    "action_batch_events": len(action_matches),
                    "action_batch_accepted": (
                        action_matches[0].get("validation_accepted") is True
                        if len(action_matches) == 1 else None
                    ),
                    "completion_events": len(completion_matches),
                    "completion_accepted": (
                        completion_matches[0].get("accepted_batch") is True
                        if len(completion_matches) == 1 else None
                    ),
                    "status": "PASS" if row_valid else "BLOCKED",
                })

            legacy_accepted_turns = {
                event.get("logical_turn") for event in validation_events
                if event.get("validation_accepted") is True
                and event.get("logical_turn") not in resolver_turns
            }
            legacy_rows = [{
                "logical_turn": logical_turn,
                "batch_events": len(batch_by_turn.get(logical_turn, [])),
                "completion_events": len(completion_by_turn.get(logical_turn, [])),
            } for logical_turn in sorted(
                legacy_accepted_turns, key=lambda value: (value is None, str(value))
            )]
            legacy_valid = all(
                row["logical_turn"] is not None
                and row["batch_events"] == 1
                and row["completion_events"] == 1
                for row in legacy_rows
            )
            check_valid = resolver_batches_valid and legacy_valid
            checks.append({
                "id": "accepted_logical_batch_once",
                "required": True,
                "expected": "each supported resolver batch has exactly one accepted action batch and one accepted completion with the same batch_id and logical_turn; legacy valid responses retain turn pairing",
                "observed": {"resolver_batches": resolver_batch_rows,
                             "legacy_valid_response_turns": legacy_rows},
                "status": "PASS" if check_valid else "BLOCKED",
                "evidence": "batch_id and logical_turn identity in resolver action/completion trace events",
            })
        else:
            accepted_response_turns = {
                event.get("logical_turn") for event in validation_events
                if event.get("validation_accepted") is True
            }
            batch_completion_rows = [{
                "logical_turn": logical_turn,
                "batch_events": len(batch_by_turn.get(logical_turn, [])),
                "completion_events": len(completion_by_turn.get(logical_turn, [])),
            } for logical_turn in sorted(
                accepted_response_turns, key=lambda value: (value is None, str(value))
            )]
            missing_batch_observation = any(
                row["logical_turn"] is None
                or row["batch_events"] != 1
                or row["completion_events"] != 1
                for row in batch_completion_rows
            )
            checks.append({"id": "accepted_logical_batch_once", "required": True,
                           "expected": "one accepted action batch and one post-application completion per valid_response",
                           "observed": batch_completion_rows,
                           "status": "BLOCKED" if not batch_completion_rows or missing_batch_observation else "PASS",
                           "evidence": "logical_turn identity in runtime trace events"})

    if scenario in ("combat-smoke", "combat-smoke-allied-inactive"):
        creatures = selected_after.get("creatures")
        pc_rows = [row for row in creatures if row.get("type") == "player"] if isinstance(creatures, list) else []
        pc_names = [row.get("name") for row in pc_rows]
        living_non_pc = [row for row in creatures if row.get("type") != "player"
                         and row.get("status") == "alive" and _finite_number(row.get("currentHitPoints"))
                         and row["currentHitPoints"] > 0] if isinstance(creatures, list) else []
        record("complete_unique_pc_roster", expected_names, pc_names,
               None if selected_after.get("status") != "ok" else
               len(pc_names) == len(expected_names) and {str(n).casefold() for n in pc_names} ==
               {n.casefold() for n in expected_names}, "snapshots/after-run.json")
        record("living_non_pc_roster", "at least one living non-PC", [r.get("name") for r in living_non_pc],
               None if selected_after.get("status") != "ok" else bool(living_non_pc), "snapshots/after-run.json")
        scripted_actors = [(row.get("before") or {}).get("observation", {}).get("character") for row in step_rows]
        expected_active_seen = all(
            actor == (row.get("before") or {}).get("records", {}).get("party_tracker.json", {}).get("active_character")
            for actor, row in zip(scripted_actors, step_rows)
        )
        record("active_pc_identity_per_step", "scripted actor matches persisted active PC",
               expected_active_seen, expected_active_seen if step_rows and any(
                   (row.get("before") or {}).get("observation", {}).get("character") for row in step_rows
               ) and all(isinstance(actor, str) and actor for actor in scripted_actors) else None,
               "snapshots/step-*-before.json")
        phase_rows = accepted_batches
        rounds = [event.get("combat_round_before_round_transition") for event in phase_rows]
        round_values_valid = bool(phase_rows) and all(_finite_number(value) for value in rounds)
        completed_by_turn = {event.get("logical_turn"): event for event in completed_batches}
        record("phase_round_progression_observed", "pre-transition phase/cohort and post-batch round progression",
               [{"phase_before": event.get("phase_before_round_transition"),
                 "round_before": event.get("combat_round_before_round_transition"),
                 "round_requested": event.get("round_transition_requested"),
                 "round_after": completed_by_turn.get(event.get("logical_turn"), {}).get("round_after"),
                 "phase_after": completed_by_turn.get(event.get("logical_turn"), {}).get("phase_after_processing"),
                 "cohort_reason": event.get("cohort_reason")} for event in phase_rows],
               None if not round_values_valid else rounds == sorted(rounds) and
               all(event.get("phase_before_round_transition") in ("PC_PHASE", "ENEMY_PHASE")
                   for event in phase_rows) and all(event.get("logical_turn") in completed_by_turn
                                                    for event in phase_rows),
               "pre-transition combat_action_batch + post-application completion trace events")
        # Deterministic damage is credited only with an actual fast-path decision
        # in the same source-positioned step and canonical per-step state proof.
        damage_rows = []
        linked_by_step: Dict[int, List[Dict[str, Any]]] = {}
        for row in linked_events:
            linked_by_step.setdefault(row["step"], []).append(row["event"])
        for step_number, row in enumerate(step_rows, 1):
            step_input = (row.get("before") or {}).get("observation", {}).get("input", "")
            damage = re.match(r"^/dmg\s+(\d+)\b", str(step_input), re.IGNORECASE)
            if damage:
                before_obs = (row.get("before") or {}).get("observation", {})
                before_party = _step_records(row.get("before")).get("party_tracker.json", {})
                actor = before_obs.get("character")
                actor_proven = isinstance(actor, str) and actor == before_party.get("active_character")
                changed = []
                old_rows = _selected_encounter(row.get("before")).get("creatures")
                new_rows = _selected_encounter(row.get("after")).get("creatures")
                old_by_name = {str(item.get("name", "")).casefold(): item for item in old_rows or []
                               if isinstance(item, dict)}
                new_by_name = {str(item.get("name", "")).casefold(): item for item in new_rows or []
                               if isinstance(item, dict)}
                for name in old_by_name.keys() & new_by_name.keys():
                    left, right = old_by_name[name].get("currentHitPoints"), new_by_name[name].get("currentHitPoints")
                    if _finite_number(left) and _finite_number(right) and left != right:
                        changed.append((name, left, right))
                target, before_hp, after_hp = changed[0] if len(changed) == 1 else (None, None, None)
                amount = int(damage.group(1))
                delta = before_hp - after_hp if _finite_number(before_hp) and _finite_number(after_hp) else None
                fast_path = [event for event in linked_by_step.get(step_number, [])
                             if event.get("event_type") == "decision" and
                             event.get("decision_point") == "combat_command_fast_path" and
                             event.get("decision_source") == "deterministic" and
                             event.get("provider_call_avoided") is True]
                damage_rows.append({"step": before_obs.get("label"), "actor": actor,
                                    "actor_matches_active_pc": actor_proven,
                                    "canonical_changed_entity": target,
                                    "expected_delta": amount, "observed_delta": delta,
                                    "fast_path_decisions": len(fast_path)})
        record("deterministic_damage_exact_per_command", "each /dmg N reduces attacked target HP by N",
               damage_rows, None if not damage_rows or any(row["observed_delta"] is None or
                    row["fast_path_decisions"] != 1 or not row["actor_matches_active_pc"]
                    for row in damage_rows)
               else all(row["observed_delta"] == row["expected_delta"] for row in damage_rows),
               "same-step deterministic fast-path decision + canonical step snapshots")
        if scenario == "combat-smoke-allied-inactive":
            ally = next((row for row in selected_before.get("creatures", []) if row.get("npcType") == "ally"), None)
            inactive = next((row for row in selected_before.get("creatures", []) if row.get("name") == "Inactive Goblin"), None)
            action_batches = [event for event in accepted_batches if event.get("enemy_phase_batch") is True]
            eligible_cohorts = []
            explicit_actor_records = []
            for event in action_batches:
                cohort = {str(name).casefold() for name in event.get("eligible_non_pc_cohort", [])
                          if isinstance(name, str)}
                eligible_cohorts.append(cohort)
                explicit_actor_records.extend({"name": row.get("name"), "source": row.get("source"),
                                               "in_cohort": str(row.get("name", "")).casefold() in cohort}
                                              for row in event.get("explicit_actor_records", [])
                                              if isinstance(row, dict))
            ally_name = str((ally or {}).get("name", "")).casefold()
            inactive_name = str((inactive or {}).get("name", "")).casefold()
            expected_eligible = {str(row.get("name", "")).casefold() for row in
                                 (selected_before.get("creatures") or []) if isinstance(row, dict)
                                 and row.get("type") in ("enemy", "npc") and row.get("status") == "alive"
                                 and _finite_number(row.get("currentHitPoints")) and row["currentHitPoints"] > 0}
            record("ally_and_inactive_actual_batch_filter", "accepted batch cohort includes ally and excludes inactive/PCs",
                   {"accepted_batch_cohorts": [sorted(cohort) for cohort in eligible_cohorts],
                    "expected_seed_cohort": sorted(expected_eligible),
                    "explicit_actor_records": explicit_actor_records,
                    "ally": ally_name, "inactive": inactive_name},
                   None if not ally or not inactive or not action_batches else
                   ally.get("type") == "npc" and any(ally_name in cohort for cohort in eligible_cohorts) and
                   all(cohort.issubset(expected_eligible) and inactive_name not in cohort
                       for cohort in eligible_cohorts) and
                   all(row["in_cohort"] for row in explicit_actor_records),
                   "runtime combat_observation events + seeded encounter snapshot")
    elif scenario in ("initiative-pc", "initiative-dm-tie"):
        invalid = [row for row in step_rows if row["before"].get("observation", {}).get("input") == "/init 21"]
        invalid_events = [event for event in events if event.get("observation") == "initiative_gate"
                          and event.get("input") == "/init 21"]
        invalid_held = bool(invalid) and all(_same_mechanics(row["before"], row["after"]) for row in invalid)
        record("invalid_initiative_holds_pending_gate", "invalid /init leaves mechanical state unchanged",
               {"steps": len(invalid), "gate_events": len(invalid_events)},
               None if not invalid or not invalid_events else invalid_held and
               all(event.get("accepted") is False for event in invalid_events),
               "per-step read-only snapshots + initiative_gate trace")
        accepted = [event for event in events if event.get("observation") == "initiative_gate"
                    and event.get("accepted") is True]
        expected_winner = "pcGroup" if scenario == "initiative-pc" else "dmGroup"
        winner_events = [event for event in accepted if event.get("expected_winner") == expected_winner]
        record("initiative_expected_winner", expected_winner,
               [event.get("expected_winner") for event in winner_events],
               None if not accepted else bool(winner_events), "runtime initiative_gate observation")
        if scenario == "initiative-pc":
            opening_events = [event for event in events
                              if event.get("observation") == "opening_enemy_batch_completed" or
                              (event.get("observation") == "combat_action_batch" and
                               event.get("validation_accepted") is True and
                               event.get("enemy_phase_batch") is True)]
            record("pc_win_without_opening_batch", "PC winner and no opening batch", selected_after.get("initiativeWinner"),
                   None if selected_after.get("status") != "ok" or not accepted else
                   selected_after.get("initiativeWinner") == "pcGroup" and
                   selected_after.get("openingEnemyBatchPending") is False and not opening_events,
                   "snapshots/after-run.json + initiative/batch observations")
        else:
            pending_events = [event for event in accepted if event.get("marker_enabled") is True]
            opening_batches = [event for event in accepted_batches if event.get("enemy_phase_batch") is True
                               and event.get("opening_batch_pending_before_round_transition") is True]
            expected_cohort = pending_events[0].get("eligible_non_pc_cohort") if pending_events else None
            actual_cohort = opening_batches[0].get("eligible_non_pc_cohort") if len(opening_batches) == 1 else None
            explicit_actor_records = (opening_batches[0].get("explicit_actor_records", [])
                                      if len(opening_batches) == 1 else [])
            cohort = {str(name).casefold() for name in actual_cohort or []}
            explicit_actor_mismatch = any(row.get("source") not in ("actor", "actorName") or
                                          str(row.get("name", "")).casefold() not in cohort
                                          for row in explicit_actor_records if isinstance(row, dict))
            completed = [event for event in completed_batches if len(opening_batches) == 1 and
                         event.get("logical_turn") == opening_batches[0].get("logical_turn")]
            marker_events = [event for event in events if event.get("observation") == "opening_enemy_batch_completed"
                             and event.get("opening_marker_before") is True
                             and event.get("opening_marker_after") is False]
            record("dm_tie_eligible_batch_once_and_marker_cleared", "one accepted logical batch uses the pre-transition eligible cohort and completes once",
                   {"pre_transition_cohort": expected_cohort, "batch_pre_transition_cohort": actual_cohort,
                    "accepted_batch_count": len(opening_batches), "batch_completion_count": len(completed),
                    "opening_marker_transition_count": len(marker_events),
                    "explicit_actor_records": explicit_actor_records},
                   None if not expected_cohort or not opening_batches else
                   len(opening_batches) == len(completed) == len(marker_events) == 1 and
                   {str(name).casefold() for name in expected_cohort} == cohort and
                   not explicit_actor_mismatch,
                   "pre-transition initiative/cohort + accepted logical batch + marker observations")
            completion = completed[0] if len(completed) == 1 else {}
            record("dm_tie_returns_to_pc_phase", {"winner": "dmGroup", "marker": False, "phase": "PC_PHASE"},
                   {"winner": selected_after.get("initiativeWinner"),
                    "marker": selected_after.get("openingEnemyBatchPending"),
                    "phase_after_processing": completion.get("phase_after_processing"),
                    "opening_pending_after": completion.get("opening_pending_after")},
                   None if selected_after.get("status") != "ok" or not completion else
                   selected_after.get("initiativeWinner") == "dmGroup" and
                   selected_after.get("openingEnemyBatchPending") is False and
                   completion.get("phase_after_processing") == "PC_PHASE" and
                   completion.get("opening_pending_after") is False,
                   "after-run encounter snapshot + post-application completion trace")
    elif scenario == "death-save":
        actor_name = "Acheron"
        invalid_rows = [row for row in step_rows if row["before"].get("observation", {}).get("label") == "invalid death save"]
        wrong_rows = [row for row in step_rows if row["before"].get("observation", {}).get("label") == "wrong actor"]
        legal_rows = [row for row in step_rows if row["before"].get("observation", {}).get("label") == "legal death save"]
        invalid_events = [event for event in events if event.get("observation") == "death_save_roll"
                          and event.get("input") == "21"]
        wrong_events = [event for event in events if event.get("observation") == "death_save_actor_gate"
                        and event.get("actor") == "Merisiel" and event.get("pending_pc") == actor_name]
        legal_events = [event for event in events if event.get("observation") == "death_save_roll"
                        and event.get("valid") is True]
        pending_before = before_records.get("characters/acheron.json", {})
        record("pending_pc_death_state_seeded", "Acheron starts at 0 HP and unconscious with 0/0 saves",
               {"hitPoints": pending_before.get("hitPoints"), "status": pending_before.get("status"),
                "deathSaves": pending_before.get("deathSaves")},
               None if pending_before.get("read_status") != "ok" else
               _finite_number(pending_before.get("hitPoints")) and pending_before.get("hitPoints") == 0 and
               str(pending_before.get("status", "")).lower() in ("unconscious", "incapacitated") and
               pending_before.get("deathSaves") == {"successes": 0, "failures": 0},
               "snapshots/before-run.json")
        invalid_ok = bool(invalid_rows) and all(_same_mechanics(r["before"], r["after"]) for r in invalid_rows)
        invalid_ok = invalid_ok and all(event.get("valid") is False for event in invalid_events)
        record("invalid_death_roll_no_state_change", "invalid roll rejected and state unchanged",
               len(invalid_events), None if not invalid_events or not invalid_rows else invalid_ok,
               "step snapshots + death_save_roll trace")
        if party_size == 4:
            selection_transitions = []
            selection_allowed = bool(wrong_rows)
            for row in wrong_rows:
                party_before = row["before"].get("records", {}).get("party_tracker.json", {})
                party_after = row["after"].get("records", {}).get("party_tracker.json", {})
                scripted_actor = row["before"].get("observation", {}).get("character")
                before_active, after_active = party_before.get("active_character"), party_after.get("active_character")
                selection_transitions.append({"scripted_actor": scripted_actor,
                                              "active_before": before_active,
                                              "active_after": after_active})
                party_roster = party_before.get("partyMembers")
                selection_allowed = selection_allowed and isinstance(party_roster, list) and \
                    scripted_actor == "Merisiel" and before_active == scripted_actor and \
                    after_active in party_roster
            wrong_ok = (selection_allowed and any(event.get("accepted") is False for event in wrong_events)
                        and all(_same_mechanics(r["before"], r["after"]) for r in wrong_rows))
            record("wrong_actor_rejected_without_state_change", "Merisiel rejected for Acheron pending save",
                   {"actor_gate_events": [{"actor": event.get("actor"), "pending": event.get("pending_pc"),
                                           "accepted": event.get("accepted")} for event in wrong_events],
                    "allowed_active_pc_selection_transition": selection_transitions},
                   None if not wrong_rows or not wrong_events else wrong_ok,
                   "step snapshots + death_save_actor_gate trace")
        save_before = (legal_rows[0]["before"].get("records", {}).get("characters/acheron.json", {}).get("deathSaves")
                       if legal_rows else None)
        save_after = (legal_rows[-1]["after"].get("records", {}).get("characters/acheron.json", {}).get("deathSaves")
                      if legal_rows else None)
        deltas = {key: _counter_delta(save_before, save_after, key) for key in ("successes", "failures")}
        only_pending = all(event.get("resolved_pc") == actor_name for event in legal_events)
        other_changes = None
        if legal_rows:
            old_chars = _state_projection(legal_rows[0]["before"]).get("characters", {})
            new_chars = _state_projection(legal_rows[-1]["after"]).get("characters", {})
            other_changes = {}
            for path in set(old_chars) | set(new_chars):
                old, new = old_chars.get(path), new_chars.get(path)
                if old != new:
                    changed_fields = [name for name in set(old or {}) | set(new or {})
                                      if (old or {}).get(name) != (new or {}).get(name)]
                    other_changes[path] = changed_fields
        no_other_mutation = (other_changes is not None and
                             set(other_changes).issubset({"characters/acheron.json"}) and
                             set(other_changes.get("characters/acheron.json", [])).issubset({"deathSaves"}))
        record("legal_roll_updates_only_pending_pc_once", "legal roll records one save on Acheron only",
               {"save_delta": deltas, "resolved": [event.get("resolved_pc") for event in legal_events],
                "other_character_changes": other_changes},
               None if not legal_rows or not legal_events else only_pending and
               sum(value for value in deltas.values() if value is not None) == 1 and
               all(value in (0, 1) for value in deltas.values()) and no_other_mutation,
               "step character snapshots + death_save_roll trace")
    elif scenario == "surrender-exit":
        sent_inputs = [row.get("before", {}).get("observation", {}).get("input") for row in step_rows]
        if profile.get("branch") == "surrender":
            input_observed = [text for text in sent_inputs if isinstance(text, str)
                              and "party accepts" in text.lower() and "restrains" in text.lower()]
        else:
            input_observed = [text for text in sent_inputs if text == "/end_combat"]
        record("requested_exit_branch_observed", profile.get("branch"), input_observed,
               None if not sent_inputs else bool(input_observed), "step snapshot input records")
        tracker_after = after_records.get("party_tracker.json", {})
        world_after = tracker_after.get("worldConditions")
        active = world_after.get("activeCombatEncounter") if isinstance(world_after, dict) else None
        record("encounter_cleared", "no active encounter", active,
                None if tracker_after.get("status") != "ok" or not isinstance(world_after, dict)
                else active in (None, ""),
                "snapshots/after-run.json")
        final_step = step_rows[-1] if step_rows else None
        final_observation = ((final_step or {}).get("after") or {}).get("observation", {})
        output_count = final_observation.get("game_output_count")
        output_types = final_observation.get("game_output_types", [])
        completion = final_observation.get("completion_criterion")
        explicit_exit = profile.get("branch") == "explicit-exit"
        handoff_label_ok = (final_observation.get("label") == "post-exit narrator handoff"
                            if explicit_exit else
                            final_observation.get("label") == "accept last hostile surrender")
        completion_ok = (isinstance(completion, dict) and
                         completion.get("criterion") == ("backend_narration" if explicit_exit else "backend_output") and
                         (not explicit_exit or completion.get("canonical_encounter_cleared") is True))
        record("narration_handoff_observed", "actual narrator output after encounter clear",
               {"game_output_count": output_count, "backend_output_count": final_observation.get("backend_output_count"),
                "types": output_types, "timed_out": final_observation.get("timed_out"),
                "completion_criterion": completion},
               None if final_step is None or not _finite_number(output_count) or not output_types else
               output_count > 0 and _finite_number(final_observation.get("backend_output_count")) and
               final_observation.get("backend_output_count") > 0 and "narration" in output_types and
               final_observation.get("timed_out") is False and active in (None, "") and
               handoff_label_ok and completion_ok,
               "backend narration + canonical after-run party state")
        health = artifacts.get("health_probe", {})
        record("server_alive_readonly_probe", "GET /api/party returns HTTP 200", health,
               None if health.get("status") in ("not_checked", "unavailable") else
               health.get("status") == "ok" and health.get("http_status") == 200,
               "read-only GET /api/party; separate health_read_attempts")
        initial_chars = {key: val for key, val in before_records.items() if key.startswith("characters/")}
        final_chars = {key: val for key, val in after_records.items() if key.startswith("characters/")}
        xp_deltas = {}
        hp_deltas = {}
        hp_observed = 0
        xp_observed = 0
        for key, initial in initial_chars.items():
            final = final_chars.get(key, {})
            start_xp, end_xp = initial.get("experience_points"), final.get("experience_points")
            if _finite_number(start_xp) and _finite_number(end_xp):
                xp_observed += 1
                xp_deltas[str(initial.get("name") or key)] = end_xp - start_xp
            start_hp, end_hp = initial.get("hitPoints"), final.get("hitPoints")
            if _finite_number(start_hp) and _finite_number(end_hp):
                hp_observed += 1
                if end_hp != start_hp:
                    hp_deltas[key] = end_hp - start_hp
        before_creatures = selected_before.get("creatures")
        after_creatures = selected_after.get("creatures")
        if isinstance(before_creatures, list) and isinstance(after_creatures, list):
            final_hp = {str(row.get("name", "")).casefold(): row.get("currentHitPoints")
                        for row in after_creatures if isinstance(row, dict)}
            for row in before_creatures:
                if not isinstance(row, dict):
                    continue
                current = final_hp.get(str(row.get("name", "")).casefold())
                if _finite_number(row.get("currentHitPoints")) and _finite_number(current):
                    if current != row["currentHitPoints"]:
                        hp_deltas["encounter:%s" % row.get("name")] = current - row["currentHitPoints"]
        award_events = [event for event in events if event.get("observation") == "xp_award"]
        amount = award_events[0].get("amount") if len(award_events) == 1 else None
        participants = {str(name).casefold() for name in award_events[0].get("participants", [])} if len(award_events) == 1 else set()
        observed_names = {name.casefold() for name in xp_deltas}
        if not xp_deltas or hp_observed != len(initial_chars) or xp_observed != len(initial_chars):
            xp_ok: Optional[bool] = None
        elif len(award_events) == 0:
            xp_ok = all(delta == 0 for delta in xp_deltas.values()) and not hp_deltas
        elif len(award_events) != 1 or not _finite_number(amount):
            xp_ok = False
        else:
            xp_ok = (observed_names == participants and
                     all(delta == amount for delta in xp_deltas.values()) and not hp_deltas)
        record("no_duplicate_hp_or_xp_awards", "HP unchanged; XP matches zero surrender or one observed exit award",
               {"xp_deltas": xp_deltas, "hp_deltas": hp_deltas,
                "hp_observations": hp_observed, "xp_observations": xp_observed,
                "xp_award_events": award_events},
               xp_ok, "whitelisted character snapshots + observed XP event")
    elif scenario == "resume-replay":
        if profile.get("phase") == "complete":
            damage_checks = [check for check in observed_checks(
                {**profile, "scenario_id": "combat-smoke"}, before, after, artifacts, steps, events)
                if check["id"] == "deterministic_damage_exact_per_command"]
            record("completed_turn_applied_once", "completed /dmg 1 turn persisted exactly once",
                   damage_checks[0]["observed"] if damage_checks else None,
                   damage_checks[0]["status"] == "PASS" if damage_checks else None,
                   "per-step encounter snapshots")
        else:
            record("resume_link_identity", "chain and retained-state projection matched with complete phase",
                   artifacts.get("resume_chain"),
                   None if not artifacts.get("resume_chain") else artifacts["resume_chain"].get("status") == "PASS",
                   "linked complete/replay manifest and read-only state projections")
            record("replay_no_duplicate_effects", "replay mechanical state equals preserved complete-after state",
                   artifacts.get("resume_chain", {}).get("state_comparison"),
                None if not artifacts.get("resume_chain") else artifacts["resume_chain"].get("state_comparison") is True,
                "complete after-run and replay before/after snapshots")
    elif scenario in ("g5t-commander-p1", "g5t-commander-p4"):
        fixture = profile.get("fixture", {})
        fixture_steps = fixture.get("steps", []) if isinstance(fixture, dict) else []
        batch_steps = [row for row in fixture_steps if isinstance(row, dict) and
                       row.get("unit_type") == "batch"]
        trace_ref = artifacts.get("trace")
        after_ref = artifacts.get("after_snapshot")

        def refs(*values: Any) -> List[str]:
            return list(dict.fromkeys(value for value in values
                                      if isinstance(value, str) and value))

        legality_observations = []
        commander_planned_batch_count = 0
        squad_observations = []
        for batch in batch_steps:
            batch_id = batch.get("trace_batch_id")
            evidence_refs = refs(
                trace_ref,
                _g5t_batch_after_snapshot_ref(run_dir, batch, after_ref),
            )
            skipped_closing_receipts = [
                receipt for receipt in step_rows
                if batch.get("requires_combat_exit") is True
                and isinstance(receipt, dict)
                and receipt.get("script_step") == batch.get("step")
                and receipt.get("status") == "skipped"
                and receipt.get("skip_reason") == "combat_ended"
                and isinstance(receipt.get("work_unit"), dict)
                and receipt["work_unit"].get("type") == "batch"
                and receipt["work_unit"].get("id") == batch.get("unit_id")
                and receipt["work_unit"].get("round") == batch.get("round")
            ]
            if len(skipped_closing_receipts) == 1:
                commander_planned, plan_contributed = False, False
            else:
                commander_planned, plan_contributed = _g5t_commander_batch_state(
                    events, batch_id
                )
            matching = [event for event in events
                        if event.get("event_type") == "combat_observation" and
                        event.get("observation") == "applied_choice_legality" and
                        event.get("batch_id") == batch_id]
            observed = None
            if plan_contributed is False:
                status = "NOT_APPLICABLE"
                observed = {"applicability": "no_commander_plan_contribution"}
            elif plan_contributed is None:
                status = "BLOCKED"
            elif len(matching) == 1:
                applied_count = matching[0].get("applied_choice_count")
                legal_count = matching[0].get("legal_applied_choice_count")
                if (isinstance(applied_count, int) and not isinstance(applied_count, bool) and
                        applied_count > 0 and isinstance(legal_count, int) and
                        not isinstance(legal_count, bool) and
                        applied_count <= 32 and 0 <= legal_count <= applied_count):
                    observed = {"applied_choice_count": applied_count,
                                "legal_applied_choice_count": legal_count}
                    status = "PASS" if legal_count == applied_count else "FAIL"
                else:
                    status = "BLOCKED"
            else:
                status = "BLOCKED"
            legality_observations.append({
                "batch_id": batch_id, "status": status, "observed": observed,
                "evidence_refs": evidence_refs,
            })
            if commander_planned is True:
                commander_planned_batch_count += 1
                squad_matches = [event for event in events
                                 if event.get("event_type") == "combat_observation" and
                                 event.get("observation") == "commander_squad_follows_orders" and
                                 event.get("batch_id") == batch_id]
                squad_observed = None
                if len(squad_matches) == 1:
                    event = squad_matches[0]
                    followed = event.get("followed_orders")
                    if isinstance(followed, bool) and _g5t_observation_counts_valid(event):
                        if event.get("issued_choice_count") == 0:
                            if followed:
                                squad_status = "BLOCKED"
                            else:
                                squad_status = "NOT_APPLICABLE"
                                squad_observed = {
                                    "applicability": "no_commander_plan_contribution"
                                }
                        else:
                            squad_observed = {
                                "followed_orders": followed,
                                "issued_choice_count": event.get("issued_choice_count"),
                                "applied_choice_count": event.get("applied_choice_count"),
                            }
                            squad_status = "PASS" if followed else "FAIL"
                    else:
                        squad_status = "BLOCKED"
                else:
                    squad_status = "BLOCKED"
                squad_observations.append({
                    "batch_id": batch_id, "status": squad_status,
                    "observed": squad_observed, "evidence_refs": evidence_refs,
                })
            elif commander_planned is False:
                squad_observations.append({
                    "batch_id": batch_id, "status": "NOT_APPLICABLE",
                    "observed": {"applicability": "no_commander_plan"},
                    "evidence_refs": evidence_refs,
                })
            else:
                squad_observations.append({
                    "batch_id": batch_id, "status": "BLOCKED",
                    "observed": None, "evidence_refs": evidence_refs,
                })

        legality_statuses = [row["status"] for row in legality_observations]
        legality_status = (
            "FAIL" if "FAIL" in legality_statuses else
            "BLOCKED" if "BLOCKED" in legality_statuses else
            "PASS" if "PASS" in legality_statuses else "NOT_APPLICABLE"
        )
        checks.append({"id": "applied_choice_legality", "required": False,
                       "expected": "every applied commander choice was issued and Python-validated",
                       "status": legality_status,
                       "observations": legality_observations,
                       "evidence_refs": refs(trace_ref)})

        squad_statuses = [row["status"] for row in squad_observations]
        squad_status = (
            "FAIL" if "FAIL" in squad_statuses else
            "BLOCKED" if "BLOCKED" in squad_statuses or commander_planned_batch_count == 0 else
            "PASS" if "PASS" in squad_statuses else "NOT_APPLICABLE"
        )
        valid_squad_rows = [row.get("observed") for row in squad_observations
                            if row.get("status") in ("PASS", "FAIL") and
                            isinstance(row.get("observed"), dict)]
        squad_value = (True if squad_status == "PASS" else
                       False if squad_status == "FAIL" else None)
        checks.append({"id": "commander_squad_follows_orders", "required": False,
                       "expected": "applied resolver ledger follows the issued legal commander choices",
                       "observed": {"followed_orders": squad_value,
                                    "issued_choice_count": sum(row["issued_choice_count"]
                                                                for row in valid_squad_rows),
                                    "applied_choice_count": sum(row["applied_choice_count"]
                                                                 for row in valid_squad_rows),
                                    "observations": squad_observations},
                       "status": squad_status,
                       "evidence_refs": refs(trace_ref)})

        actor_names: Dict[str, str] = {}
        initial_creatures = _selected_encounter(before).get("creatures")
        try:
            from utils.combat_latency_trace import build_run_local_actor_ids

            identities = build_run_local_actor_ids(initial_creatures)
            actor_names = {actor_id: name for (kind, name), actor_id in identities.items()
                           for row in (initial_creatures or []) if isinstance(row, dict) and
                           str(row.get("type", "")).casefold() == kind and
                           " ".join(str(row.get("name", "")).split()).casefold() == name}
        except Exception:
            actor_names = {}
        after_creatures = _selected_encounter(after).get("creatures")
        self_events = [event for event in events
                       if event.get("observation") == "combat_self_preservation_outcome"]
        tracker_after = after_records.get("party_tracker.json", {})
        world_after = tracker_after.get("worldConditions")
        encounter_cleared = (
            tracker_after.get("status") == "ok" and isinstance(world_after, dict) and
            world_after.get("activeCombatEncounter") in (None, "")
        )
        auto_exit_batches = {
            event.get("batch_id") for event in events
            if event.get("observation") == "xp_award" and
            event.get("source") == "auto_exit" and isinstance(event.get("batch_id"), str)
        }
        removal_observations = []
        for event in self_events:
            actor_id, outcome = event.get("actor_id"), event.get("self_preservation_outcome")
            actor_name = actor_names.get(actor_id) if isinstance(actor_id, str) else None
            matches = [row for row in after_creatures or [] if isinstance(row, dict) and
                       isinstance(actor_name, str) and
                       " ".join(str(row.get("name", "")).split()).casefold() == actor_name.casefold()]
            persisted = matches[0] if len(matches) == 1 else {}
            defeat_reason = persisted.get("defeatReason")
            encounter_status = persisted.get("status")
            current_hp = persisted.get("currentHitPoints")
            encounter_consistent = (encounter_status == "defeated" and
                                    defeat_reason == outcome and
                                    _finite_number(current_hp) and current_hp >= 0)
            removed_actor, removed_target, satisfied_by_exit = (
                _g5t_self_preservation_menu_removal(
                    events, actor_id, event.get("batch_id"),
                    actor_name=actor_name,
                    encounter_cleared=encounter_cleared,
                    auto_exit_batches=auto_exit_batches,
                )
            )
            if outcome not in ("fled", "surrendered"):
                row_status = "BLOCKED"
            elif not isinstance(after_creatures, list) or len(matches) > 1:
                row_status = "BLOCKED"
            elif len(matches) != 1:
                row_status = "FAIL"
            elif removed_actor is False or removed_target is False:
                row_status = "FAIL"
            elif not satisfied_by_exit and (
                    not isinstance(removed_actor, bool) or not isinstance(removed_target, bool)):
                row_status = "BLOCKED"
            elif encounter_consistent and (
                    (removed_actor is True and removed_target is True) or satisfied_by_exit):
                row_status = "PASS"
            else:
                row_status = "FAIL"
            removal_observations.append({
                "actor_id": actor_id, "outcome": outcome, "batch_id": event.get("batch_id"),
                "defeat_reason": defeat_reason, "encounter_status": encounter_status,
                "current_hit_points": current_hp,
                "actor_removed_from_later_actor_menus": removed_actor,
                "actor_removed_from_later_target_menus": removed_target,
                "satisfied_by_exit": satisfied_by_exit,
                "encounter_state_consistent": encounter_consistent,
                "status": row_status, "evidence_refs": refs(trace_ref, after_ref),
            })
        traced_actor_outcomes = {
            (row.get("actor_id"), row.get("outcome")) for row in removal_observations
            if isinstance(row.get("actor_id"), str)
        }
        persisted_outcomes = []
        for creature in after_creatures or []:
            if (not isinstance(creature, dict) or
                    creature.get("defeatReason") not in ("fled", "surrendered")):
                continue
            actor_name = " ".join(str(creature.get("name", "")).split()).casefold()
            actor_id = next((identity for identity, name in actor_names.items()
                             if name.casefold() == actor_name), None)
            if (actor_id, creature.get("defeatReason")) not in traced_actor_outcomes:
                persisted_outcomes.append((actor_id, creature.get("defeatReason")))
        for untraced_actor_id, untraced_outcome in sorted(
                persisted_outcomes, key=lambda item: (item[1], item[0] or "")):
            removal_observations.append({
                "actor_id": untraced_actor_id, "outcome": untraced_outcome,
                "status": "BLOCKED",
                "evidence_refs": refs(after_ref),
                "reason": "persisted_outcome_missing_trace",
            })
        removal_status = (
            "NOT_OBSERVED" if not removal_observations else
            "FAIL" if any(row.get("status") == "FAIL" for row in removal_observations) else
            "BLOCKED" if any(row.get("status") == "BLOCKED" for row in removal_observations) else
            "PASS"
        )
        checks.append({"id": "self_preservation_removal", "required": False,
                       "expected": "every observed flee or surrender persists and leaves later menus, or its batch exits combat",
                       "observed": {"observations": removal_observations},
                       "status": removal_status,
                       "evidence_refs": refs(trace_ref, after_ref)})

        cover_events = [event for event in events
                        if event.get("observation") == "combat_cover_outcome"]
        covered_attack_steps = []
        attack_pattern = re.compile(r"^/att\s+Goblin Squad B\s+(\d+)\b", re.IGNORECASE)
        if __package__:
            from scripts.combat_latency_fixtures import build_g5t_script_steps
        else:
            from combat_latency_fixtures import build_g5t_script_steps
        scripted_attacks = [row for row in build_g5t_script_steps(party_size)
                            if attack_pattern.match(row.get("input", ""))]
        expected_attack = next(
            (row for row in scripted_attacks
             if "covered-target attack" in row.get("label", "")),
            None,
        )
        for pair in step_rows:
            before_snapshot = pair.get("before")
            after_snapshot = pair.get("after")
            before_observation = (before_snapshot.get("observation", {})
                                  if isinstance(before_snapshot, dict) else {})
            after_observation = (after_snapshot.get("observation", {})
                                  if isinstance(after_snapshot, dict) else {})
            label = before_observation.get("label")
            scripted_input = expected_attack.get("input") if expected_attack else None
            scripted_match = (attack_pattern.match(scripted_input)
                              if isinstance(scripted_input, str) else None)
            step_number = expected_attack.get("step") if expected_attack else None
            if (expected_attack is not None and label == expected_attack.get("label") and
                    isinstance(step_number, int) and not isinstance(step_number, bool) and
                    scripted_match is not None):
                covered_attack_steps.append((step_number, int(scripted_match.group(1)), pair,
                                             after_observation, scripted_input,
                                             before_observation.get("input")))

        target_actor_ids = [actor_id for actor_id, name in actor_names.items()
                            if name.casefold() == "goblin squad b"]
        matching_attack = (covered_attack_steps[0]
                           if len(covered_attack_steps) == 1 else None)
        base_ac = cover_bonus = effective = attack_effective = None
        cover_status = "NOT_OBSERVED"
        cover_evidence_refs = refs(trace_ref, after_ref)
        cover_applied = [event for event in cover_events
                         if event.get("cover_state") == "applied"]
        if matching_attack is not None:
            (step_number, scripted_roll, pair, after_observation,
             scripted_input, observed_command) = matching_attack
            before_creatures = _selected_encounter(pair.get("before")).get("creatures")
            target_rows = [row for row in before_creatures or [] if isinstance(row, dict) and
                           str(row.get("name", "")).casefold() == "goblin squad b"]
            target_row = target_rows[0] if len(target_rows) == 1 else {}
            base_ac = target_row.get("armorClass")
            cover_type = target_row.get("coverType")
            cover_feature_id = target_row.get("coverFeatureId")
            cover_bonus = {"half": 2, "three_quarters": 5}.get(cover_type)
            effective = (base_ac + cover_bonus
                         if _finite_number(base_ac) and cover_bonus is not None else None)
            output_rows = after_observation.get("actual_backend_outputs")
            output_text = "\n".join(
                str(row.get("content", "")) for row in output_rows
                if isinstance(row, dict) and isinstance(row.get("content"), str)
            ) if isinstance(output_rows, list) else ""
            attack_match = re.search(r"Rolled\s+(\d+)\s+vs AC\s+(\d+)", output_text,
                                     re.IGNORECASE)
            observed_command_match = (
                attack_pattern.match(observed_command)
                if isinstance(observed_command, str) else None
            )
            attack_effective = int(attack_match.group(2)) if attack_match else None
            attack_is_miss = bool(re.search(r"\bMiss(?:ed)?\b|\bMISSED\b", output_text,
                                            re.IGNORECASE))
            attack_is_hit = bool(re.search(r"\bHit(?:s)?\b", output_text,
                                           re.IGNORECASE))
            attack_result_matches_ac = _finite_number(effective) and (
                (attack_is_miss and not attack_is_hit and scripted_roll < effective)
                or (attack_is_hit and not attack_is_miss and scripted_roll >= effective)
            )
            target_applied = [event for event in cover_applied
                              if len(target_actor_ids) == 1 and
                              event.get("actor_id") == target_actor_ids[0]]
            if len(target_rows) != 1:
                cover_status = "BLOCKED"
            elif bool(target_row.get("coverFeatureId")) != bool(target_row.get("coverType")):
                cover_status = "FAIL"
            elif target_row.get("coverFeatureId") and target_row.get("coverType"):
                cover_evidence_refs = refs(
                    trace_ref, "snapshots/step-%03d-before.json" % step_number,
                    "snapshots/step-%03d-after.json" % step_number, after_ref,
                )
                if (len(target_rows) != 1 or not _finite_number(base_ac) or
                        cover_bonus is None or not isinstance(cover_feature_id, str)):
                    cover_status = "FAIL"
                elif len(target_applied) != 1:
                    cover_status = "BLOCKED"
                elif (target_applied[0].get("feature_id") != cover_feature_id or
                      target_applied[0].get("cover_type") != cover_type):
                    cover_status = "FAIL"
                elif attack_match is None:
                    cover_status = "BLOCKED"
                elif (scripted_input != expected_attack.get("input") or
                      observed_command_match is None or
                      int(observed_command_match.group(1)) != scripted_roll or
                      int(attack_match.group(1)) != scripted_roll or
                      attack_effective != effective or not attack_result_matches_ac):
                    cover_status = "FAIL"
                else:
                    cover_status = "PASS"
            elif (attack_match is not None and _finite_number(base_ac) and
                  (int(attack_match.group(1)) != scripted_roll or
                   attack_effective != base_ac)):
                # The observed attack disagrees with its scripted roll or with
                # the authoritative base AC, so the no-cover branch is invalid.
                cover_status = "FAIL"
                cover_evidence_refs = refs(
                    trace_ref, "snapshots/step-%03d-before.json" % step_number,
                    "snapshots/step-%03d-after.json" % step_number,
                )
            elif attack_match is None:
                # The scripted attack was sent, so missing authoritative output
                # is an evidence gap, not an unobserved model choice.
                cover_status = "BLOCKED"
            elif target_applied:
                # A trace says cover was applied to this target, but the attack
                # snapshot did not retain it as an authoritative state.
                cover_status = "FAIL"
            else:
                # The attack was observed at the target's base AC, but the
                # commander did not apply cover in this run.
                cover_status = "NOT_OBSERVED"
        elif len(covered_attack_steps) > 1 or expected_attack is None:
            cover_status = "BLOCKED"
        else:
            final_tracker = after_records.get("party_tracker.json", {})
            final_world = (final_tracker.get("worldConditions")
                           if isinstance(final_tracker, dict) else None)
            combat_exited = (isinstance(final_world, dict) and
                             final_world.get("activeCombatEncounter") in (None, ""))
            cover_status = "NOT_OBSERVED" if combat_exited else "BLOCKED"

        checks.append({"id": "cover_changes_effective_ac", "required": False,
                       "expected": "an observed covered-target attack uses base AC plus authored cover",
                       "observed": {"base_ac": base_ac, "cover_bonus": cover_bonus,
                                    "effective_ac": effective, "attack_effective_ac": attack_effective},
                       "status": cover_status,
                       "evidence_refs": cover_evidence_refs})

        after_rows = _selected_encounter(after).get("creatures")
        goblin_rows = [row for row in after_rows or [] if isinstance(row, dict) and
                       str(row.get("name", "")).casefold() == "goblin squad b"]
        tracker = after_records.get("party_tracker.json", {})
        world = tracker.get("worldConditions") if isinstance(tracker, dict) else None
        active_encounter = world.get("activeCombatEncounter") if isinstance(world, dict) else None
        final_goblin = goblin_rows[0] if len(goblin_rows) == 1 else {}
        final_base_ac = final_goblin.get("armorClass")
        target_cover_events = [event for event in cover_events
                               if len(target_actor_ids) == 1 and
                               event.get("actor_id") == target_actor_ids[0]]
        expired_trace = any(event.get("cover_state") == "expired"
                            for event in target_cover_events)
        cover_seen = bool(target_cover_events)
        relevant_snapshots = [before, after]
        relevant_snapshots.extend(
            edge for pair in step_rows for edge in (pair.get("before"), pair.get("after"))
        )
        for snapshot in relevant_snapshots:
            rows = _selected_encounter(snapshot).get("creatures")
            if isinstance(rows, list) and any(
                    isinstance(row, dict) and
                    str(row.get("name", "")).casefold() == "goblin squad b" and
                    (row.get("coverFeatureId") or row.get("coverType"))
                    for row in rows):
                cover_seen = True
                break
        inert_after_exit = active_encounter in (None, "")
        expiration_valid = (_finite_number(final_base_ac) and inert_after_exit and
                            expired_trace)
        expiration_status = (
            "NOT_OBSERVED" if not cover_seen else
            "BLOCKED" if not expired_trace or len(goblin_rows) != 1 or
            not _finite_number(final_base_ac) else
            "PASS" if expiration_valid else "FAIL"
        )
        checks.append({"id": "cover_expiration", "required": False,
                       "expected": "an observed cover expiration leaves no active cover after exit",
                       "observed": {"base_ac": final_base_ac,
                                       "effective_ac_after_exit": final_base_ac if inert_after_exit else None,
                                      "cover_inert_after_exit": inert_after_exit},
                       "status": expiration_status,
                       "evidence_refs": refs(trace_ref, after_ref)})
    elif scenario in ("g5a-ally-p1", "g5a-ally-p4"):
        if __package__:
            from scripts.combat_latency_fixtures import (
                G5A_COVER_FEATURE_ID,
                G5A_DIRECTIVE_TEXT,
                G5A_ALLY_NAME,
                build_g5a_fixture_metadata,
                validate_g5a_scripted_damage,
            )
        else:
            from combat_latency_fixtures import (
                G5A_COVER_FEATURE_ID,
                G5A_DIRECTIVE_TEXT,
                G5A_ALLY_NAME,
                build_g5a_fixture_metadata,
                validate_g5a_scripted_damage,
            )

        expected_fixture = build_g5a_fixture_metadata(party_size)
        captured_fixture = (g5a_metadata.get("fixture")
                            if isinstance(g5a_metadata, dict) else None)
        damage_contract = validate_g5a_scripted_damage(party_size)
        fixture_matches = captured_fixture == expected_fixture
        before_creatures = selected_before.get("creatures")
        expected_pc_names = ["Acheron"] if party_size == 1 else [
            "Acheron", "Merisiel", "Kira", "Vitreol"
        ]
        roster_valid: Optional[bool] = None
        active_ally_names: List[str] = []
        if isinstance(before_creatures, list):
            pc_names = [
                " ".join(row.get("name", "").split()).casefold()
                for row in before_creatures
                if isinstance(row, dict) and
                str(row.get("type", "")).strip().casefold() in {"player", "pc"} and
                isinstance(row.get("name"), str)
            ]
            expected_pc_keys = [name.casefold() for name in expected_pc_names]
            try:
                from core.combat.ally_controller import select_active_allies

                active_allies = select_active_allies({"creatures": before_creatures})
                active_ally_names = [identity.name for identity in active_allies]
            except Exception:
                active_ally_names = []
            active_ally_keys = [" ".join(name.split()).casefold()
                                for name in active_ally_names]
            roster_valid = (
                len(pc_names) == len(expected_pc_keys) and
                sorted(pc_names) == sorted(expected_pc_keys) and
                len(set(pc_names)) == len(pc_names) and
                G5A_ALLY_NAME.casefold() in active_ally_keys
            )
        record(
            "g5a_party_and_active_ally",
            {"player_characters": expected_pc_names,
             "active_allied_npc": G5A_ALLY_NAME},
            {"player_characters": expected_pc_names if not isinstance(before_creatures, list) else pc_names,
             "active_allied_npcs": active_ally_names},
            roster_valid,
            "before-run selected encounter snapshot",
        )
        record(
            "g5a_scripted_damage_legal",
            "every scripted non-critical /dmg value is within its actor's declared weapon range",
            {"fixture_matches_canonical": fixture_matches,
             "damage_contract": damage_contract},
            None if captured_fixture is None else
            fixture_matches and damage_contract.get("status") == "PASS",
            "canonical G5A script and authored character weapon data",
        )

        trace_ref = artifacts.get("trace")
        batch_step = expected_fixture["ally_batch_step"]
        directive_step = expected_fixture["directive_step"]
        batch_rows = [row for row in expected_fixture["steps"]
                      if row.get("step") == batch_step and row.get("unit_type") == "batch"]
        directive_rows = [row for row in expected_fixture["steps"]
                          if row.get("step") == directive_step and
                          isinstance(row.get("input"), str) and
                          row["input"].startswith("/cmd ")]
        expected_batch_id = batch_rows[0].get("trace_batch_id") if len(batch_rows) == 1 else None
        directive_sha256 = expected_fixture["directive_sha256"]
        directive_hash_from_text = hashlib.sha256(
            G5A_DIRECTIVE_TEXT.encode("ascii")
        ).hexdigest()
        try:
            from utils.combat_latency_trace import build_run_local_actor_ids

            actor_id_map = build_run_local_actor_ids(before_creatures)
        except Exception:
            actor_id_map = {}
        ally_actor_id = actor_id_map.get(("npc", " ".join(G5A_ALLY_NAME.split()).casefold()))
        after_creatures = selected_after.get("creatures")

        def ally_cover_rows(creatures: Any) -> List[Dict[str, Any]]:
            if not isinstance(creatures, list):
                return []
            return [
                row for row in creatures
                if isinstance(row, dict)
                and str(row.get("type", "")).strip().casefold() == "npc"
                and isinstance(row.get("name"), str)
                and " ".join(row["name"].split()).casefold()
                == " ".join(G5A_ALLY_NAME.split()).casefold()
            ]

        before_ally_cover_rows = ally_cover_rows(before_creatures)
        after_ally_cover_rows = ally_cover_rows(after_creatures)
        before_ally_cover = (
            before_ally_cover_rows[0] if len(before_ally_cover_rows) == 1 else {}
        )
        after_ally_cover = (
            after_ally_cover_rows[0] if len(after_ally_cover_rows) == 1 else {}
        )
        persisted_cover_valid = (
            None
            if len(before_ally_cover_rows) != 1 or len(after_ally_cover_rows) != 1
            else (
                before_ally_cover.get("coverFeatureId") in (None, "")
                and before_ally_cover.get("coverType") in (None, "")
                and after_ally_cover.get("coverFeatureId") == G5A_COVER_FEATURE_ID
                and after_ally_cover.get("coverType") in ("half", "three_quarters")
            )
        )
        persisted_cover_absent = (
            len(before_ally_cover_rows) == 1 and len(after_ally_cover_rows) == 1 and
            before_ally_cover.get("coverFeatureId") in (None, "") and
            before_ally_cover.get("coverType") in (None, "") and
            after_ally_cover.get("coverFeatureId") in (None, "") and
            after_ally_cover.get("coverType") in (None, "")
        )
        persisted_cover = {
            "before": {
                "feature_id": before_ally_cover.get("coverFeatureId"),
                "cover_type": before_ally_cover.get("coverType"),
            } if before_ally_cover else None,
            "after": {
                "feature_id": after_ally_cover.get("coverFeatureId"),
                "cover_type": after_ally_cover.get("coverType"),
            } if after_ally_cover else None,
            "status": ("ok" if persisted_cover_valid is True else
                       "absent" if persisted_cover_absent else
                       "invalid" if persisted_cover_valid is False else
                       "missing_or_ambiguous"),
        }

        trace_windows = (g5a_metadata.get("trace_windows", {})
                         if isinstance(g5a_metadata, dict) else {})
        window_rows = (trace_windows.get("steps", [])
                       if isinstance(trace_windows, dict) else [])

        def step_window(step_number: int, expected_step: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            matches = [row for row in window_rows if isinstance(row, dict) and
                       row.get("step") == step_number]
            if len(matches) != 1:
                return None
            row = matches[0]
            start, end = row.get("start_epoch_ms"), row.get("end_epoch_ms")
            if (row.get("status") == "skipped" or not _finite_number(start) or
                    not _finite_number(end) or start < 0 or end < start or
                    row.get("unit_type") != expected_step.get("unit_type") or
                    row.get("unit_id") != expected_step.get("unit_id") or
                    row.get("round") != expected_step.get("round")):
                return None
            return row

        def in_step_window(event: Dict[str, Any], window: Optional[Dict[str, Any]]) -> Optional[bool]:
            if window is None:
                return None
            timestamp = event.get("recorded_at_ms")
            if not _finite_number(timestamp):
                return None
            return window["start_epoch_ms"] <= timestamp <= window["end_epoch_ms"]

        expected_run_id = ((g5a_metadata.get("identity") or {}).get("run_id")
                           if isinstance(g5a_metadata, dict) else None)
        receipts = (g5a_metadata.get("receipts", [])
                    if isinstance(g5a_metadata, dict) else [])
        directive_receipts = [row for row in receipts if isinstance(row, dict) and
                              row.get("script_step", row.get("step")) == directive_step and
                              row.get("label") == (directive_rows[0].get("label")
                                                    if len(directive_rows) == 1 else None)]
        directive_receipt_valid = False
        if len(directive_receipts) == 1 and len(directive_rows) == 1:
            receipt_work_unit = directive_receipts[0].get("work_unit")
            directive_receipt_valid = (
                directive_receipts[0].get("status") == "sent" and
                isinstance(receipt_work_unit, dict) and
                receipt_work_unit.get("type") == directive_rows[0].get("unit_type") and
                receipt_work_unit.get("id") == directive_rows[0].get("unit_id") and
                receipt_work_unit.get("round") == directive_rows[0].get("round")
            )
        directive_window = step_window(
            directive_step, directive_rows[0] if len(directive_rows) == 1 else {}
        )
        accepted_directives = [event for event in events
                               if event.get("observation") == "ally_directive_accepted" and
                               event.get("batch_id") == expected_batch_id]
        accepted_valid = (
            len(accepted_directives) == 1 and
            accepted_directives[0].get("actor_id") == ally_actor_id and
            accepted_directives[0].get("directive_sha256") == directive_sha256 ==
            directive_hash_from_text and
            accepted_directives[0].get("run_id") == expected_run_id and
            directive_receipt_valid and
            directive_window is not None and
            in_step_window(accepted_directives[0], directive_window) is True
        )
        accepted_status = (
            "BLOCKED" if not accepted_directives or not directive_receipts or
            directive_window is None or
            (len(accepted_directives) == 1 and
             in_step_window(accepted_directives[0], directive_window) is None) else
            "PASS" if accepted_valid else
            "BLOCKED" if len(accepted_directives) != 1 or len(directive_receipts) != 1 else "FAIL"
        )
        checks.append({"id": "g5a_accepted_directive", "required": True,
                       "expected": "the scripted /cmd was accepted for Blairen in its driver step",
                       "observed": {"batch_id": expected_batch_id,
                                    "actor_id": ally_actor_id,
                                    "directive_sha256": directive_sha256,
                                    "accepted_events": len(accepted_directives),
                                    "driver_receipt_valid": directive_receipt_valid},
                       "status": accepted_status,
                       "evidence_refs": [trace_ref] if trace_ref else []})

        batch_window = step_window(batch_step, batch_rows[0] if len(batch_rows) == 1 else {})
        commit_events = [event for event in events
                         if event.get("observation") == "ally_choice_commit_result" and
                         event.get("batch_id") == expected_batch_id]
        actor_commits = [event for event in commit_events
                         if event.get("actor_id") == ally_actor_id]
        linked_commits = [event for event in actor_commits
                          if event.get("directive_sha256") == directive_sha256]
        applied_cover_events = [event for event in events
                                if event.get("observation") == "combat_cover_outcome" and
                                event.get("batch_id") == expected_batch_id and
                                event.get("actor_id") == ally_actor_id and
                                event.get("cover_state") == "applied"]
        selected_cover_events = [event for event in events
                                 if event.get("observation") == "combat_cover_outcome" and
                                 event.get("batch_id") == expected_batch_id and
                                 event.get("actor_id") == ally_actor_id and
                                 event.get("cover_state") == "selected"]
        commit = linked_commits[0] if len(linked_commits) == 1 else {}
        applied_cover = applied_cover_events[0] if len(applied_cover_events) == 1 else {}
        commit_time_valid = (in_step_window(commit, batch_window)
                             if commit else None)
        cover_time_valid = (in_step_window(applied_cover, batch_window)
                            if applied_cover else None)
        cover_valid = (
            accepted_valid and len(linked_commits) == 1 and
            commit.get("choice_kind") == "take_cover" and
            commit.get("choice_legal") is True and commit.get("choice_applied") is True and
            commit.get("choice_defaulted") is False and
            commit.get("cover_feature_id") == G5A_COVER_FEATURE_ID and
            commit.get("directive_request_kind") == "replan" and
            commit.get("run_id") == expected_run_id and commit_time_valid is True and
            persisted_cover_valid is True and
            len(applied_cover_events) == 1 and
            applied_cover.get("feature_id") == G5A_COVER_FEATURE_ID and
            applied_cover.get("cover_type") in ("half", "three_quarters") and
            applied_cover.get("run_id") == expected_run_id and cover_time_valid is True
        )
        legal_noncover_observed = (
            accepted_valid and len(actor_commits) == 1 and len(linked_commits) == 1 and
            commit.get("choice_kind") in {"attack", "hold"} and
            commit.get("choice_legal") is True and
            commit.get("choice_applied") is True and
            commit.get("choice_defaulted") is False and
            commit.get("directive_request_kind") in {"initial", "replan", "synchronous"} and
            commit.get("run_id") == expected_run_id and commit_time_valid is True and
            persisted_cover_absent and not applied_cover_events and not selected_cover_events
        )
        cover_status = (
            "NOT_OBSERVED" if legal_noncover_observed else
            "BLOCKED" if not accepted_valid or not actor_commits or
            batch_window is None or
            (len(linked_commits) == 1 and commit_time_valid is None) or
            (len(applied_cover_events) == 1 and cover_time_valid is None) else
            "PASS" if cover_valid else
            "FAIL" if (len(actor_commits) == 1 or linked_commits or
                       applied_cover_events or selected_cover_events) else "BLOCKED"
        )
        checks.append({"id": "g5a_directive_take_cover", "required": True,
                        "expected": "the accepted directive is linked to a legal applied authored take_cover choice",
                        "observed": {"accepted_directive": accepted_directives,
                                      "committed_choice": commit,
                                      "legal_noncover_observed": legal_noncover_observed,
                                      "applied_cover": applied_cover,
                                     "persisted_cover": persisted_cover,
                                     "selected_cover_events": len(selected_cover_events)},
                       "status": cover_status,
                       "evidence_refs": [trace_ref] if trace_ref else []})

        forbidden_choices = {"flee", "surrender", "move_to_cover",
                             "interpose_for_ally", "guard_ally"}
        allowed_choices = {"attack", "take_cover", "hold"}
        choice_kinds = [event.get("choice_kind") for event in commit_events]
        if not commit_events or any(not isinstance(kind, str) for kind in choice_kinds):
            forbidden_status = "BLOCKED"
        elif any(kind in forbidden_choices or kind not in allowed_choices
                 for kind in choice_kinds):
            forbidden_status = "FAIL"
        else:
            forbidden_status = "PASS"
        checks.append({"id": "g5a_no_forbidden_ally_choice", "required": True,
                       "expected": "no applied ally choice is flee, surrender, or a future spatial placeholder",
                       "observed": {"choice_kinds": choice_kinds,
                                    "forbidden_choices": sorted(forbidden_choices)},
                       "status": forbidden_status,
                       "evidence_refs": [trace_ref] if trace_ref else []})

        malformed_choice_events = [
            event for event in commit_events
            if not isinstance(event.get("choice_applied"), bool) or
            not isinstance(event.get("choice_legal"), bool) or
            not isinstance(event.get("actor_id"), str)
        ]
        illegal_applied_choices = [
            event for event in commit_events
            if event.get("choice_applied") is True and event.get("choice_legal") is not True
        ]
        applied_legality_status = (
            "BLOCKED" if not commit_events or malformed_choice_events else
            "FAIL" if illegal_applied_choices else "PASS"
        )
        checks.append({"id": "g5a_applied_choice_legality", "required": True,
                       "expected": "every committed applied ally choice was issued by the current Python menu and marked legal",
                       "observed": {"commit_event_count": len(commit_events),
                                    "malformed_events": len(malformed_choice_events),
                                    "illegal_applied_choices": illegal_applied_choices},
                       "status": applied_legality_status,
                       "evidence_refs": [trace_ref] if trace_ref else []})

        provider_events = artifacts.get("trace_provider_events")
        if not isinstance(provider_events, list):
            provider_events = []
        sync_purposes = {"combat_ally_batch_plan", "combat_ally_batch_narration"}
        sync_events = [event for event in provider_events
                       if isinstance(event, dict) and event.get("batch_id") == expected_batch_id and
                       event.get("purpose") in sync_purposes and
                       event.get("request_site") != "combat_tactical_prefetch"]
        sync_counts = {purpose: 0 for purpose in sync_purposes}
        sync_call_ids: set[str] = set()
        duplicate_sync_call_ids: set[str] = set()
        missing_sync_ids = []
        for event in sync_events:
            purpose = event.get("purpose")
            sync_counts[purpose] += 1
            call_id = event.get("call_id")
            if isinstance(call_id, str) and call_id:
                if call_id in sync_call_ids:
                    duplicate_sync_call_ids.add(call_id)
                sync_call_ids.add(call_id)
            else:
                missing_sync_ids.append(purpose)
        prefetch_submissions = [event for event in events
                                if event.get("observation") == "ally_prefetch_submission" and
                                event.get("batch_id") == expected_batch_id]
        submission_rows = sorted(
            prefetch_submissions,
            key=lambda event: event.get("recorded_at_ms")
            if _finite_number(event.get("recorded_at_ms")) else float("inf"),
        )
        submission_kinds = [event.get("request_kind") for event in submission_rows]
        submission_ids = [event.get("request_id") for event in submission_rows]
        trace_event_positions = {
            id(event): index for index, event in enumerate(events)
            if isinstance(event, dict)
        }
        directive_event = accepted_directives[0] if len(accepted_directives) == 1 else None
        replan_event = submission_rows[1] if len(submission_rows) == 2 else None
        directive_position = (
            trace_event_positions.get(id(directive_event))
            if directive_event is not None else None
        )
        replan_position = (
            trace_event_positions.get(id(replan_event))
            if replan_event is not None else None
        )
        replan_after_directive = (
            len(accepted_directives) == 1 and len(submission_rows) == 2 and
            submission_rows[1].get("request_kind") == "replan" and
            _finite_number(accepted_directives[0].get("recorded_at_ms")) and
            _finite_number(submission_rows[1].get("recorded_at_ms")) and
            submission_rows[1]["recorded_at_ms"] >= accepted_directives[0]["recorded_at_ms"] and
            isinstance(directive_position, int) and
            isinstance(replan_position, int) and replan_position > directive_position
        )
        submission_contract = (
            len(submission_rows) == 2 and submission_kinds == ["initial", "replan"] and
            all(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,79}", value)
                for value in submission_ids) and len(set(submission_ids)) == 2 and
            replan_after_directive
        )
        request_kind = commit.get("directive_request_kind") if commit else None
        request_kind_valid = request_kind in {"initial", "replan", "synchronous"}
        expected_plan_calls = 1 if request_kind == "synchronous" else 0
        plan_call_count = sync_counts["combat_ally_batch_plan"]
        narration_call_count = sync_counts["combat_ally_batch_narration"]
        synchronous_count = plan_call_count + narration_call_count
        attribution = (g5a_metadata.get("trace_attribution", {})
                       if isinstance(g5a_metadata, dict) else {})
        calls_valid = (
            attribution.get("status") == "PASS" and
            submission_contract and request_kind_valid and
            not missing_sync_ids and not duplicate_sync_call_ids and
            plan_call_count == expected_plan_calls and
            narration_call_count == 1 and synchronous_count <= 2
        )
        calls_status = (
            "FAIL" if synchronous_count > 2 or len(submission_rows) > 2 else
            "PASS" if calls_valid else
            "BLOCKED" if (attribution.get("status") != "PASS" or
                          not submission_rows or missing_sync_ids or duplicate_sync_call_ids or
                          narration_call_count == 0 or request_kind is None) else "FAIL"
        )
        checks.append({"id": "g5a_ally_call_bounds", "required": True,
                       "expected": "ordered initial and directive re-plan submissions, at most two background requests, and at most two synchronous ally calls per batch",
                       "observed": {"batch_id": expected_batch_id,
                                      "background_submission_count": len(submission_rows),
                                      "background_request_kinds": submission_kinds,
                                      "background_request_ids": submission_ids,
                                      "selected_request_kind": request_kind,
                                      "synchronous_provider_event_count": len(sync_events),
                                      "duplicate_synchronous_call_ids": sorted(duplicate_sync_call_ids),
                                      "synchronous_plan_calls": plan_call_count,
                                    "synchronous_narration_calls": narration_call_count,
                                    "synchronous_calls": synchronous_count,
                                    "trace_attribution_status": attribution.get("status")},
                       "status": calls_status,
                       "evidence_refs": [trace_ref] if trace_ref else []})

        expected_flags = {
            "DETERMINISTIC_ENEMY_RESOLUTION_ENABLED": True,
            "COMBAT_ALLY_CONTROLLER_ENABLED": True,
            "COMBAT_ALLY_PREFETCH_ENABLED": True,
        }
        sandbox_flags_valid = (
            isinstance(g5a_sandbox_identity, dict) and
            g5a_sandbox_identity.get("status") == "ok" and
            g5a_sandbox_identity.get("flags") == expected_flags and
            g5a_sandbox_identity.get("expected") == expected_flags
        )
        record("g5a_sandbox_flags", expected_flags,
               g5a_sandbox_identity,
               None if g5a_sandbox_identity is None else sandbox_flags_valid,
               "sandbox model_config.py AST literals")
    trace_applicability = artifacts.get("trace_applicability", {})
    non_applicable_trace = trace_applicability.get("status") == "non_applicable"
    checks.append({"id": "required_trace", "required": True,
                   "expected": "valid non-degraded trace or explicitly non-applicable empty replay span",
                   "observed": {"status": artifacts.get("required_evidence_status"),
                               "trace_applicability": trace_applicability},
                   "status": "PASS" if artifacts.get("required_evidence_status") == "ok" or non_applicable_trace else "BLOCKED",
                   "evidence": artifacts.get("trace") or "missing"})
    return checks


def _g4_check_applicability(checks: List[Dict[str, Any]], scenario: str,
                            manifest: Dict[str, Any], steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Mark checks outside a G4 scenario's domain N/A and append scoped observations."""
    if scenario == "narrator-dialogue-travel":
        combat_only = {"mechanical_apply_outcomes", "hp_delta_snapshot_reconciliation",
                       "selected_encounter_available", "final_response_validation_truth",
                       "accepted_logical_batch_once", "complete_unique_pc_roster",
                       "living_non_pc_roster", "active_pc_identity_per_step",
                       "phase_round_progression_observed", "deterministic_damage_exact_per_command",
                       "causal_trace_linkage", "ally_and_inactive_actual_batch_filter"}
        for row in checks:
            if row.get("id") in combat_only:
                row.update(required=False, status="N/A",
                           observed={"applicability": "not a combat scenario"})
        present = {row.get("id") for row in checks}
        for check_id in sorted(combat_only - present):
            checks.append({"id": check_id, "required": False, "expected": "combat-only check",
                           "observed": {"applicability": "not a combat scenario"},
                           "status": "N/A", "evidence": "scenario applicability"})
        profile = manifest.get("scenario", {}).get("profile_contract", {})
        turns = profile.get("turns", [])
        projections = manifest.get("g4_step_projections", [])
        checks.extend([
            {"id": "g4_narrator_route_and_actor_observations", "required": True,
             "expected": "five persisted source-profile locations and active actors",
             "observed": [{"room": ((row.get("projection") or {}).get("observed") or {}).get("currentLocationId"),
                           "actor": ((row.get("projection") or {}).get("observed") or {}).get("active_character")}
                          for row in projections],
             "status": "PASS" if len(projections) == 5 and all(
                 row.get("projection", {}).get("status") == "PASS" and
                 isinstance((row.get("projection", {}).get("observed") or {}).get("currentLocationId"), str) and
                 isinstance((row.get("projection", {}).get("observed") or {}).get("active_character"), str)
                 for row in projections) else "BLOCKED",
             "evidence": "retained step snapshots and manifest projection"},
            {"id": "g4_narrator_mira_backend_response", "required": True,
             "expected": "actual non-echo Mira dialogue output",
             "observed": [row.get("actual_backend_outputs", []) for row in projections
                          if row.get("kind") == "mira_dialogue"],
             "status": "PASS" if any(row.get("kind") == "mira_dialogue" and row.get("actual_backend_outputs")
                                       for row in projections) else "BLOCKED",
             "evidence": "retained backend output observations"},
        ])
    return checks


def _transcript_has_user_input(transcript: str, author: str, content: str) -> bool:
    """Match a real socket user-input record, allowing its author metadata only."""
    prefix = re.compile(r"^\[[^\]\r\n]+\] \[game_output\] type=user-input author=([^\s]+) content=(.*)$")
    for line in transcript.splitlines():
        match = prefix.fullmatch(line)
        if match and match.group(1) == author and match.group(2) == content:
            return True
    return False


def _required_check_ids(profile: Dict[str, Any]) -> set[str]:
    scenario = profile["scenario_id"]
    ids = {"party_roster_identity", "selected_encounter_available", "required_trace",
           "mechanical_apply_outcomes", "hp_delta_snapshot_reconciliation"}
    if scenario in ("combat-smoke", "combat-smoke-allied-inactive"):
        ids.update(("complete_unique_pc_roster", "living_non_pc_roster",
                    "active_pc_identity_per_step", "phase_round_progression_observed",
                    "deterministic_damage_exact_per_command", "causal_trace_linkage",
                    "final_response_validation_truth", "accepted_logical_batch_once"))
        if scenario == "combat-smoke-allied-inactive":
            ids.add("ally_and_inactive_actual_batch_filter")
    elif scenario in ("initiative-pc", "initiative-dm-tie"):
        ids.update(("invalid_initiative_holds_pending_gate", "initiative_expected_winner"))
        if scenario == "initiative-dm-tie":
            ids.update(("final_response_validation_truth", "accepted_logical_batch_once"))
        ids.add("pc_win_without_opening_batch" if scenario == "initiative-pc" else
                "dm_tie_eligible_batch_once_and_marker_cleared")
        if scenario == "initiative-dm-tie":
            ids.add("dm_tie_returns_to_pc_phase")
    elif scenario == "death-save":
        ids.update(("pending_pc_death_state_seeded", "invalid_death_roll_no_state_change",
                    "legal_roll_updates_only_pending_pc_once"))
        if profile["party_size"] == 4:
            ids.add("wrong_actor_rejected_without_state_change")
    elif scenario == "surrender-exit":
        ids.update(("encounter_cleared", "server_alive_readonly_probe", "no_duplicate_hp_or_xp_awards",
                    "requested_exit_branch_observed", "narration_handoff_observed"))
        if profile.get("branch") == "surrender":
            ids.update(("final_response_validation_truth", "accepted_logical_batch_once"))
    elif scenario == "resume-replay":
        ids.update(("completed_turn_applied_once",) if profile.get("phase") == "complete" else
                   ("resume_link_identity", "replay_no_duplicate_effects"))
    elif scenario in ("g5t-commander-p1", "g5t-commander-p4"):
        ids.update(("applied_choice_legality", "commander_squad_follows_orders",
                    "self_preservation_removal", "cover_changes_effective_ac",
                    "cover_expiration"))
    elif scenario in ("g5a-ally-p1", "g5a-ally-p4"):
        ids.update(("g5a_party_and_active_ally", "g5a_scripted_damage_legal",
                    "g5a_accepted_directive",
                    "g5a_directive_take_cover", "g5a_no_forbidden_ally_choice",
                    "g5a_applied_choice_legality", "g5a_ally_call_bounds",
                    "g5a_sandbox_flags"))
    return ids


def _expected_profile_contract(scenario: str, party: int, branch: Optional[str],
                               phase: Optional[str]) -> Optional[Dict[str, Any]]:
    if scenario in ("g5a-ally-p1", "g5a-ally-p4"):
        if party not in (1, 4) or scenario != "g5a-ally-p%d" % party or branch is not None or phase is not None:
            return None
        if __package__:
            from scripts.combat_latency_fixtures import build_gate_profile
        else:
            from combat_latency_fixtures import build_gate_profile
        profile = build_gate_profile("g5a", scenario, party)
        return {key: profile.get(key) for key in
                ("scenario_id", "party_size", "branch", "phase", "seed", "applicability")} | {
                    "gate": "g5a"}
    if scenario in ("g5t-commander-p1", "g5t-commander-p4"):
        if party not in (1, 4) or scenario != "g5t-commander-p%d" % party or branch is not None or phase is not None:
            return None
        if __package__:
            from scripts.combat_latency_fixtures import build_gate_profile
        else:
            from combat_latency_fixtures import build_gate_profile
        profile = build_gate_profile("g5t", scenario, party)
        return {key: profile.get(key) for key in
                ("scenario_id", "party_size", "branch", "phase", "seed", "applicability")} | {
                    "gate": "g5t"}
    if scenario not in {"combat-smoke", "combat-smoke-allied-inactive", "initiative-pc",
                        "initiative-dm-tie", "death-save", "surrender-exit", "resume-replay"} or party not in (1, 4):
        return None
    if (scenario == "surrender-exit" and branch not in ("surrender", "explicit-exit")) or (
            scenario != "surrender-exit" and branch is not None):
        return None
    if (scenario == "resume-replay" and phase not in ("complete", "replay")) or (
            scenario != "resume-replay" and phase is not None):
        return None
    seed: Dict[str, Any] = {}
    if scenario == "initiative-pc":
        seed = {"awaitingPcGroupRoll": True, "dmGroup": 8, "pcGroup": None}
    elif scenario == "initiative-dm-tie":
        seed = {"awaitingPcGroupRoll": True, "dmGroup": 12, "pcGroup": None, "expected_roll": 12}
    elif scenario == "death-save":
        seed = {"pending_death_save_pc": "Acheron", "hitPoints": 0, "status": "unconscious"}
    elif scenario in ("combat-smoke", "combat-smoke-allied-inactive"):
        if __package__:
            from scripts.combat_latency_fixtures import (
                CAPTURE_ALLIED_NPC_NAME,
                CAPTURE_INACTIVE_ENEMY_NAME,
                build_capture_combat_context,
            )
        else:
            from combat_latency_fixtures import (
                CAPTURE_ALLIED_NPC_NAME,
                CAPTURE_INACTIVE_ENEMY_NAME,
                build_capture_combat_context,
            )

        if scenario == "combat-smoke-allied-inactive":
            seed = {
                "allied_npc": CAPTURE_ALLIED_NPC_NAME,
                "inactive_enemy": CAPTURE_INACTIVE_ENEMY_NAME,
                "party_ally": {"name": CAPTURE_ALLIED_NPC_NAME, "role": "Ally"},
                "media_asset": "web/static/media/npcs/blairen.jpg",
            }
        seed["encounter_context"] = build_capture_combat_context(
            party, include_allied_inactive=scenario == "combat-smoke-allied-inactive"
        )
    elif scenario == "surrender-exit":
        last = "Goblin Beta" if party == 4 else "Goblin"
        enemies = ["Goblin Alpha", "Goblin Beta"] if party == 4 else ["Goblin"]
        seed = {"branch": branch, "last_hostile": last, "inactive_enemies": [name for name in enemies if name != last],
                "completion_mode": "normal_backend_output" if branch == "surrender" else "canonical_clear_then_narrator_followup",
                "followup_label": "post-exit narrator handoff" if branch == "explicit-exit" else None}
        if branch == "surrender":
            seed["encounter_context"] = (
                "%s is the last living hostile. %s has voluntarily offered unconditional "
                "surrender, lowered its weapon, and awaits the party's acceptance."
                % (last, last)
            )
    elif scenario == "resume-replay":
        seed = {"resume_phase": phase}
    return {"scenario_id": scenario, "party_size": party, "branch": branch,
            "phase": phase, "seed": seed,
            "applicability": {"party_size": party,
                              "wrong_actor_death_save": scenario == "death-save" and party == 4}}


def _expected_profile_bounds(profile: Dict[str, Any]) -> Dict[str, int]:
    scenario, party = profile["scenario_id"], profile["party_size"]
    if scenario in ("g5a-ally-p1", "g5a-ally-p4"):
        if __package__:
            from scripts.combat_latency_fixtures import (
                build_g5a_active_switch_count,
                build_g5a_script_steps,
            )
        else:
            from combat_latency_fixtures import (
                build_g5a_active_switch_count,
                build_g5a_script_steps,
            )
        max_steps = len(build_g5a_script_steps(party))
        switches = build_g5a_active_switch_count(party)
        return {"max_steps": max_steps, "max_active_switches": switches,
                "max_requests": max_steps + 1 + switches,
                "max_health_reads": 0}
    if scenario in ("g5t-commander-p1", "g5t-commander-p4"):
        if __package__:
            from scripts.combat_latency_fixtures import (
                build_g5t_script_active_switch_count,
                build_g5t_script_steps,
            )
        else:
            from combat_latency_fixtures import (
                build_g5t_script_active_switch_count,
                build_g5t_script_steps,
            )
        max_steps = len(build_g5t_script_steps(party))
        switches = build_g5t_script_active_switch_count(party)
        return {"max_steps": max_steps, "max_active_switches": switches,
                "max_requests": max_steps + 1 + switches,
                "max_health_reads": 0}
    steps = {"combat-smoke": {1: 5, 4: 22}, "combat-smoke-allied-inactive": {1: 5, 4: 22},
             "initiative-pc": {1: 2, 4: 2}, "initiative-dm-tie": {1: 2, 4: 2},
              "death-save": {1: 2, 4: 3}, "surrender-exit": {1: 2, 4: 2},
             "resume-replay": {1: {"complete": 2, "replay": 0}, 4: {"complete": 2, "replay": 0}}}
    max_steps = steps[scenario][party]
    if isinstance(max_steps, dict):
        max_steps = max_steps[profile["phase"]]
    if scenario == "surrender-exit" and profile.get("branch") == "surrender":
        max_steps = 1
    if scenario in ("combat-smoke", "combat-smoke-allied-inactive"):
        switches = 12 if party == 4 else 1
    elif scenario == "death-save":
        switches = 3 if party == 4 else 1
    elif scenario == "resume-replay" and profile["phase"] == "replay":
        switches = 0
    else:
        switches = 1
    health_reads = 1 if scenario == "surrender-exit" and profile.get("branch") == "explicit-exit" else 0
    return {"max_steps": max_steps, "max_active_switches": switches,
            "max_requests": max_steps + 1 + switches, "max_health_reads": health_reads}


def _g7_snapshot_manifests(snapshot: Any, encounter_id: str, path: str) -> List[Dict[str, Any]]:
    records = snapshot.get("records") if isinstance(snapshot, dict) else None
    history_files = records.get("modules/conversation_history", []) if isinstance(records, dict) else []
    rows = []
    for history in history_files if isinstance(history_files, list) else []:
        manifests = history.get("combat_turn_commit_manifests") if isinstance(history, dict) else None
        for row in manifests if isinstance(manifests, list) else []:
            if (isinstance(row, dict) and row.get("encounter_id") == encounter_id and
                    row.get("path") == path):
                rows.append(row)
    return rows


def _g7_trace_rows(run_dir: Path, artifacts: Dict[str, Any]) -> tuple[List[Dict[str, Any]], Optional[str]]:
    path, error = _bundle_file(run_dir, artifacts.get("trace"))
    if error or path is None:
        return [], error or "trace_missing"
    raw, error = _safe_read_bytes(path, run_dir)
    if error or raw is None:
        return [], error or "trace_unreadable"
    if len(raw) > 20 * 1024 * 1024:
        return [], "trace_size_limit_exceeded"
    rows: List[Dict[str, Any]] = []
    for number, line in enumerate(raw.splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line.decode("utf-8"))
        except (UnicodeError, ValueError):
            return [], "trace_malformed:%d" % number
        if not isinstance(row, dict):
            return [], "trace_row_not_object:%d" % number
        rows.append(row)
    return rows, None


def _g7_character_records(snapshot: Any) -> Dict[str, Dict[str, Any]]:
    records = snapshot.get("records") if isinstance(snapshot, dict) else None
    if not isinstance(records, dict):
        return {}
    return {str(row.get("name", "")).casefold(): row
            for key, row in records.items()
            if key.startswith("characters/") and isinstance(row, dict) and
            isinstance(row.get("name"), str)}


def _g7_changed_character_names(before: Any, after: Any) -> List[str]:
    """Return normalized character identities whose committed projection changed."""
    before_chars = _g7_character_records(before)
    after_chars = _g7_character_records(after)
    return sorted(
        name for name in set(before_chars) | set(after_chars)
        if (name not in before_chars or name not in after_chars or
            _g7_character_projection(before_chars[name]) !=
            _g7_character_projection(after_chars[name]))
    )


def _g7_character_projection(row: Dict[str, Any]) -> Dict[str, Any]:
    return {key: row.get(key) for key in (
        "name", "hitPoints", "maxHitPoints", "status", "condition", "condition_affected",
        "deathSaves", "resource_state", "experience_points", "experiencePoints", "currency",
        "last_combat_applied_id",
    )}


def _g7_encounter_record(snapshot: Any) -> Dict[str, Any]:
    records = snapshot.get("records") if isinstance(snapshot, dict) else None
    encounter = records.get("selected_encounter") if isinstance(records, dict) else None
    return encounter if isinstance(encounter, dict) else {}


def _g7_party_record(snapshot: Any) -> Dict[str, Any]:
    records = snapshot.get("records") if isinstance(snapshot, dict) else None
    party = records.get("party_tracker.json") if isinstance(records, dict) else None
    return party if isinstance(party, dict) else {}


def _g7_marker_names(snapshot: Any, applied_id: str) -> List[str]:
    return sorted([name for name, row in _g7_character_records(snapshot).items()
                   if row.get("last_combat_applied_id") == applied_id])


def _g7_receipts(snapshot: Any, applied_id: Optional[str] = None) -> List[Dict[str, Any]]:
    receipts = _g7_encounter_record(snapshot).get("turn_receipts", [])
    if not isinstance(receipts, list):
        return []
    return [row for row in receipts if isinstance(row, dict) and
            (applied_id is None or row.get("applied_id") == applied_id)]


def _g7_recovery_requires_zero_providers(
    phase: Any, boundary: Any, before: Any, applied_id: str
) -> bool:
    """Apply D7's provider-free rule only while the turn receipt is pending."""
    if phase != "recover":
        return False
    if boundary == "before_first_character_write":
        return True
    if isinstance(boundary, str) and re.fullmatch(
            r"after_character_write:[1-9][0-9]{0,2}", boundary):
        return True
    if boundary == "after_encounter_write":
        return not _g7_receipts(before, applied_id)
    return False


def _g7_provider_event_regenerates_recovered_turn(
    row: Dict[str, Any],
    *,
    applied_id: str,
    commit_manifest: Dict[str, Any],
    expected_profile: Optional[Dict[str, Any]],
) -> bool:
    """Recognize provider events tied to the recovered turn, not ordinary resume."""
    if row.get("applied_id") == applied_id or row.get("turn_id") == commit_manifest.get("turn_id"):
        return True

    receipt = commit_manifest.get("receipt")
    round_number = receipt.get("combat_round") if isinstance(receipt, dict) else None
    if (isinstance(round_number, bool) or not isinstance(round_number, int) or
            round_number < 1):
        return False

    if commit_manifest.get("path") == "enemy_batch":
        return row.get("batch_id") == "enemy:r%d" % round_number

    fixture = (expected_profile.get("fixture")
               if isinstance(expected_profile, dict) else None)
    party_names = fixture.get("party_names") if isinstance(fixture, dict) else None
    if not isinstance(party_names, list) or not party_names:
        return False
    actor = party_names[0]
    if not isinstance(actor, str) or not actor:
        return False
    return row.get("action_id") == "pc:r%d:%s" % (round_number, actor.casefold())


def _g7_recovery_provider_failures(
    *,
    phase: Any,
    boundary: Any,
    before: Any,
    applied_id: str,
    commit_manifest: Dict[str, Any],
    expected_profile: Optional[Dict[str, Any]],
    provider_rows: List[Dict[str, Any]],
    provider_count: Any,
) -> List[str]:
    """Enforce provider-free pending recovery without rejecting resume calls."""
    failures: List[str] = []
    requires_zero = _g7_recovery_requires_zero_providers(
        phase, boundary, before, applied_id
    )
    if requires_zero:
        if type(provider_count) is not int or provider_count != 0:
            failures.append("g7_recovery_provider_count_not_zero")
        if provider_rows:
            failures.append("g7_recovery_trace_contains_provider_events")
        return failures

    if phase in ("recover", "replay") and any(
            _g7_provider_event_regenerates_recovered_turn(
                row,
                applied_id=applied_id,
                commit_manifest=commit_manifest,
                expected_profile=expected_profile,
            )
            for row in provider_rows):
        failures.append("g7_recovery_trace_contains_recovered_turn_provider_event")
    return failures


def _g7_manifest_effects(commit_manifest: Dict[str, Any]) -> List[Dict[str, Any]]:
    effects = commit_manifest.get("character_effects")
    return [row for row in effects if isinstance(row, dict)] if isinstance(effects, list) else []


def _g7_expected_marker_names(
    phase: Any, boundary: Any, effects: List[Dict[str, Any]], committed_boundary: bool
) -> List[str]:
    """Return the marker set expected after this run's interrupt or recovery."""
    effect_names = [
        str(effect.get("character_name", "")).casefold() for effect in effects
    ]
    if phase == "interrupt":
        if boundary == "before_first_character_write":
            return []
        if isinstance(boundary, str) and boundary.startswith("after_character_write:"):
            try:
                write_count = int(boundary.rsplit(":", 1)[1])
            except ValueError:
                return []
            return effect_names[:write_count]
        return effect_names if committed_boundary else []
    if phase in ("recover", "complete", "replay"):
        return effect_names
    return []


def _g7_enemy_batch_manifest_target(
    commit_manifest: Dict[str, Any], expected_roster: Optional[List[str]]
) -> Optional[str]:
    """Return the one party PC persisted as an enemy-batch effect target."""
    effects = commit_manifest.get("character_effects")
    if not isinstance(effects, list) or len(effects) != 1 or not isinstance(effects[0], dict):
        return None
    name = effects[0].get("character_name")
    roster = {member.casefold() for member in expected_roster or []
              if isinstance(member, str)}
    if not isinstance(name, str) or name.casefold() not in roster:
        return None
    return name


def _g7_snapshot_pair_matches(left: Any, right: Any) -> bool:
    if not isinstance(left, dict) or not isinstance(right, dict):
        return False
    return left.get("mechanical_projection") == right.get("mechanical_projection")


def _g7_effect_projection_matches(effect: Dict[str, Any], character: Dict[str, Any]) -> bool:
    expected = effect.get("effect_projection")
    if not isinstance(expected, dict):
        return False
    observed = _g7_character_projection(character)
    for key, value in expected.items():
        if observed.get(key) != value:
            return False
    return True


def _g7_receipt_is_valid(receipt: Dict[str, Any], commit_manifest: Dict[str, Any]) -> bool:
    receipt_keys = {
        "schema_version", "turn_id", "applied_id", "encounter_id",
        "combat_round", "commit_timestamp",
    }
    timestamp = receipt.get("commit_timestamp")
    return (
        set(receipt) == receipt_keys and
        receipt.get("schema_version") == 1 and
        not isinstance(receipt.get("schema_version"), bool) and
        receipt.get("turn_id") == commit_manifest.get("turn_id") and
        receipt.get("applied_id") == commit_manifest.get("applied_id") and
        receipt.get("encounter_id") == commit_manifest.get("encounter_id") and
        isinstance(receipt.get("combat_round"), int) and
        not isinstance(receipt.get("combat_round"), bool) and receipt.get("combat_round") > 0 and
        isinstance(timestamp, str) and
        bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z", timestamp))
    )


def evaluate_g7_bundle(manifest: Dict[str, Any], artifacts: Dict[str, Any],
                       run_dir: Path) -> Dict[str, Any]:
    """Validate one retained G7 row; only a complete matrix may be review-ready."""
    run = Path(run_dir)
    failures: List[str] = []
    problems: List[str] = []
    scenario = manifest.get("scenario") if isinstance(manifest.get("scenario"), dict) else {}
    party = manifest.get("party") if isinstance(manifest.get("party"), dict) else {}
    profile = scenario.get("profile_contract") if isinstance(scenario.get("profile_contract"), dict) else {}
    g7 = manifest.get("g7") if isinstance(manifest.get("g7"), dict) else {}
    party_size = party.get("size")
    path, boundary, phase = profile.get("path"), profile.get("boundary"), scenario.get("phase")
    row_key = g7_matrix_key(party_size if isinstance(party_size, int) else -1,
                             path, boundary, phase)
    expected_roster: Optional[List[str]] = None
    expected_profile: Optional[Dict[str, Any]] = None

    try:
        from scripts import combat_latency_fixtures
        if (manifest.get("gate") != "g7" or scenario.get("id") != "turn-commit" or
            isinstance(party_size, bool) or party_size not in (1, 4) or
            path not in G7_PATHS or phase not in G7_PHASES):
            failures.append("g7_row_identity_invalid")
            expected_profile = None
        else:
            expected_profile = combat_latency_fixtures.build_gate_profile(
                "g7", "turn-commit", party_size, path=path, boundary=boundary, phase=phase
            )
            expected_roster = expected_profile.get("fixture", {}).get("party_names")
        if expected_profile is not None:
            expected_contract = {key: expected_profile.get(key) for key in
                ("scenario_id", "party_size", "branch", "phase", "seed", "applicability")}
            expected_contract.update({"gate": "g7", "path": path, "boundary": boundary})
            contract_hash = hashlib.sha256(
                json.dumps(expected_contract, sort_keys=True).encode("utf-8")
            ).hexdigest()
            if profile != expected_contract or scenario.get("sha256") != contract_hash:
                failures.append("g7_profile_contract_mismatch")
            if artifacts.get("matrix_keys") != [g7_matrix_key(party_size, path, boundary, phase)]:
                failures.append("g7_matrix_key_mismatch")
            expected_seed = expected_profile.get("seed")
            seed = manifest.get("seed") if isinstance(manifest.get("seed"), dict) else {}
            expected_seed_id = hashlib.sha256(
                json.dumps(expected_seed, sort_keys=True).encode("utf-8")
            ).hexdigest()
            if (party.get("roster") != expected_roster or
                    seed.get("profile_seed") != expected_seed or
                    seed.get("seed_id") != expected_seed_id or
                    seed.get("seed_profile_sha256") != expected_seed_id):
                failures.append("g7_party_or_seed_identity_mismatch")
    except (ImportError, TypeError, ValueError):
        failures.append("g7_profile_not_reconstructable")

    transport = manifest.get("transport") if isinstance(manifest.get("transport"), dict) else {}
    sandbox_runtime = manifest.get("sandbox_runtime") if isinstance(manifest.get("sandbox_runtime"), dict) else {}
    trace_gate = sandbox_runtime.get("trace_gate") if isinstance(sandbox_runtime.get("trace_gate"), dict) else {}
    configuration = manifest.get("configuration") if isinstance(manifest.get("configuration"), dict) else {}
    source = manifest.get("source") if isinstance(manifest.get("source"), dict) else {}
    dirty_sources = source.get("relevant_dirty_source_sha256")
    source_hashes = source.get("relevant_source_sha256")
    expected_dirty_digest = (hashlib.sha256(
        json.dumps(dirty_sources, sort_keys=True).encode("utf-8")
    ).hexdigest() if isinstance(dirty_sources, dict) else None)
    if (not isinstance(source.get("head"), str) or
            not re.fullmatch(r"[0-9a-f]{40,64}", source.get("head", "")) or
            not isinstance(source_hashes, dict) or not source_hashes or
            any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value)
                for value in source_hashes.values()) or
            not isinstance(dirty_sources, dict) or
            any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value)
                for value in dirty_sources.values()) or
            source.get("relevant_dirty_sha256") != expected_dirty_digest):
        problems.append("g7_source_identity_unavailable")
    configured_runtime = g7.get("configured_runtime")
    if (not isinstance(configured_runtime, dict) or configured_runtime.get("status") != "ok" or
            not isinstance(configured_runtime.get("configured_provider"), str) or
            not configured_runtime.get("configured_provider") or
            not isinstance(configured_runtime.get("configured_model"), str) or
            not configured_runtime.get("configured_model")):
        problems.append("g7_model_provider_identity_unavailable")
    if (manifest.get("evidence_kind") == "synthetic" or manifest.get("live_eligible") is not True or
            transport.get("client_source") != "socketio.Client"):
        problems.append("synthetic_or_ineligible_evidence")
    if sandbox_runtime.get("port") != 8360:
        failures.append("g7_wrong_sandbox_port")
    if trace_gate.get("status") != "ok" or trace_gate.get("enabled") is not True:
        problems.append("g7_trace_gate_unverified")
    g7_runtime = configuration.get("g7_runtime", {})
    if not isinstance(g7_runtime, dict) or g7_runtime.get("status") != "ok":
        problems.append("g7_sandbox_flags_unverified")

    integrity = _artifact_integrity(run, manifest, artifacts)
    if integrity.get("failures"):
        problems.extend("artifact:%s" % value for value in integrity["failures"])
    for name in ("transcript", "server_log", "trace", "before_snapshot", "after_snapshot"):
        artifact_path, artifact_error = _bundle_file(run, artifacts.get(name))
        if artifact_error or artifact_path is None:
            problems.append("missing_%s" % name)

    server_log_path, server_log_error = _bundle_file(run, artifacts.get("server_log"))
    if server_log_error or server_log_path is None:
        problems.append("g7_server_log_unavailable")
    else:
        server_log_raw, server_log_read_error = _safe_read_bytes(server_log_path, run)
        if server_log_read_error or server_log_raw is None:
            problems.append("g7_server_log_unreadable")
        else:
            expected_marker = "COMBAT_TURN_FAULT_INJECTED:%s" % boundary
            marker_present = b"COMBAT_TURN_FAULT_INJECTED:" in server_log_raw
            exact_marker_present = expected_marker.encode("ascii") in server_log_raw
            if phase == "interrupt" and not exact_marker_present:
                failures.append("g7_server_log_expected_fault_marker_missing")
            if phase != "interrupt" and marker_present:
                failures.append("g7_unexpected_fault_marker_in_restart_log")

    before, before_error = load_bundle_json(run, artifacts.get("before_snapshot"))
    after, after_error = load_bundle_json(run, artifacts.get("after_snapshot"))
    if before_error or not isinstance(before, dict):
        problems.append("before_snapshot:%s" % (before_error or "invalid"))
    if after_error or not isinstance(after, dict):
        problems.append("after_snapshot:%s" % (after_error or "invalid"))
    for label, snapshot in (("before", before), ("after", after)):
        if isinstance(snapshot, dict) and (snapshot.get("errors") or snapshot.get("numeric_errors")):
            problems.append("%s_snapshot_incomplete" % label)
        if isinstance(snapshot, dict):
            party_record = _g7_party_record(snapshot)
            if party_record.get("status") != "ok":
                problems.append("%s_party_tracker_unavailable" % label)
            if party_record.get("partyMembers") != expected_roster:
                failures.append("g7_%s_party_roster_mismatch" % label)
            encounter_record = _g7_encounter_record(snapshot)
            if encounter_record.get("status") != "ok":
                problems.append("%s_encounter_unavailable" % label)

    counts = manifest.get("counts", {})
    expected_steps = 1 if phase in ("interrupt", "complete") else 0
    if counts.get("steps_sent") != expected_steps or counts.get("step_attempts") != expected_steps:
        failures.append("g7_step_count_mismatch")

    expected_stop = g7.get("expected_stop") if isinstance(g7.get("expected_stop"), dict) else {}
    if phase == "interrupt":
        expected_marker = "COMBAT_TURN_FAULT_INJECTED:%s" % boundary
        if (expected_stop.get("declared") is not True or expected_stop.get("status") != "observed" or
                expected_stop.get("marker") != expected_marker or
                expected_stop.get("wait_timed_out") is not False):
            failures.append("g7_expected_lifecycle_stop_missing_or_mismatched")
    elif expected_stop.get("status") not in (None, "not_applicable"):
        failures.append("g7_unexpected_lifecycle_stop_metadata")

    trace_rows, trace_error = _g7_trace_rows(run, artifacts)
    if trace_error:
        problems.append("g7_trace:%s" % trace_error)
    provider_rows = [row for row in trace_rows if row.get("event_type") == "provider"]

    encounter_id = profile.get("seed", {}).get("encounter_id") if isinstance(profile.get("seed"), dict) else None
    for label, snapshot in (("before", before), ("after", after)):
        if not isinstance(snapshot, dict):
            continue
        party_record = snapshot.get("records", {}).get("party_tracker.json", {})
        active_encounter = (party_record.get("worldConditions") or {}).get("activeCombatEncounter")
        if active_encounter != encounter_id:
            failures.append("g7_%s_active_encounter_mismatch" % label)

    after_manifests = (_g7_snapshot_manifests(after, encounter_id, path)
                       if isinstance(after, dict) and isinstance(encounter_id, str) and isinstance(path, str) else [])
    before_manifests = (_g7_snapshot_manifests(before, encounter_id, path)
                        if isinstance(before, dict) and isinstance(encounter_id, str) and isinstance(path, str) else [])
    selected_manifests = (
        before_manifests if phase == "recover" else (after_manifests or before_manifests)
    )
    selected_manifest = selected_manifests[0] if len(selected_manifests) == 1 else None
    if selected_manifest is None or selected_manifest.get("status") != "ok":
        problems.append("g7_history_manifest_missing_or_ambiguous")
    else:
        if selected_manifest.get("schema_version") != 1:
            failures.append("g7_history_manifest_schema_version_invalid")
        turn_id = selected_manifest.get("turn_id")
        applied_id = selected_manifest.get("applied_id")
        if (selected_manifest.get("history_turn_id") != turn_id or
                not isinstance(turn_id, str) or not re.fullmatch(
                    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", turn_id) or
                not isinstance(applied_id, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", applied_id)):
            failures.append("g7_history_manifest_identity_invalid")
        effects = selected_manifest.get("character_effects")
        observed_names = ([row.get("character_name") for row in effects
                           if isinstance(row, dict)] if isinstance(effects, list) else None)
        expected_names = (
            profile.get("seed", {}).get("expected_changed_characters")
            if isinstance(profile.get("seed"), dict) else None
        )
        if path == "enemy_batch":
            if _g7_enemy_batch_manifest_target(selected_manifest, expected_roster) is None:
                failures.append("g7_enemy_batch_manifest_not_single_pc_effect")
        elif (not isinstance(expected_names, list) or
              observed_names != sorted(expected_names, key=str.casefold)):
            failures.append("g7_manifest_character_effect_set_mismatch")
        if selected_manifest.get("encounter_id") != encounter_id or selected_manifest.get("path") != path:
            failures.append("g7_history_manifest_scenario_mismatch")

        effects = _g7_manifest_effects(selected_manifest)
        effect_names = [row.get("character_name") for row in effects]
        if (len(effect_names) != len(set(name.casefold() for name in effect_names
                                         if isinstance(name, str))) or
                any(not isinstance(name, str) for name in effect_names) or
                effect_names != sorted(effect_names, key=str.casefold)):
            failures.append("g7_manifest_effect_order_or_identity_invalid")
        current_applied_id = applied_id if isinstance(applied_id, str) else ""
        provider_counts = counts.get("provider_calls")
        provider_count = (provider_counts.get("count")
                          if isinstance(provider_counts, dict) else None)
        failures.extend(_g7_recovery_provider_failures(
            phase=phase,
            boundary=boundary,
            before=before,
            applied_id=current_applied_id,
            commit_manifest=selected_manifest,
            expected_profile=expected_profile,
            provider_rows=provider_rows,
            provider_count=provider_count,
        ))
        expected_names = (
            profile.get("seed", {}).get("expected_changed_characters")
            if isinstance(profile.get("seed"), dict) else None
        )
        expected_name_keys = sorted(name.casefold() for name in effect_names
                                    if isinstance(name, str))
        if path != "enemy_batch":
            static_name_keys = sorted(name.casefold() for name in expected_names
                                      if isinstance(name, str)) if isinstance(expected_names, list) else []
            if expected_name_keys != static_name_keys:
                failures.append("g7_manifest_character_effect_set_mismatch")

        committed_boundary = boundary in (
            "after_encounter_write", "after_phase_sync", "during_success_publication",
            "after_success_publication",
        )
        expected_marker_names = _g7_expected_marker_names(
            phase, boundary, effects, committed_boundary
        )

        snapshots_to_check = (("after", after),) if phase in ("interrupt", "complete", "recover", "replay") else ()
        for label, snapshot in snapshots_to_check:
            if not isinstance(snapshot, dict):
                continue
            marker_names = _g7_marker_names(snapshot, current_applied_id)
            if marker_names != sorted(expected_marker_names):
                failures.append("g7_%s_character_marker_set_mismatch" % label)
            receipt_rows = _g7_receipts(snapshot, current_applied_id)
            receipt_expected = (phase in ("recover", "complete", "replay") or
                                (phase == "interrupt" and committed_boundary))
            if len(receipt_rows) != (1 if receipt_expected else 0):
                failures.append("g7_%s_receipt_count_mismatch" % label)
            if receipt_expected and len(receipt_rows) == 1 and not _g7_receipt_is_valid(
                    receipt_rows[0], selected_manifest):
                failures.append("g7_%s_receipt_schema_or_identity_invalid" % label)

            before_chars = _g7_character_records(before)
            after_chars = _g7_character_records(snapshot)
            marked = set(marker_names)
            for effect in effects:
                name = effect.get("character_name")
                if not isinstance(name, str):
                    continue
                key = name.casefold()
                observed_character = after_chars.get(key)
                if observed_character is None:
                    failures.append("g7_character_effect_record_missing:%s" % name)
                    continue
                if key in marked:
                    if not _g7_effect_projection_matches(effect, observed_character):
                        failures.append("g7_character_effect_projection_mismatch:%s" % name)
                elif phase == "interrupt":
                    original = before_chars.get(key)
                    if original is None or _g7_character_projection(original) != \
                            _g7_character_projection(observed_character):
                        failures.append("g7_unwritten_character_changed:%s" % name)
            if phase in ("recover", "complete", "replay") and marked != set(expected_name_keys):
                failures.append("g7_final_effect_markers_incomplete")

        if phase in ("interrupt", "complete") and isinstance(before, dict):
            if _g7_marker_names(before, current_applied_id) or _g7_receipts(before, current_applied_id):
                failures.append("g7_fresh_seed_contains_turn_effects")

        if isinstance(after, dict) and (phase != "interrupt" or committed_boundary):
            encounter_projection = selected_manifest.get("encounter_projection")
            actual_encounter = _g7_encounter_record(after)
            actual_creatures = actual_encounter.get("creatures")
            actual_projection = _g7_encounter_projection({
                "encounterId": actual_encounter.get("encounterId"),
                "current_round": actual_encounter.get("current_round"),
                "combat_round": actual_encounter.get("combat_round"),
                "combat_phase": actual_encounter.get("combat_phase"),
                "pcPhaseComplete": actual_encounter.get("pcPhaseComplete"),
                "openingEnemyBatchPending": actual_encounter.get("openingEnemyBatchPending"),
                "turn_receipts": actual_encounter.get("turn_receipts", []),
                "creatures": actual_creatures,
            })
            if not isinstance(encounter_projection, dict):
                failures.append("g7_manifest_encounter_projection_missing")
            else:
                for field in ("encounterId", "current_round", "combat_round", "combat_phase",
                              "pcPhaseComplete", "openingEnemyBatchPending"):
                    if encounter_projection.get(field) != actual_projection.get(field):
                        failures.append("g7_encounter_projection_mismatch:%s" % field)
                if encounter_projection.get("creatures") != actual_projection.get("creatures"):
                    failures.append("g7_encounter_projection_mismatch:creatures")

        publication_events = [row for row in trace_rows
                              if row.get("observation") == "combat_turn_success_publication"]
        matching_publications = [row for row in publication_events
                                 if row.get("applied_id") == current_applied_id]
        if any(row.get("applied_id") != current_applied_id for row in publication_events):
            failures.append("g7_success_publication_applied_id_mismatch")
        publication_expected = (
            (phase == "complete") or
            (phase == "interrupt" and boundary in ("during_success_publication", "after_success_publication"))
        )
        if phase == "recover" and isinstance(before, dict) and not _g7_receipts(before, current_applied_id):
            publication_expected = True
        if publication_expected and len(matching_publications) != 1:
            failures.append("g7_success_publication_trace_missing_or_duplicate")
        if phase in ("recover", "replay") and len(matching_publications) > 1:
            failures.append("g7_recovery_success_publication_duplicated")
        for name in ("experience_points", "experiencePoints"):
            if isinstance(before, dict) and isinstance(after, dict):
                before_values = {key: row.get(name) for key, row in _g7_character_records(before).items()}
                after_values = {key: row.get(name) for key, row in _g7_character_records(after).items()}
                if phase in ("recover", "replay") and before_values == after_values:
                    continue
                if phase in ("interrupt", "complete", "recover", "replay") and any(
                        before_values.get(key) != after_values.get(key)
                        for key in set(before_values) & set(after_values)):
                    failures.append("g7_unexpected_reward_delta:%s" % name)

    # A single row is never itself the complete matrix or a primary verdict.
    return {
        "automated_status": "FAIL" if failures else "BLOCKED",
        "primary_verdict": "PENDING",
        "matrix_key": row_key,
        "failures": failures,
        "problems": problems,
        "integrity_failures": integrity.get("failures", []),
        "trace_provider_events": len(provider_rows),
        "selected_manifest": selected_manifest,
        "before_snapshot": before,
        "after_snapshot": after,
        "trace_rows": trace_rows,
    }


def _evaluate_g7_run(run_dir: Path) -> Dict[str, Any]:
    manifest, error = load_bundle_json(run_dir, "manifest.json")
    if error or not isinstance(manifest, dict):
        return {"run_dir": str(run_dir), "error": "manifest:%s" % (error or "invalid")}
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict):
        return {"run_dir": str(run_dir), "manifest": manifest,
                "error": "artifacts_not_object"}
    evaluation = evaluate_g7_bundle(manifest, artifacts, run_dir)
    return {"run_dir": str(run_dir), "manifest": manifest,
            "matrix_key": evaluation.get("matrix_key"),
            "evaluation": evaluation}


def _g7_pair_identity_matches(left: Dict[str, Any], right: Dict[str, Any]) -> bool:
    first = left.get("selected_manifest")
    second = right.get("selected_manifest")
    return bool(
        isinstance(first, dict) and isinstance(second, dict) and
        first.get("turn_id") == second.get("turn_id") and
        first.get("applied_id") == second.get("applied_id") and
        first.get("encounter_id") == second.get("encounter_id") and
        first.get("path") == second.get("path")
    )


def evaluate_g7_matrix(run_rows: Iterable[Any]) -> Dict[str, Any]:
    """Revalidate all G7 bundles; readiness is never a primary gate verdict."""
    required = required_g7_matrix_keys()
    invalid_runs: List[str] = []
    duplicate_keys: List[str] = []
    by_key: Dict[str, Dict[str, Any]] = {}
    for row in run_rows:
        try:
            candidate = Path(row.get("run_dir")) if isinstance(row, dict) and row.get("run_dir") else Path(row)
            if not candidate.is_absolute():
                candidate = PROJECT_ROOT / candidate
        except (TypeError, ValueError):
            invalid_runs.append("invalid_run_directory_input")
            continue
        if (not _inside(candidate, G7_RUN_ROOT) or candidate.resolve() == G7_RUN_ROOT.resolve() or
                _has_symlink_component(candidate, PROJECT_TMP)):
            invalid_runs.append("unsafe_run_directory:%s" % candidate.name)
            continue
        result = _evaluate_g7_run(candidate)
        key = result.get("matrix_key")
        if not isinstance(key, str) or key not in required:
            invalid_runs.append("%s:%s" % (candidate.name, result.get("error", "unknown_g7_matrix_key")))
            continue
        if key in by_key:
            duplicate_keys.append(key)
            continue
        by_key[key] = result

    pair_failures: List[str] = []
    for party in (1, 4):
        from scripts import combat_latency_fixtures

        for path in G7_PATHS:
            for boundary in combat_latency_fixtures.g7_commit_boundaries(party, path):
                interrupt_key = g7_matrix_key(party, path, boundary, "interrupt")
                recover_key = g7_matrix_key(party, path, boundary, "recover")
                interrupt = by_key.get(interrupt_key, {}).get("evaluation", {})
                recover = by_key.get(recover_key, {}).get("evaluation", {})
                if (not interrupt or not recover or interrupt.get("problems") or
                        recover.get("problems") or not interrupt.get("selected_manifest") or
                        not recover.get("selected_manifest")):
                    continue
                if not _g7_pair_identity_matches(interrupt, recover):
                    pair_failures.append("%s|%s:turn_identity_not_reused" % (interrupt_key, recover_key))
                if not _g7_snapshot_pair_matches(interrupt.get("after_snapshot"),
                                                 recover.get("before_snapshot")):
                    pair_failures.append("%s|%s:retained_state_changed_before_recovery" %
                                         (interrupt_key, recover_key))
                selected = interrupt.get("selected_manifest")
                if isinstance(selected, dict):
                    applied_id = selected.get("applied_id")
                    recovery_after = recover.get("after_snapshot")
                    receipts = _g7_receipts(recovery_after, applied_id)
                    effects = _g7_manifest_effects(selected)
                    expected_names = sorted(str(effect.get("character_name", "")).casefold()
                                            for effect in effects)
                    recovery_manifest = recover.get("selected_manifest")
                    recovery_names = sorted(
                        str(effect.get("character_name", "")).casefold()
                        for effect in _g7_manifest_effects(recovery_manifest)
                    ) if isinstance(recovery_manifest, dict) else []
                    if (len(receipts) != 1 or
                            _g7_marker_names(recovery_after, applied_id or "") != expected_names):
                        pair_failures.append("%s|%s:recovery_effects_not_applied_once" %
                                             (interrupt_key, recover_key))
                    if path == "enemy_batch":
                        changed_names = _g7_changed_character_names(
                            interrupt.get("before_snapshot"), recovery_after
                        )
                        if (len(expected_names) != 1 or recovery_names != expected_names):
                            pair_failures.append(
                                "%s|%s:enemy_batch_expected_pc_not_preserved" %
                                (interrupt_key, recover_key)
                            )
                        if changed_names != expected_names:
                            pair_failures.append(
                                "%s|%s:enemy_batch_character_changes_not_single_manifest_target" %
                                (interrupt_key, recover_key)
                            )

            complete_key = g7_matrix_key(party, path, G7_BOUNDARY_NONE, "complete")
            replay_key = g7_matrix_key(party, path, G7_BOUNDARY_NONE, "replay")
            complete = by_key.get(complete_key, {}).get("evaluation", {})
            replay = by_key.get(replay_key, {}).get("evaluation", {})
            if (complete and replay and not complete.get("problems") and
                    not replay.get("problems") and complete.get("selected_manifest") and
                    replay.get("selected_manifest")):
                if not _g7_pair_identity_matches(complete, replay):
                    pair_failures.append("%s|%s:turn_identity_not_reused" % (complete_key, replay_key))
                if not _g7_snapshot_pair_matches(complete.get("after_snapshot"),
                                                 replay.get("before_snapshot")):
                    pair_failures.append("%s|%s:completed_state_not_retained" % (complete_key, replay_key))
                if not _g7_snapshot_pair_matches(replay.get("before_snapshot"),
                                                 replay.get("after_snapshot")):
                    pair_failures.append("%s|%s:replay_changed_mechanical_state" % (complete_key, replay_key))
                selected = complete.get("selected_manifest")
                if isinstance(selected, dict):
                    applied_id = selected.get("applied_id")
                    receipts = _g7_receipts(replay.get("after_snapshot"), applied_id)
                    names = sorted(str(effect.get("character_name", "")).casefold()
                                   for effect in _g7_manifest_effects(selected))
                    if (len(receipts) != 1 or
                            _g7_marker_names(replay.get("after_snapshot"), applied_id or "") != names):
                        pair_failures.append("%s|%s:replay_effects_not_idempotent" %
                                             (complete_key, replay_key))

    missing = sorted(set(required) - set(by_key))
    extra = sorted(set(by_key) - set(required))
    failed = sorted(key for key, row in by_key.items()
                    if row.get("evaluation", {}).get("failures"))
    not_ready = sorted(key for key, row in by_key.items()
                       if row.get("evaluation", {}).get("problems") or
                       row.get("evaluation", {}).get("automated_status") != "BLOCKED")
    synthetic = sorted(key for key, row in by_key.items()
                       if (row.get("manifest") or {}).get("evidence_kind") == "synthetic" or
                       (row.get("manifest") or {}).get("live_eligible") is not True)
    issues = bool(missing or extra or duplicate_keys or invalid_runs or failed or
                  not_ready or synthetic or pair_failures)
    if failed or pair_failures:
        status = "FAIL"
    elif not issues:
        status = "READY_FOR_PRIMARY_REVIEW"
    else:
        status = "BLOCKED"
    return {
        "gate": "g7",
        "automated_status": status,
        "primary_verdict": "PENDING",
        "required_keys": required,
        "observed_keys": sorted(by_key),
        "missing_required_keys": missing,
        "extra_keys": extra,
        "duplicate_keys": sorted(set(duplicate_keys)),
        "not_ready_keys": not_ready,
        "failed_keys": failed,
        "synthetic_keys": synthetic,
        "invalid_run_bundles": invalid_runs,
        "pair_failures": sorted(pair_failures),
        "runs": {key: {
            "automated_status": row.get("evaluation", {}).get("automated_status"),
            "failures": row.get("evaluation", {}).get("failures", []),
            "problems": row.get("evaluation", {}).get("problems", []),
        } for key, row in sorted(by_key.items())},
    }


def _g9_runtime_summary(receipts: List[Dict[str, Any]], status: str = "ok") -> Dict[str, Any]:
    providers = sorted({row.get("provider") for row in receipts
                        if isinstance(row.get("provider"), str) and row.get("provider") != "unknown"})
    requested = sorted({row.get("requested_model") for row in receipts
                        if isinstance(row.get("requested_model"), str) and
                        row.get("requested_model") != "unknown"})
    resolved = sorted({row.get("resolved_model") for row in receipts
                       if isinstance(row.get("resolved_model"), str) and
                       row.get("resolved_model") != "unknown"})
    upstream = sorted({row.get("observed_upstream_provider") for row in receipts
                       if isinstance(row.get("observed_upstream_provider"), str)})
    return {
        "status": status,
        "provider": providers[0] if len(providers) == 1 else providers or "unknown",
        "response_model": resolved[0] if len(resolved) == 1 else resolved or "unknown",
        "requested_models": requested,
        "resolved_models": resolved,
        "providers": providers,
        "observed_upstream_providers": upstream,
        "receipts": receipts,
    }


def _g9_model_is_direct_openai(value: Any) -> bool:
    return isinstance(value, str) and (value == "gpt-6-luna" or value.startswith("gpt-6-luna-"))


def _g9_runtime_assertions(profile: Dict[str, Any],
                           receipts: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Evaluate routing assertions only from captured router receipts."""
    scenario = profile.get("scenario_id")
    problems: List[str] = []
    failures: List[str] = []
    responses = [row for row in receipts if row.get("outcome") == "response"]
    errors = [row for row in receipts if row.get("outcome") == "transport_error"]
    if not responses:
        problems.append("response_receipt_missing")
    for row in responses:
        if row.get("requested_model") in (None, "", "unknown"):
            problems.append("requested_model_unobserved")
        if row.get("resolved_model") in (None, ""):
            problems.append("resolved_model_unobserved")
        if row.get("provider") in (None, "", "unknown"):
            problems.append("transport_provider_unobserved")
        if row.get("observed_upstream_provider") in (None, ""):
            problems.append("upstream_provider_observation_missing")

    if scenario in ("narrator-auto", "combat-auto"):
        if errors:
            failures.append("unexpected_auto_transport_error")
        for row in responses:
            if row.get("requested_model") not in (None, "", "unknown") and row.get("requested_model") != "openrouter/auto":
                failures.append("auto_requested_model_mismatch")
            if row.get("provider") not in (None, "", "unknown") and row.get("provider") != "openrouter":
                failures.append("auto_transport_provider_mismatch")
        if any(row.get("fallback") is True for row in receipts):
            failures.append("unexpected_auto_fallback")
    elif scenario == "transport-failure":
        indexed_errors = [(index, row) for index, row in enumerate(receipts)
                          if row.get("outcome") == "transport_error"]
        injected_entries = [(index, row) for index, row in indexed_errors
                            if row.get("error_type") == "OpenRouterTransportFaultInjected"]
        injected = [row for _, row in injected_entries]
        if not errors:
            problems.append("injected_transport_failure_receipt_missing")
        elif len(injected) != 1 or len(errors) != 1:
            failures.append("injected_transport_failure_not_exactly_once")
        else:
            first = injected[0]
            if (first.get("provider") != "openrouter" or
                    first.get("requested_model") != "openrouter/auto" or
                    first.get("fallback") is not False):
                failures.append("injected_transport_failure_identity_mismatch")
        fallbacks = [row for row in receipts if row.get("fallback") is True]
        fallback_response_entries = [
            (index, row) for index, row in enumerate(receipts)
            if row.get("fallback") is True and row.get("outcome") == "response"
        ]
        fallback_responses = [row for _, row in fallback_response_entries]
        if not fallbacks:
            problems.append("direct_openai_fallback_receipt_missing")
        elif len(fallbacks) != 1 or len(fallback_responses) != 1:
            failures.append("direct_openai_fallback_not_exactly_once")
        else:
            response = fallback_responses[0]
            if (response.get("provider") != "openai" or
                    response.get("requested_model") != "gpt-6-luna" or
                    not _g9_model_is_direct_openai(response.get("resolved_model"))):
                failures.append("direct_openai_fallback_identity_mismatch")

        if any(not isinstance(row.get("call_id"), str) or not row.get("call_id", "").strip()
               for row in receipts):
            failures.append("transport_failure_call_id_missing")

        injected_call_id = injected[0].get("call_id") if len(injected) == 1 else None
        if (injected_entries and fallback_response_entries and
                len(injected_entries) == 1 and len(fallback_response_entries) == 1):
            injected_index, first = injected_entries[0]
            fallback_index, response = fallback_response_entries[0]
            if (not isinstance(injected_call_id, str) or not injected_call_id.strip() or
                    response.get("call_id") != injected_call_id):
                failures.append("fallback_not_paired_with_injected_failure")
            else:
                same_call_entries = [
                    (index, row) for index, row in enumerate(receipts)
                    if row.get("call_id") == injected_call_id
                ]
                if len(same_call_entries) != 2 or {index for index, _ in same_call_entries} != {
                        injected_index, fallback_index}:
                    failures.append("transport_failure_extra_same_call_attempt")

            error_attempt = first.get("attempt_number")
            fallback_attempt = response.get("attempt_number")
            if (injected_index >= fallback_index or
                    type(error_attempt) is not int or error_attempt < 1 or
                    type(fallback_attempt) is not int or fallback_attempt != error_attempt + 1):
                failures.append("transport_failure_order_ambiguous")

        paired_fallback_index = (
            fallback_response_entries[0][0] if len(fallback_response_entries) == 1 else None
        )
        for index, row in enumerate(receipts):
            if row.get("outcome") != "response" or index == paired_fallback_index:
                continue
            if injected_call_id and row.get("call_id") == injected_call_id:
                failures.append("transport_failure_extra_same_call_attempt")
            if (paired_fallback_index is not None and index < paired_fallback_index):
                failures.append("transport_failure_order_ambiguous")
            if (row.get("fallback") is not False or
                    row.get("provider") != "openrouter" or
                    row.get("requested_model") != "openrouter/auto"):
                failures.append("transport_failure_unexpected_additional_response")
    elif scenario == "preferred-openai-rollback":
        if not responses:
            problems.append("post_rollback_openai_response_missing")
        if errors:
            failures.append("rollback_transport_error_observed")
        for row in responses:
            if (row.get("provider") not in (None, "", "unknown") and
                    row.get("provider") != "openai"):
                failures.append("rollback_response_not_direct_openai")
            if (row.get("requested_model") not in (None, "", "unknown") and
                    row.get("requested_model") != "gpt-6-luna"):
                failures.append("rollback_requested_model_mismatch")
            if (row.get("resolved_model") not in (None, "", "unknown") and
                    not _g9_model_is_direct_openai(row.get("resolved_model"))):
                failures.append("rollback_resolved_model_mismatch")
            if row.get("fallback") is True:
                failures.append("rollback_unexpected_fallback")
    else:
        problems.append("unknown_g9_scenario")
    return {"status": "FAIL" if failures else "BLOCKED" if problems else "PASS",
            "problems": sorted(set(problems)), "failures": sorted(set(failures)),
            "response_count": len(responses), "transport_error_count": len(errors),
            "requested_models": sorted({row.get("requested_model") for row in responses}),
            "resolved_models": sorted({row.get("resolved_model") for row in responses}),
            "providers": sorted({row.get("provider") for row in responses})}


def _g9_lifecycle_evaluation(run_dir: Path, artifacts: Dict[str, Any],
                             profile: Dict[str, Any], run_id: str) -> Dict[str, Any]:
    reference = artifacts.get("server_lifecycle")
    path, error = _bundle_file(Path(run_dir), reference)
    if error or path is None:
        return {"status": "BLOCKED", "problems": ["server_lifecycle:%s" % (error or "missing")],
                "failures": [], "events": []}
    raw, read_error = _safe_read_bytes(path, Path(run_dir))
    if read_error or raw is None:
        return {"status": "BLOCKED", "problems": ["server_lifecycle:%s" % (read_error or "missing")],
                "failures": [], "events": []}
    events: List[Dict[str, Any]] = []
    problems: List[str] = []
    failures: List[str] = []
    try:
        for index, line in enumerate(raw.decode("ascii").splitlines(), 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError("not_object")
            events.append(value)
    except (UnicodeError, ValueError):
        return {"status": "BLOCKED", "problems": ["server_lifecycle:malformed"],
                "failures": [], "events": []}
    if not events:
        return {"status": "BLOCKED", "problems": ["server_lifecycle:empty"],
                "failures": [], "events": []}
    row_key = profile.get("row_key")
    for event in events:
        if event.get("row_key") != row_key or event.get("run_id") != run_id:
            failures.append("server_lifecycle:identity_mismatch")
            break
        if event.get("gate") != "g9" or event.get("party_size") != profile.get("party_size"):
            failures.append("server_lifecycle:gate_or_party_mismatch")
            break
    scenario = profile.get("scenario_id")
    rollback = scenario == "preferred-openai-rollback"
    expected_types = (["prepare", "server_started", "server_stopped", "rollback_configured",
                       "server_started", "capture_completed", "server_stopped"] if rollback else
                      ["prepare", "server_started", "capture_completed", "server_stopped"])
    observed_types = [event.get("event") for event in events]
    if len(events) < len(expected_types):
        problems.append("server_lifecycle:required_event_missing")
    elif len(events) > len(expected_types):
        failures.append("server_lifecycle:duplicate_or_extra_event")
    if (observed_types != expected_types and not
            (len(observed_types) < len(expected_types) and
             observed_types == expected_types[:len(observed_types)])):
        failures.append("server_lifecycle:event_order_or_restart_count_mismatch")

    started = [event for event in events if event.get("event") == "server_started"]
    stopped = [event for event in events if event.get("event") == "server_stopped"]
    expected_postures = ["openrouter", "openai"] if rollback else ["openrouter"]
    if len(started) != len(expected_postures):
        if len(started) < len(expected_postures):
            problems.append("server_lifecycle:server_start_evidence_missing")
        else:
            failures.append("server_lifecycle:unexpected_server_restart_count")
    for index, event in enumerate(started[:len(expected_postures)]):
        posture = event.get("posture")
        if posture != expected_postures[index]:
            failures.append("server_lifecycle:server_posture_mismatch")
        expected_log = ("server_before_rollback.log" if rollback and index == 0 else
                        "server.log")
        if event.get("server_log_artifact") is None:
            problems.append("server_lifecycle:server_log_binding_missing")
        elif event.get("server_log_artifact") != expected_log:
            failures.append("server_lifecycle:server_log_binding_mismatch")
        pid = event.get("server_pid")
        listeners = event.get("listener_pids")
        listener_processes = event.get("listener_processes")
        if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
            problems.append("server_lifecycle:server_ownership_fields_missing")
        if not isinstance(listeners, list) or not listeners:
            problems.append("server_lifecycle:listener_pids_missing")
            listener_pids_valid = False
        else:
            listener_pids_valid = all(
                isinstance(item, int) and not isinstance(item, bool) and item > 0
                for item in listeners
            )
            if not listener_pids_valid:
                failures.append("server_lifecycle:listener_pid_invalid")
            elif len(set(listeners)) != len(listeners):
                failures.append("server_lifecycle:duplicate_listener_pid")
        if not isinstance(listener_processes, list) or not listener_processes:
            problems.append("server_lifecycle:listener_process_evidence_missing")
        else:
            expected_cwd = str((PROJECT_TMP / "combat_capture").resolve())
            process_pids: List[int] = []
            for process in listener_processes:
                if not isinstance(process, dict):
                    failures.append("server_lifecycle:listener_process_invalid")
                    continue
                listener_pid = process.get("pid")
                ancestry = process.get("ancestry_pids")
                if (not isinstance(listener_pid, int) or isinstance(listener_pid, bool) or
                        listener_pid <= 0):
                    failures.append("server_lifecycle:listener_pid_invalid")
                    continue
                process_pids.append(listener_pid)
                if not isinstance(ancestry, list) or not ancestry:
                    problems.append("server_lifecycle:listener_ancestry_missing")
                elif any(not isinstance(item, int) or isinstance(item, bool) or item <= 0
                         for item in ancestry):
                    failures.append("server_lifecycle:listener_ancestry_invalid")
                elif len(set(ancestry)) != len(ancestry):
                    failures.append("server_lifecycle:listener_ancestry_cycle")
                elif ancestry[0] != listener_pid or ancestry[-1] != pid:
                    failures.append("server_lifecycle:listener_ancestry_not_owned")
                elif listener_pid == pid and ancestry != [pid]:
                    failures.append("server_lifecycle:listener_same_pid_ancestry_mismatch")
                elif listener_pid != pid and len(ancestry) < 2:
                    failures.append("server_lifecycle:listener_ancestry_incomplete")
                if (process.get("port") != 8360 or
                        process.get("cwd") != expected_cwd):
                    failures.append("server_lifecycle:listener_port_or_cwd_mismatch")
            if len(set(process_pids)) != len(process_pids):
                failures.append("server_lifecycle:duplicate_listener_process")
            if listener_pids_valid and set(process_pids) != set(listeners):
                failures.append("server_lifecycle:listener_process_set_mismatch")
        if (event.get("port") != 8360 or
                event.get("cwd") != str((PROJECT_TMP / "combat_capture").resolve()) or
                event.get("ownership") != "lsof_parent_pid_and_cwd"):
            failures.append("server_lifecycle:server_ownership_assertion_failed")
    if len(stopped) != len(started):
        if len(stopped) < len(started):
            problems.append("server_lifecycle:server_stop_evidence_missing")
        else:
            failures.append("server_lifecycle:duplicate_server_stop")
    for index, event in enumerate(stopped):
        expected_log = ("server_before_rollback.log" if rollback and index == 0 else
                        "server.log")
        if event.get("server_log_artifact") is None:
            problems.append("server_lifecycle:server_stop_log_binding_missing")
        if (index >= len(started) or event.get("server_pid") != started[index].get("server_pid") or
                (event.get("server_log_artifact") is not None and
                 event.get("server_log_artifact") != expected_log) or
                event.get("port") != 8360 or event.get("remaining_listener_pids") != []):
            failures.append("server_lifecycle:server_stop_assertion_failed")
        artifact_name = "rollback_server_log" if expected_log == "server_before_rollback.log" else "server_log"
        log_path, log_error = _bundle_file(run_dir, artifacts.get(artifact_name))
        if log_error or log_path is None:
            problems.append("server_lifecycle:stopped_server_log_missing")
        else:
            log_raw, log_read_error = _safe_read_bytes(log_path, Path(run_dir))
            if log_read_error or log_raw is None:
                problems.append("server_lifecycle:stopped_server_log_unreadable")
            elif (event.get("server_log_sha256") is None or
                  event.get("server_log_bytes") is None):
                problems.append("server_lifecycle:stopped_server_log_digest_missing")
            elif (event.get("server_log_sha256") != hashlib.sha256(log_raw).hexdigest() or
                  event.get("server_log_bytes") != len(log_raw)):
                failures.append("server_lifecycle:stopped_server_log_digest_mismatch")
    prepare_events = [event for event in events if event.get("event") == "prepare"]
    if not prepare_events:
        problems.append("server_lifecycle:prepare_event_missing")
    elif len(prepare_events) > 1:
        failures.append("server_lifecycle:prepare_count_mismatch")
    capture_events = [event for event in events if event.get("event") == "capture_completed"]
    if not capture_events:
        problems.append("server_lifecycle:capture_completion_missing")
    elif len(capture_events) > 1:
        failures.append("server_lifecycle:duplicate_capture_completion")
    elif capture_events[0].get("driver_exit_status") != 0:
        failures.append("server_lifecycle:driver_failed")
    rollback_events = [event for event in events if event.get("event") == "rollback_configured"]
    if rollback:
        if not rollback_events:
            problems.append("server_lifecycle:rollback_event_missing")
        elif len(rollback_events) > 1:
            failures.append("server_lifecycle:duplicate_rollback_event")
        elif (rollback_events[0].get("provider") != "openai" or
              rollback_events[0].get("model") != "gpt-6-luna" or
              rollback_events[0].get("reseed_after_rollback") is not False):
            failures.append("server_lifecycle:rollback_posture_assertion_failed")
        if artifacts.get("rollback_server_log") is None:
            problems.append("rollback_server_log:missing")
        elif artifacts.get("rollback_server_log") != "server_before_rollback.log":
            failures.append("rollback_server_log:unexpected_artifact_binding")
        if artifacts.get("server_log") is None:
            problems.append("server_log:missing")
        elif artifacts.get("server_log") != "server.log":
            failures.append("server_log:unexpected_artifact_binding")
    elif rollback_events or artifacts.get("rollback_server_log") is not None:
        failures.append("server_lifecycle:unexpected_rollback_evidence")
    elif artifacts.get("server_log") is None:
        problems.append("server_log:missing")
    elif artifacts.get("server_log") != "server.log":
        failures.append("server_log:unexpected_artifact_binding")
    return {"status": "FAIL" if failures else "BLOCKED" if problems else "PASS",
            "problems": sorted(set(problems)), "failures": sorted(set(failures)),
            "events": events, "restart_count": max(0, len(started) - 1)}


def _g9_config_assertions(profile: Dict[str, Any], configuration: Dict[str, Any],
                          g9_metadata: Dict[str, Any], run_dir: Path) -> Dict[str, List[str]]:
    problems: List[str] = []
    failures: List[str] = []
    if not isinstance(configuration, dict):
        configuration = {}
    if not isinstance(g9_metadata, dict):
        g9_metadata = {}
    runtime = configuration.get("g9_runtime")
    marker = g9_metadata.get("sandbox_marker")
    expected = profile.get("g9_runtime", {})
    for label, value in (("runtime", runtime), ("marker", marker)):
        if not isinstance(value, dict) or value.get("status") != "ok":
            problems.append("g9_%s_identity_missing" % label)
            continue
    if isinstance(runtime, dict) and runtime.get("status") == "ok":
        if (runtime.get("configured_provider") != expected.get("configured_provider") or
                runtime.get("active_profile") != "production-auto" or
                runtime.get("configured_model") != "gpt-6-luna" or
                runtime.get("openai_fallback_model") != "gpt-6-luna" or
                runtime.get("transport_fault_injection_enabled") is not
                expected.get("transport_failure_injection")):
            failures.append("g9_sandbox_runtime_configuration_mismatch")
        if (runtime.get("provenance") != "sandbox model_config.py AST literals" or
                not isinstance(runtime.get("model_config_sha256"), str) or
                not re.fullmatch(r"[0-9a-f]{64}", runtime.get("model_config_sha256", ""))):
            problems.append("g9_sandbox_runtime_provenance_invalid")
    if isinstance(marker, dict) and marker.get("status") == "ok":
        expected_state = "configured" if profile.get("phase") == "rollback" else "not_required"
        expected_count = 1 if profile.get("phase") == "rollback" else 0
        if (marker.get("gate") != "g9" or marker.get("row_key") != profile.get("row_key") or
                marker.get("scenario_id") != profile.get("scenario_id") or
                marker.get("party_size") != profile.get("party_size") or
                marker.get("run_dir") != str(Path(run_dir).resolve().relative_to(PROJECT_ROOT)) or
                marker.get("initial_provider") != "openrouter" or
                marker.get("active_profile") != "production-auto" or
                marker.get("transport_failure_injection") is not
                expected.get("transport_failure_injection") or
                marker.get("rollback_state") != expected_state or
                marker.get("operator_restart_count_required") != expected_count or
                marker.get("reseed_after_rollback") is not False):
            failures.append("g9_sandbox_marker_mismatch")
        if (not isinstance(marker.get("sha256"), str) or
                not re.fullmatch(r"[0-9a-f]{64}", marker.get("sha256", "")) or
                marker.get("provenance") != "sandbox .g9-capture.json"):
            problems.append("g9_sandbox_marker_provenance_invalid")
        if profile.get("phase") == "rollback" and (
                marker.get("rollback_provider") != "openai" or
                marker.get("rollback_model") != "gpt-6-luna"):
            failures.append("g9_rollback_marker_posture_mismatch")
    return {"problems": problems, "failures": failures}


def _g9_narrator_state_contract(
    profile: Dict[str, Any], before: Any, after: Any,
    steps: List[Dict[str, Any]], transcript: str,
    step_errors: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Apply the G4 narrator's persisted route/actor/dialogue contract to G9."""
    expected_roster = (["Acheron"] if profile.get("party_size") == 1 else
                       ["Acheron", "Merisiel", "Kira", "Vitreol"])
    turns = profile.get("turns")
    combat_problems: List[str] = []
    combat_failures: List[str] = []
    identity_problems: List[str] = []
    identity_failures: List[str] = []
    route_problems: List[str] = []
    route_failures: List[str] = []
    dialogue_problems: List[str] = []
    dialogue_failures: List[str] = []
    projections: List[Dict[str, Any]] = []

    if not isinstance(turns, list) or len(turns) != 5:
        route_problems.append("g9_narrator_turn_profile_missing")
        turns = turns if isinstance(turns, list) else []
    start_location = (profile.get("seed", {}).get("starting_location_id")
                      if isinstance(profile.get("seed"), dict) else None)
    if not isinstance(start_location, str) or not start_location:
        route_problems.append("g9_narrator_start_location_missing")
        start_location = "CA01"

    def inspect_snapshot(label: str, snapshot: Any, expected_location: str,
                         expected_actor: str) -> Dict[str, Any]:
        if not isinstance(snapshot, dict):
            identity_problems.append("g9_narrator_snapshot_missing:%s" % label)
            route_problems.append("g9_narrator_location_snapshot_missing:%s" % label)
            combat_problems.append("g9_narrator_combat_state_missing:%s" % label)
            return {"status": "BLOCKED", "expected_location_id": expected_location,
                    "observed": {}}
        records = snapshot.get("records")
        if not isinstance(records, dict):
            identity_problems.append("g9_narrator_snapshot_records_missing:%s" % label)
            records = {}
        party_state = records.get("party_tracker.json")
        party_state = party_state if isinstance(party_state, dict) else {}
        world = party_state.get("worldConditions")
        if party_state.get("status") != "ok":
            identity_problems.append("g9_narrator_party_state_missing:%s" % label)
        elif party_state.get("partyMembers") != expected_roster:
            identity_failures.append("g9_narrator_party_roster_mismatch:%s" % label)
        if party_state.get("active_character") is None:
            identity_problems.append("g9_narrator_active_actor_missing:%s" % label)
        elif party_state.get("active_character") != expected_actor:
            identity_failures.append("g9_narrator_active_actor_mismatch:%s" % label)

        if not isinstance(world, dict) or "activeCombatEncounter" not in world:
            combat_problems.append("g9_narrator_combat_state_missing:%s" % label)
        elif world.get("activeCombatEncounter") not in (None, ""):
            combat_failures.append("g9_narrator_active_combat_present:%s" % label)
        encounter = records.get("selected_encounter")
        encounter = encounter if isinstance(encounter, dict) else {}
        if (encounter.get("status") == "missing_id" and
                encounter.get("encounterId") in (None, "")):
            pass
        elif encounter.get("status") == "ok" or encounter.get("encounterId") not in (None, ""):
            combat_failures.append("g9_narrator_selected_encounter_present:%s" % label)
        else:
            combat_problems.append("g9_narrator_encounter_absence_unproven:%s" % label)

        for name in expected_roster:
            key = "characters/%s.json" % name.lower().replace(" ", "_")
            character = records.get(key)
            if not isinstance(character, dict) or character.get("read_status") != "ok":
                identity_problems.append("g9_narrator_character_state_missing:%s:%s" % (label, key))
            elif character.get("name") != name:
                identity_failures.append("g9_narrator_character_identity_mismatch:%s:%s" % (label, key))
        for name in ("modules/conversation_history", "save_games"):
            if not isinstance(records.get(name), list):
                identity_problems.append("g9_narrator_history_or_save_state_missing:%s:%s" % (label, name))

        projection = snapshot.get("g4_read_only_projection")
        projection = projection if isinstance(projection, dict) else {}
        if (not isinstance(world, dict) or not isinstance(world.get("currentLocationId"), str) or
                not world.get("currentLocationId") or
                not isinstance(projection.get("currentLocation"), str) or
                not projection.get("currentLocation") or
                not isinstance(projection.get("currentLocationId"), str)):
            route_problems.append("g9_narrator_persisted_location_missing:%s" % label)
        elif (world.get("currentLocationId") != expected_location or
              projection.get("currentLocationId") != expected_location or
              projection.get("partyMembers") != expected_roster or
              projection.get("active_character") != expected_actor):
            route_failures.append("g9_narrator_persisted_location_or_actor_mismatch:%s" % label)
        if (not isinstance(world, dict) or
                world.get("currentLocationId") != expected_location):
            if isinstance(world, dict) and world.get("currentLocationId") is not None:
                route_failures.append("g9_narrator_world_location_mismatch:%s" % label)
            elif not isinstance(world, dict) or "currentLocationId" not in world:
                route_problems.append("g9_narrator_world_location_missing:%s" % label)

        return g4_location_projection(snapshot, expected_location, expected_roster, expected_actor)

    first_actor = turns[0].get("character") if turns and isinstance(turns[0], dict) else ""
    last_turn = turns[-1] if turns and isinstance(turns[-1], dict) else {}
    before_projection = inspect_snapshot("before-run", before, start_location, first_actor)
    final_location = last_turn.get("expected_location_id", start_location)
    final_actor = last_turn.get("character", first_actor)
    inspect_snapshot("after-run", after, final_location, final_actor)

    transcript_steps = _g4_transcript_counts(transcript).get("steps", [])
    previous_location = start_location
    mira_outputs: List[Dict[str, Any]] = []
    mira_input = ""
    mira_step_missing = False
    missing_step_numbers = set()
    for error in step_errors or []:
        match = re.match(r"snapshots/step-(\d+)-(?:before|after)\.json:", str(error))
        if match:
            missing_step_numbers.add(int(match.group(1)))
    available_step_numbers = [number for number in range(1, len(turns) + 1)
                              if number not in missing_step_numbers]
    steps_by_number = {number: row for number, row in zip(available_step_numbers, steps)}
    mira_indexes = [index for index, turn in enumerate(turns)
                    if isinstance(turn, dict) and turn.get("kind") == "mira_dialogue"]
    if len(mira_indexes) != 1:
        dialogue_problems.append("g9_narrator_mira_turn_missing_or_ambiguous")

    for index, turn in enumerate(turns):
        if not isinstance(turn, dict):
            route_problems.append("g9_narrator_turn_identity_missing:%d" % (index + 1))
            continue
        step_number = index + 1
        actor = turn.get("character")
        utterance = turn.get("input")
        expected_location = turn.get("expected_location_id")
        if (not isinstance(actor, str) or not actor or not isinstance(utterance, str) or
                not utterance or not isinstance(expected_location, str) or not expected_location):
            route_problems.append("g9_narrator_turn_identity_invalid:%d" % step_number)
            continue
        if step_number not in steps_by_number:
            route_problems.append("g9_narrator_step_snapshot_missing:%d" % step_number)
            before_step = after_step = None
        else:
            before_step = steps_by_number[step_number].get("before")
            after_step = steps_by_number[step_number].get("after")
        if not isinstance(before_step, dict) or not isinstance(after_step, dict):
            if index in mira_indexes:
                mira_input = utterance
                mira_outputs = []
                mira_step_missing = True
            projections.append({
                "step": step_number, "label": turn.get("label"),
                "expected_location_id": expected_location,
                "expected_active_character": actor,
                "projection": {"status": "BLOCKED", "expected_location_id": expected_location,
                               "expected_roster": expected_roster,
                               "expected_active_character": actor, "observed": {}},
                "kind": turn.get("kind"), "actual_backend_outputs": [], "input_echoes": [],
            })
            continue
        inspect_snapshot("step-%03d-before" % step_number, before_step,
                         previous_location, actor)
        step_projection = inspect_snapshot("step-%03d-after" % step_number, after_step,
                                           expected_location, actor)
        previous_location = expected_location
        before_observation = (before_step.get("observation", {})
                              if isinstance(before_step, dict) else {})
        after_observation = (after_step.get("observation", {})
                             if isinstance(after_step, dict) else {})
        if (before_observation.get("character") is None or
                before_observation.get("input") is None):
            route_problems.append("g9_narrator_step_input_or_actor_missing:%d" % step_number)
        elif (before_observation.get("character") != actor or
              before_observation.get("input") != utterance):
            route_failures.append("g9_narrator_step_input_or_actor_mismatch:%d" % step_number)
        if (after_observation.get("character") is not None and
                after_observation.get("character") != actor):
            route_failures.append("g9_narrator_after_step_actor_mismatch:%d" % step_number)
        if (after_observation.get("input") is not None and
                after_observation.get("input") != utterance):
            route_failures.append("g9_narrator_after_step_input_mismatch:%d" % step_number)
        if (after_observation.get("label") is not None and
                after_observation.get("label") != turn.get("label")):
            route_failures.append("g9_narrator_step_label_mismatch:%d" % step_number)

        transcript_row = next((row for row in transcript_steps
                               if isinstance(row, dict) and row.get("step") == step_number), None)
        if transcript_row is None:
            route_problems.append("g9_narrator_transcript_step_missing:%d" % step_number)
        elif (transcript_row.get("character") != actor or
              transcript_row.get("input") != utterance):
            route_failures.append("g9_narrator_transcript_step_identity_mismatch:%d" % step_number)

        outputs = after_observation.get("actual_backend_outputs")
        echoes = after_observation.get("input_echoes")
        if not isinstance(outputs, list):
            dialogue_problems.append("g9_narrator_backend_output_missing:%d" % step_number)
            outputs = []
        if not isinstance(echoes, list):
            dialogue_problems.append("g9_narrator_input_echo_missing:%d" % step_number)
            echoes = []
        projection = {
            "step": step_number,
            "label": turn.get("label"),
            "expected_location_id": expected_location,
            "expected_active_character": actor,
            "projection": step_projection,
            "kind": turn.get("kind"),
            "actual_backend_outputs": outputs,
            "input_echoes": echoes,
        }
        projections.append(projection)

        if (len(echoes) != 1 or not isinstance(echoes[0], dict) or
                echoes[0].get("type") not in ("user-input", "user_input") or
                echoes[0].get("content") != utterance):
            dialogue_failures.append("g9_narrator_input_echo_transcript_mismatch:%d" % step_number)
        elif not transcript:
            dialogue_problems.append("g9_narrator_input_echo_transcript_missing:%d" % step_number)
        elif not _transcript_has_user_input(transcript, actor, utterance):
            dialogue_failures.append("g9_narrator_input_echo_transcript_mismatch:%d" % step_number)
        for output in outputs:
            if (not isinstance(output, dict) or not isinstance(output.get("content"), str) or
                    not output.get("content", "").strip()):
                dialogue_problems.append("g9_narrator_backend_output_invalid:%d" % step_number)
            elif not transcript:
                dialogue_problems.append("g9_narrator_backend_output_transcript_missing:%d" % step_number)
            elif output.get("content") not in transcript:
                dialogue_failures.append("g9_narrator_backend_output_transcript_mismatch:%d" % step_number)
        if index in mira_indexes:
            mira_input = utterance
            mira_outputs = outputs
            mira_step_missing = not isinstance(after_step, dict)

    if len(steps) != len(turns):
        route_problems.append("g9_narrator_step_count_mismatch")
    non_echo_mira_outputs = [
        output for output in mira_outputs
        if (
        isinstance(output, dict) and isinstance(output.get("content"), str) and
        output.get("content", "").strip() and
        output.get("content", "").strip().casefold() != mira_input.strip().casefold() and
        str(output.get("type", "")).casefold() not in
        ("user-input", "user_input", "echo", "system", "startup")
        )
    ]
    if len(mira_indexes) == 1:
        if not non_echo_mira_outputs:
            if mira_step_missing:
                dialogue_problems.append("g9_narrator_mira_backend_response_missing")
            else:
                dialogue_failures.append("g9_narrator_mira_backend_reply_missing_or_echo_only")
        elif not transcript:
            dialogue_problems.append("g9_narrator_mira_transcript_missing")
        elif not any(output.get("content", "") in transcript for output in non_echo_mira_outputs):
            dialogue_failures.append("g9_narrator_mira_backend_transcript_mismatch")

    categories = (
        ("combat", combat_problems, combat_failures,
         "g9_narrator_no_active_combat", "active combat and selected encounter are absent"),
        ("identity", identity_problems, identity_failures,
         "g9_narrator_party_actor_identity", "persisted party and character identities match the profile"),
        ("route", route_problems, route_failures,
         "g9_narrator_persisted_locations", "each G4 narrator step persists its expected location and actor"),
        ("dialogue", dialogue_problems, dialogue_failures,
         "g9_narrator_real_dialogue", "input echoes are distinct from transcript-backed backend dialogue"),
    )
    checks = []
    all_problems: List[str] = []
    all_failures: List[str] = []
    for _category, category_problems, category_failures, check_id, expected in categories:
        all_problems.extend(category_problems)
        all_failures.extend(category_failures)
        status = ("FAIL" if category_failures else
                  "BLOCKED" if category_problems else "PASS")
        checks.append({"id": check_id, "required": True, "expected": expected,
                       "observed": {"problem_count": len(category_problems),
                                    "failure_count": len(category_failures)},
                       "status": status, "evidence": "retained G9 snapshots and transcript"})
    return {"problems": sorted(set(all_problems)), "failures": sorted(set(all_failures)),
            "checks": checks, "projections": projections,
            "startup_projection": before_projection}


def evaluate_g9_bundle(manifest: Dict[str, Any], artifacts: Dict[str, Any],
                       run_dir: Path) -> Dict[str, Any]:
    """Revalidate one G9 candidate bundle from retained bytes and response receipts."""
    run_dir = Path(run_dir)
    scenario = manifest.get("scenario") if isinstance(manifest.get("scenario"), dict) else {}
    party = manifest.get("party") if isinstance(manifest.get("party"), dict) else {}
    scenario_id = scenario.get("id")
    party_size = party.get("size")
    phase = scenario.get("phase")
    row_key = None
    problems: List[str] = []
    failures: List[str] = []
    try:
        from scripts import combat_latency_fixtures

        profile = combat_latency_fixtures.build_gate_profile(
            "g9", scenario_id, party_size, phase=phase or ""
        )
        row_key = profile["row_key"]
    except (KeyError, TypeError, ValueError):
        return {"automated_status": "BLOCKED", "primary_verdict": "PENDING",
                "matrix_key": None, "problems": ["invalid_g9_profile"], "failures": []}
    integrity = _artifact_integrity(run_dir, manifest, artifacts)
    loaded = integrity.get("loaded", {})
    g9_metadata = manifest.get("g9")
    if not isinstance(g9_metadata, dict):
        g9_metadata = {}
    configuration = manifest.get("configuration")
    if not isinstance(configuration, dict):
        configuration = {}
    seed_identity = manifest.get("seed")
    if not isinstance(seed_identity, dict):
        seed_identity = {}
    sandbox_runtime = manifest.get("sandbox_runtime")
    if not isinstance(sandbox_runtime, dict):
        sandbox_runtime = {}
    transport = manifest.get("transport")
    if not isinstance(transport, dict):
        transport = {}
    snapshot_chain = manifest.get("snapshot_chain")
    if not isinstance(snapshot_chain, dict):
        snapshot_chain = {}
    if (manifest.get("gate") != "g9" or manifest.get("run_id") != run_dir.name or
            artifacts.get("matrix_keys") != [row_key] or
            g9_metadata.get("row_key") != row_key):
        problems.append("g9_row_or_run_identity_mismatch")
    contract = {key: profile.get(key) for key in
                ("scenario_id", "party_size", "branch", "phase", "seed", "applicability")}
    contract.update({"gate": "g9", "row_key": profile.get("row_key"),
                     "seed_scenario_id": profile.get("seed_scenario_id"),
                     "capture_kind": profile.get("capture_kind"),
                     "g9_runtime": profile.get("g9_runtime")})
    if (scenario.get("profile_contract") != contract or
            scenario.get("sha256") != hashlib.sha256(
                json.dumps(contract, sort_keys=True).encode("utf-8")).hexdigest()):
        problems.append("g9_profile_contract_mismatch")
    expected_seed = dict(profile.get("seed", {}))
    expected_seed.pop("resume_phase", None)
    seed_hash = hashlib.sha256(json.dumps(expected_seed, sort_keys=True).encode("utf-8")).hexdigest()
    if (seed_identity.get("profile_seed") != expected_seed or
            seed_identity.get("seed_profile_sha256") != seed_hash or
            seed_identity.get("seed_id") != seed_hash):
        problems.append("g9_seed_profile_mismatch")

    before, after = loaded.get("before_snapshot"), loaded.get("after_snapshot")
    expected_names = ["Acheron"] if party_size == 1 else ["Acheron", "Merisiel", "Kira", "Vitreol"]
    narrator_row = profile.get("capture_kind") == "narrator"
    before_records = before.get("records", {}) if isinstance(before, dict) else {}
    after_records = after.get("records", {}) if isinstance(after, dict) else {}
    for label, snapshot, records in (("before", before, before_records), ("after", after, after_records)):
        party_state = records.get("party_tracker.json", {})
        encounter = records.get("selected_encounter", {})
        if (not isinstance(snapshot, dict) or _snapshot_required_errors(snapshot, manifest) or
                snapshot.get("numeric_errors") != []):
            problems.append("g9_%s_snapshot_incomplete" % label)
        party_state_valid = (party_state.get("status") == "ok" and
                             party_state.get("partyMembers") == expected_names)
        encounter_valid = (
            encounter.get("status") == "missing_id" and encounter.get("encounterId") in (None, "")
        ) if narrator_row else (
            encounter.get("status") == "ok" and bool(encounter.get("encounterId"))
        )
        if not party_state_valid or not encounter_valid:
            problems.append("g9_%s_party_or_encounter_state_missing" % label)
        for name in expected_names:
            key = "characters/%s.json" % name.lower().replace(" ", "_")
            if records.get(key, {}).get("read_status") != "ok":
                problems.append("g9_%s_character_state_missing:%s" % (label, key))
        if not isinstance(records.get("modules/conversation_history"), list) or not isinstance(
                records.get("save_games"), list):
            problems.append("g9_%s_history_or_save_state_missing" % label)
    if isinstance(before, dict) and isinstance(after, dict):
        before_party = before_records.get("party_tracker.json", {})
        before_encounter = before_records.get("selected_encounter", {})
        seed_encounter = manifest.get("seed", {}).get("active_encounter")
        before_active_encounter = ((before_party.get("worldConditions") or {}).get("activeCombatEncounter")
                                   if isinstance(before_party.get("worldConditions"), dict) else None)
        encounter_identity_valid = (
            seed_encounter in (None, "") and before_active_encounter in (None, "") and
            before_encounter.get("status") == "missing_id" and
            before_encounter.get("encounterId") in (None, "")
        ) if narrator_row else (
            seed_encounter == before_encounter.get("encounterId") and
            before_encounter.get("status") == "ok"
        )
        if (party.get("roster") != before_party.get("partyMembers") or
                manifest.get("seed", {}).get("roster") != before_party.get("partyMembers") or
                not encounter_identity_valid or
                after_records.get("party_tracker.json", {}).get("partyMembers") != expected_names):
            problems.append("g9_party_seed_snapshot_identity_mismatch")
        if (snapshot_chain.get("before_run_sha256") != snapshot_digest(before) or
                snapshot_chain.get("after_run_sha256") != snapshot_digest(after)):
            problems.append("g9_snapshot_chain_digest_mismatch")

    runtime_config = _g9_config_assertions(
        profile, configuration, g9_metadata, run_dir
    )
    problems.extend(runtime_config["problems"])
    failures.extend(runtime_config["failures"])
    source_identity = manifest.get("source")
    if not isinstance(source_identity, dict):
        source_identity = {}
    worktree = g9_metadata.get("worktree_identity", {})
    source_hashes = source_identity.get("relevant_source_sha256", {})
    source_digest = hashlib.sha256(json.dumps(
        source_hashes if isinstance(source_hashes, dict) else {}, sort_keys=True
    ).encode("utf-8")).hexdigest()
    if (not isinstance(worktree, dict) or worktree.get("status") != "ok" or
            not isinstance(worktree.get("root"), str) or not worktree.get("root") or
            worktree.get("provenance") != "git HEAD and relevant source identity"):
        problems.append("g9_worktree_identity_missing")
    elif (worktree.get("root") != str(PROJECT_ROOT.resolve()) or
          worktree.get("head") != source_identity.get("head") or
          worktree.get("relevant_dirty_sha256") != source_identity.get("relevant_dirty_sha256") or
          worktree.get("relevant_source_sha256") != source_digest):
        failures.append("g9_worktree_identity_mismatch")
    if sandbox_runtime.get("port") != 8360:
        problems.append("g9_sandbox_port_identity_missing")
    if transport.get("url") != "http://localhost:8360":
        failures.append("g9_capture_url_mismatch")

    trace_ref, trace_error = _bundle_file(run_dir, artifacts.get("trace"))
    if trace_error or trace_ref is None:
        receipt_projection = {"status": "BLOCKED", "reason": "trace_missing", "receipts": []}
        positioned = []
    else:
        offset = (manifest.get("trace_span") or {}).get("offset_before_bytes", 0)
        positioned, position_errors = parse_trace_positions(trace_ref, offset)
        if position_errors:
            problems.append("g9_trace_positions_invalid")
        receipt_projection = project_g9_receipts(positioned, manifest.get("run_id", ""))
    if receipt_projection.get("status") != "ok":
        problems.append("g9_response_receipts:%s" % receipt_projection.get("reason", "missing"))
    receipts = receipt_projection.get("receipts", [])
    if g9_metadata.get("response_receipts") != receipts:
        problems.append("g9_saved_response_receipts_mismatch")
    actual_runtime = configuration.get("actual_runtime", {})
    expected_runtime = _g9_runtime_summary(receipts, receipt_projection.get("status", "BLOCKED"))
    if actual_runtime != expected_runtime:
        problems.append("g9_actual_runtime_not_receipt_derived")
    assertions = _g9_runtime_assertions(profile, receipts)
    problems.extend(assertions["problems"])
    failures.extend(assertions["failures"])

    lifecycle = _g9_lifecycle_evaluation(run_dir, artifacts, profile, manifest.get("run_id", ""))
    problems.extend(lifecycle["problems"])
    failures.extend(lifecycle["failures"])
    lifecycle_metadata = g9_metadata.get("lifecycle", {})
    if not isinstance(lifecycle_metadata, dict):
        lifecycle_metadata = {}
    lifecycle_path, lifecycle_ref_error = _bundle_file(run_dir, artifacts.get("server_lifecycle"))
    if (lifecycle_ref_error or lifecycle_path is None or
            lifecycle_metadata.get("status") != "finalized" or
            lifecycle_metadata.get("artifact") != artifacts.get("server_lifecycle")):
        problems.append("g9_lifecycle_finalization_missing")
    else:
        lifecycle_bytes, lifecycle_bytes_error = _safe_read_bytes(lifecycle_path, run_dir)
        if (lifecycle_bytes_error or lifecycle_bytes is None or
                lifecycle_metadata.get("sha256") != hashlib.sha256(lifecycle_bytes).hexdigest()):
            problems.append("g9_lifecycle_digest_mismatch")
    for artifact_name in ("server_log", "rollback_server_log"):
        reference = artifacts.get(artifact_name)
        if reference is None:
            if artifact_name == "rollback_server_log" and not phase:
                continue
            if artifact_name == "rollback_server_log" and phase != "rollback":
                continue
            problems.append("%s:missing" % artifact_name)
            continue
        path, error = _bundle_file(run_dir, reference)
        if error or path is None:
            problems.append("%s:%s" % (artifact_name, error or "missing"))
        else:
            safe, reason = server_log_safety(path)
            if not safe:
                problems.append("%s:unsafe:%s" % (artifact_name, reason))

    if (manifest.get("evidence_kind") == "synthetic" or manifest.get("live_eligible") is not True or
            transport.get("client_source") != "socketio.Client"):
        problems.append("g9_synthetic_or_non_live_evidence")
    counts = manifest.get("counts", {})
    if not isinstance(counts, dict):
        counts = {}
    if not isinstance(counts.get("steps_sent"), int) or isinstance(counts.get("steps_sent"), bool) or counts.get("steps_sent", 0) < 1:
        problems.append("g9_transcript_step_evidence_missing")

    artifacts = dict(artifacts)
    report = loaded.get("report") if isinstance(loaded.get("report"), dict) else {}
    if artifacts.get("required_evidence_status") != report.get("status"):
        problems.append("g9_degraded_status_projection_mismatch")
    artifacts["required_evidence_status"] = report.get("status", "missing")
    step_rows, step_errors = load_step_snapshots(run_dir, manifest)
    observations, provider_events = trace_check_inputs(positioned)
    artifacts["trace_position_errors"] = []
    artifacts["trace_provider_events"] = provider_events
    checks = observed_checks(profile, before, after or {}, artifacts, step_rows,
                             observations, run_dir=run_dir) if before and after else []
    if step_errors:
        checks.append({"id": "all_step_snapshots_readable", "required": True,
                       "expected": "complete before/after snapshot pair for each sent step",
                       "observed": step_errors, "status": "BLOCKED",
                       "evidence": "manifest artifact step refs"})
    saved_checks = loaded.get("checks")
    if (not isinstance(saved_checks, dict) or saved_checks.get("checks") != checks or
            saved_checks.get("primary_verdict") != "PENDING"):
        problems.append("g9_checks_not_derived_from_retained_state")
    evaluation_checks = list(checks)
    evaluation_profile = profile
    if narrator_row:
        transcript_path, transcript_error = _bundle_file(run_dir, artifacts.get("transcript"))
        if transcript_error or transcript_path is None:
            transcript_text = ""
            problems.append("g9_narrator_transcript_missing")
        else:
            transcript_raw, transcript_read_error = _safe_read_bytes(transcript_path, run_dir)
            if transcript_read_error or transcript_raw is None:
                transcript_text = ""
                problems.append("g9_narrator_transcript_unreadable")
            else:
                try:
                    transcript_text = transcript_raw.decode("utf-8")
                except UnicodeError:
                    transcript_text = ""
                    problems.append("g9_narrator_transcript_unreadable")
        narrator_contract = _g9_narrator_state_contract(
            profile, before, after, step_rows, transcript_text, step_errors
        )
        problems.extend(narrator_contract["problems"])
        failures.extend(narrator_contract["failures"])
        narrator_manifest = {
            "scenario": {"profile_contract": {"turns": profile.get("turns", [])}},
            "g4_step_projections": narrator_contract["projections"],
        }
        evaluation_checks = _g4_check_applicability(
            evaluation_checks, "narrator-dialogue-travel", narrator_manifest, step_rows
        )
        evaluation_checks.extend(narrator_contract["checks"])
        evaluation_profile = dict(profile)
        evaluation_profile["scenario_id"] = "narrator-dialogue-travel"
    base = evaluate_evidence(manifest, evaluation_checks, artifacts, run_dir=run_dir,
                             integrity=integrity, profile=evaluation_profile)
    if base.get("automated_status") == "FAIL":
        failures.extend("capture:%s" % item.get("id", "assertion")
                        for item in base.get("failed_required_checks", []))
        if not base.get("failed_required_checks"):
            failures.append("capture:observed_failure")
    elif base.get("automated_status") != "READY_FOR_PRIMARY_REVIEW":
        problems.extend("capture:%s" % reason for reason in base.get("problems", []))
    if integrity.get("failures"):
        problems.extend("integrity:%s" % reason for reason in integrity.get("failures", []))
    failures = sorted(set(failures))
    problems = sorted(set(problems))
    status = "FAIL" if failures else "BLOCKED" if problems else "READY_FOR_PRIMARY_REVIEW"
    return {"automated_status": status, "primary_verdict": "PENDING",
            "matrix_key": row_key, "failures": failures, "problems": problems,
            "integrity_failures": integrity.get("failures", []),
            "response_receipts": len(receipts), "runtime_assertions": assertions,
            "lifecycle": {key: lifecycle.get(key) for key in ("status", "restart_count")}}


def _evaluate_g9_run(run_dir: Path) -> Dict[str, Any]:
    manifest, error = load_bundle_json(run_dir, "manifest.json")
    if error or not isinstance(manifest, dict):
        return {"run_dir": str(run_dir), "error": "manifest:%s" % (error or "invalid")}
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict):
        return {"run_dir": str(run_dir), "manifest": manifest, "error": "artifacts_not_object"}
    evaluation = evaluate_g9_bundle(manifest, artifacts, run_dir)
    return {"run_dir": str(run_dir), "manifest": manifest,
            "matrix_key": evaluation.get("matrix_key"), "evaluation": evaluation}


def evaluate_g9_matrix(run_rows: Iterable[Any]) -> Dict[str, Any]:
    """Evaluate the fixed eight G9 candidates without making a live gate verdict."""
    from scripts import combat_latency_fixtures

    required = list(combat_latency_fixtures.required_g9_row_keys())
    invalid_runs: List[str] = []
    duplicate_keys: List[str] = []
    by_key: Dict[str, Dict[str, Any]] = {}
    for row in run_rows:
        try:
            candidate = Path(row.get("run_dir")) if isinstance(row, dict) and row.get("run_dir") else Path(row)
            if not candidate.is_absolute():
                candidate = PROJECT_ROOT / candidate
        except (TypeError, ValueError):
            invalid_runs.append("invalid_run_directory_input")
            continue
        if (not _inside(candidate, G9_RUN_ROOT) or candidate.resolve() == G9_RUN_ROOT.resolve() or
                _has_symlink_component(candidate, PROJECT_TMP)):
            invalid_runs.append("unsafe_run_directory:%s" % candidate.name)
            continue
        result = _evaluate_g9_run(candidate)
        key = result.get("matrix_key")
        if not isinstance(key, str) or key not in required:
            invalid_runs.append("%s:%s" % (candidate.name, result.get("error", "unknown_g9_row_key")))
            continue
        if key in by_key:
            duplicate_keys.append(key)
            continue
        by_key[key] = result
    missing = sorted(set(required) - set(by_key))
    extra = sorted(set(by_key) - set(required))
    failed = sorted(key for key, row in by_key.items()
                    if row.get("evaluation", {}).get("automated_status") == "FAIL")
    not_ready = sorted(key for key, row in by_key.items()
                       if row.get("evaluation", {}).get("automated_status") != "READY_FOR_PRIMARY_REVIEW")
    synthetic = sorted(key for key, row in by_key.items()
                       if (row.get("manifest") or {}).get("evidence_kind") == "synthetic" or
                       (row.get("manifest") or {}).get("live_eligible") is not True or
                       (row.get("manifest") or {}).get("transport", {}).get("client_source") != "socketio.Client")
    issues = bool(missing or extra or duplicate_keys or invalid_runs or failed or not_ready or synthetic)
    status = "FAIL" if failed else "BLOCKED" if issues else "READY_FOR_PRIMARY_REVIEW"
    return {
        "gate": "g9", "automated_status": status, "primary_verdict": "PENDING",
        "required_keys": required, "observed_keys": sorted(by_key),
        "missing_required_keys": missing, "extra_keys": extra,
        "duplicate_keys": sorted(set(duplicate_keys)), "not_ready_keys": not_ready,
        "failed_keys": failed, "synthetic_keys": synthetic,
        "invalid_run_bundles": invalid_runs,
        "runs": {key: {
            "automated_status": row.get("evaluation", {}).get("automated_status"),
            "failures": row.get("evaluation", {}).get("failures", []),
            "problems": row.get("evaluation", {}).get("problems", []),
            "response_receipts": row.get("evaluation", {}).get("response_receipts"),
        } for key, row in sorted(by_key.items())},
    }


def _g10_lifecycle_evaluation(run_dir: Path, artifacts: Dict[str, Any],
                              manifest: Dict[str, Any]) -> Dict[str, Any]:
    """Revalidate exact G10 owned-server starts, stops, and log bindings."""
    lifecycle_ref = artifacts.get("server_lifecycle")
    lifecycle_path, lifecycle_error = _bundle_file(run_dir, lifecycle_ref)
    server_path, server_error = _bundle_file(run_dir, artifacts.get("server_log"))
    problems: List[str] = []
    failures: List[str] = []
    if lifecycle_error or lifecycle_path is None:
        return {"status": "BLOCKED", "problems": ["g10_lifecycle_missing"],
                "failures": [], "events": [], "restart_count": None}
    if server_error or server_path is None:
        problems.append("g10_server_log_missing")
    else:
        safe, reason = server_log_safety(server_path)
        if not safe:
            problems.append("g10_server_log_unsafe:%s" % reason)
    g10_manifest = manifest.get("g10")
    lifecycle_meta = (g10_manifest.get("lifecycle", {})
                      if isinstance(g10_manifest, dict) else {})
    if not isinstance(lifecycle_meta, dict):
        lifecycle_meta = {}
    if (not isinstance(lifecycle_meta, dict) or
            lifecycle_meta.get("status") != "finalized" or
            lifecycle_meta.get("artifact") != lifecycle_ref):
        problems.append("g10_lifecycle_not_finalized")
    if (manifest.get("evidence_kind") != "live-candidate" or
            manifest.get("live_eligible") is not True):
        problems.append("g10_lifecycle_synthetic_or_ineligible_evidence")
    raw, read_error = _safe_read_bytes(lifecycle_path, run_dir)
    if read_error or raw is None:
        return {"status": "BLOCKED", "problems": sorted(set(problems + ["g10_lifecycle_unreadable"])),
                "failures": failures, "events": [], "restart_count": None}
    events: List[Dict[str, Any]] = []
    try:
        for line in raw.decode("ascii").splitlines():
            if line.strip():
                event = json.loads(line)
                if not isinstance(event, dict):
                    raise ValueError("not_object")
                events.append(event)
    except (UnicodeError, ValueError):
        return {"status": "BLOCKED", "problems": sorted(set(problems + ["g10_lifecycle_malformed"])),
                "failures": failures, "events": [], "restart_count": None}
    if lifecycle_meta.get("sha256") != hashlib.sha256(raw).hexdigest():
        failures.append("g10_lifecycle_digest_mismatch")

    scenario = manifest.get("scenario") if isinstance(manifest.get("scenario"), dict) else {}
    party = manifest.get("party") if isinstance(manifest.get("party"), dict) else {}
    g10 = manifest.get("g10") if isinstance(manifest.get("g10"), dict) else {}
    phase = scenario.get("phase")
    expected_events = ("prepare", "server_started", "capture_completed", "server_stopped") \
        if phase == "complete" else (
            "resume_server_started", "capture_completed", "server_stopped"
        ) if phase == "resume" else ()
    if not expected_events:
        failures.append("g10_lifecycle_phase_invalid")
    elif [event.get("event") for event in events] != list(expected_events):
        problems.append("g10_lifecycle_event_order_or_count_mismatch")
    source = manifest.get("source") if isinstance(manifest.get("source"), dict) else {}
    seed = manifest.get("seed") if isinstance(manifest.get("seed"), dict) else {}
    identity = {
        "gate": "g10", "row_key": g10.get("row_key"), "run_id": manifest.get("run_id"),
        "phase": phase, "party_size": party.get("size"),
        "chain_id": manifest.get("chain_id"), "seed_id": seed.get("seed_id"),
        "sandbox_id": manifest.get("sandbox_id"),
        "source_head": source.get("head"),
        "relevant_dirty_sha256": source.get("relevant_dirty_sha256"),
    }
    for required in ("row_key", "run_id", "chain_id", "seed_id", "sandbox_id",
                     "source_head", "relevant_dirty_sha256"):
        if not identity.get(required):
            problems.append("g10_lifecycle_identity_missing:%s" % required)
    for event in events:
        if any(event.get(key) != value for key, value in identity.items()):
            failures.append("g10_lifecycle_identity_mismatch")
            break

    expected_cwd = str((PROJECT_TMP / "combat_capture").resolve())
    start_name = "server_started" if phase == "complete" else "resume_server_started"
    starts = [event for event in events if event.get("event") == start_name]
    stops = [event for event in events if event.get("event") == "server_stopped"]
    if len(starts) != 1:
        problems.append("g10_owned_server_start_missing_or_duplicated")
    if len(stops) != 1:
        problems.append("g10_owned_server_stop_missing_or_duplicated")
    for started in starts:
        server_pid = started.get("server_pid")
        server_parent_pid = started.get("server_parent_pid")
        expected_server_parent_pid = started.get("expected_server_parent_pid")
        listener_pids = started.get("listener_pids")
        listener_processes = started.get("listener_processes")
        if (not isinstance(server_pid, int) or isinstance(server_pid, bool) or server_pid <= 0 or
                not isinstance(listener_pids, list) or not listener_pids or
                not isinstance(listener_processes, list) or not listener_processes):
            problems.append("g10_owned_server_process_identity_missing")
            continue
        if not _g10_usage_value_bounded(started.get("server_launch_epoch"), 10 ** 12):
            problems.append("g10_server_launch_timestamp_missing_or_invalid")
        valid_parent_identity = (
            isinstance(server_parent_pid, int) and not isinstance(server_parent_pid, bool) and
            server_parent_pid > 0 and
            isinstance(expected_server_parent_pid, int) and
            not isinstance(expected_server_parent_pid, bool) and
            expected_server_parent_pid > 0
        )
        if not valid_parent_identity:
            problems.append("g10_server_parent_identity_missing")
        elif server_parent_pid != expected_server_parent_pid:
            failures.append("g10_server_parent_identity_mismatch")
        elif server_parent_pid == server_pid:
            failures.append("g10_server_parent_identity_cycle")
        valid_listener_pids = all(
            isinstance(pid, int) and not isinstance(pid, bool) and pid > 0
            for pid in listener_pids
        )
        if not valid_listener_pids:
            failures.append("g10_listener_pid_invalid")
        elif len(set(listener_pids)) != len(listener_pids):
            failures.append("g10_listener_pid_duplicated")
        elif listener_pids != sorted(listener_pids):
            failures.append("g10_listener_pid_order_mismatch")
        process_pids = []
        observed_process_identities = {}
        for process in listener_processes:
            if not isinstance(process, dict):
                failures.append("g10_listener_process_invalid")
                continue
            pid = process.get("pid")
            ancestry = process.get("ancestry_pids")
            if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
                failures.append("g10_listener_process_pid_invalid")
                continue
            process_pids.append(pid)
            if not isinstance(ancestry, list) or not ancestry:
                problems.append("g10_listener_ancestry_missing")
            elif any(not isinstance(item, int) or isinstance(item, bool) or item <= 0
                     for item in ancestry):
                failures.append("g10_listener_ancestry_invalid")
            elif len(set(ancestry)) != len(ancestry):
                failures.append("g10_listener_ancestry_invalid")
            elif ancestry[0] != pid or ancestry[-1] != server_pid or (
                    pid == server_pid and ancestry != [pid]):
                failures.append("g10_listener_ancestry_not_owned")
            identities = process.get("process_identities")
            ancestry_valid = (
                isinstance(ancestry, list) and bool(ancestry) and
                all(isinstance(item, int) and not isinstance(item, bool) and item > 0
                    for item in ancestry) and
                len(set(ancestry)) == len(ancestry) and ancestry[0] == pid and
                ancestry[-1] == server_pid
            )
            if not ancestry_valid:
                if not isinstance(ancestry, list) or not ancestry:
                    problems.append("g10_listener_process_identities_missing")
            elif not isinstance(identities, list) or len(identities) != len(ancestry):
                problems.append("g10_listener_process_identities_missing")
            else:
                for identity_index, identity_record in enumerate(identities):
                    if not isinstance(identity_record, dict):
                        failures.append("g10_listener_process_identity_invalid")
                        continue
                    identity_pid = identity_record.get("pid")
                    parent_pid = identity_record.get("parent_pid")
                    start_sec = identity_record.get("start_time_sec")
                    start_usec = identity_record.get("start_time_usec")
                    if (not isinstance(identity_pid, int) or isinstance(identity_pid, bool) or
                            identity_pid != ancestry[identity_index] or
                            not isinstance(parent_pid, int) or isinstance(parent_pid, bool) or
                            parent_pid <= 0 or
                            not isinstance(start_sec, int) or isinstance(start_sec, bool) or
                            start_sec <= 0 or
                            not isinstance(start_usec, int) or isinstance(start_usec, bool) or
                            start_usec < 0 or start_usec >= 1000000):
                        failures.append("g10_listener_process_identity_invalid")
                        continue
                    expected_parent = (
                        ancestry[identity_index + 1]
                        if identity_index + 1 < len(ancestry) else server_parent_pid
                    )
                    if parent_pid != expected_parent:
                        failures.append("g10_listener_process_identity_ancestry_mismatch")
                    identity_tuple = (parent_pid, start_sec, start_usec)
                    previous_identity = observed_process_identities.get(identity_pid)
                    if previous_identity is not None and previous_identity != identity_tuple:
                        failures.append("g10_listener_process_identity_conflict")
                    observed_process_identities[identity_pid] = identity_tuple
            if process.get("port") != 8360 or process.get("cwd") != expected_cwd:
                failures.append("g10_listener_port_or_cwd_mismatch")
        if len(process_pids) != len(set(process_pids)):
            failures.append("g10_listener_process_duplicated")
        if set(process_pids) != set(listener_pids):
            failures.append("g10_listener_process_set_mismatch")
        elif process_pids != listener_pids:
            failures.append("g10_listener_process_order_mismatch")
        if (started.get("port") != 8360 or started.get("cwd") != expected_cwd or
                started.get("launcher_cwd") != expected_cwd or
                started.get("server_log_artifact") != "server.log"):
            failures.append("g10_owned_server_assertion_failed")
        if started.get("ownership") != G10_OWNERSHIP_METHOD:
            failures.append("g10_native_ownership_method_missing")
        if started.get("listener_source") != G10_LISTENER_SOURCE:
            failures.append("g10_listener_source_unverified")
        if started.get("listener_set_validation") != G10_LISTENER_SET_VALIDATION:
            failures.append("g10_listener_set_proof_incomplete")
        if started.get("process_identity_validation") != G10_PROCESS_IDENTITY_VALIDATION:
            failures.append("g10_process_identity_validation_incomplete")

    capture_rows = [event for event in events if event.get("event") == "capture_completed"]
    if len(capture_rows) != 1:
        problems.append("g10_capture_completion_missing_or_duplicated")
    elif type(capture_rows[0].get("driver_exit_status")) is not int or capture_rows[0].get(
            "driver_exit_status") != 0:
        failures.append("g10_driver_exit_not_zero")
    if stops and starts:
        stopped = stops[0]
        started = starts[0]
        if (stopped.get("server_pid") != started.get("server_pid") or
                stopped.get("port") != 8360 or
                stopped.get("remaining_listener_pids") != [] or
                stopped.get("server_log_artifact") != "server.log"):
            failures.append("g10_owned_server_stop_assertion_failed")
        if server_path is not None:
            server_raw, server_read_error = _safe_read_bytes(server_path, run_dir)
            if (server_read_error or server_raw is None or
                    stopped.get("server_log_sha256") != hashlib.sha256(server_raw).hexdigest() or
                    stopped.get("server_log_bytes") != len(server_raw)):
                failures.append("g10_stopped_server_log_binding_mismatch")
    if phase == "complete":
        prepare_rows = [event for event in events if event.get("event") == "prepare"]
        if len(prepare_rows) != 1:
            problems.append("g10_prepare_event_missing_or_duplicated")
        elif prepare_rows[0].get("state_root") != expected_cwd:
            failures.append("g10_prepare_sandbox_identity_mismatch")
    elif phase == "resume" and any(event.get("event") == "prepare" for event in events):
        failures.append("g10_resume_reseeded_sandbox")

    return {"status": "ok" if not problems and not failures else "BLOCKED",
            "problems": sorted(set(problems)), "failures": sorted(set(failures)),
            "events": events, "restart_count": 0 if phase == "complete" else 1}


def _evaluate_g10_bundle(manifest: Dict[str, Any], artifacts: Dict[str, Any],
                         run_dir: Path) -> Dict[str, Any]:
    """Revalidate one G10 phase bundle; this function never records a live verdict."""
    from scripts import combat_latency_fixtures

    run = Path(run_dir)
    scenario = manifest.get("scenario") if isinstance(manifest.get("scenario"), dict) else {}
    party = manifest.get("party") if isinstance(manifest.get("party"), dict) else {}
    phase = scenario.get("phase")
    try:
        profile = combat_latency_fixtures.build_gate_profile(
            "g10", scenario.get("id"), party.get("size"), phase=phase
        )
    except (TypeError, ValueError, KeyError):
        return {"automated_status": "BLOCKED", "primary_verdict": "PENDING",
                "matrix_key": None, "problems": ["invalid_g10_profile"], "failures": []}
    row_key = profile.get("row_key")
    problems: List[str] = []
    failures: List[str] = []
    integrity = _artifact_integrity(run, manifest, artifacts)
    loaded = integrity.get("loaded", {})
    if integrity.get("failures"):
        problems.extend("artifact_integrity:%s" % item for item in integrity["failures"])
    if (manifest.get("gate") != "g10" or manifest.get("run_id") != run.name or
            artifacts.get("matrix_keys") != [row_key] or
            manifest.get("chain_id") != (manifest.get("g10") or {}).get("chain_id")):
        failures.append("g10_run_or_matrix_identity_mismatch")

    contract = {key: profile.get(key) for key in
                ("scenario_id", "party_size", "branch", "phase", "seed", "applicability")}
    contract.update({"gate": "g10", "row_key": row_key,
                     "seed_scenario_id": profile.get("seed_scenario_id"),
                     "seed_identity": profile.get("seed_identity"),
                     "script_sha256": profile.get("applicability", {}).get("script_sha256")})
    if (scenario.get("profile_contract") != contract or
            scenario.get("sha256") != hashlib.sha256(
                json.dumps(contract, sort_keys=True).encode("utf-8")).hexdigest()):
        failures.append("g10_profile_contract_mismatch")
    if (not isinstance(manifest.get("chain_id"), str) or
            not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", manifest.get("chain_id", ""))):
        problems.append("g10_chain_identity_missing_or_invalid")
    expected_seed = dict(profile.get("seed", {}))
    expected_seed.pop("resume_phase", None)
    seed_digest = hashlib.sha256(
        json.dumps(expected_seed, sort_keys=True).encode("utf-8")
    ).hexdigest()
    seed = manifest.get("seed") if isinstance(manifest.get("seed"), dict) else {}
    if (seed.get("profile_seed") != expected_seed or
            seed.get("seed_profile_sha256") != seed_digest or seed.get("seed_id") != seed_digest):
        failures.append("g10_seed_identity_mismatch")

    roster = ([combat_latency_fixtures.ONE_PC_NAME] if profile.get("party_size") == 1
              else list(combat_latency_fixtures.PC_NAMES))
    if (party.get("roster") != roster or seed.get("roster") != roster):
        failures.append("g10_party_roster_mismatch")
    g10 = manifest.get("g10") if isinstance(manifest.get("g10"), dict) else {}
    marker = loaded.get("g10_marker") if isinstance(loaded.get("g10_marker"), dict) else {}
    complete_ref = ("tmp/router-rollout/g10/%s" % run.name if phase == "complete" else
                    marker.get("complete_run_dir"))
    if isinstance(complete_ref, str):
        try:
            expected_complete_path = Path(complete_ref)
            if not expected_complete_path.is_absolute():
                expected_complete_path = PROJECT_ROOT / expected_complete_path
            if (not _inside(expected_complete_path, G10_RUN_ROOT) or
                    _has_symlink_component(expected_complete_path, PROJECT_TMP)):
                raise ValueError("unsafe")
            expected_complete = str(
                expected_complete_path.resolve().relative_to(PROJECT_ROOT.resolve())
            )
        except (OSError, RuntimeError, ValueError):
            expected_complete = None
    else:
        expected_complete = None
    if (marker.get("status") != "ok" or marker.get("gate") != "g10" or
            marker.get("scenario_id") != "full-session" or marker.get("party_size") != party.get("size") or
            marker.get("chain_id") != manifest.get("chain_id") or
            marker.get("seed_id") != seed_digest or
            marker.get("script_sha256") != profile.get("applicability", {}).get("script_sha256") or
            marker.get("complete_run_dir") != expected_complete):
        failures.append("g10_sandbox_marker_identity_mismatch")
    if (g10.get("row_key") != row_key or g10.get("phase") != phase or
            g10.get("chain_id") != manifest.get("chain_id") or
            g10.get("seed_id") != seed_digest or
            g10.get("script_sha256") != profile.get("applicability", {}).get("script_sha256") or
            g10.get("sandbox_id") != manifest.get("sandbox_id")):
        failures.append("g10_manifest_identity_mismatch")
    expected_steps = [
        {key: row.get(key) for key in ("label", "input", "character", "kind")}
        for row in profile.get("fixture", {}).get("steps", [])
    ]
    if g10.get("expected") != {
            "steps": expected_steps,
            "complete_script_sha256": profile.get("applicability", {}).get("script_sha256")
    }:
        failures.append("g10_expected_script_mismatch")

    source_identity = manifest.get("source") if isinstance(manifest.get("source"), dict) else {}
    source_hashes = source_identity.get("relevant_source_sha256")
    dirty_paths = source_identity.get("relevant_dirty_paths")
    dirty_hashes = source_identity.get("relevant_dirty_source_sha256")
    source_digest = hashlib.sha256(json.dumps(
        source_hashes if isinstance(source_hashes, dict) else {},
        sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()
    expected_dirty_digest = None
    if (isinstance(dirty_paths, list) and
            all(isinstance(path, str) and path for path in dirty_paths) and
            dirty_paths == sorted(set(dirty_paths)) and isinstance(dirty_hashes, dict) and
            set(dirty_hashes) == set(dirty_paths) and
            all(value is None or (isinstance(value, str) and
                re.fullmatch(r"[0-9a-f]{64}", value)) for value in dirty_hashes.values())):
        expected_dirty_digest = hashlib.sha256(json.dumps(
            {path: dirty_hashes.get(path) for path in dirty_paths}, sort_keys=True
        ).encode("utf-8")).hexdigest()
    worktree = g10.get("worktree_identity")
    if (not isinstance(worktree, dict) or worktree.get("status") != "ok" or
            worktree.get("root") != str(PROJECT_ROOT.resolve()) or
            worktree.get("head") != source_identity.get("head") or
            worktree.get("relevant_dirty_sha256") != source_identity.get("relevant_dirty_sha256") or
            worktree.get("relevant_source_sha256") != source_digest or
            worktree.get("provenance") != "git HEAD and relevant source identity"):
        problems.append("g10_worktree_identity_missing_or_mismatched")
    if (not isinstance(source_identity.get("head"), str) or
            not re.fullmatch(r"[0-9a-f]{40,64}", source_identity.get("head", "")) or
            not isinstance(source_identity.get("relevant_dirty_sha256"), str) or
            not re.fullmatch(r"[0-9a-f]{64}", source_identity.get("relevant_dirty_sha256", "")) or
            source_identity.get("relevant_dirty_sha256") != expected_dirty_digest or
            not isinstance(source_hashes, dict) or not source_hashes or
            any(not isinstance(path, str) or not path or not isinstance(value, str) or
                not re.fullmatch(r"[0-9a-f]{64}", value)
                for path, value in source_hashes.items()) or
            not {"scripts/capture_drive.py", "scripts/capture_evidence.py",
                 "scripts/combat_latency_fixtures.py", "scripts/seed_combat_capture.py"}
            .issubset(source_hashes)):
        problems.append("g10_source_identity_incomplete")
    if (manifest.get("sandbox_runtime", {}).get("port") != 8360 or
            manifest.get("transport", {}).get("url") != "http://localhost:8360" or
            manifest.get("transport", {}).get("client_source") != "socketio.Client" or
            manifest.get("evidence_kind") != "live-candidate" or
            manifest.get("live_eligible") is not True):
        problems.append("g10_nonlive_or_wrong_sandbox_transport")
    if (manifest.get("sandbox_runtime", {}).get("trace_gate", {}).get("status") != "ok" or
            manifest.get("sandbox_runtime", {}).get("trace_gate", {}).get("enabled") is not True):
        problems.append("g10_trace_gate_unverified")

    expected_count = len(profile.get("fixture", {}).get("steps", []))
    counts = manifest.get("counts") if isinstance(manifest.get("counts"), dict) else {}
    bounds = manifest.get("bounds") if isinstance(manifest.get("bounds"), dict) else {}
    required_count_fields = (
        "step_attempts", "steps_sent", "control_request_attempts", "control_request_calls",
        "control_request_failures", "control_requests_sent", "active_switch_attempts",
        "active_switch_requests_sent", "blocked_step_attempts", "blocked_control_attempts",
        "timeouts", "step_caps_reached", "idle_settle_caps_reached",
        "active_switch_failures", "exit_health_read_attempts",
    )
    malformed_counts = [name for name in required_count_fields
                        if type(counts.get(name)) is not int or counts.get(name) < 0]
    if malformed_counts:
        problems.append("g10_capture_counts_missing_or_malformed")
    if (counts.get("steps_sent") != expected_count or counts.get("step_attempts") != expected_count or
            counts.get("timeouts") != 0 or counts.get("start_timeout") is not False or
            counts.get("blocked_step_attempts") != 0 or counts.get("blocked_control_attempts") != 0 or
            counts.get("control_request_failures") != 0 or
            counts.get("active_switch_failures") != 0 or counts.get("step_caps_reached") != 0 or
            counts.get("idle_settle_caps_reached") != 0 or
            counts.get("control_requests_sent", profile.get("max_requests", 0) + 1) >
            profile.get("max_requests", 0) or
            counts.get("control_request_attempts", profile.get("max_requests", 0) + 1) >
            profile.get("max_requests", 0) or
            counts.get("active_switch_attempts", profile.get("max_active_switches", 0) + 1) >
            profile.get("max_active_switches", 0) or
            counts.get("active_switch_requests_sent", profile.get("max_active_switches", 0) + 1) >
            profile.get("max_active_switches", 0) or
            counts.get("exit_health_read_attempts", profile.get("max_health_reads", 0) + 1) >
            profile.get("max_health_reads", 0) or
            bounds.get("max_steps") != profile.get("max_steps") or
            bounds.get("max_requests") != profile.get("max_requests") or
            bounds.get("max_active_switches") != profile.get("max_active_switches") or
            bounds.get("max_health_reads") != profile.get("max_health_reads") or
            bounds.get("turn_timeout_seconds") != profile.get("turn_timeout_seconds")):
        problems.append("g10_fixed_capture_bounds_not_met")

    before = loaded.get("before_snapshot")
    after = loaded.get("after_snapshot")
    step_rows, step_errors = load_step_snapshots(run, manifest)
    for label, snapshot in (("before", before), ("after", after)):
        party_record = ((snapshot or {}).get("records") or {}).get("party_tracker.json", {})
        if (not isinstance(snapshot, dict) or _snapshot_required_errors(snapshot, manifest) or
                snapshot.get("numeric_errors") or party_record.get("partyMembers") != roster or
                not isinstance(snapshot.get("g10_reward_projection"), dict)):
            problems.append("g10_%s_state_snapshot_incomplete" % label)
        elif not _g10_snapshot_projections_match(snapshot):
            failures.append("g10_%s_state_projection_not_record_derived" % label)
    if step_errors or len(step_rows) != expected_count:
        problems.append("g10_step_snapshots_missing")
    else:
        for index, (expected, pair) in enumerate(zip(profile.get("fixture", {}).get("steps", []), step_rows), 1):
            for edge in ("before", "after"):
                snapshot = pair.get(edge)
                party_record = ((snapshot or {}).get("records") or {}).get("party_tracker.json", {})
                if (not isinstance(snapshot, dict) or _snapshot_required_errors(snapshot, manifest) or
                        snapshot.get("numeric_errors") or party_record.get("partyMembers") != roster or
                        not isinstance(snapshot.get("g10_reward_projection"), dict)):
                    problems.append("g10_step_%03d_%s_state_incomplete" % (index, edge))
                elif not _g10_snapshot_projections_match(snapshot):
                    failures.append("g10_step_%03d_%s_projection_not_record_derived" % (index, edge))
            before_observation = ((pair.get("before") or {}).get("observation") or {})
            after_observation = ((pair.get("after") or {}).get("observation") or {})
            if (before_observation.get("input") != expected.get("input") or
                    after_observation.get("input") != expected.get("input") or
                    after_observation.get("timed_out") is True):
                failures.append("g10_step_%03d_input_or_completion_mismatch" % index)
    snapshot_chain = manifest.get("snapshot_chain") if isinstance(manifest.get("snapshot_chain"), dict) else {}
    if (not isinstance(before, dict) or not isinstance(after, dict) or
            snapshot_chain.get("before_run_sha256") != snapshot_digest(before) or
            snapshot_chain.get("after_run_sha256") != snapshot_digest(after)):
        failures.append("g10_snapshot_chain_digest_mismatch")

    usage_artifact = loaded.get("g10_usage") if isinstance(loaded.get("g10_usage"), dict) else {}
    save_state = loaded.get("g10_save_state") if isinstance(loaded.get("g10_save_state"), dict) else {}
    diary_phase_validation = _g10_diary_phase_validation(save_state, phase)
    problems.extend(diary_phase_validation.get("problems", []))
    failures.extend(diary_phase_validation.get("failures", []))
    usage_validation = revalidate_g10_usage_artifact(
        profile, manifest, step_rows, usage_artifact,
        loaded.get("trace_positions", []) if isinstance(loaded.get("trace_positions"), list) else [],
        integrity.get("loaded", {}).get("trace_position_errors", []),
        loaded.get("g10_tracker_telemetry")
        if isinstance(loaded.get("g10_tracker_telemetry"), dict) else None,
    )
    problems.extend(usage_validation.get("problems", []))
    failures.extend(usage_validation.get("failures", []))
    if (usage_artifact.get("phase") != phase or
            usage_validation.get("expected_status") != "ok"):
        problems.append("g10_usage_or_debug_evidence_not_ready")
    if usage_validation.get("usage_step_receipts", {}).get("status") != "none_observed":
        failures.append("g10_usage_command_made_or_failed_to_exclude_provider_request")
    receipt_view = usage_validation.get("receipts", {})
    response_receipts = usage_validation.get("response_receipts", [])
    if phase == "complete" and (receipt_view.get("status") != "ok" or not response_receipts):
        problems.append("g10_complete_response_receipts_missing")
    providers = sorted({row.get("provider") for row in response_receipts
                        if isinstance(row.get("provider"), str) and row.get("provider")})
    models = sorted({row.get("resolved_model") for row in response_receipts
                     if isinstance(row.get("resolved_model"), str) and
                     row.get("resolved_model") not in ("", "unknown")})
    provider_status = ("ok" if response_receipts and providers and models else
                       "none_observed" if not response_receipts else "unknown")
    expected_provider_identity = {
        "status": provider_status,
        "providers": providers, "response_models": models,
        "response_receipt_count": len(response_receipts),
    }
    if g10.get("provider_identity") != expected_provider_identity:
        failures.append("g10_actual_provider_identity_not_receipt_derived")
    actual_runtime = manifest.get("configuration", {}).get("actual_runtime", {})
    if (actual_runtime.get("receipts") != response_receipts or
            actual_runtime.get("provider") != (providers if providers else "unknown") or
            actual_runtime.get("response_model") != (models if models else "unknown") or
            manifest.get("counts", {}).get("provider_calls", {}).get("count") != len(response_receipts)):
        failures.append("g10_runtime_summary_not_receipt_derived")
    runtime_config = manifest.get("configuration", {}).get("g10_runtime", {})
    if not isinstance(runtime_config, dict) or runtime_config.get("status") != "ok":
        problems.append("g10_runtime_configuration_identity_missing")

    if phase == "complete":
        if (save_state.get("status") != "captured" or
                save_state.get("party_roster") != roster or
                save_state.get("raw_saved_state_copied") is not False or
                not isinstance(save_state.get("save_metadata_sha256"), str) or
                not re.fullmatch(r"[0-9a-f]{64}", save_state.get("save_metadata_sha256", ""))):
            problems.append("g10_complete_save_state_missing_or_invalid")
    elif (save_state.get("status") != "retained" or save_state.get("unchanged") is not True or
          save_state.get("party_roster") != roster):
        problems.append("g10_resume_save_state_not_retained")
    saved_snapshot = save_state.get("saved_state_snapshot")
    saved_digest_map = save_state.get("saved_state_sha256")
    if isinstance(saved_snapshot, dict):
        expected_hashes = _g10_saved_state_hashes(
            Path("."), saved_snapshot, save_state.get("save_metadata_sha256", "")
        )
        if (saved_snapshot.get("numeric_errors") or
                not isinstance(saved_snapshot.get("g10_reward_projection"), dict) or
                expected_hashes != saved_digest_map or
                saved_snapshot.get("mechanical_projection") != save_state.get("saved_state_projection")):
            failures.append("g10_saved_state_projection_or_hash_map_mismatch")
        elif not _g10_snapshot_projections_match(saved_snapshot):
            failures.append("g10_saved_state_projection_not_record_derived")
    else:
        problems.append("g10_saved_state_projection_missing")

    lifecycle = _g10_lifecycle_evaluation(run, artifacts, manifest)
    problems.extend(lifecycle.get("problems", []))
    failures.extend(lifecycle.get("failures", []))
    tracker_artifact = loaded.get("g10_tracker_telemetry")
    tracker_events = lifecycle.get("events", [])
    start_name = "server_started" if phase == "complete" else "resume_server_started"
    start_events = [row for row in tracker_events if isinstance(row, dict) and
                    row.get("event") == start_name]
    if (not isinstance(tracker_artifact, dict) or len(start_events) != 1 or
            tracker_artifact.get("server_launch_epoch") !=
            start_events[0].get("server_launch_epoch")):
        problems.append("g10_tracker_server_launch_lifecycle_binding_mismatch")
    checks_doc = loaded.get("checks") if isinstance(loaded.get("checks"), dict) else {}
    saved_checks = checks_doc.get("checks") if isinstance(checks_doc.get("checks"), list) else []
    g10_checks = build_g10_checks(
        profile, manifest, step_rows, step_errors, usage_artifact, save_state,
        "finalized" if lifecycle.get("status") == "ok" else lifecycle.get("status", "pending"),
    )
    saved_by_id = {row.get("id"): row for row in saved_checks if isinstance(row, dict)}
    for expected_check in g10_checks:
        if saved_by_id.get(expected_check["id"]) != expected_check:
            problems.append("g10_derived_check_mismatch:%s" % expected_check["id"])
        legacy_resume_usage_block = (
            phase == "resume" and
            expected_check.get("id") == "g10_usage_and_debug_provenance" and
            expected_check.get("status") == "BLOCKED" and
            usage_validation.get("expected_status") == "ok" and
            usage_validation.get("startup_receipt_validation", {}).get("status") == "ok"
        )
        if (expected_check.get("required") and expected_check.get("status") != "PASS" and
                not legacy_resume_usage_block):
            problems.append("g10_required_check_not_pass:%s" % expected_check["id"])
    if checks_doc.get("primary_verdict") != "PENDING":
        failures.append("g10_builder_check_artifact_contains_primary_verdict")

    if integrity.get("failures"):
        problems.extend("integrity:%s" % item for item in integrity["failures"])
    failures = sorted(set(failures))
    problems = sorted(set(problems))
    status = "FAIL" if failures else "BLOCKED" if problems else "READY_FOR_PRIMARY_REVIEW"
    return {"automated_status": status, "primary_verdict": "PENDING",
            "matrix_key": row_key, "failures": failures, "problems": problems,
            "integrity_failures": integrity.get("failures", []),
            "response_receipts": len(response_receipts),
            "diary_identifier_evidence": {
                "status": diary_phase_validation.get("status"),
                "saved_projection_sha256": diary_phase_validation.get("saved_projection_sha256"),
                "resumed_projection_sha256": diary_phase_validation.get("resumed_projection_sha256"),
            },
            "startup_receipt_validation": usage_validation.get(
                "startup_receipt_validation", {"status": "not_applicable", "receipts": []}
            ),
            "expected_usage_status": usage_validation.get("expected_status"),
            "usage_step_receipts": usage_validation.get("usage_step_receipts", {}),
            "usage_reconciliation_problems": usage_validation.get(
                "reconciliation_problems", []
            ),
            "lifecycle": {"status": lifecycle.get("status"),
                          "restart_count": lifecycle.get("restart_count")}}


def evaluate_g10_bundle(manifest: Dict[str, Any], artifacts: Dict[str, Any],
                        run_dir: Path) -> Dict[str, Any]:
    """Fail closed on malformed retained evidence without assigning a verdict."""
    try:
        return _evaluate_g10_bundle(manifest, artifacts, run_dir)
    except (AttributeError, IndexError, KeyError, TypeError, ValueError, OSError,
            RuntimeError, OverflowError, RecursionError):
        return {"automated_status": "BLOCKED", "primary_verdict": "PENDING",
                "matrix_key": None, "failures": [],
                "problems": ["malformed_or_unreadable_g10_evidence"]}


def _evaluate_g10_run(run_dir: Path) -> Dict[str, Any]:
    manifest, error = load_bundle_json(run_dir, "manifest.json")
    if error or not isinstance(manifest, dict):
        return {"run_dir": str(run_dir), "error": "manifest:%s" % (error or "invalid")}
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict):
        return {"run_dir": str(run_dir), "manifest": manifest,
                "error": "artifacts_not_object"}
    evaluation = evaluate_g10_bundle(manifest, artifacts, run_dir)
    return {"run_dir": str(run_dir), "manifest": manifest,
            "matrix_key": evaluation.get("matrix_key"), "evaluation": evaluation}


def _g10_resume_startup_usage_totals(validation: Any) -> Dict[str, Any]:
    """Derive the only permissible resume usage delta from validated startup calls."""
    if not isinstance(validation, dict) or validation.get("status") != "ok":
        return {"status": "BLOCKED", "problems": ["g10_resume_startup_receipts_not_validated"]}
    receipts = validation.get("receipts")
    expected_sources = set(_G10_RESUME_STARTUP_SOURCES)
    if not isinstance(receipts, list) or len(receipts) != len(expected_sources):
        return {"status": "FAIL", "failures": ["g10_resume_startup_receipt_set_invalid"]}

    seen_call_ids = set()
    seen_attempt_ids = set()
    source_counts = {source: 0 for source in expected_sources}
    totals = {
        "router": {"calls": 0, "prompt_tokens": 0, "cached_tokens": 0,
                   "completion_tokens": 0, "tokens": 0, "known_cost_usd": 0.0,
                   "unpriced_calls": 0},
        "session": {"tokens": 0, "actual_usd": 0.0, "estimated_usd": 0.0,
                    "known_cost_usd": 0.0, "unpriced_calls": 0},
    }
    failures: List[str] = []
    for row in receipts:
        if not isinstance(row, dict):
            failures.append("g10_resume_startup_receipt_invalid")
            continue
        call_id, attempt_id, source = (
            row.get("call_id"), row.get("attempt_id"), row.get("source")
        )
        if (not isinstance(call_id, str) or not call_id or call_id in seen_call_ids or
                not isinstance(attempt_id, str) or not attempt_id or
                attempt_id in seen_attempt_ids or source not in expected_sources):
            failures.append("g10_resume_startup_receipt_identity_or_source_invalid")
            continue
        seen_call_ids.add(call_id)
        seen_attempt_ids.add(attempt_id)
        source_counts[source] += 1
        if source_counts[source] > 1:
            failures.append("g10_resume_startup_semantic_call_duplicated")
            continue
        numeric_tokens = (row.get("prompt_tokens"), row.get("cached_tokens"),
                          row.get("completion_tokens"), row.get("sdk_total_tokens"))
        if any(not isinstance(value, int) or isinstance(value, bool) or value < 0
               for value in numeric_tokens):
            failures.append("g10_resume_startup_token_telemetry_invalid")
            continue
        label = row.get("cost_label")
        amount = row.get("cost_usd")
        if label in ("actual", "estimated"):
            if not _finite_number(amount) or amount < 0:
                failures.append("g10_resume_startup_cost_telemetry_invalid")
                continue
            totals["router"]["known_cost_usd"] += float(amount)
            totals["session"]["known_cost_usd"] += float(amount)
            totals["session"]["actual_usd" if label == "actual" else "estimated_usd"] += float(amount)
        elif label == "unpriced_unknown" and amount is None:
            totals["router"]["unpriced_calls"] += 1
            totals["session"]["unpriced_calls"] += 1
        else:
            failures.append("g10_resume_startup_cost_telemetry_invalid")
            continue
        prompt, cached, completion, sdk_total = numeric_tokens
        if cached > prompt:
            failures.append("g10_resume_startup_token_telemetry_invalid")
            continue
        totals["router"]["calls"] += 1
        totals["router"]["prompt_tokens"] += prompt
        totals["router"]["cached_tokens"] += cached
        totals["router"]["completion_tokens"] += completion
        totals["router"]["tokens"] += prompt + completion
        totals["session"]["tokens"] += sdk_total

    if any(count != 1 for count in source_counts.values()):
        failures.append("g10_resume_startup_required_source_missing_or_duplicated")
    if failures:
        return {"status": "FAIL", "failures": sorted(set(failures))}
    for section in totals.values():
        section["cost_coverage"] = (
            "complete" if section["unpriced_calls"] == 0 else "incomplete"
        )
    return {"status": "ok", "router": totals["router"],
            "session": totals["session"]}


def _compare_g10_chain_impl(complete_row: Dict[str, Any], resume_row: Dict[str, Any],
                            party_size: int) -> Dict[str, Any]:
    """Compare one complete/resume pair for state and duplicate-cost continuity."""
    problems: List[str] = []
    failures: List[str] = []
    complete = complete_row.get("manifest") or {}
    resume = resume_row.get("manifest") or {}
    complete_artifacts = complete.get("artifacts", {})
    resume_artifacts = resume.get("artifacts", {})
    complete_dir = Path(complete_row.get("run_dir", ""))
    resume_dir = Path(resume_row.get("run_dir", ""))
    if (complete.get("chain_id") != resume.get("chain_id") or
            complete.get("party", {}).get("size") != party_size or
            resume.get("party", {}).get("size") != party_size or
            complete.get("sandbox_id") != resume.get("sandbox_id") or
            complete.get("source") != resume.get("source") or
            complete.get("seed", {}).get("seed_id") != resume.get("seed", {}).get("seed_id") or
            complete.get("party", {}).get("roster") != resume.get("party", {}).get("roster")):
        failures.append("g10_complete_resume_identity_mismatch")
    if complete.get("run_id") == resume.get("run_id") or complete_dir == resume_dir:
        failures.append("g10_complete_resume_bundle_reused")

    complete_marker, complete_marker_error = load_bundle_json(
        complete_dir, complete_artifacts.get("g10_marker")
    )
    resume_marker, resume_marker_error = load_bundle_json(
        resume_dir, resume_artifacts.get("g10_marker")
    )
    try:
        expected_complete_rel = str(complete_dir.resolve().relative_to(PROJECT_ROOT.resolve()))
    except (OSError, RuntimeError, ValueError):
        expected_complete_rel = None
    if (complete_marker_error or resume_marker_error or
            not isinstance(complete_marker, dict) or not isinstance(resume_marker, dict) or
            complete_marker.get("complete_run_dir") != expected_complete_rel or
            resume_marker.get("complete_run_dir") != expected_complete_rel):
        failures.append("g10_complete_resume_marker_binding_mismatch")

    complete_save, complete_save_error = _load_hash_bound_g10_save_state(
        complete_dir, complete
    )
    resume_save, resume_save_error = _load_hash_bound_g10_save_state(
        resume_dir, resume
    )
    complete_after, complete_after_error = load_bundle_json(
        complete_dir, complete_artifacts.get("after_snapshot")
    )
    resume_before, resume_before_error = load_bundle_json(
        resume_dir, resume_artifacts.get("before_snapshot")
    )
    resume_after, resume_after_error = load_bundle_json(
        resume_dir, resume_artifacts.get("after_snapshot")
    )
    diary_identifier_validation: Dict[str, Any] = {
        "status": "BLOCKED", "failures": [],
        "problems": ["g10_diary_identifier_evidence_missing"],
    }
    if (complete_save_error == "artifact_hash_mismatch" or
            resume_save_error == "artifact_hash_mismatch"):
        diary_identifier_validation = {
            "status": "FAIL", "failures": ["g10_diary_identifier_artifact_hash_mismatch"],
            "problems": [],
        }
    elif isinstance(complete_save, dict) and isinstance(resume_save, dict):
        diary_identifier_validation = validate_g10_diary_restart_evidence(
            complete_save, resume_save
        )
    if diary_identifier_validation.get("status") != "ok":
        problems.extend(diary_identifier_validation.get("problems", []))
        failures.extend(diary_identifier_validation.get("failures", []))
    startup_totals: Dict[str, Any] = {
        "status": "BLOCKED", "problems": ["g10_resume_usage_evidence_missing"]
    }
    if any((complete_save_error, resume_save_error, complete_after_error,
            resume_before_error, resume_after_error)):
        problems.append("g10_complete_resume_state_artifact_missing")
    elif not all(isinstance(item, dict) for item in
                 (complete_save, resume_save, complete_after, resume_before, resume_after)):
        problems.append("g10_complete_resume_state_artifact_invalid")
    else:
        complete_projection = complete_after.get("mechanical_projection")
        saved_projection = complete_save.get("saved_state_projection")
        resume_before_projection = resume_before.get("mechanical_projection")
        resume_after_projection = resume_after.get("mechanical_projection")
        complete_rewards = complete_after.get("g10_reward_projection")
        saved_snapshot = complete_save.get("saved_state_snapshot") or {}
        saved_rewards = saved_snapshot.get("g10_reward_projection")
        resume_saved_snapshot = resume_save.get("saved_state_snapshot") or {}
        resume_saved_rewards = resume_saved_snapshot.get("g10_reward_projection")
        resume_before_rewards = resume_before.get("g10_reward_projection")
        resume_after_rewards = resume_after.get("g10_reward_projection")
        if (complete_save.get("status") != "captured" or
                resume_save.get("status") != "retained" or
                complete_save.get("save_id") != resume_save.get("save_id") or
                complete_save.get("save_directory") != resume_save.get("save_directory") or
                complete_save.get("save_metadata_sha256") != resume_save.get("save_metadata_sha256") or
                complete_save.get("saved_state_projection") != resume_save.get("saved_state_projection") or
                complete_save.get("saved_state_sha256") != resume_save.get("saved_state_sha256")):
            failures.append("g10_saved_state_identity_changed_across_restart")
        if (complete_projection != saved_projection or
                complete_projection != resume_before_projection or
                resume_before_projection != resume_after_projection):
            failures.append("g10_mechanics_or_rewards_changed_across_resume")
        if (not isinstance(complete_rewards, dict) or complete_rewards != saved_rewards or
                complete_rewards != resume_saved_rewards or
                complete_rewards != resume_before_rewards or
                resume_before_rewards != resume_after_rewards):
            failures.append("g10_inventory_or_reward_state_changed_across_resume")
    complete_usage, complete_usage_error = load_bundle_json(
        complete_dir, complete_artifacts.get("g10_usage")
    )
    resume_usage, resume_usage_error = load_bundle_json(
        resume_dir, resume_artifacts.get("g10_usage")
    )
    if complete_usage_error or resume_usage_error or not isinstance(complete_usage, dict) or not isinstance(
            resume_usage, dict):
        problems.append("g10_complete_resume_usage_artifact_missing")
    else:
        complete_tracker, complete_tracker_error = load_bundle_json(
            complete_dir, complete_artifacts.get("g10_tracker_telemetry")
        )
        resume_tracker, resume_tracker_error = load_bundle_json(
            resume_dir, resume_artifacts.get("g10_tracker_telemetry")
        )
        if (complete_tracker_error or resume_tracker_error or
                not isinstance(complete_tracker, dict) or not isinstance(resume_tracker, dict)):
            problems.append("g10_complete_resume_tracker_artifact_missing")
        else:
            complete_observed = complete_usage.get("observed", {})
            resume_observed = resume_usage.get("observed", {})
            complete_receipts = complete_usage.get("router_receipts", {})
            resume_receipts_projection = resume_usage.get("router_receipts", {})
            complete_tracker_projection = project_g10_tracker_telemetry(
                complete_tracker, complete_observed, complete_receipts
            )
            resume_tracker_projection = project_g10_tracker_telemetry(
                resume_tracker, resume_observed, resume_receipts_projection
            )
            if (complete_usage.get("tracker_reconciliation") != complete_tracker_projection or
                    resume_usage.get("tracker_reconciliation") != resume_tracker_projection or
                    complete_tracker_projection.get("status") != "ok" or
                    resume_tracker_projection.get("status") != "ok"):
                problems.append("g10_complete_resume_tracker_reconciliation_invalid")
            complete_terminal = complete_tracker.get("post_shutdown", {})
            complete_terminal_source = (complete_terminal.get("source", {})
                                        if isinstance(complete_terminal, dict) else {})
            resume_baseline = resume_tracker.get("pre_run", {})
            resume_baseline_source = (resume_baseline.get("source", {})
                                     if isinstance(resume_baseline, dict) else {})
            resume_link = resume_tracker.get("prior_link", {})
            complete_tracker_path, complete_tracker_path_error = _bundle_file(
                complete_dir, complete_artifacts.get("g10_tracker_telemetry")
            )
            complete_tracker_raw, complete_tracker_read_error = (
                _safe_read_bytes(complete_tracker_path, complete_dir)
                if complete_tracker_path is not None else (None, complete_tracker_path_error)
            )
            complete_tracker_digest = (
                hashlib.sha256(complete_tracker_raw).hexdigest()
                if complete_tracker_raw is not None and not complete_tracker_read_error else None
            )
            if (complete_tracker.get("phase") != "complete" or
                    resume_tracker.get("phase") != "resume" or
                    complete_tracker.get("run_id") != complete.get("run_id") or
                    resume_tracker.get("run_id") != resume.get("run_id") or
                    complete_tracker.get("chain_id") != resume_tracker.get("chain_id") or
                    complete_tracker.get("seed_id") != resume_tracker.get("seed_id") or
                    complete_tracker.get("sandbox_id") != resume_tracker.get("sandbox_id") or
                    complete_terminal.get("window_days") != resume_baseline.get("window_days") or
                    not _g10_usage_value_bounded(
                        complete_terminal.get("captured_at_epoch"), 10 ** 12
                    ) or
                    not _g10_usage_value_bounded(
                        resume_baseline.get("captured_at_epoch"), 10 ** 12
                    ) or
                    resume_baseline.get("captured_at_epoch", 0) <
                    complete_terminal.get("captured_at_epoch", 0) or
                    complete_artifacts.get("g10_tracker_telemetry") !=
                    "g10_tracker_telemetry.json" or
                    resume_artifacts.get("g10_tracker_telemetry") !=
                    "g10_tracker_telemetry.json" or
                    complete_terminal_source.get("sha256") != resume_baseline_source.get("sha256") or
                    complete_terminal_source.get("bytes") != resume_baseline_source.get("bytes") or
                    resume_link.get("status") != "linked_complete_boundary" or
                    resume_link.get("complete_run_dir") != expected_complete_rel or
                    resume_link.get("complete_artifact") != "g10_tracker_telemetry.json" or
                    resume_link.get("complete_artifact_sha256") != complete_tracker_digest or
                    resume_link.get("complete_terminal_source_sha256") !=
                    complete_terminal_source.get("sha256") or
                    resume_link.get("complete_terminal_source_bytes") !=
                    complete_terminal_source.get("bytes")):
                failures.append("g10_tracker_complete_resume_boundary_mismatch")
        complete_sections = (complete_usage.get("observed") or {}).get("sections", {})
        resume_sections = (resume_usage.get("observed") or {}).get("sections", {})
        if not isinstance(complete_sections, dict) or not isinstance(resume_sections, dict):
            complete_sections = {}
            resume_sections = {}
            problems.append("g10_complete_resume_usage_sections_invalid")
        resume_evaluation = (resume_row.get("evaluation")
                             if isinstance(resume_row.get("evaluation"), dict) else {})
        startup_validation = resume_evaluation.get("startup_receipt_validation")
        startup_totals = _g10_resume_startup_usage_totals(startup_validation)
        if startup_totals.get("status") != "ok":
            failures.extend(startup_totals.get("failures", []))
            problems.extend(startup_totals.get("problems", []))
        if resume_evaluation.get("expected_usage_status") != "ok":
            problems.append("g10_resume_usage_not_reconciled_to_startup_receipts")
        if resume_evaluation.get("usage_reconciliation_problems") != []:
            failures.append("g10_resume_usage_receipt_reconciliation_failed")
        usage_step_receipts = resume_evaluation.get("usage_step_receipts")
        if (not isinstance(usage_step_receipts, dict) or
                usage_step_receipts.get("status") != "none_observed" or
                usage_step_receipts.get("receipts") != []):
            failures.append("g10_usage_command_made_or_failed_to_exclude_provider_request")
        if (complete_usage.get("status") != "ok" or
                resume_usage.get("status") not in ("ok", "BLOCKED") or
                (resume_usage.get("status") == "BLOCKED" and
                 (resume_evaluation.get("expected_usage_status") != "ok" or
                  not isinstance(startup_validation, dict) or
                  startup_validation.get("status") != "ok"))):
            problems.append("g10_complete_resume_usage_incomplete")

        def section_matches_expected(name: str) -> bool:
            actual = resume_sections.get(name)
            expected = startup_totals.get(name)
            if not isinstance(actual, dict) or not isinstance(expected, dict):
                return False
            for field, value in expected.items():
                observed_value = actual.get(field)
                if field.endswith("_usd") or field == "known_cost_usd":
                    if (not _finite_number(observed_value) or
                            abs(float(observed_value) - float(value)) > 0.000001):
                        return False
                elif observed_value != value:
                    return False
            return True

        if startup_totals.get("status") == "ok" and (
                not section_matches_expected("router") or
                not section_matches_expected("session")):
            failures.append("g10_resume_usage_totals_not_startup_receipt_derived")

        week_fields = ("tokens", "actual_usd", "estimated_usd", "known_cost_usd",
                       "unpriced_calls", "cost_coverage")

        def valid_week_usage(row: Any) -> bool:
            return (
                isinstance(row, dict) and
                all(field in row for field in week_fields) and
                isinstance(row.get("tokens"), int) and not isinstance(row.get("tokens"), bool) and
                row["tokens"] >= 0 and
                isinstance(row.get("unpriced_calls"), int) and
                not isinstance(row.get("unpriced_calls"), bool) and row["unpriced_calls"] >= 0 and
                all(_finite_number(row.get(field)) and row[field] >= 0
                    for field in ("actual_usd", "estimated_usd", "known_cost_usd")) and
                abs(row["known_cost_usd"] - row["actual_usd"] - row["estimated_usd"]) <= 0.000001 and
                row.get("cost_coverage") in ("complete", "incomplete")
            )

        complete_week = complete_sections.get("week")
        resume_week = resume_sections.get("week")
        if not valid_week_usage(complete_week) or not valid_week_usage(resume_week):
            problems.append("g10_rolling_week_usage_missing_or_invalid")
        elif startup_totals.get("status") == "ok":
            startup_session = startup_totals["session"]
            expected_week = {
                "tokens": complete_week["tokens"] + startup_session["tokens"],
                "actual_usd": complete_week["actual_usd"] + startup_session["actual_usd"],
                "estimated_usd": (complete_week["estimated_usd"] +
                                  startup_session["estimated_usd"]),
                "known_cost_usd": (complete_week["known_cost_usd"] +
                                   startup_session["known_cost_usd"]),
                "unpriced_calls": (complete_week["unpriced_calls"] +
                                   startup_session["unpriced_calls"]),
            }
            expected_week["cost_coverage"] = (
                "complete" if expected_week["unpriced_calls"] == 0 else "incomplete"
            )
            if (resume_week.get("tokens") != expected_week["tokens"] or
                    resume_week.get("unpriced_calls") != expected_week["unpriced_calls"] or
                    resume_week.get("cost_coverage") != expected_week["cost_coverage"] or
                    any(abs(float(resume_week.get(field)) - float(expected_week[field])) > 0.000001
                        for field in ("actual_usd", "estimated_usd", "known_cost_usd"))):
                failures.append("g10_rolling_week_usage_not_startup_receipt_derived")

        resume_receipts = resume_usage.get("router_receipts", {})
        accepted_ids = {
            (row.get("call_id"), row.get("attempt_id"))
            for row in startup_validation.get("receipts", [])
            if isinstance(row, dict)
        } if isinstance(startup_validation, dict) else set()
        projected_receipts = resume_receipts.get("receipts", [])
        projected_ids = {
            (row.get("call_id"), row.get("attempt_id"))
            for row in projected_receipts if isinstance(row, dict)
        } if isinstance(projected_receipts, list) else set()
        if (startup_totals.get("status") != "ok" or
                resume_receipts.get("status") != "ok" or
                not isinstance(projected_receipts, list) or len(projected_receipts) != 2 or
                len(accepted_ids) != 2 or projected_ids != accepted_ids):
            failures.append("g10_resume_receipt_set_not_exactly_startup_calls")

    complete_lifecycle = ((complete.get("g10") or {}).get("lifecycle") or {})
    resume_lifecycle = ((resume.get("g10") or {}).get("lifecycle") or {})
    if complete_lifecycle.get("status") != "finalized" or resume_lifecycle.get("status") != "finalized":
        problems.append("g10_chain_lifecycle_not_finalized")
    # JSONL is intentionally parsed by the per-bundle evaluator; compare its process identities there.
    complete_start_pid = None
    resume_start_pid = None
    for path, phase_name in ((complete_dir / "server_lifecycle.jsonl", "complete"),
                             (resume_dir / "server_lifecycle.jsonl", "resume")):
        raw, read_error = _safe_read_bytes(path, PROJECT_TMP)
        if read_error or raw is None:
            continue
        try:
            events = [json.loads(line) for line in raw.decode("ascii").splitlines() if line.strip()]
        except (UnicodeError, ValueError):
            continue
        expected_name = "server_started" if phase_name == "complete" else "resume_server_started"
        start = next((event for event in events if isinstance(event, dict) and
                      event.get("event") == expected_name), None)
        if start:
            if phase_name == "complete":
                complete_start_pid = start.get("server_pid")
            else:
                resume_start_pid = start.get("server_pid")
    if (not isinstance(complete_start_pid, int) or isinstance(complete_start_pid, bool) or
            not isinstance(resume_start_pid, int) or isinstance(resume_start_pid, bool)):
        problems.append("g10_chain_restart_pid_evidence_missing")
    elif complete_start_pid == resume_start_pid:
        failures.append("g10_resume_did_not_restart_owned_server")

    return {"status": "FAIL" if failures else "BLOCKED" if problems else "READY_FOR_PRIMARY_REVIEW",
            "failures": sorted(set(failures)), "problems": sorted(set(problems)),
            "diary_identifier_validation": diary_identifier_validation,
            "resume_startup_usage": startup_totals}


def _compare_g10_chain(complete_row: Dict[str, Any], resume_row: Dict[str, Any],
                       party_size: int) -> Dict[str, Any]:
    """Fail closed on malformed paired-bundle projections."""
    try:
        return _compare_g10_chain_impl(complete_row, resume_row, party_size)
    except (AttributeError, IndexError, KeyError, TypeError, ValueError, OSError,
            RuntimeError, OverflowError, RecursionError):
        return {"status": "BLOCKED", "failures": [],
                "problems": ["malformed_g10_chain_evidence"]}


def evaluate_g10_matrix(run_rows: Iterable[Any]) -> Dict[str, Any]:
    """Evaluate the closed G10 complete/resume matrix without emitting a live verdict."""
    from scripts import combat_latency_fixtures

    required = list(combat_latency_fixtures.required_g10_row_keys())
    invalid_runs: List[str] = []
    duplicate_keys: List[str] = []
    by_key: Dict[str, Dict[str, Any]] = {}
    for row in run_rows:
        try:
            candidate = Path(row.get("run_dir")) if isinstance(row, dict) and row.get("run_dir") else Path(row)
            if not candidate.is_absolute():
                candidate = PROJECT_ROOT / candidate
        except (TypeError, ValueError):
            invalid_runs.append("invalid_run_directory_input")
            continue
        if (not _inside(candidate, G10_RUN_ROOT) or candidate.resolve() == G10_RUN_ROOT.resolve() or
                _has_symlink_component(candidate, PROJECT_TMP)):
            invalid_runs.append("unsafe_run_directory:%s" % candidate.name)
            continue
        result = _evaluate_g10_run(candidate)
        key = result.get("matrix_key")
        if not isinstance(key, str) or key not in required:
            invalid_runs.append("%s:%s" % (candidate.name, result.get("error", "unknown_g10_row_key")))
            continue
        if key in by_key:
            duplicate_keys.append(key)
            continue
        by_key[key] = result
    missing = [key for key in required if key not in by_key]
    extra = sorted(set(by_key) - set(required))
    failed = sorted(key for key, row in by_key.items()
                    if row.get("evaluation", {}).get("automated_status") == "FAIL")
    not_ready = sorted(key for key, row in by_key.items()
                       if row.get("evaluation", {}).get("automated_status") != "READY_FOR_PRIMARY_REVIEW")
    synthetic = sorted(key for key, row in by_key.items()
                       if (row.get("manifest") or {}).get("evidence_kind") != "live-candidate" or
                       (row.get("manifest") or {}).get("live_eligible") is not True or
                       (row.get("manifest") or {}).get("transport", {}).get("client_source") !=
                       "socketio.Client")
    pairs: Dict[str, Dict[str, Any]] = {}
    chain_ids = set()
    pair_failures: List[str] = []
    pair_problems: List[str] = []
    for party_size in combat_latency_fixtures.G10_PARTY_SIZES:
        complete_key = combat_latency_fixtures.g10_row_key("complete", party_size)
        resume_key = combat_latency_fixtures.g10_row_key("resume", party_size)
        complete_row = by_key.get(complete_key)
        resume_row = by_key.get(resume_key)
        if complete_row is None or resume_row is None:
            pairs["p%d" % party_size] = {"status": "BLOCKED", "problems": ["phase_bundle_missing"]}
            continue
        complete_manifest = complete_row.get("manifest") or {}
        chain_id = complete_manifest.get("chain_id")
        if isinstance(chain_id, str):
            if chain_id in chain_ids:
                pair_failures.append("g10_party_chains_reused")
            chain_ids.add(chain_id)
        pair = _compare_g10_chain(complete_row, resume_row, party_size)
        pairs["p%d" % party_size] = pair
        pair_failures.extend(pair.get("failures", []))
        pair_problems.extend(pair.get("problems", []))
    issues = bool(missing or extra or duplicate_keys or invalid_runs or failed or not_ready or synthetic or
                  pair_failures or pair_problems)
    status = "FAIL" if failed or pair_failures else "BLOCKED" if issues else "READY_FOR_PRIMARY_REVIEW"
    return {
        "gate": "g10", "automated_status": status, "primary_verdict": "PENDING",
        "required_keys": required, "observed_keys": sorted(by_key),
        "missing_required_keys": missing, "extra_keys": extra,
        "duplicate_keys": sorted(set(duplicate_keys)), "not_ready_keys": not_ready,
        "failed_keys": failed, "synthetic_keys": synthetic,
        "invalid_run_bundles": sorted(set(invalid_runs)),
        "pair_failures": sorted(set(pair_failures)),
        "pair_problems": sorted(set(pair_problems)), "pairs": pairs,
        "runs": {key: {
            "automated_status": row.get("evaluation", {}).get("automated_status"),
            "failures": row.get("evaluation", {}).get("failures", []),
            "problems": row.get("evaluation", {}).get("problems", []),
            "response_receipts": row.get("evaluation", {}).get("response_receipts"),
        } for key, row in sorted(by_key.items())},
    }


def evaluate_evidence(manifest: Dict[str, Any], checks: Iterable[Dict[str, Any]],
                      artifacts: Dict[str, Any], *, run_dir: Path,
                      integrity: Optional[Dict[str, Any]] = None,
                      profile: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Validate real bundle bytes and derived observations, never status labels alone."""
    run_dir = Path(run_dir)
    integrity = integrity or _artifact_integrity(run_dir, manifest, artifacts)
    check_rows = list(checks)
    g5t_required_check_ids = (
        {"applied_choice_legality", "commander_squad_follows_orders",
         "self_preservation_removal", "cover_changes_effective_ac", "cover_expiration"}
        if profile and profile.get("scenario_id") in ("g5t-commander-p1", "g5t-commander-p4")
        else set()
    )
    g5a_required_check_ids = (
        {"g5a_party_and_active_ally", "g5a_scripted_damage_legal", "g5a_accepted_directive",
         "g5a_directive_take_cover", "g5a_no_forbidden_ally_choice",
         "g5a_applied_choice_legality", "g5a_ally_call_bounds", "g5a_sandbox_flags"}
        if profile and profile.get("scenario_id") in ("g5a-ally-p1", "g5a-ally-p4")
        else set()
    )
    failures = [row for row in check_rows
                if (row.get("required", True) or row.get("id") in
                    (g5t_required_check_ids | g5a_required_check_ids))
                and row.get("status") == "FAIL"]
    blocked_checks = [row for row in check_rows
                      if (row.get("required", True) or row.get("id") in
                          (g5t_required_check_ids | g5a_required_check_ids))
                      and row.get("status") not in ("PASS", "NOT_APPLICABLE", "NOT_OBSERVED")]
    required_missing = sorted(_required_check_ids(profile) - {row.get("id") for row in check_rows}) if profile else ["scenario_profile"]
    local_key = (profile.get("row_key") if profile and manifest.get("gate") == "g9" else
                 matrix_key(manifest.get("scenario", {}).get("id", ""),
                            manifest.get("party", {}).get("size", -1),
                            manifest.get("scenario", {}).get("branch"),
                            manifest.get("scenario", {}).get("phase")))
    scenario_id = manifest.get("scenario", {}).get("id")
    party_size = manifest.get("party", {}).get("size")
    g5t_named_key = (manifest.get("gate") == "g5t" and party_size in (1, 4) and
                     scenario_id == "g5t-commander-p%d" % party_size)
    g5a_named_key = (manifest.get("gate") == "g5a" and party_size in (1, 4) and
                     scenario_id == "g5a-ally-p%d" % party_size)
    g9_named_key = (manifest.get("gate") == "g9" and profile is not None and
                    local_key in required_g9_row_keys())
    local_key_error = (artifacts.get("matrix_keys") != [local_key] or
                       (local_key not in REQUIRED_KEYS and not g5t_named_key and
                        not g5a_named_key and not g9_named_key))
    missing_artifacts = integrity.get("failures", [])
    degraded = artifacts.get("required_evidence_status") not in ("ok", "non_applicable")
    counts = manifest.get("counts", {})
    bounds = manifest.get("bounds", {})
    numerical_count_names = ("step_attempts", "steps_sent", "backend_output_count",
                             "control_request_attempts", "control_request_calls",
                             "control_request_failures", "control_requests_sent", "active_switch_attempts", "active_switch_requests_sent",
                             "blocked_step_attempts", "blocked_control_attempts", "timeouts")
    malformed_counts = [name for name in numerical_count_names if not _finite_number(counts.get(name))]
    malformed_bounds = [name for name in ("max_steps", "max_requests", "max_health_reads",
                                           "turn_timeout_seconds", "start_timeout_seconds")
                        if not _finite_number(bounds.get(name)) or bounds.get(name) < 0]
    if not _finite_number(bounds.get("max_active_switches")) or bounds.get("max_active_switches") < 0:
        malformed_bounds.append("max_active_switches")
    if _finite_number(bounds.get("turn_timeout_seconds")) and bounds["turn_timeout_seconds"] == 0:
        malformed_bounds.append("turn_timeout_seconds")
    if _finite_number(bounds.get("start_timeout_seconds")) and bounds["start_timeout_seconds"] == 0:
        malformed_bounds.append("start_timeout_seconds")
    import sys

    fixture_module = sys.modules.get("scripts.combat_latency_fixtures")
    if fixture_module is None:
        driver_module = sys.modules.get("scripts.capture_drive")
        fixture_module = getattr(driver_module, "capture_fixtures", None)
    if fixture_module is None:
        from scripts import combat_latency_fixtures as fixture_module


    scenario_identity = manifest.get("scenario", {})
    party_identity = manifest.get("party", {})
    timeout_scenario = scenario_identity.get("id")
    g9_narrator_timeout_profile = (
        manifest.get("gate") == "g9" and scenario_identity.get("id") == "narrator-auto" and
        profile is not None and profile.get("gate") == "g9" and
        profile.get("capture_kind") == "narrator" and
        profile.get("seed_scenario_id") == "narrator-dialogue-travel" and
        profile.get("party_size") in (1, 4) and
        party_identity.get("size") == profile.get("party_size") and
        profile.get("turn_timeout_seconds") == 300
    )
    timeout_policy_allowed = (
        bounds.get("turn_timeout_seconds") == profile.get("turn_timeout_seconds")
        if g9_narrator_timeout_profile else
        fixture_module.capture_turn_timeout_allowed(
            timeout_scenario, party_identity.get("size"),
            scenario_identity.get("branch"), bounds.get("turn_timeout_seconds"),
        )
    )
    if (_finite_number(bounds.get("start_timeout_seconds")) and bounds["start_timeout_seconds"] > 180 or
            not timeout_policy_allowed or
            not _finite_number(bounds.get("turn_quiet_seconds")) or bounds.get("turn_quiet_seconds", 0) <= 0):
        malformed_bounds.append("timeout_policy")
    malformed_counts.extend(name for name in ("step_caps_reached", "idle_settle_caps_reached",
        "active_switch_failures", "health_read_attempts", "exit_health_read_attempts")
        if not _finite_number(counts.get(name)))
    timed_out = bool(counts.get("timeouts") or counts.get("start_timeout"))
    capped = bool(counts.get("blocked_step_attempts") or counts.get("blocked_control_attempts")
                  or counts.get("step_caps_reached") or counts.get("idle_settle_caps_reached"))
    over_bound = (_finite_number(counts.get("steps_sent")) and _finite_number(bounds.get("max_steps"))
                  and counts["steps_sent"] > bounds["max_steps"])
    over_bound = over_bound or (_finite_number(counts.get("control_requests_sent")) and
                                _finite_number(bounds.get("max_requests")) and
                                counts["control_requests_sent"] > bounds["max_requests"])
    over_bound = over_bound or (_finite_number(counts.get("exit_health_read_attempts")) and
                                _finite_number(bounds.get("max_health_reads")) and
                                counts["exit_health_read_attempts"] > bounds["max_health_reads"])
    over_bound = over_bound or (_finite_number(counts.get("active_switch_attempts")) and
                                _finite_number(bounds.get("max_active_switches")) and
                                counts["active_switch_attempts"] > bounds["max_active_switches"])
    source = manifest.get("source", {})
    relevant_sources = source.get("relevant_source_sha256", {})
    required_source_roots = ("core/combat/", "core/managers/combat_manager.py",
        "core/managers/multi_pc_combat.py", "core/managers/combat_state_sync.py",
        "main.py", "core/ai/action_handler.py", "utils/combat_latency_trace.py",
        "utils/ai_client_factory.py", "model_config.py")
    dirty_sources = source.get("relevant_dirty_source_sha256", {})
    expected_dirty_digest = hashlib.sha256(json.dumps(dirty_sources, sort_keys=True).encode("utf-8")).hexdigest()
    source_missing = (not isinstance(source.get("head"), str) or
                      not re.fullmatch(r"[0-9a-f]{40,64}", source.get("head", "")) or
                      not isinstance(relevant_sources, dict) or not relevant_sources
                      or not source.get("relevant_dirty_sha256") or
                      source.get("relevant_dirty_sha256") != expected_dirty_digest or
                      not isinstance(dirty_sources, dict) or
                      any(not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)
                          for digest in relevant_sources.values()) or
                      any(not any(path == required or path.startswith(required)
                                  for path in relevant_sources) for required in required_source_roots))
    sandbox_runtime = manifest.get("sandbox_runtime", {})
    trace_gate_invalid = (sandbox_runtime.get("trace_gate", {}).get("status") != "ok" or
                          sandbox_runtime.get("trace_gate", {}).get("enabled") is not True)
    prompt_hashes = manifest.get("prompt_identity_sha256", {})
    expected_prompt_count = (
        len(_prompt_identity()) if manifest.get("gate") in ("g9", "g5a") else 9
    )
    prompt_missing = (not isinstance(prompt_hashes, dict) or not prompt_hashes or
                      len(prompt_hashes) != expected_prompt_count or any(not isinstance(value, str) or
                     not re.fullmatch(r"[0-9a-f]{64}", value) for value in prompt_hashes.values())
                      )
    is_synthetic = (manifest.get("evidence_kind") == "synthetic" or
                    manifest.get("live_eligible") is not True or
                    manifest.get("transport", {}).get("client_source") != "socketio.Client")
    problems: List[str] = []
    if failures: problems.append("failed_required_checks")
    if blocked_checks: problems.append("blocked_or_unobserved_required_checks")
    if required_missing: problems.append("missing_required_check_definitions")
    if missing_artifacts: problems.append("invalid_missing_or_stale_artifacts")
    if degraded: problems.append("degraded_required_evidence")
    if timed_out: problems.append("required_timeout")
    if capped: problems.append("required_cap")
    if over_bound: problems.append("bound_exceeded")
    if malformed_counts or malformed_bounds: problems.append("malformed_counts_or_bounds")
    if local_key_error: problems.append("wrong_or_missing_per_run_matrix_key")
    if source_missing: problems.append("source_identity_missing")
    if trace_gate_invalid: problems.append("sandbox_trace_gate_unverified")
    if prompt_missing: problems.append("prompt_identity_missing")
    if counts.get("active_switch_failures"): problems.append("required_active_pc_switch_failed")
    if counts.get("control_request_failures"): problems.append("required_control_request_failed")
    if is_synthetic: problems.append("synthetic_evidence")
    automated_status = "FAIL" if failures or over_bound or capped else (
        "BLOCKED" if problems else "READY_FOR_PRIMARY_REVIEW")
    return {
        "automated_status": automated_status,
        "primary_verdict": "PENDING",
        "live_eligible": not is_synthetic,
        "matrix_key": local_key,
        "missing_required_checks": required_missing,
        "integrity_failures": missing_artifacts,
        "failed_required_checks": failures,
        "blocked_required_checks": blocked_checks,
        "problems": problems,
        "checks": check_rows,
    }


def _history_inventory(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    rows = snapshot.get("records", {})
    return {name: [{"path": entry.get("path"), "bytes": entry.get("bytes"),
                    "semantic_message_count": entry.get("semantic_message_count"),
                    "semantic_message_identities": entry.get("semantic_message_identities"),
                    "excluded_message_counts": entry.get("excluded_message_counts"),
                    "identity_status": entry.get("identity_status"),
                    "status": entry.get("status")}
                   for entry in rows.get(name, []) if isinstance(entry, dict)]
            for name in ("modules/conversation_history", "save_games")}


def compare_resume_chain(complete: Dict[str, Any], replay: Dict[str, Any]) -> Dict[str, Any]:
    """Compare immutable seed identity separately from retained/effect state."""
    mismatches = []
    complete_role = (complete.get("scenario") or {}).get("phase")
    replay_role = (replay.get("scenario") or {}).get("phase")
    if complete_role != "complete" or replay_role != "replay":
        mismatches.append("phase_roles")
    if not isinstance(complete.get("chain_id"), str) or not complete.get("chain_id"):
        mismatches.append("empty_chain_id")
    elif complete.get("chain_id") != replay.get("chain_id"):
        mismatches.append("chain_id")
    for field in ("sandbox_id", "source", "party", "seed", "transport"):
        if complete.get(field) != replay.get(field):
            mismatches.append(field)
    complete_state = (complete.get("snapshot_chain") or {}).get("after_projection")
    replay_before = (replay.get("snapshot_chain") or {}).get("before_projection")
    replay_after = (replay.get("snapshot_chain") or {}).get("after_projection")
    state_comparison = bool(complete_state and replay_before and replay_after
                            and complete_state == replay_before == replay_after)
    if not state_comparison:
        mismatches.append("retained_mechanical_state")
    complete_history = (complete.get("snapshot_chain") or {}).get("after_history_inventory")
    replay_before_history = (replay.get("snapshot_chain") or {}).get("before_history_inventory")
    replay_after_history = (replay.get("snapshot_chain") or {}).get("after_history_inventory")
    complete_messages = next((entry.get("semantic_message_identities")
                              for entry in complete_history.get("modules/conversation_history", [])
                              if entry.get("identity_status") == "ok"), None) if complete_history else None
    replay_before_messages = next((entry.get("semantic_message_identities")
                                   for entry in replay_before_history.get("modules/conversation_history", [])
                                   if entry.get("identity_status") == "ok"), None) if replay_before_history else None
    replay_after_messages = next((entry.get("semantic_message_identities")
                                  for entry in replay_after_history.get("modules/conversation_history", [])
                                  if entry.get("identity_status") == "ok"), None) if replay_after_history else None
    history_ok = bool(complete_history and replay_before_history and replay_after_history and
                      complete_messages is not None and replay_before_messages is not None and
                      replay_after_messages is not None and complete_messages)
    if history_ok:
        # A restart may append history, but it may not lose a completed-run file
        # or shrink its retained content. Raw-byte digests are evidence only.
        for group, entries in complete_history.items():
            before_map = {row.get("path"): row for row in replay_before_history.get(group, [])}
            after_map = {row.get("path"): row for row in replay_after_history.get(group, [])}
            for row in entries:
                before_entry, after_entry = before_map.get(row.get("path")), after_map.get(row.get("path"))
                if (not before_entry or before_entry.get("status") != "ok" or
                        before_entry.get("bytes", -1) < row.get("bytes", 0) or not after_entry or
                        after_entry.get("status") != "ok" or after_entry.get("bytes", -1) < before_entry.get("bytes", 0)):
                    history_ok = False
        if history_ok and complete_messages != replay_before_messages:
            history_ok = False
        if history_ok and replay_after_messages[:len(complete_messages)] != complete_messages:
            history_ok = False
        if not history_ok:
            mismatches.append("retained_history")
    else:
        mismatches.append("history_observation_missing")
    return {"status": "PASS" if not mismatches else "FAIL",
            "mismatched_identity_fields": mismatches,
            "complete_run": complete.get("run_id"), "replay_run": replay.get("run_id"),
            "state_comparison": state_comparison, "history_retained": history_ok}


def _load_run_evidence(run_dir: Path, resume_chain: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    manifest, error = load_bundle_json(run_dir, "manifest.json")
    if error or manifest is None:
        return {"run_dir": str(run_dir), "manifest": None, "error": "manifest:%s" % (error or "missing")}
    artifacts = manifest.get("artifacts", {})
    integrity = _artifact_integrity(run_dir, manifest, artifacts)
    loaded = integrity["loaded"]
    before, after = loaded.get("before_snapshot"), loaded.get("after_snapshot")
    steps, step_errors = load_step_snapshots(run_dir, manifest)
    scenario = manifest.get("scenario", {})
    party_identity = manifest.get("party", {})
    profile = _expected_profile_contract(scenario.get("id"), party_identity.get("size"),
                                         scenario.get("branch"), scenario.get("phase"))
    if profile is None or scenario.get("profile_contract") != profile:
        return {"run_dir": str(run_dir), "manifest": manifest, "error": "invalid_profile", "integrity": integrity}
    expected_bounds = _expected_profile_bounds(profile)
    if any(manifest.get("bounds", {}).get(key) != value for key, value in expected_bounds.items()):
        integrity["failures"].append("manifest:scenario_bound_mismatch")
    # Derive the single case key from the manifest; never accept caller-provided
    # matrix keys or status labels as authority.
    key = matrix_key(profile["scenario_id"], profile["party_size"], profile.get("branch"), profile.get("phase"))
    g5t_named_key = (
        profile.get("gate") == "g5t"
        and profile.get("party_size") in (1, 4)
        and profile.get("scenario_id") == "g5t-commander-p%d" % profile.get("party_size")
    )
    g5a_named_key = (
        profile.get("gate") == "g5a"
        and profile.get("party_size") in (1, 4)
        and profile.get("scenario_id") == "g5a-ally-p%d" % profile.get("party_size")
    )
    if key not in REQUIRED_KEYS and not g5t_named_key and not g5a_named_key:
        return {"run_dir": str(run_dir), "manifest": manifest, "error": "unknown_matrix_key", "integrity": integrity}
    report = loaded.get("report") or {}
    if scenario.get("sha256") != hashlib.sha256(
            json.dumps(profile, sort_keys=True).encode("utf-8")).hexdigest():
        integrity["failures"].append("manifest:scenario_profile_hash_mismatch")
    before_party = (before or {}).get("records", {}).get("party_tracker.json", {})
    expected_roster = before_party.get("partyMembers")
    manifest_party = manifest.get("party", {})
    if (manifest_party.get("size") != profile["party_size"] or
            manifest_party.get("roster") != expected_roster or
            not isinstance(expected_roster, list) or len(expected_roster) != profile["party_size"]):
        integrity["failures"].append("manifest:party_identity_mismatch")
    if manifest.get("seed", {}).get("roster") != expected_roster:
        integrity["failures"].append("manifest:seed_party_identity_mismatch")
    actual_encounter = (before or {}).get("records", {}).get("selected_encounter", {})
    if (manifest.get("seed", {}).get("active_encounter") != actual_encounter.get("encounterId") or
            actual_encounter.get("status") != "ok"):
        integrity["failures"].append("manifest:selected_seed_encounter_mismatch")
    normalized_seed = dict(profile.get("seed", {}))
    normalized_seed.pop("resume_phase", None)
    seed_hash = hashlib.sha256(json.dumps(normalized_seed, sort_keys=True).encode("utf-8")).hexdigest()
    if manifest.get("seed", {}).get("seed_profile_sha256") != seed_hash or manifest.get("seed", {}).get("seed_id") != seed_hash:
        integrity["failures"].append("manifest:seed_profile_mismatch")
    if manifest.get("seed", {}).get("profile_seed") != normalized_seed:
        integrity["failures"].append("manifest:seed_profile_content_mismatch")
    observations = loaded.get("observations", [])
    artifacts["trace_position_errors"] = loaded.get("trace_position_errors", [])
    artifacts["trace_provider_events"] = loaded.get("trace_provider_events", [])
    saved_checks = loaded.get("checks", {})
    checks_reference = artifacts.get("checks")
    if checks_reference:
        saved_checks, checks_error = load_bundle_json(run_dir, checks_reference)
        if checks_error:
            integrity["failures"].append("checks:%s" % checks_error)
    g5a_metadata = manifest.get("g5a") if profile.get("gate") == "g5a" else None
    g5a_sandbox_identity = (
        manifest.get("configuration", {}).get("ally_controller")
        if profile.get("gate") == "g5a" else None
    )
    checks = (observed_checks(
        profile, before, after or {}, artifacts, steps, observations,
        run_dir=run_dir, g5a_metadata=g5a_metadata,
        g5a_sandbox_identity=g5a_sandbox_identity,
    ) if before and after else [])
    if step_errors:
        checks.append({"id": "all_step_snapshots_readable", "required": True,
                       "expected": "complete before/after snapshot pair for each sent step",
                       "observed": step_errors, "status": "BLOCKED", "evidence": "manifest artifact step refs"})
    if not isinstance(saved_checks, dict) or saved_checks.get("checks") != checks:
        integrity["failures"].append("checks:derived_result_mismatch")
    if resume_chain is not None and profile["scenario_id"] == "resume-replay" and profile.get("phase") == "replay":
        artifacts["resume_chain"] = resume_chain
        checks = observed_checks(profile, before, after or {}, artifacts, steps, observations,
                                 run_dir=run_dir)
    artifacts["required_evidence_status"] = (
        "non_applicable" if _non_applicable_replay_trace(manifest, artifacts, loaded)
        else report.get("status", "missing")
    )
    evaluated = evaluate_evidence(manifest, checks, artifacts, run_dir=run_dir,
                                  integrity=integrity, profile=profile)
    return {"run_dir": str(run_dir), "manifest": manifest, "checks": checks, "integrity": integrity,
            "evaluation": evaluated, "matrix_key": key}


def evaluate_matrix(run_rows: Iterable[Any]) -> Dict[str, Any]:
    """Validate actual bundle files and checks before aggregating the 18 cases."""
    run_dirs: List[Path] = []
    invalid_runs: List[str] = []
    for row in run_rows:
        try:
            candidate = Path(row.get("run_dir")) if isinstance(row, dict) and row.get("run_dir") else Path(row)
        except (TypeError, ValueError):
            invalid_runs.append("invalid_run_directory_input")
            continue
        if not _inside(candidate, RUN_ROOT) or candidate.resolve() == RUN_ROOT.resolve():
            invalid_runs.append("unsafe_run_directory")
            continue
        run_dirs.append(candidate)
    by_key: Dict[str, Dict[str, Any]] = {}
    duplicate_keys: List[str] = []
    raw: Dict[str, Dict[str, Any]] = {}
    for directory in run_dirs:
        result = _load_run_evidence(directory)
        key = result.get("matrix_key")
        if not key:
            invalid_runs.append("%s:%s" % (directory.name, result.get("error", "invalid_run")))
            continue
        if key in raw:
            duplicate_keys.append(key)
        else:
            raw[key] = result
    chain_results: Dict[int, Dict[str, Any]] = {}
    for party in (1, 4):
        complete_key, replay_key = ("resume-replay:complete:p%d" % party,
                                    "resume-replay:replay:p%d" % party)
        complete_row, replay_row = raw.get(complete_key), raw.get(replay_key)
        if complete_row and replay_row:
            complete_manifest = complete_row.get("manifest") or {}
            replay_manifest = replay_row.get("manifest") or {}
            complete_artifacts = complete_manifest.get("artifacts", {})
            replay_artifacts = replay_manifest.get("artifacts", {})
            cdir, rdir = Path(complete_row["run_dir"]), Path(replay_row["run_dir"])
            complete_after, err1 = load_bundle_json(cdir, complete_artifacts.get("after_snapshot"))
            replay_before, err2 = load_bundle_json(rdir, replay_artifacts.get("before_snapshot"))
            replay_after, err3 = load_bundle_json(rdir, replay_artifacts.get("after_snapshot"))
            complete_manifest["snapshot_chain"] = {
                "after_projection": (complete_after or {}).get("mechanical_projection"),
                "after_history_inventory": _history_inventory(complete_after or {}),
            }
            replay_manifest["snapshot_chain"] = {
                "before_projection": (replay_before or {}).get("mechanical_projection"),
                "after_projection": (replay_after or {}).get("mechanical_projection"),
                "before_history_inventory": _history_inventory(replay_before or {}),
                "after_history_inventory": _history_inventory(replay_after or {}),
            }
            chain = compare_resume_chain(complete_manifest, replay_manifest)
            if err1 or err2 or err3:
                chain["status"] = "FAIL"
                chain["mismatched_identity_fields"].append("resume_snapshot_artifact")
            chain_results[party] = chain
            replay_row["resume_chain"] = chain
            # Re-evaluate replay from real bundle observations with the linked chain.
            raw[replay_key] = _load_run_evidence(rdir, resume_chain=chain)
    for key, result in raw.items():
        by_key[key] = result
    missing = sorted(set(REQUIRED_KEYS) - set(by_key))
    blocked = sorted(key for key, result in by_key.items()
                     if result.get("evaluation", {}).get("automated_status") != "READY_FOR_PRIMARY_REVIEW")
    failed = sorted(key for key, result in by_key.items()
                    if result.get("evaluation", {}).get("automated_status") == "FAIL")
    synthetic = sorted(key for key, result in by_key.items()
                       if not (result.get("manifest") or {}).get("live_eligible"))
    chain_failures = ["p%d:%s" % (party, ",".join(result.get("mismatched_identity_fields", [])))
                      for party, result in chain_results.items() if result.get("status") != "PASS"]
    issues = missing or duplicate_keys or blocked or failed or synthetic or chain_failures or invalid_runs
    return {"automated_status": "BLOCKED" if issues else "READY_FOR_PRIMARY_REVIEW",
            "primary_verdict": "PENDING", "required_keys": list(REQUIRED_KEYS),
            "observed_keys": sorted(by_key), "missing_required_keys": missing,
            "duplicate_keys": sorted(set(duplicate_keys)), "not_ready_keys": blocked,
            "failed_keys": failed, "synthetic_keys": synthetic,
            "invalid_run_bundles": invalid_runs,
            "resume_chain_failures": chain_failures,
            "runs": {key: result.get("evaluation") for key, result in by_key.items()}}


def _g4_expected_profile(scenario: str, party: int) -> Optional[Dict[str, Any]]:
    if scenario not in ("narrator-dialogue-travel", "combat-smoke") or party not in (1, 4):
        return None
    if __package__:
        from scripts.combat_latency_fixtures import build_gate_profile
    else:
        from combat_latency_fixtures import build_gate_profile
    profile = build_gate_profile("g4", scenario, party)
    contract = {key: profile.get(key) for key in
                ("scenario_id", "party_size", "branch", "phase", "seed", "applicability")}
    contract["gate"] = "g4"
    return {"profile": profile, "contract": contract}


def _g4_transcript_counts(transcript: str) -> Dict[str, Any]:
    """Count control/step/health facts from transcript lines, not manifest claims."""
    lines = transcript.splitlines()
    starts = [line for line in lines if re.search(r"\[driver\] step=\d+ start ", line)]
    dones = [line for line in lines if re.search(r"\[driver\] step=\d+ done ", line)]
    active_responses = [line for line in lines if "[driver] set_active character=" in line]
    active_failures = [line for line in lines if "[driver] [WARN] set_active request failed" in line]
    active_rejections = [line for line in active_responses if "success=False" in line]
    active_attempts = len(active_responses) + len(active_failures)
    start_controls = sum("start_game emitted;" in line for line in lines)
    health_reads = sum("[health] read-only /api/party " in line for line in lines)
    timeouts = sum(bool(re.search(r"step=\d+ timeout=yes", line)) for line in lines)
    caps = sum("turn cap reached" in line for line in lines)
    idle_caps = sum("idle settle cap reached" in line for line in lines)
    send_failures = sum(" emit " in line and " failed:" in line for line in lines)
    blocked_steps = sum("G4 input bound exceeded" in line or "scenario step bound exceeded" in line
                        for line in lines)
    blocked_controls = sum("bound exceeded" in line and "input bound" not in line for line in lines)
    step_rows = []
    transcript_backend_outputs = 0
    current_input = None
    for line in starts:
        match = re.search(r"step=(\d+) start label=.*? character=([^ ]+) input=(.*)$", line)
        if not match:
            step_rows.append(None)
        else:
            step_rows.append({"step": int(match.group(1)), "character": match.group(2),
                              "input": match.group(3)})
    for line in lines:
        start_match = re.search(r"\[driver\] step=\d+ start label=.*? character=([^ ]+) input=(.*)$", line)
        if start_match:
            current_input = start_match.group(2)
            continue
        if re.search(r"\[driver\] step=\d+ done ", line):
            current_input = None
            continue
        if current_input is not None and "[game_output] type=" in line:
            event = re.search(r"\[game_output\] type=([^ ]+).*?content=(.*)$", line)
            if event:
                output_type, content = event.group(1).casefold().replace("_", "-"), event.group(2)
                if (output_type not in ("user-input", "echo", "system", "startup") and content.strip()
                        and content.strip().casefold() != current_input.strip().casefold()):
                    transcript_backend_outputs += 1
    return {
        "step_starts": len(starts), "step_completions": len(dones), "steps": step_rows,
        "backend_output_count": transcript_backend_outputs,
        "start_controls": start_controls, "active_switch_attempts": active_attempts,
        "active_switch_requests_sent": len(active_responses), "health_reads": health_reads,
        "timeouts": timeouts, "step_caps_reached": caps, "idle_settle_caps_reached": idle_caps,
        "blocked_step_attempts": blocked_steps, "blocked_control_attempts": blocked_controls,
        "control_request_failures": len(active_failures) + send_failures,
        "control_request_attempts": start_controls + len(starts) + active_attempts,
        "control_request_calls": start_controls + len(starts) + active_attempts,
        "control_requests_sent": start_controls + len(starts) + len(active_responses),
        "active_switch_failures": len(active_failures) + len(active_rejections),
    }


def _g4_counts_match_raw(manifest: Dict[str, Any], transcript: str,
                         steps: List[Dict[str, Any]]) -> List[str]:
    counts = manifest.get("counts", {})
    observed = _g4_transcript_counts(transcript)
    errors = []
    counter_names = (
        "step_attempts", "steps_sent", "backend_output_count", "control_request_attempts",
        "control_request_calls", "control_request_failures", "control_requests_sent",
        "active_switch_attempts", "active_switch_requests_sent", "blocked_step_attempts",
        "blocked_control_attempts", "timeouts", "step_caps_reached", "idle_settle_caps_reached",
        "active_switch_failures", "health_read_attempts", "exit_health_read_attempts",
    )
    for name in counter_names:
        value = counts.get(name)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            errors.append("count_invalid:%s" % name)
    expected = {
        "step_attempts": observed["step_starts"], "steps_sent": observed["step_starts"],
        "control_request_attempts": observed["control_request_attempts"],
        "control_request_calls": observed["control_request_calls"],
        "control_request_failures": observed["control_request_failures"],
        "control_requests_sent": observed["control_requests_sent"],
        "active_switch_attempts": observed["active_switch_attempts"],
        "active_switch_requests_sent": observed["active_switch_requests_sent"],
        "blocked_step_attempts": observed["blocked_step_attempts"],
        "blocked_control_attempts": observed["blocked_control_attempts"],
        "timeouts": observed["timeouts"], "step_caps_reached": observed["step_caps_reached"],
        "idle_settle_caps_reached": observed["idle_settle_caps_reached"],
        "active_switch_failures": observed["active_switch_failures"],
        "health_read_attempts": observed["health_reads"], "exit_health_read_attempts": 0,
    }
    backend_count = 0
    for row in steps:
        observation = (row.get("after") or {}).get("observation", {})
        value = observation.get("backend_output_count")
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            errors.append("step_backend_output_count_missing")
        else:
            backend_count += value
    expected["backend_output_count"] = observed["backend_output_count"]
    if backend_count != observed["backend_output_count"]:
        errors.append("step_transcript_backend_output_mismatch")
    provider_count = (counts.get("provider_calls") or {}).get("count") if isinstance(
        counts.get("provider_calls"), dict) else None
    if not isinstance(provider_count, int) or isinstance(provider_count, bool) or provider_count < 0:
        errors.append("provider_call_count_invalid")
    if observed["step_starts"] != observed["step_completions"]:
        errors.append("transcript_step_completion_mismatch")
    if any(row is None for row in observed["steps"]):
        errors.append("transcript_step_identity_malformed")
    for name, value in expected.items():
        if counts.get(name) != value:
            errors.append("count_transcript_mismatch:%s" % name)
    startup = manifest.get("artifacts", {}).get("startup_readiness", {})
    start_timed_out = bool(startup.get("timed_out")) or startup.get("status") in (
        "timeout", "ready_quiet_timeout", "unavailable")
    if counts.get("start_timeout") is not start_timed_out:
        errors.append("start_timeout_transcript_mismatch")
    return errors


def _evaluate_g4_bundle(run_dir: Path) -> Dict[str, Any]:
    """Derive one G4 candidate entirely from retained bundle bytes and state."""
    manifest, error = load_bundle_json(run_dir, "manifest.json")
    if error or manifest is None:
        return {"run_dir": str(run_dir), "error": "manifest:%s" % (error or "missing")}
    scenario = (manifest.get("scenario") or {}).get("id")
    party = (manifest.get("party") or {}).get("size")
    expected = _g4_expected_profile(scenario, party)
    if expected is None or manifest.get("gate") != "g4":
        return {"run_dir": str(run_dir), "error": "wrong_gate_or_profile"}
    key = matrix_key(scenario, party)
    profile = expected["profile"]
    contract = expected["contract"]
    problems: List[str] = []
    artifacts = manifest.get("artifacts", {})
    integrity = _artifact_integrity(run_dir, manifest, artifacts)
    hashes = manifest.get("artifact_sha256", {})
    for ref in [artifacts.get(name) for name in
                ("transcript", "server_log", "trace", "report", "before_snapshot", "after_snapshot", "checks")]:
        path, ref_error = _bundle_file(run_dir, ref)
        if ref_error or path is None:
            problems.append("artifact_missing_or_unsafe")
            continue
        raw, read_error = _safe_read_bytes(path, run_dir)
        if read_error or raw is None or hashes.get(ref) != hashlib.sha256(raw).hexdigest():
            problems.append("artifact_hash_or_bytes_mismatch")
    problems.extend(integrity.get("failures", []))
    profile_hash = hashlib.sha256(json.dumps(contract, sort_keys=True).encode("utf-8")).hexdigest()
    if ((manifest.get("scenario") or {}).get("profile_contract") != contract or
            (manifest.get("scenario") or {}).get("sha256") != profile_hash):
        problems.append("profile_identity_mismatch")
    seeded_profile = dict(profile.get("seed", {}))
    if manifest.get("seed", {}).get("profile_seed") != seeded_profile:
        problems.append("seed_profile_mismatch")
    seed_hash = hashlib.sha256(json.dumps(seeded_profile, sort_keys=True).encode("utf-8")).hexdigest()
    if (manifest.get("seed", {}).get("seed_id") != seed_hash or
            manifest.get("seed", {}).get("seed_profile_sha256") != seed_hash):
        problems.append("seed_identity_mismatch")
    counts, bounds = manifest.get("counts", {}), manifest.get("bounds", {})
    exact_bounds = {"max_inputs": profile["max_inputs"], "max_controls": profile["max_controls"],
                    "max_health_reads": 3, "turn_timeout_seconds": 300}
    if any(bounds.get(name) != value or isinstance(bounds.get(name), bool)
           for name, value in exact_bounds.items()):
        problems.append("bounds_mismatch")
    for name in ("steps_sent", "control_requests_sent", "health_read_attempts", "timeouts",
                 "step_caps_reached", "blocked_step_attempts", "blocked_control_attempts"):
        if not _finite_number(counts.get(name)):
            problems.append("count_missing_or_nonfinite:%s" % name)
    if (counts.get("steps_sent", 0) > profile["max_inputs"] or
            counts.get("control_requests_sent", 0) > profile["max_controls"] or
            counts.get("health_read_attempts", 0) > 3):
        problems.append("bound_exceeded")
    if any(counts.get(name, 0) for name in
           ("timeouts", "start_timeout", "step_caps_reached", "idle_settle_caps_reached",
            "blocked_step_attempts", "blocked_control_attempts")):
        problems.append("timeout_or_cap_observed")
    if manifest.get("evidence_kind") != "live-candidate" or manifest.get("live_eligible") is not True:
        problems.append("synthetic_or_ineligible_evidence")
    if manifest.get("transport", {}).get("client_source") != "socketio.Client":
        problems.append("synthetic_transport")
    source = manifest.get("source", {})
    hashes_by_source = source.get("relevant_source_sha256")
    current_source = _source_identity()
    if (not isinstance(source.get("head"), str) or
            not re.fullmatch(r"[0-9a-f]{40,64}", source.get("head", "")) or
            not isinstance(hashes_by_source, dict) or not hashes_by_source or
            any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value)
                for value in hashes_by_source.values())):
        problems.append("source_identity_missing_or_invalid")
    elif source != current_source:
        problems.append("source_identity_stale_or_mismatched")
    snapshot_names = ("before_snapshot", "after_snapshot")
    snapshots = {}
    for name in snapshot_names:
        snapshots[name], load_error = load_bundle_json(run_dir, artifacts.get(name))
        if load_error or not isinstance(snapshots[name], dict):
            problems.append("snapshot_missing:%s" % name)
    if all(isinstance(snapshots.get(name), dict) for name in snapshot_names):
        before, after = snapshots["before_snapshot"], snapshots["after_snapshot"]
        steps, step_errors = load_step_snapshots(run_dir, manifest)
        if step_errors:
            problems.append("step_snapshot_data_missing")
        transcript_path, transcript_error = _bundle_file(run_dir, artifacts.get("transcript"))
        transcript_text = ""
        if transcript_error or transcript_path is None:
            problems.append("transcript_missing")
        else:
            try:
                transcript_text = transcript_path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                problems.append("transcript_unreadable")
        problems.extend(_g4_counts_match_raw(manifest, transcript_text, steps))
        checks_doc, checks_error = load_bundle_json(run_dir, artifacts.get("checks"))
        raw_checks = checks_doc.get("checks") if isinstance(checks_doc, dict) else None
        if checks_error or not isinstance(raw_checks, list):
            problems.append("required_checks_missing_or_malformed")
        else:
            check_by_id = {row.get("id"): row for row in raw_checks if isinstance(row, dict)}
            failed_required = [row.get("id") for row in raw_checks if isinstance(row, dict)
                               and row.get("required") is True and row.get("status") != "PASS"]
            if failed_required:
                problems.append("required_check_failed_or_blocked:" + ",".join(sorted(map(str, failed_required))))
            if scenario == "narrator-dialogue-travel":
                combat_only = {"mechanical_apply_outcomes", "hp_delta_snapshot_reconciliation",
                               "selected_encounter_available", "final_response_validation_truth",
                               "accepted_logical_batch_once", "complete_unique_pc_roster",
                               "living_non_pc_roster", "active_pc_identity_per_step",
                               "phase_round_progression_observed", "deterministic_damage_exact_per_command",
                               "causal_trace_linkage", "ally_and_inactive_actual_batch_filter"}
                if any(check_by_id.get(name, {}).get("required") is not False or
                       check_by_id.get(name, {}).get("status") != "N/A" for name in combat_only):
                    problems.append("narrator_combat_checks_not_marked_not_applicable")
                for required_id in ("party_roster_identity", "required_trace",
                                    "g4_narrator_route_and_actor_observations",
                                    "g4_narrator_mira_backend_response"):
                    row = check_by_id.get(required_id)
                    if not row or row.get("required") is not True or row.get("status") != "PASS":
                        problems.append("g4_required_narrator_check_missing_or_unpassed:" + required_id)
            elif any(isinstance(row, dict) and row.get("required") is True and
                     row.get("status") == "N/A" for row in raw_checks):
                problems.append("combat_required_check_marked_not_applicable")
            if scenario == "combat-smoke":
                expected_ids = _required_check_ids({"scenario_id": scenario, "party_size": party})
                if expected_ids - set(check_by_id):
                    problems.append("combat_required_checks_missing:" + ",".join(
                        sorted(expected_ids - set(check_by_id))))
        roster = ["Acheron"] if party == 1 else ["Acheron", "Merisiel", "Kira", "Vitreol"]
        if ((manifest.get("party") or {}).get("roster") != roster or
                (manifest.get("seed") or {}).get("roster") != roster):
            problems.append("manifest_roster_identity_mismatch")
        for snapshot in (before, after):
            party_record = snapshot.get("records", {}).get("party_tracker.json", {})
            projection = snapshot.get("g4_read_only_projection", {})
            if (party_record.get("status") != "ok" or party_record.get("partyMembers") != roster or
                    projection.get("partyMembers") != roster or
                    projection.get("active_character") not in roster):
                problems.append("observed_roster_or_active_pc_mismatch")
            if _snapshot_required_errors(snapshot, manifest) or snapshot.get("numeric_errors"):
                problems.append("snapshot_required_data_missing")
        before_enc = before.get("records", {}).get("selected_encounter", {})
        if scenario == "combat-smoke":
            encounter = "capture_one_pc" if party == 1 else "capture_mp"
            enemies = ["Goblin"] if party == 1 else ["Goblin Alpha", "Goblin Beta"]
            observed_enemies = [row.get("name") for row in before_enc.get("creatures", [])
                                if isinstance(row, dict) and row.get("type") == "enemy"]
            if before_enc.get("status") != "ok" or before_enc.get("encounterId") != encounter or observed_enemies != enemies:
                problems.append("seed_or_encounter_identity_mismatch")
        else:
            projections = manifest.get("g4_step_projections")
            turns = profile.get("turns")
            if not isinstance(turns, list) or len(turns) != 5 or not isinstance(projections, list) or len(projections) != len(turns):
                problems.append("narrator_step_data_missing")
            else:
                startup_location = profile.get("seed", {}).get("starting_location_id")
                first_before = steps[0].get("before", {}) if steps else {}
                first_before_projection = first_before.get("g4_read_only_projection", {})
                if (startup_location != "CA01" or
                        first_before_projection.get("currentLocationId") != startup_location):
                    problems.append("narrator_startup_location_mismatch")
                transcript_steps = _g4_transcript_counts(transcript_text).get("steps", [])
                for index, (row, turn) in enumerate(zip(projections, turns)):
                    room, actor = turn.get("expected_location_id"), turn.get("character")
                    observed = (row.get("projection") or {}).get("observed", {})
                    step_after = steps[index].get("after", {}) if index < len(steps) else {}
                    step_before = steps[index].get("before", {}) if index < len(steps) else {}
                    persisted = (step_after.get("g4_read_only_projection") or {})
                    before_observation = step_before.get("observation", {})
                    after_observation = step_after.get("observation", {})
                    raw_outputs = after_observation.get("actual_backend_outputs", [])
                    raw_echoes = after_observation.get("input_echoes", [])
                    expected_line = next((item for item in transcript_steps if item and item.get("step") == index + 1), None)
                    if ((row.get("projection") or {}).get("status") != "PASS" or
                            row.get("kind") != turn.get("kind") or
                            row.get("label") != turn.get("label") or
                            row.get("expected_location_id") != room or
                            row.get("expected_active_character") != actor or
                            observed.get("currentLocationId") != room or
                            observed.get("active_character") != actor or
                            observed != persisted or
                            (step_after.get("records", {}).get("party_tracker.json", {}).get("active_character") != actor) or
                            (step_before.get("records", {}).get("party_tracker.json", {}).get("active_character") != actor) or
                            before_observation.get("character") != actor or
                            before_observation.get("input") != turn.get("input") or
                            expected_line is None or expected_line.get("character") != actor or
                            expected_line.get("input") != turn.get("input") or
                            row.get("actual_backend_outputs") != raw_outputs or
                            row.get("input_echoes") != raw_echoes):
                        problems.append("narrator_projection_mismatch:%d" % (index + 1))
                    if (len(raw_echoes) != 1 or not isinstance(raw_echoes[0], dict) or
                            raw_echoes[0].get("type") not in ("user-input", "user_input") or
                            raw_echoes[0].get("content") != turn.get("input") or
                            not _transcript_has_user_input(transcript_text, actor, turn.get("input", ""))):
                        problems.append("narrator_input_echo_transcript_mismatch:%d" % (index + 1))
                    for output in raw_outputs:
                        if (not isinstance(output, dict) or not isinstance(output.get("content"), str) or
                                not output.get("content") or output.get("content") not in transcript_text):
                            problems.append("backend_output_transcript_mismatch:%d" % (index + 1))
                mira_indexes = [index for index, turn in enumerate(turns) if turn.get("kind") == "mira_dialogue"]
                if len(mira_indexes) != 1:
                    problems.append("mira_backend_reply_missing_or_echo_only")
                else:
                    mira_index = mira_indexes[0]
                    mira_row = projections[mira_index]
                    mira_turn = turns[mira_index]
                    mira_outputs = mira_row.get("actual_backend_outputs", [])
                    mira_echoes = mira_row.get("input_echoes", [])
                    if (not any(isinstance(output, dict) and isinstance(output.get("content"), str)
                                and output.get("content", "").strip()
                                and output.get("content", "").strip().casefold() !=
                                str(mira_turn.get("input", "")).strip().casefold()
                                and output.get("content", "") in transcript_text
                                and str(output.get("type", "")).casefold() not in ("user-input", "echo", "system")
                                for output in mira_outputs) or mira_outputs == mira_echoes):
                        problems.append("mira_backend_reply_missing_or_echo_only")
        trace_ref = artifacts.get("trace")
        trace_path, trace_error = _bundle_file(run_dir, trace_ref)
        if trace_error or trace_path is None:
            problems.append("trace_missing")
        else:
            trace_rows, parse_errors = parse_trace_positions(trace_path,
                manifest.get("trace_span", {}).get("offset_before_bytes", 0))
            steps, step_errors = load_step_snapshots(run_dir, manifest)
            startup_span = manifest.get("g4_startup_trace_span")
            if (not isinstance(startup_span, dict) or
                    startup_span.get("offset_before_bytes") != manifest.get("trace_start_offset", {}).get("source_byte_offset") or
                    startup_span.get("offset_after_bytes", -1) > (steps[0].get("before", {}).get("observation", {})
                        .get("runtimeTrace", {}).get("offset_bytes", -1) if steps else -1)):
                problems.append("startup_receipt_span_missing_or_misaligned")
            readiness = startup_span.get("readiness", {}) if isinstance(startup_span, dict) else {}
            startup_outputs = readiness.get("output_count")
            if (not isinstance(startup_span, dict) or startup_span.get("status") != "captured" or
                    readiness.get("status") != "ready" or
                    readiness.get("processing_idle") is not True or
                    readiness.get("idle_status_observed") is not True or
                    not isinstance(startup_outputs, int) or isinstance(startup_outputs, bool) or
                    startup_outputs < 1 or counts.get("start_timeout") is not False):
                problems.append("startup_readiness_missing_or_invalid")
            paired = pair_g4_receipts(trace_rows, steps, startup_span, scenario)
            if parse_errors or step_errors or paired.get("status") != "ok":
                if paired.get("reason") in ("receipt_task_outside_scenario_scope",
                                             "receipt_on_deterministic_combat_fast_path"):
                    problems.append("actual_receipt_identity_mismatch")
                problems.append("actual_receipt_or_step_data_missing")
            else:
                paired_rows = paired.get("receipts", [])
                paired_legacy = paired.get("legacy_observations", [])
                provider_count = (counts.get("provider_calls") or {}).get("count")
                if provider_count != sum(1 for row in trace_rows if row.get("event_type") == "provider"):
                    problems.append("provider_count_trace_mismatch")
                provider_counts = counts.get("provider_calls", {})
                if (provider_counts.get("core_receipts") != len(paired_rows) or
                        provider_counts.get("legacy_provider_observations") != len(paired_legacy) or
                        provider_count != len(paired_rows) + len(paired_legacy)):
                    problems.append("provider_accounting_reconciliation_mismatch")
                for linked in paired.get("receipts", []):
                    receipt = linked.get("receipt", {})
                    if receipt.get("fallback") is not False:
                        problems.append("unexpected_or_unknown_fallback")
                    if receipt.get("provider") != "openai" or not receipt.get("resolved_model") or not receipt.get("task"):
                        problems.append("actual_receipt_identity_mismatch")
                    if receipt.get("cost_label") not in ("actual", "estimated", "unpriced_unknown"):
                        problems.append("unsupported_cost_provenance")
                    reported = receipt.get("provider_reported_cost_usd")
                    provenance = receipt.get("cost_provenance")
                    estimate = receipt.get("cost_usd")
                    if reported is not None:
                        if (not _finite_number(reported) or reported < 0 or provenance != "actual" or
                                receipt.get("cost_label") != "actual"):
                            problems.append("unsupported_actual_cost_claim")
                    elif provenance == "estimated":
                        if (not _finite_number(estimate) or estimate < 0 or
                                receipt.get("cost_label") != "estimated"):
                            problems.append("unsupported_estimated_cost_claim")
                    elif (provenance not in ("unpriced", "unpriced_unknown") or
                          receipt.get("cost_label") != "unpriced_unknown"):
                        problems.append("unknown_cost_not_explicitly_unpriced")
                manifest_receipts = (manifest.get("configuration", {}).get("actual_runtime", {})
                                     .get("receipts"))
                actual_runtime = manifest.get("configuration", {}).get("actual_runtime", {})
                if manifest_receipts != paired_rows:
                    problems.append("receipt_manifest_projection_mismatch")
                if actual_runtime.get("legacy_observations") != paired_legacy:
                    problems.append("legacy_observation_manifest_projection_mismatch")
                providers = sorted({row.get("receipt", {}).get("provider") for row in paired_rows})
                models = sorted({row.get("receipt", {}).get("resolved_model") for row in paired_rows})
                if (actual_runtime.get("provider") != providers or
                        actual_runtime.get("response_model") != models or
                        actual_runtime.get("status") != "ok"):
                    problems.append("actual_runtime_profile_identity_mismatch")
                if scenario == "narrator-dialogue-travel":
                    turns = profile.get("turns", [])
                    mira_index = next((index for index, row in enumerate(turns)
                                       if row.get("kind") == "mira_dialogue"), None)
                    if (mira_index is None or not any(row.get("step") == mira_index + 1 and
                            row.get("receipt", {}).get("task") == "dm_main" for row in paired_rows)):
                        problems.append("narrator_mira_sdk_receipt_missing")
                elif scenario == "combat-smoke":
                    if not any(isinstance(row.get("step"), int) and
                               not str(steps[row["step"] - 1].get("before", {}).get("observation", {})
                                       .get("input", "")).lstrip().startswith(("/att", "/dmg"))
                               for row in paired_rows):
                        problems.append("combat_nondeterministic_sdk_receipt_missing")
    problems = sorted(set(problems))
    observed_failure_prefixes = (
        "profile_identity_mismatch", "seed_profile_mismatch", "seed_identity_mismatch",
        "manifest_roster_identity_mismatch", "observed_roster_or_active_pc_mismatch",
        "seed_or_encounter_identity_mismatch", "narrator_projection_mismatch:",
        "mira_backend_reply_missing_or_echo_only", "bounds_mismatch", "bound_exceeded",
        "timeout_or_cap_observed", "unexpected_or_unknown_fallback",
        "actual_receipt_identity_mismatch", "unsupported_actual_cost_claim",
        "unsupported_estimated_cost_claim", "unknown_cost_not_explicitly_unpriced",
        "actual_runtime_profile_identity_mismatch", "narrator_mira_sdk_receipt_missing",
        "combat_nondeterministic_sdk_receipt_missing",
        "count_transcript_mismatch:", "transcript_step_completion_mismatch",
        "narrator_input_echo_transcript_mismatch:", "backend_output_transcript_mismatch:",
        "provider_count_trace_mismatch",
        "required_check_failed_or_blocked:", "narrator_combat_checks_not_marked_not_applicable",
        "combat_required_check_marked_not_applicable", "g4_required_narrator_check_missing_or_unpassed:",
    )
    observed_failure = any(problem.startswith(observed_failure_prefixes) for problem in problems)
    return {"run_dir": str(run_dir), "matrix_key": key,
            "automated_status": "FAIL" if observed_failure else
            ("BLOCKED" if problems else "READY_FOR_PRIMARY_REVIEW"),
            "primary_verdict": "PENDING", "problems": problems}


def evaluate_g4_matrix(run_rows: Iterable[Any]) -> Dict[str, Any]:
    """Evaluate the fixed four-key G4 candidate matrix; never execute a capture."""
    seen: Dict[str, Dict[str, Any]] = {}
    duplicates: List[str] = []
    invalid: List[str] = []
    for row in run_rows:
        try:
            candidate = Path(row.get("run_dir")) if isinstance(row, dict) else Path(row)
        except (TypeError, ValueError):
            invalid.append("invalid_run_directory_input")
            continue
        if (not _inside(candidate, G4_RUN_ROOT) or candidate.resolve() == G4_RUN_ROOT.resolve()
                or _has_symlink_component(candidate, PROJECT_TMP)):
            invalid.append("unsafe_run_directory")
            continue
        result = _evaluate_g4_bundle(candidate)
        key = result.get("matrix_key")
        if not key:
            invalid.append("%s:%s" % (candidate.name, result.get("error", "invalid_bundle")))
        elif key in seen:
            duplicates.append(key)
        else:
            seen[key] = result
    missing = sorted(set(G4_REQUIRED_KEYS) - set(seen))
    blocked = sorted(key for key, row in seen.items() if row["automated_status"] != "READY_FOR_PRIMARY_REVIEW")
    failed = sorted(key for key, row in seen.items() if row["automated_status"] == "FAIL")
    issues = bool(missing or duplicates or blocked or invalid or set(seen) != set(G4_REQUIRED_KEYS))
    return {"automated_status": "BLOCKED" if issues else "READY_FOR_PRIMARY_REVIEW",
            "primary_verdict": "PENDING", "required_keys": list(G4_REQUIRED_KEYS),
            "observed_keys": sorted(seen), "missing_required_keys": missing,
            "duplicate_keys": sorted(set(duplicates)), "not_ready_keys": blocked,
            "failed_keys": failed,
            "invalid_run_bundles": invalid, "runs": seen}


def _group_g5r_after_runs(run_dirs: Iterable[Any]) -> tuple[Dict[int, List[Path]], List[str]]:
    """Group G5R run paths by their bounded, bundle-local party identity."""
    grouped: Dict[int, List[Path]] = {1: [], 4: []}
    rejected: List[str] = []
    for raw_path in run_dirs:
        try:
            candidate = Path(str(raw_path))
            if not candidate.is_absolute():
                candidate = PROJECT_ROOT / candidate
            if (not _inside(candidate, G5R_RUN_ROOT) or
                    candidate.resolve() == G5R_RUN_ROOT.resolve() or
                    _has_symlink_component(candidate, PROJECT_TMP)):
                rejected.append("unsafe_after_run:%s" % candidate.name)
                continue
            manifest, error = load_bundle_json(candidate, "manifest.json")
            party = manifest.get("party") if isinstance(manifest, dict) else None
            party_size = party.get("size") if isinstance(party, dict) else None
            if error or party_size not in grouped:
                rejected.append("after_run_party_identity_missing:%s" % candidate.name)
                continue
            grouped[party_size].append(candidate)
        except (OSError, RuntimeError, TypeError, ValueError):
            rejected.append("invalid_after_run_path")
    return grouped, rejected


def _group_g5t_after_runs(run_dirs: Iterable[Any]) -> tuple[Dict[int, List[Path]], List[str]]:
    """Group named G5T primary bundles by verified party/scenario identity."""
    grouped: Dict[int, List[Path]] = {1: [], 4: []}
    rejected: List[str] = []
    for raw_path in run_dirs:
        try:
            candidate = Path(str(raw_path))
            if not candidate.is_absolute():
                candidate = PROJECT_ROOT / candidate
            if (not _inside(candidate, G5T_RUN_ROOT) or
                    candidate.resolve() == G5T_RUN_ROOT.resolve() or
                    _has_symlink_component(candidate, PROJECT_TMP)):
                rejected.append("unsafe_after_run:%s" % candidate.name)
                continue
            manifest, error = load_bundle_json(candidate, "manifest.json")
            party = manifest.get("party") if isinstance(manifest, dict) else None
            scenario = manifest.get("scenario") if isinstance(manifest, dict) else None
            party_size = party.get("size") if isinstance(party, dict) else None
            expected_scenario = "g5t-commander-p%d" % party_size if party_size in grouped else None
            if (error or party_size not in grouped or not isinstance(scenario, dict) or
                    manifest.get("gate") != "g5t" or scenario.get("id") != expected_scenario):
                rejected.append("after_run_g5t_identity_missing:%s" % candidate.name)
                continue
            grouped[party_size].append(candidate)
        except (OSError, RuntimeError, TypeError, ValueError):
            rejected.append("invalid_after_run_path")
    return grouped, rejected


def _group_g5a_runs(run_dirs: Iterable[Any]) -> tuple[Dict[int, List[Path]], List[str]]:
    """Group G5A bundles by fixed, bundle-local party/scenario identity."""
    grouped: Dict[int, List[Path]] = {1: [], 4: []}
    rejected: List[str] = []
    for raw_path in run_dirs:
        try:
            candidate = Path(str(raw_path))
            if not candidate.is_absolute():
                candidate = PROJECT_ROOT / candidate
            if (not _inside(candidate, G5A_RUN_ROOT) or
                    candidate.resolve() == G5A_RUN_ROOT.resolve() or
                    _has_symlink_component(candidate, PROJECT_TMP)):
                rejected.append("unsafe_g5a_run:%s" % candidate.name)
                continue
            manifest, error = load_bundle_json(candidate, "manifest.json")
            party = manifest.get("party") if isinstance(manifest, dict) else None
            scenario = manifest.get("scenario") if isinstance(manifest, dict) else None
            party_size = party.get("size") if isinstance(party, dict) else None
            expected_scenario = (
                "g5a-ally-p%d" % party_size
                if type(party_size) is int and party_size in grouped else None
            )
            if (error or type(party_size) is not int or party_size not in grouped or
                    not isinstance(scenario, dict) or
                    manifest.get("gate") != "g5a" or
                    scenario.get("id") != expected_scenario or
                    manifest.get("run_id") != candidate.name):
                rejected.append("g5a_identity_missing_or_mismatched:%s" % candidate.name)
                continue
            grouped[party_size].append(candidate)
        except (OSError, RuntimeError, TypeError, ValueError):
            rejected.append("invalid_g5a_run_path")
    return grouped, rejected


def evaluate_g5a_matrix(run_dirs: Iterable[Any]) -> Dict[str, Any]:
    """Evaluate exactly three isolated primary G5A bundles for each party size."""
    grouped, rejected = _group_g5a_runs(run_dirs)
    blocking_reasons = list(rejected)
    failed_runs: List[str] = []
    seen_paths: set[str] = set()
    seen_run_ids: set[str] = set()
    run_rows: List[Dict[str, Any]] = []
    party_rows: Dict[int, Dict[str, Any]] = {}
    source_signatures: List[tuple[str, str, str, str]] = []

    for party_size in (1, 4):
        paths = grouped[party_size]
        if len(paths) != 3:
            blocking_reasons.append("p%d_requires_exactly_three_bundles" % party_size)
        accepted_statuses = []
        cover_statuses = []
        directive_cover_observations = []
        party_run_rows = []
        for run_dir in paths:
            resolved_path = str(run_dir.resolve())
            if resolved_path in seen_paths:
                blocking_reasons.append("duplicate_run_path:%s" % run_dir.name)
            seen_paths.add(resolved_path)
            bundle = _load_run_evidence(run_dir)
            manifest = bundle.get("manifest") if isinstance(bundle, dict) else None
            if not isinstance(manifest, dict):
                blocking_reasons.append("p%d_invalid_bundle:%s" % (party_size, run_dir.name))
                run_rows.append({"run_dir": str(run_dir), "party_size": party_size,
                                 "automated_status": "BLOCKED",
                                 "error": bundle.get("error") if isinstance(bundle, dict) else "invalid_bundle"})
                continue

            run_id = manifest.get("run_id")
            if not isinstance(run_id, str) or run_id != run_dir.name or run_id in seen_run_ids:
                blocking_reasons.append("duplicate_or_mismatched_run_id:%s" % run_dir.name)
            if isinstance(run_id, str):
                seen_run_ids.add(run_id)
            source = manifest.get("source")
            hashes = source.get("relevant_source_sha256") if isinstance(source, dict) else None
            head = source.get("head") if isinstance(source, dict) else None
            dirty_digest = source.get("relevant_dirty_sha256") if isinstance(source, dict) else None
            source_hashes_valid = (
                isinstance(hashes, dict) and bool(hashes) and
                all(isinstance(path, str) and path and isinstance(digest, str) and
                    re.fullmatch(r"[0-9a-f]{64}", digest) is not None
                    for path, digest in hashes.items())
            )
            source_digest = (hashlib.sha256(json.dumps(
                hashes, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")).hexdigest() if source_hashes_valid else None)
            prompt_hashes = manifest.get("prompt_identity_sha256")
            expected_prompt_count = len(_prompt_identity())
            prompt_hashes_valid = (
                isinstance(prompt_hashes, dict) and
                len(prompt_hashes) == expected_prompt_count and
                all(isinstance(path, str) and path and isinstance(digest, str) and
                    re.fullmatch(r"[0-9a-f]{64}", digest) is not None
                    for path, digest in prompt_hashes.items())
            )
            prompt_digest = (hashlib.sha256(json.dumps(
                prompt_hashes, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")).hexdigest() if prompt_hashes_valid else None)
            if (not isinstance(head, str) or not re.fullmatch(r"[0-9a-f]{40,64}", head) or
                    not isinstance(dirty_digest, str) or
                    not re.fullmatch(r"[0-9a-f]{64}", dirty_digest) or
                    not isinstance(source_digest, str) or
                    not isinstance(prompt_digest, str)):
                blocking_reasons.append("p%d_source_identity_missing:%s" % (party_size, run_dir.name))
                if not isinstance(prompt_digest, str):
                    blocking_reasons.append("p%d_prompt_identity_missing:%s" %
                                            (party_size, run_dir.name))
            else:
                source_signatures.append((head, dirty_digest, source_digest, prompt_digest))

            evaluation = bundle.get("evaluation") if isinstance(bundle, dict) else None
            automated_status = (evaluation.get("automated_status")
                                if isinstance(evaluation, dict) else "BLOCKED")
            checks = evaluation.get("checks", []) if isinstance(evaluation, dict) else []
            checks_by_id = {row.get("id"): row.get("status") for row in checks
                            if isinstance(row, dict) and isinstance(row.get("id"), str)}
            accepted_status = checks_by_id.get("g5a_accepted_directive")
            cover_status = checks_by_id.get("g5a_directive_take_cover")
            accepted_statuses.append(accepted_status)
            cover_statuses.append(cover_status)
            directive_cover_observations.append((accepted_status, cover_status))
            if automated_status == "FAIL":
                failed_runs.append(run_id if isinstance(run_id, str) else run_dir.name)
            elif automated_status != "READY_FOR_PRIMARY_REVIEW":
                blocking_reasons.append("p%d_run_not_ready:%s" % (party_size, run_dir.name))
            if accepted_status is None or cover_status is None:
                blocking_reasons.append("p%d_required_ally_observation_missing:%s" %
                                        (party_size, run_dir.name))
            party_run = {
                "run_id": run_id,
                "run_dir": str(run_dir),
                "automated_status": automated_status,
                "accepted_directive_status": accepted_status,
                "applied_legal_take_cover_status": cover_status,
                "source_head": head,
                "source_digest": source_digest,
            }
            party_run_rows.append(party_run)
            run_rows.append(party_run)

        directive_observed = any(
            accepted == "PASS" and cover == "PASS"
            for accepted, cover in directive_cover_observations
        )
        cover_observed = any(status == "PASS" for status in cover_statuses)
        party_coverage_status = (
            "PASS" if directive_observed and cover_observed else
            "FAIL" if "FAIL" in accepted_statuses or "FAIL" in cover_statuses else
            "BLOCKED"
        )
        if not directive_observed:
            blocking_reasons.append("p%d_honored_directive_not_observed" % party_size)
        if not cover_observed:
            blocking_reasons.append("p%d_applied_legal_take_cover_not_observed" % party_size)
        party_rows[party_size] = {
            "required_runs": 3,
            "observed_runs": len(paths),
            "honored_directive_observed": directive_observed,
            "applied_legal_take_cover_observed": cover_observed,
            "coverage_status": party_coverage_status,
            "runs": party_run_rows,
        }

    same_source_revision = (len(source_signatures) == 6 and
                            len(set(source_signatures)) == 1)
    if source_signatures and not same_source_revision:
        blocking_reasons.append("runs_do_not_share_one_source_revision")
    elif len(source_signatures) != 6:
        blocking_reasons.append("source_revision_identity_incomplete")

    has_failure = bool(failed_runs) or any(
        row.get("coverage_status") == "FAIL" for row in party_rows.values()
    )
    automated_status = ("FAIL" if has_failure else
                        "BLOCKED" if blocking_reasons or any(
                            row.get("coverage_status") != "PASS" for row in party_rows.values()
                        ) else "READY_FOR_PRIMARY_REVIEW")
    return {
        "gate": "g5a",
        "automated_status": automated_status,
        "primary_verdict": "PENDING",
        "required_runs_per_party": 3,
        "required_party_sizes": [1, 4],
        "party_shapes": {str(size): party_rows[size] for size in (1, 4)},
        "same_source_revision": same_source_revision,
        "source_revision": (None if not same_source_revision or not source_signatures else {
            "head": source_signatures[0][0],
            "relevant_dirty_sha256": source_signatures[0][1],
            "relevant_source_sha256": source_signatures[0][2],
            "prompt_identity_sha256": source_signatures[0][3],
        }),
        "runs": run_rows,
        "failed_runs": sorted(set(failed_runs)),
        "blocking_reasons": sorted(set(blocking_reasons)),
    }


def main(argv: Optional[List[str]] = None) -> int:
    """Offline capture-bundle evaluation and provider-free gate comparisons."""
    import argparse
    parser = argparse.ArgumentParser(description="Validate existing capture evidence bundles offline")
    parser.add_argument("--gate", choices=("g3", "g4", "g5", "g5r", "g5t", "g5a", "g7", "g9", "g10"), default="g3")
    parser.add_argument("--run-dir", action="append",
                        help="one existing evidence bundle; repeat for matrix evaluation")
    parser.add_argument("--before", action="append", default=None,
                        help="G5/G5R before bundle; repeat once for P1 and once for P4")
    parser.add_argument("--after", action="append", default=None,
                        help="G5 after bundle, G5R run, or G5T primary run; G5T requires three per party shape")
    args = parser.parse_args(argv)
    if args.gate == "g7":
        if args.before or args.after:
            parser.error("--before/--after do not apply to G7")
        if not args.run_dir:
            parser.error("--run-dir is required for G7 matrix evaluation")
        result = evaluate_g7_matrix(args.run_dir)
        print(json.dumps(result, ensure_ascii=True, sort_keys=True, indent=2))
        return 0 if result.get("automated_status") == "READY_FOR_PRIMARY_REVIEW" else 2
    if args.gate == "g9":
        if args.before or args.after:
            parser.error("--before/--after do not apply to G9")
        if not args.run_dir:
            parser.error("--run-dir is required for G9 matrix evaluation")
        result = evaluate_g9_matrix(args.run_dir)
        print(json.dumps(result, ensure_ascii=True, sort_keys=True, indent=2))
        return 0 if result.get("automated_status") == "READY_FOR_PRIMARY_REVIEW" else 2
    if args.gate == "g10":
        if args.before or args.after:
            parser.error("--before/--after do not apply to G10")
        if not args.run_dir:
            parser.error("--run-dir is required for G10 matrix evaluation")
        result = evaluate_g10_matrix(args.run_dir)
        print(json.dumps(result, ensure_ascii=True, sort_keys=True, indent=2))
        return 0 if result.get("automated_status") == "READY_FOR_PRIMARY_REVIEW" else 2
    if args.gate == "g5a":
        if args.before or args.after:
            parser.error("--before/--after do not apply to G5A")
        if not args.run_dir:
            parser.error("--run-dir is required for G5A six-run aggregation")
        result = evaluate_g5a_matrix(args.run_dir)
        print(json.dumps(result, ensure_ascii=True, sort_keys=True, indent=2))
        return 0 if result.get("automated_status") == "READY_FOR_PRIMARY_REVIEW" else 2
    if args.gate == "g5":
        from scripts.combat_latency_report import evaluate_g5_comparison, render_g5_comparison

        result = evaluate_g5_comparison(args.before or [], args.after or [])
        if args.run_dir:
            result["automated_status"] = "BLOCKED"
            result["blocking_reasons"] = sorted(set(
                result.get("blocking_reasons", []) + ["g5_requires_explicit_before_and_after_roles"]
            ))
        print(json.dumps(result, ensure_ascii=True, sort_keys=True, indent=2))
        print(render_g5_comparison(result), file=sys.stderr)
        return 0 if result.get("automated_status") == "READY_FOR_PRIMARY_REVIEW" else 2
    if args.gate == "g5r":
        from scripts.combat_latency_report import evaluate_g5r_comparison, render_g5r_comparison

        grouped_after, rejected_after = _group_g5r_after_runs(args.after or [])
        result = evaluate_g5r_comparison(args.before or [], grouped_after)
        if args.run_dir:
            rejected_after.append("g5r_requires_explicit_before_and_after_roles")
        if rejected_after:
            reasons = result.get("blocking_reasons", [])
            result["blocking_reasons"] = sorted(set(reasons + rejected_after))
            if result.get("automated_status") != "FAIL":
                result["automated_status"] = "BLOCKED"
        print(json.dumps(result, ensure_ascii=True, sort_keys=True, indent=2))
        print(render_g5r_comparison(result), file=sys.stderr)
        return 0 if result.get("automated_status") == "READY_FOR_PRIMARY_REVIEW" else 2
    if args.gate == "g5t":
        from scripts.combat_latency_report import evaluate_g5t_comparison, render_g5t_comparison

        grouped_after, rejected_after = _group_g5t_after_runs(args.after or [])
        result = evaluate_g5t_comparison(grouped_after, run_root=G5T_RUN_ROOT)
        if args.run_dir:
            rejected_after.append("g5t_requires_explicit_before_and_after_roles")
        if args.before:
            rejected_after.append("g5t_primary_accepts_after_runs_only")
        if rejected_after:
            reasons = result.get("blocking_reasons", [])
            result["blocking_reasons"] = sorted(set(reasons + rejected_after))
            if result.get("automated_status") != "FAIL":
                result["automated_status"] = "BLOCKED"
        print(json.dumps(result, ensure_ascii=True, sort_keys=True, indent=2))
        print(render_g5t_comparison(result), file=sys.stderr)
        return 0 if result.get("automated_status") == "READY_FOR_PRIMARY_REVIEW" else 2
    if args.before is not None or args.after is not None:
        parser.error("--before/--after are available only with --gate g5, g5r, or g5t")
    if not args.run_dir:
        parser.error("--run-dir is required for G3/G4 evaluation")
    result = evaluate_g4_matrix(args.run_dir) if args.gate == "g4" else evaluate_matrix(args.run_dir)
    print(json.dumps(result, ensure_ascii=True, sort_keys=True, indent=2))
    return 0 if result.get("automated_status") == "READY_FOR_PRIMARY_REVIEW" else 2


if __name__ == "__main__":
    raise SystemExit(main())
