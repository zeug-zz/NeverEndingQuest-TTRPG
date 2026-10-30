# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Combat Latency Trace - Bounded optional JSONL telemetry.
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

This software is free for non-commercial and educational use.
Commercial competing use is prohibited for 2 years from release.
See LICENSE file for full terms.
"""

"""Small, fail-open, provider-free writer for combat latency observations."""

import json
import hashlib
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional, Union


DEFAULT_TRACE_PATH = Path("debug") / "combat_turn_trace.jsonl"
MAX_RECORD_BYTES = 8192
MAX_VALUE_CHARS = 512
MAX_TRACE_ACTORS = 32
ENEMY_BATCH_DECISION_OUTCOMES = frozenset({
    "resolver_supported",
    "whole_batch_fallback",
    "resolver_disabled",
})
TACTICAL_PLAN_OUTCOMES = frozenset({
    "accepted", "partially_defaulted", "rejected_all", "prefetch_hit", "prefetch_stale",
})
TACTICAL_PREFETCH_OUTCOMES = frozenset({
    "prefetch_hit", "prefetch_stale", "prefetch_none",
    "standing_orders_unavailable",
})
TACTICAL_DEFAULT_REASON_CODES = frozenset({
    "INVALID_CHOICE", "MISSING_CHOICE", "UNKNOWN_ACTOR", "DUPLICATE_ID", "UNISSUED_ID",
    "STANDING_ORDERS_UNAVAILABLE",
})
STANDING_ORDERS_OUTCOMES = frozenset({
    "submitted", "replan_submitted", "standing_orders",
    "standing_orders_unavailable", "invalidated",
})
TACTICAL_PREFETCH_REQUEST_KINDS = frozenset({"initial", "replan"})
TACTICAL_COVER_STATES = frozenset({"selected", "applied", "expired"})
TACTICAL_COVER_TYPES = frozenset({"half", "three_quarters"})
TACTICAL_COVER_REASON_CODES = frozenset({
    "feature_missing", "malformed_feature_id", "malformed_cover_type",
})
ALLY_PREFETCH_RESOLUTIONS = frozenset({
    "prefetch_unavailable", "response_rejected", "compiler_unusable",
    "current_menu_default", "current_menu_selected",
})
ALLY_PREFETCH_REJECTION_REASONS = frozenset({
    "unparseable_response", "top_level_not_object", "top_level_shape",
    "intent_invalid", "actors_invalid", "actor_row_shape",
    "actor_identity_invalid", "actor_kind_invalid", "duplicate_actor",
    "clauses_invalid", "clause_shape", "condition_invalid", "action_shape",
    "attack_shape", "attack_target_invalid", "attack_action_invalid",
    "cover_shape", "cover_feature_invalid", "unsupported_action",
})
_ENEMY_BATCH_PARITY_OBSERVATIONS = frozenset({
    "combat_action_batch",
    "combat_batch_narration_result",
    "combat_apply_result",
    "combat_logical_batch_completed",
    "combat_tactical_plan_result",
    "combat_tactical_prefetch_status",
    "combat_self_preservation_outcome",
    "combat_cover_outcome",
    "applied_choice_legality",
    "commander_squad_follows_orders",
    "ally_choice_commit_result",
    "ally_directive_accepted",
    "ally_prefetch_submission",
})
_TRACE_LOCK = threading.Lock()
_TRACE_CONTEXT: Dict[str, Any] = {}


def trace_enabled() -> bool:
    """Return whether combat tracing is enabled, defaulting safely to False."""
    try:
        import model_config

        return bool(getattr(model_config, "ENABLE_COMBAT_TURN_TRACE", False))
    except Exception:
        return False


def _bounded_value(value: Any, depth: int = 0) -> Any:
    """Convert values to bounded JSON-compatible, ASCII-safe values."""
    if depth > 2:
        return "[truncated]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:MAX_VALUE_CHARS]
    if isinstance(value, (list, tuple)):
        return [_bounded_value(item, depth + 1) for item in value[:32]]
    if isinstance(value, dict):
        result: Dict[str, Any] = {}
        for key, item in list(value.items())[:32]:
            result[str(key)[:80]] = _bounded_value(item, depth + 1)
        return result
    return str(value)[:MAX_VALUE_CHARS]


def normalize_trace_event(event_type: str, **fields: Any) -> Dict[str, Any]:
    """Build a bounded trace record without rejecting optional event fields."""
    record: Dict[str, Any] = {
        "schema_version": 1,
        "event_type": str(event_type)[:80],
    }
    for key, value in fields.items():
        record[str(key)[:80]] = _bounded_value(value)
    return record


def _safe_trace_id(value: Any) -> Optional[str]:
    """Accept only bounded identifier characters; never serialize free text."""
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,79}", value):
        return None
    return value


def _safe_enemy_batch_id(value: Any) -> Optional[str]:
    if not isinstance(value, str) or not re.fullmatch(r"enemy:r[0-9]{1,73}", value):
        return None
    return value


def _safe_actor_id(value: Any) -> Optional[str]:
    if not isinstance(value, str) or not re.fullmatch(r"actor_(?:[1-9]|[12][0-9]|3[0-2])", value):
        return None
    return value


def _bounded_actor_ids(values: Any) -> list[str]:
    """Retain unique, run-local actor IDs without serializing names or free text."""
    if not isinstance(values, (list, tuple)):
        return []
    bounded = []
    seen = set()
    for value in values[:MAX_TRACE_ACTORS]:
        actor_id = _safe_actor_id(value)
        if actor_id is not None and actor_id not in seen:
            bounded.append(actor_id)
            seen.add(actor_id)
    return bounded


def _safe_plan_correlation_id(value: Any) -> Optional[str]:
    safe_id = _safe_trace_id(value)
    return safe_id if safe_id is not None and len(safe_id) <= 80 else None


def build_run_local_actor_ids(creatures: Any) -> Dict[tuple[str, str], str]:
    """Assign bounded, name-free IDs in encounter order for trace correlation."""
    if not isinstance(creatures, list):
        return {}
    result: Dict[tuple[str, str], str] = {}
    ambiguous = set()
    next_index = 1
    for creature in creatures[:128]:
        if not isinstance(creature, dict):
            continue
        kind = creature.get("type")
        name = creature.get("name")
        if (
            not isinstance(kind, str)
            or not isinstance(name, str)
            or not name.strip()
            or len(name) > 128
        ):
            continue
        kind = kind.strip().casefold()
        if kind == "pc":
            kind = "player"
        if kind not in {"enemy", "player", "npc"}:
            continue
        key = (kind, " ".join(name.split()).casefold())
        if key in result:
            result.pop(key, None)
            ambiguous.add(key)
            continue
        if key in ambiguous or next_index > MAX_TRACE_ACTORS:
            continue
        actor_id = "actor_%d" % next_index
        result[key] = actor_id
        next_index += 1
    return result


def _bounded_tactical_default_reasons(
    default_reasons: Optional[list[dict[str, str]]],
) -> list[dict[str, str]]:
    if not isinstance(default_reasons, list):
        return []
    bounded = []
    for item in default_reasons[:MAX_TRACE_ACTORS]:
        if not isinstance(item, dict):
            continue
        actor_id = _safe_actor_id(item.get("actor_id"))
        reason_code = item.get("reason_code")
        if (
            actor_id is not None
            and isinstance(reason_code, str)
            and reason_code in TACTICAL_DEFAULT_REASON_CODES
        ):
            bounded.append({"actor_id": actor_id, "reason_code": reason_code})
    return bounded


def _enemy_batch_work_unit_context(event_type: str, fields: Dict[str, Any]) -> Dict[str, str]:
    """Rebuild batch context for resolver observations, excluding stale PC IDs."""
    is_decision = (
        event_type == "decision"
        and fields.get("decision_point") == "enemy_batch_resolution"
    )
    is_parity_observation = (
        event_type == "combat_observation"
        and fields.get("observation") in _ENEMY_BATCH_PARITY_OBSERVATIONS
    )
    if not (is_decision or is_parity_observation):
        return {}
    batch_id = _safe_enemy_batch_id(fields.get("batch_id"))
    if batch_id is None:
        return {}
    try:
        round_number = int(batch_id[len("enemy:r"):])
        context = build_work_unit_trace_context(round_number, "ENEMY_PHASE", None)
        return context if context.get("batch_id") == batch_id else {}
    except (TypeError, ValueError, OverflowError):
        return {}


def build_work_unit_trace_context(
    combat_round: Any,
    phase: Any,
    active_pc: Any,
) -> Dict[str, str]:
    """Build stable, text-free action or enemy-batch attribution identifiers."""
    round_number = combat_round if isinstance(combat_round, int) and not isinstance(combat_round, bool) else 0
    round_number = max(0, round_number)
    normalized_phase = phase.strip().upper() if isinstance(phase, str) else "PC_PHASE"
    if normalized_phase == "ENEMY_PHASE":
        batch_id = "enemy:r%d" % round_number
        return {"batch_id": batch_id} if _safe_trace_id(batch_id) else {}
    if not isinstance(active_pc, str):
        return {}
    identity = "".join(
        character.lower() if character.isascii() and character.isalnum() else "_"
        for character in active_pc.strip()
    ).strip("_")[:32]
    if not identity:
        return {}
    action_id = "pc:r%d:%s" % (round_number, identity)
    return {"action_id": action_id} if _safe_trace_id(action_id) else {}


def set_trace_context(**fields: Any) -> bool:
    """Replace the bounded context applied to subsequent trace records."""
    if not trace_enabled():
        return False
    try:
        bounded_context = {
            str(key)[:80]: _bounded_value(value)
            for key, value in list(fields.items())[:32]
        }
        with _TRACE_LOCK:
            _TRACE_CONTEXT.clear()
            _TRACE_CONTEXT.update(bounded_context)
        return True
    except Exception as error:
        _debug_trace_failure(error)
        return False


def _debug_trace_failure(error: Exception) -> None:
    """Best-effort diagnostic logging that can never affect the caller."""
    try:
        from utils.enhanced_logger import debug

        debug("Combat latency trace skipped: %s" % error, category="combat_latency")
    except Exception:
        pass


def emit_trace_event(
    event_type: str,
    path: Optional[Union[str, Path]] = None,
    **fields: Any,
) -> bool:
    """Append one bounded trace event and return whether it was written.

    The gate is deliberately checked before path handling, payload construction,
    clock access, directory creation, locking, or file access.
    """
    if not trace_enabled():
        return False

    try:
        destination = Path(path) if path is not None else DEFAULT_TRACE_PATH
        with _TRACE_LOCK:
            context = dict(_TRACE_CONTEXT)
        merged_fields = dict(context)
        merged_fields.update(fields)
        batch_context = _enemy_batch_work_unit_context(event_type, merged_fields)
        if batch_context:
            merged_fields.update(batch_context)
            merged_fields.pop("action_id", None)
        # Set by the G5 capture orchestrator before the sandbox server starts.
        # It is intentionally absent from ordinary G3/G4 runs.
        merged_fields.pop("run_id", None)
        run_id = _safe_trace_id(os.environ.get("NEQ_G5_CAPTURE_RUN_ID"))
        if run_id is not None:
            merged_fields["run_id"] = run_id
        record = normalize_trace_event(event_type, **merged_fields)
        record["recorded_at_ms"] = int(time.time() * 1000)
        encoded = json.dumps(
            record,
            ensure_ascii=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        if len(encoded.encode("ascii")) > MAX_RECORD_BYTES:
            truncated_fields: Dict[str, Any] = {"fields_truncated": True}
            # Keep G5 run/work-unit attribution on the bounded fallback record.
            # With no G5 run id, legacy G3/G4 truncation remains byte-identical.
            if run_id is not None:
                truncated_fields["run_id"] = run_id
                for key, pattern in (("action_id", r"pc:r[0-9]{1,43}:[a-z0-9_]{1,32}"),
                                     ("batch_id", r"enemy:r[0-9]{1,73}")):
                    value = merged_fields.get(key)
                    if isinstance(value, str) and re.fullmatch(pattern, value):
                        truncated_fields[key] = value
            encoded = json.dumps(
                normalize_trace_event(event_type, **truncated_fields),
                ensure_ascii=True,
                separators=(",", ":"),
            )
        line = (encoded + "\n").encode("ascii")
        with _TRACE_LOCK:
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("ab") as trace_file:
                trace_file.write(line)
        return True
    except Exception as error:
        _debug_trace_failure(error)
        return False


def trace_stage(stage: str, started_at: float, **fields: Any) -> bool:
    """Emit an observed combat stage duration when tracing is enabled."""
    if not trace_enabled():
        return False
    try:
        elapsed_ms = (time.perf_counter() - started_at) * 1000.0
        return emit_trace_event("stage", stage=stage, elapsed_ms=elapsed_ms, **fields)
    except Exception as error:
        _debug_trace_failure(error)
        return False


def trace_combat_exit_complete(
    encounter_id: Any = None, batch_id: Any = None
) -> bool:
    """Record the end of the post-combat narration handoff, without blocking it."""
    if not trace_enabled():
        return False
    try:
        with _TRACE_LOCK:
            context = dict(_TRACE_CONTEXT)
        safe_batch_id = _safe_enemy_batch_id(batch_id)
        if safe_batch_id is None:
            safe_batch_id = _safe_enemy_batch_id(context.get("batch_id"))
        safe_encounter_id = _safe_trace_id(encounter_id)
        if safe_encounter_id is None:
            safe_encounter_id = _safe_trace_id(context.get("encounter_id"))

        fields: Dict[str, Any] = {
            "stage": "combat_exit_complete",
            "elapsed_ms": 0,
        }
        # Override potentially stale/untrusted context values with only validated IDs.
        if "batch_id" in context or safe_batch_id is not None:
            fields["batch_id"] = safe_batch_id
        if "encounter_id" in context or safe_encounter_id is not None:
            fields["encounter_id"] = safe_encounter_id
        return emit_trace_event("stage", **fields)
    except Exception as error:
        _debug_trace_failure(error)
        return False


def trace_decision(
    decision_point: str,
    decision_source: str,
    started_at: float,
    provider_call_avoided: bool,
    **fields: Any,
) -> bool:
    """Emit an observed combat decision outcome without affecting routing."""
    if not trace_enabled():
        return False
    if decision_source not in ("deterministic", "llm_fallback", "llm_tactical", "jev"):
        try:
            from utils.enhanced_logger import debug

            debug(
                "Combat latency decision trace skipped: invalid source %s"
                % decision_source,
                category="combat_latency",
            )
        except Exception:
            pass
        return False
    try:
        elapsed_ms = max(0.0, (time.perf_counter() - started_at) * 1000.0)
        event_fields: Dict[str, Any] = {
            "decision_point": decision_point,
            "decision_source": decision_source,
            "decision_latency_ms": elapsed_ms,
            "provider_call_avoided": bool(provider_call_avoided),
        }
        event_fields.update(fields)
        return emit_trace_event("decision", **event_fields)
    except Exception as error:
        _debug_trace_failure(error)
        return False


def _enemy_batch_decision_reason_codes() -> frozenset[str]:
    """Load the bounded resolver and narration reason vocabularies lazily."""
    try:
        from core.combat.enemy_narration import _REASON_CODES
        from core.combat.enemy_resolution import DECLINE_REASON_CODES

        return frozenset(DECLINE_REASON_CODES) | frozenset(_REASON_CODES) | frozenset({
            "ledger_supported",
            "resolver_disabled",
            "round_transition_unsupported",
            "preflight_error",
            "malformed_result",
            "malformed_pc_state",
        })
    except Exception:
        return frozenset()


def trace_enemy_batch_decision(
    decision_outcome: str,
    decision_reason: str,
    batch_id: str,
    started_at: float,
    *,
    logical_turn: Optional[int] = None,
    decision_source: Optional[str] = None,
    tactical_plan_outcome: Optional[str] = None,
    default_reasons: Optional[list[dict[str, str]]] = None,
    prefetch_status: Optional[str] = None,
    plan_origin: Optional[str] = None,
    standing_orders_outcome: Optional[str] = None,
) -> bool:
    """Emit one bounded deterministic-enemy decision without affecting routing."""
    if not trace_enabled():
        return False
    try:
        if decision_outcome not in ENEMY_BATCH_DECISION_OUTCOMES:
            return False
        if decision_reason not in _enemy_batch_decision_reason_codes():
            return False
        safe_batch_id = _safe_enemy_batch_id(batch_id)
        if safe_batch_id is None:
            return False
        supported = decision_outcome == "resolver_supported"
        resolved_source = decision_source or (
            "deterministic" if supported else "llm_fallback"
        )
        if resolved_source not in ("deterministic", "llm_fallback", "llm_tactical", "jev"):
            return False
        fields: Dict[str, Any] = {
            "decision_outcome": decision_outcome,
            "decision_reason": decision_reason,
            "batch_id": safe_batch_id,
        }
        if isinstance(logical_turn, int) and not isinstance(logical_turn, bool) and logical_turn > 0:
            fields["logical_turn"] = logical_turn
        if isinstance(tactical_plan_outcome, str) and tactical_plan_outcome in TACTICAL_PLAN_OUTCOMES:
            fields["tactical_plan_outcome"] = tactical_plan_outcome
        bounded_reasons = _bounded_tactical_default_reasons(default_reasons)
        if bounded_reasons:
            fields["default_reasons"] = bounded_reasons
        if isinstance(prefetch_status, str) and prefetch_status in TACTICAL_PREFETCH_OUTCOMES:
            fields["prefetch_status"] = prefetch_status
        if plan_origin in {"synchronous", "standing_orders"}:
            fields["plan_origin"] = plan_origin
        if standing_orders_outcome in STANDING_ORDERS_OUTCOMES:
            fields["standing_orders_outcome"] = standing_orders_outcome
        return trace_decision(
            "enemy_batch_resolution",
            resolved_source,
            started_at,
            provider_call_avoided=(resolved_source != "llm_tactical" and supported),
            **fields,
        )
    except Exception as error:
        _debug_trace_failure(error)
        return False


def trace_tactical_plan_result(
    batch_id: str,
    plan_correlation_id: str,
    tactical_plan_outcome: str,
    default_reasons: Optional[list[dict[str, str]]] = None,
    *,
    prefetch_status: Optional[str] = None,
    actor_ids: Optional[list[str]] = None,
    target_ids: Optional[list[str]] = None,
    plan_origin: Optional[str] = None,
    standing_orders_outcome: Optional[str] = None,
) -> bool:
    """Emit a bounded commander-plan result under the shared trace gate."""
    if not trace_enabled():
        return False
    try:
        safe_batch_id = _safe_enemy_batch_id(batch_id)
        safe_plan_id = _safe_plan_correlation_id(plan_correlation_id)
        if (
            safe_batch_id is None
            or safe_plan_id is None
            or not isinstance(tactical_plan_outcome, str)
            or tactical_plan_outcome not in TACTICAL_PLAN_OUTCOMES
            or (
                prefetch_status is not None
                and (
                    not isinstance(prefetch_status, str)
                    or prefetch_status not in TACTICAL_PREFETCH_OUTCOMES
                )
            )
            or (plan_origin is not None and plan_origin not in {"synchronous", "standing_orders"})
            or (
                standing_orders_outcome is not None
                and standing_orders_outcome not in STANDING_ORDERS_OUTCOMES
            )
        ):
            return False
        fields: Dict[str, Any] = {
            "batch_id": safe_batch_id,
            "plan_correlation_id": safe_plan_id,
            "tactical_plan_outcome": tactical_plan_outcome,
        }
        bounded_reasons = _bounded_tactical_default_reasons(default_reasons)
        if bounded_reasons:
            fields["default_reasons"] = bounded_reasons
        if prefetch_status is not None:
            fields["prefetch_status"] = prefetch_status
        if actor_ids is not None:
            fields["actor_ids"] = _bounded_actor_ids(actor_ids)
        if target_ids is not None:
            fields["target_ids"] = _bounded_actor_ids(target_ids)
        if plan_origin is not None:
            fields["plan_origin"] = plan_origin
        if standing_orders_outcome is not None:
            fields["standing_orders_outcome"] = standing_orders_outcome
        return trace_combat_observation("combat_tactical_plan_result", **fields)
    except Exception as error:
        _debug_trace_failure(error)
        return False


def trace_tactical_prefetch_status(
    batch_id: str,
    plan_correlation_id: str,
    prefetch_status: str,
    *,
    receipt_correlation_id: Optional[str] = None,
    standing_orders_outcome: Optional[str] = None,
    request_kind: Optional[str] = None,
    request_site: Optional[str] = None,
) -> bool:
    """Emit a bounded, batch-attributed prefetch lifecycle observation."""
    if not trace_enabled():
        return False
    try:
        safe_batch_id = _safe_enemy_batch_id(batch_id)
        safe_plan_id = _safe_plan_correlation_id(plan_correlation_id)
        if (
            safe_batch_id is None
            or safe_plan_id is None
            or not isinstance(prefetch_status, str)
            or prefetch_status not in TACTICAL_PREFETCH_OUTCOMES
            or (
                standing_orders_outcome is not None
                and standing_orders_outcome not in STANDING_ORDERS_OUTCOMES
            )
            or (
                request_kind is not None
                and request_kind not in TACTICAL_PREFETCH_REQUEST_KINDS
            )
            or (
                request_site is not None
                and request_site != "combat_tactical_prefetch"
            )
        ):
            return False
        fields: Dict[str, Any] = {
            "batch_id": safe_batch_id,
            "plan_correlation_id": safe_plan_id,
            "prefetch_status": prefetch_status,
        }
        if receipt_correlation_id is not None:
            safe_receipt_id = _safe_plan_correlation_id(receipt_correlation_id)
            if safe_receipt_id is None:
                return False
            fields["receipt_correlation_id"] = safe_receipt_id
        if standing_orders_outcome is not None:
            fields["standing_orders_outcome"] = standing_orders_outcome
            fields["request_site"] = "combat_tactical_prefetch"
        if request_kind is not None:
            fields["request_kind"] = request_kind
        if request_site is not None:
            fields["request_site"] = request_site
        return trace_combat_observation("combat_tactical_prefetch_status", **fields)
    except Exception as error:
        _debug_trace_failure(error)
        return False


def trace_tactical_self_preservation_outcome(
    batch_id: str,
    actor_id: str,
    outcome: str,
) -> bool:
    """Emit one applied, per-creature flee or surrender observation."""
    if not trace_enabled():
        return False
    try:
        safe_batch_id = _safe_enemy_batch_id(batch_id)
        safe_id = _safe_actor_id(actor_id)
        if (
            safe_batch_id is None
            or safe_id is None
            or not isinstance(outcome, str)
            or outcome not in {"fled", "surrendered"}
        ):
            return False
        return trace_combat_observation(
            "combat_self_preservation_outcome",
            batch_id=safe_batch_id,
            actor_id=safe_id,
            self_preservation_outcome=outcome,
        )
    except Exception as error:
        _debug_trace_failure(error)
        return False


def trace_tactical_cover_outcome(
    batch_id: str,
    actor_id: str,
    feature_id: Any,
    cover_type: Any,
    cover_state: str,
) -> bool:
    """Emit bounded authored-cover selection, application, or expiration."""
    if not trace_enabled():
        return False
    try:
        safe_batch_id = _safe_enemy_batch_id(batch_id)
        safe_actor = _safe_actor_id(actor_id)
        if (
            safe_batch_id is None
            or safe_actor is None
            or not isinstance(cover_state, str)
            or cover_state not in TACTICAL_COVER_STATES
        ):
            return False

        fields: Dict[str, Any] = {
            "batch_id": safe_batch_id,
            "actor_id": safe_actor,
            "cover_state": cover_state,
        }
        reason_code = None
        if not isinstance(feature_id, str) or not feature_id.strip():
            reason_code = "feature_missing"
        elif (
            len(feature_id) > 80
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", feature_id)
        ):
            reason_code = "malformed_feature_id"
        else:
            fields["feature_id"] = feature_id

        if isinstance(cover_type, str) and cover_type in TACTICAL_COVER_TYPES:
            fields["cover_type"] = cover_type
        elif reason_code is None:
            reason_code = "malformed_cover_type"
        if reason_code in TACTICAL_COVER_REASON_CODES:
            fields["reason_code"] = reason_code
        return trace_combat_observation("combat_cover_outcome", **fields)
    except Exception as error:
        _debug_trace_failure(error)
        return False


def trace_applied_choice_legality(
    batch_id: str,
    applied_choice_count: int,
    legal_applied_choice_count: int,
) -> bool:
    """Emit bounded legality counts for accepted choices present in the ledger."""
    if not trace_enabled():
        return False
    safe_batch_id = _safe_enemy_batch_id(batch_id)
    if (
        safe_batch_id is None
        or not isinstance(applied_choice_count, int)
        or isinstance(applied_choice_count, bool)
        or not 1 <= applied_choice_count <= MAX_TRACE_ACTORS
        or not isinstance(legal_applied_choice_count, int)
        or isinstance(legal_applied_choice_count, bool)
        or not 0 <= legal_applied_choice_count <= applied_choice_count
    ):
        return False
    try:
        return trace_combat_observation(
            "applied_choice_legality",
            batch_id=safe_batch_id,
            applied_choice_count=applied_choice_count,
            legal_applied_choice_count=legal_applied_choice_count,
        )
    except Exception as error:
        _debug_trace_failure(error)
        return False


def trace_ally_choice_commit_result(
    batch_id: str,
    actor_id: str,
    choice_kind: str,
    choice_legal: bool,
    choice_defaulted: bool,
    choice_applied: bool,
    *,
    cover_feature_id: Any = None,
    directive_sha256: Any = None,
    directive_request_kind: Any = None,
    prefetch_resolution: Any = None,
    prefetch_rejection_reason: Any = None,
) -> bool:
    """Emit bounded post-commit ally choice evidence without directive text."""
    if not trace_enabled():
        return False
    safe_batch_id = _safe_enemy_batch_id(batch_id)
    safe_actor = _safe_actor_id(actor_id)
    if (
        safe_batch_id is None
        or safe_actor is None
        or not isinstance(choice_kind, str)
        or choice_kind not in {"attack", "take_cover", "hold", "flee", "surrender"}
        or not isinstance(choice_legal, bool)
        or not isinstance(choice_defaulted, bool)
        or not isinstance(choice_applied, bool)
        or (directive_request_kind is not None and (
            not isinstance(directive_request_kind, str)
            or directive_request_kind not in {"synchronous", "initial", "replan"}
        ))
        or (prefetch_resolution is not None and (
            not isinstance(prefetch_resolution, str)
            or prefetch_resolution not in ALLY_PREFETCH_RESOLUTIONS
        ))
        or (prefetch_rejection_reason is not None and (
            not isinstance(prefetch_rejection_reason, str)
            or prefetch_rejection_reason not in ALLY_PREFETCH_REJECTION_REASONS
            or prefetch_resolution != "response_rejected"
        ))
    ):
        return False
    fields: Dict[str, Any] = {
        "batch_id": safe_batch_id,
        "actor_id": safe_actor,
        "choice_kind": choice_kind,
        "choice_legal": choice_legal,
        "choice_defaulted": choice_defaulted,
        "choice_applied": choice_applied,
    }
    if isinstance(cover_feature_id, str) and cover_feature_id:
        if (len(cover_feature_id) > 80 or
                not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", cover_feature_id)):
            return False
        fields["cover_feature_id"] = cover_feature_id
    elif cover_feature_id is not None:
        return False
    if directive_sha256 is not None:
        if (not isinstance(directive_sha256, str)
                or not re.fullmatch(r"[0-9a-f]{64}", directive_sha256)
                or directive_request_kind is None):
            return False
        fields["directive_sha256"] = directive_sha256
        fields["directive_request_kind"] = directive_request_kind
    elif directive_request_kind is not None:
        return False
    if prefetch_resolution is not None:
        fields["prefetch_resolution"] = prefetch_resolution
    if prefetch_rejection_reason is not None:
        fields["prefetch_rejection_reason"] = prefetch_rejection_reason
    try:
        return trace_combat_observation("ally_choice_commit_result", **fields)
    except Exception as error:
        _debug_trace_failure(error)
        return False


def trace_ally_directive_accepted(
    batch_id: str,
    actor_id: str,
    directive_sha256: str,
) -> bool:
    """Record an accepted directive's digest only, never its text."""
    if not trace_enabled():
        return False
    safe_batch_id = _safe_enemy_batch_id(batch_id)
    safe_actor = _safe_actor_id(actor_id)
    if (safe_batch_id is None or safe_actor is None
            or not isinstance(directive_sha256, str)
            or not re.fullmatch(r"[0-9a-f]{64}", directive_sha256)):
        return False
    try:
        return trace_combat_observation(
            "ally_directive_accepted",
            batch_id=safe_batch_id,
            actor_id=safe_actor,
            directive_sha256=directive_sha256,
        )
    except Exception as error:
        _debug_trace_failure(error)
        return False


