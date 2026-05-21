# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Utility - Toolkit Homebrew Normalizer
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

Source-faithful normalization service for toolkit Homebrew markdown uploads.

This software is free for non-commercial and educational use.
Commercial competing use is prohibited for 2 years from release.
See LICENSE file for full terms.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from model_config import DM_MAIN_MODEL
from utils.ai_client_factory import create_chat_client, get_model_config
from utils.enhanced_logger import warning
from utils.toolkit_homebrew_upload_contract import (
    build_normalized_packet_placeholder,
    compute_sha256,
    persist_builder_narrative_artifact,
    persist_normalization_report_artifact,
    persist_normalized_packet_artifact,
    persist_identity_resolution_artifact,
    persist_plot_topology_artifact,
    persist_section_extraction_artifact,
    persist_section_extractions_index,
    persist_source_graph_artifact,
    persist_source_graph_synthesis_artifact,
    persist_source_manifest_artifact,
    persist_normalization_fidelity_artifact,
    persist_normalization_repair_artifact,
    persist_packet_repair_attempt_artifact,
    persist_packet_repair_attempts_index,
    load_section_extraction_artifact,
    persist_builder_blueprint_artifact,
    persist_builder_blueprint_report_artifact,
    persist_entity_candidate_triage_artifact,
)
from utils.toolkit_entity_candidate_triage import (
    build_entity_candidate_triage_report,
    build_prefilter_decision,
    build_triage_decision,
    build_underbound_npc_findings,
    TRIAGE_REPORT_STATUS_PASS,
)
from utils.toolkit_source_extraction import (
    build_extraction_index,
    build_extraction_units,
    record_section_extraction_result,
)
from utils.toolkit_source_graph_synthesis import (
    build_identity_resolution_report,
    build_plot_topology_report,
    build_source_graph_synthesis_report,
    synthesize_normalized_packet,
)
from utils.toolkit_source_manifest import build_source_graph, build_source_manifest

try:
    from model_config import ENABLE_ACCURATE_INGEST_MULTI_PASS
except Exception:
    ENABLE_ACCURATE_INGEST_MULTI_PASS = True

try:
    from model_config import (
        ENABLE_NORMALIZATION_FIDELITY_AUDIT,
        ENABLE_NORMALIZATION_FIDELITY_REPAIR,
        NORMALIZATION_FIDELITY_MAX_REPAIR_ATTEMPTS,
    )
except Exception:
    ENABLE_NORMALIZATION_FIDELITY_AUDIT = True
    ENABLE_NORMALIZATION_FIDELITY_REPAIR = True
    NORMALIZATION_FIDELITY_MAX_REPAIR_ATTEMPTS = 3

from utils.toolkit_normalization_fidelity import (
    apply_repair_operations,
    build_fidelity_summary_for_report,
    build_repair_attempt_artifact,
    run_normalization_fidelity_audit,
    validate_repair_operations,
)

try:
    from model_config import ENABLE_ACCURATE_INGEST_BLUEPRINT_HANDOFF
except Exception:
    ENABLE_ACCURATE_INGEST_BLUEPRINT_HANDOFF = True

from utils.toolkit_builder_blueprint import (
    build_builder_blueprint_report,
    evaluate_blueprint_fidelity_precheck,
    generate_builder_blueprint,
    generate_builder_blueprint_v2,
    load_phase2_artifacts,
    serialize_builder_blueprint_to_narrative,
)

NORMALIZATION_PROMPT_PATH = Path("prompts") / "toolkit" / "homebrew_upload_normalization_prompt.txt"
MAX_NORMALIZATION_SOURCE_CHARS = 120000


def _load_prompt() -> str:
    """Load normalization prompt template from disk."""
    try:
        return NORMALIZATION_PROMPT_PATH.read_text(encoding="utf-8")
    except Exception:
        return (
            "You are a strict source-faithful module normalizer. "
            "Return ONLY JSON with grounded fields and assumptions separated."
        )


def _load_section_prompt() -> str:
    """Load section extraction prompt template from disk."""
    section_prompt_path = (
        Path("prompts") / "toolkit" / "source_section_extraction_prompt.txt"
    )
    try:
        return section_prompt_path.read_text(encoding="utf-8")
    except Exception:
        return (
            "Extract structured facts from the supplied section text only. "
            "Return VALID JSON ONLY with extracted_atoms array. "
            "Every fact MUST include source_refs evidence. "
            "Mark uncertain items as ambiguous."
        )


def _load_identity_prompt() -> str:
    """Load identity adjudication prompt template from disk."""
    prompt_path = (
        Path("prompts") / "toolkit" / "source_identity_adjudication_prompt.txt"
    )
    try:
        return prompt_path.read_text(encoding="utf-8")
    except Exception:
        return (
            "Resolve aliases, duplicates, and ambiguous entity identities. "
            "Return VALID JSON ONLY with decisions array. "
            "Never merge without source evidence."
        )


