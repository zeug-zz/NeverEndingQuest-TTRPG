# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Start the copied Capture Arena runtime in-process for one explicit arm."""

from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional, Sequence


SANDBOX_PORT = 8360
MAPPING_PILOT_MODULE = "Mapping_Pilot_Arena"
_SUPPORTED_ARMS = ("A", "B", "D")
_COMBAT_FIXTURE_ID = "combat_stage_tavern_zones"
_SUPPORTED_FIXTURE_IDS = (
    "interior_tavern",
    "landscape_village",
    "transition_tower_approach",
    _COMBAT_FIXTURE_ID,
)
_WEB_PORT_ASSIGNMENT = re.compile(r"^\s*WEB_PORT\s*=\s*(\d+)\s*(?:#.*)?$", re.MULTILINE)
_SECRET_FIELD = re.compile(
    r"(?:api[_-]?key|private[_-]?key|credential|secret|password|authorization|token)",
    re.IGNORECASE,
)


def _owning_project_root(source_file: str | Path) -> Path:
    source = Path(source_file).resolve(strict=True)
    parents = source.parents
    if (
        len(parents) >= 5
        and parents[2].name == "combat_capture"
        and parents[3].name == "tmp"
    ):
        return parents[4]
    if len(parents) < 3:
        raise ValueError("cannot resolve the mapping-pilot owning repository")
    return parents[2]


PROJECT_ROOT = _owning_project_root(__file__)


@dataclass(frozen=True)
class ValidatedSandbox:
    root: Path
    metadata: dict[str, Any]
    fixture_payloads: dict[str, dict[str, Any]]
    runtime_to_source: dict[str, str]


def validate_runtime_root(
    runtime_root: str | Path,
    *,
    project_root: Optional[str | Path] = None,
) -> Path:
    """Require the real, non-symlinked owning-repo ``tmp/combat_capture``."""
    owner = Path(project_root) if project_root is not None else PROJECT_ROOT
    try:
        owner = owner.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ValueError("mapping-pilot owning repository is unavailable") from exc
    requested = Path(runtime_root)
    if not requested.is_absolute():
        requested = Path.cwd() / requested
    if ".." in Path(runtime_root).parts:
        raise ValueError("mapping-pilot runtime root must not contain traversal")
    _reject_symlink_components(requested)
    expected = owner / "tmp" / "combat_capture"
    _reject_symlink_components(expected)
    try:
        resolved = requested.resolve(strict=True)
        expected_resolved = expected.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ValueError("mapping-pilot sandbox root is unavailable") from exc
    if not resolved.is_dir() or resolved != expected_resolved:
        raise ValueError(
            "runtime root must be exactly the owning repository tmp/combat_capture"
        )
    return resolved


