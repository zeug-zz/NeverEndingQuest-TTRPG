# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Process-local, batch-bound lifecycle for optional tactical standing orders."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional


MAX_PREFETCH_BATCH_ID_CHARS = 64
MAX_PREFETCH_MESSAGE_CHARS = 48_000
MAX_PREFETCH_RESULT_CHARS = 48_000
DEFAULT_PREFETCH_DEADLINE_SECONDS = 120.0
_BATCH_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")
_IDENTITY_RE = re.compile(r"[A-Za-z0-9_-]{1,128}")
_RECEIPT_LOCK = threading.RLock()


@dataclass
class _TacticalPrefetchReceipt:
    """One bounded request receipt, tagged to its roster version and batch."""

    encounter_id: str
    batch_id: str
    roster_identity: str
    roster_members: tuple[str, ...]
    request_sequence: int
    request_kind: str
    status: str
    deadline: float
    correlation_id: Optional[str]
    response_parser: Optional[Callable[[Any], Any]] = None
    result: Any = None
    error: Optional[BaseException] = None
    parse_rejection_reason: Optional[str] = None


@dataclass(frozen=True)
class TacticalPrefetchSubmission:
    """Bounded result of attempting to reserve the process-local receipt."""

    submitted: bool
    status: str
    receipt_correlation_id: Optional[str] = None


@dataclass(frozen=True)
class TacticalPrefetchResult:
    """No-wait consume result, with only bounded receipt provenance."""

    status: str
    result: Any = None
    receipt_correlation_id: Optional[str] = None
    error: Optional[BaseException] = None
    roster_identity: Optional[str] = None
    roster_members: tuple[str, ...] = ()
    ally_departed: bool = False
    request_kind: Optional[str] = None
    receipt_status: Optional[str] = None
    parse_rejection_reason: Optional[str] = None


@dataclass(frozen=True)
class TacticalPrefetchParseOutcome:
    """Internal parser result carrying only an optional bounded rejection code."""

    value: Any
    rejection_reason: Optional[str] = None


@dataclass
class _TacticalPrefetchBatch:
    """Per-batch submission cap, state-edge baseline, and completed order sets."""

    encounter_id: str
    batch_id: str
    state_snapshot: dict[str, Any]
    roster_members: tuple[str, ...]
    departed_members: set[str]
    request_count: int
    receipts: list[_TacticalPrefetchReceipt]
    consumed: bool = False


_BATCHES: dict[tuple[str, str], _TacticalPrefetchBatch] = {}
_RECEIPT_SEQUENCE = 0


def _stable_messages(messages: Any) -> Optional[tuple[tuple[str, str], ...]]:
    if not isinstance(messages, (list, tuple)) or not messages or len(messages) > 4:
        return None
    stable = []
    total_chars = 0
    for message in messages:
        if not isinstance(message, dict):
            return None
        role = message.get("role")
        content = message.get("content")
        if not isinstance(role, str) or not isinstance(content, str):
            return None
        total_chars += len(role) + len(content)
        if total_chars > MAX_PREFETCH_MESSAGE_CHARS:
            return None
        stable.append((role, content))
    return tuple(stable)


