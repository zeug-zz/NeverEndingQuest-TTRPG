## Context

`toolkit-accurate-ingest-backstage-audit-mvp` introduced a read-only audit run containing `run.json`, `evidence.json`, `audit_report.json`, and `recommendation.json`. These artifacts are useful for humans and builders, but they are still report-shaped rather than prompt-shaped.

The next step is not to make the auditor autonomous. The safe pattern is: audit artifacts -> deterministic builder brief -> OpenSpec or patch prompt -> human/Plan verification -> one narrow builder task.

## Goals / Non-Goals

**Goals:**

- Read one existing backstage audit run directory.
- Validate required artifact presence and task identity consistency.
- Produce compact builder-facing JSON and Markdown outputs.
- Preserve evidence references and deterministic gate authority.
- Keep outputs runtime-only and outside module directories.

**Non-Goals:**

- No LLM/provider calls.
- No ModuleBuilder, seed writer, benchmark, publishability, readiness, or finisher execution.
- No module artifact mutation.
- No waiver creation or gate override.
- No GUI integration or shared backstage harness extraction in this slice.

## Decisions

### Decision 1: Runtime-Only Briefing Utility

Create a narrow script/utility rather than a shared `core/agents/backstage/` harness.

Rationale: The audit MVP is still new. A small bridge proves the shape before introducing a framework-like abstraction.

Alternative considered: build a generalized backstage harness now. Rejected because it would widen scope and risk hiding the concrete accurate-ingest contract.

### Decision 2: Existing Audit Run Is The Only Input

The brief generator reads `run.json`, `evidence.json`, `audit_report.json`, and `recommendation.json` from an existing run directory.

Rationale: This preserves the audit as the evidence source and avoids report refresh side effects.

Alternative considered: re-run the audit internally. Rejected because it can mask stale-run behavior and violates the separation between audit and briefing.

### Decision 3: Two Output Artifacts

Emit `builder_brief.json` for tests/tools and `builder_prompt_context.md` for human/LLM builder prompt composition.

Rationale: JSON is deterministic and easy to assert; Markdown is easy to paste into builder prompts.

Alternative considered: emit only Markdown. Rejected because schema assertions would be weaker.

### Decision 4: Deterministic Lane Classification

Map audit recommendation/finding state into one of: `diagnose_reports`, `repair_artifacts`, `openspec_work`, `review_warnings`, `no_action`.

Rationale: Builders need a lane, not permission to apply arbitrary changes.

## Risks / Trade-offs

- Risk: Brief becomes another authority layer -> Mitigation: preserve source audit recommendation and explicitly state that deterministic gates remain authoritative.
- Risk: Markdown context grows too large -> Mitigation: include counts, top findings, evidence keys, and paths only; never embed full report bodies.
- Risk: Builders mutate modules based on a brief -> Mitigation: safety spec and output wording must state approval/verification boundaries.
- Risk: Briefing duplicates audit fields -> Mitigation: keep it a projection, not a replacement; `task_id` links it to the audit run.

## Migration Plan

1. Add utility/script and temp-fixture tests.
2. Verify existing backstage audit tests still pass.
3. Keep briefing opt-in via explicit script call.
4. Rollback by deleting the new utility/script and tests; audit MVP remains unaffected.
