## Overview

Phase 11 closes the accurate-ingest roadmap by making source fidelity measurable (benchmark) and enforceable (publication gate). The design adds two new capabilities: a deterministic benchmark runner that compares ingested module artifacts against source graph expectations, and a publication gate composition helper that integrates benchmark results into the existing publishability check chain.

All measurement is deterministic. All enforcement is additive. No existing gate is weakened.

## Current State

The accurate-ingest pipeline now produces these artifacts per module:

| Artifact | Source | Phase |
|---|---|---|
| `source_manifest.json` | `utils/toolkit_source_manifest.py` | Phase 1 |
| `source_graph.json` | `utils/toolkit_source_graph_synthesis.py` | Phases 2-3 |
| `source_fidelity_report.json` | `utils/toolkit_fidelity_verifier.py` | Phase 3 |
| `build_fidelity_report.json` | `utils/toolkit_build_fidelity.py` | Phase 8 |
| `builder_blueprint.json` | `utils/toolkit_builder_blueprint.py` | Phase 4 |
| `narrative_enrichment_plan.json` | `utils/toolkit_narrative_enrichment_plan.py` | Phase 9 |

The toolkit publication path already composes `ready_status` (structural) and `publishable_status` (semantic) through `scripts/audit_module_publishability.py`. Phase 11 adds source-fidelity status as a third dimension without replacing the first two.

Publication gate composition already exists. Phase 11 extensions are additive and flagged.

## Decisions

### Decision 1: Benchmark Fixture Contract Model

The benchmark fixture SHALL be a JSON contract file per module that defines expectations, not a hardcoded test script. This allows future benchmark modules without code changes.

**Benchmark fixture schema:**

```json
{
  "benchmark_version": "numillian_benchmark.v1",
  "module_slug": "The_Hidden_City_of_Numillian",
  "source_path": "path/to/numillian_source.md",
  "expectations": {
    "npc_preservation": {
      "total_source_npcs": 20,
      "minimum_represented": 20,
      "allow_minor_unused": true
    },
    "location_preservation": {
      "total_source_locations": 13,
      "minimum_preserved": 13,
      "allowed_mappings": {}
    },
    "puzzle_preservation": {
      "required_puzzles": [
        "skull_riddle",
        "flooding_room",
        "kill_the_dog_mindscape"
      ]
    },
    "lore_preservation": {
      "required_elements": [
        "gatepact",
        "kobe_protection"
      ]
    },
    "tone_preservation": {
      "expected_tone": "quirky_character_driven_hidden_city",
      "blocked_replacement": "generic_conspiracy_thriller"
    }
  },
  "publication_thresholds": {
    "pass": {
      "npc_preservation": 1.0,
      "location_preservation": 1.0,
      "puzzle_preservation": 1.0,
      "lore_preservation": 1.0,
      "tone_preservation": "pass"
    },
    "degraded": {
      "npc_preservation": 0.85,
      "location_preservation": 0.85,
      "puzzle_preservation": 0.67,
      "lore_preservation": 0.5,
      "tone_preservation": "degraded"
    }
  }
}
```

### Decision 2: Benchmark Runner Architecture

The benchmark runner SHALL be a standalone Python script `scripts/benchmark_accurate_ingest.py` with module-local execution. It MUST NOT call LLM providers.

**Runner flow:**

1. Load benchmark fixture from `data/benchmarks/<module_slug>_benchmark.json`.
2. Load source graph from module artifact workspace or module directory.
3. For each expectation category, compare source graph evidence against fixture thresholds.
4. Compute per-category scores and aggregate status.
5. Write `accurate_ingest_benchmark_report.json` to the module workspace.
6. Return structured result with pass/degraded/blocked per category.

**Category measurement rules:**

| Category | How Measured | Deterministic |
|---|---|---|
| NPC preservation | Count source NPCs present in module context/areas. Allow minor/unused classification via review note. | Yes |
| Location preservation | Match source location names/aliases against module area/location names. Allow approved explicit mappings. | Yes |
| Puzzle preservation | Keyword/feature match against module puzzles and area descriptions. | Yes |
| Lore preservation | Keyword/concept match in module objective, plot, and context. | Yes |
| Tone preservation | Compare tone descriptor against module context metadata. Operator-reviews classification; automated check is warning-only. | Yes (detection); advisory (classification) |

