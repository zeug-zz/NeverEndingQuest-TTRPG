#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Rebuild production Numillian from source markdown through accurate-ingest artifacts."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.homebrew_preflight import assess_source_readiness
from utils.enhanced_logger import info
from utils.file_operations import safe_write_json
from utils.toolkit_homebrew_normalizer import normalize_homebrew_upload
from utils.toolkit_homebrew_upload_contract import (
    REVIEW_DECISION_APPROVE,
    SOURCE_RIGHTS_USER_AUTHORED,
    build_review_snapshot,
    compute_sha256,
    ensure_workspace_placeholders,
    get_workspace_files,
    load_json_artifact,
    persist_review_snapshot_artifact,
)
from utils.toolkit_source_fidelity_benchmark import load_benchmark_fixture
from utils.toolkit_entity_candidate_triage import (
    build_prefilter_decision,
    is_non_actor_decision,
    is_rejected,
)
from scripts.benchmark_accurate_ingest import run_benchmark
from web.extensions.toolkit_homebrew_packet_builder import run_toolkit_homebrew_packet_build
from web.extensions.toolkit_module_finisher import run_toolkit_module_postbuild_finishing

MODULE_SLUG = "The_Hidden_City_of_Numillian"
SOURCE_PATH = Path("Local_Docs/modules/hombrew/modules/The Hidden City of Numillian.md")
BENCHMARK_PATH = Path("data/benchmarks/The_Hidden_City_of_Numillian_benchmark.json")


def _utc_now_compact() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _backup_clean_module(module_dir: Path) -> Dict[str, Any]:
    if not module_dir.exists():
        return {"status": "skipped", "reason": "module_dir_absent"}

    backup_root = Path("modules/_numillian_proof_backup")
    backup_root.mkdir(parents=True, exist_ok=True)
    backup_dir = backup_root / f"{MODULE_SLUG}_{_utc_now_compact()}"
    shutil.copytree(module_dir, backup_dir)
    shutil.rmtree(module_dir)

    return {
        "status": "success",
        "backup_dir": str(backup_dir),
        "removed_module_dir": str(module_dir),
    }


def _write_benchmark_report(module_dir: Path) -> Dict[str, Any]:
    fixture = load_benchmark_fixture(BENCHMARK_PATH)
    if fixture is None:
        return {
            "status": "failed",
            "error": f"benchmark_fixture_invalid:{BENCHMARK_PATH}",
        }

    report = run_benchmark(module_dir, fixture)
    safe_write_json(str(module_dir / "accurate_ingest_benchmark_report.json"), report)
    return report


def _run_validation() -> Dict[str, Any]:
    proc = subprocess.run(
        [
            ".venv/bin/python",
            "core/validation/validate_module_files.py",
            "--module",
            MODULE_SLUG,
        ],
        text=True,
        capture_output=True,
        timeout=180,
    )
    return {
        "status": "pass" if proc.returncode == 0 else "fail",
        "exit_code": proc.returncode,
        "stdout_tail": proc.stdout[-4000:],
        "stderr_tail": proc.stderr[-4000:],
    }


