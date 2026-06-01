# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Utility - Critical Narrative Repair
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

Deterministic, fail-closed repair orchestration for critical narrative omissions.
Consumes a Step 2 agent-run directory, builds a Builder LLM prompt, parses and
validates the structured repair plan, and applies validated artifacts safely.

This software is free for non-commercial and educational use.
Commercial competing use is prohibited for 2 years from release.
See LICENSE file for full terms.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from utils.file_operations import safe_write_json
from utils.enhanced_logger import error

_FORBIDDEN_RELATIVE_PATHS = frozenset({
    "MODULE_SUMMARY.md",
    "accurate_ingest_benchmark_report.json",
    "toolkit_build_report.json",
    "source_fidelity_report.json",
    "validation_report.json",
    "seed_source_report.json",
})

_FORBIDDEN_PATH_PREFIXES = frozenset({
    "data/benchmarks/",
    "data/agent_runs/",
    "openspec/",
    "Local_Docs/",
})

_REQUIRED_RUN_FILES = frozenset({
    "run.json",
    "critical_evidence.json",
    "source_excerpts.json",
    "builder_repair_brief.md",
})

_REQUIRED_OMISSION_NAMES = frozenset({"Kobe", "skull_riddle", "flooding_room"})
_REQUIRED_SOURCE_EXCERPT_KEYS = frozenset({"kobe", "skull_riddle", "flooding_room"})

_ALLOWED_OPERATIONS = frozenset({"replace_json_file", "patch_json_object"})

_PROTECTED_TOP_LEVEL_KEYS = frozenset({
    "npcs",
    "areas",
    "locations",
    "puzzles",
    "plotPoints",
    "plot_points",
    "semantic_authority",
    "source_contract",
})


def load_repair_run(run_dir: Path) -> Optional[Dict[str, Any]]:
    """Load agent-run artifacts from a directory.

    Returns a dict with keys: run, critical_evidence, source_excerpts,
    builder_repair_brief, run_dir. Returns None if any required file
    is missing or malformed.
    """
    run_data: Dict[str, Any] = {"run_dir": str(run_dir)}

    for filename in _REQUIRED_RUN_FILES:
        fpath = run_dir / filename
        if not fpath.exists() or not fpath.is_file():
            error(f"REPAIR: Missing required run file: {fpath}",
                  category="narrative_repair")
            return None
        try:
            raw = fpath.read_text(encoding="utf-8")
            if filename.endswith(".json"):
                parsed = json.loads(raw)
            else:
                parsed = raw  # markdown
            key = filename.replace(".json", "").replace(".md", "")
            # Normalize key names
            key_map = {
                "builder_repair_brief": "builder_repair_brief",
                "critical_evidence": "critical_evidence",
                "source_excerpts": "source_excerpts",
                "run": "run",
            }
            run_data[key_map.get(key, key)] = parsed
        except Exception as exc:
            error(f"REPAIR: Failed to parse {fpath}: {exc}",
                  category="narrative_repair")
            return None

    return run_data


def build_builder_repair_prompt(run_data: Dict[str, Any]) -> str:
    """Build a structured Builder LLM prompt from repair run data.

    The prompt is assembled from the builder_repair_brief markdown.
    It instructs the LLM to return structured JSON only.
    """
    brief = run_data.get("builder_repair_brief", "")

    if isinstance(brief, str):
        prompt = brief + "\n\n"
    else:
        return ""

    prompt += (
        "## Builder Instruction\n\n"
        "You are a narrative repair Builder.  Using the Source-Lock Constraints, "
        "Source Excerpts, Required Repair Targets, and Acceptance Checks above, "
        "synthesize the missing critical narrative content into structured module "
        "JSON updates.\n\n"
        "Return ONLY a single JSON object with the following structure:\n\n"
        "```json\n"
        "{\n"
        '  "repair_plan_version": "critical_narrative_repair.v1",\n'
        '  "module_slug": "<module-slug>",\n'
        '  "omissions_addressed": ["Kobe", "skull_riddle", "flooding_room"],\n'
        '  "artifact_updates": [\n'
        "    {\n"
        '      "relative_path": "module_context.json",\n'
        '      "operation": "replace_json_file",\n'
        '      "json": { <complete replacement object> },\n'
        '      "source_excerpt_keys": ["kobe"],\n'
        '      "rationale": "<source-faithful rationale text>"\n'
        "    }\n"
        "  ]\n"
        "}\n"
        "```\n\n"
        "Rules:\n"
        "- Use `replace_json_file` to provide complete replacement objects.\n"
        "- Use `patch_json_object` for targeted field inserts/merges.\n"
        "- Include ALL required top-level keys for `replace_json_file`.\n"
        "- When patching plot points or area locations, include complete parent records.\n"
        "- Map each update to the source excerpt keys that authorize it.\n"
        "- Do NOT include freeform text outside the JSON response.\n"
        "- Do NOT invent new characters, puzzles, or locations.\n"
        "- Follow all Source-Lock Constraints and Do Not Use rules in the brief.\n"
    )
    return prompt


