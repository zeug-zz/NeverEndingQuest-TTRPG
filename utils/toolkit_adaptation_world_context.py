# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.

"""
NeverEndingQuest Utility - Toolkit Adaptation World Context
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

Provider-free, bounded, read-only world-narrative context for the explicit
LLM adaptation lane. The returned pack is advisory context only. It does not
apply canon, alter registry or campaign state, or make mechanical decisions.

This software is free for non-commercial and educational use.
Commercial competing use is prohibited for 2 years from release.
See LICENSE file for full terms.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import quote


WORLD_CONTEXT_CONTRACT_VERSION = "toolkit_adaptation_world_context.v1"
WORLD_CONTEXT_VERSION = WORLD_CONTEXT_CONTRACT_VERSION

WORLD_CONTEXT_STATUS_AVAILABLE = "available"
WORLD_CONTEXT_STATUS_FALLBACK = "fallback"
WORLD_CONTEXT_SEED_STATUS_AVAILABLE = "available"
WORLD_CONTEXT_SEED_STATUS_UNAVAILABLE = "unavailable"
WORLD_CONTEXT_SEED_STATUS_INVALID = "invalid"

WORLD_CONTEXT_FALLBACK_NONE = "none"
WORLD_CONTEXT_FALLBACK_SEED_UNAVAILABLE = "seed_data_unavailable"
WORLD_CONTEXT_FALLBACK_SEED_INVALID = "seed_data_invalid"
WORLD_CONTEXT_FALLBACK_CONTEXT_INCOMPLETE = "context_incomplete"

# TABLETOP MODE: Task 6.2 exposes only this scalar provenance envelope to the
# adaptation author and report surfaces.  The world context pack itself stays
# on the Python side of the boundary.
WORLD_CONTEXT_PROVENANCE_VERSION = "toolkit_adaptation_world_context_provenance.v1"

DEFAULT_MEMORY_DB_PATH = "data/memory.db"
DEFAULT_WORLD_NARRATIVE_SEED_DB_PATH = "data/world_narrative_seed.db"
DEFAULT_REGISTRY_PATH = "modules/world_registry.json"
DEFAULT_CAMPAIGN_PATH = "modules/campaign.json"

MAX_CONTEXT_SERIALIZED_CHARS = 24000
MAX_CONTEXT_CHARS = MAX_CONTEXT_SERIALIZED_CHARS
MAX_DIAGNOSTICS = 24
MAX_TEXT_CHARS = 420
MAX_MODEL_TEXT_CHARS = 640
MAX_PRESSURES = 8
MAX_REGISTRY_MODULES = 24
MAX_MODULE_LIST_ITEMS = 24
MAX_SEEDS = 10
MAX_SEED_SCAN_ROWS = 64
MAX_SEED_CONTENT_KEYS = 12
MAX_SEED_CONTENT_ITEMS = 6
MAX_NESTED_CONTENT_DEPTH = 2

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CREDENTIAL_RE = re.compile(
    r"(?i)(?:api[_ -]?key|authorization|bearer|password|secret|credential|token)\s*[:=]\s*[^\s,;]+"
)
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[^\s,;]+")

_CAMPAIGN_TEXT_FIELDS = {
    "summary",
    "premise",
    "setting",
    "tone",
    "current_focus",
}
_CAMPAIGN_LIST_FIELDS = {
    "themes",
    "conflicts",
    "domains",
    "factions",
    "active_threads",
}

_SEED_CONTENT_FIELDS = {
    "summary",
    "premise",
    "hook",
    "objective",
    "pressure",
    "continuity",
    "tone",
    "setting",
    "resolution",
    "follow_up",
    "world_hooks",
    "themes",
    "factions",
    "locations",
    "npcs",
    "encounters",
    "items",
    "tags",
}
_SEED_NESTED_FIELDS = {
    "name",
    "summary",
    "purpose",
    "role",
    "description",
    "hook",
    "objective",
    "pressure",
    "scope",
    "relation",
}

_APPROVED_VALUES = {"1", "true", "approved", "accepted", "ready", "applied"}


def _ascii_text(value: Any, limit: int = MAX_TEXT_CHARS) -> str:
    """Return bounded ASCII text without exposing arbitrary source content."""
    if value is None:
        return ""
    if isinstance(value, (Mapping, list, tuple, set)):
        return ""
    text = str(value).replace("\x00", " ").replace("\r\n", "\n").replace("\r", "\n")
    text = text.encode("ascii", "replace").decode("ascii").strip()
    text = _BEARER_RE.sub("Bearer [REDACTED]", text)
    text = _CREDENTIAL_RE.sub("[REDACTED_CREDENTIAL]", text)
    if len(text) <= limit:
        return text
    marker = " [truncated]"
    return text[: max(0, limit - len(marker))].rstrip() + marker


def _diagnostic(
    code: str,
    message: str,
    path: str = "",
    severity: str = "warning",
) -> Dict[str, str]:
    """Build one deterministic, bounded diagnostic."""
    return {
        "code": _ascii_text(code, 96),
        "message": _ascii_text(message, 240),
        "path": _ascii_text(path, 160),
        "severity": severity if severity in {"warning", "error"} else "warning",
    }


def _dedupe_diagnostics(diagnostics: Iterable[Mapping[str, Any]]) -> List[Dict[str, str]]:
    """Sort and deduplicate diagnostics so repeated reads are stable."""
    unique = {}
    for item in diagnostics:
        if not isinstance(item, Mapping):
            continue
        normalized = _diagnostic(
            str(item.get("code") or "context_error"),
            str(item.get("message") or "World context is degraded."),
            str(item.get("path") or ""),
            str(item.get("severity") or "warning"),
        )
        key = tuple(normalized[field] for field in ("code", "message", "path", "severity"))
        unique[key] = normalized
    ordered = sorted(unique.values(), key=lambda item: (item["code"], item["path"], item["message"]))
    return ordered[:MAX_DIAGNOSTICS]


def _canonical_json(value: Any) -> str:
    """Serialize context with stable key ordering and no provider-specific data."""
    return json.dumps(value, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":"))


def _stable_input_key(value: Any) -> str:
    """Return a deterministic ordering key for JSON-like input values."""
    try:
        return _canonical_json(value)
    except (TypeError, ValueError):
        return _ascii_text(value, MAX_TEXT_CHARS)


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _safe_identifier(value: Any, limit: int = 160) -> str:
    """Return a bounded identifier with path and credential-like text removed."""
    text = _ascii_text(value, limit)
    if not text or "/" in text or "\\" in text or ".." in text:
        return ""
    return text


def build_world_context_provenance(context: Any = None) -> Dict[str, Any]:
    """Return scalar world-context provenance without copying world state.

    ``context`` may be the task-6.1 context pack, its ``provenance`` mapping,
    or an attempt metadata mapping that already contains the scalar fields.
    The returned object deliberately contains no campaign model, pressure,
    registry, or seed content.  Missing or unusable context becomes an
    explicit unavailable fallback so callers can report honest provenance.
    """
    raw: Mapping[str, Any] = context if isinstance(context, Mapping) else {}
    nested = raw.get("world_context_provenance")
    if isinstance(nested, Mapping):
        source: Mapping[str, Any] = nested
    else:
        candidate = raw.get("provenance")
        source = candidate if isinstance(candidate, Mapping) else raw

    def _pick(*keys: str) -> Any:
        for key in keys:
            if key in source and source.get(key) not in (None, ""):
                return source.get(key)
            if key in raw and raw.get(key) not in (None, ""):
                return raw.get(key)
        return None

    context_status = str(_pick("context_status", "world_context_status", "status") or "unavailable").strip().lower()
    if context_status not in {WORLD_CONTEXT_STATUS_AVAILABLE, WORLD_CONTEXT_STATUS_FALLBACK, "unavailable"}:
        context_status = WORLD_CONTEXT_STATUS_FALLBACK

    seed_status = str(_pick("world_seed_status") or WORLD_CONTEXT_SEED_STATUS_UNAVAILABLE).strip().lower()
    if seed_status not in {
        WORLD_CONTEXT_SEED_STATUS_AVAILABLE,
        WORLD_CONTEXT_SEED_STATUS_UNAVAILABLE,
        WORLD_CONTEXT_SEED_STATUS_INVALID,
    }:
        seed_status = WORLD_CONTEXT_SEED_STATUS_INVALID

    seed_hash = _pick("world_seed_hash")
    if not isinstance(seed_hash, str) or not _SHA256_RE.fullmatch(seed_hash.strip().lower()):
        if seed_status == WORLD_CONTEXT_SEED_STATUS_AVAILABLE:
            seed_status = WORLD_CONTEXT_SEED_STATUS_INVALID
        seed_hash = None
    else:
        seed_hash = seed_hash.strip().lower()

    seed_version = _ascii_text(_pick("world_seed_version"), 120) or None
    if seed_status != WORLD_CONTEXT_SEED_STATUS_AVAILABLE:
        seed_version = None
        seed_hash = None

    context_hash = _pick("context_hash", "world_context_hash")
    if not isinstance(context_hash, str) or not _SHA256_RE.fullmatch(context_hash.strip().lower()):
        context_hash = None
    else:
        context_hash = context_hash.strip().lower()

    selected_module = _safe_identifier(_pick("selected_module", "world_context_selected_module"), 140) or None
    fallback_status = _ascii_text(_pick("fallback_status", "world_context_fallback_status"), 80)
    if not fallback_status:
        fallback_status = (
            WORLD_CONTEXT_FALLBACK_NONE
            if seed_status == WORLD_CONTEXT_SEED_STATUS_AVAILABLE and context_status == WORLD_CONTEXT_STATUS_AVAILABLE
            else WORLD_CONTEXT_FALLBACK_SEED_INVALID
            if seed_status == WORLD_CONTEXT_SEED_STATUS_INVALID
            else WORLD_CONTEXT_FALLBACK_SEED_UNAVAILABLE
        )

    return {
        "provenance_version": WORLD_CONTEXT_PROVENANCE_VERSION,
        "context_version": _ascii_text(_pick("context_version", "version"), 120) or WORLD_CONTEXT_CONTRACT_VERSION,
        "context_status": context_status,
        "fallback_status": fallback_status,
        "world_seed_status": seed_status,
        "world_seed_version": seed_version,
        "world_seed_hash": seed_hash,
        "context_hash": context_hash,
        "selected_module": selected_module,
        "read_only": True,
        "provider_free": True,
        "raw_context_included": False,
        "canon_write_allowed": False,
        "registry_write_allowed": False,
        "mechanical_write_allowed": False,
    }


# Compatibility aliases make the provenance boundary discoverable without
# exposing another retrieval or persistence mechanism.
extract_world_context_provenance = build_world_context_provenance
normalize_world_context_provenance = build_world_context_provenance


def _text_list(value: Any, limit: int = MAX_MODULE_LIST_ITEMS) -> List[str]:
    """Normalize a bounded list of short narrative labels."""
    if not isinstance(value, (list, tuple)):
        return []
    values = {_ascii_text(item, MAX_TEXT_CHARS) for item in value}
    return sorted(item for item in values if item)[:limit]


def _normalize_nested_value(value: Any, depth: int = 0) -> Any:
    """Keep only compact narrative scalar/list/object values."""
    if isinstance(value, str):
        return _ascii_text(value)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    if isinstance(value, bool):
        return value
    if depth >= MAX_NESTED_CONTENT_DEPTH:
        return _ascii_text(value, 180) if value not in (None, "") else ""
    if isinstance(value, list):
        normalized = []
        for item in value[:MAX_SEED_CONTENT_ITEMS]:
            compact = _normalize_nested_value(item, depth + 1)
            if compact not in (None, "", [], {}):
                normalized.append(compact)
        return normalized
    if isinstance(value, Mapping):
        normalized_object: Dict[str, Any] = {}
        for key in sorted(value, key=lambda item: str(item)):
            if not isinstance(key, str):
                continue
            if key not in _SEED_NESTED_FIELDS:
                continue
            compact = _normalize_nested_value(value[key], depth + 1)
            if compact not in (None, "", [], {}):
                normalized_object[key] = compact
            if len(normalized_object) >= MAX_SEED_CONTENT_KEYS:
                break
        return normalized_object
    return ""


def _normalize_seed_content(value: Any) -> Optional[Dict[str, Any]]:
    """Allowlist compact seed content instead of returning raw JSON."""
    if isinstance(value, str):
        text = _ascii_text(value, MAX_TEXT_CHARS)
        return {"summary": text} if text else None
    if isinstance(value, list):
        items = [_normalize_nested_value(item) for item in value[:MAX_SEED_CONTENT_ITEMS]]
        items = [item for item in items if item not in (None, "", [], {})]
        return {"items": items} if items else None
    if not isinstance(value, Mapping):
        return None

    normalized: Dict[str, Any] = {}
    for key in sorted(value, key=lambda item: str(item)):
        if not isinstance(key, str):
            continue
        if key not in _SEED_CONTENT_FIELDS:
            continue
        compact = _normalize_nested_value(value[key])
        if compact not in (None, "", [], {}):
            normalized[key] = compact
        if len(normalized) >= MAX_SEED_CONTENT_KEYS:
            break
    return normalized or None


def _normalize_seed(value: Any, index: int, *, require_approval_marker: bool = False) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, str]]]:
    """Normalize one approved seed and return a diagnostic for invalid data."""
    if not isinstance(value, Mapping):
        return None, _diagnostic("invalid_seed_record", "Approved seed must be an object.", f"approved_module_seeds[{index}]", "error")

    marker_present = any(key in value for key in ("approved", "approval_status", "status", "applied"))
    marker_approved = False
    if marker_present:
        for key in ("approved", "approval_status", "status", "applied"):
            if key not in value:
                continue
            marker = value.get(key)
            if isinstance(marker, bool):
                marker_approved = marker_approved or marker
            elif isinstance(marker, (int, float)) and not isinstance(marker, bool):
                marker_approved = marker_approved or marker == 1
            else:
                marker_approved = marker_approved or str(marker).strip().lower() in _APPROVED_VALUES

    if require_approval_marker:
        if not marker_present:
            return None, _diagnostic("seed_approval_marker_missing", "Seed approval could not be established.", f"approved_module_seeds[{index}]", "error")
        if not marker_approved:
            return None, None
    elif marker_present and not marker_approved:
        return None, _diagnostic("seed_not_approved", "Seed is not approved for adaptation context.", f"approved_module_seeds[{index}]", "error")

    module_slug = _safe_identifier(
        value.get("module_slug") or value.get("module") or value.get("module_name"),
        160,
    )
    seed_type = _safe_identifier(value.get("seed_type") or value.get("type"), 96)
    if not module_slug or not seed_type:
        return None, _diagnostic("invalid_seed_record", "Approved seed requires module_slug and seed_type.", f"approved_module_seeds[{index}]", "error")

    content_value = value.get("content")
    if content_value is None:
        content_value = value.get("content_json")
    if isinstance(content_value, str):
        try:
            content_value = json.loads(content_value)
        except (TypeError, ValueError):
            return None, _diagnostic("invalid_seed_json", "Approved seed content is not valid JSON.", f"approved_module_seeds[{index}].content", "error")
    content = _normalize_seed_content(content_value)
    if not content:
        return None, _diagnostic("invalid_seed_content", "Approved seed has no allowlisted narrative content.", f"approved_module_seeds[{index}].content", "error")

    seed: Dict[str, Any] = {
        "module_slug": module_slug,
        "seed_type": seed_type,
        "content": content,
    }
    seed_id = _safe_identifier(value.get("seed_id"), 96)
    if seed_id:
        seed["seed_id"] = seed_id
    return seed, None


def _normalize_seeds(value: Any, *, require_approval_marker: bool = False) -> Tuple[str, List[Dict[str, Any]], List[Dict[str, str]]]:
    if not isinstance(value, list):
        return WORLD_CONTEXT_SEED_STATUS_INVALID, [], [
            _diagnostic("invalid_seed_data", "Approved module seeds must be a list.", "approved_module_seeds", "error")
        ]
    if not value:
        return WORLD_CONTEXT_SEED_STATUS_UNAVAILABLE, [], [
            _diagnostic("no_approved_module_seeds", "No approved module seeds are available.", "approved_module_seeds")
        ]

    normalized: List[Dict[str, Any]] = []
    diagnostics: List[Dict[str, str]] = []
    ordered_values = sorted(list(value), key=_stable_input_key)
    for index, item in enumerate(ordered_values[:MAX_SEED_SCAN_ROWS]):
        seed, diagnostic = _normalize_seed(
            item,
            index,
            require_approval_marker=require_approval_marker,
        )
        if diagnostic is not None:
            diagnostics.append(diagnostic)
        if seed is not None:
            normalized.append(seed)

    normalized.sort(key=lambda item: (
        str(item.get("module_slug", "")).lower(),
        str(item.get("seed_type", "")).lower(),
        str(item.get("seed_id", "")).lower(),
        _canonical_json(item.get("content", {})),
    ))
    normalized = normalized[:MAX_SEEDS]
    if any(item.get("severity") == "error" for item in diagnostics):
        return WORLD_CONTEXT_SEED_STATUS_INVALID, normalized, diagnostics
    if not normalized:
        return WORLD_CONTEXT_SEED_STATUS_UNAVAILABLE, [], diagnostics or [
            _diagnostic("no_approved_module_seeds", "No approved module seeds are available.", "approved_module_seeds")
        ]
    return WORLD_CONTEXT_SEED_STATUS_AVAILABLE, normalized, diagnostics


def _normalize_campaign_model(value: Any, campaign_id: Any = None, version: Any = None) -> Optional[Dict[str, Any]]:
    if not isinstance(value, Mapping):
        return None
    source = value.get("campaign_model") if isinstance(value.get("campaign_model"), Mapping) else value
    result: Dict[str, Any] = {}
    resolved_campaign_id = _safe_identifier(source.get("campaign_id") or campaign_id, 120)
    if resolved_campaign_id:
        result["campaign_id"] = resolved_campaign_id
    resolved_version = source.get("version", version)
    if isinstance(resolved_version, int) and not isinstance(resolved_version, bool) and resolved_version >= 0:
        result["version"] = resolved_version

    aliases = {
        "summary": ("summary", "world_summary"),
        "premise": ("premise", "campaign_premise"),
        "setting": ("setting", "world_setting"),
        "tone": ("tone", "tone_guidance"),
        "current_focus": ("current_focus", "focus"),
    }
    for output_key, candidates in aliases.items():
        for candidate in candidates:
            text = _ascii_text(source.get(candidate), MAX_MODEL_TEXT_CHARS)
            if text:
                result[output_key] = text
                break
    for field in sorted(_CAMPAIGN_LIST_FIELDS):
        values = _text_list(source.get(field), MAX_MODULE_LIST_ITEMS)
        if values:
            result[field] = values
    return result or None


def _normalize_pressure(value: Any, index: int) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, str]]]:
    if isinstance(value, str):
        summary = _ascii_text(value)
        return ({"summary": summary}, None) if summary else (None, _diagnostic("invalid_active_pressure", "Active pressure summary is empty.", f"active_pressures[{index}]", "error"))
    if not isinstance(value, Mapping):
        return None, _diagnostic("invalid_active_pressure", "Active pressure must be an object or text.", f"active_pressures[{index}]", "error")
    summary = _ascii_text(value.get("summary") or value.get("pressure") or value.get("description") or value.get("hook"))
    if not summary:
        return None, _diagnostic("invalid_active_pressure", "Active pressure requires a bounded summary.", f"active_pressures[{index}]", "error")
    pressure: Dict[str, Any] = {"summary": summary}
    for output_key, candidates, limit in (
        ("thread_id", ("thread_id", "id"), 120),
        ("pressure_type", ("pressure_type", "thread_type", "type"), 96),
        ("status", ("status",), 32),
    ):
        for candidate in candidates:
            text = _safe_identifier(value.get(candidate), limit)
            if text:
                pressure[output_key] = text
                break
    priority = value.get("priority")
    if isinstance(priority, int) and not isinstance(priority, bool):
        pressure["priority"] = max(0, min(priority, 100))
    return pressure, None


def _normalize_pressures(value: Any) -> Tuple[str, List[Dict[str, Any]], List[Dict[str, str]]]:
    if not isinstance(value, list):
        return "invalid", [], [_diagnostic("invalid_active_pressures", "Active pressures must be a list.", "active_pressures", "error")]
    normalized: List[Dict[str, Any]] = []
    diagnostics: List[Dict[str, str]] = []
    ordered_values = sorted(list(value), key=_stable_input_key)
    for index, item in enumerate(ordered_values[:MAX_PRESSURES]):
        pressure, diagnostic = _normalize_pressure(item, index)
        if pressure is not None:
            normalized.append(pressure)
        if diagnostic is not None:
            diagnostics.append(diagnostic)
    normalized.sort(key=lambda item: (-int(item.get("priority", 0)), str(item.get("thread_id", "")).lower(), str(item.get("summary", "")).lower()))
    if any(item.get("severity") == "error" for item in diagnostics):
        return "invalid", normalized, diagnostics
    return "available", normalized, diagnostics


def _normalize_registry_module(module_slug: Any, value: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(value, Mapping):
        value = {}
    slug = _safe_identifier(module_slug or value.get("module_slug") or value.get("moduleName"), 140)
    name = _ascii_text(value.get("module_name") or value.get("moduleName") or slug, 180)
    if not slug and not name:
        return None
    module: Dict[str, Any] = {}
    if slug:
        module["module_slug"] = slug
    if name:
        module["module_name"] = name
    for key, aliases in (
        ("plot_objective", ("plot_objective", "plotObjective")),
        ("starting_location", ("starting_location", "startingLocation")),
    ):
        for alias in aliases:
            text = _ascii_text(value.get(alias), MAX_TEXT_CHARS)
            if text:
                module[key] = text
                break
    area_count = value.get("area_count", value.get("areaCount"))
    if isinstance(area_count, int) and not isinstance(area_count, bool) and area_count >= 0:
        module["area_count"] = min(area_count, 10000)
    level_range = value.get("level_range", value.get("levelRange"))
    if isinstance(level_range, Mapping):
        minimum = level_range.get("min")
        maximum = level_range.get("max")
        if isinstance(minimum, int) and isinstance(maximum, int) and not isinstance(minimum, bool) and not isinstance(maximum, bool):
            module["level_range"] = {"min": minimum, "max": maximum}
    return module


def _normalize_registry_context(registry: Any, campaign: Any = None) -> Optional[Dict[str, Any]]:
    if registry is not None and not isinstance(registry, Mapping):
        return None
    registry = registry if isinstance(registry, Mapping) else {}
    campaign = campaign if isinstance(campaign, Mapping) else {}
    result: Dict[str, Any] = {}
    world_name = _ascii_text(registry.get("world_name") or registry.get("worldName"), 180)
    registry_version = _ascii_text(registry.get("registry_version") or registry.get("registryVersion"), 80)
    if world_name:
        result["world_name"] = world_name
    if registry_version:
        result["registry_version"] = registry_version

    modules = registry.get("modules")
    module_items: List[Tuple[str, Any]] = []
    if isinstance(modules, Mapping):
        module_items = [(str(key), value) for key, value in modules.items()]
    elif isinstance(modules, list):
        module_items = [(str(index), value) for index, value in enumerate(modules)]
    elif isinstance(registry.get("module_slugs"), list):
        module_items = [(str(value), {}) for value in registry.get("module_slugs", [])]
    normalized_modules = []
    for module_slug, module_value in module_items:
        module = _normalize_registry_module(module_slug, module_value)
        if module is not None:
            normalized_modules.append(module)
    normalized_modules.sort(key=lambda item: (str(item.get("module_slug", "")).lower(), str(item.get("module_name", "")).lower()))
    if normalized_modules:
        result["modules"] = normalized_modules[:MAX_REGISTRY_MODULES]
        result["module_count"] = len(normalized_modules)

    campaign_aliases = {
        "active_module": ("active_module", "currentModule"),
        "hub_module": ("hub_module", "hubModule"),
    }
    for output_key, aliases in campaign_aliases.items():
        for alias in aliases:
            text = _safe_identifier(campaign.get(alias) or registry.get(alias), 140)
            if text:
                result[output_key] = text
                break
    for output_key, alias in (
        ("completed_modules", "completedModules"),
        ("available_modules", "availableModules"),
    ):
        values = _text_list(campaign.get(alias) if alias in campaign else registry.get(output_key), MAX_MODULE_LIST_ITEMS)
        if values:
            result[output_key] = values
    world_state = campaign.get("worldState")
    if isinstance(world_state, Mapping):
        major_decisions = _text_list(world_state.get("majorDecisions"), 8)
        if major_decisions:
            result["major_decisions"] = major_decisions
        if isinstance(world_state.get("hubEstablished"), bool):
            result["hub_established"] = world_state["hubEstablished"]
    return result or None


def _read_json(path: Any, kind: str) -> Tuple[Optional[Any], Optional[Dict[str, str]]]:
    if path in (None, ""):
        return None, _diagnostic(f"{kind}_unavailable", f"{kind.replace('_', ' ').capitalize()} was not supplied.", kind)
    try:
        candidate = Path(os.fspath(path))
    except (TypeError, ValueError):
        return None, _diagnostic(f"invalid_{kind}", f"{kind.replace('_', ' ').capitalize()} path is invalid.", kind, "error")
    if not candidate.exists() or not candidate.is_file():
        return None, _diagnostic(f"{kind}_unavailable", f"{kind.replace('_', ' ').capitalize()} file is unavailable.", kind)
    try:
        with candidate.open("r", encoding="utf-8") as handle:
            return json.load(handle), None
    except (OSError, ValueError):
        return None, _diagnostic(f"invalid_{kind}", f"{kind.replace('_', ' ').capitalize()} file is invalid.", kind, "error")


def _open_sqlite_read_only(path: Any) -> Tuple[Optional[sqlite3.Connection], Optional[str]]:
    if path in (None, ""):
        return None, "missing"
    try:
        candidate = Path(os.fspath(path))
    except (TypeError, ValueError):
        return None, "invalid"
    if not candidate.exists() or not candidate.is_file():
        return None, "missing"
    try:
        uri = "file:" + quote(str(candidate.resolve()), safe="/:") + "?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
        connection.row_factory = sqlite3.Row
        return connection, None
    except (OSError, sqlite3.Error):
        return None, "invalid"


def _table_columns(connection: sqlite3.Connection, table_name: str) -> List[str]:
    rows = connection.execute("PRAGMA table_info(" + table_name + ")").fetchall()
    return [str(row[1]) for row in rows]


def _table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    row = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return bool(row)


def _load_seed_version(connection: sqlite3.Connection) -> str:
    try:
        if _table_exists(connection, "schema_version"):
            row = connection.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1").fetchone()
            if row and row[0] not in (None, ""):
                return _ascii_text(row[0], 80)
    except sqlite3.Error:
        pass
    return "module_narrative_seeds.v1"


def _load_seeds_from_db(path: Any, source_label: str) -> Tuple[str, List[Dict[str, Any]], Optional[str], List[Dict[str, str]]]:
    connection, error_kind = _open_sqlite_read_only(path)
    if connection is None:
        code = "seed_database_missing" if error_kind == "missing" else "seed_database_invalid"
        status = WORLD_CONTEXT_SEED_STATUS_UNAVAILABLE if error_kind == "missing" else WORLD_CONTEXT_SEED_STATUS_INVALID
        message = "Approved seed database is unavailable." if error_kind == "missing" else "Approved seed database is invalid."
        return status, [], None, [
            _diagnostic(code, message, source_label, "error" if error_kind == "invalid" else "warning")
        ]
    try:
        if not _table_exists(connection, "module_narrative_seeds"):
            return WORLD_CONTEXT_SEED_STATUS_UNAVAILABLE, [], None, [
                _diagnostic("seed_table_missing", "Approved module seed table is unavailable.", source_label)
            ]
        columns = _table_columns(connection, "module_narrative_seeds")
        required = {"module_slug", "seed_type", "content_json"}
        if not required.issubset(set(columns)):
            return WORLD_CONTEXT_SEED_STATUS_INVALID, [], None, [
                _diagnostic("seed_schema_invalid", "Approved module seed table is missing required columns.", source_label, "error")
            ]
        selected = [column for column in ("seed_id", "module_slug", "seed_type", "content_json", "approved", "approval_status", "status", "applied") if column in columns]
        order_columns = ["module_slug", "seed_type"]
        if "seed_id" in columns:
            order_columns.append("seed_id")
        rows = connection.execute(
            "SELECT " + ", ".join(selected) + " FROM module_narrative_seeds ORDER BY "
            + ", ".join(column + " ASC" for column in order_columns)
            + " LIMIT ?",
            (MAX_SEED_SCAN_ROWS,),
        ).fetchall()
        values = [dict(row) for row in rows]
        status, seeds, diagnostics = _normalize_seeds(values, require_approval_marker=True)
        if status == WORLD_CONTEXT_SEED_STATUS_UNAVAILABLE and not diagnostics:
            diagnostics = [_diagnostic("no_approved_module_seeds", "No approved module seeds are available.", source_label)]
        if status == WORLD_CONTEXT_SEED_STATUS_UNAVAILABLE:
            for item in diagnostics:
                if item.get("path") == "approved_module_seeds":
                    item["path"] = source_label
        return status, seeds, _load_seed_version(connection), diagnostics
    except sqlite3.Error:
        return WORLD_CONTEXT_SEED_STATUS_INVALID, [], None, [
            _diagnostic("seed_database_read_failed", "Approved seed database could not be read.", source_label, "error")
        ]
    finally:
        connection.close()


def _load_campaign_model_from_db(path: Any, campaign_id: Optional[str]) -> Tuple[str, Optional[Dict[str, Any]], List[Dict[str, str]]]:
    connection, error_kind = _open_sqlite_read_only(path)
    if connection is None:
        return "unavailable", None, [_diagnostic("campaign_model_unavailable", "Campaign world model database is unavailable.", "campaign_world_model")]
    try:
        if not _table_exists(connection, "campaign_world_model"):
            return "unavailable", None, [_diagnostic("campaign_model_table_missing", "Campaign world model table is unavailable.", "campaign_world_model")]
        if campaign_id:
            row = connection.execute(
                "SELECT campaign_id, version, summary_json FROM campaign_world_model WHERE campaign_id = ? ORDER BY version DESC LIMIT 1",
                (campaign_id,),
            ).fetchone()
        else:
            row = connection.execute(
                "SELECT campaign_id, version, summary_json FROM campaign_world_model ORDER BY version DESC, campaign_id ASC LIMIT 1"
            ).fetchone()
        if not row:
            return "unavailable", None, [_diagnostic("campaign_model_unavailable", "No campaign world model is available.", "campaign_world_model")]
        try:
            summary = json.loads(str(row[2]))
        except (TypeError, ValueError):
            return "invalid", None, [_diagnostic("invalid_campaign_model", "Campaign world model JSON is invalid.", "campaign_world_model", "error")]
        if not isinstance(summary, Mapping):
            summary = {"summary": summary}
        normalized = _normalize_campaign_model(summary, row[0], row[1])
        if normalized is None:
            return "invalid", None, [_diagnostic("invalid_campaign_model", "Campaign world model has no allowlisted fields.", "campaign_world_model", "error")]
        return "available", normalized, []
    except sqlite3.Error:
        return "invalid", None, [_diagnostic("campaign_model_read_failed", "Campaign world model could not be read.", "campaign_world_model", "error")]
    finally:
        connection.close()


def _load_pressures_from_db(path: Any) -> Tuple[str, List[Dict[str, Any]], List[Dict[str, str]]]:
    connection, error_kind = _open_sqlite_read_only(path)
    if connection is None:
        return "unavailable", [], [_diagnostic("active_pressures_unavailable", "Active narrative pressure database is unavailable.", "narrative_threads")]
    try:
        if not _table_exists(connection, "narrative_threads"):
            return "unavailable", [], [_diagnostic("active_pressures_table_missing", "Narrative pressure table is unavailable.", "narrative_threads")]
        columns = _table_columns(connection, "narrative_threads")
        selected = [column for column in ("thread_id", "thread_type", "status", "summary", "updated_at") if column in columns]
        if "summary" not in selected:
            return "invalid", [], [_diagnostic("active_pressures_schema_invalid", "Narrative pressure table has no summary field.", "narrative_threads", "error")]
        where = " WHERE status = 'active'" if "status" in columns else ""
        order_columns = []
        if "updated_at" in columns:
            order_columns.append("updated_at DESC")
        if "thread_id" in columns:
            order_columns.append("thread_id ASC")
        order = " ORDER BY " + ", ".join(order_columns) if order_columns else ""
        rows = connection.execute(
            "SELECT " + ", ".join(selected) + " FROM narrative_threads" + where + order + " LIMIT ?",
            (MAX_PRESSURES,),
        ).fetchall()
        values = []
        for row in rows:
            raw = dict(row)
            values.append({
                "thread_id": raw.get("thread_id"),
                "pressure_type": raw.get("thread_type"),
                "status": raw.get("status") or "active",
                "summary": raw.get("summary"),
            })
        status, normalized, diagnostics = _normalize_pressures(values)
        return status, normalized, diagnostics
    except sqlite3.Error:
        return "invalid", [], [_diagnostic("active_pressures_read_failed", "Narrative pressure data could not be read.", "narrative_threads", "error")]
    finally:
        connection.close()


def _component_source_label(source: str) -> str:
    return source if source in {"provided", "runtime_db", "seed_db", "registry_file", "campaign_file"} else "provided"


def _truncate_nested(value: Any, text_limit: int = 120, list_limit: int = 4) -> Any:
    if isinstance(value, str):
        return _ascii_text(value, text_limit)
    if isinstance(value, list):
        return [_truncate_nested(item, text_limit, list_limit) for item in value[:list_limit]]
    if isinstance(value, Mapping):
        return {key: _truncate_nested(value[key], text_limit, list_limit) for key in sorted(value)}
    return value


def _fit_context_pack(pack: Dict[str, Any]) -> Dict[str, Any]:
    """Apply deterministic secondary compaction if normal bounds are exceeded."""
    if len(_canonical_json(pack)) <= MAX_CONTEXT_SERIALIZED_CHARS:
        return pack
    pack["bounds"]["truncated"] = True
    pack["diagnostics"] = _dedupe_diagnostics([
        *pack.get("diagnostics", []),
        _diagnostic("context_truncated", "World context was compacted to its serialized size bound.", "bounds"),
    ])
    registry = pack.get("registry_context")
    if isinstance(registry, Mapping) and isinstance(registry.get("modules"), list):
        registry["modules"] = [
            {
                key: module[key]
                for key in ("module_slug", "module_name", "level_range", "area_count")
                if key in module
            }
            for module in registry["modules"]
            if isinstance(module, Mapping)
        ]
    seeds = pack.get("approved_module_seeds")
    if isinstance(seeds, list):
        compact_seeds = []
        for seed in seeds:
            if not isinstance(seed, Mapping):
                continue
            content = seed.get("content") if isinstance(seed.get("content"), Mapping) else {}
            compact_content = {key: content[key] for key in ("summary", "hook", "objective", "pressure") if key in content}
            compact = {key: seed[key] for key in ("module_slug", "seed_type", "seed_id") if key in seed}
            if compact_content:
                compact["content"] = compact_content
            compact_seeds.append(compact)
        pack["approved_module_seeds"] = compact_seeds
    pack["campaign_model"] = _truncate_nested(pack.get("campaign_model", {}), 180, 4)
    pack["active_pressures"] = _truncate_nested(pack.get("active_pressures", []), 180, 4)
    if len(_canonical_json(pack)) > MAX_CONTEXT_SERIALIZED_CHARS:
        pack["registry_context"] = _truncate_nested(pack.get("registry_context", {}), 100, 3)
        pack["approved_module_seeds"] = _truncate_nested(pack.get("approved_module_seeds", []), 100, 3)
    if len(_canonical_json(pack)) > MAX_CONTEXT_SERIALIZED_CHARS:
        pack["registry_context"] = {}
        pack["approved_module_seeds"] = []
        pack["active_pressures"] = []
        pack["campaign_model"] = _truncate_nested(pack.get("campaign_model", {}), 80, 2)
    return pack


def _finalize_hash(pack: Dict[str, Any]) -> Dict[str, Any]:
    """Attach a hash over the complete context except the hash field itself."""
    hash_input = deepcopy(pack)
    hash_input["provenance"].pop("context_hash", None)
    hash_input.pop("context_hash", None)
    context_hash = _sha256(hash_input)
    pack["provenance"]["context_hash"] = context_hash
    pack["context_hash"] = context_hash
    return pack


def build_world_narrative_context(
    campaign_model: Any = None,
    active_pressures: Any = None,
    registry_context: Any = None,
    approved_module_seeds: Any = None,
    *,
    runtime_db_path: Any = DEFAULT_MEMORY_DB_PATH,
    seed_db_path: Any = DEFAULT_WORLD_NARRATIVE_SEED_DB_PATH,
    registry_path: Any = DEFAULT_REGISTRY_PATH,
    campaign_path: Any = DEFAULT_CAMPAIGN_PATH,
    campaign_id: Optional[str] = None,
    selected_module: Optional[str] = None,
    seed_version: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a bounded read-only world-narrative context pack.

    Direct values are intended for tested retrieval adapters and are treated
    as already selected context. When a value is omitted, the provider reads
    only the allowlisted rows or JSON fields from the supplied local sources.
    No source is initialized, migrated, or written.
    """
    diagnostics: List[Dict[str, str]] = []
    source_kinds = set()

    if campaign_model is None:
        campaign_status, normalized_campaign, campaign_diagnostics = _load_campaign_model_from_db(runtime_db_path, campaign_id)
        diagnostics.extend(campaign_diagnostics)
        if campaign_status == "available":
            source_kinds.add("runtime_db")
    else:
        normalized_campaign = _normalize_campaign_model(campaign_model, campaign_id)
        campaign_status = "available" if normalized_campaign is not None else "invalid"
        if campaign_status == "available":
            source_kinds.add("provided")
        else:
            diagnostics.append(_diagnostic("invalid_campaign_model", "Campaign model has no allowlisted fields.", "campaign_model", "error"))

    if active_pressures is None:
        pressure_status, normalized_pressures, pressure_diagnostics = _load_pressures_from_db(runtime_db_path)
        diagnostics.extend(pressure_diagnostics)
        if pressure_status == "available":
            source_kinds.add("runtime_db")
    else:
        pressure_status, normalized_pressures, pressure_diagnostics = _normalize_pressures(active_pressures)
        diagnostics.extend(pressure_diagnostics)
        if pressure_status == "available":
            source_kinds.add("provided")

    campaign_file_data = None
    if registry_context is None:
        registry_data, registry_diagnostic = _read_json(registry_path, "registry_context")
        if registry_diagnostic is not None:
            diagnostics.append(registry_diagnostic)
        campaign_file_data, campaign_file_diagnostic = _read_json(campaign_path, "campaign_context")
        if campaign_file_diagnostic is not None:
            diagnostics.append(campaign_file_diagnostic)
        normalized_registry = _normalize_registry_context(registry_data, campaign_file_data)
        registry_status = "available" if normalized_registry is not None else "unavailable"
        if registry_data is not None:
            source_kinds.add("registry_file")
        if campaign_file_data is not None:
            source_kinds.add("campaign_file")
    else:
        normalized_registry = _normalize_registry_context(registry_context)
        registry_status = "available" if normalized_registry is not None else "invalid"
        if registry_status == "available":
            source_kinds.add("provided")
        else:
            diagnostics.append(_diagnostic("invalid_registry_context", "Registry context has no allowlisted fields.", "registry_context", "error"))

    if approved_module_seeds is None:
        seed_status, normalized_seeds, seed_version_from_db, seed_diagnostics = _load_seeds_from_db(
            seed_db_path,
            "seed_db",
        )
        diagnostics.extend(seed_diagnostics)
        if seed_status == WORLD_CONTEXT_SEED_STATUS_UNAVAILABLE and runtime_db_path not in (None, ""):
            runtime_seed_status, runtime_seeds, runtime_seed_version, runtime_seed_diagnostics = _load_seeds_from_db(
                runtime_db_path,
                "runtime_db",
            )
            if runtime_seed_status in {WORLD_CONTEXT_SEED_STATUS_AVAILABLE, WORLD_CONTEXT_SEED_STATUS_INVALID}:
                seed_status = runtime_seed_status
                normalized_seeds = runtime_seeds
                seed_version_from_db = runtime_seed_version
                diagnostics.extend(runtime_seed_diagnostics)
        if seed_status == WORLD_CONTEXT_SEED_STATUS_AVAILABLE:
            source_kinds.add("seed_db")
    else:
        seed_status, normalized_seeds, seed_diagnostics = _normalize_seeds(approved_module_seeds)
        diagnostics.extend(seed_diagnostics)
        seed_version_from_db = None
        if seed_status == WORLD_CONTEXT_SEED_STATUS_AVAILABLE:
            source_kinds.add("provided")

    resolved_seed_version = _ascii_text(seed_version or seed_version_from_db or "", 80) or None
    if seed_status == WORLD_CONTEXT_SEED_STATUS_INVALID:
        normalized_seeds = []
    seed_hash = _sha256(normalized_seeds) if seed_status == WORLD_CONTEXT_SEED_STATUS_AVAILABLE and normalized_seeds else None
    component_status = {
        "campaign_model": campaign_status,
        "active_pressures": pressure_status,
        "registry_context": registry_status,
        "approved_module_seeds": seed_status,
    }

    if seed_status == WORLD_CONTEXT_SEED_STATUS_INVALID:
        status = WORLD_CONTEXT_STATUS_FALLBACK
        fallback_status = WORLD_CONTEXT_FALLBACK_SEED_INVALID
    elif seed_status != WORLD_CONTEXT_SEED_STATUS_AVAILABLE:
        status = WORLD_CONTEXT_STATUS_FALLBACK
        fallback_status = WORLD_CONTEXT_FALLBACK_SEED_UNAVAILABLE
    elif any(value != "available" for value in (campaign_status, pressure_status, registry_status)):
        status = WORLD_CONTEXT_STATUS_FALLBACK
        fallback_status = WORLD_CONTEXT_FALLBACK_CONTEXT_INCOMPLETE
    else:
        status = WORLD_CONTEXT_STATUS_AVAILABLE
        fallback_status = WORLD_CONTEXT_FALLBACK_NONE

    pack: Dict[str, Any] = {
        "version": WORLD_CONTEXT_CONTRACT_VERSION,
        "context_version": WORLD_CONTEXT_CONTRACT_VERSION,
        "status": status,
        "context_status": status,
        "fallback_status": fallback_status,
        "read_only": True,
        "provider_free": True,
        "campaign_model": normalized_campaign or {},
        "active_pressures": normalized_pressures,
        "registry_context": normalized_registry or {},
        "approved_module_seeds": normalized_seeds,
        "component_status": component_status,
        "diagnostics": _dedupe_diagnostics(diagnostics),
        "bounds": {
            "max_serialized_chars": MAX_CONTEXT_SERIALIZED_CHARS,
            "max_pressures": MAX_PRESSURES,
            "max_registry_modules": MAX_REGISTRY_MODULES,
            "max_approved_module_seeds": MAX_SEEDS,
            "truncated": False,
        },
        "provenance": {
            "contract_version": WORLD_CONTEXT_CONTRACT_VERSION,
            "world_seed_status": seed_status,
            "world_seed_version": resolved_seed_version,
            "world_seed_hash": seed_hash,
            "selected_module": _safe_identifier(selected_module, 140) or None,
            "source_kinds": sorted(_component_source_label(item) for item in source_kinds),
            "context_hash": "0" * 64,
        },
        "world_seed_status": seed_status,
        "world_seed_version": resolved_seed_version,
        "world_seed_hash": seed_hash,
        "context_hash": "0" * 64,
    }
    pack = _fit_context_pack(pack)
    pack["world_seed_hash"] = _sha256(pack["approved_module_seeds"]) if pack["approved_module_seeds"] else None
    pack["provenance"]["world_seed_hash"] = pack["world_seed_hash"]
    return _finalize_hash(pack)