def tactical_roster_identity(roster_members: Any) -> Optional[str]:
    """Hash a bounded sorted enemy identity set, not a menu/perception snapshot."""
    if not isinstance(roster_members, (list, tuple, set)) or len(roster_members) > 32:
        return None
    members = []
    for member in roster_members:
        if not isinstance(member, str) or not member.strip() or len(member) > 128:
            return None
        members.append(" ".join(member.split()).casefold())
    if len(set(members)) != len(members):
        return None
    encoded = json.dumps(sorted(members), ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()


def _safe_encounter_id(value: Any) -> Optional[str]:
    if not isinstance(value, str) or _IDENTITY_RE.fullmatch(value) is None:
        return None
    return value


def _safe_state_snapshot(value: Any) -> Optional[dict[str, Any]]:
    """Retain only the bounded state edges needed to detect D6 re-plan triggers."""
    if not isinstance(value, dict):
        return None
    try:
        copied = json.loads(json.dumps(value, ensure_ascii=True, allow_nan=False))
    except (TypeError, ValueError, OverflowError):
        return None
    if len(json.dumps(copied, separators=(",", ":"))) > 8192:
        return None
    roster = copied.get("roster")
    enemy_roster = copied.get("enemy_roster", roster)
    enemies = copied.get("enemies")
    pcs = copied.get("pcs")
    if (
        not isinstance(roster, list)
        or len(roster) > 32
        or any(not isinstance(item, str) or len(item) > 128 for item in roster)
        or not isinstance(enemy_roster, list)
        or len(enemy_roster) > 32
        or any(not isinstance(item, str) or len(item) > 128 for item in enemy_roster)
        or not isinstance(enemies, dict)
        or len(enemies) > 32
        or not isinstance(pcs, dict)
        or len(pcs) > 32
        or not isinstance(copied.get("commander_active"), bool)
        or not isinstance(copied.get("targeted_pcs"), list)
        or len(copied["targeted_pcs"]) > 32
    ):
        return None
    for name, state in enemies.items():
        if (
            not isinstance(name, str)
            or not isinstance(state, dict)
            or any(not isinstance(state.get(key), bool) for key in ("active", "bloodied", "near_death"))
        ):
            return None
    for name, state in pcs.items():
        if (
            not isinstance(name, str)
            or not isinstance(state, dict)
            or any(not isinstance(state.get(key), bool) for key in ("active", "zero_hp"))
        ):
            return None
    return copied


def _major_state_change(
    previous: dict[str, Any], current: dict[str, Any]
) -> tuple[bool, set[str]]:
    """Detect only the named D6 edge triggers; action counts are never inputs."""
    reasons = set()
    if previous.get("roster") != current.get("roster"):
        reasons.add("roster_changed")
    if previous.get("enemy_roster", previous.get("roster")) != current.get(
        "enemy_roster", current.get("roster")
    ):
        reasons.add("enemy_roster_changed")
    if previous.get("commander_active") is True and current.get("commander_active") is False:
        reasons.add("commander_down")
    old_enemies = previous.get("enemies", {})
    new_enemies = current.get("enemies", {})
    for name in set(old_enemies) | set(new_enemies):
        old = old_enemies.get(name, {})
        new = new_enemies.get(name, {})
        if (not old.get("bloodied", False) and new.get("bloodied", False)) or (
            not old.get("near_death", False) and new.get("near_death", False)
        ):
            reasons.add("enemy_newly_injury_band")
            break
    targeted = set(previous.get("targeted_pcs", []))
    old_pcs = previous.get("pcs", {})
    new_pcs = current.get("pcs", {})
    for name in targeted:
        old = old_pcs.get(name, {})
        new = new_pcs.get(name, {})
        if old.get("active", False) and (
            not new.get("active", False) or new.get("zero_hp", False)
        ):
            reasons.add("targeted_pc_down_or_departed")
            break
    return bool(reasons), reasons


def tactical_prefetch_replan_needed(
    encounter_id: Any, batch_id: Any, state_snapshot: Any
) -> bool:
    """Check state-edge triggers before doing menu/prompt work; never count actions."""
    safe_encounter = _safe_encounter_id(encounter_id)
    safe_state = _safe_state_snapshot(state_snapshot)
    if safe_encounter is None or not isinstance(batch_id, str) or safe_state is None:
        return False
    with _RECEIPT_LOCK:
        batch = _BATCHES.get((safe_encounter, batch_id))
        if batch is None or batch.consumed or batch.request_count >= 2:
            return False
        changed, _reasons = _major_state_change(batch.state_snapshot, safe_state)
        return changed


def tactical_batch_id(encounter_id: Any, round_number: Any) -> Optional[str]:
    """Build the same bounded identity used by the deterministic batch planner."""
    if (not isinstance(encounter_id, str) or not encounter_id.strip()
            or not isinstance(round_number, int) or isinstance(round_number, bool)
            or round_number < 1):
        return None
    suffix = f"-r{round_number}-enemy_phase"
    safe_id = re.sub(r"[^A-Za-z0-9_-]", "_", encounter_id).strip("_")
    prefix_limit = max(0, MAX_PREFETCH_BATCH_ID_CHARS - len(suffix))
    bounded_id = safe_id[:prefix_limit].strip("_")
    batch_id = f"{bounded_id or 'combat'}{suffix}"
    return batch_id if len(batch_id) <= MAX_PREFETCH_BATCH_ID_CHARS else batch_id[-MAX_PREFETCH_BATCH_ID_CHARS:]


def _bounded_result(value: Any) -> Any:
    """Detach JSON-compatible router output and reject oversized/mutable objects."""
    encoded = json.dumps(value, ensure_ascii=True, separators=(",", ":"), allow_nan=False)
    if len(encoded) > MAX_PREFETCH_RESULT_CHARS:
        raise ValueError("prefetch_result_too_large")
    return json.loads(encoded)


def _next_correlation_id() -> str:
    global _RECEIPT_SEQUENCE
    _RECEIPT_SEQUENCE += 1
    return f"prefetch-{_RECEIPT_SEQUENCE:010d}"


def _valid_deadline_seconds(value: Any) -> float:
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or value <= 0 or value > 600):
        return DEFAULT_PREFETCH_DEADLINE_SECONDS
    return float(value)