def validate_sandbox(
    runtime_root: str | Path,
    *,
    arm: str,
    fixture_id: str,
    party_size: int,
    project_root: Optional[str | Path] = None,
) -> ValidatedSandbox:
    """Fail closed on path, arm, fixture, party, port, or seed metadata drift."""
    root = validate_runtime_root(runtime_root, project_root=project_root)
    if arm not in _SUPPORTED_ARMS:
        raise ValueError("mapping-pilot arm must be A, B, or D")
    if fixture_id not in _SUPPORTED_FIXTURE_IDS:
        raise ValueError("unsupported mapping-pilot fixture")
    if (
        isinstance(party_size, bool)
        or not isinstance(party_size, int)
        or party_size not in (1, 4)
    ):
        raise ValueError("mapping-pilot party size must be 1 or 4")

    config_path = _safe_file(root, "config.py")
    try:
        config_text = config_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ValueError("sandbox config is unavailable") from exc
    ports = _WEB_PORT_ASSIGNMENT.findall(config_text)
    if ports != [str(SANDBOX_PORT)]:
        raise ValueError("sandbox config must set exactly WEB_PORT = 8360")

    metadata = _read_json(root, "mapping_pilot/seed_metadata.json")
    if not isinstance(metadata, dict) or _contains_secret_field(metadata):
        raise ValueError("mapping-pilot seed metadata is invalid or contains a secret field")
    if (
        isinstance(metadata.get("format_version"), bool)
        or
        metadata.get("format_version") != 1
        or metadata.get("arm") != arm
        or metadata.get("fixture_id") != fixture_id
        or metadata.get("fixture_id") not in _SUPPORTED_FIXTURE_IDS
    ):
        raise ValueError("launcher arm or fixture does not match sandbox seed metadata")
    if arm == "B" and fixture_id == _COMBAT_FIXTURE_ID:
        raise ValueError("mapping-pilot arm B is not registered for combat")
    if isinstance(metadata.get("effective_seed"), bool) or not isinstance(
        metadata.get("effective_seed"), int
    ):
        raise ValueError("mapping-pilot effective seed metadata is invalid")
    counterbalance = metadata.get("counterbalance")
    if (
        not isinstance(counterbalance, Mapping)
        or not isinstance(counterbalance.get("row_id"), str)
        or not counterbalance.get("row_id")
        or isinstance(counterbalance.get("fixed_seed"), bool)
        or not isinstance(counterbalance.get("fixed_seed"), int)
        or counterbalance.get("fixed_seed") != metadata.get("effective_seed")
    ):
        raise ValueError("mapping-pilot counterbalance seed metadata is invalid")
    row_type = counterbalance.get("row_type")
    if row_type == "planned":
        if not isinstance(counterbalance.get("script"), str) or not counterbalance.get("script"):
            raise ValueError("mapping-pilot planned counterbalance metadata is invalid")
    elif row_type == "replacement_only":
        if (
            counterbalance.get("inherited_fixture_id") != fixture_id
            or counterbalance.get("inherited_arm") != arm
            or counterbalance.get("inherited_party") != party_size
            or not isinstance(counterbalance.get("inherited_script"), str)
            or not counterbalance.get("inherited_script")
        ):
            raise ValueError("mapping-pilot replacement counterbalance metadata is invalid")
    else:
        raise ValueError("mapping-pilot counterbalance row type is invalid")

    party = metadata.get("party")
    if not isinstance(party, Mapping):
        raise ValueError("mapping-pilot party metadata is invalid")
    members = party.get("members")
    if (
        isinstance(party.get("size"), bool)
        or
        party.get("size") != party_size
        or not isinstance(members, list)
        or len(members) != party_size
        or any(not isinstance(name, str) or not name.strip() for name in members)
        or len(set(members)) != len(members)
    ):
        raise ValueError("launcher party size does not match sandbox seed metadata")

    fixture_payloads: dict[str, dict[str, Any]] = {}
    for expected_fixture_id in _SUPPORTED_FIXTURE_IDS:
        expected_payload = _read_json(
            root,
            "mapping_pilot/expected/%s.json" % expected_fixture_id,
        )
        if (
            not isinstance(expected_payload, Mapping)
            or expected_payload.get("fixture_id") != expected_fixture_id
            or not isinstance(expected_payload.get("source_truth"), Mapping)
        ):
            raise ValueError("sandbox frozen fixture payload is invalid")
        source_truth = dict(expected_payload["source_truth"])
        if source_truth.get("fixture_id") != expected_fixture_id:
            raise ValueError("sandbox frozen fixture identity is inconsistent")
        fixture_payloads[expected_fixture_id] = source_truth

    id_map = _read_json(
        root,
        "modules/%s/location_id_map.json" % MAPPING_PILOT_MODULE,
    )
    id_map_values = id_map.get("runtime_location_ids") if isinstance(id_map, Mapping) else None
    if not isinstance(id_map_values, Mapping) or not id_map_values:
        raise ValueError("sandbox runtime location ID map is invalid")
    runtime_to_source: dict[str, str] = {}
    for source_id, runtime_id in id_map_values.items():
        if (
            not isinstance(source_id, str)
            or not isinstance(runtime_id, str)
            or not source_id
            or not runtime_id
            or runtime_id in runtime_to_source
        ):
            raise ValueError("sandbox runtime location ID map is invalid")
        runtime_to_source[runtime_id] = source_id

    mapping = metadata.get("mapping")
    selected_fixture = fixture_payloads[fixture_id]
    source_ids = selected_fixture.get("location_ids")
    runtime_location_id = mapping.get("runtime_location_id") if isinstance(mapping, Mapping) else None
    if (
        not isinstance(mapping, Mapping)
        or mapping.get("module") != MAPPING_PILOT_MODULE
        or not isinstance(source_ids, list)
        or len(source_ids) != 1
        or mapping.get("source_location_id") != source_ids[0]
        or not isinstance(runtime_location_id, str)
        or runtime_to_source.get(runtime_location_id) != source_ids[0]
    ):
        raise ValueError("mapping-pilot fixture and runtime location metadata conflict")
    if mapping.get("area_id") not in ("MPA001", "MPA002"):
        raise ValueError("mapping-pilot area metadata is invalid")

    tracker = _read_json(root, "party_tracker.json")
    if not isinstance(tracker, Mapping):
        raise ValueError("sandbox party tracker is invalid")
    world = tracker.get("worldConditions")
    if (
        tracker.get("module") != MAPPING_PILOT_MODULE
        or tracker.get("partyMembers") != members
        or tracker.get("active_character") not in members
        or not isinstance(world, Mapping)
        or world.get("currentLocationId") != mapping.get("runtime_location_id")
    ):
        raise ValueError("sandbox party tracker conflicts with seed metadata")
    if fixture_id == _COMBAT_FIXTURE_ID:
        combat_mapping = mapping.get("combat_actors")
        if (
            world.get("activeCombatEncounter") != "mapping_pilot_combat"
            or not isinstance(combat_mapping, Mapping)
            or combat_mapping.get("placement_scope") != "shadow_only"
        ):
            raise ValueError("combat fixture metadata is inconsistent")
    elif mapping.get("combat_actors") is not None:
        raise ValueError("non-combat fixture contains combat seed metadata")

    _validate_canonical_location(root, mapping)
    return ValidatedSandbox(root, metadata, fixture_payloads, runtime_to_source)


