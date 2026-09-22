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
from typing import Any, Dict, List, Optional, Sequence, Tuple


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS_DIR = Path(__file__).resolve().parent
for _bootstrap_path in (_PROJECT_ROOT, _SCRIPTS_DIR):
    if str(_bootstrap_path) not in sys.path:
        sys.path.insert(0, str(_bootstrap_path))

# The fixture payload builders are the canonical fixed roster/encounter shapes.
# Reuse them by import; the fixtures module is intentionally never modified.
import combat_latency_fixtures as capture_fixtures  # noqa: E402
from utils.file_operations import safe_write_json  # noqa: E402
from utils.module_path_manager import ModulePathManager  # noqa: E402


PROJECT_ROOT = _PROJECT_ROOT
SANDBOX_ROOT = PROJECT_ROOT / "tmp" / "combat_capture"
SANDBOX_DISPLAY = "tmp/combat_capture"
SANDBOX_PORT = 8360
SANDBOX_PORT_LITERAL = "WEB_PORT = %d" % SANDBOX_PORT
TRACE_GATE_LITERAL = "ENABLE_COMBAT_TURN_TRACE = True"
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


def _patch_sandbox_model_config() -> None:
    model_config_path = _assert_sandbox_path(SANDBOX_ROOT / "model_config.py")
    text = model_config_path.read_text(encoding="utf-8")
    if len(_MODEL_TRACE_PATTERN.findall(text)) != 1:
        raise RuntimeError(
            "expected exactly one ENABLE_COMBAT_TURN_TRACE = False in sandbox model_config.py"
        )
    updated = _MODEL_TRACE_PATTERN.sub(TRACE_GATE_LITERAL, text, count=1)
    if TRACE_GATE_LITERAL not in updated:
        raise RuntimeError("sandbox ENABLE_COMBAT_TURN_TRACE patch did not apply")
    model_config_path.write_text(updated, encoding="utf-8")


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


def _build_encounter(
    party_names: List[str], party_size: int
) -> Tuple[Dict[str, Any], str]:
    if party_size == PARTY_SIZE_FOUR:
        base_payload = capture_fixtures._encounter_payload()
        encounter_id = "capture_mp"
    else:
        base_payload = capture_fixtures._one_pc_encounter_payload()
        encounter_id = "capture_one_pc"
    encounter = json.loads(json.dumps(base_payload))
    encounter["id"] = encounter_id
    encounter["encounterId"] = encounter_id
    pc_creatures = [
        _pc_creature(name, _party_initiative(name, party_size)) for name in party_names
    ]
    encounter["creatures"] = pc_creatures + list(encounter.get("creatures", []))
    return encounter, encounter_id


def _build_party_tracker(
    reference: Dict[str, str], party_names: List[str], encounter_id: str
) -> Dict[str, Any]:
    return {
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
    reference: Dict[str, str], party_names: List[str], party_size: int
) -> str:
    path_manager = ModulePathManager(reference["module"])
    for name in party_names:
        character_relative = path_manager.get_character_unified_path(name)
        _write_json(
            character_relative,
            capture_fixtures._character_payload(name, _party_initiative(name, party_size)),
        )

    encounter, encounter_id = _build_encounter(party_names, party_size)
    _write_json("modules/encounters/encounter_%s.json" % encounter_id, encounter)

    tracker = _build_party_tracker(reference, party_names, encounter_id)
    _write_json("party_tracker.json", tracker)
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


def prepare(party_size: int) -> int:
    """Rebuild the sandbox from scratch and seed it for the capture run."""
    logging.getLogger("utils.file_operations").setLevel(logging.WARNING)
    _assert_sandbox_root()
    installed_before = _hash_installed_sentinels()

    if SANDBOX_ROOT.exists():
        shutil.rmtree(_assert_sandbox_root())
    SANDBOX_ROOT.mkdir(parents=True, exist_ok=False)

    copied = _copy_runtime()
    _patch_sandbox_config()
    _patch_sandbox_model_config()
    reference = _read_capture_arena_reference()
    party_names = _party_names(party_size)
    _create_sandbox_dirs()
    encounter_id = _seed_party(reference, party_names, party_size)

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
    print(
        "[PATCH] config.py %s; model_config.py %s" % (SANDBOX_PORT_LITERAL, TRACE_GATE_LITERAL)
    )
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
    parser.add_argument(
        "--party",
        type=int,
        choices=(PARTY_SIZE_ONE, PARTY_SIZE_FOUR),
        default=None,
        help="party size to seed (required with --prepare; ignored with --restore)",
    )
    args = parser.parse_args(argv)
    if args.prepare:
        if args.party is None:
            parser.error("--party 1|4 is required with --prepare")
        return prepare(args.party)
    return restore()


if __name__ == "__main__":
    raise SystemExit(main())
