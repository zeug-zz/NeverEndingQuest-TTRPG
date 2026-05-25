# Change: Accurate-Ingest Generator Source Locks

## Why

The source-enhanced ModuleBuilder handoff is now archived and proves that accurate-ingest packet builds can route through the existing ModuleBuilder orchestration with source NPC, location, puzzle, tone, and source-lock metadata present before generation starts.

The next failure boundary is inside the generator layer. ModuleBuilder sub-generators can still behave like generic blank-concept generation unless source rosters, source locks, and encounter/monster references are propagated into their prompt context.

Numillian exposes the gap clearly: source extraction sees encounter seeds and monster-like references, but the blueprint/seed output has no monster stat files and empty encounter monster arrays. The next change MUST lock source contract propagation before attempting monster stat materialization.

## What Changes

- Add generator-level source-contract tests for ModuleBuilder, ModuleGenerator, AreaGenerator, LocationGenerator, and PlotGenerator prompt/context surfaces.
- Extend source-enhanced builder handoff with `source_monster_refs`, `source_encounter_seeds`, and a bounded source encounter plan when available.
- Ensure source-enhanced generator prompts include explicit source-lock guidance for required names, plot topology, puzzle rules, and forbidden replacement content.
- Preserve legacy/non-source ModuleBuilder and Describe-your-Adventure flows when no source blueprint is present.

## Impact

- Accurate-ingest moves from handoff proof to generator-context hardening.
- Numillian monster/encounter references become visible to the generator layer before later stat-file materialization work.
- Existing generator behavior remains compatible for ordinary concept builds.

## Non-Goals

- Do not generate or hydrate `monsters/*.json` in this change.
- Do not change benchmark thresholds, scanner logic, or fixture data.
- Do not run a production Numillian rebuild.
- Do not weaken build-fidelity, source-fidelity, validation, readiness, or publishability gates.
- Do not replace ModuleBuilder or rewrite generator architecture.

## MUST Constraints

- Source-enhanced generator context SHALL include required source rosters and source-lock guidance before LLM generation calls.
- Source monster and encounter references SHALL be propagated into builder/generator handoff artifacts when present in normalized packet or blueprint artifacts.
- Legacy concept builds SHALL remain functional without source blueprint artifacts.
- Tests SHALL be deterministic and provider-free.
- Generator source locks SHALL prevent unsupported replacement plotlines and major invented entities in prompt guidance.

## SHOULD Guidance

- Prefer additive prompt/context helpers over broad generator rewrites.
- Prefer source-contract tests before runtime generation behavior changes.
- Keep Numillian as the fixture for monster/encounter visibility, but avoid modifying production Numillian artifacts in this change.

## Rollback

If generator context changes destabilize concept builds, revert the source-context injection while preserving tests that define the required source-lock contract for the next focused fix.

## Dependencies

- `toolkit-accurate-ingest-builder-audit-briefing` is archived.
- `toolkit-accurate-ingest-modulebuilder-handoff` is archived.
- `plans/accurate-ingest-fix.md` identifies this as the next recovery slice.