def trace_ally_prefetch_submission(
    batch_id: str,
    request_id: str,
    request_kind: str,
) -> bool:
    """Record a bounded ally background-request identity and lifecycle kind."""
    if not trace_enabled():
        return False
    safe_batch_id = _safe_enemy_batch_id(batch_id)
    safe_request_id = _safe_plan_correlation_id(request_id)
    if (safe_batch_id is None or safe_request_id is None
            or not isinstance(request_kind, str)
            or request_kind not in TACTICAL_PREFETCH_REQUEST_KINDS):
        return False
    try:
        return trace_combat_observation(
            "ally_prefetch_submission",
            batch_id=safe_batch_id,
            request_id=safe_request_id,
            request_kind=request_kind,
        )
    except Exception as error:
        _debug_trace_failure(error)
        return False


def trace_commander_squad_follows_orders(
    batch_id: str,
    issued_choice_count: int,
    applied_choice_count: int,
    followed_orders: bool,
) -> bool:
    """Emit bounded commander-choice counts and ledger-followthrough result."""
    if not trace_enabled():
        return False
    safe_batch_id = _safe_enemy_batch_id(batch_id)
    if (
        safe_batch_id is None
        or not isinstance(issued_choice_count, int)
        or isinstance(issued_choice_count, bool)
        or not 0 <= issued_choice_count <= MAX_TRACE_ACTORS
        or not isinstance(applied_choice_count, int)
        or isinstance(applied_choice_count, bool)
        or not 0 <= applied_choice_count <= issued_choice_count
        or not isinstance(followed_orders, bool)
    ):
        return False
    try:
        return trace_combat_observation(
            "commander_squad_follows_orders",
            batch_id=safe_batch_id,
            issued_choice_count=issued_choice_count,
            applied_choice_count=applied_choice_count,
            followed_orders=followed_orders,
        )
    except Exception as error:
        _debug_trace_failure(error)
        return False


