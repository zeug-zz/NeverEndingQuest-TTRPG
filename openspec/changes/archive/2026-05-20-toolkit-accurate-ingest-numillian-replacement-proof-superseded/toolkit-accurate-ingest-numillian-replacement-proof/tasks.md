# Tasks: Accurate-Ingest Numillian Replacement Proof

## 1. Baseline And Source Authority

- [ ] 1.1 Confirm source markdown exists at `Local_Docs/modules/hombrew/modules/The Hidden City of Numillian.md`.
- [ ] 1.2 Confirm `modules/The_Hidden_City_of_Numillian/` is the production target.
- [ ] 1.3 Confirm `modules/The_Hidden_City_of_Numillian_v1/` is absent or explicitly non-production/archive-only.
- [ ] 1.4 Inspect `data/benchmarks/The_Hidden_City_of_Numillian_benchmark.json` and record required expectations.
- [ ] 1.5 Inspect current Numillian git status and identify canonical vs runtime artifact changes.

## 2. Deterministic Production Module Proof

- [ ] 2.1 Build or refresh production Numillian from source markdown through deterministic accurate-ingest artifacts.
- [ ] 2.2 Persist or identify workspace artifacts used for the production build when practical.
- [ ] 2.3 Ensure canonical artifacts exist: context files, BU plot/party files, BU areas, maps, seed files, source report, source-fidelity report, validation report, toolkit report, benchmark report, and summary/doc files.
- [ ] 2.4 Ensure runtime files remain ignored and are not required for publication.
- [ ] 2.5 Ensure canonical artifacts are trackable without `git add -f`.

## 3. Benchmark And Source-Fidelity Proof

- [ ] 3.1 Run the Numillian source-fidelity benchmark against current production module.
- [ ] 3.2 Confirm all 13 source locations are preserved by original source name or approved mapping.
- [ ] 3.3 Confirm required NPC threshold passes.
- [ ] 3.4 Confirm Trial-at-the-Door puzzle, skull riddle, flooding room puzzle, kill-the-dog mindscape, Gatepact lore, Kobe protection objective, and quirky tone are present.
- [ ] 3.5 If benchmark is degraded, document accepted limitation and verify waiver contract before publication can pass.
- [ ] 3.6 Confirm `source_fidelity_report.json`, `accurate_ingest_benchmark_report.json`, and `toolkit_build_report.json` agree on final source-fidelity status.

## 4. Validation And Publishability Proof

- [ ] 4.1 Run module schema/reference validation for `The_Hidden_City_of_Numillian`.
- [ ] 4.2 Run publishability audit for `The_Hidden_City_of_Numillian`.
- [ ] 4.3 Confirm publishability blocks if source fidelity is blocked.
- [ ] 4.4 Confirm publishability passes only when readiness, semantic publication checks, and source fidelity allow it.
- [ ] 4.5 Verify media-handoff debt, if any, is explicit and does not masquerade as full publication readiness.

## 5. MODULE_SUMMARY And v1 Archive Guard

- [ ] 5.1 Confirm `MODULE_SUMMARY.md` is generated from final audited module artifacts.
- [ ] 5.2 Confirm `MODULE_SUMMARY.md` does not include stale v1-only content or generic replacement plot drift.
- [ ] 5.3 Confirm `MODULE_SUMMARY.md` is not used as a source-fidelity input or repair path.
- [ ] 5.4 Confirm v1 archive is not selected as production by published module catalog or default module discovery.
- [ ] 5.5 Document v1 role as archive/comparison if it remains present.

## 6. Tests And Regression Coverage

- [ ] 6.1 Extend or add Numillian end-to-end tests proving source expectations and publishability gate agreement.
- [ ] 6.2 Add regression coverage for v1 archive/non-production guard.
- [ ] 6.3 Add regression coverage proving `MODULE_SUMMARY.md` remains final-derived only.
- [ ] 6.4 Add regression coverage for benchmark/publishability/source-fidelity agreement.

## 7. Verification

- [ ] 7.1 Run `.venv/bin/python -m py_compile utils/toolkit_blueprint_seed_writer.py utils/toolkit_blueprint_enrichment.py web/extensions/toolkit_homebrew_packet_builder.py web/routes/toolkit_homebrew_routes.py web/extensions/toolkit_module_finisher.py scripts/audit_module_publishability.py`.
- [ ] 7.2 Run `.venv/bin/python -m unittest -q scripts.test_toolkit_blueprint_v2_contract`.
- [ ] 7.3 Run `.venv/bin/python -m unittest -q scripts.test_toolkit_blueprint_seed_writer`.
- [ ] 7.4 Run `.venv/bin/python -m unittest -q scripts.test_toolkit_blueprint_enrichment_patches`.
- [ ] 7.5 Run `.venv/bin/python -m unittest -q scripts.test_toolkit_homebrew_gui_unified_flow`.
- [ ] 7.6 Run `.venv/bin/python -m unittest -q scripts.test_toolkit_module_summary_finisher_contract`.
- [ ] 7.7 Run `.venv/bin/python -m unittest -q scripts.test_accurate_ingest_numillian_end_to_end`.
- [ ] 7.8 Run `.venv/bin/python -m unittest -q scripts.test_audit_module_publishability`.
- [ ] 7.9 Run `.venv/bin/python core/validation/validate_module_files.py --module The_Hidden_City_of_Numillian`.
- [ ] 7.10 Run `.venv/bin/python scripts/benchmark_accurate_ingest.py --module The_Hidden_City_of_Numillian --json`.
- [ ] 7.11 Run `.venv/bin/python scripts/audit_module_publishability.py --module The_Hidden_City_of_Numillian --json`.
- [ ] 7.12 Run `openspec validate toolkit-accurate-ingest-numillian-replacement-proof`.
- [ ] 7.13 Run targeted ASCII compliance on changed Python/prompt/docs files.

## Builder Guidance

Do not restore `modules/The_Hidden_City_of_Numillian_v1/` as production. Prefer deterministic rebuild/refresh from source markdown and targeted schema-valid remediation. Do not commit or push. Keep runtime files ignored and canonical artifacts trackable without force-add.