def _load_plot_topology_prompt() -> str:
    """Load plot topology prompt template from disk."""
    prompt_path = (
        Path("prompts") / "toolkit" / "source_plot_topology_prompt.txt"
    )
    try:
        return prompt_path.read_text(encoding="utf-8")
    except Exception:
        return (
            "Convert adventure facts into structured plot, puzzle, clue, "
            "and trial topology. Return VALID JSON ONLY. "
            "Preserve source order when no dependency evidence exists."
        )


def _load_fidelity_repair_prompt() -> str:
    """Load fidelity repair prompt template from disk."""
    prompt_path = (
        Path("prompts") / "toolkit" / "normalization_fidelity_repair_prompt.txt"
    )
    try:
        return prompt_path.read_text(encoding="utf-8")
    except Exception:
        return (
            "Patch the normalized packet to include missing source-backed "
            "content. Return VALID JSON ONLY with operations array. "
            "Every operation MUST include source_refs evidence."
        )


def _validate_section_extraction_payload(payload: Dict[str, Any]) -> bool:
    """Validate a parsed section extraction payload has required shape.

    Returns False if extracted_atoms is missing, not a list, or contains
    non-dict entries without source evidence.
    """
    atoms = payload.get("extracted_atoms")
    if not isinstance(atoms, list):
        return False
    for atom in atoms:
        if not isinstance(atom, dict):
            return False
        # Each non-empty atom must carry at least one source evidence field
        src_refs = atom.get("source_refs")
        evidence = atom.get("evidence")
        if not isinstance(src_refs, list) or len(src_refs) == 0:
            if isinstance(evidence, str) and evidence.strip():
                continue
            return False
    return True


