## Why

The read-only backstage audit MVP now produces compact deterministic evidence, findings, and recommendations, but an LLM Builder still needs a safe bridge from those artifacts into a bounded implementation prompt. Without a briefing layer, builders may reread too much context, miss evidence references, or treat audit recommendations as permission to mutate module artifacts.

This change adds a deterministic builder briefing step that converts an existing audit run directory into small, evidence-backed prompt context while preserving the audit's read-only authority boundaries.

## What Changes

- Add a narrow builder-briefing utility that reads an existing backstage audit run directory.
- Validate the four required audit artifacts before producing briefing output.
- Emit compact `builder_brief.json` and `builder_prompt_context.md` artifacts into the same runtime audit run directory.
- Preserve recommendation action, reason, evidence references, report-consistency summary, and grouped finding counts.
- Classify the next builder lane without mutating module artifacts or refreshing reports.
- No LLM/provider calls are introduced.

## Capabilities

### New Capabilities

- `accurate-ingest-builder-audit-brief-inputs`: Validates and loads existing backstage audit run artifacts.
- `accurate-ingest-builder-audit-brief-output`: Defines compact JSON and Markdown briefing outputs for builder consumption.
- `accurate-ingest-builder-audit-brief-safety`: Ensures briefing writes are isolated to runtime audit directories and remain read-only for modules.
- `accurate-ingest-builder-audit-next-step-routing`: Maps audit recommendations/findings into deterministic builder lanes.

### Modified Capabilities

- None.

## Impact

- Affected code: new briefing utility/script and focused tests.
- Affected artifacts: runtime-only `builder_brief.json` and `builder_prompt_context.md` under an existing audit run directory.
- No module JSON, benchmark fixtures, publishability scripts, ModuleBuilder, seed writer, or GUI flows are changed.
- Merge safety impact is low because this is additive tooling outside live runtime and existing build paths.