def launch(
    *,
    arm: str,
    fixture_id: str,
    party_size: int,
    runtime_root: Optional[str | Path] = None,
    known_ids: Optional[set[str]] = None,
    perceived_ids: Optional[set[str]] = None,
    movement_hint_observer: Optional[Callable[[Any], Any]] = None,
    module_importer: Optional[Callable[[str], Any]] = None,
    server_runner: Optional[Callable[[Any], Any]] = None,
    adapter_installer: Optional[Callable[..., Any]] = None,
) -> Any:
    """Import the sandbox app, patch it, and run its native Socket.IO server.

    The production path never invokes ``run_web.py``: its subprocess would lose
    these process-local replacements. Test hooks inject modules and the server
    callable without importing runtime owners or starting a listener.
    """
    selected_root = (
        Path(runtime_root)
        if runtime_root is not None
        else PROJECT_ROOT / "tmp" / "combat_capture"
    )
    validated = validate_sandbox(
        selected_root,
        arm=arm,
        fixture_id=fixture_id,
        party_size=party_size,
    )
    if (known_ids is None) != (perceived_ids is None):
        raise ValueError("known and perceived ID overrides must be supplied together")

    importer = module_importer or importlib.import_module
    previous_cwd = Path.cwd()
    previous_sys_path = list(sys.path)
    previous_browser_flag = os.environ.get("NEQ_OPEN_BROWSER")
    installation = None
    try:
        # Set headless mode and sandbox import precedence before importing the
        # web application, main.py, combat prompt owners, or provider factories.
        os.environ["NEQ_OPEN_BROWSER"] = "0"
        os.chdir(validated.root)
        sys.path.insert(0, str(validated.root))

        web_interface = importer("web.web_interface")
        _require_runtime_module(web_interface, validated.root / "web" / "web_interface.py")
        main_module = getattr(web_interface, "dm_main", None)
        _require_runtime_module(main_module, validated.root / "main.py")
        combat_prompts_module = importer("core.combat.prompts")
        _require_runtime_module(
            combat_prompts_module, validated.root / "core" / "combat" / "prompts.py"
        )
        combat_manager_module = importer("core.combat.combat_manager")
        _require_runtime_module(
            combat_manager_module,
            validated.root / "core" / "combat" / "combat_manager.py",
        )
        adapter_module = importer("scripts.mapping_pilot.adapter")
        _require_runtime_module(
            adapter_module, validated.root / "scripts" / "mapping_pilot" / "adapter.py"
        )

        packet_provider = adapter_module.SandboxPacketProvider(
            runtime_root=validated.root,
            metadata=validated.metadata,
            fixture_payloads=validated.fixture_payloads,
            runtime_to_source=validated.runtime_to_source,
            explicit_known_ids=known_ids,
            explicit_perceived_ids=perceived_ids,
        )
        install = adapter_installer or adapter_module.install_adapter
        installation = install(
            arm=arm,
            main_module=main_module,
            combat_prompts_module=combat_prompts_module,
            packet_provider=packet_provider,
            combat_manager_module=combat_manager_module,
            movement_hint_observer=(
                movement_hint_observer or _ignore_movement_hint_observation
                if arm == "D"
                else None
            ),
            fixture_id=fixture_id,
            runtime_root=validated.root,
        )
        if getattr(web_interface, "INSTALL_ROOT", None) is None or Path(
            web_interface.INSTALL_ROOT
        ).resolve(strict=True) != validated.root:
            raise ValueError("web interface did not resolve to the validated sandbox")
        if getattr(web_interface, "_configured_web_port", None) != SANDBOX_PORT:
            raise ValueError("web interface did not resolve to sandbox port 8360")
        runner = server_runner or _run_web_interface
        return runner(web_interface)
    finally:
        if installation is not None:
            installation.uninstall()
        sys.path[:] = previous_sys_path
        try:
            os.chdir(previous_cwd)
        finally:
            if previous_browser_flag is None:
                os.environ.pop("NEQ_OPEN_BROWSER", None)
            else:
                os.environ["NEQ_OPEN_BROWSER"] = previous_browser_flag


