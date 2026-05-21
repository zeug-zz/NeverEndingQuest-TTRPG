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

import hashlib
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
ENRICHMENT_STATUS_NOT_IMPLEMENTED = "not_implemented"
ENRICHMENT_STATUS_FAILED = "failed"

ALL_ENRICHMENT_STATUSES = {
    ENRICHMENT_STATUS_SKIPPED,
    ENRICHMENT_STATUS_DEGRADED,
    ENRICHMENT_STATUS_COMPLETE,
    ENRICHMENT_STATUS_NOT_IMPLEMENTED,
    ENRICHMENT_STATUS_FAILED,
}

_CACHE_KEY_HASH = "sha256"

def _stable_json_dumps(value: Any) -> str:
    """Deterministic JSON serialization stable across dict key order.

    Uses sort_keys, compact separators, and ensure_ascii so the output
    is identical regardless of dict insertion order or runtime locale.
    """
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _input_cache_key(pass_type: str, inputs: Dict[str, Any]) -> str:
    """Compute a deterministic cache key for enrichment pass inputs.

    Uses SHA-256 of stable JSON. Excludes raw file paths from module_dir
    by hashing only serializable metadata (targets, excerpts, counts).
    Returns a 64-char hex digest string.
    """
    payload = {
        "pass_type": pass_type,
        "inputs": inputs,
    }
    serialized = _stable_json_dumps(payload)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


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
    "features", "traps", "dcChecks", "doors", "lootTable",
    "encounters", "npcs", "monsters",
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
            # Validate each patch before applying to reject structural mutations
            validation = validate_enrichment_patch(patch)
            if not validation["valid"]:
                rejected.append({
                    "patch": patch,
                    "reason": validation["reason"],
                })
                continue

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
            "reason": "feature_flag_disabled",
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
    failed_passes = 0

    # Pass 1: Module overview and plot enrichment
    try:
        result = _run_enrichment_pass(blueprint, module_dir, "module_overview")
        pass_results.append(result)
        all_applied.extend(result.get("applied", []))
        all_rejected.extend(result.get("rejected", []))
        all_errors.extend(result.get("errors", []))
        all_warnings.extend(result.get("warnings", []))
    except Exception as e:
        failed_passes += 1
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
        failed_passes += 1
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
        failed_passes += 1
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
        failed_passes += 1
        all_warnings.append(f"Plot enrichment pass failed: {e}")

    overall_rejected = len(all_rejected)
    overall_applied = len(all_applied)

    # Pass exceptions must not return complete. Degrade immediately.
    if failed_passes > 0:
        return {
            "status": ENRICHMENT_STATUS_DEGRADED,
            "reason": f"{failed_passes} enrichment pass(es) failed",
            "applied": all_applied,
            "rejected": all_rejected,
            "errors": all_errors,
            "warnings": all_warnings,
            "passes": pass_results,
        }

    # If enabled but every pass is a no-op (provider not yet implemented),
    # never report complete.
    if overall_applied == 0 and not all_errors:
        not_implemented = any(
            "provider orchestration not yet implemented" in str(w).lower()
            for w in all_warnings
        )
        if not_implemented:
            return {
                "status": ENRICHMENT_STATUS_NOT_IMPLEMENTED,
                "reason": "LLM provider orchestration not yet implemented",
                "applied": all_applied,
                "rejected": all_rejected,
                "errors": all_errors,
                "warnings": all_warnings,
                "passes": pass_results,
            }

    # Pass-level errors degrade status even if no patches were rejected.
    if all_errors:
        return {
            "status": ENRICHMENT_STATUS_DEGRADED,
            "reason": "enrichment_pass_errors",
            "applied": all_applied,
            "rejected": all_rejected,
            "errors": all_errors,
            "warnings": all_warnings,
            "passes": pass_results,
        }

    status = ENRICHMENT_STATUS_COMPLETE if overall_rejected == 0 else ENRICHMENT_STATUS_DEGRADED

    return {
        "status": status,
        "applied": all_applied,
        "rejected": all_rejected,
        "errors": all_errors,
        "warnings": all_warnings,
        "passes": pass_results,
    }


def _select_bounded_excerpt(
    candidate: Dict[str, Any],
    max_chars: int = 200,
) -> str:
    """Select a bounded source excerpt from a candidate record.

    Prefers source_refs text, falls back to candidate_text, then
    location binding text. Clips to max_chars without ellipsis to
    keep output deterministic for prompt construction.
    """
    source_refs = candidate.get("source_refs", [])
    if source_refs and isinstance(source_refs, list):
        for ref in source_refs:
            ref_text = ref.get("text", "") if isinstance(ref, dict) else str(ref)
            if ref_text:
                return ref_text[:max_chars]

    text = candidate.get("candidate_text", "") or ""
    if text:
        return text[:max_chars]

    bindings = candidate.get("location_bindings", [])
    if bindings and isinstance(bindings, list):
        binding_text = ", ".join(str(b) for b in bindings)
        if binding_text:
            return binding_text[:max_chars]

    return ""


_NON_ACTOR_ADJUDICATED_TYPES: frozenset = frozenset({
    "narrative_phrase", "plot_note", "tone_marker", "unknown",
})

_ACTOR_NPC_ADJUDICATED_TYPES: frozenset = frozenset({
    "true_npc", "scene_actor", "monster_actor",
})


def _build_npc_pass_inputs(
    blueprint: Dict[str, Any],
    module_dir: str,
    max_excerpt_chars: int = 200,
) -> Dict[str, Any]:
    """Build bounded NPC enrichment pass inputs from blueprint triage data.

    Selects bounded source excerpts and kept/reclassified candidate records
    when triage-like data is present. Rejected narrative phrases are excluded
    from enrichment targets but preserved as diagnostics.

    Args:
        blueprint: builder_blueprint.v2 dict
        module_dir: Module directory path
        max_excerpt_chars: Maximum length for source excerpts

    Returns:
        Dict with:
          npc_targets: list of NPC enrichment targets with identity fields
          rejected_narratives: list of rejected non-actor phrases (diagnostics)
          excerpt_count: count of bounded excerpts selected
          has_triage_data: whether triage decisions were consumed
          source_artifact: name of source artifact used
    """
    npc_targets: List[Dict[str, Any]] = []
    rejected_narratives: List[Dict[str, Any]] = []
    has_triage_data = False
    source_artifact = "module_context"

    triage_report = blueprint.get("entity_candidate_triage_report")
    if triage_report and isinstance(triage_report, dict):
        decisions = triage_report.get("decisions", [])
        if decisions:
            has_triage_data = True
            source_artifact = "entity_candidate_triage_report"

            for d in decisions:
                decision = d.get("decision", "")
                adj_type = d.get("adjudicated_type", "")

                if decision == "reject" or adj_type in _NON_ACTOR_ADJUDICATED_TYPES:
                    rejected_narratives.append({
                        "candidate_text": d.get("candidate_text", ""),
                        "candidate_slug": d.get("candidate_slug", ""),
                        "adjudicated_type": adj_type,
                        "decision": decision,
                        "reason": d.get("reason", ""),
                    })
                    continue

                if decision in ("keep", "reclassify") and adj_type in _ACTOR_NPC_ADJUDICATED_TYPES:
                    target: Dict[str, Any] = {
                        "candidate_text": d.get("candidate_text", ""),
                        "candidate_slug": d.get("candidate_slug", ""),
                        "adjudicated_type": adj_type,
                        "decision": decision,
                        "source_refs": d.get("source_refs", []),
                        "location_bindings": d.get("location_bindings", []),
                    }
                    excerpt = _select_bounded_excerpt(d, max_excerpt_chars)
                    if excerpt:
                        target["source_excerpt"] = excerpt
                    npc_targets.append(target)

    if not has_triage_data:
        module_context_path = os.path.join(module_dir, "module_context.json")
        if os.path.isfile(module_context_path):
            try:
                with open(module_context_path, "r", encoding="utf-8") as f:
                    module_context = json.load(f)
                for npc_key, npc_data in module_context.get("npcs", {}).items():
                    target: Dict[str, Any] = {
                        "candidate_text": npc_data.get("name", npc_key),
                        "candidate_slug": npc_key,
                        "adjudicated_type": "true_npc",
                        "decision": "keep",
                        "source_refs": npc_data.get("source_refs", []),
                        "location_bindings": [],
                    }
                    desc = npc_data.get("description", "") or ""
                    if desc:
                        target["source_excerpt"] = desc[:max_excerpt_chars]
                    npc_targets.append(target)
            except (json.JSONDecodeError, IOError):
                pass

    cache_payload = {
        "pass_type": "npc",
        "targets": sorted(
            (t["candidate_slug"], t.get("source_excerpt", ""))
            for t in npc_targets
        ),
        "rejected_count": len(rejected_narratives),
        "has_triage_data": has_triage_data,
        "source_artifact": source_artifact,
    }

    return {
        "npc_targets": npc_targets,
        "rejected_narratives": rejected_narratives,
        "excerpt_count": sum(1 for t in npc_targets if t.get("source_excerpt")),
        "has_triage_data": has_triage_data,
        "source_artifact": source_artifact,
        "input_cache_key": hashlib.sha256(
            _stable_json_dumps(cache_payload).encode("utf-8")
        ).hexdigest(),
    }


