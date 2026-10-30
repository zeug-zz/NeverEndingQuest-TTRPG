# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Pure identity and receipt helpers for durable combat turn commits."""

# TABLETOP MODE: Keep turn identity and receipt data inside the combat domain.

import hashlib
import copy
import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

# TABLETOP MODE: Boundary hooks are inert unless sandbox fault injection is authorized.
from core.combat.turn_fault_injection import maybe_inject_combat_turn_fault


_APPLIED_ID_DOMAIN = "neq.combat.turn.applied-id.v1"
_APPLIED_ID_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_TURN_ID_PATTERN = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_COMMIT_TIMESTAMP_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$"
)
_REQUIRED_RECEIPT_FIELDS = frozenset({
    "schema_version",
    "turn_id",
    "applied_id",
    "encounter_id",
    "combat_round",
    "commit_timestamp",
})
_OPTIONAL_RECEIPT_FIELDS = frozenset({"position_deltas"})
_PROVIDER_MESSAGE_FIELDS = frozenset({
    "role",
    "content",
    "name",
    "tool_calls",
    "tool_call_id",
    "function_call",
})
COMBAT_TURN_COMMIT_MANIFEST_KEY = "_combat_turn_commit_manifest"
# TABLETOP MODE: Private command metadata is durable history, never provider content.
COMBAT_ALLY_DIRECTIVE_HISTORY_KEY = "_combat_ally_directive"
_COMMIT_MANIFEST_MAX_BYTES = 4 * 1024 * 1024
_COMMIT_MANIFEST_FIELDS = frozenset({
    "schema_version",
    "turn_id",
    "applied_id",
    "encounter_id",
    "path",
    "character_effects",
    "encounter_projection",
    "receipt",
    "staged_rewards",
    "success_narration",
})
_COMMIT_MANIFEST_RECEIPT_FIELDS = frozenset({
    "schema_version",
    "turn_id",
    "applied_id",
    "encounter_id",
    "combat_round",
})


def new_turn_id() -> str:
    """Return a canonical UUID string for one accepted user input."""
    return str(uuid.uuid4())


def _validate_turn_id(turn_id: Any) -> str:
    if not isinstance(turn_id, str) or not _TURN_ID_PATTERN.fullmatch(turn_id):
        raise ValueError("turn_id must be a UUID string")
    try:
        uuid.UUID(turn_id)
    except (ValueError, AttributeError) as exc:
        raise ValueError("turn_id must be a UUID string") from exc
    return turn_id


def _validate_applied_id(applied_id: Any) -> str:
    if not isinstance(applied_id, str) or not _APPLIED_ID_PATTERN.fullmatch(applied_id):
        raise ValueError("applied_id must use the lowercase sha256 form")
    return applied_id


