## Why

The accurate-ingest pipeline now has source graph extraction, multipass normalization, fidelity review/repair, blueprint handoff, and a pre-build review panel. The remaining source-fidelity gap is after the packet builder runs: the generated module can still omit required source NPCs, locations, puzzles, clue chains, plot beats, or source-locked names before the existing readiness/finisher pipeline sees the module.

This change adds build-time source-fidelity gates that inspect the built module against the existing accurate-ingest artifacts and persist reviewable reports. It prevents a source-divergent generated module from moving forward as if it were publishable.

## Phase Numbering Note

The roadmap has two historical numbering schemes. This OpenSpec change treats **Phase 6** as the next implementation slice after the completed fidelity review panel: **build fidelity gates and final source fidelity reporting**. Narrative enrichment remains a later phase and is explicitly out of scope here.

## What Changes

- Add a build fidelity report helper that compares generated module artifacts against `source_graph.json`, `builder_blueprint.json`, and existing fidelity/normalization reports.
- Persist `build_fidelity_report.json` after packet build execution.
- Persist or update `source_fidelity_report.json` as a final rollup across normalization, blueprint, and build fidelity outcomes.
- Fail closed before post-build finishing/publication when critical source atoms are missing or replaced.
- Surface compact build-fidelity status in existing toolkit job results and review/status payloads.
- Preserve legacy behavior when workspaces do not carry accurate-ingest source/blueprint artifacts or the feature flag is disabled.

## Capabilities

### New Capabilities

- `toolkit-build-fidelity-report`: Generated modules can be audited against source graph and builder blueprint artifacts after build execution.
- `toolkit-build-fidelity-gate`: Accurate-ingest builds fail closed before finishing when critical source fidelity blockers remain.
- `toolkit-source-fidelity-rollup`: Final source fidelity reports summarize normalization, blueprint, and build fidelity outcomes for review and regression.
- `toolkit-build-fidelity-status-surfacing`: Existing toolkit status/review payloads expose compact build fidelity outcomes without redesigning the UI.

## Non-Goals

- Do not modify `ModuleBuilder` or `ModuleGenerator` internals.
- Do not add narrative enrichment or `narrative_enrichment_plan.json` behavior.
- Do not repair generated modules in this slice.
- Do not introduce waiver/approval bypasses for critical blockers.
- Do not require build-fidelity gates for legacy workspaces without accurate-ingest artifacts.
- Do not replace the existing readiness/publishability pipeline; this gate runs before it.

## Impact

- **Backend:** likely `utils/toolkit_build_fidelity.py` (new), `utils/toolkit_homebrew_upload_contract.py`, `web/extensions/toolkit_homebrew_packet_builder.py`, `web/routes/toolkit_homebrew_routes.py`, and `model_config.py`.
- **Frontend:** minimal status surfacing in `web/templates/module_toolkit.html` only if needed for compact report display.
- **Tests:** new helper, packet-builder, route/source-contract, and legacy compatibility tests.
- **Risk:** false positives can block builds. The helper must distinguish critical source atoms from advisory/tone atoms and report exact blocker reasons.

## Rollback

- Add a feature flag such as `ENABLE_ACCURATE_INGEST_BUILD_FIDELITY_GATES`, default enabled for accurate-ingest workspaces.
- If disabled, preserve current post-build behavior.
- If report assembly fails in accurate-ingest mode, fail closed with a reviewable `build_fidelity_report.json` error payload.
- If report assembly fails in legacy mode, preserve existing behavior.