# ---------------------------------------------------------------------------
# NPC enrichment response parsing and conversion
# ---------------------------------------------------------------------------

def _parse_npc_enrichment_response(
    response_data: Any,
) -> Dict[str, Any]:
    """Parse and validate a JSON-only NPC enrichment response.

    Accepts only dict input. Rejects arrays, prose-wrapped text,
    and other non-dict structures. Returns the parsed result or
    an error dict.

    Args:
        response_data: Raw provider response (dict, list, or string)

    Returns:
        Dict with:
          valid: bool
          response (if valid): parsed dict
          patches_raw (if valid): list of proposed patch dicts
          pass_name (if valid): pass name string
          pass_type (if valid): pass type string
          error (if invalid): error message string
    """
    if isinstance(response_data, str):
        stripped = response_data.strip()
        if stripped.startswith("```") or stripped.endswith("```"):
            return {"valid": False, "error": "response is prose-wrapped in code fences"}
        if stripped.startswith("`") or stripped.endswith("`"):
            return {"valid": False, "error": "response is wrapped in backticks"}
        try:
            response_data = json.loads(stripped)
        except (json.JSONDecodeError, ValueError) as e:
            return {"valid": False, "error": f"malformed JSON: {e}"}

    if not isinstance(response_data, dict):
        if isinstance(response_data, list):
            return {"valid": False, "error": "response is a JSON array, expected object"}
        return {"valid": False, "error": f"response has unexpected type: {type(response_data).__name__}"}

    pass_name = response_data.get("pass_name", "")
    if not pass_name:
        return {"valid": False, "error": "missing pass_name in response"}

    patches_raw = response_data.get("proposed_patches")
    if patches_raw is None:
        return {"valid": False, "error": "missing proposed_patches array in response"}
    if not isinstance(patches_raw, list):
        return {"valid": False, "error": "proposed_patches must be a list"}

    filtered = [p for p in patches_raw if isinstance(p, dict)]

    return {
        "valid": True,
        "response": response_data,
        "patches_raw": filtered,
        "pass_name": pass_name,
        "pass_type": response_data.get("pass_type", ""),
    }


