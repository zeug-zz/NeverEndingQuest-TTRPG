# Why

`spatial-constraint-solver-generalization` fixed the Numillian bread-loaf case narrowly, but its tier contract is not generally correct. Tier 1 is the only coordinate-only path that can honestly prove every authored edge has Manhattan distance exactly 1. Tier 2 scatter/relax can fail to create cardinal adjacencies at all, and Tier 3 linear layout cannot satisfy arbitrary cross-edges, cycles, or high-degree graphs.

The current plan therefore risks false-positive publication readiness: a module can be reported as spatially repaired because a fallback tier emitted coordinates, even though the output still violates the strict spatial contract.

# What Changes

- Strengthen Tier 1 as the authoritative coordinate-only solver path.
- Require every tier that reports success to pass the same full adjacency validator.
- Demote Tier 2 and Tier 3 from guaranteed success fallbacks to diagnostic or best-effort helpers unless they independently validate.
- Add explicit structured failure diagnostics for non-embedded edges, search limits, and false fallback outputs.
- Preserve existing valid module coordinates unless `force_relayout=True` or an explicit remediation path is requested.

# Capability Scope

- `scripts/remediate_module_coordinates.py` solver orchestration and result classification.
- Spatial embedding regression coverage in `scripts/test_spatial_embedding_solver.py` and related spatial validation tests.
- OpenSpec contract correction for `spatial-grid-embedding-solver`.

# Non-Goals

- Adding connector rooms or mutating authored topology. That is handled by the dependent `spatial-topology-normalization-failsafe` change.
- Introducing LLM-based coordinate solving.
- Weakening the strict Manhattan adjacency validator.
- Allowing overlapping coordinates or hidden validator exceptions.

# Impact

- Prevents false green builds from Tier 2/Tier 3 fallback outputs.
- Makes failure modes actionable by identifying exact unsatisfied edges.
- Provides a reliable base for the deterministic topology-normalization failsafe.

# Risks

- Modules that previously appeared repaired by Tier 2/Tier 3 may now correctly fail with spatial diagnostics.
- Raising Tier 1 limits can increase runtime if not guarded by deterministic budgets.

# Fallback

- Keep existing Tier 2/Tier 3 code behind diagnostic names while requiring full validation before success.
- If runtime becomes a concern, preserve the current Tier 1 room cap and emit explicit `tier1_search_limit` diagnostics rather than claiming fallback success.

# Merge Safety and SP/MP Impact

- This is toolkit/module-builder remediation logic, not gameplay runtime behavior.
- Single-player and tabletop runtime flows are unaffected except that broken modules should no longer publish with false spatial success.
