## Overview

This change moves accurate-ingest fidelity diagnostics to the correct side of the pipeline boundary. Pre-build diagnostics should guide blueprint generation and report warnings, but they should not block artifact creation by default. The final artifact gates remain strict and are the authoritative place to decide whether a built module is playable or publishable.

## Contract Layer (MUST)

- Accurate-ingest jobs MUST attempt deterministic blueprint generation when source normalization, packet artifacts, and source text are readable.
- Pre-build fidelity diagnostics MUST NOT alone force `awaiting_review` or `blocked_by_fidelity` before `builder_blueprint.json` can be produced.
- If the job cannot produce a bounded blueprint because required source/packet artifacts are missing or malformed, it MUST fail with explicit `missing_artifacts` or malformed-artifact diagnostics.
- Jobs that explicitly enter required review MUST preserve existing strict approval behavior, including stale signature and non-approvable review rejection.
- The GUI MUST NOT render `rejected`, `blocked`, `failed`, `quarantined`, or missing-module states as successful completion.
- The GUI MUST NOT append MMG guidance unless a module folder exists and the build has reached an MMG-eligible artifact state.
- Downstream schema validation, source-fidelity benchmark, build fidelity, publishability, playable-publication, and report-agreement gates MUST remain authoritative and fail-closed.

## Guidance Layer (SHOULD)

- Treat source-fidelity findings before ModuleBuilder as diagnostics with severity metadata and recommended next actions.
- Keep a small explicit allowlist of conditions that genuinely require pre-build review, such as current user-submitted rejection, stale required review signatures, unreadable source, or structurally impossible packet state.
- Prefer deterministic source-atom classification improvements before adding new LLM repair steps.
- Add source-contract tests that prevent regressions in the Elden Ring-like source pattern: markdown headings as locations, escaped numbered subheadings as rooms, appendices as sections, and prose fragments not promoted to entities.
- Keep implementation minimal and localized to accurate-ingest toolkit code.

## Current Failure Mode

An accurate-ingest job can reach `awaiting_review` with `blocked_by_fidelity` before `builder_blueprint.json` is written. The GUI then allows rejection, renders the rejected job as successful, and suggests opening MMG despite no module directory existing. This is both a pipeline deadlock and a status UX bug.

## Proposed Flow

1. Normalize/upload source and produce packet artifacts.
2. Extract source atoms and classify them deterministically.
3. Build fidelity diagnostics as warning/blocker metadata.
4. Generate a bounded builder blueprint whenever source/packet inputs are readable.
5. Run ModuleBuilder/seed/support materialization.
6. Run validation, source-fidelity benchmark, build fidelity, publishability, playable-publication, and report-agreement gates.
7. Render final status according to actual artifact state.

## Required Review Boundary

Required review remains valid only when the backend has a current explicit review state that must be decided before continuing. Clean or degraded diagnostics alone are not sufficient to pause artifact generation. If a job is manually rejected, it is terminally rejected and must not receive success/MMG guidance.

## Source Classification Notes

The classifier should reduce false blockers by separating:

- location headings such as `### Bridge of Sacrifice`
- escaped numbered room headings such as `#### 1\\. Chapel`
- appendix/section headings such as `Appendix A`
- prose fragments such as `gathered around a`
- NPC-like names such as `Nomadic Merchant`
- creature/monster-like names such as `Guard Dog`, `Lesser Black Knife Assassin`, or `Lion Guardian`

These classifications do not need perfect semantic interpretation; they need stable enough routing so source-fidelity diagnostics do not block blueprint creation unnecessarily.

## Risks

- Risk: Allowing degraded diagnostics to continue could produce low-quality artifacts.
- Mitigation: Final validation, source-fidelity, report-agreement, and playable-publication gates remain fail-closed.
- Risk: GUI status could still overstate success.
- Mitigation: Add explicit no-module/rejected/blocked status tests and gate MMG guidance on module existence.
- Risk: Classification fixes overfit one source.
- Mitigation: Use generic markdown/source patterns rather than Elden Ring-specific labels.

## Rollback

If continuation causes regressions, revert the accurate-ingest pre-build continuation logic while keeping GUI status fixes. The final gates do not need rollback because they remain unchanged.
