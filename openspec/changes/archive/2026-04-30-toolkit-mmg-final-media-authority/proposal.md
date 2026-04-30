# Why

The Module Builder sidebar can continue to show `Publication blocked: missing media` and `Needs Module Media Generator` after Module Media Generator completes. The sidebar currently derives media handoff status from persisted `toolkit_build_report.json` media-debt fields, so stale or degraded publishability reports can keep an MMG handoff sticky even when module-local media has already been generated.

# What Changes

- Add a durable Module Media Generator final media report for each module after unified asset generation completes.
- Treat that MMG report as the final authority for the sidebar's media-generator-needed state.
- Preserve `toolkit_build_report.json` as the authority for non-media readiness and publishability failures.
- Ensure static fallback media remains informational only and does not count as module-complete media.
- Add regression coverage for stale build reports, MMG pass/fail outcomes, malformed reports, and semantic failure preservation.

# Capability Scope

- Module Media Generator completion and post-run media audit.
- Module Builder sidebar media handoff signals.
- Persisted module-level media-generator report contract.
- Focused tests for report authority and stale report override behavior.

# Non-Goals

- Do not replace the publishability audit or readiness gate.
- Do not hide semantic, topology, monster-reference, or other non-media blockers.
- Do not count `web/static/media` fallback assets as module-local media completion.
- Do not rewrite generated media files or regenerate assets in this change.

# Impact

- A fresh authoritative MMG pass suppresses stale media-only sidebar handoff signals.
- A fresh authoritative MMG fail keeps or creates the sidebar MMG handoff based on actual missing module-local media.
- Existing modules without an MMG report continue to use current build-report behavior.
- Sidebar users get deterministic feedback that reflects final MMG media state instead of stale publishability snapshots.

# Risks

- If the MMG report audits a different asset set than the unified asset status endpoint, sidebar state could diverge from MMG UI state.
- If the report is treated too broadly, it could accidentally suppress non-media blockers.
- If generation completion remains socket-successful despite asset failures, users may still need clearer residual-missing feedback.

# Fallback

- If the MMG report is absent, malformed, non-authoritative, or has an unknown contract, fall back to existing `toolkit_build_report.json` sidebar behavior.
- If MMG report writing fails, keep the existing report refresh path and log degradation without blocking the socket completion path.
- Keep non-media build report failures visible even when MMG media status passes.

# Merge Safety and SP/MP Impact

- Keep MMG report construction in a toolkit extension/helper with thin host wiring.
- Keep sidebar override localized to `ModuleStitcher` module-list metadata.
- Gameplay runtime and single-player flow are unaffected; this targets module toolkit/build-time surfaces.
