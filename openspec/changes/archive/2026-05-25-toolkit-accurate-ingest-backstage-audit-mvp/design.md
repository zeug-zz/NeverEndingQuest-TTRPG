# Design: Accurate-Ingest Backstage Audit MVP

## Architecture Boundary

This MVP is a read-only diagnosis layer for accurate-ingest reports. It is not the shared backstage harness and it is not an implementation of repair automation.

Hard ownership boundaries:

- The auditor owns evidence collection, report parsing, finding grouping, and recommendation formatting.
- Existing benchmark, validation, readiness, and publishability scripts remain the authoritative deterministic checks.
- ModuleBuilder and seed writer remain outside the auditor execution path.
- Accurate-ingest source-fidelity and publishability gates remain authoritative; the auditor cannot override their results.

## Key Decisions

### Decision 1: Narrow Script Before Shared Harness

The first implementation SHOULD use a small script/helper surface, such as `scripts/run_backstage_agent.py accurate-ingest-audit --module <slug>` backed by a narrow utility module. A shared `core/agents/backstage/` package SHOULD be deferred until this MVP proves the shape.

Rationale: The lowest-risk proof is deterministic report orchestration. A broad harness would add abstraction before contracts are validated.

### Decision 2: Read-Only Evidence Bundle

The auditor MUST collect evidence by reading existing files and, where needed, running existing commands in JSON mode without persisting refreshed reports into module directories.

Evidence items MUST include:

- path or command label
- existence/parse status
- content hash for files where practical
- compact status summary
- reason the evidence was used

Large source/report bodies SHOULD NOT be copied into the final audit artifact.

### Decision 3: Domain Findings

Findings MUST be grouped by domain:

- `source_fidelity`
- `build_fidelity`
- `validation`
- `readiness`
- `semantic_publishability`
- `report_consistency`
- `artifact_presence`

Report disagreement MUST be represented explicitly, for example source fidelity pass plus stale toolkit report failure.

### Decision 4: Runtime-Only Output

Audit run artifacts SHOULD be written under a runtime-only path such as:

```text
data/agent_runs/accurate_ingest_audit/<task_id>/
```

If that path is used, `.gitignore` MUST ignore generated run artifacts. Tests MAY use temp directories to avoid touching the real runtime path.

## Output Shape

The MVP SHOULD emit:

```text
run.json
evidence.json
audit_report.json
recommendation.json
```

`audit_report.json` SHOULD include:

- module slug and module path
- overall audit status: `pass`, `warning`, `blocked`, or `failed`
- evidence references
- grouped findings
- report consistency summary
- deterministic command summaries when commands are run
- next-step recommendation

## Safety And Failure Semantics

- Missing optional reports SHOULD produce warnings, not crashes.
- Missing module directory MUST fail with a clear error.
- Corrupt JSON report files MUST produce parse findings and continue where possible.
- Command failures MUST be captured as evidence and findings, not silently ignored.
- The auditor MUST never downgrade deterministic failures to pass.

## Migration Sequence

1. Add tests and minimal artifact parser/report builder.
2. Add CLI/script entrypoint and runtime-output support.
3. Add read-only command parity for benchmark/publishability JSON checks.
4. Add mutation-safety tests that hash module files before and after auditor execution.
5. Validate OpenSpec and targeted tests.

## Rollback Strategy

Because the MVP is additive/read-only, rollback is deletion of the new script/helper/tests. Generated runtime run artifacts are ignored and do not require repository rollback.

## Compatibility

- Existing module validation, benchmark, and publishability scripts MUST continue to work unchanged.
- Existing accurate-ingest reports MUST remain in their current formats.
- Legacy modules without accurate-ingest artifacts SHOULD produce `unknown` or warning findings rather than hard failures unless the requested module path is missing.
