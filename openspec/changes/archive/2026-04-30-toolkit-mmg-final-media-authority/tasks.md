# Tasks

## 1. OpenSpec Artifacts

- [x] 1.1 Create proposal, design, tasks, executor prompts, and capability spec.
- [x] 1.2 Validate the change with OpenSpec.

## 2. MMG Final Media Report

- [x] 2.1 Add a helper for building and writing `module_media_generator_report.json`.
- [x] 2.2 Define and enforce the `module_media_generator_report.v1` contract fields.
- [x] 2.3 Audit module-local media presence for required MMG assets without counting static fallback media.
- [x] 2.4 Record residual missing media and optional per-run generation failures.

## 3. MMG Completion Hook

- [x] 3.1 Call the report writer after unified asset generation completes.
- [x] 3.2 Keep existing toolkit build-report refresh behavior as a separate fail-open step.
- [x] 3.3 Optionally include residual media-report summary in the socket completion payload.

## 4. Sidebar Authority Override

- [x] 4.1 Load MMG final media reports in `ModuleStitcher` fail-open.
- [x] 4.2 Suppress stale media-only build-report handoff when an authoritative MMG pass report has no missing media.
- [x] 4.3 Surface MMG handoff when an authoritative MMG fail/degraded report has missing module-local media.
- [x] 4.4 Preserve non-media build, readiness, and publishability failures.

## 5. Regression Coverage

- [x] 5.1 Add sidebar tests for MMG pass suppressing stale/current media-only debt.
- [x] 5.2 Add sidebar tests for MMG fail surfacing handoff with stale or absent build reports.
- [x] 5.3 Add fallback tests for missing, malformed, non-authoritative, or unknown-contract MMG reports.
- [x] 5.4 Add semantic/build failure preservation tests.
- [x] 5.5 Add helper or source-contract tests proving static fallback media is not counted as module completion.

## 6. Verification

- [x] 6.1 Compile modified Python files.
- [x] 6.2 Run targeted sidebar/MMG regression tests.
- [x] 6.3 Run OpenSpec validation.

## Guidance

- Keep the implementation narrow and contract-driven.
- Do not let MMG media status hide non-media failures.
- Do not count static fallback assets as module-local media completion.
- Prefer additive files and fail-open behavior for malformed reports.