def _run_web_interface(web_interface: Any) -> Any:
    """Call the web interface's native server entry point in this process."""
    _safe_directory_create(
        Path(web_interface.INSTALL_ROOT).resolve(strict=True), "templates"
    )
    if os.environ.get("NEQ_OPEN_BROWSER") != "0":
        raise ValueError("sandbox launch must remain headless")
    return web_interface.socketio.run(
        web_interface.app,
        host=web_interface.WEB_HOST,
        port=SANDBOX_PORT,
        debug=False,
        use_reloader=False,
        allow_unsafe_werkzeug=True,
    )


def _ignore_movement_hint_observation(_observation: Any) -> None:
    """Default no-op observer; task 9 injects a shadow-ledger callback."""


def _require_runtime_module(module: Any, expected_path: Path) -> None:
    module_path = getattr(module, "__file__", None)
    if not isinstance(module_path, (str, os.PathLike)):
        raise ValueError("sandbox runtime module has no source path")
    try:
        actual = Path(module_path).resolve(strict=True)
        expected = expected_path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ValueError("sandbox runtime module source is unavailable") from exc
    if actual != expected:
        raise ValueError("runtime module did not load from the validated sandbox")


def _validate_canonical_location(root: Path, mapping: Mapping[str, Any]) -> None:
    module_dir = _safe_directory(root, "modules/" + MAPPING_PILOT_MODULE)
    areas_dir = _safe_directory(module_dir, "areas")
    runtime_location_id = mapping.get("runtime_location_id")
    area_matches: list[str] = []
    for area_path in sorted(areas_dir.glob("*.json")):
        if area_path.name.endswith("_BU.json"):
            continue
        if area_path.is_symlink():
            raise ValueError("sandbox canonical area path is unsafe")
        area = _read_json_path(area_path)
        if not isinstance(area, Mapping):
            continue
        if any(
            isinstance(location, Mapping)
            and location.get("locationId") == runtime_location_id
            for location in area.get("locations", [])
        ):
            area_matches.append(str(area.get("areaId", "")))
    if area_matches != [str(mapping.get("area_id", ""))]:
        raise ValueError("sandbox canonical location does not match seed metadata")


