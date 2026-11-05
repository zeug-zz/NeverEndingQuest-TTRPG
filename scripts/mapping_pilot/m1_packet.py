# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Create deterministic, provider-free M1 sketch and owner-rating packets."""

from __future__ import annotations

import copy
import csv
import hashlib
import io
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from scripts.mapping_pilot.cartographer import (
    ATTEMPT_LEDGER_FILENAME,
    PROJECT_ROOT,
)
from scripts.mapping_pilot.fixtures import FIXTURE_FILES, load_verified_fixtures
from scripts.mapping_pilot.layout import normalize_fixture_layout, validate_layout
from scripts.mapping_pilot.m1 import render_m1_sketch
from scripts.mapping_pilot.manifest import DEFAULT_PREREG_ROOT, MANIFEST_NAME


M1_ROOT = Path("tmp/router-rollout/mapping-pilot/m1")
D1_ROOT = Path("tmp/router-rollout/mapping-pilot/d1")
_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_SCRIPT_PATH_BY_FIXTURE = {
    "interior_tavern": "scripts/interior.json",
    "landscape_village": "scripts/landscape.json",
    "transition_tower_approach": "scripts/landscape.json",
    "combat_stage_tavern_zones": "scripts/combat.json",
}
_COMBAT_VARIANTS = (("P1", "party_1"), ("P4", "party_4"))
_D1_VIEWPOINT_ID = "D1_REVIEW_VIEWPOINT"


