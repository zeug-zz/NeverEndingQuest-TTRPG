# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Deterministic, source-bound selection for the offline D1 mapping pilot."""

from __future__ import annotations

import json
import hashlib
import re
import subprocess
from pathlib import Path
from typing import Any, Callable

from scripts.mapping_pilot.cartographer import PROJECT_ROOT
from scripts.mapping_pilot.evidence import _reject_symlink_components

MODULE_QUOTAS = {"Keep_of_Doom": 7, "The_Thornwood_Watch": 6, "The_Pumpkin_Kings_Curse": 7}
_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def create_d1_selection(run_id: str, *, modules_dir: str | Path = "modules",
                        output_root: str | Path = "tmp/router-rollout/mapping-pilot",
                        commit_reader: Callable[[], str] | None = None) -> dict[str, Any]:
    """Create immutable ``d1/<run_id>/selection.json`` and return its payload."""
    if not isinstance(run_id, str) or not _TOKEN.fullmatch(run_id) or run_id in (".", ".."):
        raise ValueError("run_id must be a safe path token")
    root = Path(modules_dir)
    if not root.is_absolute():
        root = PROJECT_ROOT / root
    root = root.resolve(strict=True)
    selected: dict[str, list[tuple[str, Path, str]]] = {}
    count_by_type: dict[str, dict[str, int]] = {}
    for slug, quota in MODULE_QUOTAS.items():
        groups: dict[str, list[tuple[str, Path, str]]] = {}
        seen: set[str] = set()
        for path in sorted((root / slug / "areas").glob("*_BU.json")):
            _reject_symlink_components(path)
            area = json.loads(path.read_text(encoding="utf-8"))
            area_type = area.get("areaType") if isinstance(area, dict) else None
            if not isinstance(area_type, str) or not area_type:
                raise ValueError("missing authored area type in %s" % path.name)
            rows = area.get("locations")
            if not isinstance(rows, list):
                raise ValueError("area locations must be an array in %s" % path.name)
            for row in rows:
                if not isinstance(row, dict) or not isinstance(row.get("locationId"), str) or not row["locationId"]:
                    raise ValueError("invalid authored location in %s" % path.name)
                location_id = row["locationId"]
                if location_id in seen:
                    raise ValueError("duplicate location ID %s in %s" % (location_id, slug))
                seen.add(location_id)
                groups.setdefault(area_type, []).append(
                    (location_id, path, hashlib.sha256(path.read_bytes()).hexdigest(), area_type)
                )
        if not groups:
            raise ValueError("missing authored area type for %s" % slug)
        for rows in groups.values():
            rows.sort(key=lambda item: item[0])
        keys = sorted(groups)
        cursors = dict.fromkeys(keys, 0)
        chosen = []
        while len(chosen) < quota:
            advanced = False
            for key in keys:
                cursor = cursors[key]
                if cursor < len(groups[key]):
                    chosen.append(groups[key][cursor])
                    cursors[key] += 1
                    advanced = True
                    if len(chosen) == quota:
                        break
            if not advanced:
                raise ValueError("insufficient eligible locations for %s quota %d" % (slug, quota))
        selected[slug] = chosen
        count_by_type[slug] = {key: cursors[key] for key in keys}
    commit = (commit_reader or _read_commit)()
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-fA-F]{40,64}", commit):
        raise ValueError("repository commit identity is invalid")
    record = {"schema_version": 1, "run_id": run_id, "commit": commit,
              "module_quotas": dict(MODULE_QUOTAS), "selected_counts_by_area_type": count_by_type,
              "locations": [{"module_slug": slug, "location_id": location_id,
                             "area_type": area_type,
                             "source_paths": [str(path.relative_to(root.parent))],
                             "source_sha256": {str(path.relative_to(root.parent)): digest}}
                            for slug in MODULE_QUOTAS
                            for location_id, path, digest, area_type in selected[slug]]}
    out = Path(output_root)
    if out.is_absolute():
        try:
            out = out.relative_to(PROJECT_ROOT)
        except ValueError as exc:
            raise ValueError("output root must be beneath project tmp") from exc
    if not out.parts or out.parts[0] != "tmp" or ".." in out.parts:
        raise ValueError("output root must be beneath project tmp")
    run_dir = PROJECT_ROOT / out / "d1" / run_id
    _reject_symlink_components(run_dir)
    run_dir.parent.mkdir(parents=True, exist_ok=True)
    try:
        run_dir.mkdir(exist_ok=False)
    except FileExistsError as exc:
        raise ValueError("run directory already exists") from exc
    try:
        from utils.file_operations import safe_write_json
        if not safe_write_json(str(run_dir / "selection.json"), record):
            raise OSError("atomic selection write failed")
    except Exception:
        import shutil
        shutil.rmtree(run_dir, ignore_errors=True)
        raise
    return record


def _read_commit() -> str:
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(PROJECT_ROOT),
                            capture_output=True, text=True, check=True)
    return result.stdout.strip()
