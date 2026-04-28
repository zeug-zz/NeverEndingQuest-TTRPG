# Context

The current spatial solver plan has a valid Tier 1 idea and invalid Tier 2/Tier 3 guarantees. Coordinate-only embedding on a 2D cardinal grid is a constraint satisfaction problem. If a graph cannot be embedded under those constraints within the bounded search budget, a coordinate-only fallback cannot truthfully guarantee success.

# Goals

- Make Tier 1 the only coordinate-only solver that can produce authoritative success.
- Improve Tier 1 determinism, diagnostics, and search ordering.
- Ensure Tier 2/Tier 3 cannot report success unless the final output passes strict adjacency validation.
- Prepare exact failure diagnostics for the topology-normalization failsafe.

# Non-Goals

- Connector insertion or topology mutation.
- LLM involvement.
- Relaxing map/area parity validation.

# Decisions

1. Tier 1 SHALL be the authoritative coordinate-only solver.
   - It SHOULD order rooms by descending degree, then by constrained-neighbor count, then stable room id.
   - It SHOULD place rooms with the fewest legal candidate cells first after each assignment.
   - It MUST terminate within configured limits and report whether failure was due to no solution found or budget exhaustion.

2. Success SHALL be validator-derived, not tier-derived.
   - Any coordinate output from any helper MUST run through `_is_fully_adjacent` or equivalent strict graph validation.
   - A tier name alone MUST NOT imply success.

3. Tier 2 SHALL become best-effort refinement or diagnostics.
   - `_relax_with_expansion` may still attempt to improve near-miss layouts.
   - It MUST return `success=false` if any authored edge remains non-cardinal.
   - It SHOULD report unresolved edges, distances, and blocking occupancy.

4. Tier 3 linear layout SHALL be rolled back as a general fallback.
   - `_build_linear_layout` MAY remain only for chain/tree fixtures where full validation passes.
   - It MUST NOT be described as valid for arbitrary connected graphs.
   - It MUST NOT publish coordinates for graphs with unresolved cross-edges.

5. Diagnostics SHALL be structured enough for downstream deterministic topology normalization.
   - Include `error_class`, `tier`, `rooms`, `edge`, `distance`, `reason`, and `suggested_next_step` where applicable.

# Architecture

- Add or refactor a solver result envelope such as:

```json
{
  "status": "success|failed",
  "tier": "tier1_constraint_solver|tier2_best_effort|tier3_chain_only",
  "coordinates": {},
  "unresolved_edges": [],
  "diagnostics": []
}
```

- Route all fallback outputs through one validator gate before writing coordinates.
- Treat unvalidated outputs as diagnostics only.
- Keep validation non-mutating; remediation may write only after validation accepts the proposed coordinates.

# Hard Constraints

- No solver tier may claim success while any graph edge has Manhattan distance other than 1.
- No fallback may overlap rooms on the same coordinate.
- No fallback may remove authored connectivity in this change.

# Guidance

- Prefer small deterministic improvements over broad heuristic rewrites.
- Keep Tier 1 room cap configurable and conservative until regression data proves higher limits are safe.
- Use fixture names that encode topology shape: `bread_loaf`, `cross_edge`, `star_degree4`, `chain`, `non_embed_budget`.

# Migration and Rollback

- Existing modules are not mutated by this scaffold.
- Rollback is straightforward: restore previous solver orchestration, though this would reintroduce false-success risk.
- The dependent topology-normalization failsafe should consume diagnostics rather than relying on legacy Tier 2/Tier 3 behavior.

# Verification Plan

- `.venv/bin/python -m py_compile scripts/remediate_module_coordinates.py scripts/test_spatial_embedding_solver.py scripts/test_spatial_coordinate_grounding.py scripts/test_analyze_module_spatial_parity.py`
- `.venv/bin/python scripts/test_spatial_embedding_solver.py`
- `.venv/bin/python scripts/test_spatial_coordinate_grounding.py`
- `.venv/bin/python scripts/test_analyze_module_spatial_parity.py`
- `.venv/bin/python scripts/audit_module_publishability.py --module The_Hidden_City_of_Numillian --json`
