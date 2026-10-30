# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Combat Capture Sandbox Seeder
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

This software is free for non-commercial and educational use.
Commercial competing use is prohibited for 2 years from release.
See LICENSE file for full terms.

ARCHITECTURE ROLE: Test Tooling - Scripted Combat Capture Ensemble

Creates a lean, real copy of the runtime at tmp/combat_capture/ so the
scripted combat capture can run with combat tracing enabled without touching
the installed tree. The sandbox is gitignored and is rebuilt from scratch on
every --prepare.

Isolation contract:
- Every copy and write is asserted to stay under tmp/combat_capture/.
- The installed tree is never written; sentinel hashes are compared before
  and after --prepare.
- The sandbox runs with the main venv interpreter and cwd inside the sandbox
  so utils.repo_paths.repository_root() resolves to the sandbox copy.

Provider-free and deterministic: no network calls, no provider requests, and
no dependence on wall-clock time.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS_DIR = Path(__file__).resolve().parent
for _bootstrap_path in (_PROJECT_ROOT, _SCRIPTS_DIR):
    if str(_bootstrap_path) not in sys.path:
        sys.path.insert(0, str(_bootstrap_path))

# The fixture payload builders are the canonical fixed roster/encounter shapes.
# Reuse them by import; the fixtures module is intentionally never modified.
import combat_latency_fixtures as capture_fixtures  # noqa: E402
from scripts import capture_evidence  # noqa: E402
from utils.file_operations import safe_write_json  # noqa: E402


PROJECT_ROOT = _PROJECT_ROOT
SANDBOX_ROOT = PROJECT_ROOT / "tmp" / "combat_capture"
SANDBOX_DISPLAY = "tmp/combat_capture"
SANDBOX_PORT = 8360
SANDBOX_PORT_LITERAL = "WEB_PORT = %d" % SANDBOX_PORT
TRACE_GATE_LITERAL = "ENABLE_COMBAT_TURN_TRACE = True"
RESOLVER_GATE_LITERAL = "DETERMINISTIC_ENEMY_RESOLUTION_ENABLED = True"
TACTICAL_GATE_LITERAL = "COMBAT_TACTICAL_BRAIN_ENABLED = True"
ALLY_CONTROLLER_GATE_LITERAL = "COMBAT_ALLY_CONTROLLER_ENABLED = True"
ALLY_PREFETCH_GATE_LITERAL = "COMBAT_ALLY_PREFETCH_ENABLED = True"
MODULE_DIR_NAME = "Capture_Arena"
PARTY_SIZE_FOUR = 4
PARTY_SIZE_ONE = 1
SEED_TIMESTAMP = "2026-01-01T00:00:00"
DEFAULT_TRACE_DISPLAY = "debug/combat_turn_trace.jsonl"

_CODE_FILES = (
    "main.py",
    "run_web.py",
    "model_config.py",
    "config.py",
    "config_template.py",
    "debug_config.py",
    "VERSION",
    "dm_logo.png",
)
_REQUIRED_CODE_FILES = ("main.py", "run_web.py", "model_config.py", "config.py")
_CODE_DIRS = (
    "core",
    "utils",
    "updates",
    "web",
    "prompts",
    "schemas",
    "scripts",
    "templates",
    "icons",
)
_REQUIRED_CODE_DIRS = ("core", "utils", "updates", "web", "prompts", "schemas", "scripts")
_DATA_DIRS = ("data/bestiary", "data/styles")
_DATA_FILES = (
    "data/spell_repository.json",
    "data/active_pack.json",
    "data/style_templates.json",
)
_COMMON_IGNORES = ("__pycache__", "*.pyc", "*.pyo", ".pytest_cache", ".DS_Store")
_WEB_IGNORES = ("monsters_backup", "videos", "*_video.mp4")
_SCRIPTS_IGNORES = ("tmp", "test_*.py")
_SANDBOX_DIRS = (
    "characters",
    "debug",
    "combat_logs",
    "save_games",
    "modules/campaign_archives",
    "modules/conversation_history",
    "modules/campaign_summaries",
    "modules/backups",
    "modules/logs",
    "modules/encounters",
)
_INSTALLED_SENTINELS = ("party_tracker.json", "config.py", "model_config.py")
_CONFIG_PORT_PATTERN = re.compile(r"^WEB_PORT\s*=\s*\d+", re.MULTILINE)
_MODEL_TRACE_PATTERN = re.compile(r"^ENABLE_COMBAT_TURN_TRACE\s*=\s*False", re.MULTILINE)
_MODEL_RESOLVER_ASSIGNMENT_PATTERN = re.compile(
    r"^DETERMINISTIC_ENEMY_RESOLUTION_ENABLED\s*=", re.MULTILINE
)
_MODEL_RESOLVER_DISABLED_PATTERN = re.compile(
    r"^(DETERMINISTIC_ENEMY_RESOLUTION_ENABLED\s*=\s*)False\b", re.MULTILINE
)
_MODEL_TACTICAL_ASSIGNMENT_PATTERN = re.compile(
    r"^COMBAT_TACTICAL_BRAIN_ENABLED\s*=", re.MULTILINE
)
_MODEL_TACTICAL_DISABLED_PATTERN = re.compile(
    r"^(COMBAT_TACTICAL_BRAIN_ENABLED\s*=\s*)False\b", re.MULTILINE
)
_MODEL_PREFETCH_ASSIGNMENT_PATTERN = re.compile(
    r"^COMBAT_TACTICAL_PREFETCH_ENABLED\s*=", re.MULTILINE
)
_MODEL_PREFETCH_DISABLED_PATTERN = re.compile(
    r"^(COMBAT_TACTICAL_PREFETCH_ENABLED\s*=\s*)False\b", re.MULTILINE
)
_MODEL_ALLY_CONTROLLER_ASSIGNMENT_PATTERN = re.compile(
    r"^COMBAT_ALLY_CONTROLLER_ENABLED\s*=", re.MULTILINE
)
_MODEL_ALLY_CONTROLLER_DISABLED_PATTERN = re.compile(
    r"^(COMBAT_ALLY_CONTROLLER_ENABLED\s*=\s*)False\b", re.MULTILINE
)
_MODEL_ALLY_PREFETCH_ASSIGNMENT_PATTERN = re.compile(
    r"^COMBAT_ALLY_PREFETCH_ENABLED\s*=", re.MULTILINE
)
_MODEL_ALLY_PREFETCH_DISABLED_PATTERN = re.compile(
    r"^(COMBAT_ALLY_PREFETCH_ENABLED\s*=\s*)False\b", re.MULTILINE
)
_MODEL_FAULT_ASSIGNMENT_PATTERN = re.compile(
    r"^COMBAT_TURN_COMMIT_FAULT_INJECTION_ENABLED\s*=", re.MULTILINE
)
_MODEL_FAULT_DISABLED_PATTERN = re.compile(
    r"^(COMBAT_TURN_COMMIT_FAULT_INJECTION_ENABLED\s*=\s*)False\b", re.MULTILINE
)
_MODEL_G9_PROVIDER_PATTERN = re.compile(
    r"^(LLM_PROVIDER\s*=\s*)['\"](?:openai|openrouter)['\"]", re.MULTILINE
)
_MODEL_G9_PROFILE_PATTERN = re.compile(
    r"^(ACTIVE_PROFILE\s*=\s*)['\"][^'\"]+['\"]", re.MULTILINE
)
_MODEL_G9_TRANSPORT_FAULT_PATTERN = re.compile(
    r"^(OPENROUTER_TRANSPORT_FAULT_INJECTION_ENABLED\s*=\s*)False\b", re.MULTILINE
)
_MODEL_G9_TRANSPORT_FAULT_ASSIGNMENT_PATTERN = re.compile(
    r"^OPENROUTER_TRANSPORT_FAULT_INJECTION_ENABLED\s*=", re.MULTILINE
)
_G9_MARKER_NAME = ".g9-capture.json"
_G10_MARKER_NAME = ".g10-capture.json"
_RUN_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}")


