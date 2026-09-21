#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
Jev Phase 0 eval-set extractor.

Builds a provider-free JSONL eval set for the action-required decision from
existing narrator-path artifacts:

  - modules/conversation_history/conversation_history.json  (user -> assistant pairs)
  - debug/quality_control/rejected_narrator_turns.jsonl     (rejected narrator attempts)

Label semantics match utils/action_predictor.py: requires_actions is True when
the narrator response carries at least one action other than ``updateTime``.

History pairs produce ``strong`` labels (accepted narrator turn). Rejected
attempts produce ``weak`` labels (the model emitted a response that was later
rejected, but its action set is still evidence of expected actions).

No network calls. No LLM provider calls.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_HISTORY = REPO_ROOT / "modules" / "conversation_history" / "conversation_history.json"
DEFAULT_REJECTED = REPO_ROOT / "debug" / "quality_control" / "rejected_narrator_turns.jsonl"
DEFAULT_OUT = REPO_ROOT / "debug" / "jev" / "eval_set.jsonl"

EXCLUDED_STATE_MARKERS = (
    "You are a master storyteller, cartographer of myth",
)
EXCLUDED_STATE_PREFIXES = (
    "Error Note",
)
IGNORED_ACTION_TYPES = ("updateTime",)
DEFAULT_MAX_STATE_CHARS = 20000
REJECTION_REASON_MAX_CHARS = 240


def _hash_state(text: str) -> str:
    """Return a short stable hash for a state string."""
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]


