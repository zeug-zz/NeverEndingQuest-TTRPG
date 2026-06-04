## Why

Accurate-ingest GUI builds can generate usable module artifacts and then fail at the final build-fidelity boundary because source-fidelity diagnostics are treated as absolute publication blockers. This is wrong for cases like `Well_of_Ruin`, where markdown/mechanics headings such as `Trigger`, `Passive Element`, and `Active Element` are misclassified as required locations and stop a module that should proceed to final editorial reconciliation and publication validation.

## What Changes

- Add a final blocker-classification boundary after ModuleBuilder output and build-fidelity reporting.
- Split final build-fidelity blockers into fatal blockers and editorial/source-fidelity blockers.
- Keep fatal structural blockers fail-closed before readiness/finishing.
- Convert editorial/source-fidelity blockers into final reconciliation evidence instead of immediate build failure.
- Persist `final_reconciliation_brief.json` and `final_reconciliation_report.json` artifacts in the upload workspace.
- Add provider-free reconciliation acceptance/status plumbing for this boundary change; live LLM Builder patching is deferred to the next change.
- Update report-agreement/publication status semantics so accepted reconciliation can allow playable publication without falsely claiming clean source fidelity.
- Update GUI status language to distinguish playable publication from clean source-fidelity preservation.

Non-goals:

- Do not change source manifest/source graph extraction, normalized packet generation, blueprint generation, backstage audit briefing, or source-enhanced ModuleBuilder handoff.
- Do not implement the live LLM Builder final editor in this change.
- Do not mutate original source graph artifacts to hide extractor mistakes.
- Do not weaken JSON/schema/readiness/publishability gates.
- Do not claim `source_fidelity_status: pass` unless source fidelity truly passes.

## Capabilities

### New Capabilities

- `accurate-ingest-final-blocker-classification`: Classify post-ModuleBuilder build-fidelity blockers as fatal or editorial before deciding whether the build can continue.
- `accurate-ingest-final-reconciliation-brief`: Persist deterministic final reconciliation evidence artifacts for editorial blockers.
- `accurate-ingest-build-fidelity-editorial-continuation`: Allow generated modules with editorial/source-fidelity blockers to continue toward final reconciliation instead of stopping before readiness/finishing.
- `accurate-ingest-reconciled-source-fidelity-status`: Represent accepted final reconciliation as an effective source-fidelity status distinct from clean pass.

### Modified Capabilities

- `toolkit-build-fidelity-gate`: Build-fidelity gating must fail closed only for fatal structural blockers; editorial/source-fidelity blockers must route to final reconciliation.
- `toolkit-source-fidelity-publication-gate`: Source-fidelity blocked status must not block playable publication when accepted final reconciliation exists and all deterministic publication gates pass.
- `toolkit-source-fidelity-publication-precedence`: Publishability audit must consume module-level final reconciliation status after source-fidelity status lookup.
- `toolkit-module-build-reporting`: Toolkit reports must include final reconciliation status and source-fidelity effective status.
- `toolkit-homebrew-review-status-ux`: GUI status must distinguish playable publication from clean source-fidelity pass and show reconciled/degraded source fidelity honestly.

## Impact

- Affected code: `web/extensions/toolkit_homebrew_packet_builder.py`, `utils/toolkit_build_fidelity.py`, new final blocker/reconciliation utilities, `utils/toolkit_report_agreement.py`, `web/extensions/toolkit_module_finisher.py`, `web/templates/module_toolkit.html`, and targeted tests.
- Affected artifacts: workspace `build_fidelity_report.json`, `source_fidelity_report.json`, new `final_reconciliation_brief.json`, new `final_reconciliation_report.json`, module `toolkit_build_report.json`, GUI job state payloads.
- Provider behavior: this boundary change is provider-free. If accepted reconciliation is absent, source-fidelity blockers remain blocking. The next change will add live LLM Builder final editorial patching.
- Compatibility: legacy/non-source builds remain unchanged. Single-player and tabletop runtime behavior are unaffected; this only changes accurate-ingest final publication readiness flow.
- Fallback: fatal blockers still block. Editorial blockers without accepted reconciliation still block playable publication.