def parse_builder_repair_response(text: str) -> Optional[Dict[str, Any]]:
    """Parse a Builder LLM response into a structured repair plan.

    Extracts JSON from the response, handling markdown code fences.
    Returns None if the response is not valid JSON.
    """
    if not text or not isinstance(text, str):
        return None

    # Try direct JSON parse
    text_stripped = text.strip()
    try:
        return json.loads(text_stripped)
    except json.JSONDecodeError:
        pass

    # Try extracting from ```json ... ``` fence
    import re
    fence_match = re.search(r'```(?:json)?\s*\n(.*?)\n\s*```', text, re.DOTALL)
    if fence_match:
        try:
            return json.loads(fence_match.group(1).strip())
        except json.JSONDecodeError:
            pass

    return None


def validate_repair_plan(
    plan: Dict[str, Any],
    module_dir: Path,
) -> Dict[str, Any]:
    """Validate a repair plan dictionary.

    Returns a dict with `valid` (bool) and `errors` (list of strings).
    """
    errors: List[str] = []

    if not isinstance(plan, dict):
        errors.append("Repair plan is not a dictionary")
        return {"valid": False, "errors": errors}

    # Check version
    version = plan.get("repair_plan_version")
    if version != "critical_narrative_repair.v1":
        errors.append(f"Unsupported repair_plan_version: {version}")

    # Check slug
    slug = plan.get("module_slug", "")
    if not isinstance(slug, str) or not slug:
        errors.append("module_slug is missing or empty")
    elif slug != module_dir.name:
        errors.append(f"module_slug does not match target module: {slug} != {module_dir.name}")

    # Check omissions addressed
    omissions = plan.get("omissions_addressed", [])
    if not isinstance(omissions, list):
        errors.append("omissions_addressed is not a list")
    else:
        missing = _REQUIRED_OMISSION_NAMES - set(omissions)
        if missing:
            errors.append(f"Required omissions not addressed: {sorted(missing)}")

    # Validate each artifact update
    updates = plan.get("artifact_updates", [])
    if not isinstance(updates, list) or not updates:
        errors.append("artifact_updates is empty or not a list")
    else:
        source_key_coverage: Set[str] = set()
        for i, update in enumerate(updates):
            update_errors = _validate_artifact_update(update, i, module_dir)
            errors.extend(update_errors)
            if isinstance(update, dict):
                keys = update.get("source_excerpt_keys", [])
                if isinstance(keys, list):
                    source_key_coverage.update(k for k in keys if isinstance(k, str))
        missing_keys = _REQUIRED_SOURCE_EXCERPT_KEYS - source_key_coverage
        if missing_keys:
            errors.append(f"Required source excerpts not referenced: {sorted(missing_keys)}")

    return {"valid": len(errors) == 0, "errors": errors}


