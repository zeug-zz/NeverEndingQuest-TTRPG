# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Utility - Toolkit Final Blocker Classifier
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

This software is free for non-commercial and educational use.
Commercial competing use is prohibited for 2 years from release.
See LICENSE file for full terms.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional


# Fatal blocker detection patterns (message-based)
FATAL_MESSAGE_KEYWORDS = [
    "invalid json",
    "schema validation",
    "missing required artifact",
    "missing canonical artifact",
    "critical file missing",
    "unrecoverable topology",
    "broken topology",
    "no valid topology",
    # Full-module validation report structural failure patterns
    "not cardinally adjacent",
    "expected monsters/",
    "is not one of",
]

# Fatal blocker categories (category-based)
FATAL_CATEGORIES = [
    "structural",
    "schema",
    "topology",
    # Full-module validation report categories representing structural defects
    "reference_integrity",
    "spatial_contract",
    "party",
]

# Editorial blocker categories (source-fidelity mismatches)
EDITORIAL_CATEGORIES = [
    "location",
    "npc",
    "puzzle",
    "clue",
    "item",
    "encounter",
    "plot_beat",
]

# Source-fidelity/generic categories (for "not found in module" fallback)
SOURCE_FIDELITY_CATEGORIES = [
    "source_fidelity",
    "source-fidelity",
    "build_fidelity",
    "build-fidelity",
    "fidelity",
]

# Editorial blocker message patterns (recognizable required-source phrases)
EDITORIAL_MESSAGE_PATTERNS = [
    "required location",
    "required npc",
    "required puzzle",
    "required clue",
    "required item",
    "required encounter",
    "required plot beat",
]


def _normalize_blocker_evidence(blocker: Dict[str, Any], classification: str) -> Dict[str, Any]:
    """Build a normalized blocker evidence dict from raw blocker data.
    
    Preserves all diagnostic fields from the original blocker dict
    while adding the classification type.
    
    Args:
        blocker: Raw blocker dict from build-fidelity report
        classification: Classification type ("fatal", "editorial", "warning")
        
    Returns:
        Normalized blocker dict with preserved evidence fields
    """
    result = {
        "type": classification,
        "raw": blocker,
    }
    
    # Core identity fields
    for field in ("message", "category", "source_atom_id", "atom_id"):
        value = blocker.get(field)
        if value is not None:
            result[field] = value
    
    # Source reference fields
    for field in ("source_ref", "source_refs", "ref", "refs"):
        value = blocker.get(field)
        if value is not None:
            result[field] = value
    
    # Diagnostic detail fields
    for field in ("severity", "reason", "expected", "actual"):
        value = blocker.get(field)
        if value is not None:
            result[field] = value
    
    result.setdefault("message", "")
    result.setdefault("category", "")
    
    return result


def _is_fatal_blocker(message: str, category: str) -> bool:
    """Determine if a blocker is fatal based on message or category.
    
    Args:
        message: Blocker message text
        category: Blocker category
        
    Returns:
        True if blocker is fatal, False otherwise
    """
    message_lower = message.lower()
    
    # Check message keywords
    for keyword in FATAL_MESSAGE_KEYWORDS:
        if keyword in message_lower:
            return True
    
    # Check category
    if category in FATAL_CATEGORIES:
        return True
    
    return False


def _is_editorial_blocker(message: str, category: str) -> bool:
    """Determine if a blocker is editorial based on message or category.
    
    Editorial blockers are source-fidelity mismatches that can be reconciled.
    This function checks both category and message patterns with three conditions:
    1. category is in EDITORIAL_CATEGORIES, OR
    2. message contains a recognizable required-source phrase, OR
    3. category is a known source-fidelity category AND message contains "not found in module"
    
    Args:
        message: Blocker message text
        category: Blocker category
        
    Returns:
        True if blocker is editorial, False otherwise
    """
    # Check category first (most reliable)
    if category in EDITORIAL_CATEGORIES:
        return True
    
    # Check message patterns (recognizable required-source phrases)
    message_lower = message.lower()
    for pattern in EDITORIAL_MESSAGE_PATTERNS:
        if pattern in message_lower:
            return True
    
    # Check source-fidelity category with "not found in module" pattern
    if category in SOURCE_FIDELITY_CATEGORIES and "not found in module" in message_lower:
        return True
    
    return False