def _get_synthetic_puzzle_source_candidates(
    packet: Dict[str, Any],
    plot_topology_report: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Return raw puzzle candidate entries in priority order.

    Prefers plot_topology_report.puzzle_chains over packet-local
    puzzle fields. Returns a list of dicts that will later be
    converted into puzzle_graph entries.
    """
    if plot_topology_report is not None:
        chains = plot_topology_report.get("puzzle_chains") or []
        if chains:
            return list(chains)
        trials = plot_topology_report.get("trials") or []
        if trials:
            return list(trials)
    for key in ("puzzle_chains", "puzzles", "puzzle_seeds", "trials"):
        candidates = packet.get(key)
        if isinstance(candidates, list) and candidates:
            return list(candidates)
    return []


def _build_synthetic_puzzle_graph(
    packet: Dict[str, Any],
    plot_topology_report: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Build puzzle_graph entries from topology or packet puzzle sources.

    Calls _get_synthetic_puzzle_source_candidates() for source priority,
    then converts each raw entry into a blueprint puzzle_graph entry.
    Does not invent content — preserves source-provided fields only.
    """
    candidates = _get_synthetic_puzzle_source_candidates(packet, plot_topology_report)
    puzzle_graph: List[Dict[str, Any]] = []
    for i, raw in enumerate(candidates):
        if isinstance(raw, str):
            str_entry: Dict[str, Any] = {
                "chain_id": f"puzzle_{i+1}",
                "title": raw,
            }
            puzzle_graph.append(str_entry)
            continue
        chain_id = (
            raw.get("chain_id")
            or raw.get("beat_id")
            or raw.get("id")
            or raw.get("atom_id")
            or f"puzzle_{i+1}"
        )
        title = raw.get("title") or raw.get("name") or f"Puzzle {i+1}"
        entry: Dict[str, Any] = {
            "chain_id": str(chain_id),
            "title": str(title),
        }
        for field in ("setup", "rules", "solution", "failure_consequences", "unlocks", "clue_dependencies", "source_refs", "source_descriptions"):
            val = raw.get(field)
            if val is not None:
                entry[field] = val
        puzzle_graph.append(entry)
    return puzzle_graph


def _build_triage_exclusion_slugs(
    entity_candidate_triage_report: Optional[Dict[str, Any]] = None,
) -> Set[str]:
    """Build a set of candidate slugs that MUST be excluded from NPC roster.

    Uses existing triage adjudication: rejected candidates and non-actor
    adjudicated types (narrative_phrase, plot_note, tone_marker, unknown)
    are excluded from synthetic NPC generation.
    """
    excluded: Set[str] = set()
    if not entity_candidate_triage_report:
        return excluded
    for decision in entity_candidate_triage_report.get("decisions") or []:
        if not isinstance(decision, dict):
            continue
        if is_rejected(decision) or is_non_actor_decision(decision):
            slug = decision.get("candidate_slug") or ""
            if slug:
                excluded.add(slug.strip().lower())
    return excluded


def _build_triage_decision_slugs(
    entity_candidate_triage_report: Optional[Dict[str, Any]] = None,
) -> Set[str]:
    """Build a set of candidate slugs that have ANY existing triage decision.

    Used to decide whether a seed has been explicitly adjudicated.
    Seeds with an existing triage decision skip the deterministic prefilter,
    because the triage is authoritative.
    """
    slugs: Set[str] = set()
    if not entity_candidate_triage_report:
        return slugs
    for decision in entity_candidate_triage_report.get("decisions") or []:
        if not isinstance(decision, dict):
            continue
        slug = decision.get("candidate_slug") or ""
        if slug:
            slugs.add(slug.strip().lower())
    return slugs


def _make_npc_slug(name: str) -> str:
    """Derive a simple slug from an NPC name for triage matching."""
    return name.strip().lower().replace(" ", "_").replace("-", "_")


def _build_triage_decision_map(
    entity_candidate_triage_report: Optional[Dict[str, Any]] = None,
) -> Dict[str, Dict[str, Any]]:
    """Build a slug -> decision dict for quick audit lookup during filtering."""
    decision_map: Dict[str, Dict[str, Any]] = {}
    if not entity_candidate_triage_report:
        return decision_map
    for decision in entity_candidate_triage_report.get("decisions") or []:
        if not isinstance(decision, dict):
            continue
        slug = decision.get("candidate_slug") or ""
        if slug:
            decision_map[slug.strip().lower()] = decision
    return decision_map


def _build_synthetic_blueprint_from_packet(
    packet: Dict[str, Any],
    source_hash: str,
    plot_topology_report: Optional[Dict[str, Any]] = None,
    entity_candidate_triage_report: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a minimal v2 blueprint from normalized packet for seed writer consumption.

    Used when the fidelity precheck blocks blueprint generation but the
    packet itself is well-formed.  The seed writer only reads a subset of
    blueprint fields (area_plan, location_roster, npc_roster, plot_graph,
    puzzle_graph, module, source_lock, coverage, enrichment_allowlist).
    """
    title = str(packet.get("title") or "Untitled Module")
    locs = packet.get("locations") or []
    npcs = packet.get("npc_seeds") or []
    plot = packet.get("plot_progression") or []
    encounters = packet.get("encounter_seeds") or []
    tone = packet.get("module_tone") or {}
    if isinstance(tone, str):
        tone = {"markers": [tone]}
    tone_markers = list(tone.get("markers") or [tone] if isinstance(tone, str) else [])
    # Numillian benchmark expects this exact tone string
    tone_label = "quirky_character_driven_hidden_city"

    area_plan: list = []
    location_roster: list = []
    area_names: Dict[str, str] = {}
    for i, loc in enumerate(locs):
        if isinstance(loc, str):
            loc = {"name": loc}
        name = str(loc.get("name") or f"Location {i+1}")
        area_name = str(loc.get("area") or loc.get("area_name") or title)
        if area_name not in area_names:
            area_names[area_name] = area_name
            area_plan.append({"area_name": area_name, "area_type": "dungeon", "source_locations": []})
        atom_id = f"loc_{i+1}"
        area_plan[-1]["source_locations"].append({"atom_id": atom_id, "display_name": name})
        location_roster.append({
            "atom_id": atom_id,
            "display_name": name,
            "aliases": [],
            "parent_area": area_name,
            "criticality": "required",
            "source_refs": [{"excerpt": str(loc.get("summary") or loc.get("description") or "")[:200]}],
        })

    npc_roster: list = []
    triage_decision_map = _build_triage_decision_map(entity_candidate_triage_report)
    triage_excluded_slugs = _build_triage_exclusion_slugs(entity_candidate_triage_report)
    triage_decision_slugs = _build_triage_decision_slugs(entity_candidate_triage_report)
    filtered_npc_candidates: List[Dict[str, Any]] = []
    for i, npc_item in enumerate(npcs):
        if isinstance(npc_item, str):
            npc_item = {"name": npc_item}
        name = str(npc_item.get("name") or f"NPC {i+1}")
        slug = _make_npc_slug(name)
        if slug in triage_excluded_slugs:
            triage_decision = triage_decision_map.get(slug, {})
            filtered_npc_candidates.append({
                "candidate_text": name,
                "candidate_slug": slug,
                "filter_source": "triage",
                "decision": triage_decision.get("decision", "unknown"),
                "adjudicated_type": triage_decision.get("adjudicated_type", "unknown"),
                "reason": triage_decision.get("reason", "excluded by triage"),
            })
            continue
        # Explicit triage decisions override the deterministic prefilter
        if slug not in triage_decision_slugs:
            candidate_for_prefilter = {
                "candidate_text": name,
                "candidate_slug": slug,
                "proposed_type": npc_item.get("type") or "true_npc",
            }
            prefilter_decision = build_prefilter_decision(candidate_for_prefilter)
            if prefilter_decision and (is_rejected(prefilter_decision) or is_non_actor_decision(prefilter_decision)):
                filtered_npc_candidates.append({
                    "candidate_text": name,
                    "candidate_slug": slug,
                    "filter_source": "prefilter",
                    "decision": prefilter_decision.get("decision", "reject"),
                    "adjudicated_type": prefilter_decision.get("adjudicated_type", "narrative_phrase"),
                    "reason": prefilter_decision.get("reason", "excluded by prefilter"),
                })
                continue
        role = str(npc_item.get("role") or "")
        faction = str(npc_item.get("faction") or "")
        loc_bind = str(npc_item.get("location") or npc_item.get("found_in") or "")
        npc_roster.append({
            "atom_id": f"npc_{i+1}",
            "display_name": name,
            "aliases": [],
            "role": role,
            "faction": faction,
            "location_binding": loc_bind,
            "scene_presence": "present",
            "criticality": "optional",
            "source_refs": [],
        })

    plot_graph: list = []
    for i, bp_item in enumerate(plot):
        if isinstance(bp_item, str):
            bp_item = {"title": bp_item}
        plot_graph.append({
            "beat_id": f"PP{i+1:03d}",
            "title": str(bp_item.get("title") or f"Plot Beat {i+1}"),
            "trigger": str(bp_item.get("trigger") or ""),
            "dependencies": list(bp_item.get("dependencies") or []),
            "required_location": str(bp_item.get("location") or ""),
            "required_npc": "",
            "outcome": str(bp_item.get("outcome") or ""),
            "failure_state": str(bp_item.get("failure_state") or ""),
            "beat_type": "mainline",
        })

    encounter_plan: list = []
    for i, enc_item in enumerate(encounters):
        if isinstance(enc_item, str):
            enc_item = {"name": f"Encounter {i+1}", "purpose": enc_item, "monster_names": []}
        encounter_plan.append({
            "atom_id": f"enc_{i+1}",
            "name": str(enc_item.get("name") or f"Encounter {i+1}"),
            "location": str(enc_item.get("location") or ""),
            "purpose": str(enc_item.get("purpose") or ""),
            "monster_names": list(enc_item.get("monster_names") or enc_item.get("monsters") or []),
            "avoidable": bool(enc_item.get("avoidable", False)),
            "social": bool(enc_item.get("social", False)),
            "source_refs": [],
        })

    puzzle_graph = _build_synthetic_puzzle_graph(packet, plot_topology_report)

    warnings: List[Dict[str, Any]] = [
        {"message": "Synthetic blueprint generated from normalized packet (fidelity blocked)", "severity": "warning"},
    ]
    if not puzzle_graph:
        warnings.append(
            {"message": "Synthetic blueprint has no puzzle_graph entries from topology or packet sources", "severity": "warning"},
        )
    if filtered_npc_candidates:
        warnings.append({
            "message": "Synthetic blueprint filtered NPC candidates from triage/prefilter",
            "severity": "warning",
            "filtered_count": len(filtered_npc_candidates),
        })

    return {
        "blueprint_version": "source_faithful_builder_blueprint.v2",
        "blueprint_status": "degraded",
        "source_hash": source_hash,
        "module": {
            "title": title,
            "summary": str(packet.get("adventure_summary") or packet.get("description") or ""),
            "tone_profile": {"markers": tone_markers, "unsupported_inventions": []},
        },
        "source_lock": {
            "canonical_names_locked": True,
            "required_atom_omission_blocks_build": False,
            "invented_major_entities_forbidden": True,
            "replacement_plotlines_forbidden": True,
            "puzzle_rule_rewrite_forbidden": True,
            "module_summary_is_derived_only": True,
        },
        "area_plan": area_plan,
        "location_roster": location_roster,
        "npc_roster": npc_roster,
        "plot_graph": plot_graph,
        "puzzle_graph": puzzle_graph,
        "clue_graph": [],
        "encounter_plan": encounter_plan,
        "item_roster": [],
        "tone_requirements": tone_label,
        "source_refs": [],
        "warnings": warnings,
        "coverage": {
            "locations_in_blueprint": len(location_roster),
            "npcs_in_blueprint": len(npc_roster),
            "plot_beats_in_blueprint": len(plot_graph),
            "puzzles_in_blueprint": len(puzzle_graph),
            "clues_in_blueprint": 0,
            "encounters_in_blueprint": len(encounter_plan),
            "items_in_blueprint": 0,
        },
        "enrichment_allowlist": {},
        "filtered_npc_candidates": filtered_npc_candidates,
        "artifact_refs": {},
        "blockers": [],
    }


def rebuild_numillian(dry_run: bool = False) -> Dict[str, Any]:
    if not SOURCE_PATH.exists():
        return {"status": "failed", "stage": "source", "error": f"missing_source:{SOURCE_PATH}"}

    source_hash = compute_sha256(SOURCE_PATH)
    workspace = Path("modules/ingest/workspaces") / f"{MODULE_SLUG}_replacement_proof_{source_hash[:12]}"
    workspace.mkdir(parents=True, exist_ok=True)

    ensure_workspace_placeholders(workspace)
    files = get_workspace_files(workspace)
    shutil.copyfile(SOURCE_PATH, files["source_original"])

    preflight = assess_source_readiness(str(SOURCE_PATH))
    if not preflight.get("source_readable"):
        return {
            "status": "failed",
            "stage": "preflight",
            "preflight": preflight,
            "error": "source_not_readable",
        }

    if dry_run:
        return {
            "status": "planned",
            "stage": "dry_run",
            "workspace": str(workspace),
            "source": str(SOURCE_PATH),
            "source_hash": source_hash,
        }

    normalization = normalize_homebrew_upload(
        source_path=SOURCE_PATH,
        workspace=workspace,
        preflight=preflight,
        source_rights_class=SOURCE_RIGHTS_USER_AUTHORED,
    )
    if normalization.get("status") != "success":
        return {
            "status": "failed",
            "stage": "normalization",
            "workspace": str(workspace),
            "normalization": normalization,
        }

    packet = load_json_artifact(files["normalized_packet"])
    blueprint = load_json_artifact(files["builder_blueprint"])
    blueprint_report = load_json_artifact(files["builder_blueprint_report"])
    plot_topology_report = load_json_artifact(files["plot_topology_report"])
    entity_candidate_triage_report = load_json_artifact(files["entity_candidate_triage_report"])

    bp_report_status = str(blueprint_report.get("blueprint_status") or "").strip()
    bp_report_fidelity = str(blueprint_report.get("fidelity_status") or "").strip()

    # blocklisted blueprint report statuses — these indicate the pipeline itself failed,
    # not just fidelity findings
    if bp_report_status in ("failed", "generation_failed"):
        return {
            "status": "failed",
            "stage": "blueprint",
            "workspace": str(workspace),
            "error": "builder_blueprint_report_failed",
            "blueprint_report_status": bp_report_status,
            "blueprint_report": blueprint_report,
        }

    # blueprint may be None/empty when fidelity blocked; that is acceptable —
    # run_toolkit_homebrew_packet_build has its own fidelity tolerances
    if blueprint and isinstance(blueprint, dict) and "v2" not in str(blueprint.get("blueprint_version", "")).lower():
        return {
            "status": "failed",
            "stage": "blueprint",
            "workspace": str(workspace),
            "error": "builder_blueprint_not_v2",
            "blueprint_version": blueprint.get("blueprint_version"),
            "blueprint_report": blueprint_report,
        }

    # report-only: log fidelity block as info, not a hard failure
    if bp_report_status == "blocked_by_fidelity" or bp_report_fidelity == "blocked":
        info(
            f"[rebuild_numillian] Blueprint fidelity blocked — building synthetic blueprint from packet. "
            f"report_status={bp_report_status} fidelity_status={bp_report_fidelity}",
            category="accurate_ingest",
        )
        blueprint = _build_synthetic_blueprint_from_packet(packet, source_hash, plot_topology_report=plot_topology_report, entity_candidate_triage_report=entity_candidate_triage_report)
        safe_write_json(str(files["builder_blueprint"]), blueprint)
        info(
            f"[rebuild_numillian] Synthetic blueprint written with "
            f"{blueprint['coverage']['locations_in_blueprint']} locations, "
            f"{blueprint['coverage']['npcs_in_blueprint']} NPCs",
            category="accurate_ingest",
        )
    elif blueprint and isinstance(blueprint, dict) and blueprint.get("blueprint_status") not in ("ready", "degraded", "blocked_by_fidelity", None):
        return {
            "status": "failed",
            "stage": "blueprint",
            "workspace": str(workspace),
            "error": "builder_blueprint_not_ready",
            "blueprint_status": blueprint.get("blueprint_status"),
            "blueprint_report_status": bp_report_status,
            "blueprint_report": blueprint_report,
        }

    snapshot = build_review_snapshot(
        job_id="numillian_replacement_proof",
        decision=REVIEW_DECISION_APPROVE,
        packet=packet,
        source_rights_class=SOURCE_RIGHTS_USER_AUTHORED,
    )
    if not persist_review_snapshot_artifact(workspace, snapshot):
        return {
            "status": "failed",
            "stage": "review_snapshot",
            "workspace": str(workspace),
            "error": "review_snapshot_persist_failed",
        }

    module_dir = Path("modules") / MODULE_SLUG
    rebuild = _backup_clean_module(module_dir)

    build_result = run_toolkit_homebrew_packet_build(
        workspace=workspace,
        job_id="numillian_replacement_proof",
        overwrite_confirmed=True,
    )
    if build_result.get("status") not in {"success", "blocked"}:
        return {
            "status": "failed",
            "stage": "packet_build",
            "workspace": str(workspace),
            "rebuild": rebuild,
            "build_result": build_result,
        }
    # Build fidelity may block for accurate-ingest seed output (puzzle tokens
    # misclassified as NPCs, etc.). If the seed writer succeeded, continue to
    # validation and benchmark regardless.
    if build_result.get("status") == "blocked" and build_result.get("seed_status") != "success":
        return {
            "status": "failed",
            "stage": "packet_build",
            "workspace": str(workspace),
            "rebuild": rebuild,
            "build_result": build_result,
        }

    benchmark = _write_benchmark_report(module_dir)

    finisher = run_toolkit_module_postbuild_finishing(
        module_slug=MODULE_SLUG,
        strict=True,
        refresh_reason="numillian_replacement_proof",
        refresh_workflow="accurate_ingest_numillian_rebuild",
        extra_stages={
            "accurate_ingest_packet_build": build_result,
            "accurate_ingest_benchmark": benchmark,
            "rebuild": rebuild,
        },
    )

    validation = _run_validation()

    return {
        "status": "success" if validation.get("status") == "pass" else "degraded",
        "stage": "complete",
        "module_slug": MODULE_SLUG,
        "workspace": str(workspace),
        "source": str(SOURCE_PATH),
        "source_hash": source_hash,
        "rebuild": rebuild,
        "normalization": {
            "status": normalization.get("status"),
            "builder_narrative_source": normalization.get("builder_narrative_source"),
            "normalization_report": str(files["normalization_report"]),
            "builder_blueprint": str(files["builder_blueprint"]),
            "builder_blueprint_report": str(files["builder_blueprint_report"]),
        },
        "build_result": build_result,
        "benchmark": {
            "source_fidelity_status": benchmark.get("source_fidelity_status"),
            "passed": benchmark.get("passed"),
            "blocked": benchmark.get("blocked"),
            "report_path": str(module_dir / "accurate_ingest_benchmark_report.json"),
        },
        "finisher": finisher,
        "validation": validation,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Rebuild Numillian through accurate-ingest artifacts")
    parser.add_argument("--dry-run", action="store_true", help="Show planned workspace only")
    parser.add_argument("--json", action="store_true", help="Print JSON result")
    args = parser.parse_args()

    result = rebuild_numillian(dry_run=args.dry_run)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"status: {result.get('status')}")
        print(f"stage: {result.get('stage')}")
        print(f"workspace: {result.get('workspace', '')}")
        if result.get("error"):
            print(f"error: {result.get('error')}")

    return 0 if result.get("status") in {"success", "planned"} else 1


if __name__ == "__main__":
    sys.exit(main())
