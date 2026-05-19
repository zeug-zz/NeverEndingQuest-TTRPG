# Design: Accurate-Ingest GUI State And Overwrite Safety

## Overview

This change stabilizes two cross-cutting concerns in the accurate-ingest GUI path:

```text
backend phase events -> normalized job status payload -> GUI visible progress
route overwrite confirmation -> packet build authorization -> module write boundary
```

The intent is to make state visible and destructive writes impossible without explicit confirmation.

## Decision 1: Canonical Accurate-Ingest Phase Labels

Backend job status should expose a normalized accurate-ingest phase in addition to existing status fields.

Canonical labels:

```text
preflight
extracting_source_truth
building_blueprint
awaiting_review
seeding_module
enriching_module
build_fidelity
readiness
finishing
publishability_audit
completed
not_publishable
failed
quarantined
rejected
```

Terminal states may remain existing job statuses. The canonical phase field should not remove existing `status`, `stage`, `pipeline_status`, or `progress_stage` fields.

## Decision 2: Compact Accurate-Ingest Status Summary

The job payload should include a compact accurate-ingest summary derived from existing artifacts and build result state.

Recommended shape:

```json
{
  "accurate_ingest": {
    "enabled": true,
    "phase": "seeding_module",
    "source_counts": {
      "locations": 13,
      "npcs": 23,
      "plot_beats": 12,
      "areas": 4
    },
    "blueprint_status": "ready",
    "seed_status": "success",
    "enrichment_status": "skipped|degraded|success|not_implemented",
    "build_fidelity_status": "pass|degraded|blocked|unknown",
    "readiness_status": "pass|fail|unknown",
    "publishability_status": "pass|fail|unknown",
    "source_fidelity_status": "pass|degraded|blocked|unknown"
  }
}
```

The exact field name can be `accurate_ingest` or a similarly stable nested key, but the data must be grouped so GUI and tests do not scrape unrelated raw fields.

## Decision 3: Overwrite Authorization At Shared Write Boundary

Overwrite safety should be enforced at the packet-build boundary because route, retry, and direct helper paths can all reach module materialization.

Any path that writes over an existing `modules/<slug>/` directory must provide one of:

1. A route-issued overwrite confirmation token tied to the current job/workspace/module slug.
2. A validated rebuild plan artifact produced by `prepare_backup_clean_rebuild(...)` or the existing clean-rebuild guard path.

If neither is present and the output module directory exists, packet build must fail closed before seeding or ModuleBuilder execution.

## Decision 4: Rebuild And Retry Semantics

Supported outcomes:

- First build: output directory absent, no overwrite token required.
- Existing module without confirmation: refuse before write.
- Confirmed clean rebuild: proceed only after backup-clean rebuild preparation.
- Retry-from-packet without confirmation: refuse if it would rewrite module files.
- Finishing-only retry: allowed because it reuses existing module artifacts and refreshes reports, not source packet materialization.

## Decision 5: Status Rendering Should Stay Additive

The frontend may render new phase/status fields if needed, but this slice should first prove backend payload continuity. Avoid broad template rewrites unless tests show the GUI cannot surface the data.

## Likely Touchpoints

- `web/routes/toolkit_homebrew_routes.py` for job payload summaries, route-level confirmation flow, and finishing/retry handling.
- `web/extensions/toolkit_homebrew_packet_builder.py` for shared overwrite authorization at the write boundary.
- `web/extensions/toolkit_homebrew_rebuild_guard.py` for existing backup-clean rebuild contracts.
- `web/templates/module_toolkit.html` only if source/status payload tests prove a missing rendering hook.
- `scripts/test_toolkit_homebrew_gui_unified_flow.py` for status payload and GUI flow contracts.
- `scripts/test_toolkit_module_build_publication_parity.py` or route-specific tests for overwrite/retry behavior.

## Migration And Rollback

This change is additive. Existing job status fields remain. If the new accurate-ingest summary causes an issue, callers can ignore it while existing status behavior remains intact.

Overwrite guards are fail-closed by design. If a legitimate rebuild path is blocked, fix the confirmation/rebuild-plan propagation rather than weakening helper-level checks.
