# Change: Accurate-Ingest ModuleBuilder Handoff

## Why

The Numillian source-fidelity proof now passes through the support rebuild path, but the broader recovery architecture still requires proof that accurate-ingest GUI builds use the existing ModuleBuilder orchestration as the default creative authoring path.

The deterministic seed writer is valuable as support tooling, preview, fallback, fixture generation, and source-vs-output comparison. It MUST NOT silently replace ModuleBuilder for human-authored adventure ingest. The next architectural step is to lock the default GUI path to source-enhanced ModuleBuilder handoff and prove that the handoff artifact carries source truth before generation starts.

## What Changes

- Add a source-contract handoff requirement for accurate-ingest packet builds.
- Require default accurate-ingest GUI builds to route through `_execute_module_builder(...)` when no explicit seed writer mode is requested.
- Require the builder handoff artifact to include source identity, build mode, required source rosters, puzzle/challenge identifiers, tone requirements, and forbidden-invention guidance.
- Preserve seed writer routes only as explicit `fallback`, `preview`, or `support` modes.
- Add deterministic source-contract tests that prove required Numillian source names enter `builder_input`/`builder_narrative` before ModuleBuilder runs.

## Impact

- Accurate-ingest GUI architecture moves back toward the recovery plan's intended ModuleBuilder-first path.
- Seed writer functionality remains available for support and fallback use.
- Existing Describe-your-Adventure and non-source concept-builder flows remain compatible.
- No production Numillian module artifacts are modified by the scaffold step.

## Non-Goals

- Do not implement generator-level prompt hardening in this change.
- Do not run a production Numillian rebuild in scaffold or source-contract steps.
- Do not change benchmark thresholds, scanner logic, or benchmark fixture data.
- Do not commit or publish dirty Numillian module artifacts.
- Do not delete the seed writer.
- Do not require live provider calls for verification.

## MUST Constraints

- Default accurate-ingest GUI builds SHALL use existing ModuleBuilder orchestration when no explicit seed writer mode is supplied.
- Seed writer execution SHALL require explicit seed writer mode or explicit fallback authorization.
- The builder handoff artifact SHALL preserve source identity and required source contract fields before ModuleBuilder runs.
- Handoff source-contract tests SHALL be deterministic and provider-free.
- Existing legacy/concept builder paths SHALL remain functional when no source-blueprint artifacts are present.

## SHOULD Guidance

- Prefer enhancing existing packet builder handoff artifacts over adding a parallel builder executor.
- Prefer source-contract tests around `builder_input.json` and `builder_narrative.md` before changing sub-generator prompts.
- Keep ModuleBuilder as the creative generation boundary in this change.

## Rollback

Each handoff change SHOULD be independently revertible. If source-enhanced handoff causes GUI build regressions, revert the handoff serialization/routing change while keeping tests that describe the required source-contract behavior.

## Dependencies

- `toolkit-accurate-ingest-numillian-npc-location-preservation` is archived and restored Numillian source fidelity to pass.
- `toolkit-accurate-ingest-llm-blueprint-enrichment` is archived background work.
- `plans/accurate-ingest-fix.md` remains the broader recovery plan.