def _launch_prefetch_request(
    batch: _TacticalPrefetchBatch,
    receipt: _TacticalPrefetchReceipt,
    frozen_messages: tuple[tuple[str, str], ...],
    *,
    llm_call: Callable[..., Any],
    clock: Callable[[], float],
    executor: Optional[Callable[[Callable[[], None]], Any]],
) -> TacticalPrefetchSubmission:
    """Start one immutable-message worker and roll back a failed submission."""
    def run_plan() -> None:
        with _RECEIPT_LOCK:
            if _BATCHES.get((batch.encounter_id, batch.batch_id)) is not batch:
                return
            if receipt.status != "pending":
                return
            try:
                if clock() >= receipt.deadline:
                    receipt.status = "expired"
                    return
            except Exception:
                receipt.status = "expired"
                return
        try:
            # TABLETOP MODE: Prefetched standing orders are parsed as a JSON object.
            response = llm_call(
                "combat_main",
                [{"role": role, "content": content} for role, content in frozen_messages],
                json_output=False,
                max_tokens=1200,
                json_contract=True,
            )
            safe_response = _bounded_result(response)
            response_parser = receipt.response_parser
            if response_parser is None:
                from core.combat.tactical_brain import parse_standing_orders_response

                response_parser = parse_standing_orders_response
            parser_output = response_parser(safe_response)
            if isinstance(parser_output, TacticalPrefetchParseOutcome):
                parsed_response = parser_output.value
                parse_rejection_reason = parser_output.rejection_reason
            else:
                parsed_response = parser_output
                parse_rejection_reason = None
            worker_error = None
        except Exception as exc:
            parsed_response = None
            parse_rejection_reason = None
            worker_error = exc

        with _RECEIPT_LOCK:
            if _BATCHES.get((batch.encounter_id, batch.batch_id)) is not batch:
                return
            if receipt.status != "pending":
                return
            try:
                expired = clock() >= receipt.deadline
            except Exception:
                expired = True
            if expired:
                receipt.status = "expired"
                receipt.result = None
                receipt.error = None
            elif worker_error is not None:
                receipt.status = "failed"
                terminal_names = {"GameLLMTerminalError", "LLMJSONError"}
                receipt.error = (
                    worker_error
                    if any(cls.__name__ in terminal_names for cls in type(worker_error).__mro__)
                    else None
                )
            elif parsed_response is None:
                receipt.status = "invalid"
                receipt.result = None
                receipt.parse_rejection_reason = (
                    parse_rejection_reason
                    if isinstance(parse_rejection_reason, str)
                    and re.fullmatch(r"[a-z_]{1,48}", parse_rejection_reason)
                    else None
                )
            else:
                receipt.status = "completed"
                receipt.result = parsed_response

    try:
        if executor is not None:
            executor(run_plan)
        else:
            thread = threading.Thread(
                target=run_plan,
                name="combat-tactical-prefetch-%s" % receipt.correlation_id[-4:],
                daemon=True,
            )
            thread.start()
    except Exception:
        with _RECEIPT_LOCK:
            key = (batch.encounter_id, batch.batch_id)
            if _BATCHES.get(key) is batch and receipt.status == "pending":
                batch.receipts.remove(receipt)
                batch.request_count -= 1
                if batch.request_count == 0:
                    _BATCHES.pop(key, None)
        return TacticalPrefetchSubmission(False, "failed", receipt.correlation_id)
    status = "submitted" if receipt.request_kind == "initial" else "replan_submitted"
    return TacticalPrefetchSubmission(True, status, receipt.correlation_id)