def compute_applied_id(encounter_id: str, turn_id: str) -> str:
    """Derive the stable versioned applied ID for an encounter turn."""
    if not isinstance(encounter_id, str) or not encounter_id.strip():
        raise ValueError("encounter_id must be a non-empty string")
    normalized_turn_id = _validate_turn_id(turn_id)
    identity_bytes = (
        _APPLIED_ID_DOMAIN + "\0" + encounter_id + "\0" + normalized_turn_id
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(identity_bytes).hexdigest()


def build_accepted_input_record(content: str, *, turn_id: Optional[str] = None) -> Dict[str, str]:
    """Build the persisted user-history record carrying its private identity."""
    if not isinstance(content, str):
        raise TypeError("accepted input content must be a string")
    identity = _validate_turn_id(turn_id) if turn_id is not None else new_turn_id()
    return {"role": "user", "content": content, "turn_id": identity}


def conversation_history_for_prompt(history: List[Any]) -> List[Any]:
    """Return provider messages with only standard message fields preserved."""
    if not isinstance(history, list):
        raise TypeError("conversation history must be a list")
    visible_history = []
    for message in history:
        if isinstance(message, Mapping):
            # TABLETOP MODE: A private /cmd input record is projected only to its ally.
            if COMBAT_ALLY_DIRECTIVE_HISTORY_KEY in message:
                continue
            visible_history.append({
                key: value for key, value in message.items()
                if key in _PROVIDER_MESSAGE_FIELDS
            })
        else:
            visible_history.append(message)
    return visible_history


class CombatTurnManifestError(ValueError):
    """Explicit fail-closed error for invalid persisted turn manifests."""


def _validate_json_value(value: Any, *, depth: int = 0, nodes: Optional[List[int]] = None) -> None:
    """Reject non-JSON data, unsafe nesting, and pathological manifests."""
    if nodes is None:
        nodes = [0]
    nodes[0] += 1
    if nodes[0] > 100000 or depth > 64:
        raise CombatTurnManifestError("combat_turn_manifest_invalid:bounds")
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise CombatTurnManifestError("combat_turn_manifest_invalid:non_finite_number")
        return
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise CombatTurnManifestError("combat_turn_manifest_invalid:object_key")
            _validate_json_value(child, depth=depth + 1, nodes=nodes)
        return
    if isinstance(value, list):
        for child in value:
            _validate_json_value(child, depth=depth + 1, nodes=nodes)
        return
    raise CombatTurnManifestError("combat_turn_manifest_invalid:json_value")


def validate_combat_turn_commit_manifest(manifest: Any) -> Dict[str, Any]:
    """Validate and return a bounded, JSON-safe version-1 pending commit."""
    if not isinstance(manifest, Mapping):
        raise CombatTurnManifestError("combat_turn_manifest_invalid:object")
    if set(manifest) != _COMMIT_MANIFEST_FIELDS:
        raise CombatTurnManifestError("combat_turn_manifest_invalid:fields")
    _validate_json_value(manifest)
    try:
        encoded = json.dumps(
            manifest,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise CombatTurnManifestError("combat_turn_manifest_invalid:encoding") from exc
    if len(encoded) > _COMMIT_MANIFEST_MAX_BYTES:
        raise CombatTurnManifestError("combat_turn_manifest_invalid:bytes")

    if type(manifest.get("schema_version")) is not int or manifest["schema_version"] != 1:
        raise CombatTurnManifestError("combat_turn_manifest_invalid:schema_version")
    try:
        turn_id = _validate_turn_id(manifest.get("turn_id"))
        applied_id = _validate_applied_id(manifest.get("applied_id"))
    except (TypeError, ValueError) as exc:
        raise CombatTurnManifestError("combat_turn_manifest_invalid:identity") from exc
    encounter_id = manifest.get("encounter_id")
    if not isinstance(encounter_id, str) or not encounter_id.strip():
        raise CombatTurnManifestError("combat_turn_manifest_invalid:encounter_id")
    if applied_id != compute_applied_id(encounter_id, turn_id):
        raise CombatTurnManifestError("combat_turn_manifest_invalid:applied_id")
    if manifest.get("path") not in {"normal", "enemy_batch"}:
        raise CombatTurnManifestError("combat_turn_manifest_invalid:path")

    projection = manifest.get("encounter_projection")
    if not isinstance(projection, Mapping):
        raise CombatTurnManifestError("combat_turn_manifest_invalid:encounter_projection")
    projection_id = projection.get("encounterId", projection.get("id"))
    if projection_id != encounter_id:
        raise CombatTurnManifestError("combat_turn_manifest_invalid:projection_identity")
    combat_round = projection.get("combat_round", projection.get("current_round"))
    if (
        not isinstance(combat_round, int)
        or isinstance(combat_round, bool)
        or combat_round < 1
    ):
        raise CombatTurnManifestError("combat_turn_manifest_invalid:combat_round")
    if projection.get("combat_phase") not in {"PC_PHASE", "ENEMY_PHASE"}:
        raise CombatTurnManifestError("combat_turn_manifest_invalid:combat_phase")
    if not isinstance(projection.get("creatures"), list):
        raise CombatTurnManifestError("combat_turn_manifest_invalid:creatures")
    try:
        read_turn_receipts(projection)
    except (TypeError, ValueError) as exc:
        raise CombatTurnManifestError("combat_turn_manifest_invalid:projection_receipts") from exc

    receipt = manifest.get("receipt")
    if not isinstance(receipt, Mapping) or set(receipt) != _COMMIT_MANIFEST_RECEIPT_FIELDS:
        raise CombatTurnManifestError("combat_turn_manifest_invalid:receipt")
    if (
        type(receipt.get("schema_version")) is not int
        or receipt.get("schema_version") != 1
        or receipt.get("turn_id") != turn_id
        or receipt.get("applied_id") != applied_id
        or receipt.get("encounter_id") != encounter_id
        or receipt.get("combat_round") != combat_round
    ):
        raise CombatTurnManifestError("combat_turn_manifest_invalid:receipt_identity")

    effects = manifest.get("character_effects")
    if not isinstance(effects, list):
        raise CombatTurnManifestError("combat_turn_manifest_invalid:character_effects")
    effect_keys = []
    effect_names = set()
    for entry in effects:
        if not isinstance(entry, Mapping) or set(entry) != {"character_name", "payload"}:
            raise CombatTurnManifestError("combat_turn_manifest_invalid:character_effect")
        name = entry.get("character_name")
        payload = entry.get("payload")
        identity = _character_identity_key(name) if isinstance(name, str) else ""
        if not identity or identity in effect_names or not isinstance(payload, Mapping):
            raise CombatTurnManifestError("combat_turn_manifest_invalid:character_identity")
        if payload.get("last_combat_applied_id") != applied_id:
            raise CombatTurnManifestError("combat_turn_manifest_invalid:character_marker")
        payload_name = payload.get("name")
        if isinstance(payload_name, str) and _character_identity_key(payload_name) != identity:
            raise CombatTurnManifestError("combat_turn_manifest_invalid:character_payload_identity")
        effect_names.add(identity)
        effect_keys.append(identity)
    if effect_keys != sorted(effect_keys):
        raise CombatTurnManifestError("combat_turn_manifest_invalid:character_order")

    rewards = manifest.get("staged_rewards")
    if not isinstance(rewards, list):
        raise CombatTurnManifestError("combat_turn_manifest_invalid:staged_rewards")
    reward_names = set()
    for reward in rewards:
        if not isinstance(reward, Mapping) or set(reward) != {
            "character_name", "experience_points_delta"
        }:
            raise CombatTurnManifestError("combat_turn_manifest_invalid:reward")
        name = reward.get("character_name")
        identity = _character_identity_key(name) if isinstance(name, str) else ""
        amount = reward.get("experience_points_delta")
        if (
            not identity
            or identity in reward_names
            or identity not in effect_names
            or not isinstance(amount, int)
            or isinstance(amount, bool)
            or amount <= 0
        ):
            raise CombatTurnManifestError("combat_turn_manifest_invalid:reward_value")
        reward_names.add(identity)

    narration = manifest.get("success_narration")
    if not isinstance(narration, Mapping) or set(narration) != {"text", "payload"}:
        raise CombatTurnManifestError("combat_turn_manifest_invalid:narration")
    narration_text = narration.get("text")
    if (
        not isinstance(narration_text, str)
        or narration.get("payload") != "Dungeon Master: " + narration_text
    ):
        raise CombatTurnManifestError("combat_turn_manifest_invalid:narration_payload")

    return copy.deepcopy(dict(manifest))


def build_combat_turn_commit_manifest(
    *,
    encounter_id: str,
    turn_id: str,
    path: str,
    encounter_projection: Mapping[str, Any],
    character_payloads: Mapping[str, Mapping[str, Any]],
    changed_character_names: Sequence[str],
    staged_rewards: Sequence[Mapping[str, Any]],
    success_narration: str,
) -> Dict[str, Any]:
    """Build the exact staged payload manifest before its first durable effect."""
    applied_id = compute_applied_id(encounter_id, turn_id)
    changed = {_character_identity_key(name) for name in changed_character_names}
    payload_by_identity = {
        _character_identity_key(name): payload
        for name, payload in character_payloads.items()
    }
    effects = []
    for name in sorted(changed_character_names, key=lambda value: _character_identity_key(value)):
        identity = _character_identity_key(name)
        payload = payload_by_identity.get(identity)
        if identity not in changed or not isinstance(payload, Mapping):
            raise CombatTurnManifestError("combat_turn_manifest_invalid:missing_effect_payload")
        effects.append({"character_name": name, "payload": copy.deepcopy(dict(payload))})
    raw_round = encounter_projection.get(
        "combat_round", encounter_projection.get("current_round", 1)
    )
    manifest = {
        "schema_version": 1,
        "turn_id": turn_id,
        "applied_id": applied_id,
        "encounter_id": encounter_id,
        "path": path,
        "character_effects": effects,
        "encounter_projection": copy.deepcopy(dict(encounter_projection)),
        "receipt": {
            "schema_version": 1,
            "turn_id": turn_id,
            "applied_id": applied_id,
            "encounter_id": encounter_id,
            "combat_round": raw_round,
        },
        "staged_rewards": copy.deepcopy(sorted(
            list(staged_rewards),
            key=lambda reward: _character_identity_key(reward["character_name"]),
        )),
        "success_narration": {
            "text": success_narration,
            "payload": "Dungeon Master: " + success_narration,
        },
    }
    return validate_combat_turn_commit_manifest(manifest)


def history_with_combat_turn_manifest(
    history: Sequence[Any], turn_id: str, manifest: Mapping[str, Any]
) -> List[Any]:
    """Return a history copy with a validated manifest on its accepted input."""
    validated = validate_combat_turn_commit_manifest(manifest)
    if validated["turn_id"] != _validate_turn_id(turn_id):
        raise CombatTurnManifestError("combat_turn_manifest_invalid:history_turn_id")
    if not isinstance(history, Sequence) or isinstance(history, (str, bytes)):
        raise CombatTurnManifestError("combat_turn_manifest_invalid:history")
    copied = copy.deepcopy(list(history))
    matches = [
        index for index, message in enumerate(copied)
        if isinstance(message, Mapping)
        and message.get("role") == "user"
        and message.get("turn_id") == turn_id
    ]
    if len(matches) != 1:
        raise CombatTurnManifestError("combat_turn_manifest_invalid:history_record")
    record = copied[matches[0]]
    existing = record.get(COMBAT_TURN_COMMIT_MANIFEST_KEY)
    if existing is not None:
        validated_existing = validate_combat_turn_commit_manifest(existing)
        if validated_existing != validated:
            raise CombatTurnManifestError("combat_turn_manifest_invalid:manifest_conflict")
    record[COMBAT_TURN_COMMIT_MANIFEST_KEY] = validated
    return copied


def build_turn_receipt(
    encounter_id: str,
    turn_id: str,
    combat_round: int,
    commit_timestamp: str,
) -> Dict[str, Any]:
    """Build the exact required receipt fields; the reserved spatial slot is omitted."""
    if not isinstance(encounter_id, str) or not encounter_id.strip():
        raise ValueError("encounter_id must be a non-empty string")
    if not isinstance(combat_round, int) or isinstance(combat_round, bool) or combat_round < 1:
        raise ValueError("combat_round must be a positive integer")
    if not isinstance(commit_timestamp, str) or not _COMMIT_TIMESTAMP_PATTERN.fullmatch(
        commit_timestamp
    ):
        raise ValueError("commit_timestamp must be a UTC RFC3339 timestamp ending in Z")
    try:
        datetime.fromisoformat(commit_timestamp[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError("commit_timestamp must be a valid UTC RFC3339 timestamp") from exc

    identity = _validate_turn_id(turn_id)
    return {
        "schema_version": 1,
        "turn_id": identity,
        "applied_id": compute_applied_id(encounter_id, identity),
        "encounter_id": encounter_id,
        "combat_round": combat_round,
        "commit_timestamp": commit_timestamp,
    }


def validate_turn_receipt(receipt: Mapping[str, Any]) -> Dict[str, Any]:
    """Validate receipt identity and exact fields without interpreting position deltas."""
    if not isinstance(receipt, Mapping):
        raise TypeError("turn receipt must be a mapping")
    fields = set(receipt)
    if not _REQUIRED_RECEIPT_FIELDS.issubset(fields):
        raise ValueError("turn receipt is missing required fields")
    if fields - _REQUIRED_RECEIPT_FIELDS - _OPTIONAL_RECEIPT_FIELDS:
        raise ValueError("turn receipt contains unsupported fields")

    if type(receipt.get("schema_version")) is not int or receipt["schema_version"] != 1:
        raise ValueError("turn receipt schema_version must be integer 1")
    turn_id = _validate_turn_id(receipt.get("turn_id"))
    encounter_id = receipt.get("encounter_id")
    if not isinstance(encounter_id, str) or not encounter_id.strip():
        raise ValueError("turn receipt encounter_id must be a non-empty string")
    applied_id = _validate_applied_id(receipt.get("applied_id"))
    if applied_id != compute_applied_id(encounter_id, turn_id):
        raise ValueError("turn receipt applied_id does not match its identity")
    if (
        not isinstance(receipt.get("combat_round"), int)
        or isinstance(receipt.get("combat_round"), bool)
        or receipt["combat_round"] < 1
    ):
        raise ValueError("turn receipt combat_round must be a positive integer")
    timestamp = receipt.get("commit_timestamp")
    if not isinstance(timestamp, str) or not _COMMIT_TIMESTAMP_PATTERN.fullmatch(timestamp):
        raise ValueError("turn receipt commit_timestamp must be UTC RFC3339 ending in Z")
    try:
        datetime.fromisoformat(timestamp[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError("turn receipt commit_timestamp is not a valid date-time") from exc
    return {field: receipt[field] for field in _REQUIRED_RECEIPT_FIELDS}


def read_turn_receipts(encounter: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Read receipt history, treating only an absent legacy field as empty."""
    if not isinstance(encounter, Mapping):
        raise TypeError("encounter must be a mapping")
    if "turn_receipts" not in encounter:
        return []
    receipts = encounter["turn_receipts"]
    if not isinstance(receipts, list):
        raise ValueError("encounter turn_receipts must be a list")
    return [validate_turn_receipt(receipt) for receipt in receipts]


def with_turn_receipt(
    encounter: Mapping[str, Any], receipt: Mapping[str, Any]
) -> Dict[str, Any]:
    """Return an encounter copy with an append-only, duplicate-safe receipt list."""
    if not isinstance(encounter, Mapping):
        raise TypeError("encounter must be a mapping")
    validated_receipt = validate_turn_receipt(receipt)
    encounter_id = encounter.get("encounterId", encounter.get("id"))
    if isinstance(encounter_id, str) and encounter_id != validated_receipt["encounter_id"]:
        raise ValueError("turn receipt encounter_id does not match the encounter")

    receipts = read_turn_receipts(encounter)
    for existing in receipts:
        if existing["applied_id"] != validated_receipt["applied_id"]:
            continue
        stable_fields = _REQUIRED_RECEIPT_FIELDS - {"commit_timestamp"}
        if any(existing[field] != validated_receipt[field] for field in stable_fields):
            raise ValueError("existing applied_id has conflicting receipt identity")
        return dict(encounter)

    result = dict(encounter)
    raw_receipts = encounter.get("turn_receipts", [])
    result["turn_receipts"] = list(raw_receipts) + [validated_receipt]
    return result


def read_character_applied_id(character: Mapping[str, Any]) -> Optional[str]:
    """Read a character marker, treating a missing or empty legacy value as empty."""
    if not isinstance(character, Mapping):
        raise TypeError("character must be a mapping")
    applied_id = character.get("last_combat_applied_id")
    if applied_id is None or applied_id == "":
        return None
    return _validate_applied_id(applied_id)


def with_character_applied_id(
    character: Mapping[str, Any], applied_id: str
) -> Dict[str, Any]:
    """Return a character copy carrying the marker in its eventual atomic write."""
    if not isinstance(character, Mapping):
        raise TypeError("character must be a mapping")
    result = dict(character)
    result["last_combat_applied_id"] = _validate_applied_id(applied_id)
    return result


@dataclass(frozen=True)
class TurnCharacterEffect:
    """One character's validated, replayable effect for a combat turn."""

    character_name: str
    character_path: str
    stage: Callable[[Mapping[str, Any]], Mapping[str, Any]]


@dataclass(frozen=True)
class TurnCommitResult:
    """Durable result of a character-first/encounter-last turn commit."""

    encounter_data: Dict[str, Any]
    receipt: Dict[str, Any]
    applied_id: str
    replayed: bool
    changed_characters: tuple[str, ...]
    write_count: int
    character_payloads: Dict[str, Dict[str, Any]]


class TurnCommitError(RuntimeError):
    """Bounded failure raised before or during a durable turn commit."""

    def __init__(self, stage: str, target: Optional[str] = None):
        self.stage = stage
        self.target = target
        suffix = ":%s" % target if target else ""
        super().__init__("combat_turn_commit_failed:%s%s" % (stage, suffix))


def _character_identity_key(name: str) -> str:
    return " ".join(name.split()).casefold()


def _validate_committed_character(
    character_name: str,
    character_data: Mapping[str, Any],
    validator: Optional[Callable[[str, Mapping[str, Any]], Any]],
) -> None:
    if validator is None:
        from updates.update_character_info import load_schema, validate_character_data

        is_valid, error_message = validate_character_data(
            dict(character_data), load_schema(), character_name
        )
        if not is_valid:
            raise ValueError(error_message)
        return
    validation_result = validator(character_name, character_data)
    if validation_result is False:
        raise ValueError("character schema validation failed")


def _utc_commit_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def commit_combat_turn(
    encounter_id: str,
    turn_id: str,
    encounter_path: str,
    encounter_projection: Mapping[str, Any],
    character_effects: Sequence[TurnCharacterEffect],
    *,
    read_json: Callable[[str], Any],
    write_json: Callable[[str, Any], Any],
    validate_character: Optional[
        Callable[[str, Mapping[str, Any]], Any]
    ] = None,
    finalize_encounter: Optional[
        Callable[[Dict[str, Any], Mapping[str, Mapping[str, Any]]], Mapping[str, Any]]
    ] = None,
    before_character_writes: Optional[Callable[[], Any]] = None,
    manifest_details: Optional[Mapping[str, Any]] = None,
    manifest_writer: Optional[Callable[[Mapping[str, Any]], Any]] = None,
    character_write_observer: Optional[Callable[[str, str], Any]] = None,
    encounter_write_observer: Optional[Callable[[str], Any]] = None,
) -> TurnCommitResult:
    """Stage all effects, write marked characters, then write one receipt snapshot.

    The optional pre-character callback is used by the deterministic enemy
    batch to persist its single history checkpoint after all commit inputs have
    been validated but before the first character write.
    """
    if (
        not isinstance(encounter_id, str)
        or not encounter_id.strip()
        or not isinstance(encounter_path, str)
        or not encounter_path
        or not isinstance(encounter_projection, Mapping)
        or not isinstance(character_effects, Sequence)
        or not callable(read_json)
        or not callable(write_json)
    ):
        raise TurnCommitError("preflight")

    try:
        applied_id = compute_applied_id(encounter_id, turn_id)
        durable_encounter = read_json(encounter_path)
        if not isinstance(durable_encounter, Mapping):
            raise ValueError("encounter read failed")
        durable_encounter = copy.deepcopy(dict(durable_encounter))
        durable_encounter_id = durable_encounter.get(
            "encounterId", durable_encounter.get("id")
        )
        if durable_encounter_id != encounter_id:
            raise ValueError("encounter identity mismatch")
        durable_receipts = read_turn_receipts(durable_encounter)
        for receipt in durable_receipts:
            if receipt["applied_id"] == applied_id:
                return TurnCommitResult(
                    encounter_data=durable_encounter,
                    receipt=receipt,
                    applied_id=applied_id,
                    replayed=True,
                    changed_characters=(),
                    write_count=0,
                    character_payloads={},
                )
    except TurnCommitError:
        raise
    except Exception as exc:
        raise TurnCommitError("preflight", encounter_path) from exc

    effects_by_identity: Dict[str, TurnCharacterEffect] = {}
    for effect in character_effects:
        if (
            not isinstance(effect, TurnCharacterEffect)
            or not isinstance(effect.character_name, str)
            or not effect.character_name.strip()
            or not isinstance(effect.character_path, str)
            or not effect.character_path
            or not callable(effect.stage)
        ):
            raise TurnCommitError("preflight")
        identity_key = _character_identity_key(effect.character_name)
        if not identity_key or identity_key in effects_by_identity:
            raise TurnCommitError("preflight", effect.character_name)
        effects_by_identity[identity_key] = effect

    staged_payloads: Dict[str, Dict[str, Any]] = {}
    original_payloads: Dict[str, Dict[str, Any]] = {}
    staged_names: Dict[str, str] = {}
    already_applied: set[str] = set()
    ordered_effects = sorted(
        effects_by_identity.items(),
        key=lambda item: (item[0], item[1].character_path.casefold()),
    )
    try:
        for identity_key, effect in ordered_effects:
            current = read_json(effect.character_path)
            if not isinstance(current, Mapping):
                raise TurnCommitError("character_read", effect.character_name)
            current_payload = copy.deepcopy(dict(current))
            original_payloads[identity_key] = copy.deepcopy(current_payload)
            staged_names[identity_key] = effect.character_name
            if read_character_applied_id(current_payload) == applied_id:
                staged_payloads[identity_key] = current_payload
                already_applied.add(identity_key)
                continue

            projected = effect.stage(copy.deepcopy(current_payload))
            if not isinstance(projected, Mapping):
                raise TurnCommitError("character_stage", effect.character_name)
            marked = with_character_applied_id(projected, applied_id)
            try:
                _validate_committed_character(
                    effect.character_name, marked, validate_character
                )
            except Exception as exc:
                raise TurnCommitError(
                    "character_validation", effect.character_name
                ) from exc
            staged_payloads[identity_key] = marked
    except TurnCommitError:
        raise
    except Exception as exc:
        raise TurnCommitError("character_stage") from exc

    final_projection = copy.deepcopy(dict(encounter_projection))
    projected_encounter_id = final_projection.get(
        "encounterId", final_projection.get("id")
    )
    if projected_encounter_id != encounter_id:
        raise TurnCommitError("encounter_stage", encounter_path)
    if "turn_receipts" in durable_encounter:
        final_projection["turn_receipts"] = copy.deepcopy(
            durable_encounter["turn_receipts"]
        )
    try:
        if finalize_encounter is not None:
            finalized = finalize_encounter(
                final_projection,
                {
                    staged_names[key]: value
                    for key, value in staged_payloads.items()
                },
            )
            if not isinstance(finalized, Mapping):
                raise ValueError("encounter finalizer returned invalid state")
            final_projection = copy.deepcopy(dict(finalized))
        combat_round = final_projection.get(
            "combat_round", final_projection.get("current_round", 1)
        )
        if (
            not isinstance(combat_round, int)
            or isinstance(combat_round, bool)
            or combat_round < 1
        ):
            raise ValueError("invalid encounter round")
    except Exception as exc:
        raise TurnCommitError("encounter_stage", encounter_path) from exc

    if manifest_writer is not None:
        try:
            if not isinstance(manifest_details, Mapping):
                raise CombatTurnManifestError("combat_turn_manifest_invalid:metadata")
            changed_names = [
                staged_names[identity_key]
                for identity_key, _effect in ordered_effects
                if identity_key not in already_applied
            ]
            derived_rewards = []
            for identity_key, _effect in ordered_effects:
                if identity_key in already_applied:
                    continue
                before = original_payloads[identity_key].get("experience_points", 0)
                after = staged_payloads[identity_key].get("experience_points", 0)
                if (
                    isinstance(before, int)
                    and not isinstance(before, bool)
                    and isinstance(after, int)
                    and not isinstance(after, bool)
                    and after > before
                ):
                    derived_rewards.append({
                        "character_name": staged_names[identity_key],
                        "experience_points_delta": after - before,
                    })
            declared_rewards = manifest_details.get("staged_rewards", [])
            if declared_rewards:
                declared_by_identity = {
                    _character_identity_key(row.get("character_name")): row.get(
                        "experience_points_delta"
                    )
                    for row in declared_rewards
                    if isinstance(row, Mapping)
                }
                derived_by_identity = {
                    _character_identity_key(row["character_name"]): row[
                        "experience_points_delta"
                    ]
                    for row in derived_rewards
                }
                if declared_by_identity != derived_by_identity:
                    raise CombatTurnManifestError(
                        "combat_turn_manifest_invalid:reward_payload_mismatch"
                    )
            manifest = build_combat_turn_commit_manifest(
                encounter_id=encounter_id,
                turn_id=turn_id,
                path=manifest_details.get("path"),
                encounter_projection=final_projection,
                character_payloads={
                    staged_names[key]: value for key, value in staged_payloads.items()
                },
                changed_character_names=changed_names,
                staged_rewards=derived_rewards,
                success_narration=manifest_details.get("success_narration"),
            )
            if manifest_writer(manifest) is False:
                raise ValueError("manifest persistence returned false")
        except TurnCommitError:
            raise
        except Exception as exc:
            raise TurnCommitError("manifest", encounter_path) from exc

    if before_character_writes is not None:
        try:
            if before_character_writes() is False:
                raise ValueError("pre-character checkpoint failed")
        except Exception as exc:
            raise TurnCommitError("history", encounter_path) from exc

    if any(identity_key not in already_applied for identity_key, _effect in ordered_effects):
        maybe_inject_combat_turn_fault("before_first_character_write")

    changed_characters = []
    character_write_ordinal = 0
    for identity_key, effect in ordered_effects:
        if identity_key in already_applied:
            continue
        current_payload = staged_payloads[identity_key]
        try:
            succeeded = write_json(effect.character_path, current_payload)
        except Exception as exc:
            raise TurnCommitError("character_write", effect.character_name) from exc
        if not succeeded:
            raise TurnCommitError("character_write", effect.character_name)
        changed_characters.append(effect.character_name)
        character_write_ordinal += 1
        maybe_inject_combat_turn_fault(
            "after_character_write", ordinal=character_write_ordinal
        )
        if character_write_observer is not None:
            try:
                character_write_observer(effect.character_name, effect.character_path)
            except Exception:
                pass

    try:
        receipt = build_turn_receipt(
            encounter_id,
            turn_id,
            combat_round,
            _utc_commit_timestamp(),
        )
        final_projection = with_turn_receipt(final_projection, receipt)
        succeeded = write_json(encounter_path, final_projection)
    except Exception as exc:
        raise TurnCommitError("encounter_write", encounter_path) from exc
    if not succeeded:
        raise TurnCommitError("encounter_write", encounter_path)
    maybe_inject_combat_turn_fault("after_encounter_write")
    if encounter_write_observer is not None:
        try:
            encounter_write_observer(encounter_path)
        except Exception:
            pass

    return TurnCommitResult(
        encounter_data=final_projection,
        receipt=receipt,
        applied_id=applied_id,
        replayed=False,
        changed_characters=tuple(changed_characters),
        write_count=len(changed_characters) + 1,
        character_payloads={
            staged_names[key]: value for key, value in staged_payloads.items()
        },
    )