def _convert_npc_enrichment_output_to_patches(
    parsed: Dict[str, Any],
    npc_targets: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Convert parsed NPC enrichment output into validated patch candidates.

    Each proposed patch must have at minimum: blueprint_id, target_file,
    json_path, field, value. Source refs or reason must be present as
    justification. Structural field proposals are rejected.

    Args:
        parsed: Result from _parse_npc_enrichment_response with valid=True
        npc_targets: Optional Step 1.1 scaffold NPC targets for identity refs

    Returns:
        Dict with:
          patch_candidates: list of patch dicts for validate_enrichment_patch
          dropped: list of dropped proposals with reasons
    """
    patch_candidates: List[Dict[str, Any]] = []
    dropped: List[Dict[str, Any]] = []

    slug_map: Dict[str, Dict[str, Any]] = {}
    if npc_targets:
        for t in npc_targets:
            slug = t.get("candidate_slug", "")
            if slug:
                slug_map[slug] = t

    patches_raw = parsed.get("patches_raw", [])

    for i, proposal in enumerate(patches_raw):
        if not isinstance(proposal, dict):
            dropped.append({"index": i, "reason": "proposal is not a dict"})
            continue

        bp_id = proposal.get("blueprint_id", "")
        target_file = proposal.get("target_file", "")
        json_path = proposal.get("json_path", "")
        field = proposal.get("field", "")
        value = proposal.get("value", "")

        if not bp_id:
            dropped.append({"index": i, "reason": "missing blueprint_id"})
            continue
        if not target_file:
            dropped.append({"index": i, "reason": "missing target_file"})
            continue
        if not json_path:
            dropped.append({"index": i, "reason": "missing json_path"})
            continue
        if not field:
            dropped.append({"index": i, "reason": "missing field"})
            continue
        if not isinstance(value, str) or not value:
            dropped.append({"index": i, "reason": "missing or non-string value"})
            continue

        if field in FORBIDDEN_FIELDS:
            dropped.append({"index": i, "reason": f"forbidden field: {field}"})
            continue
        if _has_forbidden_path_pattern(json_path):
            dropped.append({"index": i, "reason": f"forbidden path pattern in: {json_path}"})
            continue

        source_refs = proposal.get("source_refs", [])
        reason = proposal.get("reason", "")
        if not source_refs and not reason:
            dropped.append({"index": i, "reason": "missing source_refs and reason (no justification)"})
            continue

        patch: Dict[str, Any] = {
            "op": "replace",
            "blueprint_id": bp_id,
            "target_file": target_file,
            "json_path": json_path,
            "field": field,
            "value": value,
        }

        if source_refs:
            patch["source_refs"] = source_refs
        if reason:
            patch["reason"] = reason

        entity_slug = proposal.get("entity_slug", "")
        if entity_slug:
            patch["entity_slug"] = entity_slug
            if entity_slug in slug_map:
                scaffold = slug_map[entity_slug]
                if "source_excerpt" in scaffold:
                    patch["_scaffold_source_excerpt"] = scaffold["source_excerpt"]

        patch_candidates.append(patch)

    return {
        "patch_candidates": patch_candidates,
        "dropped": dropped,
    }


# ---------------------------------------------------------------------------
# Plot/puzzle/clue field constants
# ---------------------------------------------------------------------------

_PLOT_PROSE_FIELDS: frozenset = frozenset({
    "description", "title", "plotImpact", "mainObjective",
})

_PLOT_STRUCTURAL_METADATA: frozenset = frozenset({
    "id", "nextPoints", "prerequisites", "status", "type",
})

_PUZZLE_CLUE_PROSE_FIELDS: frozenset = frozenset({
    "clues", "setup", "rules", "solution",
    "description", "dmInstructions", "features",
    "dcChecks", "adventureSummary",
})


# ---------------------------------------------------------------------------
# Location pass input scaffold helpers
# ---------------------------------------------------------------------------

_LOCATION_PROSE_FIELDS: frozenset = frozenset({
    "description", "dmInstructions", "adventureSummary", "plotHooks",
    "features", "traps", "dcChecks", "doors", "lootTable",
    "encounters", "npcs", "monsters",
})

_LOCATION_STRUCTURAL_FIELDS: frozenset = frozenset({
    "areaId", "locationId", "connectivity", "areaConnectivity",
    "areaConnectivityId", "dependencies", "nextPoints", "prerequisites",
})


def _location_source_excerpt(
    location: Dict[str, Any],
    max_chars: int = 200,
) -> str:
    """Collect bounded excerpt from a location's prose fields.

    Concatenates non-empty prose fields with '. ' separator,
    clipped to max_chars without ellipsis.
    """
    parts: List[str] = []
    for field in sorted(_LOCATION_PROSE_FIELDS):
        val = location.get(field)
        if val and isinstance(val, str):
            parts.append(val.strip())
    if not parts:
        return ""
    combined = ". ".join(parts)
    return combined[:max_chars]


def _build_location_pass_inputs(
    blueprint: Dict[str, Any],
    module_dir: str,
    max_excerpt_chars: int = 200,
) -> Dict[str, Any]:
    """Build bounded location enrichment pass inputs from module area files.

    Discovers locations from area files, selects bounded source excerpts,
    and preserves identity fields without treating them as editable.

    Args:
        blueprint: builder_blueprint.v2 dict
        module_dir: Module directory path
        max_excerpt_chars: Maximum length for source excerpts

    Returns:
        Dict with:
          location_targets: list of location target dicts with identity/excerpt
          area_count: number of area files discovered
          location_count: total locations across all areas
          excerpt_count: count of targets with bounded excerpts
          excerpt_max_chars: max excerpt length configured
    """
    location_targets: List[Dict[str, Any]] = []
    areas_dir = os.path.join(module_dir, "areas")
    area_count = 0

    if os.path.isdir(areas_dir):
        for fname in sorted(os.listdir(areas_dir)):
            if not fname.endswith(".json"):
                continue
            area_path = os.path.join(areas_dir, fname)
            try:
                with open(area_path, "r", encoding="utf-8") as f:
                    area_data = json.load(f)
            except (json.JSONDecodeError, IOError):
                continue

            area_count += 1
            area_id = area_data.get("areaId", "")
            area_name = area_data.get("areaName", "")
            locations = area_data.get("locations", [])
            if not isinstance(locations, list):
                continue

            for idx, loc in enumerate(locations):
                if not isinstance(loc, dict):
                    continue

                loc_id = loc.get("locationId", "")
                loc_name = loc.get("name", "")

                target: Dict[str, Any] = {
                    "area_file": fname,
                    "area_id": area_id,
                    "area_name": area_name,
                    "location_id": loc_id,
                    "location_name": loc_name,
                    "location_index": idx,
                    "location_path": f"locations[{idx}]",
                    "source_excerpt": _location_source_excerpt(loc, max_excerpt_chars),
                }
                location_targets.append(target)

    cache_payload = {
        "pass_type": "location",
        "targets": sorted(
            (t["location_id"], t["source_excerpt"])
            for t in location_targets
        ),
        "area_count": area_count,
        "max_excerpt_chars": max_excerpt_chars,
    }

    return {
        "location_targets": location_targets,
        "area_count": area_count,
        "location_count": len(location_targets),
        "excerpt_count": sum(1 for t in location_targets if t.get("source_excerpt")),
        "excerpt_max_chars": max_excerpt_chars,
        "input_cache_key": hashlib.sha256(
            _stable_json_dumps(cache_payload).encode("utf-8")
        ).hexdigest(),
    }


# ---------------------------------------------------------------------------
# Plot/puzzle/clue pass input scaffold helpers
# ---------------------------------------------------------------------------


def _plot_prose_excerpt(
    plot_point: Dict[str, Any],
    max_chars: int = 200,
) -> str:
    """Collect bounded excerpt from a plot point's prose fields."""
    parts: List[str] = []
    for field in sorted(_PLOT_PROSE_FIELDS):
        val = plot_point.get(field)
        if val and isinstance(val, str):
            parts.append(val.strip())
    if not parts:
        return ""
    combined = ". ".join(parts)
    return combined[:max_chars]


def _puzzle_clue_excerpt(
    location: Dict[str, Any],
    max_chars: int = 200,
) -> str:
    """Collect bounded excerpt from a location's puzzle/clue-relevant prose fields."""
    parts: List[str] = []
    for field in sorted(_PUZZLE_CLUE_PROSE_FIELDS):
        val = location.get(field)
        if val and isinstance(val, str):
            parts.append(val.strip())
    if not parts:
        return ""
    combined = ". ".join(parts)
    return combined[:max_chars]


def _build_plot_puzzle_clue_pass_inputs(
    blueprint: Dict[str, Any],
    module_dir: str,
    max_excerpt_chars: int = 200,
) -> Dict[str, Any]:
    """Build bounded plot/puzzle/clue enrichment pass inputs.

    Discovers plot points from module_plot_BU.json and puzzle/clue-
    relevant location fields from area files. Produces bounded source
    excerpts and identity metadata without patch application.

    Args:
        blueprint: builder_blueprint.v2 dict
        module_dir: Module directory path
        max_excerpt_chars: Maximum length for source excerpts

    Returns:
        Dict with:
          plot_point_targets: list of plot point target dicts
          puzzle_clue_targets: list of location targets with puzzle/clue fields
          plot_point_count: number of plot points discovered
          puzzle_clue_location_count: number of locations with puzzle/clue-relevant fields
          plot_excerpt_count: count of plot point excerpts with content
          puzzle_clue_excerpt_count: count of puzzle/clue excerpts with content
          excerpt_max_chars: max excerpt length configured
    """
    plot_point_targets: List[Dict[str, Any]] = []
    puzzle_clue_targets: List[Dict[str, Any]] = []

    # --- Read plot points from module_plot_BU.json ---
    plot_path = os.path.join(module_dir, "module_plot_BU.json")
    if os.path.isfile(plot_path):
        try:
            with open(plot_path, "r", encoding="utf-8") as f:
                plot_data = json.load(f)
        except (json.JSONDecodeError, IOError):
            plot_data = {}

        for pp in plot_data.get("plotPoints", []):
            if not isinstance(pp, dict):
                continue
            pp_id = pp.get("id", "")
            if not pp_id:
                continue
            structural: Dict[str, Any] = {}
            for key in _PLOT_STRUCTURAL_METADATA:
                if key in pp:
                    structural[key] = pp[key]
            plot_point_targets.append({
                "plot_point_id": pp_id,
                "plot_point_title": pp.get("title", ""),
                "source_excerpt": _plot_prose_excerpt(pp, max_excerpt_chars),
                "structural_metadata": structural,
            })

    # --- Read puzzle/clue-relevant fields from area files ---
    areas_dir = os.path.join(module_dir, "areas")
    if os.path.isdir(areas_dir):
        for fname in sorted(os.listdir(areas_dir)):
            if not fname.endswith(".json"):
                continue
            area_path = os.path.join(areas_dir, fname)
            try:
                with open(area_path, "r", encoding="utf-8") as f:
                    area_data = json.load(f)
            except (json.JSONDecodeError, IOError):
                continue

            area_id = area_data.get("areaId", "")
            area_name = area_data.get("areaName", "")
            for idx, loc in enumerate(area_data.get("locations", [])):
                if not isinstance(loc, dict):
                    continue
                loc_id = loc.get("locationId", "")
                excerpt = _puzzle_clue_excerpt(loc, max_excerpt_chars)
                puzzle_clue_targets.append({
                    "area_file": fname,
                    "area_id": area_id,
                    "area_name": area_name,
                    "location_id": loc_id,
                    "location_name": loc.get("name", ""),
                    "location_index": idx,
                    "location_path": f"locations[{idx}]",
                    "source_excerpt": excerpt,
                })

    cache_payload = {
        "pass_type": "plot_puzzle_clue",
        "plot_points": sorted(
            (t["plot_point_id"], t["source_excerpt"])
            for t in plot_point_targets
        ),
        "puzzle_clue": sorted(
            (t["location_id"], t["source_excerpt"])
            for t in puzzle_clue_targets
        ),
        "max_excerpt_chars": max_excerpt_chars,
    }

    return {
        "plot_point_targets": plot_point_targets,
        "puzzle_clue_targets": puzzle_clue_targets,
        "plot_point_count": len(plot_point_targets),
        "puzzle_clue_location_count": len(puzzle_clue_targets),
        "plot_excerpt_count": sum(1 for t in plot_point_targets if t.get("source_excerpt")),
        "puzzle_clue_excerpt_count": sum(1 for t in puzzle_clue_targets if t.get("source_excerpt")),
        "excerpt_max_chars": max_excerpt_chars,
        "input_cache_key": hashlib.sha256(
            _stable_json_dumps(cache_payload).encode("utf-8")
        ).hexdigest(),
    }


# ---------------------------------------------------------------------------
# Encounter/item pass input scaffold helpers
# ---------------------------------------------------------------------------

_ENCOUNTER_PROSE_FIELDS: frozenset = frozenset({
    "encounters", "monsters", "npcs", "traps", "dcChecks",
    "adventureSummary", "description", "dmInstructions",
})

_ITEM_PROSE_FIELDS: frozenset = frozenset({
    "lootTable", "features", "description", "doors", "dmInstructions",
})


def _encounter_excerpt(
    location: Dict[str, Any],
    max_chars: int = 200,
) -> str:
    """Collect bounded excerpt from a location's encounter-relevant prose fields."""
    parts: List[str] = []
    for field in sorted(_ENCOUNTER_PROSE_FIELDS):
        val = location.get(field)
        if val and isinstance(val, str):
            parts.append(val.strip())
    if not parts:
        return ""
    combined = ". ".join(parts)
    return combined[:max_chars]


def _item_excerpt(
    location: Dict[str, Any],
    max_chars: int = 200,
) -> str:
    """Collect bounded excerpt from a location's item-relevant prose fields."""
    parts: List[str] = []
    for field in sorted(_ITEM_PROSE_FIELDS):
        val = location.get(field)
        if val and isinstance(val, str):
            parts.append(val.strip())
    if not parts:
        return ""
    combined = ". ".join(parts)
    return combined[:max_chars]


def _build_encounter_item_pass_inputs(
    blueprint: Dict[str, Any],
    module_dir: str,
    max_excerpt_chars: int = 200,
) -> Dict[str, Any]:
    """Build bounded encounter/item enrichment pass inputs.

    Discovers encounter-relevant and item-relevant fields from area file
    locations. Produces bounded source excerpts and identity metadata
    without patch application.

    Args:
        blueprint: builder_blueprint.v2 dict
        module_dir: Module directory path
        max_excerpt_chars: Maximum length for source excerpts

    Returns:
        Dict with:
          encounter_targets: list of location targets with encounter excerpts
          item_targets: list of location targets with item excerpts
          encounter_location_count: number of locations with encounter excerpts
          item_location_count: number of locations with item excerpts
          encounter_excerpt_count: count with non-empty encounter excerpts
          item_excerpt_count: count with non-empty item excerpts
          excerpt_max_chars: max excerpt length configured
    """
    encounter_targets: List[Dict[str, Any]] = []
    item_targets: List[Dict[str, Any]] = []

    areas_dir = os.path.join(module_dir, "areas")
    if os.path.isdir(areas_dir):
        for fname in sorted(os.listdir(areas_dir)):
            if not fname.endswith(".json"):
                continue
            area_path = os.path.join(areas_dir, fname)
            try:
                with open(area_path, "r", encoding="utf-8") as f:
                    area_data = json.load(f)
            except (json.JSONDecodeError, IOError):
                continue

            area_id = area_data.get("areaId", "")
            area_name = area_data.get("areaName", "")
            for idx, loc in enumerate(area_data.get("locations", [])):
                if not isinstance(loc, dict):
                    continue
                loc_id = loc.get("locationId", "")
                loc_name = loc.get("name", "")

                e_excerpt = _encounter_excerpt(loc, max_excerpt_chars)
                i_excerpt = _item_excerpt(loc, max_excerpt_chars)

                encounter_targets.append({
                    "area_file": fname,
                    "area_id": area_id,
                    "area_name": area_name,
                    "location_id": loc_id,
                    "location_name": loc_name,
                    "location_index": idx,
                    "location_path": f"locations[{idx}]",
                    "source_excerpt": e_excerpt,
                })

                item_targets.append({
                    "area_file": fname,
                    "area_id": area_id,
                    "area_name": area_name,
                    "location_id": loc_id,
                    "location_name": loc_name,
                    "location_index": idx,
                    "location_path": f"locations[{idx}]",
                    "source_excerpt": i_excerpt,
                })

    cache_payload = {
        "pass_type": "encounter_item",
        "encounter": sorted(
            (t["location_id"], t["source_excerpt"])
            for t in encounter_targets
        ),
        "item": sorted(
            (t["location_id"], t["source_excerpt"])
            for t in item_targets
        ),
        "max_excerpt_chars": max_excerpt_chars,
    }

    return {
        "encounter_targets": encounter_targets,
        "item_targets": item_targets,
        "encounter_location_count": len(encounter_targets),
        "item_location_count": len(item_targets),
        "encounter_excerpt_count": sum(
            1 for t in encounter_targets if t.get("source_excerpt")
        ),
        "item_excerpt_count": sum(
            1 for t in item_targets if t.get("source_excerpt")
        ),
        "excerpt_max_chars": max_excerpt_chars,
        "input_cache_key": hashlib.sha256(
            _stable_json_dumps(cache_payload).encode("utf-8")
        ).hexdigest(),
    }


# ---------------------------------------------------------------------------
# Tone/style pass input scaffold helpers
# ---------------------------------------------------------------------------

_TONE_STYLE_SOURCE_FIELDS: frozenset = frozenset({
    "description", "dmInstructions", "adventureSummary",
    "areaDescription", "mainObjective", "plotHooks",
    "plotImpact", "title",
})

# Mood keywords for deterministic tone guidance
_TONE_MOOD_KEYWORDS: Dict[str, List[str]] = {
    "dark": ["dark", "shadow", "gloom", "ominous", "foreboding", "sinister",
             "eerie", "creepy", "haunted", "dread", "macabre"],
    "mysterious": ["mystery", "unknown", "strange", "ancient", "forgotten",
                   "arcane", "enigmatic", "cryptic", "hidden", "secret"],
    "hopeful": ["light", "hope", "dawn", "courage", "brave", "inspire",
                "triumph", "glorious", "radiant", "blessing"],
    "melancholy": ["sad", "wistful", "mournful", "tragic", "grief",
                   "lonely", "lost", "fading", "decay", "ruin"],
    "heroic": ["epic", "quest", "destiny", "valor", "honor", "noble",
               "mighty", "legendary", "oath", "sacred"],
    "natural": ["forest", "wild", "nature", "ancient", "overgrown",
                "primal", "elemental", "wilderness", "untamed", "verdant"],
}

# Mood fields NOT in this list: tone notes without IDs, NPCs, locations, etc.
# List is intentionally stable, authored words only


def _derive_tone_notes(
    excerpt: str,
    source_kind: str,
    source_id: str,
) -> List[str]:
    """Derive deterministic tone/style notes from a bounded excerpt.

    Returns a list of concise guidance strings. Only sources from authored
    prose; never invents plot IDs, NPC names, location IDs, or objectives.
    """
    notes: List[str] = []
    excerpt_lower = excerpt.lower()

    mood_hits: List[str] = []
    for mood, keywords in _TONE_MOOD_KEYWORDS.items():
        for kw in keywords:
            if kw in excerpt_lower:
                mood_hits.append(mood)
                break

    if mood_hits:
        notes.append(f"Mood indicators: {', '.join(sorted(set(mood_hits)))}")

    return notes


def _tone_source_excerpt(
    source_data: Dict[str, Any],
    max_chars: int = 200,
) -> str:
    """Collect bounded excerpt from a tone/style-relevant prose fields."""
    parts: List[str] = []
    for field in sorted(_TONE_STYLE_SOURCE_FIELDS):
        val = source_data.get(field)
        if val and isinstance(val, str):
            parts.append(val.strip())
    if not parts:
        return ""
    combined = ". ".join(parts)
    return combined[:max_chars]


def _build_tone_style_pass_inputs(
    blueprint: Dict[str, Any],
    module_dir: str,
    max_excerpt_chars: int = 200,
) -> Dict[str, Any]:
    """Build bounded tone/style enrichment pass inputs.

    Reads bounded excerpts from module context, plot, and area files.
    Produces identity metadata and deterministic tone guidance notes
    without patch application or invented plot content.

    Args:
        blueprint: builder_blueprint.v2 dict
        module_dir: Module directory path
        max_excerpt_chars: Maximum length for source excerpts

    Returns:
        Dict with:
          tone_style_targets: list of guidance target dicts
          source_count: total number of sources discovered
          excerpt_count: count with non-empty excerpts
          has_guidance: whether any tone notes were derived
          excerpt_max_chars: max excerpt length configured
    """
    tone_style_targets: List[Dict[str, Any]] = []

    # --- Module context ---
    context_path = os.path.join(module_dir, "module_context.json")
    if os.path.isfile(context_path):
        try:
            with open(context_path, "r", encoding="utf-8") as f:
                ctx = json.load(f)
        except (json.JSONDecodeError, IOError):
            ctx = {}

        excerpt = _tone_source_excerpt(ctx, max_excerpt_chars)
        if excerpt:
            tone_style_targets.append({
                "source_kind": "module_context",
                "source_id": ctx.get("module_id", ""),
                "source_excerpt": excerpt,
                "tone_style_guidance": _derive_tone_notes(
                    excerpt, "module_context", ctx.get("module_id", ""),
                ),
            })

    # --- Module plot ---
    plot_path = os.path.join(module_dir, "module_plot_BU.json")
    if os.path.isfile(plot_path):
        try:
            with open(plot_path, "r", encoding="utf-8") as f:
                plot_data = json.load(f)
        except (json.JSONDecodeError, IOError):
            plot_data = {}

        mo_excerpt = _tone_source_excerpt(plot_data, max_excerpt_chars)
        if mo_excerpt:
            tone_style_targets.append({
                "source_kind": "plot_main_objective",
                "source_id": "main_objective",
                "source_excerpt": mo_excerpt,
                "tone_style_guidance": _derive_tone_notes(
                    mo_excerpt, "plot_main_objective", "main_objective",
                ),
            })

        for pp in plot_data.get("plotPoints", []):
            if not isinstance(pp, dict):
                continue
            pp_id = pp.get("id", "")
            pp_excerpt = _tone_source_excerpt(pp, max_excerpt_chars)
            if pp_excerpt:
                tone_style_targets.append({
                    "source_kind": "plot_point",
                    "source_id": pp_id,
                    "source_excerpt": pp_excerpt,
                    "tone_style_guidance": _derive_tone_notes(
                        pp_excerpt, "plot_point", pp_id,
                    ),
                })

    # --- Area files ---
    areas_dir = os.path.join(module_dir, "areas")
    if os.path.isdir(areas_dir):
        for fname in sorted(os.listdir(areas_dir)):
            if not fname.endswith(".json"):
                continue
            area_path = os.path.join(areas_dir, fname)
            try:
                with open(area_path, "r", encoding="utf-8") as f:
                    area_data = json.load(f)
            except (json.JSONDecodeError, IOError):
                continue

            area_id = area_data.get("areaId", "")
            area_desc = area_data.get("areaDescription", "")
            if area_desc:
                clipped = area_desc[:max_excerpt_chars]
                tone_style_targets.append({
                    "source_kind": "area_description",
                    "source_id": area_id,
                    "source_excerpt": clipped,
                    "tone_style_guidance": _derive_tone_notes(
                        clipped, "area_description", area_id,
                    ),
                })

            for idx, loc in enumerate(area_data.get("locations", [])):
                if not isinstance(loc, dict):
                    continue
                loc_id = loc.get("locationId", "")
                loc_excerpt = _tone_source_excerpt(loc, max_excerpt_chars)
                if loc_excerpt:
                    tone_style_targets.append({
                        "source_kind": "location",
                        "source_id": loc_id,
                        "source_excerpt": loc_excerpt,
                        "tone_style_guidance": _derive_tone_notes(
                            loc_excerpt, "location", loc_id,
                        ),
                    })

    has_guidance = any(
        t.get("tone_style_guidance") for t in tone_style_targets
    )

    cache_payload = {
        "pass_type": "tone_style",
        "sources": sorted(
            (t["source_kind"], t["source_id"], t["source_excerpt"])
            for t in tone_style_targets
        ),
        "has_guidance": has_guidance,
        "max_excerpt_chars": max_excerpt_chars,
    }

    return {
        "tone_style_targets": tone_style_targets,
        "source_count": len(tone_style_targets),
        "excerpt_count": sum(
            1 for t in tone_style_targets if t.get("source_excerpt")
        ),
        "has_guidance": has_guidance,
        "excerpt_max_chars": max_excerpt_chars,
        "input_cache_key": hashlib.sha256(
            _stable_json_dumps(cache_payload).encode("utf-8")
        ).hexdigest(),
    }


# ---------------------------------------------------------------------------
# Location enrichment response parsing, conversion, and application
# ---------------------------------------------------------------------------


def _parse_location_enrichment_response(
    response_data: Any,
) -> Dict[str, Any]:
    """Parse and validate a JSON-only location enrichment response.

    Accepts only dict input. Rejects arrays, prose-wrapped text,
    and other non-dict structures. Mirrors _parse_npc_enrichment_response.
    """
    if isinstance(response_data, str):
        stripped = response_data.strip()
        if stripped.startswith("```") or stripped.endswith("```"):
            return {"valid": False, "error": "response is prose-wrapped in code fences"}
        if stripped.startswith("`") or stripped.endswith("`"):
            return {"valid": False, "error": "response is wrapped in backticks"}
        try:
            response_data = json.loads(stripped)
        except (json.JSONDecodeError, ValueError) as e:
            return {"valid": False, "error": f"malformed JSON: {e}"}

    if not isinstance(response_data, dict):
        if isinstance(response_data, list):
            return {"valid": False, "error": "response is a JSON array, expected object"}
        return {"valid": False, "error": f"response has unexpected type: {type(response_data).__name__}"}

    pass_name = response_data.get("pass_name", "")
    if not pass_name:
        return {"valid": False, "error": "missing pass_name in response"}

    patches_raw = response_data.get("proposed_patches")
    if patches_raw is None:
        return {"valid": False, "error": "missing proposed_patches array in response"}
    if not isinstance(patches_raw, list):
        return {"valid": False, "error": "proposed_patches must be a list"}

    filtered = [p for p in patches_raw if isinstance(p, dict)]

    return {
        "valid": True,
        "response": response_data,
        "patches_raw": filtered,
        "pass_name": pass_name,
        "pass_type": response_data.get("pass_type", ""),
    }


def _convert_location_enrichment_output_to_patches(
    parsed: Dict[str, Any],
) -> Dict[str, Any]:
    """Convert parsed location enrichment output into validated patch candidates.

    Each proposed patch must have at minimum: blueprint_id, target_file,
    json_path, field, value, and location identity metadata. Structural
    field proposals are rejected by existing guards.

    Returns:
        Dict with:
          patch_candidates: list of patch dicts for validate_enrichment_patch
          dropped: list of dropped proposals with reasons
    """
    patch_candidates: List[Dict[str, Any]] = []
    dropped: List[Dict[str, Any]] = []

    patches_raw = parsed.get("patches_raw", [])

    for i, proposal in enumerate(patches_raw):
        if not isinstance(proposal, dict):
            dropped.append({"index": i, "reason": "proposal is not a dict"})
            continue

        bp_id = proposal.get("blueprint_id", "")
        target_file = proposal.get("target_file", "")
        json_path = proposal.get("json_path", "")
        field = proposal.get("field", "")
        value = proposal.get("value", "")

        if not bp_id:
            dropped.append({"index": i, "reason": "missing blueprint_id"})
            continue
        if not target_file:
            dropped.append({"index": i, "reason": "missing target_file"})
            continue
        if not json_path:
            dropped.append({"index": i, "reason": "missing json_path"})
            continue
        if not field:
            dropped.append({"index": i, "reason": "missing field"})
            continue
        if not isinstance(value, str) or not value:
            dropped.append({"index": i, "reason": "missing or non-string value"})
            continue

        # Verify target_file looks like an area file
        if not target_file.startswith("areas/") or not target_file.endswith((".json", "_BU.json")):
            dropped.append({"index": i, "reason": f"target_file not a valid area path: {target_file}"})
            continue

        # Check for forbidden structural fields/paths
        if field in FORBIDDEN_FIELDS:
            dropped.append({"index": i, "reason": f"forbidden field: {field}"})
            continue
        if _has_forbidden_path_pattern(json_path):
            dropped.append({"index": i, "reason": f"forbidden path pattern in: {json_path}"})
            continue

        source_refs = proposal.get("source_refs", [])
        reason = proposal.get("reason", "")
        if not source_refs and not reason:
            dropped.append({"index": i, "reason": "missing source_refs and reason (no justification)"})
            continue

        patch: Dict[str, Any] = {
            "op": "replace",
            "blueprint_id": bp_id,
            "target_file": target_file,
            "json_path": json_path,
            "field": field,
            "value": value,
        }

        if source_refs:
            patch["source_refs"] = source_refs
        if reason:
            patch["reason"] = reason

        for key in ("area_file", "area_id", "location_id", "location_path", "source_excerpt"):
            if key in proposal:
                patch[key] = proposal[key]

        patch_candidates.append(patch)

    return {
        "patch_candidates": patch_candidates,
        "dropped": dropped,
    }


def _validate_and_apply_location_enrichment_patches(
    patch_candidates: List[Dict[str, Any]],
    converter_dropped: List[Dict[str, Any]],
    module_dir: str,
    blueprint: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Validate and apply location enrichment patch candidates.

    Mirrors _validate_and_apply_npc_enrichment_patches with location-
    specific metadata preservation.
    """
    total_candidates = len(patch_candidates)
    converter_dropped_count = len(converter_dropped)

    validator_rejected: List[Dict[str, Any]] = []
    apply_rejected: List[Dict[str, Any]] = []
    valid_patches: List[Dict[str, Any]] = []

    loc_meta_keys = ("source_refs", "reason", "area_file", "area_id",
                     "location_id", "location_path", "source_excerpt")

    for pc in patch_candidates:
        vresult = validate_enrichment_patch(pc, blueprint=blueprint)
        if vresult["valid"]:
            valid_patches.append(pc)
        else:
            entry: Dict[str, Any] = {
                "patch": pc,
                "reason": vresult["reason"],
            }
            for key in loc_meta_keys:
                if key in pc:
                    entry[key] = pc[key]
            validator_rejected.append(entry)

    apply_result = apply_enrichment_patches(valid_patches, module_dir)

    for ar in apply_result.get("rejected", []):
        ar_patch = ar.get("patch", {})
        entry: Dict[str, Any] = {
            "patch": ar_patch,
            "reason": ar.get("reason", ""),
        }
        for key in loc_meta_keys:
            if key in ar_patch:
                entry[key] = ar_patch[key]
        apply_rejected.append(entry)

    applied = []
    for ap in apply_result.get("applied", []):
        ap_patch = ap.get("patch", {})
        entry: Dict[str, Any] = {
            "patch": ap_patch,
            "target_file": ap.get("target_file", ""),
        }
        for key in loc_meta_keys:
            if key in ap_patch:
                entry[key] = ap_patch[key]
        applied.append(entry)

    return {
        "total_candidates": total_candidates,
        "converter_dropped_count": converter_dropped_count,
        "validator_rejected": validator_rejected,
        "apply_rejected": apply_rejected,
        "applied": applied,
        "warnings": apply_result.get("warnings", []),
        "errors": apply_result.get("errors", []),
        "validated_count": len(valid_patches),
        "applied_count": len(applied),
    }


# ---------------------------------------------------------------------------
# NPC enrichment patch validation, application, and diagnostics
# ---------------------------------------------------------------------------

def _validate_and_apply_npc_enrichment_patches(
    patch_candidates: List[Dict[str, Any]],
    converter_dropped: List[Dict[str, Any]],
    module_dir: str,
    blueprint: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Validate and apply NPC enrichment patch candidates.

    Runs candidates through validate_enrichment_patches, applies only
    validator-approved patches via apply_enrichment_patches, and returns
    comprehensive diagnostics preserving metadata.

    Args:
        patch_candidates: List of patch candidate dicts from converter
        converter_dropped: List of converter-dropped proposals
        module_dir: Module directory path for patch application
        blueprint: Optional blueprint for allowlist checks

    Returns:
        Dict with:
          total_candidates: count received from converter
          converter_dropped_count: count dropped during conversion
          validator_rejected: list of validator-rejected patches with metadata
          apply_rejected: list of apply-stage rejected patches with metadata
          applied: list of applied patches with metadata
          warnings: list of warning strings
          errors: list of error dicts
          validated_count: count that passed validation
          applied_count: count actually written to files
    """
    total_candidates = len(patch_candidates)
    converter_dropped_count = len(converter_dropped)

    validator_rejected: List[Dict[str, Any]] = []
    apply_rejected: List[Dict[str, Any]] = []

    valid_patches: List[Dict[str, Any]] = []

    for pc in patch_candidates:
        vresult = validate_enrichment_patch(pc, blueprint=blueprint)
        if vresult["valid"]:
            valid_patches.append(pc)
        else:
            rejected_entry: Dict[str, Any] = {
                "patch": pc,
                "reason": vresult["reason"],
            }
            for key in ("source_refs", "entity_slug", "_scaffold_source_excerpt"):
                if key in pc:
                    rejected_entry[key] = pc[key]
            validator_rejected.append(rejected_entry)

    apply_result = apply_enrichment_patches(valid_patches, module_dir)

    for ar in apply_result.get("rejected", []):
        ar_patch = ar.get("patch", {})
        entry: Dict[str, Any] = {
            "patch": ar_patch,
            "reason": ar.get("reason", ""),
        }
        for key in ("source_refs", "entity_slug", "_scaffold_source_excerpt"):
            if key in ar_patch:
                entry[key] = ar_patch[key]
        apply_rejected.append(entry)

    applied = []
    for ap in apply_result.get("applied", []):
        ap_patch = ap.get("patch", {})
        entry: Dict[str, Any] = {
            "patch": ap_patch,
            "target_file": ap.get("target_file", ""),
        }
        for key in ("source_refs", "reason", "entity_slug", "_scaffold_source_excerpt"):
            if key in ap_patch:
                entry[key] = ap_patch[key]
        applied.append(entry)

    return {
        "total_candidates": total_candidates,
        "converter_dropped_count": converter_dropped_count,
        "validator_rejected": validator_rejected,
        "apply_rejected": apply_rejected,
        "applied": applied,
        "warnings": apply_result.get("warnings", []),
        "errors": apply_result.get("errors", []),
        "validated_count": len(valid_patches),
        "applied_count": len(applied),
    }


def _resolve_pass_status(result: Dict[str, Any]) -> str:
    """Determine status from current pass result."""
    if result.get("errors"):
        return ENRICHMENT_STATUS_DEGRADED
    if result.get("applied"):
        return ENRICHMENT_STATUS_COMPLETE
    return ENRICHMENT_STATUS_NOT_IMPLEMENTED


def _build_pass_telemetry(
    pass_type: str,
    result: Dict[str, Any],
    input_cache_key: str = "",
) -> Dict[str, Any]:
    """Build deterministic pass telemetry payload."""
    applied_list = result.get("applied", [])
    rejected_list = result.get("rejected", [])
    return {
        "pass_type": pass_type,
        "status": _resolve_pass_status(result),
        "provider_call_count": 0,
        "cache_hit_count": 0,
        "cache_miss_count": 0,
        "parse_failure_count": 0,
        "rejected_patch_count": len(rejected_list),
        "applied_patch_count": len(applied_list),
        "input_cache_key": input_cache_key,
    }


def _run_enrichment_pass(
    blueprint: Dict[str, Any],
    module_dir: str,
    pass_type: str,
    npc_enrichment_data: Optional[Dict[str, Any]] = None,
    location_enrichment_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Run a single enrichment pass.

    Each pass:
    1. Reads current module files
    2. Builds an LLM prompt targeting the pass domain
    3. Calls the LLM to generate patch proposals
    4. Validates each patch
    5. Applies validated patches
    6. Returns result summary

    When pass_type is "npc" and npc_enrichment_data is provided (with
    patch_candidates and converter_dropped), the pass runs the full
    validation-application pipeline against the injected data.
    Without injected data, the pass is a no-op (provider not yet called).

    Args:
        blueprint: builder_blueprint.v2 dict
        module_dir: Module directory path
        pass_type: Enrichment domain ("npc", "location", "plot_puzzle_clue",
            "encounter_item", "tone_style", "module_overview", etc.)
        npc_enrichment_data: Optional dict from NPC parser+converter output.
            Expected keys: patch_candidates (list), converter_dropped (list)
        location_enrichment_data: Optional dict from location parser+converter output.
            Expected keys: patch_candidates (list), converter_dropped (list)

    Returns:
        Dict with pass results including applied, rejected, errors, warnings.
    """
    result: Dict[str, Any] = {
        "pass_type": pass_type,
        "applied": [],
        "rejected": [],
        "errors": [],
        "warnings": ["LLM provider orchestration not yet implemented for this pass"],
        "patches_requested": 0,
        "patches_returned": 0,
    }

    if pass_type == "location":
        inputs = _build_location_pass_inputs(blueprint, module_dir)
        result["location_pass_inputs"] = {
            "area_count": inputs.get("area_count", 0),
            "location_count": inputs.get("location_count", 0),
            "excerpt_count": inputs.get("excerpt_count", 0),
            "excerpt_max_chars": inputs.get("excerpt_max_chars", 200),
            "input_cache_key": inputs.get("input_cache_key", ""),
        }

        if location_enrichment_data is not None:
            patch_candidates = location_enrichment_data.get("patch_candidates", [])
            converter_dropped = location_enrichment_data.get("converter_dropped", [])

            if not patch_candidates and not converter_dropped:
                result["errors"].append({
                    "message": "location_enrichment_data provided but has no patch_candidates or converter_dropped",
                })
            else:
                vaa = _validate_and_apply_location_enrichment_patches(
                    patch_candidates, converter_dropped, module_dir,
                    blueprint=blueprint,
                )
                result["applied"] = vaa["applied"]
                result["rejected"] = (
                    vaa["validator_rejected"] + vaa["apply_rejected"]
                )
                result["errors"] = vaa["errors"]
                result["warnings"] = vaa["warnings"]
                result["patches_requested"] = vaa["total_candidates"]
                result["patches_returned"] = vaa["applied_count"] + len(vaa["validator_rejected"])
                result["location_validation_diagnostics"] = {
                    "total_candidates": vaa["total_candidates"],
                    "converter_dropped_count": vaa["converter_dropped_count"],
                    "validated_count": vaa["validated_count"],
                    "applied_count": vaa["applied_count"],
                    "validator_rejected_count": len(vaa["validator_rejected"]),
                    "apply_rejected_count": len(vaa["apply_rejected"]),
                }

    if pass_type == "plot_puzzle_clue":
        inputs = _build_plot_puzzle_clue_pass_inputs(blueprint, module_dir)
        result["plot_puzzle_clue_pass_inputs"] = {
            "plot_point_count": inputs.get("plot_point_count", 0),
            "puzzle_clue_location_count": inputs.get("puzzle_clue_location_count", 0),
            "plot_excerpt_count": inputs.get("plot_excerpt_count", 0),
            "puzzle_clue_excerpt_count": inputs.get("puzzle_clue_excerpt_count", 0),
            "excerpt_max_chars": inputs.get("excerpt_max_chars", 200),
            "input_cache_key": inputs.get("input_cache_key", ""),
        }

    if pass_type == "encounter_item":
        inputs = _build_encounter_item_pass_inputs(blueprint, module_dir)
        result["encounter_item_pass_inputs"] = {
            "encounter_location_count": inputs.get("encounter_location_count", 0),
            "item_location_count": inputs.get("item_location_count", 0),
            "encounter_excerpt_count": inputs.get("encounter_excerpt_count", 0),
            "item_excerpt_count": inputs.get("item_excerpt_count", 0),
            "excerpt_max_chars": inputs.get("excerpt_max_chars", 200),
            "input_cache_key": inputs.get("input_cache_key", ""),
        }

    if pass_type == "tone_style":
        inputs = _build_tone_style_pass_inputs(blueprint, module_dir)
        result["tone_style_pass_inputs"] = {
            "source_count": inputs.get("source_count", 0),
            "excerpt_count": inputs.get("excerpt_count", 0),
            "has_guidance": inputs.get("has_guidance", False),
            "excerpt_max_chars": inputs.get("excerpt_max_chars", 200),
            "input_cache_key": inputs.get("input_cache_key", ""),
        }

    if pass_type == "npc":
        inputs = _build_npc_pass_inputs(blueprint, module_dir)
        result["npc_pass_inputs"] = {
            "npc_target_count": len(inputs.get("npc_targets", [])),
            "rejected_narrative_count": len(inputs.get("rejected_narratives", [])),
            "excerpt_count": inputs.get("excerpt_count", 0),
            "has_triage_data": inputs.get("has_triage_data", False),
            "source_artifact": inputs.get("source_artifact", "module_context"),
            "input_cache_key": inputs.get("input_cache_key", ""),
        }

        if npc_enrichment_data is not None:
            patch_candidates = npc_enrichment_data.get("patch_candidates", [])
            converter_dropped = npc_enrichment_data.get("converter_dropped", [])

            if not patch_candidates and not converter_dropped:
                result["errors"].append({
                    "message": "npc_enrichment_data provided but has no patch_candidates or converter_dropped",
                })
            else:
                vaa = _validate_and_apply_npc_enrichment_patches(
                    patch_candidates, converter_dropped, module_dir,
                    blueprint=blueprint,
                )
                result["applied"] = vaa["applied"]
                result["rejected"] = (
                    vaa["validator_rejected"] + vaa["apply_rejected"]
                )
                result["errors"] = vaa["errors"]
                result["warnings"] = vaa["warnings"]
                result["patches_requested"] = vaa["total_candidates"]
                result["patches_returned"] = vaa["applied_count"] + len(vaa["validator_rejected"])
                result["npc_validation_diagnostics"] = {
                    "total_candidates": vaa["total_candidates"],
                    "converter_dropped_count": vaa["converter_dropped_count"],
                    "validated_count": vaa["validated_count"],
                    "applied_count": vaa["applied_count"],
                    "validator_rejected_count": len(vaa["validator_rejected"]),
                    "apply_rejected_count": len(vaa["apply_rejected"]),
                }

    # Build telemetry from current result
    cache_key = ""
    for key in ("npc_pass_inputs", "location_pass_inputs",
                 "plot_puzzle_clue_pass_inputs", "encounter_item_pass_inputs",
                 "tone_style_pass_inputs"):
        sub = result.get(key, {})
        if isinstance(sub, dict) and sub.get("input_cache_key"):
            cache_key = sub["input_cache_key"]
            break

    result["pass_telemetry"] = _build_pass_telemetry(
        pass_type, result, input_cache_key=cache_key,
    )

    return result


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


def _extract_pass_meta(pass_result: Dict[str, Any]) -> Dict[str, Any]:
    """Extract compact pass metadata from a single pass result.

    Returns minimal metadata without raw excerpts or pass input targets.
    Fail-open: missing keys produce empty strings or zeroes.
    """
    telemetry = pass_result.get("pass_telemetry", {}) or {}
    cache_key = ""
    for summary_key in ("npc_pass_inputs", "location_pass_inputs",
                         "plot_puzzle_clue_pass_inputs", "encounter_item_pass_inputs",
                         "tone_style_pass_inputs"):
        sub = pass_result.get(summary_key, {})
        if isinstance(sub, dict) and sub.get("input_cache_key"):
            cache_key = sub["input_cache_key"]
            break
    if not cache_key:
        cache_key = telemetry.get("input_cache_key", "")

    return {
        "pass_type": pass_result.get("pass_type", ""),
        "status": telemetry.get("status", ""),
        "input_cache_key": cache_key,
        "applied_count": telemetry.get("applied_patch_count", 0),
        "rejected_count": telemetry.get("rejected_patch_count", 0),
    }


def build_enrichment_report(
    pipeline_result: Dict[str, Any],
    blueprint: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build enrichment_report.json from pipeline result.

    Pass metadata is additive and derived from pass results without
    embedding large raw excerpts. Legacy pipeline_result shapes
    missing pass_telemetry or input_cache_keys produce empty metadata.
    """
    from datetime import datetime, timezone

    passes = pipeline_result.get("passes", []) or []
    pass_metadata: List[Dict[str, Any]] = []
    pass_telemetry: List[Dict[str, Any]] = []
    input_cache_keys: Dict[str, str] = {}

    for p in passes:
        if not isinstance(p, dict):
            pass_metadata.append({"pass_type": "", "status": "",
                                  "input_cache_key": ""})
            pass_telemetry.append({})
            continue
        pass_metadata.append(_extract_pass_meta(p))
        pt = p.get("pass_telemetry", {}) or {}
        pass_telemetry.append(dict(pt))
        ptype = p.get("pass_type", "")
        pkey = pass_metadata[-1].get("input_cache_key", "")
        if ptype and pkey:
            input_cache_keys[ptype] = pkey

    return {
        "enrichment_report_version": ENRICHMENT_REPORT_VERSION,
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "status": pipeline_result.get("status", ENRICHMENT_STATUS_SKIPPED),
        "reason": pipeline_result.get("reason", ""),
        "applied_count": len(pipeline_result.get("applied", [])),
        "rejected_count": len(pipeline_result.get("rejected", [])),
        "error_count": len(pipeline_result.get("errors", [])),
        "warning_count": len(pipeline_result.get("warnings", [])),
        "pass_count": len(passes),
        "applied": pipeline_result.get("applied", []),
        "rejected": pipeline_result.get("rejected", []),
        "errors": pipeline_result.get("errors", []),
        "warnings": pipeline_result.get("warnings", []),
        "pass_metadata": pass_metadata,
        "pass_telemetry": pass_telemetry,
        "input_cache_keys": input_cache_keys,
    }