def build_world_narrative_context_pack(*args: Any, **kwargs: Any) -> Dict[str, Any]:
    """Compatibility alias for callers that name the result a context pack."""
    return build_world_narrative_context(*args, **kwargs)


def get_world_narrative_context(*args: Any, **kwargs: Any) -> Dict[str, Any]:
    """Read-only retrieval alias for the adaptation context boundary."""
    return build_world_narrative_context(*args, **kwargs)


class WorldNarrativeContextProvider:
    """Reusable read-only provider with project-local source defaults."""

    def __init__(
        self,
        *,
        runtime_db_path: Any = DEFAULT_MEMORY_DB_PATH,
        seed_db_path: Any = DEFAULT_WORLD_NARRATIVE_SEED_DB_PATH,
        registry_path: Any = DEFAULT_REGISTRY_PATH,
        campaign_path: Any = DEFAULT_CAMPAIGN_PATH,
    ) -> None:
        self.runtime_db_path = runtime_db_path
        self.seed_db_path = seed_db_path
        self.registry_path = registry_path
        self.campaign_path = campaign_path

    def build(self, **kwargs: Any) -> Dict[str, Any]:
        """Build one context pack without retaining or mutating source state."""
        options = dict(kwargs)
        options.setdefault("runtime_db_path", self.runtime_db_path)
        options.setdefault("seed_db_path", self.seed_db_path)
        options.setdefault("registry_path", self.registry_path)
        options.setdefault("campaign_path", self.campaign_path)
        return build_world_narrative_context(**options)