def _validate_protected_content_preserved(
    existing: Dict[str, Any],
    replacement: Dict[str, Any],
    prefix: str,
) -> List[str]:
    """Verify replacement payload does not remove protected keys.

    For dict values, replacement keys must be a superset of existing keys.
    For list values, replacement length must be >= existing length.
    """
    errors: List[str] = []
    for key in _PROTECTED_TOP_LEVEL_KEYS:
        existing_val = existing.get(key)
        replacement_val = replacement.get(key)
        if existing_val is None:
            continue  # nothing to protect

        if replacement_val is None:
            errors.append(f"{prefix}: replace_json_file would remove protected key {key}")
            continue

        if isinstance(existing_val, dict) and isinstance(replacement_val, dict):
            missing = set(existing_val.keys()) - set(replacement_val.keys())
            if missing:
                sorted_missing = sorted(missing)
                for item_key in sorted_missing[:5]:
                    errors.append(
                        f"{prefix}: would remove protected key "
                        f"{key}.{item_key}"
                    )
                if len(sorted_missing) > 5:
                    errors.append(
                        f"{prefix}: ...and {len(sorted_missing) - 5} more "
                        f"removed protected keys in {key}"
                    )
        elif isinstance(existing_val, dict):
            errors.append(
                f"{prefix}: would change protected dict {key} "
                f"to {type(replacement_val).__name__}"
            )
        elif isinstance(existing_val, list) and isinstance(replacement_val, list):
            if len(replacement_val) < len(existing_val):
                errors.append(
                    f"{prefix}: would shrink protected list "
                    f"{key} ({len(existing_val)} -> {len(replacement_val)})"
                )
        elif isinstance(existing_val, list):
            errors.append(
                f"{prefix}: would change protected list {key} "
                f"to {type(replacement_val).__name__}"
            )
    return errors


def _validate_artifact_update(
    update: Dict[str, Any],
    index: int,
    module_dir: Path,
) -> List[str]:
    """Validate a single artifact_update entry."""
    errors: List[str] = []
    prefix = f"artifact_updates[{index}]"

    if not isinstance(update, dict):
        errors.append(f"{prefix}: not a dictionary")
        return errors

    # relative_path
    rel_path = update.get("relative_path", "")
    if not isinstance(rel_path, str) or not rel_path:
        errors.append(f"{prefix}: missing relative_path")
    else:
        # Path traversal check
        if ".." in rel_path or rel_path.startswith("/"):
            errors.append(f"{prefix}: relative_path contains traversal: {rel_path}")
        # Forbidden path checks
        if rel_path in _FORBIDDEN_RELATIVE_PATHS:
            errors.append(f"{prefix}: forbidden relative_path: {rel_path}")
        if any(rel_path.startswith(p) for p in _FORBIDDEN_PATH_PREFIXES):
            errors.append(f"{prefix}: forbidden path prefix: {rel_path}")
        if not rel_path.endswith(".json"):
            errors.append(f"{prefix}: relative_path must target a JSON artifact: {rel_path}")
        # Must be within module directory
        resolved = (module_dir / rel_path).resolve()
        module_resolved = module_dir.resolve()
        if not str(resolved).startswith(str(module_resolved)):
            errors.append(f"{prefix}: path not within module dir: {rel_path}")
        # Check if JSON key exists
        if "json" not in update:
            errors.append(f"{prefix}: missing json payload")

    # operation
    operation = update.get("operation", "")
    if operation not in _ALLOWED_OPERATIONS:
        errors.append(f"{prefix}: invalid operation '{operation}'")

    # json payload
    json_payload = update.get("json")
    if json_payload is None:
        errors.append(f"{prefix}: json is None")
    elif not isinstance(json_payload, dict):
        errors.append(f"{prefix}: json is not a dict")

    # Protected content removal guard for replace_json_file
    if (operation == "replace_json_file"
            and isinstance(json_payload, dict)
            and isinstance(rel_path, str)
            and rel_path):
        target_path = module_dir / rel_path
        existing = _load_json_safe(target_path)
        if existing is not None:
            errors.extend(
                _validate_protected_content_preserved(existing, json_payload, prefix)
            )
    elif (operation == "patch_json_object"
            and isinstance(json_payload, dict)
            and isinstance(rel_path, str)
            and rel_path):
        target_path = module_dir / rel_path
        existing = _load_json_safe(target_path)
        if existing is not None:
            merged = _deep_merge(existing, json_payload)
            errors.extend(
                _validate_protected_content_preserved(existing, merged, prefix)
            )

    # source_excerpt_keys
    keys = update.get("source_excerpt_keys", [])
    if not isinstance(keys, list):
        errors.append(f"{prefix}: source_excerpt_keys not a list")
    elif not keys:
        errors.append(f"{prefix}: source_excerpt_keys is empty")
    else:
        unknown_keys = [
            key for key in keys
            if not isinstance(key, str) or key not in _REQUIRED_SOURCE_EXCERPT_KEYS
        ]
        if unknown_keys:
            errors.append(f"{prefix}: unknown source_excerpt_keys: {unknown_keys}")

    # rationale
    rationale = update.get("rationale", "")
    if not isinstance(rationale, str) or not rationale.strip():
        errors.append(f"{prefix}: rationale is empty")

    return errors