def _read_json(root: Path, relative_path: str) -> Any:
    return _read_json_path(_safe_file(root, relative_path))


def _read_json_path(path: Path) -> Any:
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError("sandbox JSON input is invalid") from exc


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> Any:
    raise ValueError("non-standard JSON value")


def _contains_secret_field(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(
            _SECRET_FIELD.search(str(key)) or _contains_secret_field(child)
            for key, child in value.items()
        )
    if isinstance(value, list):
        return any(_contains_secret_field(child) for child in value)
    return False


def _safe_file(root: Path, relative_path: str) -> Path:
    raw = Path(relative_path)
    if raw.is_absolute() or ".." in raw.parts or "\\" in relative_path:
        raise ValueError("sandbox path is unsafe")
    current = root
    for part in raw.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("sandbox path is unsafe")
    try:
        resolved = current.resolve(strict=True)
        resolved.relative_to(root.resolve(strict=True))
    except (OSError, RuntimeError, ValueError) as exc:
        raise ValueError("sandbox path is unsafe") from exc
    if not resolved.is_file():
        raise ValueError("sandbox file is unavailable")
    return resolved


def _safe_directory(root: Path, relative_path: str) -> Path:
    raw = Path(relative_path)
    if raw.is_absolute() or ".." in raw.parts or "\\" in relative_path:
        raise ValueError("sandbox path is unsafe")
    current = root
    for part in raw.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("sandbox path is unsafe")
    try:
        resolved = current.resolve(strict=True)
        resolved.relative_to(root.resolve(strict=True))
    except (OSError, RuntimeError, ValueError) as exc:
        raise ValueError("sandbox path is unsafe") from exc
    if not resolved.is_dir():
        raise ValueError("sandbox directory is unavailable")
    return resolved


def _safe_directory_create(root: Path, relative_path: str) -> Path:
    raw = Path(relative_path)
    if raw.is_absolute() or ".." in raw.parts or "\\" in relative_path:
        raise ValueError("sandbox path is unsafe")
    current = root
    for part in raw.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("sandbox path is unsafe")
    try:
        current.resolve(strict=False).relative_to(root.resolve(strict=True))
    except (OSError, RuntimeError, ValueError) as exc:
        raise ValueError("sandbox path is unsafe") from exc
    current.mkdir(parents=True, exist_ok=True)
    return current


def _reject_symlink_components(path: Path) -> None:
    absolute = Path(os.path.abspath(path))
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current = current / part
        try:
            if current.is_symlink():
                raise ValueError("mapping-pilot paths must not traverse symlinks")
        except OSError as exc:
            raise ValueError("mapping-pilot path cannot be inspected") from exc


def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Launch one mapping-pilot arm inside tmp/combat_capture."
    )
    parser.add_argument("--arm", choices=("A", "B", "D"), required=True)
    parser.add_argument("--fixture-id", choices=(
        "interior_tavern",
        "landscape_village",
        "transition_tower_approach",
        "combat_stage_tavern_zones",
    ), required=True)
    parser.add_argument("--party-size", type=int, choices=(1, 4), required=True)
    parser.add_argument(
        "--runtime-root",
        default=str(PROJECT_ROOT / "tmp" / "combat_capture"),
        help="must resolve exactly to this repository's tmp/combat_capture",
    )
    parser.add_argument("--known-id", action="append", dest="known_ids")
    parser.add_argument("--perceived-id", action="append", dest="perceived_ids")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse_args(argv)
    known_ids = set(args.known_ids) if args.known_ids else None
    perceived_ids = set(args.perceived_ids) if args.perceived_ids else None
    launch(
        arm=args.arm,
        fixture_id=args.fixture_id,
        party_size=args.party_size,
        runtime_root=args.runtime_root,
        known_ids=known_ids,
        perceived_ids=perceived_ids,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