def _load_json_file(path: Path) -> Any:
    """Load a JSON file, returning None on any failure."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return None


def _iter_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    """Yield parsed JSON objects from a JSONL file, skipping malformed lines."""
    try:
        raw_lines = path.read_text(encoding="utf-8").splitlines()
    except (FileNotFoundError, OSError, UnicodeDecodeError):
        return
    for line in raw_lines:
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            yield record


def _parse_structured_content(content: Any) -> Optional[Any]:
    """Parse assistant/narrator content that may be a JSON string or already parsed."""
    if isinstance(content, (dict, list)):
        return content
    if not isinstance(content, str):
        return None
    try:
        return json.loads(content)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


def _non_time_actions(content: Any) -> Optional[List[str]]:
    """Return non-updateTime action names, or None when content is unparseable.

    Returns an empty list when the content parses but carries no actions.
    """
    parsed = _parse_structured_content(content)
    if not isinstance(parsed, dict):
        return None
    actions = parsed.get("actions")
    if not isinstance(actions, list):
        return []
    names: List[str] = []
    for entry in actions:
        if not isinstance(entry, dict):
            continue
        name = entry.get("action")
        if isinstance(name, str) and name and name not in IGNORED_ACTION_TYPES:
            names.append(name)
    return names


def _is_excluded_state(text: str) -> Optional[str]:
    """Return an exclusion reason when the state text is not a predictable turn."""
    for marker in EXCLUDED_STATE_MARKERS:
        if marker in text:
            return "module_creation_prompt"
    stripped = text.lstrip()
    for prefix in EXCLUDED_STATE_PREFIXES:
        if stripped.startswith(prefix):
            return "retry_correction_note"
    return None


def _make_case(
    case_id: str,
    source: str,
    state: str,
    label: bool,
    strength: str,
    evidence: str,
    meta: Dict[str, Any],
    max_state_chars: int,
) -> Dict[str, Any]:
    """Build a normalized eval case record."""
    truncated = len(state) > max_state_chars
    capped = state[:max_state_chars] if truncated else state
    return {
        "case_id": case_id,
        "source": source,
        "state": capped,
        "state_chars": len(capped),
        "state_hash": _hash_state(capped),
        "truncated": truncated,
        "label_requires_actions": bool(label),
        "label_strength": strength,
        "label_evidence": evidence,
        "meta": meta,
    }


def extract_history_cases(
    history: Any,
    max_state_chars: int = DEFAULT_MAX_STATE_CHARS,
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """Extract user->assistant pairs with action-derived labels."""
    cases: List[Dict[str, Any]] = []
    skipped = {
        "non_user_entries": 0,
        "empty_state": 0,
        "excluded_module_creation_prompt": 0,
        "excluded_retry_correction_note": 0,
        "no_next_assistant": 0,
        "unparseable_assistant": 0,
    }
    if not isinstance(history, list):
        return cases, skipped

    for index, message in enumerate(history):
        if not isinstance(message, dict) or message.get("role") != "user":
            skipped["non_user_entries"] += 1
            continue
        state = message.get("content")
        if not isinstance(state, str) or not state.strip():
            skipped["empty_state"] += 1
            continue
        exclusion = _is_excluded_state(state)
        if exclusion == "module_creation_prompt":
            skipped["excluded_module_creation_prompt"] += 1
            continue
        if exclusion == "retry_correction_note":
            skipped["excluded_retry_correction_note"] += 1
            continue

        next_assistant: Optional[Dict[str, Any]] = None
        for follower in history[index + 1:]:
            if not isinstance(follower, dict):
                continue
            if follower.get("role") == "assistant":
                next_assistant = follower
                break
            if follower.get("role") == "user":
                break
        if next_assistant is None:
            skipped["no_next_assistant"] += 1
            continue

        actions = _non_time_actions(next_assistant.get("content"))
        if actions is None:
            skipped["unparseable_assistant"] += 1
            continue

        case_id = "hist-{:04d}".format(index)
        evidence = "next_assistant_actions:" + (",".join(sorted(set(actions))) if actions else "none")
        meta: Dict[str, Any] = {}
        active_pc = message.get("active_pc")
        if isinstance(active_pc, str) and active_pc:
            meta["active_pc"] = active_pc
        cases.append(
            _make_case(
                case_id=case_id,
                source="conversation_history",
                state=state,
                label=bool(actions),
                strength="strong",
                evidence=evidence,
                meta=meta,
                max_state_chars=max_state_chars,
            )
        )

    return cases, skipped


def extract_rejected_cases(
    records: Iterable[Dict[str, Any]],
    max_state_chars: int = DEFAULT_MAX_STATE_CHARS,
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """Extract rejected narrator attempts with weak action-derived labels."""
    cases: List[Dict[str, Any]] = []
    skipped = {
        "empty_state": 0,
        "unparseable_rejected_response": 0,
    }

    for position, record in enumerate(records):
        if not isinstance(record, dict):
            skipped["empty_state"] += 1
            continue
        state = record.get("user_input")
        if not isinstance(state, str) or not state.strip():
            skipped["empty_state"] += 1
            continue
        actions = _non_time_actions(record.get("rejected_response"))
        if actions is None:
            skipped["unparseable_rejected_response"] += 1
            continue

        meta: Dict[str, Any] = {}
        for key in ("module", "location_id", "location_name", "timestamp"):
            value = record.get(key)
            if isinstance(value, str) and value:
                meta[key] = value
        reason = record.get("rejection_reason")
        if isinstance(reason, str) and reason:
            meta["rejection_reason"] = reason[:REJECTION_REASON_MAX_CHARS]

        evidence = "rejected_response_actions:" + (",".join(sorted(set(actions))) if actions else "none")
        cases.append(
            _make_case(
                case_id="rej-{:04d}".format(position),
                source="rejected_turns",
                state=state,
                label=bool(actions),
                strength="weak",
                evidence=evidence,
                meta=meta,
                max_state_chars=max_state_chars,
            )
        )

    return cases, skipped


def dedupe_cases(cases: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], int]:
    """Deduplicate by state hash, preferring strong labels over weak ones."""
    best: Dict[str, Dict[str, Any]] = {}
    duplicates = 0
    for case in cases:
        key = case.get("state_hash", "")
        existing = best.get(key)
        if existing is None:
            best[key] = case
            continue
        duplicates += 1
        if existing.get("label_strength") != "strong" and case.get("label_strength") == "strong":
            best[key] = case
    ordered = sorted(best.values(), key=lambda c: (c.get("source", ""), c.get("case_id", "")))
    return ordered, duplicates


def _median(values: List[int]) -> int:
    """Return an integer median for a list of ints (0 when empty)."""
    if not values:
        return 0
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return int(ordered[middle])
    return int((ordered[middle - 1] + ordered[middle]) / 2)


def summarize_cases(cases: List[Dict[str, Any]], skipped: Dict[str, int]) -> Dict[str, Any]:
    """Build a compact, content-free summary of the eval set."""
    by_source: Dict[str, int] = {}
    by_label: Dict[str, int] = {"requires_actions_true": 0, "requires_actions_false": 0}
    by_strength: Dict[str, int] = {}
    lengths = [int(c.get("state_chars", 0)) for c in cases]
    for case in cases:
        source = str(case.get("source", "unknown"))
        by_source[source] = by_source.get(source, 0) + 1
        strength = str(case.get("label_strength", "unknown"))
        by_strength[strength] = by_strength.get(strength, 0) + 1
        if case.get("label_requires_actions"):
            by_label["requires_actions_true"] += 1
        else:
            by_label["requires_actions_false"] += 1
    return {
        "total_cases": len(cases),
        "by_source": by_source,
        "by_label": by_label,
        "by_strength": by_strength,
        "truncated_cases": sum(1 for c in cases if c.get("truncated")),
        "state_chars": {
            "min": min(lengths) if lengths else 0,
            "median": _median(lengths),
            "max": max(lengths) if lengths else 0,
            "p90": sorted(lengths)[int(len(lengths) * 0.9)] if lengths else 0,
        },
        "skipped": skipped,
    }


def write_eval_set(path: Path, cases: List[Dict[str, Any]]) -> None:
    """Write cases as JSONL, creating parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for case in cases:
            handle.write(json.dumps(case, ensure_ascii=True) + "\n")


