# Design: Blueprint Enrichment Real Status

## Overview

This change is a status-contract hardening slice for blueprint enrichment. It does not implement provider-backed enrichment. It makes the existing enrichment scaffold honest, testable, and safe for later real passes.

The design goal is simple:

```text
no real enrichment -> never report complete
real validated patches -> complete or degraded depending on rejected/error state
provider/pass problems -> degraded or failed with explicit reason
structural mutation attempts -> rejected and reported
```

## Status Contract

The enrichment layer should use bounded status values:

| Status | Meaning |
|---|---|
| `skipped` | Enrichment is disabled or intentionally bypassed. |
| `not_implemented` | Enrichment was enabled, but provider orchestration is unavailable/no-op. |
| `degraded` | The pipeline ran but pass exceptions, validation errors, rejected patches, or provider issues prevented a clean enrichment result. |
| `failed` | A fatal required operation failed and no safe enrichment result can be trusted. |
| `complete` | At least one real validated patch was applied and no errors/rejections occurred. |

## Pipeline Semantics

`run_enrichment_pipeline(...)` should preserve current fail-open behavior for build artifacts:

- Disabled flag returns `skipped` with reason `feature_flag_disabled`.
- Enabled placeholder/no-provider state returns `not_implemented`, not `complete`.
- Pass exceptions return `degraded` or `failed` with pass-level diagnostics.
- Pass results containing errors return `degraded`.
- Any rejected patch returns `degraded` unless policy later defines a non-blocking warning class.
- `complete` requires at least one applied patch and zero rejected patches/errors.

## Patch Validation

Patch validation remains Python-authoritative. It may accept only prose/text enrichment fields and must reject structural mutation attempts, including names, IDs, coordinates, connectivity, dependencies, puzzle rules, puzzle solutions, and failure consequences.

The patch validator should remain deterministic and provider-independent. Later LLM output must be routed through this validator before any patch is applied.

## Report Shape

`build_enrichment_report(...)` should expose stable diagnostics:

- `enrichment_report_version`
- `created_at`
- `status`
- `reason`
- `applied_count`
- `rejected_count`
- `error_count`
- `warning_count`
- `pass_count`
- `applied`
- `rejected`
- `errors`
- `warnings`
- pass-level metadata when available

Existing consumers should keep working if extra keys are added.

## Compatibility

- Feature flag defaults remain off.
- Existing tests may patch the feature flag on to exercise behavior.
- No GUI state machine or ModuleBuilder routing changes are required here.
- No provider credentials are required for verification.

## Risks

- Existing code may already implement part of this contract. Builder should avoid unnecessary churn and focus on source-contract tests and any missing edge-case behavior.
- If `failed` is not yet needed by callers, it can be introduced as a constant without routing fatal states to it until a testable fatal case exists.
