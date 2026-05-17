## 1. Artifact Contract and Feature Flag

- [x] 1.1 Add `ENABLE_ACCURATE_INGEST_BUILD_FIDELITY_GATES` to `model_config.py`, default enabled.
- [x] 1.2 Extend `utils/toolkit_homebrew_upload_contract.py` workspace paths with `build_fidelity_report.json` and `source_fidelity_report.json`.
- [x] 1.3 Add atomic persistence/load helpers for both reports without breaking existing artifact helpers.
- [x] 1.4 Add source-contract tests proving no `ModuleBuilder`/`ModuleGenerator` internals are modified.

## 2. Build Fidelity Helper

- [x] 2.1 Add `utils/toolkit_build_fidelity.py` with SPDX/header and artifact-only helpers.
- [x] 2.2 Implement `is_build_fidelity_required(workspace)` using accurate-ingest source/blueprint artifacts and the feature flag.
- [x] 2.3 Implement `build_build_fidelity_report(workspace, module_dir)` with compact status, artifact availability, coverage, blockers, warnings, and stage results.
- [x] 2.4 Implement deterministic checks for required source NPCs, keyed locations, plot beats, puzzle/trial rules, clue chains, encounters/items where source artifacts provide enough structure.
- [x] 2.5 Implement advisory warnings for tone/profile divergence where deterministic structure is insufficient.
- [x] 2.6 Implement `can_continue_after_build_fidelity(report)` with fail-closed outcomes for blocked/failed critical source fidelity.
- [x] 2.7 Implement `build_source_fidelity_rollup(workspace, build_report)` using normalization, blueprint, and build fidelity artifacts.

## 3. Packet Builder Integration

- [x] 3.1 Integrate build fidelity report generation after successful packet build and before post-build finishing/publication handoff.
- [x] 3.2 Persist `build_fidelity_report.json` and `source_fidelity_report.json` into the upload workspace.
- [x] 3.3 If build fidelity is blocked/failed, return a reviewable blocked job result and do not invoke finishing/publication.
- [x] 3.4 If build fidelity passes/degrades without blockers, preserve existing finishing/publication flow.
- [x] 3.5 Preserve legacy behavior when gates are disabled or no accurate-ingest artifacts are present.

## 4. Status and Review Surfacing

- [x] 4.1 Include compact build fidelity status in packet build result payloads.
- [x] 4.2 Include report artifact paths in existing job/review/status payloads where available.
- [x] 4.3 Add minimal toolkit UI/status rendering for build fidelity pass/degraded/blocked states without redesigning the review panel.
- [x] 4.4 Ensure blocked report payloads include actionable source atom/category/artifact path details.

## 5. Tests

- [x] 5.1 Add helper tests for pass, degraded warning-only, blocked missing required NPC, blocked missing keyed location, blocked replaced plot topology, failed malformed source artifact, failed missing module output, legacy workspace, and disabled flag.
- [x] 5.2 Add packet builder integration tests proving blocked build fidelity prevents finishing/publication executor calls.
- [x] 5.3 Add packet builder integration tests proving pass/degraded-without-blockers preserves existing finishing/publication flow.
- [x] 5.4 Add route/status tests proving report paths and compact status are exposed.
- [x] 5.5 Add source-contract tests proving no narrative enrichment, no repair mutation, and no `ModuleBuilder`/`ModuleGenerator` internals are touched.

## 6. Verification

- [x] 6.1 Run `.venv/bin/python -m py_compile utils/toolkit_build_fidelity.py utils/toolkit_homebrew_upload_contract.py web/extensions/toolkit_homebrew_packet_builder.py web/routes/toolkit_homebrew_routes.py model_config.py`.
- [x] 6.2 Run new build fidelity helper and packet builder tests.
- [x] 6.3 Run existing impacted suites: `scripts.test_packet_builder_blueprint_handoff`, `scripts.test_toolkit_homebrew_fidelity_review`, `scripts.test_toolkit_homebrew_md_upload_routes`, and `scripts.test_toolkit_module_build_publication_parity`.
- [x] 6.4 Run `openspec validate toolkit-accurate-ingest-build-fidelity-gates`.
- [x] 6.5 Confirm this slice does not add `narrative_enrichment_plan.json`, does not alter `ModuleBuilder`/`ModuleGenerator`, and does not mutate generated modules as a repair step.