def build_eval_set(
    history_path: Path,
    rejected_path: Path,
    sources: Tuple[str, ...],
    max_state_chars: int = DEFAULT_MAX_STATE_CHARS,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Build the combined, deduplicated eval set plus a summary."""
    all_cases: List[Dict[str, Any]] = []
    merged_skipped: Dict[str, int] = {}

    if "history" in sources:
        history = _load_json_file(history_path)
        cases, skipped = extract_history_cases(history, max_state_chars=max_state_chars)
        all_cases.extend(cases)
        for key, value in skipped.items():
            merged_skipped["history_" + key] = value

    if "rejected" in sources:
        records = list(_iter_jsonl(rejected_path))
        cases, skipped = extract_rejected_cases(records, max_state_chars=max_state_chars)
        all_cases.extend(cases)
        for key, value in skipped.items():
            merged_skipped["rejected_" + key] = value

    deduped, duplicates = dedupe_cases(all_cases)
    summary = summarize_cases(deduped, merged_skipped)
    summary["duplicates_removed"] = duplicates
    return deduped, summary


def print_summary(summary: Dict[str, Any], out_path: Path) -> None:
    """Print an ASCII, content-free summary."""
    print("[JEV EVAL] cases={} -> {}".format(summary.get("total_cases", 0), out_path))
    print("[JEV EVAL] by_source={}".format(json.dumps(summary.get("by_source", {}), sort_keys=True)))
    print("[JEV EVAL] by_label={}".format(json.dumps(summary.get("by_label", {}), sort_keys=True)))
    print("[JEV EVAL] by_strength={}".format(json.dumps(summary.get("by_strength", {}), sort_keys=True)))
    print("[JEV EVAL] state_chars={}".format(json.dumps(summary.get("state_chars", {}), sort_keys=True)))
    print("[JEV EVAL] duplicates_removed={}".format(summary.get("duplicates_removed", 0)))
    print("[JEV EVAL] skipped={}".format(json.dumps(summary.get("skipped", {}), sort_keys=True)))


def parse_sources(raw: str) -> Tuple[str, ...]:
    """Parse and validate a comma-separated source selector."""
    allowed = {"history", "rejected"}
    parts = [part.strip().lower() for part in raw.split(",") if part.strip()]
    invalid = [part for part in parts if part not in allowed]
    if invalid:
        raise ValueError("unsupported source(s): {}".format(",".join(sorted(set(invalid)))))
    return tuple(sorted(set(parts)))


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description="Extract the Jev Phase 0 action-prediction eval set.")
    parser.add_argument("--history", default=str(DEFAULT_HISTORY), help="conversation_history.json path")
    parser.add_argument("--rejected", default=str(DEFAULT_REJECTED), help="rejected narrator turns JSONL path")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="output JSONL path")
    parser.add_argument("--sources", default="history,rejected", help="comma-separated: history,rejected")
    parser.add_argument("--max-state-chars", type=int, default=DEFAULT_MAX_STATE_CHARS)
    args = parser.parse_args(argv)

    try:
        sources = parse_sources(args.sources)
    except ValueError as exc:
        print("[JEV EVAL] ERROR: {}".format(exc))
        return 2

    cases, summary = build_eval_set(
        history_path=Path(args.history),
        rejected_path=Path(args.rejected),
        sources=sources,
        max_state_chars=args.max_state_chars,
    )
    out_path = Path(args.out)
    write_eval_set(out_path, cases)
    print_summary(summary, out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