def classify_final_build_blockers(
    build_fidelity_report: Any,
    module_dir: Optional[Path] = None,
    source_graph: Optional[Dict[str, Any]] = None,
    source_manifest: Optional[Dict[str, Any]] = None,
    builder_blueprint_report: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Classify build-fidelity blockers into fatal/editorial categories.
    
    This is a provider-free classifier that determines whether blockers
    are fatal (block build) or editorial (allow final reconciliation).
    
    Args:
        build_fidelity_report: Build fidelity report dict with blockers
        module_dir: Optional module directory path
        source_graph: Optional source graph dict
        source_manifest: Optional source manifest dict
        builder_blueprint_report: Optional builder blueprint report dict
    
    Returns:
        Dict with classification results:
        {
            "status": "no_blockers" | "fatal" | "editorial" | "mixed" | "unknown",
            "fatal_blockers": [...],
            "editorial_blockers": [...],
            "warnings": [...],
            "can_attempt_final_reconciliation": bool,
            "fatal_count": int,
            "editorial_count": int,
            "original_refusal_reason": str,
            "report_paths": {},
        }
    """
    # Defensive parsing: handle None or non-dict input
    if build_fidelity_report is None or not isinstance(build_fidelity_report, dict):
        return {
            "status": "unknown",
            "fatal_blockers": [],
            "editorial_blockers": [],
            "warnings": [{
                "type": "invalid_input",
                "message": "build_fidelity_report is None or not a dict",
                "category": "input_validation",
            }],
            "can_attempt_final_reconciliation": False,
            "fatal_count": 0,
            "editorial_count": 0,
            "original_refusal_reason": "",
            "report_paths": {},
        }
    
    # Extract blockers and refusal reason
    blockers = build_fidelity_report.get("blockers", [])
    original_refusal_reason = build_fidelity_report.get("refusal_reason", "")
    
    # Extract report paths passthrough
    report_paths = _extract_report_paths(build_fidelity_report)
    
    # Check for missing module directory FIRST (fatal regardless of report status)
    if module_dir is not None and not module_dir.exists():
        fatal_blocker = {
            "type": "missing_module_directory",
            "message": f"Module directory does not exist: {module_dir}",
            "category": "structural",
            "source_atom_id": None,
            "raw": {"module_dir": str(module_dir)},
        }
        return {
            "status": "fatal",
            "fatal_blockers": [fatal_blocker],
            "editorial_blockers": [],
            "warnings": [],
            "can_attempt_final_reconciliation": False,
            "fatal_count": 1,
            "editorial_count": 0,
            "original_refusal_reason": original_refusal_reason,
            "report_paths": report_paths,
        }
    
    # Check if report indicates success
    status = build_fidelity_report.get("status", "")
    can_continue = build_fidelity_report.get("can_continue", False)
    
    # If status is pass/success or no blockers, return no_blockers
    if status in ("pass", "success") or (not blockers and can_continue):
        return {
            "status": "no_blockers",
            "fatal_blockers": [],
            "editorial_blockers": [],
            "warnings": [],
            "can_attempt_final_reconciliation": False,
            "fatal_count": 0,
            "editorial_count": 0,
            "original_refusal_reason": "",
            "report_paths": report_paths,
        }
    
    # Classify each blocker
    fatal_blockers = []
    editorial_blockers = []
    warnings = []
    
    for blocker in blockers:
        if not isinstance(blocker, dict):
            warnings.append({
                "type": "invalid_blocker",
                "message": f"Blocker is not a dict: {blocker}",
                "category": "input_validation",
            })
            continue
        
        message = blocker.get("message", "")
        category = blocker.get("category", "")
        
        # Check if fatal using helper (fatal takes priority)
        if _is_fatal_blocker(message, category):
            fatal_blockers.append(_normalize_blocker_evidence(blocker, "fatal"))
        elif _is_editorial_blocker(message, category):
            # Editorial blocker (source-fidelity mismatch)
            editorial_blockers.append(_normalize_blocker_evidence(blocker, "editorial"))
        else:
            # Unknown blocker
            warnings.append(_normalize_blocker_evidence(blocker, "unknown"))
    
    # Determine status
    fatal_count = len(fatal_blockers)
    editorial_count = len(editorial_blockers)
    warning_count = len(warnings)
    
    if fatal_count > 0 and editorial_count > 0:
        status = "mixed"
        can_attempt_final_reconciliation = False
    elif fatal_count > 0:
        status = "fatal"
        can_attempt_final_reconciliation = False
    elif editorial_count > 0:
        status = "editorial"
        can_attempt_final_reconciliation = True
    elif warning_count > 0:
        status = "unknown"
        can_attempt_final_reconciliation = False
    else:
        status = "no_blockers"
        can_attempt_final_reconciliation = False
    
    return {
        "status": status,
        "fatal_blockers": fatal_blockers,
        "editorial_blockers": editorial_blockers,
        "warnings": warnings,
        "can_attempt_final_reconciliation": can_attempt_final_reconciliation,
        "fatal_count": fatal_count,
        "editorial_count": editorial_count,
        "original_refusal_reason": original_refusal_reason,
        "report_paths": report_paths,
    }


def _extract_report_paths(report: Dict[str, Any]) -> Dict[str, Any]:
    """Extract report path metadata from build fidelity report.
    
    Checks for common report path keys and returns a dict with
    any found paths. Returns empty dict if no paths present.
    """
    paths = {}
    path_keys = [
        "report_path",
        "rollup_path",
        "source_fidelity_report_path",
        "build_fidelity_report_path",
    ]
    
    for key in path_keys:
        value = report.get(key)
        if value is not None:
            paths[key] = value
    
    # Also check for nested report_paths dict
    nested_paths = report.get("report_paths")
    if isinstance(nested_paths, dict):
        paths.update(nested_paths)
    
    return paths
