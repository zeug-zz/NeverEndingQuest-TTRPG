## Context

`toolkit-accurate-ingest-multipass-normalization` produces source graph, section extraction, identity, topology, synthesis, and packet artifacts. Those artifacts make source-faithful normalization possible, but they do not yet prove that the final `normalized_packet.json` preserved required NPCs, locations, plot beats, puzzles, clues, tone markers, and source constraints.

This change adds an audit-and-repair layer between packet synthesis and later builder handoff. It deliberately stops before builder blueprint generation and build-time fidelity gates.

## Contract Layer (MUST)

- Fidelity audit MUST run after `normalized_packet.json` synthesis and before any later builder handoff in the readable-source upload path.
- Fidelity audit MUST compare packet content against source-backed artifacts, not against freeform model summary alone.
- Required source atoms MUST be classified as covered, missing, distorted, unsupported, ambiguous, or not-applicable.
- Audit output MUST include source atom IDs and source refs for every blocking fidelity finding where available.
- Audit output MUST distinguish deterministic findings from LLM-advisory findings.
- Repair attempts MUST be bounded by a configured maximum attempt count.
- Repair attempts MUST produce patch proposals, not direct file writes.
- Python validation MUST reject repair proposals that lack source refs, introduce unsupported additions, violate `validate_review_packet(...)`, or overwrite existing source-backed packet content without stronger evidence.
- Repair failure MUST NOT delete source graph, multipass artifacts, original packet, or previous reports.
- Repair success MUST persist a review-compatible `normalized_packet.json` and a repair trail.
- User-facing Python log/console text introduced by implementation MUST be ASCII-only.

## Guidance Layer (SHOULD)

- Fidelity scoring SHOULD weight required source atoms more heavily than minor tone or optional detail atoms.
- Required NPCs, keyed locations, puzzle rules, clue dependencies, and mainline plot beats SHOULD be blocking if missing.
- Unsupported packet additions SHOULD be warning or blocking depending on whether they replace or obscure source truth.
- Repair prompts SHOULD be compact and include only relevant missing/distorted findings plus bounded source excerpts.
- Repair should prefer additive packet patches over destructive rewrites.
- Reports SHOULD include compact rollups in `normalization_report.json` and detailed evidence in dedicated artifacts.

## Artifact Contract

New workspace artifacts planned by this change:

- `normalization_fidelity_report.json` - source graph vs normalized packet coverage, severity, and repairability report.
- `packet_repair_attempts/index.json` - registry of repair attempts and outcomes.
- `packet_repair_attempts/attempt_<n>.json` - prompt inputs, proposed patch, validation result, applied flag, and rejection reasons.
- `normalization_repair_report.json` - compact final repair summary and final fidelity status.

Existing artifacts affected by implementation:

- `normalization_report.json` should include compact fidelity fields: audit status, fidelity status, blocking count, warning count, repair attempted, repair status, and final packet state.
- `normalized_packet.json` may be replaced only by a validated repaired packet.

## Fidelity Finding Model

Findings should have a stable shape similar to:

```json
{
  "finding_id": "stable_hash_or_sequence",
  "source_atom_id": "npc_wayne_...",
  "category": "missing|distorted|unsupported|ambiguous|covered",
  "severity": "blocking|warning|info",
  "repairable": true,
  "packet_path": "npc_seeds[?]",
  "expected": "Wayne the crooked-toothed innkeeper",
  "actual": "",
  "source_refs": [
    {"line_start": 21, "line_end": 23, "excerpt": "Wayne the crooked-toothed innkeeper"}
  ],
  "evidence_basis": "deterministic|llm_advisory"
}
```

## Repair Patch Model

Repair proposals should use additive and path-scoped operations similar to:

```json
{
  "repair_version": "normalization_packet_repair.v1",
  "operations": [
    {
      "op": "add_npc_seed",
      "source_atom_id": "npc_wayne_...",
      "target_path": "npc_seeds",
      "value": {"name": "Wayne", "role": "Innkeeper"},
      "source_refs": [{"line_start": 21, "excerpt": "Wayne..."}]
    }
  ]
}
```

Allowed operation names should be narrow for this slice: `add_location`, `add_npc_seed`, `add_monster_ref`, `add_plot_progression`, `add_warning`, `add_confidence_note`, `add_connectivity_hint`, and `add_assumption`. Broader destructive operations should be deferred.

## Orchestration

1. Load `source_graph.json`, `identity_resolution_report.json`, `plot_topology_report.json`, and `normalized_packet.json` when present.
2. Build deterministic packet coverage indexes for NPCs, locations, monsters, plot beats, puzzle chains, clue dependencies, warnings, assumptions, and tone notes.
3. Compare required and major source atoms against packet indexes.
4. Emit `normalization_fidelity_report.json`.
5. If repair is enabled and blocking repairable findings exist, build a bounded repair prompt.
6. Parse LLM repair proposal as JSON only.
7. Validate patch operations against source refs and packet schema compatibility.
8. Apply accepted operations to a packet copy.
9. Re-run fidelity audit on the repaired packet.
10. Persist final repair artifacts and compact status.

## Degraded Behavior

- If source graph artifacts are missing, audit reports `status=skipped` with reason `missing_source_artifacts` and no repair runs.
- If packet validation fails before repair, audit reports `status=failed` and repair may run only if a safe packet baseline exists.
- If repair provider fails, audit remains available and `normalization_report.json` records `repair_status=provider_failed`.
- If all repair attempts fail validation, the original packet remains authoritative and the report records repair failure.

## Rollback

Rollback is straightforward: disable fidelity audit/repair flags and leave multipass packet synthesis unchanged. Existing fidelity and repair artifacts are additive and safe to ignore.