def submit_tactical_prefetch(
    encounter_id: str,
    batch_id: str,
    roster_members: Any,
    messages: Any,
    state_snapshot: Any,
    *,
    llm_call: Callable[..., Any],
    request_kind: str = "initial",
    trigger_kind: Optional[str] = None,
    response_parser: Optional[Callable[[Any], Any]] = None,
    deadline_seconds: Any = DEFAULT_PREFETCH_DEADLINE_SECONDS,
    clock: Callable[[], float] = time.monotonic,
    executor: Optional[Callable[[Callable[[], None]], Any]] = None,
) -> TacticalPrefetchSubmission:
    """Submit an initial order request or one state-edge-triggered re-plan.

    A worker receives only a frozen JSON message tuple and the router callable;
    encounter, character, persistence, and trace objects never cross the thread
    boundary. The receipt is keyed by encounter and round-batch identity and
    stores only a roster digest plus bounded transition facts.
    """
    stable_messages = _stable_messages(messages)
    safe_encounter = _safe_encounter_id(encounter_id)
    safe_state = _safe_state_snapshot(state_snapshot)
    roster_identity = tactical_roster_identity(roster_members)
    roster_keys = tuple(sorted(
        " ".join(member.split()).casefold() for member in roster_members
    )) if isinstance(roster_members, (list, tuple, set)) else ()
    if (
        safe_encounter is None
        or not isinstance(batch_id, str)
        or _BATCH_ID_RE.fullmatch(batch_id) is None
        or not roster_keys
        or roster_identity is None
        or safe_state is None
        or stable_messages is None
        or not callable(llm_call)
        or request_kind not in {"initial", "replan"}
        or (request_kind == "initial" and trigger_kind is not None)
        or (request_kind == "replan" and trigger_kind not in {None, "state_edge", "directive"})
        or (response_parser is not None and not callable(response_parser))
        or safe_state.get("roster") != list(roster_keys)
    ):
        return TacticalPrefetchSubmission(False, "invalid")

    now = clock()
    deadline = now + _valid_deadline_seconds(deadline_seconds)
    key = (safe_encounter, batch_id)
    with _RECEIPT_LOCK:
        batch = _BATCHES.get(key)
        if request_kind == "initial":
            if batch is not None:
                return TacticalPrefetchSubmission(False, "already_submitted")
            batch = _TacticalPrefetchBatch(
                encounter_id=safe_encounter,
                batch_id=batch_id,
                state_snapshot=safe_state,
                roster_members=roster_keys,
                departed_members=set(),
                request_count=0,
                receipts=[],
            )
            _BATCHES[key] = batch
        else:
            if batch is None or batch.request_count < 1:
                return TacticalPrefetchSubmission(False, "no_initial_request")
            if batch.consumed:
                return TacticalPrefetchSubmission(False, "batch_completed")
            has_change, _reasons = _major_state_change(batch.state_snapshot, safe_state)
            previous_roster = set(batch.state_snapshot.get("roster", []))
            current_roster = set(safe_state.get("roster", []))
            batch.departed_members.update(previous_roster - current_roster)
            batch.state_snapshot = safe_state
            batch.roster_members = roster_keys
            if trigger_kind != "directive" and not has_change:
                return TacticalPrefetchSubmission(False, "no_major_change")
            if batch.request_count >= 2:
                return TacticalPrefetchSubmission(False, "request_cap_reached")

        receipt = _TacticalPrefetchReceipt(
            encounter_id=safe_encounter,
            batch_id=batch_id,
            roster_identity=roster_identity,
            roster_members=roster_keys,
            request_sequence=batch.request_count + 1,
            request_kind=request_kind,
            status="pending",
            deadline=deadline,
            correlation_id=_next_correlation_id(),
            response_parser=response_parser,
        )
        batch.request_count += 1
        batch.receipts.append(receipt)

    return _launch_prefetch_request(
        batch,
        receipt,
        tuple(stable_messages),
        llm_call=llm_call,
        clock=clock,
        executor=executor,
    )


def has_tactical_prefetch_submission(encounter_id: Any, batch_id: Any) -> bool:
    """Tell the resolver whether the no-sync standing-orders path was selected."""
    safe_encounter = _safe_encounter_id(encounter_id)
    if safe_encounter is None or not isinstance(batch_id, str):
        return False
    with _RECEIPT_LOCK:
        batch = _BATCHES.get((safe_encounter, batch_id))
        return batch is not None and batch.request_count > 0