def apply_repair_plan(
    plan: Dict[str, Any],
    module_dir: Path,
    apply: bool = False,
) -> Dict[str, Any]:
    """Apply a validated repair plan to module artifacts.

    When apply=False, returns a dry-run report.
    When apply=True, writes files using safe JSON write patterns.

    Returns a dict suitable for builder_repair_result.json.
    """
    result: Dict[str, Any] = {
        "status": "dry_run_ready" if not apply else "applied",
        "module_slug": plan.get("module_slug", ""),
        "omissions_addressed": plan.get("omissions_addressed", []),
        "files_proposed": [],
        "files_written": [],
        "validation_errors": [],
        "write_errors": [],
    }

    # Pre-validate
    validation = validate_repair_plan(plan, module_dir)
    if not validation["valid"]:
        result["status"] = "failed"
        result["validation_errors"] = validation["errors"]
        if apply:
            result["status"] = "failed"
        return result

    updates = plan.get("artifact_updates", [])
    for update in updates:
        rel_path = update.get("relative_path", "")
        operation = update.get("operation", "")
        json_payload = update.get("json")

        target_path = module_dir / rel_path
        result["files_proposed"].append(str(target_path))

        if not apply:
            continue

        try:
            if operation == "replace_json_file":
                if not safe_write_json(str(target_path), json_payload):
                    result["write_errors"].append(f"{rel_path}: safe_write_json returned false")
                    continue
            elif operation == "patch_json_object":
                # Load existing, merge, write back
                existing = _load_json_safe(target_path)
                if existing is None:
                    result["write_errors"].append(
                        f"{rel_path}: cannot load existing for patch"
                    )
                    continue
                merged = _deep_merge(existing, json_payload)
                if not safe_write_json(str(target_path), merged):
                    result["write_errors"].append(f"{rel_path}: safe_write_json returned false")
                    continue
            result["files_written"].append(str(target_path))
        except Exception as exc:
            error(f"REPAIR: Failed to write {target_path}: {exc}",
                  category="narrative_repair")
            result["write_errors"].append(f"{rel_path}: {exc}")

    if apply and not result["write_errors"]:
        result["status"] = "applied"
    elif apply and result["write_errors"]:
        result["status"] = "failed"

    # Next verification commands
    slug = plan.get("module_slug", "")
    result["next_verification_commands"] = [
        f".venv/bin/python scripts/check_critical_narrative_evidence.py --module {slug} --json",
        f".venv/bin/python scripts/benchmark_accurate_ingest.py --module {slug} --json",
        f".venv/bin/python core/validation/validate_module_files.py --module {slug}",
    ]

    return result


def write_builder_repair_result(run_dir: Path, result: Dict[str, Any]) -> bool:
    """Write builder_repair_result.json into the agent-run directory."""
    try:
        fpath = run_dir / "builder_repair_result.json"
        raw = json.dumps(result, indent=2, ensure_ascii=False)
        run_dir.mkdir(parents=True, exist_ok=True)
        tmp = fpath.with_suffix(".json.tmp")
        tmp.write_text(raw, encoding="utf-8")
        tmp.replace(fpath)
        return True
    except Exception as exc:
        error(f"REPAIR: Failed to write result: {exc}",
              category="narrative_repair")
        return False


def _load_json_safe(path: Path) -> Optional[Dict[str, Any]]:
    """Load JSON safely, returning None on failure."""
    try:
        if path.exists() and path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return None


def _deep_merge(base: Dict[str, Any], overlay: Dict[str, Any]) -> Dict[str, Any]:
    """Deep merge overlay dict into base dict recursively."""
    result = dict(base)
    for key, val in overlay.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result
