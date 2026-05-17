# Builder Prompts: toolkit-accurate-ingest-build-fidelity-gates

Use these prompts sequentially. Each step MUST stop after verification and report evidence before the next step starts.

## Step 1 - Artifact Contract and Feature Flag

Implement OpenSpec `toolkit-accurate-ingest-build-fidelity-gates` Step 1 only.

Goal: Add artifact paths, persistence/load helpers, and feature flag for build fidelity reports.

Allowed files: `model_config.py`, `utils/toolkit_homebrew_upload_contract.py`, focused tests.

Forbidden changes: Do not edit packet builder integration yet. Do not create audit logic yet. Do not touch `ModuleBuilder` or `ModuleGenerator`.

Required:

- Add `ENABLE_ACCURATE_INGEST_BUILD_FIDELITY_GATES = True` near existing accurate-ingest flags.
- Add workspace paths for `build_fidelity_report.json` and `source_fidelity_report.json`.
- Add atomic persist/load helpers for both reports, matching existing helper style.
- Add source-contract tests proving no builder/generator internals are touched.

Verify:

- `.venv/bin/python -m py_compile model_config.py utils/toolkit_homebrew_upload_contract.py`
- targeted upload-contract/source-contract tests.

Report: changed files, helper names, test commands/results, and stop.

## Step 2 - Build Fidelity Helper

Implement OpenSpec `toolkit-accurate-ingest-build-fidelity-gates` Step 2 only.

Goal: Add artifact-only build fidelity audit helper.

Allowed files: `utils/toolkit_build_fidelity.py`, helper tests.

Forbidden changes: Do not integrate packet builder yet. Do not mutate generated modules. Do not call LLM/provider clients. Do not repair output.

Required:

- Implement `is_build_fidelity_required(workspace)`.
- Implement `build_build_fidelity_report(workspace, module_dir)`.
- Implement `can_continue_after_build_fidelity(report)`.
- Implement `build_source_fidelity_rollup(workspace, build_report)`.
- Detect required NPC/location/plot/puzzle/clue omissions using source graph and blueprint artifacts.
- Return compact blocker/warning lists with source atom/category/artifact path where possible.
- Preserve legacy/disabled outcomes without blocking.

Verify:

- `.venv/bin/python -m py_compile utils/toolkit_build_fidelity.py`
- helper tests for pass, degraded, blocked, failed, legacy, disabled.

Report: status values, blocker categories covered, test commands/results, and stop.

## Step 3 - Packet Builder Integration

Implement OpenSpec `toolkit-accurate-ingest-build-fidelity-gates` Step 3 only.

Goal: Run and persist build fidelity reports after successful packet build and before finishing/publication.

Allowed files: `web/extensions/toolkit_homebrew_packet_builder.py`, `utils/toolkit_homebrew_upload_contract.py` only if helper import adjustment is needed, integration tests.

Forbidden changes: Do not touch `ModuleBuilder`/`ModuleGenerator`. Do not add UI changes yet. Do not repair generated modules.

Required:

- After successful packet build, resolve generated module path.
- If build fidelity is not required, preserve existing flow.
- If required, build and persist `build_fidelity_report.json` and `source_fidelity_report.json`.
- If report blocks/fails, return a reviewable blocked result and do not call finishing/publication.
- If report passes/degrades without blockers, preserve existing finishing/publication flow.

Verify:

- `.venv/bin/python -m py_compile web/extensions/toolkit_homebrew_packet_builder.py`
- integration tests proving blocked report prevents finishing executor calls.
- integration tests proving pass/degraded path continues.

Report: exact integration point, blocked/pass behavior evidence, test commands/results, and stop.

## Step 4 - Status Surfacing

Implement OpenSpec `toolkit-accurate-ingest-build-fidelity-gates` Step 4 only.

Goal: Surface compact build fidelity status through existing toolkit job/status/review payloads and minimal UI text.

Allowed files: `web/routes/toolkit_homebrew_routes.py`, `web/templates/module_toolkit.html`, focused route/template tests.

Forbidden changes: Do not redesign the upload UI. Do not alter review approval semantics. Do not add narrative enrichment.

Required:

- Include build fidelity status/report paths in existing job/review/status payloads where available.
- Render compact pass/degraded/blocked lines in existing Homebrew upload status/review surfaces.
- Preserve legacy rendering when build fidelity fields are absent.

Verify:

- `.venv/bin/python -m py_compile web/routes/toolkit_homebrew_routes.py`
- route/status tests for report path exposure.
- template/source-contract tests for additive UI behavior.

Report: payload fields, UI strings/IDs added, test commands/results, and stop.

## Step 5 - Full Verification

Implement OpenSpec `toolkit-accurate-ingest-build-fidelity-gates` Step 5-6 verification only.

Goal: Complete test coverage, source-contract checks, and OpenSpec validation.

Allowed files: tests and `tasks.md` checkbox updates after all checks pass.

Forbidden changes: Do not add new runtime behavior in this step.

Required:

- Run py_compile gate from `tasks.md`.
- Run new build fidelity helper and packet builder tests.
- Run impacted suites: `scripts.test_packet_builder_blueprint_handoff`, `scripts.test_toolkit_homebrew_fidelity_review`, `scripts.test_toolkit_homebrew_md_upload_routes`, `scripts.test_toolkit_module_build_publication_parity`.
- Run `openspec validate toolkit-accurate-ingest-build-fidelity-gates`.
- Confirm no narrative enrichment, no repair mutation, and no builder/generator internal changes.
- Mark tasks complete only after evidence passes.

Report: all commands/results and final readiness for archive.
