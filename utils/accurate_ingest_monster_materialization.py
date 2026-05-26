# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest accurate-ingest monster materialization
and encounter seed binding.

Step 1.4 implementation: reuse-first resolution of source monster references
with schema-sufficiency validation and per-ref resolution logging.
Step 2.2 implementation: encounter seed binding against resolution log.
"""

import json
import os
import re
from typing import Any, Dict, List

# Minimum required fields for a monster artifact to count as schema-sufficient.
# Parity with HYDRATION_REQUIRED_MONSTER_FIELDS in utils.module_monster_authority.
_MONSTER_REQUIRED_FIELDS = {"size", "alignment", "armorClass"}


def _is_schema_sufficient(data: Dict[str, Any]) -> bool:
    """Return True if the loaded monster data has all required fields."""
    return all(
        field in data and data[field] is not None
        for field in _MONSTER_REQUIRED_FIELDS
    )


def _normalize_ref(name: str) -> str:
    """Produce a stable slug for monster-file lookup.

    Provider-free; avoids imports from runtime modules that trigger chat-client
    initialization at import time.
    """
    return re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower()).strip("_")


def materialize_source_monsters(
    module_dir: str,
    source_monster_refs: List[str],
    source_encounter_seeds: List[Any],
) -> Dict[str, Any]:
    """Resolve source monster references against existing module-local files.

    Returns a deterministic report dictionary with:
    - status: str (skipped, pass, degraded)
    - monsters_planned: int
    - monsters_reused: int
    - monsters_generated: int
    - monsters_unresolved: int
    - encounters_planned: int
    - encounters_bound: int
    - unresolved_refs: List[str]
    - artifact_paths: List[str]
    - resolution_log: List[Dict] - per-ref diagnostics
    """
    refs = [str(ref).strip() for ref in source_monster_refs if str(ref).strip()]
    seeds = [seed for seed in source_encounter_seeds if seed]

    if not refs and not seeds:
        return {
            "status": "skipped",
            "monsters_planned": 0,
            "monsters_reused": 0,
            "monsters_generated": 0,
            "monsters_skipped": 0,
            "monsters_unresolved": 0,
            "encounters_planned": 0,
            "encounters_bound": 0,
            "encounters_unresolved": 0,
            "encounters_unbound": 0,
            "encounter_bindings": [],
            "unresolved_refs": [],
            "artifact_paths": [],
            "resolution_log": [],
        }

    monsters_dir = os.path.join(module_dir, "monsters")
    resolution_log: List[Dict[str, Any]] = []

    for ref in refs:
        slug = _normalize_ref(ref)
        candidate = os.path.join(monsters_dir, f"{slug}.json")

        if not os.path.isfile(candidate):
            resolution_log.append({
                "ref": ref,
                "status": "unresolved",
                "reason": "file_not_found",
                "artifact_path": candidate,
            })
            continue

        try:
            with open(candidate, "rb") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            resolution_log.append({
                "ref": ref,
                "status": "unresolved",
                "reason": "invalid_json",
                "artifact_path": candidate,
            })
            continue

        if _is_schema_sufficient(data):
            resolution_log.append({
                "ref": ref,
                "status": "reused",
                "reason": "reused",
                "artifact_path": candidate,
            })
        else:
            resolution_log.append({
                "ref": ref,
                "status": "unresolved",
                "reason": "missing_required_fields",
                "artifact_path": candidate,
            })

    reused = [e["ref"] for e in resolution_log if e["status"] == "reused"]
    unresolved = [e["ref"] for e in resolution_log if e["status"] == "unresolved"]
    artifact_paths = [e["artifact_path"] for e in resolution_log if e["status"] == "reused"]

    encounter_binding = bind_encounter_monsters(seeds, resolution_log)

    status: str
    if unresolved or encounter_binding["status"] == "degraded":
        status = "degraded"
    else:
        status = "pass"

    return {
        "status": status,
        "monsters_planned": len(refs),
        "monsters_reused": len(reused),
        "monsters_generated": 0,
        "monsters_skipped": 0,
        "monsters_unresolved": len(unresolved),
        "encounters_planned": len(seeds),
        "encounters_bound": encounter_binding["seeds_bound"],
        "encounters_unresolved": encounter_binding["seeds_unresolved"],
        "encounters_unbound": encounter_binding["seeds_unbound"],
        "encounter_bindings": encounter_binding["bindings"],
        "unresolved_refs": unresolved,
        "artifact_paths": artifact_paths,
        "resolution_log": resolution_log,
    }


def _normalize_token(text: str) -> str:
    """Lowercase and collapse non-alphanumeric for substring matching."""
    return re.sub(r"[^a-z0-9]+", " ", str(text).strip().lower())


def _ref_matches_seed(seed_text: str, ref_name: str) -> bool:
    """Return True if the normalized ref name appears as a word in the seed."""
    norm_seed = _normalize_token(seed_text)
    norm_ref = _normalize_token(ref_name)
    if not norm_ref:
        return False
    return f" {norm_ref} " in f" {norm_seed} "


def bind_encounter_monsters(
    encounter_seeds: List[Any],
    resolution_log: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Bind encounter seeds to canonical materialized monster refs.

    Returns a deterministic report with per-seed binding entries and
    aggregate counts.
    """
    seeds = [s for s in encounter_seeds if s]
    log = [e for e in resolution_log if isinstance(e, dict)]

    if not seeds and not log:
        return {
            "status": "skipped",
            "seeds_planned": 0,
            "seeds_bound": 0,
            "seeds_unresolved": 0,
            "seeds_unbound": 0,
            "bindings": [],
        }

    reused_entries = [e for e in log if e.get("status") == "reused"]
    unresolved_entries = [e for e in log if e.get("status") == "unresolved"]

    bindings: List[Dict[str, Any]] = []

    for seed in seeds:
        matched_reused = [
            e for e in reused_entries
            if _ref_matches_seed(seed, e.get("ref", ""))
        ]
        matched_unresolved = [
            e for e in unresolved_entries
            if _ref_matches_seed(seed, e.get("ref", ""))
        ]

        if matched_reused:
            entry = matched_reused[0]
            bindings.append({
                "seed": seed,
                "status": "bound",
                "monster_ref": entry["ref"],
                "artifact_path": entry.get("artifact_path"),
                "unresolved_refs": [e["ref"] for e in matched_unresolved],
                "reason": "bound",
            })
        elif matched_unresolved:
            bindings.append({
                "seed": seed,
                "status": "unresolved",
                "monster_ref": None,
                "artifact_path": None,
                "unresolved_refs": [e["ref"] for e in matched_unresolved],
                "reason": "unresolved_ref",
            })
        else:
            bindings.append({
                "seed": seed,
                "status": "unbound",
                "monster_ref": None,
                "artifact_path": None,
                "unresolved_refs": [],
                "reason": "no_source_ref",
            })

    seeds_bound = sum(1 for b in bindings if b["status"] == "bound")
    seeds_unresolved = sum(1 for b in bindings if b["status"] == "unresolved")
    seeds_unbound = sum(1 for b in bindings if b["status"] == "unbound")

    if seeds_unresolved > 0:
        overall_status = "degraded"
    else:
        overall_status = "pass"

    return {
        "status": overall_status,
        "seeds_planned": len(bindings),
        "seeds_bound": seeds_bound,
        "seeds_unresolved": seeds_unresolved,
        "seeds_unbound": seeds_unbound,
        "bindings": bindings,
    }
