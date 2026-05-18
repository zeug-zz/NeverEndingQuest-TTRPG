# Proposal: Final Benchmark and Publication Gate Integration

## Problem

Accurate-ingest pipeline components now exist end-to-end:
- Source graph extraction (Phase 1)
- Multi-pass normalization and fidelity repair (Phases 2-3)
- Blueprint handoff and source-locked builder (Phase 4 + hardening)
- Review UI and fidelity panel (Phase 6)
- Build-time fidelity gates (Phase 8)
- Narrative enrichment placeholder (Phase 9)
- Deterministic content-block import for structured sources (Phase 10)

However, there is no final end-to-end benchmark contract that proves source fidelity against a real published adventure, and no publication gate integration that consistently surfaces degraded fidelity in the toolkit publication workflow. Operators cannot currently answer "is this module source-faithful enough to publish?" with a single deterministic report, nor can the system enforce publication warnings or blockers based on benchmark-measured fidelity.

## Proposed Solution

Add a final benchmark + publication gate integration slice that:

1. Defines a benchmark fixture contract using The Hidden City of Numillian as the canonical benchmark module, with explicit per-field source-fidelity expectations derived from direct source comparison.
2. Creates a deterministic benchmark runner that compares ingested module artifacts against source graph expectations without requiring LLM calls.
3. Integrates source-fidelity benchmark results into the existing toolkit publication gate, surfacing fidelity status alongside existing readiness and publishability checks.
4. Adds publication warnings for degraded source-fidelity modules and publication blockers for blocked fidelity modules, while preserving the existing structural readiness and semantic publishability gates as authoritative foundations.
5. Surfaces fidelity status in toolkit build reports, publishability audits, and sidebar readiness displays.

All benchmark measurement is deterministic (no LLM calls). All publication enforcement is additive to existing gates.

## Non-Goals

- This slice does not run Numillian ingestion or mutate module artifacts.
- This slice does not change existing structural readiness or semantic publishability check behavior.
- This slice does not auto-publish or auto-block modules without explicit operator awareness.
- This slice does not weaken any existing source-fidelity scoring thresholds.
- This slice does not implement runtime UI changes in the planning scaffold step.
- This slice does not alter ModuleBuilder, ModuleGenerator, or provider-dependent builder paths.
- This slice does not create benchmark result JSON files or modify actual module data.

## Success Criteria

1. An operator can run the Numillian benchmark and receive a deterministic pass/degraded/blocked verdict per expectation category.
2. Publication gate composition includes source-fidelity status as a distinct category alongside readiness and semantic publishability.
3. Degraded fidelity modules surface publication warnings; blocked fidelity modules trigger publication blockers.
4. Legacy modules without accurate-ingest artifacts fail open (do not block) rather than fail closed.
5. Existing `ready_status` and `publishable_status` remain semantically unchanged for modules that pass all existing gates.
6. All new behavior is behind `ENABLE_ACCURATE_INGEST_FINAL_BENCHMARK` (default True) and falls back cleanly when accurate-ingest artifacts are absent.

## Architecture Impact

- **Additive**: New benchmark runner script, new publication gate helper, new report fields.
- **No breaking changes**: Existing publication paths remain authoritative; fidelity status is layered on top.
- **Module-local**: Benchmark and gate helpers operate on module-local artifacts, never runtime campaign state.
- **Feature-flagged**: Rollout controlled by model_config flag with safe fallback.
