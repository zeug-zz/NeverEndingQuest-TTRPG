# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Utility - Toolkit Blueprint Enrichment
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

Bounded LLM enrichment patch pipeline for the accurate-ingest pipeline.
Validates, applies, and orchestrates prose enrichment of seeded module
fields while forbidding structural mutations.

This software is free for non-commercial and educational use.
Commercial competing use is prohibited for 2 years from release.
See LICENSE file for full terms.
"""

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from utils.file_operations import safe_write_json

ENRICHMENT_REPORT_VERSION = "blueprint_enrichment_report.v1"

# Enrichment status constants
ENRICHMENT_STATUS_SKIPPED = "skipped"
ENRICHMENT_STATUS_DEGRADED = "degraded"
ENRICHMENT_STATUS_COMPLETE = "complete"

# Patch operation schema
REQUIRED_PATCH_FIELDS = [
    "op", "blueprint_id", "target_file", "json_path", "field", "value",
]

ALLOWED_OPS = {"replace"}

# Target file patterns allowed for enrichment
ALLOWED_TARGET_FILES = {
    "module_context.json",
    "module_context_BU.json",
    "module_plot.json",
    "module_plot_BU.json",
}

# Patterns that, if present in a json_path, indicate a forbidden structural change
FORBIDDEN_PATH_PATTERNS = [
    r'\bname\b',
    r'\b(?:location|area|beat|chain|clue|atom)_*id\b',
    r'\bconnectivity\b',
    r'\b_area_?[Cc]onnectivity\b',
    r'\bcoordinates\b',
    r'\blocationId\b',
    r'\bareaId\b',
    r'\bdependencies\b',
    r'\bnextPoints\b',
    r'\bprerequisites\b',
    r'\bclue_dependencies\b',
    r'\brules\b',
    r'\bsolution\b',
    r'\bfailure_consequences\b',
    r'\bunlocks\b',
    r'\bbeat_type\b',
    r'\btype\b(?!.*(?:description|area|terrain))',
]

# Field names that are always forbidden
FORBIDDEN_FIELDS = {
    "name", "id", "locationId", "areaId", "beat_id", "chain_id",
    "clue_id", "atom_id", "type", "status", "coordinates",
    "connectivity", "areaConnectivity", "areaConnectivityId",
    "dependencies", "nextPoints", "prerequisites",
    "clue_dependencies", "rules", "solution",
    "failure_consequences", "unlocks",
}

# Allowed field names for enrichment
ALLOWED_FIELDS = {
    "description", "role", "faction", "mainObjective",
    "plotImpact", "areaDescription", "dmInstructions",
    "adventureSummary", "plotHooks",
}


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

def _resolve_json_path(data: Any, json_path: str) -> Tuple[bool, Any, str]:
    """Resolve a dot-separated json_path with bracket-index support.

    Supports paths like:
      npcs.high_priest_malak.description
      plotPoints[0].description
      locations[2].plotHooks[1]

    Returns (found, value_or_parent, key_or_error).
    If found is True, value_or_parent is the value and key_or_error is the last key.
    If found is False, value_or_parent is the parent dict and key_or_error is the missing key.
    """
    parts = re.findall(r'[^.\[\]]+|\[\d+\]', json_path)
    current = data
    for i, part in enumerate(parts):
        is_last = i == len(parts) - 1
        if part.startswith('[') and part.endswith(']'):
            idx = int(part[1:-1])
            if not isinstance(current, (list, tuple)):
                return False, current, part
            if idx >= len(current):
                return False, current, part
            if is_last:
                return True, current, idx
            current = current[idx]
        else:
            if not isinstance(current, dict):
                return False, current, part
            if part not in current:
                return False, current, part
            if is_last:
                return True, current, part
            current = current[part]
    return True, current, parts[-1] if parts else ""


def _set_json_path(data: Any, json_path: str, value: Any) -> bool:
    """Set a value at a dot-separated json_path.

    Returns True on success, False on failure.
    """
    found, parent_or_val, key = _resolve_json_path(data, json_path)
    if not found:
        parts = re.findall(r'[^.\[\]]+|\[\d+\]', json_path)
        if len(parts) <= 1:
            return False
        parent_parts = parts[:-1]
        last_key = parts[-1]
        current = data
        for i, part in enumerate(parent_parts):
            is_last = i == len(parent_parts) - 1
            if part.startswith('[') and part.endswith(']'):
                idx = int(part[1:-1])
                if not isinstance(current, (list, tuple)):
                    return False
                if idx >= len(current):
                    return False
                if is_last:
                    if last_key.startswith('[') and last_key.endswith(']'):
                        lidx = int(last_key[1:-1])
                        if lidx >= len(current[idx]):
                            return False
                        current[idx][lidx] = value
                        return True
                    elif isinstance(current[idx], dict):
                        current[idx][last_key] = value
                        return True
                    else:
                        return False
                current = current[idx]
            else:
                if not isinstance(current, dict):
                    return False
                if part not in current:
                    return False
                if is_last:
                    target = current[part]
                    if isinstance(target, dict):
                        target[last_key] = value
                    elif isinstance(target, list) and last_key.startswith('['):
                        lidx = int(last_key[1:-1])
                        if lidx >= len(target):
                            return False
                        target[lidx] = value
                    else:
                        current[part] = value
                    return True
                current = current[part]
        return False
    if isinstance(parent_or_val, dict):
        parent_or_val[key] = value
        return True
    elif isinstance(parent_or_val, list) and isinstance(key, int):
        parent_or_val[key] = value
        return True
    return False


# ---------------------------------------------------------------------------
# Enrichment allowlist helpers
# ---------------------------------------------------------------------------

def _get_enrichment_allowlist(blueprint: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Get enrichment allowlist from blueprint or return built-in defaults."""
    if blueprint:
        allowlist = blueprint.get("enrichment_allowlist")
        if allowlist:
            return allowlist
    from utils.toolkit_builder_blueprint import _ENRICHMENT_ALLOWLIST_DEFAULT
    return dict(_ENRICHMENT_ALLOWLIST_DEFAULT)


