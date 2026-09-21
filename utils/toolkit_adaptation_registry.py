# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Utility - LLM Adaptation Registry Publication
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

Python-owned, provider-free registry integration for the explicit LLM
adaptation publication lane. The helper reads a staged module, builds the
module and area registry entries in memory, writes them atomically, verifies
the exact expected metadata from the persisted registry, and then delegates
campaign availability synchronization to the separate provider-free helper.

The helper captures pre-registration state before the first write. If registry
verification or campaign synchronization fails after that write, both runtime
state files are restored through the adaptation publication transaction
rollback helper.
"""

from __future__ import annotations

import copy
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from utils.file_operations import safe_read_json, safe_write_json
from utils.toolkit_adaptation_publication_transaction import (
    capture_adaptation_publication_snapshot,
    rollback_adaptation_publication,
)


ADAPTATION_REGISTRY_CONTRACT_VERSION = "toolkit_adaptation_registry.v1"
DEFAULT_REGISTRY_RELATIVE_PATH = "modules/world_registry.json"
_MODULE_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,119}$")
_MAX_METADATA_TEXT = 4000
_MAX_THEME_COUNT = 64
_MAX_LIST_ITEMS = 64


class AdaptationRegistryError(ValueError):
    """Raised when staged registry input cannot be represented safely."""


def _utc_now_iso() -> str:
    """Return a second-precision UTC timestamp."""
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _bounded_text(value: Any, limit: int = _MAX_METADATA_TEXT) -> str:
    """Return bounded text suitable for registry metadata."""
    if value is None:
        return ""
    if not isinstance(value, str):
        raise AdaptationRegistryError("registry metadata text is malformed")
    text = value.strip()
    if len(text) > limit:
        return text[:limit]
    return text


def _bounded_string_list(value: Any, field_name: str) -> List[str]:
    """Normalize a bounded list of strings without inventing values."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise AdaptationRegistryError(f"{field_name} must be a list")
    if len(value) > _MAX_LIST_ITEMS:
        raise AdaptationRegistryError(f"{field_name} contains too many entries")
    result: List[str] = []
    for item in value:
        if not isinstance(item, str):
            raise AdaptationRegistryError(f"{field_name} contains non-text metadata")
        result.append(_bounded_text(item, 512))
    return result


def _resolve_registry_path(registry_path: Optional[Path]) -> Path:
    """Resolve a registry path without changing the runtime-only location."""
    candidate = (
        Path(registry_path)
        if registry_path is not None
        else Path(DEFAULT_REGISTRY_RELATIVE_PATH)
    )
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    return candidate.resolve()


def _validate_module_slug(module_slug: Any) -> str:
    """Validate the registry key supplied by the Python build path."""
    if not isinstance(module_slug, str) or not _MODULE_SLUG_RE.fullmatch(module_slug):
        raise AdaptationRegistryError("module_slug is not path-safe")
    return module_slug


def _load_required_object(path: Path, label: str) -> Dict[str, Any]:
    """Load one required JSON object and distinguish missing from malformed."""
    if not path.is_file():
        raise AdaptationRegistryError(f"{label}_missing")
    payload = safe_read_json(str(path))
    if not isinstance(payload, Mapping):
        raise AdaptationRegistryError(f"{label}_malformed")
    return dict(payload)


def _active_area_paths(module_dir: Path) -> List[Path]:
    """Return active area files using the existing module-file conventions."""
    areas_dir = module_dir / "areas"
    if not areas_dir.is_dir() or areas_dir.is_symlink():
        raise AdaptationRegistryError("adaptation_area_directory_missing")

    excluded_prefixes = ("module_", "party_", "campaign_", "map_", "plot_")
    paths = []
    for path in sorted(areas_dir.glob("*.json")):
        if path.name.endswith("_BU.json"):
            continue
        if path.name.startswith(excluded_prefixes):
            continue
        if path.is_file() and not path.is_symlink():
            paths.append(path)
    if not paths:
        raise AdaptationRegistryError("adaptation_area_entries_missing")
    return paths


