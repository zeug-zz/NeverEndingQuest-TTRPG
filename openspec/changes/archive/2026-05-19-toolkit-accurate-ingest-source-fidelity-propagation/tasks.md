# Tasks: Accurate-Ingest Source-Fidelity Propagation

## 1. Baseline Review

- [x] 1.1 Review current source-fidelity helpers in `web/extensions/toolkit_homebrew_packet_builder.py`.
- [x] 1.2 Review `scripts/audit_module_publishability.py` source-fidelity loading and gate composition.
- [x] 1.3 Review `web/extensions/toolkit_module_finisher.py` build report generation.
- [x] 1.4 Review existing tests for source-fidelity, publishability, and GUI accurate-ingest status.

## 2. Module-Level Artifact Contract

- [x] 2.1 Define `SOURCE_FIDELITY_REPORT_VERSION = "source_fidelity_report.v1"` in the narrowest appropriate module.
- [x] 2.2 Add or normalize helper to build final module-level source-fidelity report payload.
- [x] 2.3 Include required fields: `report_version`, `module_slug`, `source_fidelity_status`, and `categories`.
- [x] 2.4 Preserve provenance where available: `source_hash`, `source_path`, workspace artifact refs, benchmark/build-fidelity detail, waiver data.
- [x] 2.5 Persist the artifact as `modules/<slug>/source_fidelity_report.json` for accurate-ingest builds.

## 3. Build Report Surfacing

- [x] 3.1 Ensure `toolkit_build_report.json` includes final `source_fidelity_status`.
- [x] 3.2 Include `source_fidelity_categories` or equivalent category detail in `toolkit_build_report.json`.
- [x] 3.3 Include artifact reference to `source_fidelity_report.json` when present.
- [x] 3.4 Ensure report surfacing does not treat `MODULE_SUMMARY.md` as a source-fidelity repair mechanism.

## 4. Publishability Audit Precedence

- [x] 4.1 Update `_load_source_fidelity_status(...)` in `scripts/audit_module_publishability.py` to prefer `source_fidelity_report.json`.
- [x] 4.2 Preserve fallback to `accurate_ingest_benchmark_report.json`.
- [x] 4.3 Preserve legacy fail-open `unknown` when neither artifact exists.
- [x] 4.4 Ensure blocked module-level source fidelity blocks final publishability.
- [x] 4.5 Ensure stale benchmark status cannot override module-level source-fidelity status.
- [x] 4.6 Preserve existing degraded/waiver behavior through `utils/toolkit_publication_gate_composer.py` unless a narrow composer bug is found.

## 5. Tests

- [x] 5.1 Add publishability test: module-level `source_fidelity_report.json` is preferred over stale benchmark report.
- [x] 5.2 Add publishability test: `source_fidelity_status="blocked"` blocks final publishability.
- [x] 5.3 Add publishability test: `source_fidelity_status="pass"` allows readiness/semantic gates to decide.
- [x] 5.4 Add publishability test: legacy modules without accurate-ingest artifacts remain `unknown` and fail open.
- [x] 5.5 Add GUI/finisher test: accurate-ingest build persists `source_fidelity_report.json` into module directory.
- [x] 5.6 Add build report test: `toolkit_build_report.json` mirrors source-fidelity status and categories.
- [x] 5.7 Add regression test: `MODULE_SUMMARY.md` does not repair or override source-fidelity failures.

## 6. Verification

- [x] 6.1 Run `.venv/bin/python -m py_compile scripts/audit_module_publishability.py web/extensions/toolkit_module_finisher.py web/extensions/toolkit_homebrew_packet_builder.py`.
- [x] 6.2 Run `.venv/bin/python -m unittest -q scripts.test_audit_module_publishability`.
- [x] 6.3 Run `.venv/bin/python -m unittest -q scripts.test_toolkit_homebrew_gui_unified_flow`.
- [x] 6.4 Run `.venv/bin/python -m unittest -q scripts.test_toolkit_module_build_publication_parity`.
- [x] 6.5 Run `openspec validate toolkit-accurate-ingest-source-fidelity-propagation`.
- [x] 6.6 Run targeted ASCII compliance on changed Python/test files.

## Builder Guidance

Use micro-edits. Start with report loading/precedence tests in `scripts/test_audit_module_publishability.py`, then implement the smallest helper changes needed. Avoid mutating production module data. Keep GUI template changes out of scope unless a route/status test proves they are required.