def create_m1_packet(
    run_id: str,
    *,
    d1_run_id: str | None = None,
    output_root: str | Path = M1_ROOT,
    d1_root: str | Path = D1_ROOT,
) -> Path:
    """Write sketches, hashes, and blank ratings below one new run directory.

    ``output_root`` and ``d1_root`` are injectable project-relative paths under
    ``tmp/`` so provider-free tests never write to the rollout evidence roots.
    The manifest is written last and is the completion marker for a packet.
    """
    _validate_token(run_id, "run_id")
    if d1_run_id is not None:
        _validate_token(d1_run_id, "d1_run_id")

    output_root_rel = _project_tmp_relative(output_root, "output_root")
    run_dir_rel = output_root_rel / run_id
    run_dir = PROJECT_ROOT / run_dir_rel
    _reject_symlink_components(run_dir)
    if run_dir.exists():
        raise FileExistsError("M1 run directory already exists: %s" % run_dir_rel)

    fixtures, frozen_hashes = load_verified_fixtures()
    scripts, script_hashes = _load_verified_scripts(frozen_hashes)
    prereg_manifest_path = DEFAULT_PREREG_ROOT / MANIFEST_NAME
    if prereg_manifest_path.is_symlink() or not prereg_manifest_path.is_file():
        raise ValueError("frozen preregistration manifest is missing or unsafe")
    prereg_manifest_hash = hashlib.sha256(prereg_manifest_path.read_bytes()).hexdigest()

    specs = _build_fixture_specs(fixtures, frozen_hashes, scripts)
    omitted_d1: list[dict[str, Any]] = []
    d1_input: dict[str, Any] | None = None
    if d1_run_id is not None:
        d1_specs, omitted_d1, d1_input = _load_d1_specs(d1_run_id, d1_root)
        specs.extend(d1_specs)

    sketch_rows: list[dict[str, Any]] = []
    artifacts: dict[str, bytes] = {}
    seen_ids: set[str] = set()
    for spec in specs:
        sketch_id = _stable_sketch_id(
            str(spec["source"]),
            str(spec["identity"]),
            str(spec["location_id"]),
            str(spec["viewpoint"]),
        )
        if sketch_id in seen_ids:
            raise ValueError("duplicate M1 sketch identity: %s" % sketch_id)
        seen_ids.add(sketch_id)
        filename = "sketch-%s.txt" % sketch_id
        sketch = render_m1_sketch(
            spec["layout"],
            current_location_id=str(spec["location_id"]),
            active_actor_id=str(spec["active_actor_id"]),
            party_known_ids=frozenset(spec["party_known_ids"]),
            perceived_ids=frozenset(spec["perceived_ids"]),
        )
        payload = sketch.encode("ascii")
        artifacts[filename] = payload
        row = {
            "sketch_id": sketch_id,
            "file": filename,
            "source": spec["source"],
            "identity": spec["identity"],
            "location_id": spec["location_id"],
            "viewpoint": spec["viewpoint"],
            "viewpoint_context": spec["viewpoint_context"],
            "source_paths": spec["source_paths"],
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
        if "attempt_number" in spec:
            row["attempt_number"] = spec["attempt_number"]
        sketch_rows.append(row)

    ratings_payload = _build_ratings_sheet(sketch_rows)
    artifacts["ratings.csv"] = ratings_payload
    manifest = {
        "schema_version": 1,
        "run_id": run_id,
        "completion": "complete",
        "d1_run_id": d1_run_id,
        "fixtures": _fixture_manifest_rows(fixtures, frozen_hashes, script_hashes),
        "inputs": {
            "prereg_manifest_sha256": prereg_manifest_hash,
            "d1_ledger": d1_input,
        },
        "omitted_d1_layouts": omitted_d1,
        "sketches": sketch_rows,
        "artifact_sha256": {
            name: hashlib.sha256(payload).hexdigest()
            for name, payload in sorted(artifacts.items())
        },
    }

    _reject_symlink_components(PROJECT_ROOT / output_root_rel)
    (PROJECT_ROOT / output_root_rel).mkdir(parents=True, exist_ok=True)
    _reject_symlink_components(run_dir)
    run_dir.mkdir(exist_ok=False)
    for filename, payload in artifacts.items():
        with (run_dir / filename).open("xb") as output_file:
            output_file.write(payload)

    from utils.file_operations import safe_write_json

    if not safe_write_json(
        str(run_dir_rel / "manifest.json"),
        manifest,
        create_backup=False,
        acquire_lock=False,
        json_kwargs={"ensure_ascii": True, "indent": 2, "sort_keys": True},
    ):
        raise OSError("M1 manifest write failed; run has no completion manifest")
    return run_dir_rel


def _build_fixture_specs(
    fixtures: Mapping[str, Mapping[str, Any]],
    frozen_hashes: Mapping[str, str],
    scripts: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    for fixture_id in FIXTURE_FILES:
        fixture = fixtures.get(fixture_id)
        if not isinstance(fixture, Mapping):
            raise ValueError("verified fixture is missing: %s" % fixture_id)
        layout = normalize_fixture_layout(fixture)
        current_location_id = _current_location_id(layout)
        script_path = _SCRIPT_PATH_BY_FIXTURE[fixture_id]
        script = scripts[script_path]
        fixture_path = FIXTURE_FILES[fixture_id]
        if fixture_path not in frozen_hashes:
            raise ValueError("fixture hash is missing: %s" % fixture_path)

        if fixture_id == "combat_stage_tavern_zones":
            placement_rules = layout.get("initial_placement_rules")
            if not isinstance(placement_rules, Mapping):
                raise ValueError("combat fixture has no initial placement rules")
            for viewpoint, party_key in _COMBAT_VARIANTS:
                placement = placement_rules.get(party_key)
                if not isinstance(placement, Mapping):
                    raise ValueError("combat fixture has no %s placement" % party_key)
                pcs = placement.get("pcs")
                if not isinstance(pcs, Mapping) or not pcs:
                    raise ValueError("combat fixture has no %s PC placements" % party_key)
                variant_layout = copy.deepcopy(layout)
                _apply_party_placements(variant_layout, pcs)
                actor_id, actor_source, derivation = _script_actor(
                    fixture, variant_layout, script, script_path, party_key
                )
                if actor_id not in pcs:
                    raise ValueError("scripted active actor is absent from %s" % party_key)
                known_ids, perceived_ids = _fixture_knowledge(
                    variant_layout, current_location_id
                )
                specs.append(
                    _fixture_spec(
                        fixture_id=fixture_id,
                        fixture_path=fixture_path,
                        script_path=script_path,
                        location_id=current_location_id,
                        viewpoint=viewpoint,
                        party_key=party_key,
                        active_actor_id=actor_id,
                        active_actor_source=actor_source,
                        derivation=derivation,
                        party_members=list(pcs.keys()),
                        party_source=(
                            "%s#initial_placement_rules.%s.pcs" % (fixture_path, party_key)
                        ),
                        layout=variant_layout,
                        known_ids=known_ids,
                        perceived_ids=perceived_ids,
                    )
                )
        else:
            party_key = "party_1"
            actor_id, actor_source, derivation = _script_actor(
                fixture, layout, script, script_path, party_key
            )
            known_ids, perceived_ids = _fixture_knowledge(layout, current_location_id)
            specs.append(
                _fixture_spec(
                    fixture_id=fixture_id,
                    fixture_path=fixture_path,
                    script_path=script_path,
                    location_id=current_location_id,
                    viewpoint="start",
                    party_key=party_key,
                    active_actor_id=actor_id,
                    active_actor_source=actor_source,
                    derivation=derivation,
                    party_members=None,
                    party_source=None,
                    layout=layout,
                    known_ids=known_ids,
                    perceived_ids=perceived_ids,
                )
            )
    return specs


def _fixture_spec(
    *,
    fixture_id: str,
    fixture_path: str,
    script_path: str,
    location_id: str,
    viewpoint: str,
    party_key: str,
    active_actor_id: str,
    active_actor_source: str,
    derivation: str,
    party_members: list[str] | None,
    party_source: str | None,
    layout: Mapping[str, Any],
    known_ids: frozenset[str],
    perceived_ids: frozenset[str],
) -> dict[str, Any]:
    context: dict[str, Any] = {
        "party_key": party_key,
        "active_actor_id": active_actor_id,
        "active_actor_source": active_actor_source,
        "derivation": derivation,
        "knowledge_source": "%s#fixture start facts via B/D viewpoint rules" % fixture_path,
        "party_known_ids": sorted(known_ids),
        "perceived_ids": sorted(perceived_ids),
    }
    if party_members is not None:
        context["party_members"] = party_members
        context["party_members_source"] = party_source
    return {
        "source": "fixture",
        "identity": fixture_id,
        "location_id": location_id,
        "viewpoint": viewpoint,
        "active_actor_id": active_actor_id,
        "party_known_ids": known_ids,
        "perceived_ids": perceived_ids,
        "viewpoint_context": context,
        "source_paths": [fixture_path, script_path],
        "layout": layout,
    }


def _load_verified_scripts(
    frozen_hashes: Mapping[str, str],
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    script_paths = sorted(set(_SCRIPT_PATH_BY_FIXTURE.values()))
    scripts: dict[str, dict[str, Any]] = {}
    hashes: dict[str, str] = {}
    for relative_path in script_paths:
        expected_hash = frozen_hashes.get(relative_path)
        if not isinstance(expected_hash, str):
            raise ValueError("frozen script hash is missing: %s" % relative_path)
        path = DEFAULT_PREREG_ROOT.joinpath(*Path(relative_path).parts)
        if path.is_symlink() or not path.is_file():
            raise ValueError("frozen script is missing or unsafe: %s" % relative_path)
        payload = path.read_bytes()
        observed_hash = hashlib.sha256(payload).hexdigest()
        if observed_hash != expected_hash:
            raise ValueError("frozen script hash changed: %s" % relative_path)
        try:
            value = json.loads(payload.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("frozen script is invalid JSON: %s" % relative_path) from exc
        if not isinstance(value, dict):
            raise ValueError("frozen script must be an object: %s" % relative_path)
        scripts[relative_path] = value
        hashes[relative_path] = observed_hash
    return scripts, hashes


def _fixture_manifest_rows(
    fixtures: Mapping[str, Mapping[str, Any]],
    frozen_hashes: Mapping[str, str],
    script_hashes: Mapping[str, str],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for fixture_id in FIXTURE_FILES:
        fixture_path = FIXTURE_FILES[fixture_id]
        script_path = _SCRIPT_PATH_BY_FIXTURE[fixture_id]
        if fixture_id not in fixtures or fixture_path not in frozen_hashes:
            raise ValueError("frozen fixture provenance is incomplete: %s" % fixture_id)
        if script_path not in script_hashes:
            raise ValueError("frozen script provenance is incomplete: %s" % script_path)
        rows.append(
            {
                "fixture_id": fixture_id,
                "fixture_path": fixture_path,
                "fixture_sha256": frozen_hashes[fixture_path],
                "script_path": script_path,
                "script_sha256": script_hashes[script_path],
            }
        )
    return rows


def _script_actor(
    fixture: Mapping[str, Any],
    layout: Mapping[str, Any],
    script: Mapping[str, Any],
    script_path: str,
    party_key: str,
) -> tuple[str, str, str]:
    if fixture.get("fixture_id") not in script.get("fixture_ids", []):
        raise ValueError("frozen script does not declare fixture %s" % fixture.get("fixture_id"))
    feature_ids = _feature_ids(layout)
    turns = script.get("turns")
    if not isinstance(turns, list):
        raise ValueError("frozen script has no turns: %s" % script_path)

    for turn_index, turn in enumerate(turns):
        if not isinstance(turn, Mapping):
            continue
        expected_ids: set[str] = set()
        checks = turn.get("expected_checks", [])
        if isinstance(checks, list):
            for check in checks:
                if isinstance(check, Mapping) and isinstance(check.get("feature_ids"), list):
                    expected_ids.update(
                        item for item in check["feature_ids"] if isinstance(item, str)
                    )
        if not feature_ids.intersection(expected_ids):
            continue
        actor = _actor_for_turn(turn, party_key)
        if actor is not None:
            turn_id = turn.get("id", str(turn_index + 1))
            return (
                actor,
                "%s#turns[%s].actor.%s" % (script_path, turn_id, party_key),
                "fixture-specific scripted start viewpoint",
            )

    for turn_index, turn in enumerate(turns):
        if not isinstance(turn, Mapping):
            continue
        actor = _actor_for_turn(turn, party_key)
        if actor is not None:
            turn_id = turn.get("id", str(turn_index + 1))
            return (
                actor,
                "%s#turns[%s].actor.%s" % (script_path, turn_id, party_key),
                "fixture-specific turn unavailable; used the script start-of-scene viewpoint",
            )
    raise ValueError("frozen script does not define an active actor for %s" % party_key)


def _actor_for_turn(turn: Mapping[str, Any], party_key: str) -> str | None:
    actor = turn.get("actor")
    if not isinstance(actor, Mapping):
        return None
    value = actor.get(party_key)
    return value if isinstance(value, str) and value else None


def _feature_ids(layout: Mapping[str, Any]) -> set[str]:
    features: set[str] = set()
    if layout.get("layout_type") == "combat_zones":
        rows = layout.get("feature_anchors", [])
        for row in rows if isinstance(rows, list) else []:
            if isinstance(row, Mapping) and isinstance(row.get("feature_id"), str):
                features.add(row["feature_id"])
        return features
    locations = layout.get("locations", [])
    for location in locations if isinstance(locations, list) else []:
        if not isinstance(location, Mapping):
            continue
        rows = location.get("features", [])
        for row in rows if isinstance(rows, list) else []:
            if isinstance(row, Mapping) and isinstance(row.get("feature_id"), str):
                features.add(row["feature_id"])
    return features


def _apply_party_placements(layout: dict[str, Any], pcs: Mapping[str, Any]) -> None:
    zones = {
        row.get("zone_id")
        for row in layout.get("zones", [])
        if isinstance(row, Mapping) and isinstance(row.get("zone_id"), str)
    }
    occupants = layout.get("occupant_roles")
    if not isinstance(occupants, list):
        raise ValueError("combat fixture has no occupant roles")
    for actor_id, zone_id in pcs.items():
        if (
            not isinstance(actor_id, str)
            or not actor_id
            or not isinstance(zone_id, str)
            or zone_id not in zones
        ):
            raise ValueError("combat fixture contains an invalid party placement")
        occupants.append(
            {
                "actor_id": actor_id,
                "name": actor_id,
                "kind": "player_character",
                "initial_zone_id": zone_id,
            }
        )


def _current_location_id(layout: Mapping[str, Any]) -> str:
    if layout.get("layout_type") == "combat_zones":
        value = layout.get("location_id")
        if isinstance(value, str) and value:
            return value
    locations = layout.get("locations")
    if isinstance(locations, list) and locations:
        first = locations[0]
        if isinstance(first, Mapping):
            value = first.get("location_id")
            if isinstance(value, str) and value:
                return value
    raise ValueError("layout has no start-of-scene location")


def _fixture_knowledge(
    layout: Mapping[str, Any], current_location_id: str
) -> tuple[frozenset[str], frozenset[str]]:
    """Mirror adapter._fixture_knowledge without depending on its private API."""
    perceived: set[str] = set()
    known: set[str] = {current_location_id}
    if layout.get("layout_type") == "combat_zones":
        feature_rows = layout.get("feature_anchors", [])
        npc_rows = layout.get("npc_anchors", [])
        for collection in (feature_rows, npc_rows):
            if not isinstance(collection, list):
                continue
            for row in collection:
                if not isinstance(row, Mapping):
                    continue
                identifier = row.get("feature_id", row.get("npc_id"))
                if isinstance(identifier, str) and row.get("perceivable", True) is not False:
                    perceived.add(identifier)
        zone_ids = {
            row.get("zone_id")
            for row in layout.get("zones", [])
            if isinstance(row, Mapping) and isinstance(row.get("zone_id"), str)
        }
        for row in layout.get("occupant_roles", []):
            if (
                isinstance(row, Mapping)
                and row.get("initial_zone_id") in zone_ids
                and isinstance(row.get("actor_id"), str)
            ):
                perceived.add(row["actor_id"])
        exit_rows = layout.get("exits", [])
    else:
        locations = layout.get("locations", [])
        current = next(
            (
                row
                for row in locations
                if isinstance(row, Mapping)
                and row.get("location_id") == current_location_id
            ),
            {},
        )
        for feature in current.get("features", []):
            if (
                isinstance(feature, Mapping)
                and feature.get("perceivable", True) is not False
                and isinstance(feature.get("feature_id"), str)
            ):
                perceived.add(feature["feature_id"])
        for npc in current.get("npc_anchors", []):
            if (
                isinstance(npc, Mapping)
                and npc.get("perceivable", True) is not False
                and isinstance(npc.get("npc_id"), str)
            ):
                perceived.add(npc["npc_id"])
        exit_rows = current.get("exits", [])
    known.update(perceived)
    if isinstance(exit_rows, list):
        for exit_row in exit_rows:
            if (
                isinstance(exit_row, Mapping)
                and exit_row.get("destination_knowledge") == "known"
                and isinstance(exit_row.get("known_destination_location_id"), str)
            ):
                known.add(exit_row["known_destination_location_id"])
    return frozenset(known), frozenset(perceived)


def _load_d1_specs(
    d1_run_id: str,
    d1_root: str | Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    d1_root_rel = _project_tmp_relative(d1_root, "d1_root")
    run_dir_rel = d1_root_rel / d1_run_id
    run_dir = PROJECT_ROOT / run_dir_rel
    _reject_symlink_components(run_dir)
    if not run_dir.is_dir():
        raise FileNotFoundError("D1 run directory is missing: %s" % run_dir_rel)
    ledger_path = run_dir / ATTEMPT_LEDGER_FILENAME
    _reject_symlink_components(ledger_path)
    if not ledger_path.is_file():
        raise FileNotFoundError("D1 attempt ledger is missing: %s" % ledger_path)
    ledger_bytes = ledger_path.read_bytes()
    try:
        ledger = json.loads(ledger_bytes.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("D1 attempt ledger is invalid JSON") from exc
    if not isinstance(ledger, Mapping) or ledger.get("schema_version") != 1:
        raise ValueError("D1 attempt ledger has an unsupported shape")
    attempts = ledger.get("attempts")
    if not isinstance(attempts, list):
        raise ValueError("D1 attempt ledger has no attempts list")

    specs: list[dict[str, Any]] = []
    omitted: list[dict[str, Any]] = []
    for attempt_index, attempt in enumerate(attempts, start=1):
        if not isinstance(attempt, Mapping):
            omitted.append(
                {
                    "attempt_number": attempt_index,
                    "module_slug": "",
                    "location_id": "",
                    "reason": "invalid_attempt_record",
                }
            )
            continue
        module_slug = attempt.get("module_slug")
        location_id = attempt.get("location_id")
        status = attempt.get("status")
        if status != "validated":
            omitted.append(
                {
                    "attempt_number": attempt.get("attempt_number", attempt_index),
                    "module_slug": module_slug if isinstance(module_slug, str) else "",
                    "location_id": location_id if isinstance(location_id, str) else "",
                    "reason": "status:%s" % status if isinstance(status, str) else "status_missing",
                }
            )
            continue
        try:
            if not _valid_identifier(module_slug) or not _valid_identifier(location_id):
                raise ValueError("D1 attempt identity is invalid")
            location_key = "%s:%s" % (module_slug, location_id)
            if attempt.get("location_key") != location_key:
                raise ValueError("D1 location identity does not match its attempt")
            layout = validate_layout(attempt.get("proposal"))
            locations = layout.get("locations")
            if (
                layout.get("layout_type") != "locations"
                or layout.get("fixture_id") != location_key
                or not isinstance(locations, list)
                or len(locations) != 1
                or not isinstance(locations[0], Mapping)
                or locations[0].get("location_id") != location_id
            ):
                raise ValueError("D1 proposal does not match its attempt identity")
            current_location_id = _current_location_id(layout)
            known_ids, perceived_ids = _fixture_knowledge(layout, current_location_id)
        except (TypeError, ValueError, KeyError):
            omitted.append(
                {
                    "attempt_number": attempt.get("attempt_number", attempt_index),
                    "module_slug": module_slug if isinstance(module_slug, str) else "",
                    "location_id": location_id if isinstance(location_id, str) else "",
                    "reason": "invalid_layout",
                }
            )
            continue
        specs.append(
            {
                "source": "d1",
                "identity": module_slug,
                "location_id": current_location_id,
                "viewpoint": "D1-review-start",
                "active_actor_id": _D1_VIEWPOINT_ID,
                "party_known_ids": known_ids,
                "perceived_ids": perceived_ids,
                "viewpoint_context": {
                    "party_key": "not authored for D1",
                    "active_actor_id": _D1_VIEWPOINT_ID,
                    "active_actor_source": "D1 layout has no active party actor; neutral review viewpoint",
                    "derivation": "validated D1 layout start-of-scene projection",
                    "knowledge_source": "validated D1 layout using B/D fixture knowledge rules",
                    "party_known_ids": sorted(known_ids),
                    "perceived_ids": sorted(perceived_ids),
                },
                "source_paths": [
                    (run_dir_rel / ATTEMPT_LEDGER_FILENAME).as_posix()
                ],
                "attempt_number": attempt.get("attempt_number", attempt_index),
                "layout": layout,
            }
        )

    input_record = {
        "path": (run_dir_rel / ATTEMPT_LEDGER_FILENAME).as_posix(),
        "sha256": hashlib.sha256(ledger_bytes).hexdigest(),
    }
    return specs, omitted, input_record


def _build_ratings_sheet(sketches: list[dict[str, Any]]) -> bytes:
    sheet = io.StringIO(newline="")
    sheet.write("# Threshold: mean >= 3.5 for legibility and usefulness\n")
    sheet.write("# Ratings: enter a whole-number value from 1 to 5; leave blank until review.\n")
    sheet.write("# Disclosure: sketch format is visible, so blinding is partial.\n")
    writer = csv.DictWriter(
        sheet,
        fieldnames=("sketch_id", "sketch_file", "legibility_1_5", "usefulness_1_5"),
        lineterminator="\n",
    )
    writer.writeheader()
    for sketch in sketches:
        writer.writerow(
            {
                "sketch_id": sketch["sketch_id"],
                "sketch_file": sketch["file"],
                "legibility_1_5": "",
                "usefulness_1_5": "",
            }
        )
    return sheet.getvalue().encode("ascii")


def _stable_sketch_id(
    source: str,
    identity: str,
    location_id: str,
    viewpoint: str,
) -> str:
    components = (source, identity, location_id, viewpoint)
    safe_components = [
        re.sub(r"[^A-Za-z0-9_-]+", "-", item).strip("-_") or "item"
        for item in components
    ]
    identity_hash = hashlib.sha256("\x1f".join(components).encode("utf-8")).hexdigest()[:12]
    return "%s-%s-%s-%s-%s" % (*safe_components, identity_hash)


def _project_tmp_relative(path: str | Path, label: str) -> Path:
    raw = Path(path)
    if (
        raw.is_absolute()
        or "\\" in str(path)
        or ".." in raw.parts
        or "." in raw.parts
        or not raw.parts
        or raw.parts[0] != "tmp"
    ):
        raise ValueError("%s must be a project-relative path beneath tmp/" % label)
    tmp_root = PROJECT_ROOT / "tmp"
    if tmp_root.is_symlink() or not tmp_root.is_dir():
        raise ValueError("project tmp/ must exist and must not be a symlink")
    candidate = PROJECT_ROOT / raw
    _reject_symlink_components(candidate)
    try:
        candidate.resolve(strict=False).relative_to(tmp_root.resolve(strict=True))
    except (OSError, RuntimeError, ValueError) as exc:
        raise ValueError("%s must remain beneath project tmp/" % label) from exc
    return raw


def _reject_symlink_components(path: Path) -> None:
    try:
        relative = path.relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise ValueError("M1 paths must remain within the project") from exc
    current = PROJECT_ROOT
    for component in relative.parts:
        current = current / component
        if current.is_symlink():
            raise ValueError("M1 paths must not traverse symlinks")


def _validate_token(value: Any, label: str) -> None:
    if (
        not isinstance(value, str)
        or value in (".", "..")
        or not _TOKEN_PATTERN.fullmatch(value)
    ):
        raise ValueError("%s must be a safe path token" % label)


def _valid_identifier(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and value not in (".", "..")
        and "/" not in value
        and "\\" not in value
        and value.isascii()
    )