def trace_provider_call(site: str, started_at: float, response: Any = None) -> bool:
    """Emit provider latency and only the usage metadata actually available."""
    if not trace_enabled():
        return False
    try:
        fields: Dict[str, Any] = {
            "site": site,
            "elapsed_ms": (time.perf_counter() - started_at) * 1000.0,
        }
        usage = getattr(response, "usage", None)
        if usage is not None:
            for name in ("prompt_tokens", "completion_tokens", "total_tokens"):
                value = getattr(usage, name, None)
                if value is None and isinstance(usage, dict):
                    value = usage.get(name)
                if value is not None:
                    fields[name] = value
        return emit_trace_event("provider", **fields)
    except Exception as error:
        _debug_trace_failure(error)
        return False


def trace_compression_event(
    site: str,
    call_occurred: bool,
    cache_hit: bool,
    started_at: Optional[float] = None,
    **fields: Any,
) -> bool:
    """Emit an observed compression decision without changing compression policy."""
    if not trace_enabled():
        return False
    try:
        event_fields: Dict[str, Any] = {
            "site": site,
            "call_occurred": call_occurred,
            "cache_hit": cache_hit,
        }
        if started_at is not None:
            event_fields["elapsed_ms"] = (time.perf_counter() - started_at) * 1000.0
        event_fields.update(fields)
        return emit_trace_event("compression", **event_fields)
    except Exception as error:
        _debug_trace_failure(error)
        return False