def _assert_sandbox_root() -> Path:
    """Refuse to operate unless the sandbox root is exactly <repo>/tmp/combat_capture."""
    root = SANDBOX_ROOT
    if root.name != "combat_capture" or root.parent.name != "tmp":
        raise RuntimeError("sandbox root must be exactly tmp/combat_capture")
    if root == PROJECT_ROOT or root.parent.parent.resolve() != PROJECT_ROOT.resolve():
        raise RuntimeError("sandbox root must live directly under the project tmp/ directory")
    for component in (root.parent, root):
        if component.is_symlink():
            raise RuntimeError("refusing to operate on a symlinked path: %s" % component)
    return root


def _assert_sandbox_path(path: Path) -> Path:
    """Return the resolved path after asserting it stays inside the sandbox root."""
    resolved_root = SANDBOX_ROOT.resolve()
    resolved = Path(path).resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise RuntimeError("refusing to write outside the sandbox: %s" % path)
    return resolved


def _copy_file(relative_path: str, *, required: bool) -> None:
    source = PROJECT_ROOT / relative_path
    if not source.is_file():
        if required:
            raise RuntimeError("missing required source file: %s" % relative_path)
        print("[WARN] optional source missing: %s" % relative_path)
        return
    destination = _assert_sandbox_path(SANDBOX_ROOT / relative_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _copy_tree(relative_path: str, *, extra_ignores: Sequence[str], required: bool) -> None:
    source = PROJECT_ROOT / relative_path
    if not source.is_dir():
        if required:
            raise RuntimeError("missing required source directory: %s" % relative_path)
        print("[WARN] optional source directory missing: %s" % relative_path)
        return
    destination = _assert_sandbox_path(SANDBOX_ROOT / relative_path)
    ignore = shutil.ignore_patterns(*(_COMMON_IGNORES + tuple(extra_ignores)))
    shutil.copytree(source, destination, ignore=ignore)


def _copy_runtime() -> int:
    """Copy the app code, the capture module, and the runtime data subset."""
    copied = 0
    for relative_path in _CODE_FILES:
        required = relative_path in _REQUIRED_CODE_FILES
        _copy_file(relative_path, required=required)
        copied += 1
    for relative_path in _CODE_DIRS:
        extra_ignores: Tuple[str, ...] = ()
        if relative_path == "web":
            extra_ignores = _WEB_IGNORES
        elif relative_path == "scripts":
            extra_ignores = _SCRIPTS_IGNORES
        _copy_tree(
            relative_path,
            extra_ignores=extra_ignores,
            required=relative_path in _REQUIRED_CODE_DIRS,
        )
        copied += 1
    for relative_path in _DATA_DIRS:
        _copy_tree(relative_path, extra_ignores=(), required=False)
        copied += 1
    for relative_path in _DATA_FILES:
        _copy_file(relative_path, required=False)
        copied += 1
    _copy_tree("modules/%s" % MODULE_DIR_NAME, extra_ignores=(), required=True)
    copied += 1
    sandbox_module_dir = _assert_sandbox_path(SANDBOX_ROOT / "modules" / MODULE_DIR_NAME)
    if not sandbox_module_dir.is_dir():
        raise RuntimeError("capture module was not copied into the sandbox")
    return copied


def _patch_sandbox_config() -> None:
    config_path = _assert_sandbox_path(SANDBOX_ROOT / "config.py")
    text = config_path.read_text(encoding="utf-8")
    if len(_CONFIG_PORT_PATTERN.findall(text)) != 1:
        raise RuntimeError("expected exactly one WEB_PORT assignment in sandbox config.py")
    updated = _CONFIG_PORT_PATTERN.sub(SANDBOX_PORT_LITERAL, text, count=1)
    if SANDBOX_PORT_LITERAL not in updated:
        raise RuntimeError("sandbox WEB_PORT patch did not apply")
    config_path.write_text(updated, encoding="utf-8")


def _replace_g9_config_literals(text: str, scenario_id: str) -> str:
    """Patch only the sandbox's provider/profile and G9 fault-injection flag."""
    if scenario_id not in capture_fixtures.G9_SCENARIOS:
        raise ValueError("G9 model configuration requires a fixed G9 scenario")
    provider_matches = list(_MODEL_G9_PROVIDER_PATTERN.finditer(text))
    profile_matches = list(_MODEL_G9_PROFILE_PATTERN.finditer(text))
    fault_assignments = list(_MODEL_G9_TRANSPORT_FAULT_ASSIGNMENT_PATTERN.finditer(text))
    if len(provider_matches) != 1:
        raise RuntimeError("expected exactly one literal LLM_PROVIDER assignment in sandbox model_config.py")
    if len(profile_matches) != 1 or profile_matches[0].group(0).split("=", 1)[1].strip().split()[0] != '"production-auto"':
        raise RuntimeError("expected exactly one ACTIVE_PROFILE = production-auto in sandbox model_config.py")
    if len(fault_assignments) != 1 or len(_MODEL_G9_TRANSPORT_FAULT_PATTERN.findall(text)) != 1:
        raise RuntimeError("expected exactly one disabled G9 transport fault flag in sandbox model_config.py")

    updated = _MODEL_G9_PROVIDER_PATTERN.sub(r'\g<1>"openrouter"', text, count=1)
    enabled = scenario_id == "transport-failure"
    updated = _MODEL_G9_TRANSPORT_FAULT_PATTERN.sub(
        r"\g<1>%s" % ("True" if enabled else "False"), updated, count=1
    )
    if len(_MODEL_G9_PROVIDER_PATTERN.findall(updated)) != 1:
        raise RuntimeError("G9 provider patch did not apply")
    if len(_MODEL_G9_TRANSPORT_FAULT_ASSIGNMENT_PATTERN.findall(updated)) != 1:
        raise RuntimeError("G9 transport fault patch did not apply")
    return updated


def _patch_sandbox_model_config(gate: str = "g3", scenario_id: str = "") -> None:
    model_config_path = _assert_sandbox_path(SANDBOX_ROOT / "model_config.py")
    if gate == "g9":
        _assert_sandbox_root()
    text = model_config_path.read_text(encoding="utf-8")
    if len(_MODEL_TRACE_PATTERN.findall(text)) != 1:
        raise RuntimeError(
            "expected exactly one ENABLE_COMBAT_TURN_TRACE = False in sandbox model_config.py"
        )
    updated = _MODEL_TRACE_PATTERN.sub(TRACE_GATE_LITERAL, text, count=1)
    if TRACE_GATE_LITERAL not in updated:
        raise RuntimeError("sandbox ENABLE_COMBAT_TURN_TRACE patch did not apply")
    if gate in ("g5r", "g5t", "g5a", "g7"):
        if (len(_MODEL_RESOLVER_ASSIGNMENT_PATTERN.findall(updated)) != 1 or
                len(_MODEL_RESOLVER_DISABLED_PATTERN.findall(updated)) != 1):
            raise RuntimeError(
                "expected exactly one disabled DETERMINISTIC_ENEMY_RESOLUTION_ENABLED assignment "
                "in sandbox model_config.py"
            )
        updated = _MODEL_RESOLVER_DISABLED_PATTERN.sub(
            r"\g<1>True", updated, count=1
        )
        if len(_MODEL_RESOLVER_ASSIGNMENT_PATTERN.findall(updated)) != 1 or not re.search(
                r"^DETERMINISTIC_ENEMY_RESOLUTION_ENABLED\s*=\s*True\b",
                updated, re.MULTILINE):
            raise RuntimeError("sandbox deterministic enemy resolution patch did not apply")
    if gate == "g5t":
        if (len(_MODEL_TACTICAL_ASSIGNMENT_PATTERN.findall(updated)) != 1 or
                len(_MODEL_TACTICAL_DISABLED_PATTERN.findall(updated)) != 1):
            raise RuntimeError(
                "expected exactly one disabled COMBAT_TACTICAL_BRAIN_ENABLED assignment "
                "in sandbox model_config.py"
            )
        updated = _MODEL_TACTICAL_DISABLED_PATTERN.sub(r"\g<1>True", updated, count=1)
        if (len(_MODEL_TACTICAL_ASSIGNMENT_PATTERN.findall(updated)) != 1 or
                not re.search(r"^COMBAT_TACTICAL_BRAIN_ENABLED\s*=\s*True\b",
                              updated, re.MULTILINE)):
            raise RuntimeError("sandbox tactical brain patch did not apply")
    if gate == "g5a":
        for assignment, disabled, name, literal in (
            (_MODEL_ALLY_CONTROLLER_ASSIGNMENT_PATTERN,
             _MODEL_ALLY_CONTROLLER_DISABLED_PATTERN,
             "COMBAT_ALLY_CONTROLLER_ENABLED", ALLY_CONTROLLER_GATE_LITERAL),
            (_MODEL_ALLY_PREFETCH_ASSIGNMENT_PATTERN,
             _MODEL_ALLY_PREFETCH_DISABLED_PATTERN,
             "COMBAT_ALLY_PREFETCH_ENABLED", ALLY_PREFETCH_GATE_LITERAL),
        ):
            if len(assignment.findall(updated)) != 1 or len(disabled.findall(updated)) != 1:
                raise RuntimeError(
                    "expected exactly one disabled %s assignment in sandbox model_config.py"
                    % name
                )
            updated = disabled.sub(r"\g<1>True", updated, count=1)
            if not re.search(r"^%s\s*=\s*True\b" % name, updated, re.MULTILINE):
                raise RuntimeError("sandbox %s patch did not apply" % name)
    if gate == "g7":
        if (len(_MODEL_FAULT_ASSIGNMENT_PATTERN.findall(updated)) != 1 or
                len(_MODEL_FAULT_DISABLED_PATTERN.findall(updated)) != 1):
            raise RuntimeError(
                "expected exactly one disabled COMBAT_TURN_COMMIT_FAULT_INJECTION_ENABLED assignment "
                "in sandbox model_config.py"
            )
        updated = _MODEL_FAULT_DISABLED_PATTERN.sub(r"\g<1>True", updated, count=1)
        if not re.search(
                r"^COMBAT_TURN_COMMIT_FAULT_INJECTION_ENABLED\s*=\s*True\b",
                updated, re.MULTILINE):
            raise RuntimeError("sandbox combat-turn fault injection patch did not apply")
        if (len(_MODEL_TACTICAL_ASSIGNMENT_PATTERN.findall(updated)) != 1 or
                len(_MODEL_TACTICAL_DISABLED_PATTERN.findall(updated)) != 1 or
                len(_MODEL_PREFETCH_ASSIGNMENT_PATTERN.findall(updated)) != 1 or
                len(_MODEL_PREFETCH_DISABLED_PATTERN.findall(updated)) != 1):
            raise RuntimeError("G7 requires exactly one disabled tactical brain and prefetch literal")
    if gate == "g9":
        updated = _replace_g9_config_literals(updated, scenario_id)
    model_config_path.write_text(updated, encoding="utf-8")


def _validate_g9_run_dir(run_dir: str) -> Path:
    """Require a not-yet-created G9 run directory below its canonical tmp root."""
    value = Path(str(run_dir))
    candidate = value if value.is_absolute() else PROJECT_ROOT / value
    run_root = PROJECT_ROOT / "tmp" / "router-rollout" / "g9"
    try:
        absolute = candidate.absolute()
        root_absolute = run_root.absolute()
        relative = absolute.relative_to(root_absolute)
    except ValueError as exc:
        raise ValueError("G9 --run-dir must be a child of tmp/router-rollout/g9/") from exc
    if len(relative.parts) != 1 or not _RUN_ID_PATTERN.fullmatch(relative.name):
        raise ValueError("G9 --run-dir must end in a simple unique run id")
    current = PROJECT_ROOT
    for part in absolute.relative_to(PROJECT_ROOT).parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("G9 --run-dir must not traverse symlinks")
    if candidate.exists() or candidate.is_symlink():
        raise ValueError("G9 --run-dir must be unique and not yet created")
    return candidate


def _validate_g10_run_dir(run_dir: str) -> Path:
    """Require a unique G10 evidence directory below its canonical tmp root."""
    value = Path(str(run_dir))
    candidate = value if value.is_absolute() else PROJECT_ROOT / value
    run_root = PROJECT_ROOT / "tmp" / "router-rollout" / "g10"
    try:
        absolute = candidate.absolute()
        root_absolute = run_root.absolute()
        relative = absolute.relative_to(root_absolute)
    except ValueError as exc:
        raise ValueError("G10 --run-dir must be a child of tmp/router-rollout/g10/") from exc
    if len(relative.parts) != 1 or not _RUN_ID_PATTERN.fullmatch(relative.name):
        raise ValueError("G10 --run-dir must end in a simple unique run id")
    current = PROJECT_ROOT
    for part in absolute.relative_to(PROJECT_ROOT).parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("G10 --run-dir must not traverse symlinks")
    if candidate.exists() or candidate.is_symlink():
        raise ValueError("G10 --run-dir must be unique and not yet created")
    return candidate


def _g9_marker_path() -> Path:
    return _assert_sandbox_path(SANDBOX_ROOT / _G9_MARKER_NAME)


def _write_g9_marker(payload: Dict[str, Any]) -> None:
    marker_path = _g9_marker_path()
    if not safe_write_json(str(marker_path), payload, create_backup=False, acquire_lock=False):
        raise RuntimeError("failed to write sandbox G9 marker")


def _read_g9_marker() -> Dict[str, Any]:
    marker_path = _g9_marker_path()
    if not marker_path.is_file():
        raise ValueError("G9 sandbox marker is missing; prepare the row once before rollback")
    try:
        payload = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("G9 sandbox marker is unreadable") from exc
    if not isinstance(payload, dict) or payload.get("gate") != "g9":
        raise ValueError("G9 sandbox marker is invalid")
    return payload


def _write_g10_marker(payload: Dict[str, Any]) -> None:
    marker_path = _assert_sandbox_path(SANDBOX_ROOT / _G10_MARKER_NAME)
    if not safe_write_json(str(marker_path), payload, create_backup=False, acquire_lock=False):
        raise RuntimeError("failed to write sandbox G10 marker")


def rollback_openai(scenario_id: str, party_size: int, run_dir: str) -> int:
    """Change the prepared sandbox to direct OpenAI without reseeding or restarting it."""
    _assert_sandbox_root()
    row_key = capture_fixtures.g9_row_key(scenario_id, party_size)
    if scenario_id != "preferred-openai-rollback":
        raise ValueError("--rollback-openai applies only to preferred-openai-rollback rows")
    validated_run_dir = _validate_g9_run_dir(run_dir)
    marker = _read_g9_marker()
    expected_run = str(validated_run_dir.relative_to(PROJECT_ROOT))
    if (marker.get("row_key") != row_key or marker.get("scenario_id") != scenario_id or
            marker.get("party_size") != party_size or marker.get("run_dir") != expected_run):
        raise ValueError("G9 rollback identity does not match the prepared scenario, party, and run directory")
    if marker.get("rollback_state") != "pending":
        raise ValueError("G9 rollback was already configured; do not reseed or repeat the rollback")

    model_config_path = _assert_sandbox_path(SANDBOX_ROOT / "model_config.py")
    text = model_config_path.read_text(encoding="utf-8")
    provider_matches = list(_MODEL_G9_PROVIDER_PATTERN.finditer(text))
    profile_matches = list(_MODEL_G9_PROFILE_PATTERN.finditer(text))
    if (len(provider_matches) != 1 or provider_matches[0].group(0).split("=", 1)[1].strip().split()[0] != '"openrouter"' or
            len(profile_matches) != 1 or profile_matches[0].group(0).split("=", 1)[1].strip().split()[0] != '"production-auto"'):
        raise ValueError("G9 rollback requires the prepared OpenRouter production-auto sandbox")
    if len(_MODEL_G9_TRANSPORT_FAULT_PATTERN.findall(text)) != 1:
        raise ValueError("G9 rollback requires the transport-failure flag to be disabled")
    identity = capture_evidence.read_sandbox_g9_identity(SANDBOX_ROOT)
    if (identity.get("status") != "ok" or identity.get("configured_model") != "gpt-6-luna" or
            identity.get("transport_fault_injection_enabled") is not False):
        raise ValueError("G9 rollback requires direct gpt-6-luna availability and disabled fault injection")
    updated = _MODEL_G9_PROVIDER_PATTERN.sub(r'\g<1>"openai"', text, count=1)
    model_config_path.write_text(updated, encoding="utf-8")
    marker.update({
        "rollback_state": "configured",
        "rollback_provider": "openai",
        "rollback_model": "gpt-6-luna",
        "operator_restart_count_required": 1,
        "reseed_after_rollback": False,
    })
    _write_g9_marker(marker)
    print("[ROLLBACK] sandbox model_config.py now selects direct OpenAI gpt-6-luna")
    print("[NEXT] restart the existing sandbox server exactly once; do not reseed")
    return 0


def transform_g4_narrator_area_fixture(sandbox_module_dir: Path) -> Dict[str, str]:
    """Make only the sandbox BU/live CA02 area inputs peaceful and hydration-stable."""
    module_dir = Path(sandbox_module_dir).resolve()
    if module_dir.name != MODULE_DIR_NAME or module_dir.parent.name != "modules":
        raise ValueError("G4 area transform requires the sandbox Capture_Arena module directory")
    root = module_dir.parent.parent.resolve()
    if root == PROJECT_ROOT.resolve() or root.parent != (PROJECT_ROOT / "tmp").resolve():
        raise ValueError("G4 area transform must operate below project tmp/ sandbox")

    hashes: Dict[str, str] = {}
    for filename in ("CTR001_BU.json", "CTR001.json"):
        path = module_dir / "areas" / filename
        if not path.is_file() or not path.resolve().is_relative_to(root):
            raise ValueError("required sandbox area fixture is missing or outside sandbox: %s" % filename)
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("areaId") != "CTR001" or not isinstance(payload.get("locations"), list):
            raise ValueError("unexpected Capture_Arena area fixture shape: %s" % filename)
        matches = [location for location in payload["locations"]
                   if isinstance(location, dict) and location.get("locationId") == "CA02"]
        if len(matches) != 1:
            raise ValueError("Capture_Arena area must contain exactly one CA02")
        pit = matches[0]
        # Keep the room and authored geometry; strip only the hostile encounter
        # cues which would start combat during this narrator-only scenario.
        pit["description"] = (
            "A quiet sunken sand pit ringed by splintered practice stakes and "
            "scarred shield racks. The arena is empty between training sessions."
        )
        pit["dmInstructions"] = (
            "Keep the training pit peaceful and empty. Describe the sand, "
            "practice stakes, and shield racks; do not start or imply combat."
        )
        pit["monsters"] = []
        raw = json.dumps(payload, ensure_ascii=True, indent=2) + "\n"
        path.write_text(raw, encoding="utf-8")
        hashes[filename] = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return hashes


def transform_g5t_commander_fixtures(sandbox_module_dir: Path) -> Dict[str, str]:
    """Seed G5T monster authority and authored cover only in the isolated sandbox."""
    module_dir = Path(sandbox_module_dir).resolve()
    if module_dir.name != MODULE_DIR_NAME or module_dir.parent.name != "modules":
        raise ValueError("G5T fixture transform requires the sandbox Capture_Arena module directory")
    root = module_dir.parent.parent.resolve()
    if root == PROJECT_ROOT.resolve() or root.parent != (PROJECT_ROOT / "tmp").resolve():
        raise ValueError("G5T fixture transform must operate below project tmp/ sandbox")

    fixture = capture_fixtures.build_g5t_commander_fixture(1)
    hashes: Dict[str, str] = {}
    for name, payload in fixture["monster_definitions"].items():
        slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
        relative = "modules/%s/monsters/%s.json" % (MODULE_DIR_NAME, slug)
        path = (root / relative).resolve()
        if not path.is_relative_to(root):
            raise RuntimeError("refusing to write outside the G5T sandbox: %s" % path)
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = json.dumps(payload, ensure_ascii=True, indent=2) + "\n"
        path.write_text(raw, encoding="utf-8")
        hashes[relative] = hashlib.sha256(raw.encode("utf-8")).hexdigest()

    source_features = fixture["training_pit_area"]["locations"][0]["tacticalFeatures"]
    if len(source_features) != 1 or source_features[0].get("featureId") != capture_fixtures.G5T_TRAINING_PIT_FEATURE_ID:
        raise ValueError("G5T fixture must contain exactly one authored CA02 cover feature")
    for filename in ("CTR001_BU.json", "CTR001.json"):
        path = module_dir / "areas" / filename
        if not path.is_file() or not path.resolve().is_relative_to(root):
            raise ValueError("required sandbox area fixture is missing or outside sandbox: %s" % filename)
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("areaId") != "CTR001" or not isinstance(payload.get("locations"), list):
            raise ValueError("unexpected Capture_Arena area fixture shape: %s" % filename)
        matches = [location for location in payload["locations"]
                   if isinstance(location, dict) and location.get("locationId") == "CA02"]
        if len(matches) != 1:
            raise ValueError("Capture_Arena area must contain exactly one CA02")
        location = matches[0]
        existing = location.get("tacticalFeatures", [])
        if not isinstance(existing, list):
            raise ValueError("sandbox CA02 tacticalFeatures must be a list")
        existing = [row for row in existing if not (
            isinstance(row, dict) and row.get("featureId") == capture_fixtures.G5T_TRAINING_PIT_FEATURE_ID
        )]
        location["tacticalFeatures"] = existing + json.loads(json.dumps(source_features))
        raw = json.dumps(payload, ensure_ascii=True, indent=2) + "\n"
        path.write_text(raw, encoding="utf-8")
        hashes[filename] = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return hashes


def transform_g5a_ally_fixtures(sandbox_module_dir: Path) -> Dict[str, str]:
    """Seed ally-usable authored cover only in the isolated G5A sandbox copy."""
    module_dir = Path(sandbox_module_dir).resolve()
    if module_dir.name != MODULE_DIR_NAME or module_dir.parent.name != "modules":
        raise ValueError("G5A fixture transform requires the sandbox Capture_Arena module directory")
    root = module_dir.parent.parent.resolve()
    if root == PROJECT_ROOT.resolve() or root.parent != (PROJECT_ROOT / "tmp").resolve():
        raise ValueError("G5A fixture transform must operate below project tmp/ sandbox")

    source_features = capture_fixtures.build_g5a_training_pit_area()["locations"][0][
        "tacticalFeatures"
    ]
    if (len(source_features) != 1 or
            source_features[0].get("featureId") != capture_fixtures.G5A_COVER_FEATURE_ID or
            "npc" not in source_features[0].get("usableBy", [])):
        raise ValueError("G5A fixture must define exactly one NPC-usable authored cover feature")
    hashes: Dict[str, str] = {}
    for filename in ("CTR001_BU.json", "CTR001.json"):
        path = module_dir / "areas" / filename
        if not path.is_file() or not path.resolve().is_relative_to(root):
            raise ValueError("required sandbox area fixture is missing or outside sandbox: %s" % filename)
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("areaId") != "CTR001" or not isinstance(payload.get("locations"), list):
            raise ValueError("unexpected Capture_Arena area fixture shape: %s" % filename)
        matches = [location for location in payload["locations"]
                   if isinstance(location, dict) and
                   location.get("locationId") == capture_fixtures.G5A_COVER_LOCATION_ID]
        if len(matches) != 1:
            raise ValueError("Capture_Arena area must contain exactly one G5A cover location")
        location = matches[0]
        existing = location.get("tacticalFeatures", [])
        if not isinstance(existing, list):
            raise ValueError("sandbox G5A tacticalFeatures must be a list")
        existing = [row for row in existing if not (
            isinstance(row, dict) and
            row.get("featureId") == capture_fixtures.G5A_COVER_FEATURE_ID
        )]
        location["tacticalFeatures"] = existing + json.loads(json.dumps(source_features))
        raw = json.dumps(payload, ensure_ascii=True, indent=2) + "\n"
        path.write_text(raw, encoding="utf-8")
        hashes[filename] = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return hashes


def _read_capture_arena_reference() -> Dict[str, str]:
    """Derive the seeded module/area/start-location ids from the sandbox module files."""
    module_dir = _assert_sandbox_path(SANDBOX_ROOT / "modules" / MODULE_DIR_NAME)
    area_files = sorted(
        path for path in module_dir.glob("areas/*.json") if not path.name.endswith("_BU.json")
    )
    if len(area_files) != 1:
        raise RuntimeError("expected exactly one live area file for %s" % MODULE_DIR_NAME)
    area_data = json.loads(area_files[0].read_text(encoding="utf-8"))
    area_id = str(area_data.get("areaId") or "")
    if not area_id:
        raise RuntimeError("capture area file is missing areaId")

    map_files = sorted(
        path
        for path in module_dir.glob("map_%s.json" % area_id)
        if not path.name.endswith("_BU.json")
    )
    if len(map_files) != 1:
        raise RuntimeError("expected exactly one map file for area %s" % area_id)
    map_data = json.loads(map_files[0].read_text(encoding="utf-8"))
    start_location_id = str(map_data.get("startRoom") or "")
    if not start_location_id:
        raise RuntimeError("capture map file is missing startRoom")

    start_location = next(
        (
            location
            for location in area_data.get("locations", [])
            if str(location.get("locationId") or "") == start_location_id
        ),
        None,
    )
    if start_location is None:
        raise RuntimeError(
            "start room %s is not present in capture area %s" % (start_location_id, area_id)
        )
    return {
        "module": MODULE_DIR_NAME,
        "area_id": area_id,
        "area_name": str(area_data.get("areaName") or ""),
        "start_location_id": start_location_id,
        "start_location_name": str(start_location.get("name") or ""),
    }


def _party_names(party_size: int) -> List[str]:
    if party_size == PARTY_SIZE_FOUR:
        return list(capture_fixtures.PC_NAMES)
    return [capture_fixtures.ONE_PC_NAME]


def _party_initiative(name: str, party_size: int) -> int:
    if party_size == PARTY_SIZE_FOUR:
        return int(capture_fixtures.PC_INITIATIVES[name])
    return int(capture_fixtures.ONE_PC_INITIATIVE)


def _pc_creature(name: str, initiative: int) -> Dict[str, Any]:
    """Adapt the fixture character payload into a player creature entry."""
    payload = capture_fixtures._character_payload(name, initiative)
    return {
        "name": payload["name"],
        "type": "player",
        "initiative": payload["initiative"],
        "status": payload["status"],
        "conditions": [],
        "actions": {"actionType": "", "target": ""},
        "currentHitPoints": payload["hitPoints"],
        "maxHitPoints": payload["maxHitPoints"],
        "armorClass": payload["armorClass"],
    }


def _capture_character_path(name: str) -> str:
    """Return the canonical character path for this tool's fixed seed roster.

    These fixture identities are deliberately bounded to the authored capture
    roster. Calling ModulePathManager.format_filename here would import the
    production character-update owner just to normalize these known names.
    """
    allowed_names = set(capture_fixtures.PC_NAMES) | {
        capture_fixtures.ONE_PC_NAME,
        capture_fixtures.CAPTURE_ALLIED_NPC_NAME,
    }
    if name not in allowed_names:
        raise ValueError("unsupported Capture_Arena seed character")
    return "characters/%s.json" % name.lower().replace(" ", "_")


def _apply_capture_goblin_attack_count(encounter: Dict[str, Any]) -> None:
    # Goblins make one selected attack per turn in the training-pit capture.
    for creature in encounter.get("creatures", []):
        if (creature.get("type") == "enemy" and
                creature.get("monsterType") == "Goblin"):
            creature["numAttacks"] = 1
            creature["attacks"] = [{"name": "Scimitar"}, {"name": "Shortbow"}]


def _build_encounter(
    party_names: List[str], party_size: int, profile: Optional[Dict[str, Any]] = None
) -> Tuple[Dict[str, Any], str]:
    if profile is not None and profile.get("gate") == "g7":
        fixture = capture_fixtures.build_g7_turn_commit_fixture(
            party_size, profile.get("path", "normal")
        )
        return json.loads(json.dumps(fixture["encounter"])), fixture["encounter_id"]
    if profile is not None and profile.get("gate") == "g5t":
        fixture = capture_fixtures.build_g5t_commander_fixture(party_size)
        encounter = json.loads(json.dumps(fixture["encounter"]))
        encounter_id = profile["scenario_id"]
        encounter["id"] = encounter_id
        encounter["encounterId"] = encounter_id
        encounter["encounterSummary"] = (
            "A Hobgoblin Captain directs a goblin squad in the Capture Arena training pit."
        )
        seed = profile.get("seed", {})
        enemy_hit_points = {
            capture_fixtures.G5T_COMMANDER_NAME: seed.get("captain_hit_points"),
            capture_fixtures.G5T_GOBLIN_NAMES[0]: seed.get("goblin_squad_a_hit_points"),
            capture_fixtures.G5T_GOBLIN_NAMES[1]: seed.get("goblin_squad_b_hit_points"),
        }
        for creature in encounter.get("creatures", []):
            if creature.get("type") != "enemy":
                continue
            maximum = creature.get("maxHitPoints")
            hp = enemy_hit_points.get(creature.get("name"))
            if isinstance(hp, int) and not isinstance(hp, bool) and isinstance(maximum, int):
                creature["currentHitPoints"] = hp
        encounter.update({
            "initiativeMode": "two_group_phase1",
            "initiativeRolls": {"dmGroup": 0, "pcGroup": 1},
            "initiativeWinner": "pcGroup",
            "roundStartsWith": "pcGroup",
            "awaitingPcGroupRoll": False,
            "combat_round": 1,
            "current_round": 1,
        })
        return encounter, encounter_id

    if profile is not None and profile.get("gate") == "g5a":
        base_payload = (capture_fixtures._one_pc_encounter_payload()
                        if party_size == 1 else capture_fixtures._encounter_payload())
        encounter_id = profile["scenario_id"]
        encounter = json.loads(json.dumps(base_payload))
        encounter["id"] = encounter_id
        encounter["encounterId"] = encounter_id
        encounter["encounterSummary"] = profile["seed"]["encounter_context"]
        pc_creatures = [
            _pc_creature(name, _party_initiative(name, party_size))
            for name in party_names
        ]
        encounter["creatures"] = pc_creatures + list(encounter.get("creatures", []))
        capture_fixtures.apply_capture_profile(encounter, {}, profile)
        _apply_capture_goblin_attack_count(encounter)
        return encounter, encounter_id

    if party_size == PARTY_SIZE_FOUR:
        base_payload = capture_fixtures._encounter_payload()
        encounter_id = "capture_mp"
    else:
        base_payload = capture_fixtures._one_pc_encounter_payload()
        encounter_id = "capture_one_pc"
    encounter = json.loads(json.dumps(base_payload))
    encounter["id"] = encounter_id
    encounter["encounterId"] = encounter_id
    if profile is not None:
        encounter["encounterSummary"] = "Capture Arena named scenario seed: %s" % profile["scenario_id"]
    pc_creatures = [
        _pc_creature(name, _party_initiative(name, party_size)) for name in party_names
    ]
    encounter["creatures"] = pc_creatures + list(encounter.get("creatures", []))
    if profile is not None:
        seed_profile = dict(profile)
        seed_profile["scenario_id"] = profile.get("seed_scenario_id", profile["scenario_id"])
        capture_fixtures.apply_capture_profile(encounter, {}, seed_profile)
    _apply_capture_goblin_attack_count(encounter)
    return encounter, encounter_id


def _build_party_tracker(
    reference: Dict[str, str], party_names: List[str], encounter_id: str,
    profile: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    tracker = {
        "module": reference["module"],
        "partyMembers": list(party_names),
        "active_character": party_names[0],
        "partyNPCs": [],
        "worldConditions": {
            "year": 1492,
            "month": "Springmonth",
            "day": 5,
            "time": "09:00:00",
            "weather": "",
            "season": "Spring",
            "dayNightCycle": "Day",
            "moonPhase": "New Moon",
            "currentLocation": reference["start_location_name"],
            "currentLocationId": reference["start_location_id"],
            "currentArea": reference["area_name"],
            "currentAreaId": reference["area_id"],
            "majorEventsUnderway": [],
            "politicalClimate": "",
            "activeEncounter": "",
            "activeCombatEncounter": encounter_id,
            "lastRealInputTimestamp": SEED_TIMESTAMP,
        },
    }
    if profile is not None and profile.get("gate") == "g5t":
        training_pit = next(
            (
                location
                for location in capture_fixtures.build_g5t_training_pit_area()["locations"]
                if location.get("locationId") == capture_fixtures.G5T_TRAINING_PIT_LOCATION_ID
            ),
            None,
        )
        if training_pit is None:
            raise ValueError("G5T fixture is missing the authored Training Pit location")
        tracker["worldConditions"].update({
            "currentLocation": str(training_pit.get("name") or ""),
            "currentLocationId": capture_fixtures.G5T_TRAINING_PIT_LOCATION_ID,
        })
    elif profile is not None and profile.get("gate") == "g5a":
        tracker["worldConditions"].update({
            "currentLocation": "Training Pit",
            "currentLocationId": capture_fixtures.G5A_COVER_LOCATION_ID,
        })
    if profile is not None:
        ally = profile.get("seed", {}).get("party_ally")
        if ally:
            tracker["partyNPCs"] = [dict(ally)]
        tracker["worldConditions"]["weatherConditions"] = ""
    return tracker


def _write_json(relative_path: str, payload: Dict[str, Any]) -> Path:
    destination = _assert_sandbox_path(SANDBOX_ROOT / relative_path)
    if not safe_write_json(
        str(destination), payload, create_backup=False, acquire_lock=False
    ):
        raise RuntimeError("failed to write sandbox file: %s" % relative_path)
    if not destination.is_file():
        raise RuntimeError("sandbox file missing after write: %s" % relative_path)
    return destination


def _create_sandbox_dirs() -> None:
    for relative_path in _SANDBOX_DIRS:
        _assert_sandbox_path(SANDBOX_ROOT / relative_path).mkdir(parents=True, exist_ok=True)


def _seed_party(
    reference: Dict[str, str], party_names: List[str], party_size: int,
    profile: Optional[Dict[str, Any]] = None,
    *, writer: Optional[Callable[[str, Dict[str, Any]], Any]] = None,
    path_manager: Optional[Any] = None,
) -> str:
    write_fixture = writer or _write_json
    g7_fixture = (
        capture_fixtures.build_g7_turn_commit_fixture(
            party_size, profile.get("path", "normal")
        )
        if profile is not None and profile.get("gate") == "g7" else None
    )
    def character_path(name: str) -> str:
        if path_manager is not None:
            return path_manager.get_character_unified_path(name)
        return _capture_character_path(name)

    for name in party_names:
        character_relative = character_path(name)
        if profile is None:
            character_payload = capture_fixtures._character_payload(
                name, _party_initiative(name, party_size)
            )
        elif profile.get("gate") == "g5a":
            character_payload = capture_fixtures.build_g5a_character_payload(
                name, _party_initiative(name, party_size)
            )
        else:
            overrides = profile.get("character_overrides", {}).get(name)
            if g7_fixture is not None:
                overrides = {
                    "armorClass": g7_fixture["pc_armor_class"],
                    "hitPoints": g7_fixture["pc_hit_points"],
                    "maxHitPoints": g7_fixture["pc_hit_points"],
                }
                overrides.update(g7_fixture["character_overrides"].get(name, {}))
            if profile.get("gate") == "g5t":
                pc_hit_points = profile.get("seed", {}).get("pc_hit_points")
                if isinstance(pc_hit_points, int) and not isinstance(pc_hit_points, bool):
                    overrides = dict(overrides or {})
                    overrides.update({
                        "hitPoints": pc_hit_points,
                        "maxHitPoints": pc_hit_points,
                        "status": "alive",
                        "deathSaves": {"successes": 0, "failures": 0},
                    })
            character_payload = capture_fixtures.build_capture_character_payload(
                name,
                _party_initiative(name, party_size),
                overrides,
            )
        # Named evidence seeds record known zero XP so exit/replay checks can
        # distinguish an observed zero from a missing value. The unchanged
        # default latency fixture deliberately keeps its historical payload.
        if profile is not None and "experience_points" not in character_payload:
            character_payload["experience_points"] = 0
        write_fixture(
            character_relative,
            character_payload,
        )

    narrator_only = bool(
        profile and profile.get("seed_scenario_id", profile.get("scenario_id")) ==
        "narrator-dialogue-travel"
    )
    if narrator_only:
        encounter_id = ""
    else:
        encounter, encounter_id = _build_encounter(party_names, party_size, profile)
        for name, payload in (profile or {}).get("npc_characters", {}).items():
            write_fixture(character_path(name), payload)
        write_fixture("modules/encounters/encounter_%s.json" % encounter_id, encounter)

    tracker = _build_party_tracker(reference, party_names, encounter_id, profile)
    write_fixture("party_tracker.json", tracker)
    return encounter_id


def _hash_installed_sentinels() -> Dict[str, str]:
    hashes: Dict[str, str] = {}
    for relative_path in _INSTALLED_SENTINELS:
        path = PROJECT_ROOT / relative_path
        if path.is_file():
            hashes[relative_path] = hashlib.sha256(path.read_bytes()).hexdigest()
        else:
            hashes[relative_path] = "missing"
    return hashes


def _directory_size_bytes(path: Path) -> int:
    total = 0
    for item in path.rglob("*"):
        try:
            if item.is_file():
                total += item.stat().st_size
        except OSError:
            continue
    return total


def _format_mb(byte_count: int) -> str:
    return "%.1f MB" % (byte_count / (1024.0 * 1024.0))


def _venv_python_display() -> str:
    candidates = (
        PROJECT_ROOT / ".venv" / "bin" / "python",
        PROJECT_ROOT / ".venv" / "Scripts" / "python.exe",
    )
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return sys.executable


def prepare(
    party_size: int, scenario_id: str = "", branch: str = "", phase: str = "",
    gate: Optional[str] = None,
    path: str = "", boundary: str = "", run_dir: str = "", chain_id: str = "",
) -> int:
    """Rebuild the sandbox from scratch and seed it for the capture run."""
    logging.getLogger("utils.file_operations").setLevel(logging.WARNING)
    _assert_sandbox_root()
    gate = gate or capture_fixtures.infer_capture_gate(scenario_id) or "g3"
    profile = (capture_fixtures.build_gate_profile(
        gate, scenario_id, party_size, branch, phase, path, boundary
    )
               if scenario_id else None)
    if gate != "g3" and profile is None:
        raise ValueError("--gate %s requires a fixed --scenario profile" % gate)
    g9_run_dir: Optional[Path] = None
    if gate == "g9":
        if phase:
            raise ValueError("G9 rollback uses --rollback-openai after prepare; do not prepare with --phase")
        if not run_dir:
            raise ValueError("G9 --prepare requires a unique --run-dir")
        g9_run_dir = _validate_g9_run_dir(run_dir)
        marker_path = _g9_marker_path()
        if (scenario_id == "preferred-openai-rollback" and marker_path.is_file() and
                (SANDBOX_ROOT / "model_config.py").is_file()):
            raise ValueError("preferred-openai-rollback is already prepared; use --rollback-openai without reseeding")
    g10_run_dir: Optional[Path] = None
    if gate == "g10":
        if phase != "complete":
            raise ValueError("G10 prepares only --phase complete; resume uses the retained sandbox")
        if not chain_id or not _RUN_ID_PATTERN.fullmatch(chain_id):
            raise ValueError("G10 --prepare requires a simple --chain-id")
        if not run_dir:
            raise ValueError("G10 --prepare requires the complete-phase --run-dir")
        g10_run_dir = _validate_g10_run_dir(run_dir)
    elif chain_id:
        raise ValueError("--chain-id applies only with --gate g10")
    if scenario_id == "resume-replay" and phase == "replay":
        raise ValueError("resume-replay --phase replay drives an already-running sandbox; do not prepare")
    if gate == "g7" and phase in ("recover", "replay"):
        raise ValueError("G7 --phase %s uses retained state; do not prepare or reseed" % phase)
    if profile is None and (branch or phase or path or boundary):
        raise ValueError("--branch/--phase/--path/--boundary require --scenario")
    installed_before = _hash_installed_sentinels()

    if SANDBOX_ROOT.exists():
        shutil.rmtree(_assert_sandbox_root())
    SANDBOX_ROOT.mkdir(parents=True, exist_ok=False)

    copied = _copy_runtime()
    _patch_sandbox_config()
    _patch_sandbox_model_config(gate, scenario_id)
    if profile and profile.get("seed_scenario_id", profile["scenario_id"]) == "narrator-dialogue-travel":
        transform_g4_narrator_area_fixture(SANDBOX_ROOT / "modules" / MODULE_DIR_NAME)
    if profile and profile.get("gate") == "g5t":
        transform_g5t_commander_fixtures(SANDBOX_ROOT / "modules" / MODULE_DIR_NAME)
    if profile and profile.get("gate") == "g5a":
        transform_g5a_ally_fixtures(SANDBOX_ROOT / "modules" / MODULE_DIR_NAME)
    reference = _read_capture_arena_reference()
    party_names = _party_names(party_size)
    _create_sandbox_dirs()
    encounter_id = _seed_party(reference, party_names, party_size, profile)

    if gate == "g10" and profile is not None and g10_run_dir is not None:
        seed_profile = dict(profile.get("seed", {}))
        seed_digest = hashlib.sha256(
            json.dumps(seed_profile, ensure_ascii=True, sort_keys=True).encode("ascii")
        ).hexdigest()
        _write_g10_marker({
            "gate": "g10",
            "scenario_id": capture_fixtures.G10_SCENARIO,
            "seed_scenario_id": profile.get("seed_scenario_id"),
            "party_size": party_size,
            "chain_id": chain_id,
            "complete_run_dir": str(g10_run_dir.relative_to(PROJECT_ROOT)),
            "seed_id": seed_digest,
            "script_sha256": profile.get("applicability", {}).get("script_sha256"),
        })

    if gate == "g9" and profile is not None and g9_run_dir is not None:
        rollback_scenario = scenario_id == "preferred-openai-rollback"
        _write_g9_marker({
            "gate": "g9",
            "row_key": profile["row_key"],
            "scenario_id": scenario_id,
            "party_size": party_size,
            "run_dir": str(g9_run_dir.relative_to(PROJECT_ROOT)),
            "initial_provider": "openrouter",
            "active_profile": "production-auto",
            "transport_failure_injection": scenario_id == "transport-failure",
            "rollback_state": "pending" if rollback_scenario else "not_required",
            "operator_restart_count_required": 1 if rollback_scenario else 0,
            "reseed_after_rollback": False,
        })

    trackers = json.loads(
        _assert_sandbox_path(SANDBOX_ROOT / "party_tracker.json").read_text(encoding="utf-8")
    )
    if trackers.get("worldConditions", {}).get("activeCombatEncounter") != encounter_id:
        raise RuntimeError("seeded party_tracker.json did not set activeCombatEncounter")

    installed_after = _hash_installed_sentinels()
    changed = sorted(
        key for key in installed_before if installed_before[key] != installed_after[key]
    )

    print("[SEED] mode=prepare party=%d sandbox=%s" % (party_size, SANDBOX_DISPLAY))
    print(
        "[COPY] sources=%d module=%s (excluded .venv .git tmp debug graphic_packs "
        "modules/* except %s)" % (copied, MODULE_DIR_NAME, MODULE_DIR_NAME)
    )
    model_patches = [TRACE_GATE_LITERAL]
    if gate in ("g5r", "g7"):
        model_patches.append(RESOLVER_GATE_LITERAL)
    elif gate == "g5t":
        model_patches.extend((RESOLVER_GATE_LITERAL, TACTICAL_GATE_LITERAL))
    elif gate == "g5a":
        model_patches.extend((
            RESOLVER_GATE_LITERAL,
            ALLY_CONTROLLER_GATE_LITERAL,
            ALLY_PREFETCH_GATE_LITERAL,
        ))
    if gate == "g7":
        model_patches.append("COMBAT_TURN_COMMIT_FAULT_INJECTION_ENABLED = True")
    if gate == "g9":
        model_patches.extend((
            'LLM_PROVIDER = "openrouter"',
            'ACTIVE_PROFILE = "production-auto"',
            "OPENROUTER_TRANSPORT_FAULT_INJECTION_ENABLED = %s" %
            ("True" if scenario_id == "transport-failure" else "False"),
        ))
    print("[PATCH] config.py %s; model_config.py %s" %
          (SANDBOX_PORT_LITERAL, "; ".join(model_patches)))
    print(
        "[SEED] module=%s area=%s (%s) start=%s (%s)"
        % (
            reference["module"],
            reference["area_id"],
            reference["area_name"],
            reference["start_location_id"],
            reference["start_location_name"],
        )
    )
    print(
        "[SEED] partyMembers=%s active_character=%s"
        % (",".join(party_names), party_names[0])
    )
    print(
        "[SEED] encounter=%s file=modules/encounters/encounter_%s.json"
        % (encounter_id, encounter_id)
    )
    if profile is not None:
        if gate == "g9":
            print(
                "[SEED] scenario=%s row=%s branch=%s phase=%s max_steps=%d max_requests=%d"
                % (profile["scenario_id"], profile["row_key"], profile.get("branch") or "-",
                   profile.get("phase") or "-", profile["max_steps"], profile["max_requests"])
            )
        else:
            print(
                "[SEED] scenario=%s branch=%s phase=%s max_steps=%d max_requests=%d"
                % (profile["scenario_id"], profile.get("branch") or "-",
                   profile.get("phase") or "-", profile["max_steps"], profile["max_requests"])
            )
    print("[SEED] trace=%s (relative to sandbox)" % DEFAULT_TRACE_DISPLAY)
    print("[SIZE] sandbox=%s" % _format_mb(_directory_size_bytes(SANDBOX_ROOT)))

    for key in sorted(installed_before):
        print("[VERIFY] installed %s sha256=%s" % (key, installed_before[key][:12]))
    if changed:
        print("[FAIL] installed files changed during prepare: %s" % ", ".join(changed))
        return 1
    print("[PASS] installed tree unchanged; sandbox ready at %s" % SANDBOX_DISPLAY)

    python_display = _venv_python_display()
    print(
        "[NEXT] start:   cd %s && NEQ_OPEN_BROWSER=0 %s run_web.py"
        % (SANDBOX_DISPLAY, python_display)
    )
    print("[NEXT] restore: %s scripts/seed_combat_capture.py --restore" % python_display)
    return 0


def restore() -> int:
    """Remove the sandbox after asserting the target path is exactly tmp/combat_capture."""
    target = _assert_sandbox_root()
    if not target.exists():
        print("[RESTORE] no sandbox at %s; nothing to remove" % SANDBOX_DISPLAY)
        return 0
    freed = _format_mb(_directory_size_bytes(target))
    shutil.rmtree(target)
    print("[RESTORE] removed %s (freed %s)" % (SANDBOX_DISPLAY, freed))
    print("[PASS] sandbox removed; installed tree untouched")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Prepare or restore the tmp/combat_capture sandbox for the capture ensemble"
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", action="store_true", help="rebuild and seed the sandbox")
    mode.add_argument("--restore", action="store_true", help="remove the sandbox")
    mode.add_argument(
        "--rollback-openai", action="store_true",
        help="switch an already-prepared G9 rollback sandbox to direct OpenAI without reseeding",
    )
    parser.add_argument(
        "--party",
        type=int,
        choices=(PARTY_SIZE_ONE, PARTY_SIZE_FOUR),
        default=None,
        help="party size to seed (required with --prepare; ignored with --restore)",
    )
    parser.add_argument(
        "--scenario", choices=capture_fixtures.CAPTURE_SCENARIO_CHOICES,
        help="bounded named seed profile; omitted preserves the legacy seed",
    )
    parser.add_argument(
        "--gate", choices=capture_fixtures.CAPTURE_GATE_CHOICES, default=None,
        help="fixed capture gate (inferred from a named scenario; otherwise g3)",
    )
    parser.add_argument(
        "--branch", choices=capture_fixtures.CAPTURE_BRANCHES,
        help="required for surrender-exit; the two branches are separate runs",
    )
    parser.add_argument(
        "--phase", choices=(capture_fixtures.G7_COMMIT_PHASES +
                            (capture_fixtures.G9_ROLLBACK_PHASE,) +
                            capture_fixtures.G10_PHASES),
        help="G7/G10 lifecycle phase; G9 rollback phase is reserved for the socket driver",
    )
    parser.add_argument("--path", choices=capture_fixtures.G7_COMMIT_PATHS,
                        help="G7 turn-commit path: normal or enemy_batch")
    parser.add_argument("--boundary", choices=(capture_fixtures.G7_COMMIT_BOUNDARIES +
                                                   (capture_fixtures.G7_COMMIT_BOUNDARY_P4_NORMAL_ONLY,
                                                    "none")),
                        help="G7 turn-commit fault boundary")
    parser.add_argument(
        "--run-dir", default=None,
        help="unique G9/G10 evidence run directory under tmp/router-rollout/<gate>/<run-id>/",
    )
    parser.add_argument("--chain-id", default=None,
                        help="G10 identity shared by the complete and resume phase bundles")
    args = parser.parse_args(argv)
    gate = args.gate or capture_fixtures.infer_capture_gate(args.scenario) or "g3"
    if args.prepare:
        if args.party is None:
            parser.error("--party 1|4 is required with --prepare")
        try:
            if gate == "g4" and not args.scenario:
                parser.error("--gate g4 requires --scenario narrator-dialogue-travel|combat-smoke")
            if gate in capture_fixtures.G5_CAPTURE_GATES and not args.scenario:
                requirement = ("g5t-commander-p1|g5t-commander-p4" if gate == "g5t"
                               else "combat-smoke")
                parser.error("--gate %s requires --scenario %s" % (gate, requirement))
            if gate == "g7" and not args.scenario:
                parser.error("--gate g7 requires --scenario turn-commit")
            if gate == "g9" and not args.scenario:
                parser.error("--gate g9 requires --scenario %s" % "|".join(capture_fixtures.G9_SCENARIOS))
            if gate == "g9" and not args.run_dir:
                parser.error("--gate g9 --prepare requires a unique --run-dir")
            if gate == "g9" and args.phase:
                parser.error("G9 rollback uses --rollback-openai after prepare; do not prepare with --phase")
            if gate == "g10" and args.phase != "complete":
                parser.error("G10 prepares only --phase complete; resume uses the retained sandbox")
            if gate == "g10" and (not args.run_dir or not args.chain_id):
                parser.error("--gate g10 --prepare requires --run-dir and --chain-id")
            if gate not in ("g9", "g10") and args.run_dir:
                parser.error("--run-dir applies only with --gate g9 or g10")
            if gate != "g10" and args.chain_id:
                parser.error("--chain-id applies only with --gate g10")
            if gate == "g7" and args.phase in ("recover", "replay"):
                parser.error("G7 --phase %s uses retained state; do not prepare or reseed" % args.phase)
            if gate == "g7" and (args.path is None or args.phase is None or args.boundary is None):
                parser.error("--gate g7 requires --path, --boundary, and --phase")
            if gate != "g7" and (args.path or args.boundary):
                parser.error("--path/--boundary apply only with --gate g7")
            if args.scenario:
                capture_fixtures.build_gate_profile(
                    gate, args.scenario, args.party, args.branch or "", args.phase or "",
                    args.path or "", args.boundary or "",
                )
                if args.scenario == "resume-replay" and args.phase == "replay":
                    parser.error("resume-replay --phase replay uses the same prepared sandbox; do not prepare")
            elif args.branch or args.phase or args.path or args.boundary:
                parser.error("--branch/--phase/--path/--boundary require --scenario")
        except ValueError as exc:
            parser.error(str(exc))
        return prepare(args.party, args.scenario or "", args.branch or "", args.phase or "", gate,
                       args.path or "", args.boundary or "", args.run_dir or "", args.chain_id or "")
    if args.rollback_openai:
        if gate != "g9":
            parser.error("--rollback-openai requires --gate g9")
        if args.scenario != "preferred-openai-rollback":
            parser.error("--rollback-openai requires --scenario preferred-openai-rollback")
        if args.party is None:
            parser.error("--party 1|4 is required with --rollback-openai")
        if not args.run_dir:
            parser.error("--rollback-openai requires the same unique --run-dir used for prepare")
        if args.branch or args.phase or args.path or args.boundary:
            parser.error("--branch/--phase/--path/--boundary do not apply to --rollback-openai")
        try:
            return rollback_openai(args.scenario, args.party, args.run_dir)
        except ValueError as exc:
            parser.error(str(exc))
    if args.scenario or args.branch or args.phase or args.path or args.boundary or args.run_dir or args.chain_id:
        parser.error("--scenario/--branch/--phase/--path/--boundary apply only with --prepare")
    if gate != "g3":
        parser.error("--gate applies only with --prepare")
    return restore()


if __name__ == "__main__":
    raise SystemExit(main())