def _extract_json_payload(raw_text: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Extract JSON object from model response text."""
    text = str(raw_text or "").strip()
    if not text:
        return None, "empty_model_response"

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed, None
        return None, "model_response_not_object"
    except Exception:
        pass

    marker = "```json"
    lower_text = text.lower()
    start_index = lower_text.find(marker)
    if start_index == -1:
        start_index = text.find("```")
    if start_index != -1:
        fence_start = text.find("\n", start_index)
        if fence_start != -1:
            fence_end = text.find("```", fence_start + 1)
            if fence_end != -1:
                candidate = text[fence_start + 1:fence_end].strip()
                try:
                    parsed = json.loads(candidate)
                    if isinstance(parsed, dict):
                        return parsed, None
                    return None, "model_fenced_payload_not_object"
                except Exception:
                    return None, "model_fenced_payload_invalid_json"

    return None, "model_response_invalid_json"


def _as_list(value: Any) -> List[Any]:
    """Normalize potentially singular values to list."""
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]


def _as_string(value: Any) -> str:
    """Normalize arbitrary value to stripped string."""
    return str(value or "").strip()


def _build_builder_narrative(packet: Dict[str, Any], model_payload: Dict[str, Any]) -> str:
    """Build builder narrative text derived from normalized packet/model output."""
    candidate = _as_string(model_payload.get("builder_narrative"))
    if candidate:
        return candidate

    title = _as_string(packet.get("title")) or "Untitled Module"
    summary = _as_string(packet.get("adventure_summary"))
    tone = _as_string(packet.get("module_tone"))
    location_count = len(_as_list(packet.get("locations")))
    npc_count = len(_as_list(packet.get("npc_seeds")))
    monster_count = len(_as_list(packet.get("monster_refs")))

    parts = [f"Module: {title}"]
    if summary:
        parts.append(f"Summary: {summary}")
    if tone:
        parts.append(f"Tone: {tone}")
    parts.append(
        f"Scope: {location_count} locations, {npc_count} NPC seeds, {monster_count} monster references."
    )
    assumptions = _as_list(packet.get("assumptions"))
    if assumptions:
        parts.append("Assumptions: " + "; ".join(_as_string(a) for a in assumptions if _as_string(a)))
    return "\n".join(parts)


def _build_normalized_packet(
    source_path: Path,
    source_hash: str,
    preflight: Dict[str, Any],
    source_rights_class: str,
    model_payload: Dict[str, Any],
    source_was_truncated: bool,
) -> Dict[str, Any]:
    """Build normalized packet by merging model payload onto canonical placeholder."""
    base_packet = build_normalized_packet_placeholder(
        source_path=source_path,
        source_hash=source_hash or compute_sha256(source_path),
        preflight=preflight,
        source_rights_class=source_rights_class,
    )

    # TABLETOP MODE: Mark packet as model-normalized for review gate validation.
    base_packet["normalization_state"] = "normalized"

    string_fields = [
        "title",
        "author",
        "description",
        "adventure_summary",
        "module_tone",
    ]
    for field in string_fields:
        candidate = _as_string(model_payload.get(field))
        if candidate:
            base_packet[field] = candidate

    level_min = model_payload.get("estimated_level_min")
    level_max = model_payload.get("estimated_level_max")
    if isinstance(level_min, int):
        base_packet["estimated_level_min"] = level_min
    if isinstance(level_max, int):
        base_packet["estimated_level_max"] = level_max

    list_fields = [
        "acts",
        "locations",
        "connectivity_hints",
        "encounter_seeds",
        "npc_seeds",
        "monster_refs",
        "plot_progression",
        "continuity_hints",
        "media_hints",
        "assumptions",
        "warnings",
    ]
    for field in list_fields:
        base_packet[field] = _as_list(model_payload.get(field))

    grounded_facts = _as_list(model_payload.get("grounded_facts"))
    if grounded_facts:
        base_packet["confidence_notes"]["grounded_facts"] = grounded_facts

    if source_was_truncated:
        base_packet["warnings"].append(
            {
                "type": "source_truncated",
                "message": "Source was truncated for normalization token safety.",
            }
        )

    return base_packet


def normalize_homebrew_upload(
    source_path: Path,
    workspace: Path,
    preflight: Dict[str, Any],
    source_rights_class: str,
) -> Dict[str, Any]:
    """Run LLM normalization for a readable Homebrew upload source."""
    try:
        source_text = source_path.read_text(encoding="utf-8", errors="replace")
    except Exception as read_error:
        report = {
            "status": "failed",
            "stage": "normalizing",
            "error": f"source_read_failed: {read_error}",
        }
        persist_normalization_report_artifact(workspace, report)
        return report

    source_was_truncated = False
    normalized_source_text = source_text
    if len(normalized_source_text) > MAX_NORMALIZATION_SOURCE_CHARS:
        normalized_source_text = normalized_source_text[:MAX_NORMALIZATION_SOURCE_CHARS]
        source_was_truncated = True

    source_hash = compute_sha256(source_path)

    # Build deterministic source manifest and source graph before LLM call
    source_graph_degraded = False
    source_graph = None
    source_graph_summary = None
    try:
        source_graph = build_source_graph(
            source_text=source_text,
            source_path=str(source_path),
            source_hash=source_hash,
        )
        source_graph_summary = source_graph.get("summary", {}) if source_graph else None
        if workspace:
            manifest_ok = persist_source_manifest_artifact(
                workspace, build_source_manifest(source_text, str(source_path), source_hash)
            )
            graph_ok = persist_source_graph_artifact(workspace, source_graph)
            if not (manifest_ok and graph_ok):
                warning("TOOLKIT_HOMEBREW: Source graph artifact persistence failed",
                        category="web_interface")
                source_graph_degraded = True
    except Exception as graph_error:
        warning(f"TOOLKIT_HOMEBREW: Source graph generation failed: {graph_error}",
                category="web_interface")
        source_graph_degraded = True

    # -----------------------------------------------------------------
    #  Multipass section extraction and synthesis (Phase 2)
    # -----------------------------------------------------------------
    multipass_enabled = bool(ENABLE_ACCURATE_INGEST_MULTI_PASS)
    multipass_degraded = False
    identity_degraded = False
    topology_degraded = False
    artifact_persistence_degraded = False
    identity_report: Optional[Dict[str, Any]] = None
    plot_topology: Optional[Dict[str, Any]] = None
    synthesis_report: Optional[Dict[str, Any]] = None
    extraction_units: List[Dict[str, Any]] = []

    if multipass_enabled and source_graph is not None and not source_graph_degraded:
        try:
            # Step 1 -- build extraction units from manifest graph
            extraction_units = build_extraction_units(
                source_text=source_text,
                source_path=str(source_path),
                source_hash=source_hash,
                source_graph=source_graph,
            )

            # Step 2 -- section extraction per unit (with cache/skip)
            section_results: List[Dict[str, Any]] = []
            for unit in extraction_units:
                sec_id = unit["section_id"]
                sec_identity = unit.get("section_identity", "")

                # Cache check: reuse existing successful or cached artifact
                cached = None
                if workspace:
                    cached = load_section_extraction_artifact(workspace, sec_id)
                if (
                    cached
                    and cached.get("source_hash") == source_hash
                    and cached.get("section_identity") == sec_identity
                    and cached.get("status") in ("success", "cached")
                ):
                    result = record_section_extraction_result(
                        unit,
                        "cached",
                        cached.get("model", ""),
                        extracted_atoms=cached.get("extracted_atoms", []),
                        cache_hit=True,
                    )
                    section_results.append(result)
                    continue

                # Provider call for new/changed section
                section_prompt = _load_section_prompt()
                section_config = get_model_config("builders", DM_MAIN_MODEL)
                section_model = section_config.get("model", DM_MAIN_MODEL)
                section_text = unit.get("source_text", "")
                section_payload = json.dumps(
                    {
                        "section_id": unit["section_id"],
                        "heading_path": unit["heading_path"],
                        "line_start": unit["line_start"],
                        "line_end": unit["line_end"],
                        "atom_hints": unit.get("atom_hints", [])[:10],
                        "source_text": section_text,
                    },
                    ensure_ascii=True,
                )
                user_msg = (
                    "Extract structured facts from this source section.\n"
                    "Return JSON only.\n\n"
                    f"### SECTION CONTEXT\n{section_payload}"
                )
                try:
                    client = create_chat_client()
                    resp = client.chat.completions.create(
                        model=section_model,
                        messages=[
                            {"role": "system", "content": section_prompt},
                            {"role": "user", "content": user_msg},
                        ],
                        temperature=section_config.get("temperature", 0.2),
                        timeout=90,
                        **section_config.get("extra_body", {}),
                    )
                    section_raw = _as_string(resp.choices[0].message.content)
                    parsed, err = _extract_json_payload(section_raw)
                    if err:
                        result = record_section_extraction_result(
                            unit, "degraded", section_model, error=err,
                            response_preview=section_raw
                        )
                    elif not _validate_section_extraction_payload(parsed):
                        result = record_section_extraction_result(
                            unit, "degraded", section_model,
                            error="invalid_section_extraction_shape",
                            response_preview=section_raw,
                        )
                    else:
                        result = record_section_extraction_result(
                            unit, "success", section_model,
                            extracted_atoms=parsed.get("extracted_atoms", [])
                        )
                except Exception as sec_error:
                    result = record_section_extraction_result(
                        unit, "degraded", section_model,
                        error=f"provider_failed: {sec_error}"
                    )
                section_results.append(result)

            # Persist per-section artifacts and index
            if workspace:
                for unit_result in section_results:
                    ok = persist_section_extraction_artifact(
                        workspace,
                        unit_result.get("section_id", "unknown"),
                        unit_result,
                    )
                    if not ok:
                        artifact_persistence_degraded = True
                index = build_extraction_index(extraction_units)
                ok = persist_section_extractions_index(workspace, index)
                if not ok:
                    artifact_persistence_degraded = True

            # Step 3 -- identity adjudication (with LLM prompt)
            identity_adjudication_output: Optional[Dict[str, Any]] = None
            identity_prompt = _load_identity_prompt()
            try:
                # Build compact identity payload
                identity_atoms = []
                for a in (
                    source_graph.get("atoms", []) if source_graph else []
                ):
                    identity_atoms.append({
                        "id": a.get("id", ""),
                        "type": a.get("type", ""),
                        "name": a.get("name", ""),
                        "summary": a.get("summary", "")[:200],
                        "criticality": a.get("criticality", "minor"),
                        "confidence": a.get("confidence", "medium"),
                    })
                identity_user_msg = (
                    "Resolve identity aliases, duplicates, and ambiguous entities.\n"
                    "Return JSON only.\n\n"
                    f"MECHANICAL_CANDIDATES:\n{json.dumps(identity_atoms[:30], ensure_ascii=True)}\n\n"
                    f"SECTION_FACTS:\n{json.dumps([r.get('evidence_summary', {}) for r in section_results], ensure_ascii=True)}"
                )
                ident_client = create_chat_client()
                ident_config = get_model_config("builders", DM_MAIN_MODEL)
                ident_resp = ident_client.chat.completions.create(
                    model=ident_config.get("model", DM_MAIN_MODEL),
                    messages=[
                        {"role": "system", "content": identity_prompt},
                        {"role": "user", "content": identity_user_msg},
                    ],
                    temperature=ident_config.get("temperature", 0.2),
                    timeout=90,
                    **ident_config.get("extra_body", {}),
                )
                ident_raw = _as_string(ident_resp.choices[0].message.content)
                ident_parsed, ident_err = _extract_json_payload(ident_raw)
                if ident_err:
                    identity_degraded = True
                else:
                    identity_adjudication_output = ident_parsed
            except Exception:
                identity_degraded = True

            identity_report = build_identity_resolution_report(
                source_graph, section_results,
                adjudication_model_output=identity_adjudication_output,
            )
            if workspace:
                ok = persist_identity_resolution_artifact(workspace, identity_report)
                if not ok:
                    artifact_persistence_degraded = True

            # Step 3b -- entity candidate triage (deterministic prefilter)
            triage_decisions: List[Dict[str, Any]] = []
            triage_warnings: List[Dict[str, Any]] = []
            triage_blockers: List[Dict[str, Any]] = []
            if workspace and source_graph is not None:
                try:
                    atoms = source_graph.get("atoms", [])
                    for atom in atoms:
                        atom_type = atom.get("type", "")
                        if atom_type not in ("npc", "scene_actor", "monster_actor", "item", "faction", "mechanic", "puzzle", "encounter"):
                            continue
                        candidate = {
                            "candidate_text": atom.get("name", ""),
                            "candidate_slug": atom.get("id", atom.get("name", "")).replace(" ", "_").lower(),
                            "proposed_type": atom_type,
                            "source_refs": atom.get("source_refs"),
                        }
                        pref = build_prefilter_decision(candidate)
                        if pref is not None:
                            triage_decisions.append(pref)
                            continue
                        if atom_type == "npc":
                            deci = build_triage_decision(
                                candidate_text=candidate["candidate_text"],
                                candidate_slug=candidate["candidate_slug"],
                                proposed_type=atom_type,
                                adjudicated_type="true_npc",
                                decision="keep",
                                reason="Accepted from source graph without adjudication seam.",
                                source_refs=candidate.get("source_refs"),
                            )
                            triage_decisions.append(deci)

                    ub_findings = build_underbound_npc_findings(triage_decisions)
                    triage_warnings = ub_findings.get("warnings", [])
                    triage_blockers = ub_findings.get("blockers", [])

                    triage_report = build_entity_candidate_triage_report(
                        decisions=triage_decisions,
                        status=TRIAGE_REPORT_STATUS_PASS,
                        warnings=triage_warnings if triage_warnings else None,
                        blockers=triage_blockers if triage_blockers else None,
                    )
                    ok = persist_entity_candidate_triage_artifact(workspace, triage_report)
                    if not ok:
                        artifact_persistence_degraded = True
                except Exception:
                    artifact_persistence_degraded = True

            # Step 4 -- plot topology synthesis (with LLM prompt)
            topology_model_output: Optional[Dict[str, Any]] = None
            topology_prompt = _load_plot_topology_prompt()
            try:
                topology_user_msg = (
                    "Convert adventure facts into structured plot, puzzle, and trial topology.\n"
                    "Return JSON only.\n\n"
                    f"SOURCE_GRAPH_SUMMARY:\n{json.dumps(source_graph_summary or {}, ensure_ascii=True)}\n\n"
                    f"IDENTITY_SUMMARY:\n{json.dumps(identity_report.get('summary', {}), ensure_ascii=True)}"
                )
                topo_client = create_chat_client()
                topo_config = get_model_config("builders", DM_MAIN_MODEL)
                topo_resp = topo_client.chat.completions.create(
                    model=topo_config.get("model", DM_MAIN_MODEL),
                    messages=[
                        {"role": "system", "content": topology_prompt},
                        {"role": "user", "content": topology_user_msg},
                    ],
                    temperature=topo_config.get("temperature", 0.2),
                    timeout=90,
                    **topo_config.get("extra_body", {}),
                )
                topo_raw = _as_string(topo_resp.choices[0].message.content)
                topo_parsed, topo_err = _extract_json_payload(topo_raw)
                if topo_err:
                    topology_degraded = True
                else:
                    topology_model_output = topo_parsed
            except Exception:
                topology_degraded = True

            plot_topology = build_plot_topology_report(
                source_graph, section_results,
                topology_model_output=topology_model_output,
            )
            if workspace:
                ok = persist_plot_topology_artifact(workspace, plot_topology)
                if not ok:
                    artifact_persistence_degraded = True

            # Step 5 -- synthesis report
            synthesis_report = build_source_graph_synthesis_report(
                source_graph, section_results, identity_report, plot_topology
            )
            if workspace:
                ok = persist_source_graph_synthesis_artifact(workspace, synthesis_report)
                if not ok:
                    artifact_persistence_degraded = True

            section_degraded = any(
                r.get("status") == "degraded"
                for r in section_results
                if isinstance(r, dict)
            )

            if section_degraded or identity_degraded or topology_degraded or artifact_persistence_degraded:
                multipass_degraded = True

        except Exception as multipass_error:
            warning(
                f"TOOLKIT_HOMEBREW: Multipass normalization degraded: {multipass_error}",
                category="web_interface",
            )
            multipass_degraded = True
    elif multipass_enabled:
        multipass_degraded = True
        warning(
            "TOOLKIT_HOMEBREW: Multipass skipped -- missing or degraded source graph",
            category="web_interface",
        )

    # Collect multipass status for report inclusion
    multipass_summary: Dict[str, Any] = {}
    if multipass_enabled:
        multipass_summary = {
            "enabled": True,
            "degraded": multipass_degraded,
            "identity_degraded": identity_degraded,
            "topology_degraded": topology_degraded,
            "artifact_persistence_degraded": artifact_persistence_degraded,
            "extraction_units": len(extraction_units),
            "successful_sections": sum(
                1 for u in extraction_units if u.get("status") == "success"
            ),
            "cached_sections": sum(
                1 for u in extraction_units if u.get("cache_hit")
            ),
            "degraded_sections": sum(
                1 for u in extraction_units if u.get("status") == "degraded"
            ),
            "identity_canonical_count": (
                identity_report.get("summary", {}).get("total_canonical", 0)
                if identity_report
                else 0
            ),
            "identity_ambiguous_count": (
                identity_report.get("summary", {}).get("total_ambiguous", 0)
                if identity_report
                else 0
            ),
            "plot_beats": (
                len(plot_topology.get("plot_beats", [])) if plot_topology else 0
            ),
            "puzzle_chains": (
                len(plot_topology.get("puzzle_chains", [])) if plot_topology else 0
            ),
        }
    else:
        multipass_summary = {"enabled": False, "degraded": False}
    # -----------------------------------------------------------------
    #  Legacy one-shot LLM normalization (always runs as fallback)
    # -----------------------------------------------------------------

    prompt_template = _load_prompt()
    model_config = get_model_config("builders", DM_MAIN_MODEL)
    model_name = model_config.get("model", DM_MAIN_MODEL)

    request_payload = {
        "source_filename": source_path.name,
        "preflight": preflight,
        "source_text": normalized_source_text,
    }
    user_prompt = (
        "Normalize the uploaded Homebrew markdown into the required JSON contract.\n"
        "Return JSON only.\n\n"
        f"INPUT_PAYLOAD:\n{json.dumps(request_payload, ensure_ascii=True)}"
    )

    try:
        client = create_chat_client()
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": prompt_template},
                {"role": "user", "content": user_prompt},
            ],
            temperature=model_config.get("temperature", 0.3),
            timeout=120,
            **model_config.get("extra_body", {}),
        )
        model_text = _as_string(response.choices[0].message.content)
    except Exception as provider_error:
        report = {
            "status": "failed",
            "stage": "normalizing",
            "error": f"normalizer_provider_failed: {provider_error}",
            "model": model_name,
            "source_graph_degraded": source_graph_degraded,
            "multipass": multipass_summary,
        }
        if source_graph_summary:
            report["source_graph"] = source_graph_summary
        persist_normalization_report_artifact(workspace, report)
        return report

    model_payload, parse_error = _extract_json_payload(model_text)
    if parse_error:
        report = {
            "status": "failed",
            "stage": "normalizing",
            "error": parse_error,
            "model": model_name,
            "response_preview": model_text[:1000],
            "source_graph_degraded": source_graph_degraded,
            "multipass": multipass_summary,
        }
        if source_graph_summary:
            report["source_graph"] = source_graph_summary
        persist_normalization_report_artifact(workspace, report)
        return report

    # Build legacy packet first as base contract
    legacy_packet = _build_normalized_packet(
        source_path=source_path,
        source_hash=source_hash,
        preflight=preflight,
        source_rights_class=source_rights_class,
        model_payload=model_payload or {},
        source_was_truncated=source_was_truncated,
    )

    # Overlay with source-graph synthesis when multipass has results
    if (
        multipass_enabled
        and source_graph is not None
        and identity_report is not None
        and plot_topology is not None
    ):
        packet = synthesize_normalized_packet(
            source_graph,
            identity_report,
            plot_topology,
            legacy_model_payload=legacy_packet,
        )
        # Ensure contract fields survive from legacy packet
        for key in (
            "packet_version",
            "normalization_state",
            "source_path",
            "source_hash",
            "source_rights_class",
            "review_policy",
            "v2_alignment",
            "provenance",
        ):
            if key in legacy_packet and key not in packet:
                packet[key] = legacy_packet[key]
        packet["normalization_state"] = "normalized"
    else:
        packet = legacy_packet

    # -----------------------------------------------------------------
    #  Normalization fidelity audit and bounded repair loop (Phase 3)
    # -----------------------------------------------------------------
    fidelity_enabled = bool(ENABLE_NORMALIZATION_FIDELITY_AUDIT)
    repair_enabled = bool(ENABLE_NORMALIZATION_FIDELITY_REPAIR)
    fidelity_report: Dict[str, Any] = {}
    repair_summary: Dict[str, Any] = {}
    max_repair_attempts = int(NORMALIZATION_FIDELITY_MAX_REPAIR_ATTEMPTS)

    if fidelity_enabled:
        fidelity_report = run_normalization_fidelity_audit(
            source_graph=source_graph,
            identity_report=identity_report,
            plot_topology=plot_topology,
            normalized_packet=packet,
        )
        if workspace:
            persist_normalization_fidelity_artifact(workspace, fidelity_report)

        # Bounded repair loop
        if (
            repair_enabled
            and fidelity_report.get("status") in ("blocked", "degraded")
        ):
            repairable_findings = [
                f for f in fidelity_report.get("findings", [])
                if f.get("repairable")
            ]
            repair_attempt_made = False
            repair_ok = False
            attempts_tried = 0
            repair_index_entries: List[Dict[str, Any]] = []

            for attempt in range(1, max_repair_attempts + 1):
                attempts_tried = attempt
                repairable_findings = [
                    f for f in fidelity_report.get("findings", [])
                    if f.get("repairable")
                ]
                if not repairable_findings:
                    break

                repair_prompt = _load_fidelity_repair_prompt()
                repair_config = get_model_config("builders", DM_MAIN_MODEL)
                repair_model = repair_config.get("model", DM_MAIN_MODEL)
                repair_user_msg = (
                    "Propose additive packet repair operations for these fidelity gaps.\n"
                    "Return JSON only.\n\n"
                    f"MISSING_FINDINGS:\n{json.dumps(repairable_findings[:20], ensure_ascii=True)}\n\n"
                    f"CURRENT_PACKET_KEYS:\n{json.dumps(sorted(packet.keys()), ensure_ascii=True)}"
                )
                model_output = ""
                proposed_ops: List[Dict[str, Any]] = []
                accepted_ops: List[Dict[str, Any]] = []
                rejected_ops: List[Dict[str, Any]] = []

                try:
                    repair_client = create_chat_client()
                    repair_resp = repair_client.chat.completions.create(
                        model=repair_model,
                        messages=[
                            {"role": "system", "content": repair_prompt},
                            {"role": "user", "content": repair_user_msg},
                        ],
                        temperature=repair_config.get("temperature", 0.2),
                        timeout=90,
                        **repair_config.get("extra_body", {}),
                    )
                    model_output = _as_string(repair_resp.choices[0].message.content)
                    parsed, parse_err = _extract_json_payload(model_output)
                    if parse_err:
                        attempt_artifact = build_repair_attempt_artifact(
                            attempt, repair_user_msg, model_output,
                            [], [], [],
                            applied=False, status="parse_error", reason=parse_err,
                        )
                        if workspace:
                            persist_packet_repair_attempt_artifact(workspace, attempt, attempt_artifact)
                            repair_index_entries.append({"attempt": attempt, "status": "parse_error"})
                        continue

                    proposed_ops = parsed.get("operations", [])
                except Exception as repair_error:
                    attempt_artifact = build_repair_attempt_artifact(
                        attempt, repair_user_msg, "",
                        [], [], [],
                        applied=False, status="provider_failed",
                        reason=f"provider_failed: {repair_error}",
                    )
                    if workspace:
                        persist_packet_repair_attempt_artifact(workspace, attempt, attempt_artifact)
                        repair_index_entries.append({"attempt": attempt, "status": "provider_failed"})
                    continue

                accepted_ops, rejected_ops = validate_repair_operations(
                    proposed_ops, repairable_findings, source_graph
                )
                if not accepted_ops:
                    attempt_artifact = build_repair_attempt_artifact(
                        attempt, repair_user_msg, model_output,
                        proposed_ops, accepted_ops, rejected_ops,
                        applied=False, status="all_rejected",
                        reason="No operations passed source-evidence validation",
                    )
                    if workspace:
                        persist_packet_repair_attempt_artifact(workspace, attempt, attempt_artifact)
                        repair_index_entries.append({"attempt": attempt, "status": "all_rejected"})
                    continue

                # Apply accepted operations to a packet copy
                repaired_packet = apply_repair_operations(packet, accepted_ops)
                # Re-audit
                re_audit = run_normalization_fidelity_audit(
                    source_graph=source_graph,
                    identity_report=identity_report,
                    plot_topology=plot_topology,
                    normalized_packet=repaired_packet,
                )
                attempt_artifact = build_repair_attempt_artifact(
                    attempt, repair_user_msg, model_output,
                    proposed_ops, accepted_ops, rejected_ops,
                    applied=True, status=re_audit.get("status", "unknown"),
                    reason="",
                )
                if workspace:
                    persist_packet_repair_attempt_artifact(workspace, attempt, attempt_artifact)
                    repair_index_entries.append({"attempt": attempt, "status": re_audit.get("status", "unknown")})

                repair_attempt_made = True
                packet = repaired_packet
                fidelity_report = re_audit
                if re_audit.get("status") == "clean":
                    repair_ok = True
                    break
                if re_audit.get("status") not in ("blocked", "degraded"):
                    repair_ok = re_audit.get("status") == "degraded"
                    break

            if workspace and repair_index_entries:
                persist_packet_repair_attempts_index(
                    workspace,
                    {
                        "index_version": "packet_repair_attempts.v1",
                        "total_attempts": attempts_tried,
                        "entries": repair_index_entries,
                    },
                )

            repair_summary = {
                "repair_attempted": repair_attempt_made,
                "repair_attempts": attempts_tried,
                "repair_status": (
                    "success" if repair_ok
                    else "provider_failed" if not repair_attempt_made
                    else "failed"
                ),
            }
            if workspace and repair_attempt_made:
                persist_normalization_repair_artifact(
                    workspace,
                    {"repair_report_version": "normalization_repair.v1", "summary": repair_summary},
                )

    # -----------------------------------------------------------------
    #  Phase 4: Builder blueprint generation and source-locked narrative
    # -----------------------------------------------------------------
    blueprint_summary: Dict[str, Any] = {}
    blueprint_ready = False
    blueprint_narrative_text = ""
    blueprint_enabled = bool(ENABLE_ACCURATE_INGEST_BLUEPRINT_HANDOFF)
    if blueprint_enabled and workspace:
        bp_artifacts = load_phase2_artifacts({
            "source_graph": workspace / "source_graph.json",
            "identity_resolution_report": workspace / "identity_resolution_report.json",
            "plot_topology_report": workspace / "plot_topology_report.json",
            "source_graph_synthesis_report": workspace / "source_graph_synthesis_report.json",
            "normalized_packet": workspace / "normalized_packet.json",
            "normalization_fidelity_report": workspace / "normalization_fidelity_report.json",
            "normalization_report": workspace / "normalization_report.json",
            "entity_candidate_triage_report": workspace / "entity_candidate_triage_report.json",
        })
        # Override placeholders with live artifacts from this normalization run.
        # Placeholder normalized_packet.json is truthy, so `or packet` is unsafe here.
        if source_graph is not None:
            bp_artifacts["source_graph"] = source_graph
        if identity_report is not None:
            bp_artifacts["identity_resolution_report"] = identity_report
        if plot_topology is not None:
            bp_artifacts["plot_topology_report"] = plot_topology
        if synthesis_report is not None:
            bp_artifacts["source_graph_synthesis_report"] = synthesis_report
        bp_artifacts["normalized_packet"] = packet
        if fidelity_report:
            bp_artifacts["normalization_fidelity_report"] = fidelity_report

        precheck = evaluate_blueprint_fidelity_precheck(
            source_graph=bp_artifacts["source_graph"],
            normalized_packet=bp_artifacts["normalized_packet"],
            fidelity_report=bp_artifacts["normalization_fidelity_report"],
            normalization_report=bp_artifacts["normalization_report"],
        )

        if precheck.get("precheck_status") == "allowed":
            try:
                bp = generate_builder_blueprint_v2(
                    source_graph=bp_artifacts["source_graph"],
                    identity_report=bp_artifacts["identity_resolution_report"],
                    plot_topology=bp_artifacts["plot_topology_report"],
                    synthesis_report=bp_artifacts["source_graph_synthesis_report"],
                    normalized_packet=bp_artifacts["normalized_packet"],
                    fidelity_report=bp_artifacts["normalization_fidelity_report"],
                    triage_report=bp_artifacts.get("entity_candidate_triage_report"),
                )
                bp_report = build_builder_blueprint_report(
                    blueprint_status="ready",
                    artifacts=bp_artifacts,
                    precheck_result=precheck,
                    blueprint=bp,
                )
                blueprint_narrative_text = serialize_builder_blueprint_to_narrative(bp)
                bp_ok = persist_builder_blueprint_artifact(workspace, bp)
                bp_report_ok = persist_builder_blueprint_report_artifact(workspace, bp_report)
                if bp_ok and bp_report_ok:
                    blueprint_ready = True
                    blueprint_summary = {
                        "blueprint_status": "ready",
                        "npc_count": len(bp.get("npc_roster") or []),
                        "location_count": len(bp.get("location_roster") or []),
                        "blueprint_persisted": bp_ok,
                    }
            except Exception as bp_error:
                err_report = build_builder_blueprint_report(
                    blueprint_status="generation_failed",
                    artifacts=bp_artifacts,
                    precheck_result=precheck,
                )
                persist_builder_blueprint_report_artifact(workspace, err_report)
                blueprint_summary = {
                    "blueprint_status": "generation_failed",
                    "error": str(bp_error),
                }
        else:
            err_report = build_builder_blueprint_report(
                blueprint_status=precheck.get("refusal_reason", "blocked_by_fidelity"),
                artifacts=bp_artifacts,
                precheck_result=precheck,
            )
            persist_builder_blueprint_report_artifact(workspace, err_report)
            blueprint_summary = {
                "blueprint_status": precheck.get("refusal_reason", "blocked_by_fidelity"),
                "refusal_reason": precheck.get("detail", ""),
            }

    # Select narrative: blueprint-derived when ready, legacy otherwise
    if blueprint_ready and blueprint_narrative_text:
        builder_narrative = blueprint_narrative_text
        builder_narrative_source = "blueprint"
    else:
        builder_narrative = _build_builder_narrative(packet, model_payload or {})
        builder_narrative_source = "legacy"

    report = {
        "status": "success",
        "stage": "normalizing",
        "model": model_name,
        "source_chars": len(source_text),
        "normalized_source_chars": len(normalized_source_text),
        "source_truncated": source_was_truncated,
        "assumptions_count": len(_as_list(packet.get("assumptions"))),
        "warnings_count": len(_as_list(packet.get("warnings"))),
        "grounded_facts_count": len(_as_list(packet.get("confidence_notes", {}).get("grounded_facts"))),
        "source_graph_degraded": source_graph_degraded,
        "multipass": multipass_summary,
        "fidelity": build_fidelity_summary_for_report(fidelity_report),
        "repair": repair_summary,
        "blueprint": blueprint_summary if blueprint_summary else None,
    }

    if source_graph_summary:
        report["source_graph"] = source_graph_summary

    packet_ok = persist_normalized_packet_artifact(workspace, packet)
    report_ok = persist_normalization_report_artifact(workspace, report)
    narrative_ok = persist_builder_narrative_artifact(workspace, builder_narrative)

    if not (packet_ok and report_ok and narrative_ok):
        warning(
            "TOOLKIT_HOMEBREW: Normalization artifact persistence failed",
            category="web_interface",
        )
        failed_report = dict(report)
        failed_report["status"] = "failed"
        failed_report["error"] = "normalization_artifact_persistence_failed"
        failed_report["packet_persisted"] = packet_ok
        failed_report["report_persisted"] = report_ok
        failed_report["builder_narrative_persisted"] = narrative_ok
        persist_normalization_report_artifact(workspace, failed_report)
        return {
            "status": "failed",
            "stage": "normalizing",
            "error": "normalization_artifact_persistence_failed",
            "model": model_name,
            "packet_persisted": packet_ok,
            "report_persisted": report_ok,
            "builder_narrative_persisted": narrative_ok,
            "normalized_packet": packet,
            "normalization_report": failed_report,
        }

    return {
        "status": "success",
        "stage": "normalizing",
        "model": model_name,
        "normalized_packet": packet,
        "normalization_report": report,
        "builder_narrative": builder_narrative,
        "builder_narrative_source": builder_narrative_source,
        "source_truncated": source_was_truncated,
    }