__all__ = [
    "DEFAULT_CAMPAIGN_PATH",
    "DEFAULT_MEMORY_DB_PATH",
    "DEFAULT_REGISTRY_PATH",
    "DEFAULT_WORLD_NARRATIVE_SEED_DB_PATH",
    "MAX_CONTEXT_CHARS",
    "MAX_CONTEXT_SERIALIZED_CHARS",
    "MAX_DIAGNOSTICS",
    "MAX_PRESSURES",
    "MAX_REGISTRY_MODULES",
    "MAX_SEEDS",
    "WORLD_CONTEXT_PROVENANCE_VERSION",
    "WORLD_CONTEXT_CONTRACT_VERSION",
    "WORLD_CONTEXT_FALLBACK_CONTEXT_INCOMPLETE",
    "WORLD_CONTEXT_FALLBACK_NONE",
    "WORLD_CONTEXT_FALLBACK_SEED_INVALID",
    "WORLD_CONTEXT_FALLBACK_SEED_UNAVAILABLE",
    "WORLD_CONTEXT_SEED_STATUS_AVAILABLE",
    "WORLD_CONTEXT_SEED_STATUS_INVALID",
    "WORLD_CONTEXT_SEED_STATUS_UNAVAILABLE",
    "WORLD_CONTEXT_STATUS_AVAILABLE",
    "WORLD_CONTEXT_STATUS_FALLBACK",
    "WorldNarrativeContextProvider",
    "build_world_context_provenance",
    "build_world_narrative_context",
    "build_world_narrative_context_pack",
    "extract_world_context_provenance",
    "get_world_narrative_context",
    "normalize_world_context_provenance",
]
