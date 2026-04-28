# Context

The immediate spatial model is a single 2D cardinal grid. Under that model, overlapping coordinates are invalid and every authored edge must be Manhattan distance 1. Coordinate-only solvers cannot guarantee success for every graph under bounded search and current schema. Topology normalization can guarantee adjacency by adding real connector nodes and replacing impossible direct edges with valid connector paths.

# Goals

- Deterministically repair unresolved spatial adjacency failures after coordinate-only solving fails.
- Preserve all original authored rooms.
- Preserve reachability intent by replacing impossible edges with connector paths.
- Keep generated content visible, provenance-tagged, and parity-synchronized across area/map artifacts.
- Keep LLM advisory, optional, and non-authoritative.

# Non-Goals

- Same-coordinate multi-plane rooms.
- Invisible validator exceptions.
- LLM-authored canonical topology mutation.
- Semantic rewrite of plot, NPC, monster, or quest content.

# Decisions

1. Connector insertion SHALL be deterministic and Python-owned.
   - For an unresolved edge `A <-> B`, remediation creates one or more connector nodes and replaces the direct edge with `A <-> Connector... <-> B`.
   - Connector count MAY be more than one if needed to satisfy coordinate pathing.

2. Generated connectors SHALL be real module content.
   - They must appear in area data and any map/graph structures needed by validators.
   - They must not be hidden-only metadata.

3. Provenance SHALL be explicit.
   - Generated connectors should carry a payload such as:

```json
{
  "spatial_remediation": {
    "generated": true,
    "reason": "non_embed_edge",
    "source_edge": ["A", "B"],
    "method": "deterministic_connector_insertion"
  }
}
```

4. No overlapping coordinates in this change.
   - Same X/Y in different dimensions requires a future schema and validator contract for `plane`, `layer`, or `dimension`.
   - Until then, every location occupies a unique coordinate in the emitted map.

5. LLM builder intervention SHALL be advisory only.
   - Python may ask an LLM for flavor/name suggestions after it identifies exact structural debt.
   - Suggestions must be constrained to whitelisted connector archetypes and validated before use.
   - If the LLM fails or suggests invalid content, deterministic templates are used.

# Connector Archetypes

- `hidden_passage`: mundane passage or secret corridor.
- `trapdoor_crawlspace`: vertical or cramped connector.
- `mirror_portal`: magical transition point.
- `dimensional_threshold`: weird-space connector for high-fantasy modules.
- `service_tunnel`: architectural connector.

The builder SHOULD choose from archetypes using stable deterministic inputs such as module tone, area tags, source/destination names, and existing transition labels.

# Algorithm Sketch

1. Run corrected coordinate-only solver.
2. If it succeeds, stop.
3. Collect unresolved edges from solver diagnostics.
4. For each unresolved edge, choose connector archetype deterministically.
5. Create connector location id and display name using stable collision-resistant naming.
6. Replace direct connectivity edge with connector path.
7. Assign connector coordinates using an available cardinal route or re-run coordinate solving on the normalized graph.
8. Synchronize area and map artifacts.
9. Re-run spatial contract and map/area parity validation.
10. If validation still fails, emit `author_structural_debt` and do not publish as repaired.

# Hard Constraints

- The original authored rooms MUST remain present.
- Generated connectors MUST be reachable.
- Final success MUST be based on post-normalization validation.
- Validation scripts MUST remain non-mutating.

# Guidance

- Prefer one connector per unresolved edge when possible.
- Keep connector descriptions short and functional in the first implementation.
- Do not overuse exotic dimensional flavor for mundane modules.

# Migration and Rollback

- Connector insertion should be opt-in through an explicit remediation/build flag until reviewed.
- Generated connector nodes can be removed by reverting module artifact changes or rerunning remediation without topology normalization.
- If provenance schema proves too broad, narrow it before archive rather than supporting unreviewed variants.

# Verification Plan

- `.venv/bin/python -m py_compile scripts/remediate_module_coordinates.py scripts/test_spatial_embedding_solver.py scripts/test_spatial_coordinate_grounding.py scripts/test_analyze_module_spatial_parity.py`
- `.venv/bin/python scripts/test_spatial_embedding_solver.py`
- `.venv/bin/python scripts/test_spatial_coordinate_grounding.py`
- `.venv/bin/python scripts/test_analyze_module_spatial_parity.py`
- `.venv/bin/python scripts/audit_module_publishability.py --module The_Hidden_City_of_Numillian --json`
- Add a fixture proving an unsatisfied edge becomes a connector path and passes post-normalization validation.