def trace_file_operation(category: str, site: str) -> bool:
    """Emit an observed combat file operation."""
    if not trace_enabled():
        return False
    try:
        return emit_trace_event("file_operation", category=category, site=site)
    except Exception as error:
        _debug_trace_failure(error)
        return False


def _opaque_target_id(path: Any) -> Optional[str]:
    """Return a short path-derived identity without exposing path bytes."""
    try:
        resolved_path = Path(path).resolve(strict=False)
        return hashlib.sha256(str(resolved_path).encode("utf-8")).hexdigest()[:12]
    except Exception:
        return None


def trace_batch_file_write(
    batch_id: str,
    target_kind: str,
    target_path: Any,
    site: str = "enemy_batch_write",
) -> bool:
    """Emit one opaque write observation for one physical enemy-batch file."""
    if not trace_enabled():
        return False
    try:
        safe_batch_id = _safe_enemy_batch_id(batch_id)
        if safe_batch_id is None or target_kind not in {"history", "character", "encounter"}:
            return False
        if site != "enemy_batch_write":
            return False
        target_id = _opaque_target_id(target_path)
        if target_id is None:
            return False
        return emit_trace_event(
            "file_operation",
            category="write",
            site=site,
            batch_id=safe_batch_id,
            target_kind=target_kind,
            target_id=target_id,
        )
    except Exception as error:
        _debug_trace_failure(error)
        return False


def trace_combat_observation(observation: str, **fields: Any) -> bool:
    """Emit bounded state-machine evidence through the existing opt-in trace gate."""
    if not trace_enabled():
        return False
    try:
        # ``path`` is an output-routing parameter only on the lower-level writer.
        # Observations carry metadata, so retain legacy caller provenance under a
        # metadata-only name rather than allowing it to redirect the trace file.
        if "path" in fields:
            metadata_key = "legacy_path_metadata"
            suffix = 2
            while metadata_key in fields:
                metadata_key = "legacy_path_metadata_%d" % suffix
                suffix += 1
            fields[metadata_key] = fields.pop("path")
        return emit_trace_event("combat_observation", observation=observation, **fields)
    except Exception as error:
        _debug_trace_failure(error)
        return False
