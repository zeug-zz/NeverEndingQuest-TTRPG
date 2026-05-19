# Proposal: Accurate-Ingest GUI Builder Unification

## Problem

The accurate-ingest roadmap started because Module Builder uploads were producing impoverished modules with little relevance to the ingested adventure source. The root cause was that a full markdown/PDF adventure was compressed into a thin normalized packet and short `builder_narrative`, then `ModuleBuilder` re-expanded that summary as if it were a new concept prompt. This caused source NPCs, keyed locations, puzzles, plot topology, and tone to be dropped or replaced.

The source-truth infrastructure now exists: source manifest/graph extraction, multi-pass normalization, fidelity audit and repair, builder blueprint artifacts, fidelity review, build-time gates, deterministic content-block parsing, final benchmark/publication gate integration, and Homebrewery `MODULE_SUMMARY.md` generation at the end of toolkit finishing.

The remaining gap is integration. The blueprint is still mostly serialized into a prompt and handed to `ModuleBuilder.build_module(...)`. The deterministic importer can preserve map-key structure but is too skeletal for polished user modules and can bypass richer builder/finisher behavior. `MODULE_SUMMARY.md` accurately presents the final module, but it cannot repair a module that already lost source truth.

## Proposed Solution

Create a unified GUI ingest path where accurate-ingest produces a deterministic builder blueprint, materializes a module skeleton from that blueprint, applies bounded LLM enrichment only to approved text fields, runs existing fidelity/readiness/publishability gates, and generates `MODULE_SUMMARY.md` as the final presentation artifact.

The target flow is:

```text
Upload MD/PDF
  -> preflight and rights declaration
  -> deterministic structure/content-block extraction
  -> multi-pass source graph/identity/topology synthesis where needed
  -> builder_blueprint.v2
  -> fidelity/blueprint review panel
  -> deterministic module seed writer
  -> bounded LLM enrichment over approved fields
  -> build fidelity gate
  -> readiness/semantic/media/materialization finisher
  -> MODULE_SUMMARY.md generation
  -> source-fidelity publication gate
```

Core principle:

> The builder may format, deepen, and fill gaps inside source bounds. It must not rediscover or replace the adventure.

## Scope

This change will plan and implement:

1. A `builder_blueprint.v2` contract that can drive module materialization without a freeform concept prompt.
2. A deterministic seed writer that creates schema-valid skeletal module files from the blueprint without provider calls.
3. A bounded enrichment pipeline that applies validated patch operations to allowed text fields only.
4. GUI route/job-state orchestration for the unified accurate-ingest build path.
5. Shared finisher routing so successful accurate-ingest GUI builds always produce `toolkit_build_report.json` and `MODULE_SUMMARY.md`.
6. Final source-fidelity benchmark/publication behavior after the unified build completes.

## Non-Goals

- This change does not remove legacy Describe-your-Adventure concept builds.
- This change does not remove the current deterministic importer CLI path.
- This change does not make `MODULE_SUMMARY.md` authoritative source truth.
- This change does not allow LLM enrichment to rename locations, NPCs, puzzle rules, or plot topology.
- This change does not weaken existing readiness, semantic publishability, or source-fidelity gates.
- This change does not auto-publish modules.

## Success Criteria

1. GUI accurate-ingest jobs build from `builder_blueprint.v2`, not from summary-only prose.
2. Deterministic seeding preserves required source locations, NPCs, plot beats, puzzles, clues, and locks before LLM enrichment starts.
3. LLM enrichment can improve descriptions and narrative fields only through validated patch operations tied to blueprint IDs.
4. Every successful accurate-ingest GUI build enters the existing toolkit finisher and generates `MODULE_SUMMARY.md`.
5. Build/source-fidelity reports remain authoritative over the summary document.
6. Numillian end-to-end testing proves that source locations and core puzzle/lore objectives survive the full GUI-equivalent path.

## Architecture Impact

- Additive helper modules for blueprint v2 generation, seed writing, enrichment patches, and GUI orchestration.
- Additive feature flags for blueprint-native GUI build and enrichment rollout.
- Legacy Module Builder flow remains available for concept-first builds.
- Existing accurate-ingest artifact chain remains the source of truth.
- Existing toolkit finisher remains the final publication/reporting path.