def _area_entry(area: Mapping[str, Any], module_slug: str, path: Path) -> Tuple[str, Dict[str, Any]]:
    """Build one registry area entry from one staged area file."""
    area_id = area.get("areaId")
    area_name = area.get("areaName")
    if not isinstance(area_id, str) or not area_id.strip():
        raise AdaptationRegistryError(f"area_id_missing:{path.name}")
    if not isinstance(area_name, str) or not area_name.strip():
        raise AdaptationRegistryError(f"area_name_missing:{path.name}")

    locations = area.get("locations", [])
    if not isinstance(locations, list):
        raise AdaptationRegistryError(f"area_locations_malformed:{area_id}")
    if any(not isinstance(location, Mapping) for location in locations):
        raise AdaptationRegistryError(f"area_locations_malformed:{area_id}")

    recommended_level = area.get("recommendedLevel", 1)
    if isinstance(recommended_level, bool) or not isinstance(recommended_level, int):
        raise AdaptationRegistryError(f"area_level_malformed:{area_id}")

    area_entry = {
        "areaName": _bounded_text(area_name, 512),
        "areaDescription": _bounded_text(area.get("areaDescription", "")),
        "areaType": _bounded_text(area.get("areaType", ""), 256),
        "dangerLevel": _bounded_text(area.get("dangerLevel", "unknown"), 128),
        "recommendedLevel": recommended_level,
        "climate": _bounded_text(area.get("climate", ""), 256),
        "terrain": _bounded_text(area.get("terrain", ""), 256),
        "areaConnectivity": _bounded_string_list(
            area.get("areaConnectivity", []), "areaConnectivity"
        ),
        "areaConnectivityId": _bounded_string_list(
            area.get("areaConnectivityId", []), "areaConnectivityId"
        ),
        "locationCount": len(locations),
        "module": module_slug,
    }
    return area_id.strip(), area_entry


def _travel_metadata(module_context: Mapping[str, Any]) -> Dict[str, str]:
    """Copy only bounded, registry-safe travel metadata from staged context."""
    raw_travel = module_context.get("travelNarration", {})
    if raw_travel in (None, ""):
        return {}
    if not isinstance(raw_travel, Mapping):
        raise AdaptationRegistryError("module_travel_narration_malformed")
    result: Dict[str, str] = {}
    for key in ("travelNarration", "dmGuidance", "generatedDate"):
        value = raw_travel.get(key)
        if value is not None:
            result[key] = _bounded_text(value)
    return result


def _build_entries(
    module_slug: str,
    module_dir: Path,
    added_date: str,
) -> Dict[str, Any]:
    """Build expected module and area entries without touching the registry."""
    area_entries: Dict[str, Dict[str, Any]] = {}
    area_levels: List[int] = []
    area_files = _active_area_paths(module_dir)
    for area_path in area_files:
        area = _load_required_object(area_path, f"area_file:{area_path.name}")
        area_id, entry = _area_entry(area, module_slug, area_path)
        if area_id in area_entries:
            raise AdaptationRegistryError(f"duplicate_area_id:{area_id}")
        area_entries[area_id] = entry
        area_levels.append(int(entry["recommendedLevel"]))

    plot_path = module_dir / "module_plot.json"
    plot: Dict[str, Any] = {}
    if plot_path.exists():
        plot = _load_required_object(plot_path, "module_plot")
    plot_points = plot.get("plotPoints", [])
    if plot_points is None:
        plot_points = []
    if not isinstance(plot_points, list):
        raise AdaptationRegistryError("module_plot_points_malformed")
    themes: List[str] = []
    for point in plot_points[:_MAX_THEME_COUNT]:
        if not isinstance(point, Mapping):
            raise AdaptationRegistryError("module_plot_point_malformed")
        description = point.get("description", "")
        if description is None:
            description = ""
        if not isinstance(description, str):
            raise AdaptationRegistryError("module_plot_description_malformed")
        if description.strip():
            themes.append(_bounded_text(description))

    objective = plot.get("mainObjective", "")
    if objective is None:
        objective = ""
    if not isinstance(objective, str):
        raise AdaptationRegistryError("module_plot_objective_malformed")

    context_path = module_dir / "module_context.json"
    context: Dict[str, Any] = {}
    if context_path.exists():
        context = _load_required_object(context_path, "module_context")
        context_module_id = context.get("module_id", context.get("moduleId"))
        if context_module_id is not None:
            if not isinstance(context_module_id, str) or context_module_id != module_slug:
                raise AdaptationRegistryError("module_context_identity_mismatch")
        context_areas = context.get("areas")
        if isinstance(context_areas, Mapping):
            context_area_ids = {
                str(area_id).strip() for area_id in context_areas if str(area_id).strip()
            }
            missing_area_ids = sorted(context_area_ids - set(area_entries))
            if missing_area_ids:
                raise AdaptationRegistryError(
                    "module_context_area_entries_missing:" + ",".join(missing_area_ids)
                )

    module_entry = {
        "moduleName": module_slug,
        "addedDate": added_date,
        "themes": themes,
        "plotObjective": _bounded_text(objective),
        "levelRange": {
            "min": min(area_levels),
            "max": max(area_levels),
        },
        "areaCount": len(area_entries),
        "travelNarration": _travel_metadata(context),
    }

    return {
        "contract_version": ADAPTATION_REGISTRY_CONTRACT_VERSION,
        "module_slug": module_slug,
        "module_entry": module_entry,
        "area_entries": area_entries,
        "area_ids": sorted(area_entries),
        "area_files": [path.name for path in area_files],
        "registry_last_updated": added_date,
    }