def _is_target_file_allowed(target_file: str) -> bool:
    """Check if a target file is allowed for enrichment."""
    fname = os.path.basename(target_file)
    if fname in ALLOWED_TARGET_FILES:
        return True
    if re.match(r'^area_.*_BU\.json$', fname):
        return True
    return False


def _is_field_allowed(field_name: str) -> bool:
    """Check if a field name is allowed for enrichment."""
    return field_name in ALLOWED_FIELDS


def _has_forbidden_path_pattern(json_path: str) -> bool:
    """Check if a json_path contains forbidden structural patterns."""
    parts = re.findall(r'[^.\[\]]+', json_path)
    for pattern in FORBIDDEN_PATH_PATTERNS:
        for part in parts:
            if re.match(pattern, part, re.IGNORECASE):
                return True
    return False


# ---------------------------------------------------------------------------
# Patch validation
# ---------------------------------------------------------------------------

def validate_enrichment_patch(
    patch: Dict[str, Any],
    blueprint: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Validate a single enrichment patch operation.

    Returns dict with:
      valid: bool
      reason: str (empty if valid)
      patch: the original patch (unchanged)
    """
    # Check all required fields present
    for field in REQUIRED_PATCH_FIELDS:
        if field not in patch:
            return {
                "valid": False,
                "reason": f"Missing required field '{field}'",
                "patch": patch,
            }

    # Check op is allowed
    op = patch.get("op", "")
    if op not in ALLOWED_OPS:
        return {
            "valid": False,
            "reason": f"Unsupported operation '{op}'. Allowed: {', '.join(sorted(ALLOWED_OPS))}",
            "patch": patch,
        }

    # Check blueprint_id is meaningful
    bp_id = patch.get("blueprint_id", "")
    if not bp_id or not bp_id.strip():
        return {
            "valid": False,
            "reason": "blueprint_id is empty",
            "patch": patch,
        }

    # Check target file is allowed
    target_file = patch.get("target_file", "")
    if not _is_target_file_allowed(target_file):
        return {
            "valid": False,
            "reason": f"Target file '{target_file}' is not an allowed enrichment target",
            "patch": patch,
        }

    # Check field is allowed
    field_name = patch.get("field", "")
    if not _is_field_allowed(field_name):
        return {
            "valid": False,
            "reason": f"Field '{field_name}' is not an allowed enrichment field",
            "patch": patch,
        }

    # Check json_path is not empty
    json_path = patch.get("json_path", "")
    if not json_path or not json_path.strip():
        return {
            "valid": False,
            "reason": "json_path is empty",
            "patch": patch,
        }

    # Check for path traversal
    if ".." in json_path or json_path.startswith("/"):
        return {
            "valid": False,
            "reason": f"Path traversal detected in json_path: '{json_path}'",
            "patch": patch,
        }

    # Check for forbidden structural patterns in path
    if _has_forbidden_path_pattern(json_path):
        return {
            "valid": False,
            "reason": f"json_path contains forbidden structural patterns: '{json_path}'",
            "patch": patch,
        }

    # Check value is a string (text fields only)
    value = patch.get("value")
    if not isinstance(value, str):
        return {
            "valid": False,
            "reason": f"Value must be a string, got {type(value).__name__}",
            "patch": patch,
        }

    # Check value length against blueprint allowlist if available
    allowlist = _get_enrichment_allowlist(blueprint)
    if bp_id in allowlist:
        max_chars = allowlist[bp_id].get("max_chars", 0)
        if max_chars and len(value) > max_chars:
            return {
                "valid": False,
                "reason": f"Value exceeds max_chars ({max_chars}) for blueprint_id '{bp_id}'",
                "patch": patch,
            }

    # All checks passed
    return {
        "valid": True,
        "reason": "",
        "patch": patch,
    }


def validate_enrichment_patches(
    patches: List[Dict[str, Any]],
    blueprint: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Validate a list of enrichment patches.

    Returns a list of validation result dicts (one per patch).
    """
    return [validate_enrichment_patch(p, blueprint=blueprint) for p in patches]


# ---------------------------------------------------------------------------
# Patch application
# ---------------------------------------------------------------------------

def apply_enrichment_patches(
    patches: List[Dict[str, Any]],
    module_dir: str,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Apply validated enrichment patches to module files.

    Args:
        patches: List of validated patch dicts
        module_dir: Module directory path
        dry_run: If True, return planned changes without writing

    Returns:
        Dict with: applied, rejected, errors, warnings
    """
    applied: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    warnings: List[str] = []

    module_path = Path(module_dir)

    # Group patches by target file for batch processing
    file_patches: Dict[str, List[Dict[str, Any]]] = {}
    for patch in patches:
        target_file = patch.get("target_file", "")
        if target_file not in file_patches:
            file_patches[target_file] = []
        file_patches[target_file].append(patch)

    for target_file, file_patch_list in file_patches.items():
        file_path = module_path / target_file

        if not file_path.exists():
            warnings.append(f"Target file '{target_file}' does not exist - skipping")
            for p in file_patch_list:
                rejected.append({
                    "patch": p,
                    "reason": f"Target file '{target_file}' does not exist",
                })
            continue

        # Load file data
        try:
            with open(str(file_path), "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            errors.append({
                "target_file": target_file,
                "reason": f"Failed to load file: {e}",
            })
            for p in file_patch_list:
                rejected.append({
                    "patch": p,
                    "reason": f"Failed to load file: {e}",
                })
            continue

        if dry_run:
            for patch in file_patch_list:
                jp = patch.get("json_path", "")
                found, _, _ = _resolve_json_path(data, jp)
                applied.append({
                    "patch": patch,
                    "target_file": target_file,
                    "path_resolved": found,
                })
            continue

        # Apply patches to the loaded data
        for patch in file_patch_list:
            json_path = patch.get("json_path", "")
            new_value = patch.get("value", "")

            success = _set_json_path(data, json_path, new_value)
            if success:
                applied.append({
                    "patch": patch,
                    "target_file": target_file,
                })
            else:
                warnings.append(f"Could not resolve json_path '{json_path}' in '{target_file}'")
                rejected.append({
                    "patch": patch,
                    "reason": f"Could not resolve json_path '{json_path}' in '{target_file}'",
                })

        # Write updated file atomically
        try:
            safe_write_json(str(file_path), data)
        except Exception as e:
            errors.append({
                "target_file": target_file,
                "reason": f"Failed to write file: {e}",
            })
            # Rollback is not possible at this granularity -
            # applied patches in this file were already written
            for p in file_patch_list:
                if p not in [r["patch"] for r in rejected]:
                    rejected.append({
                        "patch": p,
                        "reason": f"File write failed: {e}",
                    })

    return {
        "applied": applied,
        "rejected": rejected,
        "errors": errors,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Pipeline orchestration
# ---------------------------------------------------------------------------

def run_enrichment_pipeline(
    blueprint: Dict[str, Any],
    module_dir: str,
) -> Dict[str, Any]:
    """Run bounded enrichment pipeline against a seeded module.

    When ENABLE_ACCURATE_INGEST_BLUEPRINT_ENRICHMENT is False,
    returns immediately with status='skipped'.

    When enabled, runs LLM passes for each enrichment domain,
    validates patches, and applies them atomically.

    Args:
        blueprint: builder_blueprint.v2 dict
        module_dir: Module directory path

    Returns:
        Dict with: status, applied, rejected, errors, warnings, passes
    """
    try:
        from model_config import ENABLE_ACCURATE_INGEST_BLUEPRINT_ENRICHMENT
        enabled = bool(ENABLE_ACCURATE_INGEST_BLUEPRINT_ENRICHMENT)
    except (ImportError, AttributeError):
        enabled = False

    if not enabled:
        return {
            "status": ENRICHMENT_STATUS_SKIPPED,
            "reason": "ENABLE_ACCURATE_INGEST_BLUEPRINT_ENRICHMENT is disabled",
            "applied": [],
            "rejected": [],
            "errors": [],
            "warnings": [],
            "passes": [],
        }

    pass_results: List[Dict[str, Any]] = []
    all_applied: List[Dict[str, Any]] = []
    all_rejected: List[Dict[str, Any]] = []
    all_errors: List[Dict[str, Any]] = []
    all_warnings: List[str] = []

    # Pass 1: Module overview and plot enrichment
    try:
        result = _run_enrichment_pass(blueprint, module_dir, "module_overview")
        pass_results.append(result)
        all_applied.extend(result.get("applied", []))
        all_rejected.extend(result.get("rejected", []))
        all_errors.extend(result.get("errors", []))
        all_warnings.extend(result.get("warnings", []))
    except Exception as e:
        all_warnings.append(f"Module overview pass failed: {e}")

    # Pass 2: NPC enrichment
    try:
        result = _run_enrichment_pass(blueprint, module_dir, "npc")
        pass_results.append(result)
        all_applied.extend(result.get("applied", []))
        all_rejected.extend(result.get("rejected", []))
        all_errors.extend(result.get("errors", []))
        all_warnings.extend(result.get("warnings", []))
    except Exception as e:
        all_warnings.append(f"NPC enrichment pass failed: {e}")

    # Pass 3: Area/location prose enrichment
    try:
        result = _run_enrichment_pass(blueprint, module_dir, "location")
        pass_results.append(result)
        all_applied.extend(result.get("applied", []))
        all_rejected.extend(result.get("rejected", []))
        all_errors.extend(result.get("errors", []))
        all_warnings.extend(result.get("warnings", []))
    except Exception as e:
        all_warnings.append(f"Location enrichment pass failed: {e}")

    # Pass 4: Plot point enrichment
    try:
        result = _run_enrichment_pass(blueprint, module_dir, "plot")
        pass_results.append(result)
        all_applied.extend(result.get("applied", []))
        all_rejected.extend(result.get("rejected", []))
        all_errors.extend(result.get("errors", []))
        all_warnings.extend(result.get("warnings", []))
    except Exception as e:
        all_warnings.append(f"Plot enrichment pass failed: {e}")

    overall_rejected = len(all_rejected)
    status = ENRICHMENT_STATUS_COMPLETE if overall_rejected == 0 else ENRICHMENT_STATUS_DEGRADED

    return {
        "status": status,
        "applied": all_applied,
        "rejected": all_rejected,
        "errors": all_errors,
        "warnings": all_warnings,
        "passes": pass_results,
    }


def _run_enrichment_pass(
    blueprint: Dict[str, Any],
    module_dir: str,
    pass_type: str,
) -> Dict[str, Any]:
    """Run a single enrichment pass.

    Each pass:
    1. Reads current module files
    2. Builds an LLM prompt targeting the pass domain
    3. Calls the LLM to generate patch proposals
    4. Validates each patch
    5. Applies validated patches
    6. Returns result summary

    For now, the LLM step is a no-op that returns empty patches.
    Provider orchestration will be added in a follow-up.
    """
    return {
        "pass_type": pass_type,
        "applied": [],
        "rejected": [],
        "errors": [],
        "warnings": ["LLM provider orchestration not yet implemented for this pass"],
        "patches_requested": 0,
        "patches_returned": 0,
    }


# ---------------------------------------------------------------------------
# Report builder
# ---------------------------------------------------------------------------

def _build_skipped_report(reason: str) -> Dict[str, Any]:
    return {
        "status": ENRICHMENT_STATUS_SKIPPED,
        "reason": reason,
        "applied": [],
        "rejected": [],
        "errors": [],
        "warnings": [reason],
        "passes": [],
    }


def build_enrichment_report(
    pipeline_result: Dict[str, Any],
    blueprint: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build enrichment_report.json from pipeline result."""
    from datetime import datetime, timezone

    return {
        "enrichment_report_version": ENRICHMENT_REPORT_VERSION,
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "status": pipeline_result.get("status", ENRICHMENT_STATUS_SKIPPED),
        "reason": pipeline_result.get("reason", ""),
        "applied_count": len(pipeline_result.get("applied", [])),
        "rejected_count": len(pipeline_result.get("rejected", [])),
        "error_count": len(pipeline_result.get("errors", [])),
        "warning_count": len(pipeline_result.get("warnings", [])),
        "pass_count": len(pipeline_result.get("passes", [])),
        "applied": pipeline_result.get("applied", []),
        "rejected": pipeline_result.get("rejected", []),
        "errors": pipeline_result.get("errors", []),
        "warnings": pipeline_result.get("warnings", []),
    }