### Decision 3: Publication Gate Composition

The publication gate SHALL compose three independent dimensions:

```
ready_status    (from scripts/audit_module_readiness.py)
publishable_status (from scripts/audit_module_publishability.py)
source_fidelity_status (NEW from benchmark runner)
```

**Composition rules:**

| ready_status | publishable_status | source_fidelity_status | Final Publishable |
|---|---|---|---|
| pass | pass | pass | pass |
| pass | pass | degraded | degraded (warning) |
| pass | pass | blocked | blocked |
| pass | degraded | pass | degraded |
| pass | degraded | blocked | blocked |
| any | blocked | any | blocked |
| degraded | any | any | degraded |
| unknown | any | any | unknown |

The most severe status across all three dimensions wins. Existing `ready_status` and `publishable_status` remain authoritative sources. Source-fidelity status is additive only.

### Decision 4: Degraded-With-Waiver Behavior

When source-fidelity is `degraded` but structural readiness and semantic publishability are `pass`, the system SHALL:
1. Surface a publication warning (not a blocker).
2. Require an explicit operator review decision (waive or fix).
3. Allow publication with waiver, logged in publication metadata.
4. Never auto-block a module on degraded source-fidelity alone.

Blocked source-fidelity (scores below degraded thresholds) SHALL block publication regardless of other gates.

### Decision 5: Legacy Module Handling

Modules without accurate-ingest artifacts (pre-Phase-1 ingested modules, Describe-your-Adventure builds) SHALL NOT be affected. The benchmark runner SHALL return `source_fidelity_status: "unknown"` when source graph artifacts are absent. The publication gate SHALL treat `unknown` as non-blocking (fail open).

### Decision 6: Feature Flag

Add `ENABLE_ACCURATE_INGEST_FINAL_BENCHMARK = True` to `model_config.py`. When disabled, all source-fidelity checks degrade to `unknown` without blocking. When enabled, benchmark runner and publication gate composition are active.

## Implementation Notes

Recommended files:

- `scripts/benchmark_accurate_ingest.py` - Benchmark runner (new)
- `utils/toolkit_source_fidelity_benchmark.py` - Benchmark contract and scoring helpers (new)
- `utils/toolkit_publication_gate_composer.py` - Gate composition helper (new)
- `data/benchmarks/The_Hidden_City_of_Numillian_benchmark.json` - Numillian benchmark fixture (new)
- `scripts/audit_module_publishability.py` - Add source-fidelity dimension (modify, additive)
- `web/extensions/toolkit_module_finisher.py` - Surface source-fidelity status (modify, additive)
- `model_config.py` - Add ENABLE_ACCURATE_INGEST_FINAL_BENCHMARK flag (modify, additive)

Existing files that MUST remain compatible:

- `scripts/audit_module_readiness.py`
- `scripts/module_semantic_authority_audit.py`
- `scripts/module_semantic_probe_harness.py`
- `scripts/audit_module_publishability.py` (existing paths)
- `web/extensions/toolkit_homebrew_readiness_gate.py`

## Test Strategy

Add or extend tests for:

- Benchmark fixture loading and validation.
- Per-category deterministic scoring (NPC count, location name match, puzzle keyword match, lore concept match).
- Aggregate status computation (pass/degraded/blocked) from per-category scores.
- Publication gate composition with all status combinations.
- Degraded-with-waiver behavior: warning surfaced, waiver accepted, publication allowed.
- Blocked source-fidelity behavior: publication blocked regardless of other gates.
- Legacy modules without accurate-ingest artifacts returning `unknown`.
- Feature flag disabled: source-fidelity degrades to `unknown`.
- Existing publishability audit tests remain passing without regression.

## Risks

| Risk | Mitigation |
|---|---|
| Benchmark thresholds too strict for real modules | Degraded threshold allows 85% coverage; waiver path available |
| Tone classification subjective | Warning-only; operator-reviewed; automated check is advisory |
| Legacy modules blocked by new gate | `unknown` status fails open; feature flag provides kill switch |
| Publication gate composition becomes confusing with three dimensions | Deterministic composition rules; worst-status-wins principle |
| Numillian benchmark fixture data drifts from source | Fixture is versioned JSON; comparison is against source graph, not hardcoded values |