def build_adaptation_registry_entries(
    module_slug: str,
    module_dir: Path,
    *,
    added_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Return bounded expected registry entries for a staged adaptation."""
    try:
        slug = _validate_module_slug(module_slug)
        candidate_dir = Path(module_dir).resolve()
        if not candidate_dir.is_dir() or candidate_dir.is_symlink():
            raise AdaptationRegistryError("adaptation_module_directory_missing")
        timestamp = str(added_date or _utc_now_iso()).strip()
        if not timestamp:
            raise AdaptationRegistryError("registry_added_date_missing")
        entries = _build_entries(slug, candidate_dir, timestamp)
        return {
            "status": "success",
            "module_slug": slug,
            "entries": entries,
        }
    except Exception as exc:
        return {
            "status": "blocked",
            "reason": str(exc) or "adaptation_registry_entries_invalid",
            "module_slug": str(module_slug or ""),
        }


def _load_registry_object(registry_file: Path) -> Dict[str, Any]:
    """Load and validate the registry envelope required by this transaction."""
    if not registry_file.is_file():
        raise AdaptationRegistryError("registry_missing")
    registry = safe_read_json(str(registry_file))
    if not isinstance(registry, Mapping):
        raise AdaptationRegistryError("registry_malformed")
    if not isinstance(registry.get("modules"), Mapping):
        raise AdaptationRegistryError("registry_modules_malformed")
    if not isinstance(registry.get("areas"), Mapping):
        raise AdaptationRegistryError("registry_areas_malformed")
    return dict(registry)


def _values_match(expected: Any, actual: Any) -> bool:
    """Compare JSON values strictly, including scalar types."""
    if type(expected) is not type(actual):
        return False
    if isinstance(expected, Mapping):
        return all(
            key in actual and _values_match(value, actual[key])
            for key, value in expected.items()
        )
    if isinstance(expected, list):
        return len(expected) == len(actual) and all(
            _values_match(expected_value, actual_value)
            for expected_value, actual_value in zip(expected, actual)
        )
    return expected == actual


def _display_value(value: Any) -> str:
    """Return bounded diagnostic text without copying unbounded registry data."""
    text = repr(value).encode("ascii", "replace").decode("ascii")
    return text[:240]


def verify_adaptation_registry_entries(
    registry_path: Path,
    expected: Mapping[str, Any],
) -> Dict[str, Any]:
    """Verify exact module and area identity/content metadata after writing."""
    try:
        if not isinstance(expected, Mapping):
            raise AdaptationRegistryError("registry_verification_expected_entries_missing")
        module_slug = _validate_module_slug(expected.get("module_slug"))
        module_expected = expected.get("module_entry")
        area_expected = expected.get("area_entries")
        if not isinstance(module_expected, Mapping):
            raise AdaptationRegistryError("registry_verification_module_entry_missing")
        if not isinstance(area_expected, Mapping) or not area_expected:
            raise AdaptationRegistryError("registry_verification_area_entries_missing")

        registry_file = _resolve_registry_path(registry_path)
        registry = _load_registry_object(registry_file)
        modules = registry["modules"]
        areas = registry["areas"]
        mismatches: List[Dict[str, str]] = []

        actual_module = modules.get(module_slug)
        module_verified = isinstance(actual_module, Mapping)
        if not module_verified:
            mismatches.append({"field": "module", "reason": "missing"})
        else:
            for field, expected_value in module_expected.items():
                actual_value = actual_module.get(field)
                if not _values_match(expected_value, actual_value):
                    mismatches.append(
                        {
                            "field": f"module.{field}",
                            "expected": _display_value(expected_value),
                            "actual": _display_value(actual_value),
                        }
                    )
                    module_verified = False

        expected_area_ids = sorted(str(area_id) for area_id in area_expected)
        actual_area_ids = sorted(
            str(area_id)
            for area_id, area_value in areas.items()
            if isinstance(area_value, Mapping)
            and area_value.get("module") == module_slug
        )
        areas_verified = expected_area_ids == actual_area_ids
        if not areas_verified:
            mismatches.append(
                {
                    "field": "areas.identity",
                    "expected": _display_value(expected_area_ids),
                    "actual": _display_value(actual_area_ids),
                }
            )

        expected_last_updated = expected.get("registry_last_updated")
        if expected_last_updated is not None and not _values_match(
            expected_last_updated, registry.get("lastUpdated")
        ):
            mismatches.append(
                {
                    "field": "registry.lastUpdated",
                    "expected": _display_value(expected_last_updated),
                    "actual": _display_value(registry.get("lastUpdated")),
                }
            )

        for area_id, expected_area in area_expected.items():
            actual_area = areas.get(area_id)
            area_ok = isinstance(actual_area, Mapping)
            if not area_ok:
                mismatches.append(
                    {"field": f"areas.{area_id}", "reason": "missing_or_malformed"}
                )
                areas_verified = False
                continue
            for field, expected_value in expected_area.items():
                actual_value = actual_area.get(field)
                if not _values_match(expected_value, actual_value):
                    mismatches.append(
                        {
                            "field": f"areas.{area_id}.{field}",
                            "expected": _display_value(expected_value),
                            "actual": _display_value(actual_value),
                        }
                    )
                    areas_verified = False

        verified = bool(module_verified and areas_verified and not mismatches)
        return {
            "status": "success" if verified else "blocked",
            "verified": verified,
            "module_verified": bool(module_verified),
            "areas_verified": bool(areas_verified),
            "module_slug": module_slug,
            "verified_area_ids": expected_area_ids if verified else [],
            "mismatches": mismatches[:32],
        }
    except Exception as exc:
        return {
            "status": "blocked",
            "verified": False,
            "module_verified": False,
            "areas_verified": False,
            "reason": str(exc) or "registry_verification_failed",
            "mismatches": [],
        }


def _base_result(module_slug: str, registry_file: Path) -> Dict[str, Any]:
    """Build the bounded transaction result envelope."""
    return {
        "contract_version": ADAPTATION_REGISTRY_CONTRACT_VERSION,
        "status": "blocked",
        "module_slug": module_slug,
        "registry_path": str(registry_file),
        "integration_attempted": False,
        "verification_required": True,
        "registry_is_final_stateful_publication": True,
        "python_authoritative": True,
        "campaign_sync": {
            "status": "not_attempted",
            "reason": "finisher_campaign_sync_boundary",
        },
        "rollback": {
            "status": "not_attempted",
            "reason": "pre_registration_boundary",
        },
    }


def _apply_adaptation_rollback(
    result: Dict[str, Any],
    snapshot: Optional[Mapping[str, Any]],
    failure_reason: str,
) -> Dict[str, Any]:
    """Restore state after a registry or campaign publication failure."""
    if not isinstance(snapshot, Mapping):
        result["rollback"] = {
            "status": "blocked",
            "attempted": False,
            "verified": False,
            "reason": "rollback_metadata_missing",
        }
        result["publication_status"] = "blocked"
        result["reason"] = f"{failure_reason};rollback_metadata_missing"
        return result

    rollback_result = rollback_adaptation_publication(
        snapshot,
        failure_reason=failure_reason,
    )
    result["rollback"] = rollback_result
    result["publication_status"] = "blocked"
    if rollback_result.get("status") != "success":
        result["reason"] = f"{failure_reason};rollback_incomplete"
    else:
        result["reason"] = failure_reason
    return result


def integrate_adaptation_registry(
    module_slug: str,
    module_dir: Path,
    *,
    registry_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Atomically add a staged module and all required areas, then verify."""
    registry_file = _resolve_registry_path(registry_path)
    result = _base_result(str(module_slug or ""), registry_file)

    entries_result = build_adaptation_registry_entries(module_slug, module_dir)
    if entries_result.get("status") != "success":
        result["reason"] = entries_result.get(
            "reason", "adaptation_registry_entries_invalid"
        )
        result["entries"] = {"status": "blocked"}
        return result

    expected = entries_result["entries"]
    result["expected_area_ids"] = list(expected.get("area_ids", []))
    try:
        registry = _load_registry_object(registry_file)
        modules = registry["modules"]
        areas = registry["areas"]
        if expected["module_slug"] in modules:
            result["reason"] = "registry_module_conflict"
            return result
        area_conflicts = [area_id for area_id in expected["area_ids"] if area_id in areas]
        if area_conflicts:
            result["reason"] = "registry_area_conflict"
            result["area_conflicts"] = area_conflicts
            return result

        snapshot_result = capture_adaptation_publication_snapshot(
            expected["module_slug"],
            registry_path=registry_file,
            campaign_path=registry_file.parent / "campaign.json",
            area_ids=list(expected["area_ids"]),
        )
        if snapshot_result.get("status") != "success":
            result["reason"] = snapshot_result.get(
                "reason", "adaptation_publication_snapshot_failed"
            )
            result["rollback"] = {
                "status": "not_attempted",
                "attempted": False,
                "verified": False,
                "reason": "pre_registration_snapshot_failed",
            }
            return result
        rollback_snapshot = snapshot_result.get("snapshot")
        if not isinstance(rollback_snapshot, Mapping):
            result["reason"] = "adaptation_publication_snapshot_missing"
            result["rollback"] = {
                "status": "not_attempted",
                "attempted": False,
                "verified": False,
                "reason": "pre_registration_snapshot_missing",
            }
            return result
        result["rollback"] = dict(snapshot_result.get("metadata") or {})
        result["rollback"]["status"] = "pending"
        result["rollback"]["attempted"] = False
        result["rollback"]["verified"] = False
        result["_rollback_snapshot"] = rollback_snapshot

        candidate = copy.deepcopy(registry)
        candidate["modules"][expected["module_slug"]] = copy.deepcopy(
            expected["module_entry"]
        )
        for area_id, area_entry in expected["area_entries"].items():
            candidate["areas"][area_id] = copy.deepcopy(area_entry)
        candidate["lastUpdated"] = expected["module_entry"]["addedDate"]

        result["integration_attempted"] = True
        if not safe_write_json(str(registry_file), candidate):
            result["reason"] = "registry_write_failed"
            result["write"] = {"status": "failed", "atomic": True}
            return _apply_adaptation_rollback(
                result,
                rollback_snapshot,
                "registry_write_failed",
            )
        result["write"] = {"status": "success", "atomic": True}
    except Exception as exc:
        result["reason"] = str(exc) or "registry_integration_failed"
        result["write"] = {"status": "failed", "atomic": True}
        return _apply_adaptation_rollback(
            result,
            result.get("_rollback_snapshot"),
            result["reason"],
        )

    try:
        verification = verify_adaptation_registry_entries(registry_file, expected)
    except Exception as exc:
        verification = {
            "status": "blocked",
            "verified": False,
            "reason": f"registry_verification_exception:{exc}",
        }
    result["verification"] = verification
    if not isinstance(verification, Mapping):
        result["reason"] = "registry_post_write_verification_missing"
        return _apply_adaptation_rollback(
            result,
            result.get("_rollback_snapshot"),
            "registry_post_write_verification_missing",
        )
    if (
        verification.get("status") != "success"
        or verification.get("verified") is not True
        or verification.get("module_verified") is not True
        or verification.get("areas_verified") is not True
    ):
        result["reason"] = "registry_post_write_verification_failed"
        return _apply_adaptation_rollback(
            result,
            result.get("_rollback_snapshot"),
            "registry_post_write_verification_failed",
        )

    try:
        from utils.toolkit_adaptation_campaign import (
            synchronize_adaptation_campaign_module,
        )

        campaign_sync = synchronize_adaptation_campaign_module(
            module_slug,
            campaign_path=registry_file.parent / "campaign.json",
            registry_path=registry_file,
        )
    except Exception as exc:
        campaign_sync = {
            "status": "blocked",
            "reason": f"campaign_sync_exception:{exc}",
            "module_slug": module_slug,
            "campaign_visibility_verified": False,
        }
    result["campaign_sync"] = campaign_sync
    if not isinstance(campaign_sync, Mapping):
        result["campaign_sync"] = {
            "status": "blocked",
            "reason": "campaign_sync_result_missing",
            "module_slug": module_slug,
            "campaign_visibility_verified": False,
        }
        return _apply_adaptation_rollback(
            result,
            result.get("_rollback_snapshot"),
            "adaptation_campaign_sync_result_missing",
        )
    campaign_status = str(campaign_sync.get("status") or "blocked").strip().lower()
    if campaign_status not in {"success", "deferred"}:
        result["reason"] = "adaptation_campaign_sync_failed"
        return _apply_adaptation_rollback(
            result,
            result.get("_rollback_snapshot"),
            "adaptation_campaign_sync_failed",
        )

    result.update(
        {
            "status": "success",
            "reason": "adaptation_registry_integrated_and_verified",
            "verified": True,
        }
    )
    result["rollback"].update(
        {
            "status": "not_needed",
            "attempted": False,
            "verified": True,
            "reason": "publication_transaction_pending_final_report",
        }
    )
    return result


__all__ = [
    "ADAPTATION_REGISTRY_CONTRACT_VERSION",
    "AdaptationRegistryError",
    "build_adaptation_registry_entries",
    "verify_adaptation_registry_entries",
    "integrate_adaptation_registry",
    "capture_adaptation_publication_snapshot",
    "rollback_adaptation_publication",
]
