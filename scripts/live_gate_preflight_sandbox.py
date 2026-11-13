# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Prepare one isolated SP3 fixture-party sandbox without loading config.py.

This tool only copies and seeds files below tmp/combat_capture. It does not
launch Python, a host, a driver, a server, or a native companion. The later
profile runner owns the guarded host lifecycle and port lock. Seeding requires
the internally planned worker invocation to match the declared intended
command, working directory, and PYTHONPATH.
"""

from __future__ import annotations

import argparse
import copy
import fnmatch
import json
import os
import re
import shutil
import stat
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

from scripts.live_gate_preflight_safety import (
    InvocationIdentityMismatch,
    SANDBOX_PROVIDER_KEY_PLACEHOLDER,
    run_after_invocation_identity,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SANDBOX_RELATIVE = Path("tmp/combat_capture")
MAPPING_MODULE = "Mapping_Pilot_Arena"
_FIXTURE_IDS = (
    "interior_tavern",
    "landscape_village",
    "transition_tower_approach",
    "combat_stage_tavern_zones",
)
_PARTY_SIZES = (1, 4)
_SOURCE_SHA = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_CHECKPOINT_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SOURCE_FILES = (
    "main.py",
    "run_web.py",
    "model_config.py",
    "debug_config.py",
    "VERSION",
    "dm_logo.png",
)
_REQUIRED_SOURCE_FILES = {"main.py", "run_web.py", "model_config.py"}
_SOURCE_DIRECTORIES = (
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
_REQUIRED_SOURCE_DIRECTORIES = {
    "core", "utils", "updates", "web", "prompts", "schemas", "scripts"
}
_DATA_DIRECTORIES = ("data/bestiary", "data/styles")
_DATA_FILES = (
    "data/spell_repository.json",
    "data/active_pack.json",
    "data/style_templates.json",
)
_COMMON_IGNORES = ("__pycache__", "*.pyc", "*.pyo", ".pytest_cache", ".DS_Store")
_TREE_IGNORES = {
    "web": ("monsters_backup", "videos", "*_video.mp4", "node_modules"),
    "scripts": ("tmp", "test_*.py"),
}
_SYNTHETIC_CONFIG = '''# Synthetic provider-free sandbox configuration.
import re as _re
import model_config as _model_config

_secret_name = _re.compile(
    r"(?:API[_-]?KEY|SECRET|TOKEN|PASSWORD|CREDENTIAL|AUTH)", _re.IGNORECASE
)
for _name in dir(_model_config):
    if not _name.startswith("_") and not _secret_name.search(_name):
        globals()[_name] = getattr(_model_config, _name)

OPENAI_API_KEY = "preflight-stub-not-a-key"
OPENROUTER_API_KEY = "preflight-stub-not-a-key"
ANTHROPIC_API_KEY = "preflight-stub-not-a-key"
GOOGLE_API_KEY = "preflight-stub-not-a-key"
GEMINI_API_KEY = "preflight-stub-not-a-key"
MISTRAL_API_KEY = "preflight-stub-not-a-key"
COHERE_API_KEY = "preflight-stub-not-a-key"
MODULES_DIR = "modules"
DEFAULT_MODULE = "Mapping_Pilot_Arena"
EXCHANGE_RATE_API_URL = ""
EXCHANGE_RATE_TARGET_CURRENCY = "NZD"
EXCHANGE_RATE_TIMEOUT_SECONDS = 5
ENABLE_LIVE_EXCHANGE_RATE = False
MULTIPLAYER_MODE = True
WEB_PORT = 8360
WEB_HOST = "127.0.0.1"
WEB_CORS_ALLOWED_ORIGINS = []
DEBUG_STATUS_SYNC = False
'''
_PREPARATION_STARTUP_GUARD_VERIFIED = False


class SandboxPreparationError(RuntimeError):
    """Raised when a requested isolated sandbox cannot be prepared safely."""


@dataclass(frozen=True)
class PlannedWorkerInvocation:
    """Trusted worker launch plan derived from validated fixture/run inputs."""

    fixture_id: str
    party_size: int
    lifecycle: str
    source_sha: str
    run_id: str
    planned_row_id: str
    arm: str
    command: tuple[str, ...]
    working_directory: str
    pythonpath: str

    def identity(self) -> dict[str, Any]:
        return {
            "command": list(self.command),
            "working_directory": self.working_directory,
            "pythonpath": self.pythonpath,
        }


def _relative_path(value: str | Path, label: str) -> PurePosixPath:
    raw = PurePosixPath(str(value))
    if raw.is_absolute() or ".." in raw.parts or "\\" in str(value) or not raw.parts:
        raise SandboxPreparationError(label + " path is unsafe")
    return raw


def _project_root(value: str | Path) -> Path:
    requested = Path(value)
    if requested.is_symlink():
        raise SandboxPreparationError("project root must not be a symlink")
    try:
        root = requested.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise SandboxPreparationError("project root is unavailable") from exc
    if not root.is_dir():
        raise SandboxPreparationError("project root is unavailable")
    return root


def _assert_no_symlink_path(root: Path, relative: str | Path, label: str) -> Path:
    raw = _relative_path(relative, label)
    cursor = root
    for part in raw.parts:
        cursor = cursor / part
        try:
            if cursor.is_symlink():
                raise SandboxPreparationError(label + " path traverses a symlink")
        except OSError as exc:
            raise SandboxPreparationError(label + " path cannot be inspected") from exc
    return cursor


def _target_path(project_root: str | Path) -> tuple[Path, Path]:
    root = _project_root(project_root)
    tmp_root = root / "tmp"
    if tmp_root.is_symlink() or not tmp_root.is_dir():
        raise SandboxPreparationError("project tmp/ must be an existing non-symlink directory")
    candidate = _assert_no_symlink_path(root, SANDBOX_RELATIVE, "sandbox")
    try:
        candidate.absolute().relative_to(tmp_root.absolute())
    except ValueError as exc:
        raise SandboxPreparationError("sandbox must stay below project tmp/") from exc
    if candidate.exists() or candidate.is_symlink():
        raise SandboxPreparationError("sandbox already exists; refusing to replace it")
    return root, candidate


def _require_preparation_startup_guard() -> None:
    """Fail closed unless the dedicated preflight guard ran at interpreter startup."""
    global _PREPARATION_STARTUP_GUARD_VERIFIED
    if _PREPARATION_STARTUP_GUARD_VERIFIED:
        return

    try:
        root = _project_root(PROJECT_ROOT)
        from scripts.live_gate_preflight_safety import (
            expected_guarded_pythonpath,
            require_sanitized_environment,
            require_startup_guard_from,
        )

        if os.environ.get("PYTHONPATH") != expected_guarded_pythonpath(root):
            raise ValueError("preflight PYTHONPATH identity differs")
        tmp_root = root / "tmp"
        if tmp_root.is_symlink() or not tmp_root.is_dir():
            raise ValueError("project tmp is unavailable")
        cwd = Path.cwd().resolve(strict=True)
        cwd.relative_to(tmp_root.resolve(strict=True))
        sitecustomize_path = root / "scripts" / "live_gate_preflight_guard" / "sitecustomize.py"
        expected_sitecustomize = _source_file(
            root, "scripts/live_gate_preflight_guard/sitecustomize.py", required=True
        )
        source_sitecustomize = _source_file(root, "scripts/sitecustomize.py", required=True)
        expected_network_guard = _source_file(
            root, "scripts/live_gate_preflight_safety.py", required=True
        )
        if expected_sitecustomize is None or source_sitecustomize is None or expected_network_guard is None:
            raise ValueError("dedicated preflight guard sources are unavailable")

        startup_module = sys.modules.get("sitecustomize")
        startup_origin = getattr(startup_module, "__file__", None)
        if not isinstance(startup_origin, (str, os.PathLike)):
            raise ValueError("interpreter startup hook is unavailable")
        if Path(startup_origin).resolve(strict=True) != sitecustomize_path.resolve(strict=True):
            raise ValueError("interpreter startup hook is not the dedicated guard")
        if sitecustomize_path.read_bytes() != expected_sitecustomize.read_bytes():
            raise ValueError("dedicated preflight guard source identity differs")
        source_guard_module = sys.modules.get("scripts.sitecustomize")
        if (
            Path(getattr(source_guard_module, "__file__", "")).resolve(strict=True)
            != source_sitecustomize
        ):
            raise ValueError("preflight guard implementation source differs")
        safety_module = sys.modules.get("scripts.live_gate_preflight_safety")
        if (
            Path(getattr(safety_module, "__file__", "")).resolve(strict=True)
            != expected_network_guard
        ):
            raise ValueError("preflight safety implementation source differs")
        config_origin_guard = getattr(
            source_guard_module, "_CONFIG_IMPORT_ORIGIN_GUARD", None
        )
        if (
            config_origin_guard is None
            or config_origin_guard not in sys.meta_path
            or getattr(config_origin_guard, "project_root", None) != root
            or "config" in sys.modules
        ):
            raise ValueError("preparation config import origin guard is unavailable")

        require_startup_guard_from(sitecustomize_path)
        require_sanitized_environment()
    except (OSError, RuntimeError, ValueError, ImportError) as exc:
        raise SandboxPreparationError(
            "preparation_requires_dedicated_startup_guard"
        ) from exc

    _PREPARATION_STARTUP_GUARD_VERIFIED = True


def _source_file(root: Path, relative: str | Path, *, required: bool) -> Path | None:
    candidate = _assert_no_symlink_path(root, relative, "source")
    if not candidate.exists():
        if required:
            raise SandboxPreparationError("required runtime source is missing")
        return None
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
        metadata = resolved.stat()
    except (OSError, RuntimeError, ValueError) as exc:
        raise SandboxPreparationError("runtime source is missing or escapes project") from exc
    if not stat.S_ISREG(metadata.st_mode):
        raise SandboxPreparationError("runtime source is not a regular file")
    return resolved


def _sandbox_destination(root: Path, relative: str | Path) -> Path:
    raw = _relative_path(relative, "sandbox output")
    destination = _assert_no_symlink_path(root, raw, "sandbox output")
    try:
        destination.absolute().relative_to(root.absolute())
    except ValueError as exc:
        raise SandboxPreparationError("sandbox output escapes the isolated copy") from exc
    return destination


def _copy_file(root: Path, sandbox: Path, relative: str, *, required: bool) -> None:
    if relative in ("config.py", "config_template.py"):
        raise SandboxPreparationError("project configuration files must not be copied")
    source = _source_file(root, relative, required=required)
    if source is None:
        return
    destination = _sandbox_destination(sandbox, relative)
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(source, destination)
    except OSError as exc:
        raise SandboxPreparationError("runtime source copy failed") from exc


def _ignored(relative: str, name: str) -> bool:
    patterns = _COMMON_IGNORES + _TREE_IGNORES.get(relative.split("/", 1)[0], ())
    return any(fnmatch.fnmatch(name, pattern) for pattern in patterns)


def _copy_tree(root: Path, sandbox: Path, relative: str, *, required: bool) -> None:
    source = _assert_no_symlink_path(root, relative, "runtime directory")
    if not source.exists():
        if required:
            raise SandboxPreparationError("required runtime directory is missing")
        return
    try:
        resolved_source = source.resolve(strict=True)
        resolved_source.relative_to(root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise SandboxPreparationError("runtime directory is missing or escapes project") from exc
    if not resolved_source.is_dir():
        raise SandboxPreparationError("runtime source is not a directory")

    relative_root = PurePosixPath(relative)
    destination_root = _sandbox_destination(sandbox, relative_root)
    destination_root.mkdir(parents=True, exist_ok=True)
    pending = [(resolved_source, destination_root, relative_root.as_posix())]
    while pending:
        current_source, current_destination, current_relative = pending.pop()
        try:
            entries = sorted(os.scandir(current_source), key=lambda entry: entry.name)
        except OSError as exc:
            raise SandboxPreparationError("runtime directory cannot be read") from exc
        for entry in entries:
            if entry.is_symlink():
                raise SandboxPreparationError("runtime source tree contains a symlink")
            if _ignored(current_relative, entry.name):
                continue
            source_path = Path(entry.path)
            child_relative = current_relative + "/" + entry.name
            destination = _sandbox_destination(sandbox, child_relative)
            try:
                metadata = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise SandboxPreparationError("runtime source entry cannot be inspected") from exc
            if stat.S_ISDIR(metadata.st_mode):
                destination.mkdir(parents=True, exist_ok=True)
                pending.append((source_path, destination, child_relative))
            elif stat.S_ISREG(metadata.st_mode):
                destination.parent.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.copy2(source_path, destination)
                except OSError as exc:
                    raise SandboxPreparationError("runtime source tree copy failed") from exc
            else:
                raise SandboxPreparationError("runtime source tree contains a special file")


def _copy_runtime(root: Path, sandbox: Path) -> None:
    for relative in _SOURCE_FILES:
        _copy_file(root, sandbox, relative, required=relative in _REQUIRED_SOURCE_FILES)
    for relative in _SOURCE_DIRECTORIES:
        _copy_tree(root, sandbox, relative, required=relative in _REQUIRED_SOURCE_DIRECTORIES)
    for relative in _DATA_DIRECTORIES:
        _copy_tree(root, sandbox, relative, required=False)
    for relative in _DATA_FILES:
        _copy_file(root, sandbox, relative, required=False)
    _copy_tree(root, sandbox, "modules/Capture_Arena", required=True)


def _write_file(sandbox: Path, relative: str | Path, content: bytes) -> Path:
    destination = _sandbox_destination(sandbox, relative)
    destination.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(destination, flags, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as exc:
        raise SandboxPreparationError("sandbox output already exists") from exc
    except OSError as exc:
        raise SandboxPreparationError("sandbox output could not be written") from exc
    return destination


def _write_json(sandbox: Path, relative: str | Path, payload: Mapping[str, Any]) -> Path:
    from utils.file_operations import safe_write_json

    destination = _sandbox_destination(sandbox, relative)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not safe_write_json(
        str(destination),
        dict(payload),
        create_backup=False,
        acquire_lock=False,
        json_kwargs={"ensure_ascii": True, "sort_keys": True, "allow_nan": False},
    ):
        raise SandboxPreparationError("sandbox JSON output could not be written")
    return destination


def _runtime_location(
    module_payloads: Mapping[str, Mapping[str, Any]], runtime_location_id: str
) -> tuple[str, Mapping[str, Any], Mapping[str, Any]]:
    matches: list[tuple[str, Mapping[str, Any], Mapping[str, Any]]] = []
    for relative, area in module_payloads.items():
        if not relative.startswith("areas/") or relative.endswith("_BU.json"):
            continue
        locations = area.get("locations")
        if not isinstance(locations, list):
            continue
        for location in locations:
            if isinstance(location, Mapping) and location.get("locationId") == runtime_location_id:
                matches.append((str(area.get("areaId") or ""), area, location))
    if len(matches) != 1 or not matches[0][0]:
        raise SandboxPreparationError("selected fixture location is missing or duplicated")
    return matches[0]


def _write_fixture_module(
    sandbox: Path,
    plan: Mapping[str, Any],
    module_payloads: Mapping[str, Mapping[str, Any]],
    expected_payloads: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    from scripts.mapping_pilot.fixtures import FIXTURE_FILES

    fixture_id = str(plan["fixture_id"])
    runtime_location_id = str(plan["runtime_location_id"])
    area_id, area, location = _runtime_location(module_payloads, runtime_location_id)
    written: dict[str, Any] = {}
    for relative, source_payload in module_payloads.items():
        payload = copy.deepcopy(dict(source_payload))
        if relative == "map_%s.json" % area_id:
            payload["startRoom"] = runtime_location_id
        path = "modules/%s/%s" % (MAPPING_MODULE, relative)
        _write_json(sandbox, path, payload)
        written[relative] = payload

    expected_root = Path("mapping_pilot") / "expected"
    for expected_fixture_id, relative_source in FIXTURE_FILES.items():
        payload = expected_payloads.get(expected_fixture_id)
        if (
            not isinstance(payload, Mapping)
            or payload.get("fixture_id") != expected_fixture_id
            or payload.get("source_file") != relative_source
        ):
            raise SandboxPreparationError("verified expected fixture payload is incomplete")
        _write_json(
            sandbox,
            expected_root / (expected_fixture_id + ".json"),
            payload,
        )

    mapping = {
        "module": MAPPING_MODULE,
        "source_location_id": plan["source_location_id"],
        "runtime_location_id": runtime_location_id,
        "area_id": area_id,
        "area_name": str(area.get("areaName") or ""),
        "location_name": str(location.get("name") or ""),
        "id_map_file": "modules/%s/location_id_map.json" % MAPPING_MODULE,
    }
    if fixture_id not in expected_payloads:
        raise SandboxPreparationError("selected fixture is absent from verified inputs")
    return {"mapping": mapping, "module_payloads": written}


def _write_seed_state(
    project_root: Path,
    sandbox: Path,
    plan: Mapping[str, Any],
    module_payloads: Mapping[str, Mapping[str, Any]],
    mapping: dict[str, Any],
) -> dict[str, Any]:
    from scripts import seed_combat_capture as capture_seed
    from scripts import combat_latency_fixtures as capture_fixtures

    party_size = int(plan["party_size"])
    party_names = capture_seed._party_names(party_size)
    for name in party_names:
        character = capture_fixtures.build_capture_character_payload(
            name, capture_seed._party_initiative(name, party_size)
        )
        _write_json(sandbox, capture_seed._capture_character_path(name), character)

    reference_area, reference, _location = _runtime_location(
        module_payloads, str(plan["runtime_location_id"])
    )
    reference_payload = {
        "module": MAPPING_MODULE,
        "area_id": reference_area,
        "area_name": str(reference.get("areaName") or ""),
        "start_location_id": str(plan["runtime_location_id"]),
        "start_location_name": str(_location.get("name") or ""),
    }
    encounter_id = ""
    if plan["fixture_id"] == "combat_stage_tavern_zones":
        encounter, combat_mapping = capture_seed._build_mapping_pilot_combat_encounter(
            party_names, party_size, dict(plan["fixture"])
        )
        encounter_id = str(encounter["encounterId"])
        _write_json(
            sandbox,
            "modules/encounters/encounter_%s.json" % encounter_id,
            encounter,
        )
        mapping["combat_actors"] = combat_mapping
        goblin_source = _source_file(
            project_root,
            "modules/Capture_Arena/monsters/goblin.json",
            required=True,
        )
        if goblin_source is None:
            raise SandboxPreparationError("combat monster template is unavailable")
        goblin_payload = json.loads(goblin_source.read_text(encoding="utf-8"))
        if not isinstance(goblin_payload, Mapping) or goblin_payload.get("name") != "Goblin":
            raise SandboxPreparationError("combat monster template identity is invalid")
        _write_json(
            sandbox,
            "modules/%s/monsters/goblin.json" % MAPPING_MODULE,
            goblin_payload,
        )

    tracker = capture_seed._build_party_tracker(
        reference_payload, party_names, encounter_id
    )
    _write_json(sandbox, "party_tracker.json", tracker)
    counterbalance = dict(plan["counterbalance"])
    metadata = {
        "format_version": 1,
        "effective_seed": int(plan["effective_seed"]),
        "arm": str(plan["arm"]),
        "fixture_id": str(plan["fixture_id"]),
        "party": {"size": party_size, "members": list(party_names)},
        "counterbalance": counterbalance,
        "mapping": mapping,
    }
    _write_json(sandbox, "mapping_pilot/seed_metadata.json", metadata)
    return metadata


def _prepare_new_sandbox(
    project_root: str | Path,
    plan: Mapping[str, Any],
    module_payloads: Mapping[str, Mapping[str, Any]],
    expected_payloads: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    root, sandbox = _target_path(project_root)
    if (
        plan.get("fixture_id") not in _FIXTURE_IDS
        or type(plan.get("party_size")) is not int
        or plan.get("party_size") not in _PARTY_SIZES
        or not isinstance(plan.get("counterbalance"), Mapping)
        or plan["counterbalance"].get("row_type") != "planned"
        or str(plan["counterbalance"].get("row_id", "")).startswith("R")
        or plan["counterbalance"].get("party") not in (None, plan["party_size"])
        or plan["counterbalance"].get("fixed_seed") != plan.get("effective_seed")
    ):
        raise SandboxPreparationError("fixture-party seed identity is invalid")

    sandbox.mkdir(mode=0o700, parents=False, exist_ok=False)
    try:
        _copy_runtime(root, sandbox)
        _write_file(sandbox, "config.py", _SYNTHETIC_CONFIG.encode("ascii"))
        written_module = _write_fixture_module(
            sandbox, plan, module_payloads, expected_payloads
        )
        metadata = _write_seed_state(
            root,
            sandbox,
            plan,
            written_module["module_payloads"],
            written_module["mapping"],
        )
        from scripts.mapping_pilot.launcher import validate_sandbox

        validate_sandbox(
            sandbox,
            arm=str(plan["arm"]),
            fixture_id=str(plan["fixture_id"]),
            party_size=int(plan["party_size"]),
            project_root=root,
        )
        config_path = sandbox / "config.py"
        if (
            config_path.is_symlink()
            or not config_path.is_file()
            or config_path.read_bytes() != _SYNTHETIC_CONFIG.encode("ascii")
        ):
            raise SandboxPreparationError("synthetic sandbox config identity is invalid")
    except BaseException:
        if not sandbox.is_symlink() and sandbox.exists():
            shutil.rmtree(sandbox)
        raise

    return {
        "status": "prepared",
        "sandbox_root": "tmp/combat_capture",
        "fixture_id": metadata["fixture_id"],
        "party_size": metadata["party"]["size"],
        "planned_row_id": metadata["counterbalance"]["row_id"],
        "arm": metadata["arm"],
        "effective_seed": metadata["effective_seed"],
        "profile_id": "%s:p%d" % (metadata["fixture_id"], metadata["party"]["size"]),
        "config_source": "synthetic",
        "sandbox_provider_key_placeholder": SANDBOX_PROVIDER_KEY_PLACEHOLDER,
        "real_project_config_read_or_copied": False,
        "native_companion_started": False,
        "host_started": False,
    }


def _load_profile_seed_plan(
    fixture_id: str, party_size: int, planned_row_id: str | None
) -> tuple[dict[str, Any], dict[str, Any]]:
    from scripts.live_gate_preflight_profiles import (
        PREREG_ROOT,
        _safe_source_path,
        copy_profile_document,
        load_profile_coverage,
    )

    if fixture_id not in _FIXTURE_IDS or type(party_size) is not int or party_size not in _PARTY_SIZES:
        raise SandboxPreparationError("unsupported fixture-party selection")
    coverage = load_profile_coverage()
    if coverage["fixture_party_pair_count"] != 8 or coverage["replacement_only_rows_activated"]:
        raise SandboxPreparationError("source-bound profile coverage is invalid")
    document = copy_profile_document()
    pair_profile = next(
        row for row in document["profiles"]
        if row["fixture_id"] == fixture_id and row["party_size"] == party_size
    )
    pair_rows = pair_profile["planned_row_ids"]
    selected_row_id = planned_row_id or pair_rows[0]
    if selected_row_id not in pair_rows or selected_row_id.startswith("R"):
        raise SandboxPreparationError("sandbox seed row is not bound to the fixture-party profile")

    source_path = _safe_source_path(
        PROJECT_ROOT, PREREG_ROOT / "counterbalance.json", "frozen counterbalance"
    )
    try:
        counterbalance = json.loads(source_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SandboxPreparationError("frozen counterbalance cannot be read") from exc
    rows = counterbalance.get("rows") if isinstance(counterbalance, Mapping) else None
    selected_rows = [
        row for row in rows or []
        if isinstance(row, Mapping) and row.get("row_id") == selected_row_id
    ]
    if len(selected_rows) != 1:
        raise SandboxPreparationError("profile-bound planned row is unavailable")
    row = selected_rows[0]
    if (
        row.get("row_type") != "planned"
        or row.get("party") != party_size
        or type(row.get("fixed_seed")) is not int
        or row.get("arm") not in ("A", "B", "D")
    ):
        raise SandboxPreparationError("profile-bound planned row identity is invalid")

    from scripts.seed_combat_capture import _build_mapping_pilot_seed_plan

    plan = _build_mapping_pilot_seed_plan(
        fixture_id, str(row["arm"]), party_size, row["fixed_seed"]
    )
    if plan["counterbalance"].get("row_id") != selected_row_id:
        raise SandboxPreparationError("seed builder resolved a different planned row")
    return plan, pair_profile


def _load_profile_seed_inputs(
    project_root: Path,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    from scripts.live_gate_preflight_profiles import PREREG_ROOT
    from scripts.mapping_pilot.fixtures import (
        build_fixture_payloads,
        load_verified_fixtures,
    )

    fixtures, source_hashes = load_verified_fixtures(project_root / PREREG_ROOT)
    module_payloads, expected_payloads = build_fixture_payloads(
        fixtures, source_hashes
    )
    return module_payloads, expected_payloads


def _planned_worker_invocation(
    project_root: Path,
    plan: Mapping[str, Any],
    *,
    lifecycle: str,
    source_sha: str,
    run_id: str,
    resume_checkpoint_sha256: str | None,
    preflight_run_id: str | None = None,
) -> PlannedWorkerInvocation:
    """Build the worker identity through the same controller command factory."""
    if lifecycle not in ("startup", "resume"):
        raise SandboxPreparationError("worker lifecycle identity is invalid")
    if not isinstance(source_sha, str) or _SOURCE_SHA.fullmatch(source_sha) is None:
        raise SandboxPreparationError("worker source identity is invalid")
    if not isinstance(run_id, str) or _RUN_ID.fullmatch(run_id) is None:
        raise SandboxPreparationError("worker run identity is invalid")
    if lifecycle == "resume":
        if (
            not isinstance(resume_checkpoint_sha256, str)
            or _CHECKPOINT_SHA256.fullmatch(resume_checkpoint_sha256) is None
        ):
            raise SandboxPreparationError("resume checkpoint identity is invalid")
    elif resume_checkpoint_sha256 is not None:
        raise SandboxPreparationError("startup checkpoint identity is invalid")

    fixture_id = plan.get("fixture_id")
    party_size = plan.get("party_size")
    row = plan.get("counterbalance")
    if (
        fixture_id not in _FIXTURE_IDS
        or type(party_size) is not int
        or party_size not in _PARTY_SIZES
        or not isinstance(row, Mapping)
        or row.get("row_type") != "planned"
        or not isinstance(row.get("row_id"), str)
        or row["row_id"].startswith("R")
        or plan.get("arm") not in ("A", "B", "D")
    ):
        raise SandboxPreparationError("planned worker fixture identity is invalid")

    selected_row_id = str(row["row_id"])
    selected_arm = str(plan["arm"])
    lifecycle_id = run_id + ("_s" if lifecycle == "startup" else "_r")
    from scripts.live_gate_preflight_profile_runner import (
        CharacterizationError,
        _host_command,
    )
    from scripts.live_gate_preflight_safety import expected_guarded_pythonpath

    try:
        command = _host_command(
            fixture_id=str(fixture_id),
            party_size=party_size,
            lifecycle=lifecycle,
            source_sha=source_sha,
            run_id=run_id,
            planned_row_id=selected_row_id,
            arm=selected_arm,
            lifecycle_id=lifecycle_id,
            resume_checkpoint_sha256=resume_checkpoint_sha256,
            preflight_run_id=preflight_run_id,
        )
    except CharacterizationError as exc:
        raise SandboxPreparationError(
            "planned worker command is unavailable"
        ) from exc
    if not isinstance(command, list) or not command or any(
        not isinstance(part, str) or not part for part in command
    ):
        raise SandboxPreparationError("planned worker command is invalid")

    root = project_root.resolve(strict=True)
    return PlannedWorkerInvocation(
        fixture_id=str(fixture_id),
        party_size=party_size,
        lifecycle=lifecycle,
        source_sha=source_sha,
        run_id=run_id,
        planned_row_id=selected_row_id,
        arm=selected_arm,
        command=tuple(command),
        working_directory=str(root / SANDBOX_RELATIVE),
        pythonpath=expected_guarded_pythonpath(root),
    )


def prepare_profile_sandbox(
    fixture_id: str,
    party_size: int,
    planned_row_id: str | None = None,
    *,
    lifecycle: str,
    source_sha: str,
    run_id: str,
    intended_host_identity: Mapping[str, Any],
    resume_checkpoint_sha256: str | None = None,
    resume_checkpoint: Mapping[str, Any] | None = None,
    preflight_run_id: str | None = None,
) -> dict[str, Any]:
    """Seed only after intent matches the internally planned worker launch."""
    _require_preparation_startup_guard()
    root = _project_root(PROJECT_ROOT)
    plan, _pair_profile = _load_profile_seed_plan(
        fixture_id, party_size, planned_row_id
    )
    worker_plan = _planned_worker_invocation(
        root,
        plan,
        lifecycle=lifecycle,
        source_sha=source_sha,
        run_id=run_id,
        resume_checkpoint_sha256=resume_checkpoint_sha256,
        preflight_run_id=preflight_run_id,
    )
    if lifecycle == "resume":
        if (
            not isinstance(resume_checkpoint, Mapping)
            or resume_checkpoint.get("state_sha256") != resume_checkpoint_sha256
        ):
            raise SandboxPreparationError("row-bound resume checkpoint is unavailable")
    elif resume_checkpoint is not None:
        raise SandboxPreparationError("startup cannot consume a resume checkpoint")
    module_payloads, expected_payloads = _load_profile_seed_inputs(root)
    prepared, identity_evidence = run_after_invocation_identity(
        worker_plan.identity(),
        intended_host_identity,
        lambda: _prepare_new_sandbox(
            root, plan, module_payloads, expected_payloads
        ),
    )
    if lifecycle == "resume":
        try:
            _install_row_resume_checkpoint(
                root,
                root / SANDBOX_RELATIVE,
                plan,
                resume_checkpoint,
                expected_sha256=str(resume_checkpoint_sha256),
            )
        except BaseException:
            sandbox_path = root / SANDBOX_RELATIVE
            if not sandbox_path.is_symlink() and sandbox_path.exists():
                shutil.rmtree(sandbox_path)
            raise
    prepared["invocation_identity"] = identity_evidence
    return prepared


def _install_row_resume_checkpoint(
    project_root: Path,
    target_sandbox: Path,
    plan: Mapping[str, Any],
    checkpoint: Mapping[str, Any],
    *,
    expected_sha256: str,
) -> None:
    """Install only canonical state from an explicitly row-bound moved checkpoint."""
    from scripts.mapping_pilot import launcher

    required_fields = {
        "checkpoint_root",
        "state_sha256",
        "row_id",
        "fixture_id",
        "party_size",
        "arm",
        "fixed_seed",
    }
    row = plan.get("counterbalance")
    if (
        set(checkpoint) != required_fields
        or checkpoint.get("state_sha256") != expected_sha256
        or checkpoint.get("row_id") != (row.get("row_id") if isinstance(row, Mapping) else None)
        or checkpoint.get("fixture_id") != plan.get("fixture_id")
        or checkpoint.get("party_size") != plan.get("party_size")
        or checkpoint.get("arm") != plan.get("arm")
        or type(checkpoint.get("fixed_seed")) is not int
        or checkpoint.get("fixed_seed") != plan.get("effective_seed")
        or re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None
    ):
        raise SandboxPreparationError("resume checkpoint row identity differs")

    checkpoint_relative = _relative_path(
        checkpoint.get("checkpoint_root"), "resume checkpoint"
    )
    if (
        not checkpoint_relative.parts
        or checkpoint_relative.parts[0] != "tmp"
        or checkpoint_relative.as_posix() == SANDBOX_RELATIVE.as_posix()
    ):
        raise SandboxPreparationError("resume checkpoint path is outside project tmp")
    source = _assert_no_symlink_path(
        project_root, checkpoint_relative, "resume checkpoint"
    )
    try:
        resolved_source = source.resolve(strict=True)
        resolved_tmp = (project_root / "tmp").resolve(strict=True)
        resolved_source.relative_to(resolved_tmp)
        resolved_target = target_sandbox.resolve(strict=True)
        resolved_target.relative_to(resolved_tmp)
    except (OSError, RuntimeError, ValueError) as exc:
        raise SandboxPreparationError("resume checkpoint path is unavailable") from exc
    if not resolved_source.is_dir() or resolved_source == resolved_target:
        raise SandboxPreparationError("resume checkpoint directory is invalid")
    try:
        resolved_source.relative_to(resolved_target)
    except ValueError:
        pass
    else:
        raise SandboxPreparationError("resume checkpoint cannot be inside active sandbox")
    try:
        resolved_target.relative_to(resolved_source)
    except ValueError:
        pass
    else:
        raise SandboxPreparationError("resume checkpoint cannot contain active sandbox")

    source_metadata_path = _assert_no_symlink_path(
        resolved_source,
        "mapping_pilot/seed_metadata.json",
        "resume checkpoint seed metadata",
    )
    try:
        source_metadata = json.loads(source_metadata_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SandboxPreparationError("resume checkpoint seed metadata is unavailable") from exc
    source_counterbalance = (
        source_metadata.get("counterbalance")
        if isinstance(source_metadata, Mapping)
        else None
    )
    source_party = source_metadata.get("party") if isinstance(source_metadata, Mapping) else None
    if (
        not isinstance(source_metadata, Mapping)
        or source_metadata.get("fixture_id") != plan.get("fixture_id")
        or source_metadata.get("arm") != plan.get("arm")
        or source_metadata.get("effective_seed") != plan.get("effective_seed")
        or not isinstance(source_party, Mapping)
        or source_party.get("size") != plan.get("party_size")
        or not isinstance(source_counterbalance, Mapping)
        or source_counterbalance.get("row_id") != checkpoint.get("row_id")
        or source_counterbalance.get("row_type") != "planned"
        or source_counterbalance.get("fixed_seed") != plan.get("effective_seed")
    ):
        raise SandboxPreparationError("resume checkpoint metadata is not bound to row")

    target_metadata_path = _assert_no_symlink_path(
        target_sandbox,
        "mapping_pilot/seed_metadata.json",
        "active sandbox seed metadata",
    )
    try:
        target_metadata = json.loads(target_metadata_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SandboxPreparationError("active sandbox seed metadata is unavailable") from exc
    if (
        not isinstance(target_metadata, Mapping)
        or target_metadata.get("fixture_id") != source_metadata.get("fixture_id")
        or target_metadata.get("arm") != source_metadata.get("arm")
        or target_metadata.get("effective_seed") != source_metadata.get("effective_seed")
        or target_metadata.get("mapping") != source_metadata.get("mapping")
        or target_metadata.get("party") != source_metadata.get("party")
        or target_metadata.get("counterbalance") != source_metadata.get("counterbalance")
    ):
        raise SandboxPreparationError("resume checkpoint differs from active seed identity")

    observed_sha256 = launcher._canonical_state_sha256(resolved_source)
    if observed_sha256 != expected_sha256:
        raise SandboxPreparationError("resume checkpoint state hash differs")

    for relative, is_directory, required in (
        ("party_tracker.json", False, True),
        ("characters", True, True),
        ("modules/%s/areas" % MAPPING_MODULE, True, True),
        ("modules/%s/module_plot.json" % MAPPING_MODULE, False, False),
        ("modules/encounters", True, False),
        ("encounters", True, False),
    ):
        source_entry = _assert_no_symlink_path(
            resolved_source, relative, "resume checkpoint state"
        )
        destination = _assert_no_symlink_path(
            target_sandbox, relative, "active sandbox state"
        )
        if not source_entry.exists():
            if required:
                raise SandboxPreparationError("resume checkpoint canonical state is incomplete")
            if destination.is_dir() and not destination.is_symlink():
                shutil.rmtree(destination)
            elif destination.exists():
                destination.unlink()
            continue
        if source_entry.is_symlink() or source_entry.is_dir() != is_directory:
            raise SandboxPreparationError("resume checkpoint state path is invalid")
        if destination.is_symlink():
            raise SandboxPreparationError("active sandbox state path is unsafe")
        if destination.is_dir():
            shutil.rmtree(destination)
        elif destination.exists():
            destination.unlink()
        destination.parent.mkdir(parents=True, exist_ok=True)
        if is_directory:
            _copy_checkpoint_tree(source_entry, destination)
        else:
            if not source_entry.is_file():
                raise SandboxPreparationError("resume checkpoint state file is invalid")
            shutil.copy2(source_entry, destination)

    if launcher._canonical_state_sha256(target_sandbox) != expected_sha256:
        raise SandboxPreparationError("installed resume checkpoint state hash differs")
    try:
        launcher.validate_sandbox(
            target_sandbox,
            arm=str(plan["arm"]),
            fixture_id=str(plan["fixture_id"]),
            party_size=int(plan["party_size"]),
            resume=True,
            resume_checkpoint_sha256=expected_sha256,
            project_root=project_root,
        )
    except Exception as exc:
        raise SandboxPreparationError("resume checkpoint is not a valid moved state") from exc


def _copy_checkpoint_tree(source: Path, destination: Path) -> None:
    if source.is_symlink() or not source.is_dir():
        raise SandboxPreparationError("resume checkpoint state directory is invalid")
    destination.mkdir(parents=True, exist_ok=False)
    try:
        entries = sorted(os.scandir(source), key=lambda entry: entry.name)
    except OSError as exc:
        raise SandboxPreparationError("resume checkpoint state directory is unreadable") from exc
    for entry in entries:
        if entry.is_symlink():
            raise SandboxPreparationError("resume checkpoint state contains a symlink")
        source_child = source / entry.name
        destination_child = destination / entry.name
        try:
            metadata = entry.stat(follow_symlinks=False)
        except OSError as exc:
            raise SandboxPreparationError("resume checkpoint state cannot be inspected") from exc
        if stat.S_ISDIR(metadata.st_mode):
            _copy_checkpoint_tree(source_child, destination_child)
        elif stat.S_ISREG(metadata.st_mode):
            shutil.copy2(source_child, destination_child)
        else:
            raise SandboxPreparationError("resume checkpoint state contains a special file")


def remove_prepared_sandbox(
    plan: Mapping[str, Any], seeded: Mapping[str, Any]
) -> bool:
    """Remove only the exact fixture copy created for this planned row."""
    root = _project_root(PROJECT_ROOT)
    if (
        not isinstance(plan, Mapping)
        or not isinstance(seeded, Mapping)
        or seeded.get("status") != "prepared"
        or seeded.get("sandbox_root") != SANDBOX_RELATIVE.as_posix()
        or seeded.get("fixture_id") != plan.get("fixture_id")
        or seeded.get("party_size") != plan.get("party_size")
        or seeded.get("planned_row_id") != plan.get("row_id")
        or seeded.get("arm") != plan.get("arm")
        or seeded.get("effective_seed") != plan.get("fixed_seed")
    ):
        raise SandboxPreparationError("prepared sandbox identity differs from row plan")
    sandbox = _assert_no_symlink_path(root, SANDBOX_RELATIVE, "sandbox")
    if not sandbox.exists():
        return True
    if not sandbox.is_dir():
        raise SandboxPreparationError("prepared sandbox root is not a directory")
    try:
        resolved = sandbox.resolve(strict=True)
        resolved.relative_to((root / "tmp").resolve(strict=True))
    except (OSError, RuntimeError, ValueError) as exc:
        raise SandboxPreparationError("prepared sandbox escaped project tmp") from exc
    metadata_path = _assert_no_symlink_path(
        root, SANDBOX_RELATIVE / "mapping_pilot" / "seed_metadata.json", "seed metadata"
    )
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SandboxPreparationError("prepared sandbox identity is unavailable") from exc
    counterbalance = metadata.get("counterbalance") if isinstance(metadata, Mapping) else None
    party = metadata.get("party") if isinstance(metadata, Mapping) else None
    if (
        not isinstance(counterbalance, Mapping)
        or metadata.get("fixture_id") != plan.get("fixture_id")
        or not isinstance(party, Mapping)
        or party.get("size") != plan.get("party_size")
        or counterbalance.get("row_id") != plan.get("row_id")
        or counterbalance.get("row_type") != "planned"
        or counterbalance.get("fixed_seed") != plan.get("fixed_seed")
        or metadata.get("arm") != plan.get("arm")
        or metadata.get("effective_seed") != plan.get("fixed_seed")
    ):
        raise SandboxPreparationError("prepared sandbox identity differs from row plan")
    try:
        shutil.rmtree(sandbox)
    except OSError as exc:
        raise SandboxPreparationError("prepared sandbox cleanup failed") from exc
    return not sandbox.exists()


def _parse_identity_json(value: str) -> Mapping[str, Any]:
    try:
        identity = json.loads(value)
    except (TypeError, json.JSONDecodeError) as exc:
        raise argparse.ArgumentTypeError("host invocation identity must be JSON") from exc
    if not isinstance(identity, Mapping):
        raise argparse.ArgumentTypeError("host invocation identity must be an object")
    return identity


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare an isolated sandbox only when its intended worker identity "
            "matches the internally planned invocation; this command never launches a host."
        )
    )
    parser.add_argument("--prepare", action="store_true", required=True)
    parser.add_argument("--fixture-id", choices=_FIXTURE_IDS, required=True)
    parser.add_argument("--party-size", type=int, choices=_PARTY_SIZES, required=True)
    parser.add_argument("--planned-row-id")
    parser.add_argument("--lifecycle", choices=("startup", "resume"), required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--resume-checkpoint-sha256")
    parser.add_argument("--preflight-run-id")
    parser.add_argument(
        "--intended-host-identity-json", type=_parse_identity_json, required=True
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        result = prepare_profile_sandbox(
            args.fixture_id,
            args.party_size,
            args.planned_row_id,
            lifecycle=args.lifecycle,
            source_sha=args.source_sha,
            run_id=args.run_id,
            intended_host_identity=args.intended_host_identity_json,
            resume_checkpoint_sha256=args.resume_checkpoint_sha256,
            preflight_run_id=args.preflight_run_id,
        )
    except InvocationIdentityMismatch as exc:
        print(
            "[FAIL] profile_sandbox="
            + json.dumps(
                {
                    "failure_code": "invocation_identity_mismatch",
                    "identity_evidence": exc.evidence,
                },
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
        return 1
    except (ImportError, OSError, ValueError, SandboxPreparationError) as exc:
        print("[FAIL] profile_sandbox=" + str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