def has_tactical_prefetch_replan_submission(encounter_id: Any, batch_id: Any) -> bool:
    """Return whether the batch has accepted its one re-plan submission."""
    safe_encounter = _safe_encounter_id(encounter_id)
    if safe_encounter is None or not isinstance(batch_id, str):
        return False
    with _RECEIPT_LOCK:
        batch = _BATCHES.get((safe_encounter, batch_id))
        return bool(
            batch is not None
            and any(receipt.request_kind == "replan" for receipt in batch.receipts)
        )


def consume_tactical_prefetch(
    encounter_id: str,
    batch_id: str,
    *,
    current_roster_members: Any = None,
    clock: Callable[[], float] = time.monotonic,
) -> TacticalPrefetchResult:
    """Select the newest completed schema-valid set without a snapshot-fingerprint gate."""
    safe_encounter = _safe_encounter_id(encounter_id)
    if safe_encounter is None or not isinstance(batch_id, str):
        return TacticalPrefetchResult("prefetch_none")
    current_identity = tactical_roster_identity(current_roster_members)
    current_keys = set()
    if isinstance(current_roster_members, (list, tuple, set)):
        current_keys = {
            " ".join(item.split()).casefold()
            for item in current_roster_members if isinstance(item, str)
        }
    now = clock()
    with _RECEIPT_LOCK:
        batch = _BATCHES.get((safe_encounter, batch_id))
        if batch is None or batch.consumed:
            return TacticalPrefetchResult("prefetch_none")
        initial_roster = set(batch.roster_members)
        batch.departed_members.update(initial_roster - current_keys)
        batch.consumed = True
        usable = [
            receipt for receipt in batch.receipts
            if receipt.status == "completed" and now < receipt.deadline
            and receipt.result is not None
        ]
        if usable:
            receipt = max(usable, key=lambda item: item.request_sequence)
            return TacticalPrefetchResult(
                "prefetch_hit",
                copy.deepcopy(receipt.result),
                receipt.correlation_id,
                roster_identity=receipt.roster_identity,
                roster_members=receipt.roster_members,
                ally_departed=bool(batch.departed_members),
                request_kind=receipt.request_kind,
                receipt_status=receipt.status,
                parse_rejection_reason=receipt.parse_rejection_reason,
            )
        latest_receipt = (
            max(batch.receipts, key=lambda item: item.request_sequence)
            if batch.receipts else None
        )
        return TacticalPrefetchResult(
            "standing_orders_unavailable",
            receipt_correlation_id=(
                latest_receipt.correlation_id if latest_receipt is not None else None
            ),
            error=(latest_receipt.error if latest_receipt is not None else None),
            roster_identity=current_identity,
            roster_members=tuple(sorted(current_keys)),
            ally_departed=bool(batch.departed_members),
            request_kind=(
                latest_receipt.request_kind if latest_receipt is not None else None
            ),
            receipt_status=(
                "expired"
                if latest_receipt is not None and now >= latest_receipt.deadline
                else latest_receipt.status if latest_receipt is not None else None
            ),
            parse_rejection_reason=(
                latest_receipt.parse_rejection_reason
                if latest_receipt is not None else None
            ),
        )


def invalidate_tactical_prefetch(
    encounter_id: Optional[str] = None,
    batch_id: Optional[str] = None,
) -> TacticalPrefetchResult:
    """Invalidate the identified batch; workers completing later are discarded."""
    with _RECEIPT_LOCK:
        if encounter_id is None and batch_id is None:
            keys = list(_BATCHES)
        elif isinstance(encounter_id, str) and isinstance(batch_id, str):
            keys = [(encounter_id, batch_id)]
        else:
            keys = [key for key in _BATCHES if key[1] == batch_id]
        invalidated_id = None
        for key in keys:
            batch = _BATCHES.pop(key, None)
            if batch is None:
                continue
            for receipt in batch.receipts:
                if receipt.status in {"pending", "completed", "failed", "invalid", "expired"}:
                    receipt.status = "cancelled"
                    receipt.result = None
                    receipt.error = None
                    invalidated_id = receipt.correlation_id
        if invalidated_id is None:
            return TacticalPrefetchResult("prefetch_none")
        return TacticalPrefetchResult(
            "prefetch_stale", receipt_correlation_id=invalidated_id
        )


def _reset_tactical_prefetch_for_tests() -> None:
    """Clear process-local batch receipts between isolated provider-free tests."""
    with _RECEIPT_LOCK:
        _BATCHES.clear()
