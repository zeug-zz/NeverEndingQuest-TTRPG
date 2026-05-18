# Tasks: Toolkit Accurate-Ingest Final Benchmark and Publication Gate Integration

## 1. Artifact and State Review

- [x] 1.1 Review `plans/accurate-ingest.md` Phase 11 acceptance criteria.
- [x] 1.2 Review existing `scripts/audit_module_publishability.py` gate composition.
- [x] 1.3 Review existing `scripts/audit_module_readiness.py` for readiness status contract.
- [x] 1.4 Review existing accurate-ingest artifact formats: `source_graph.json`, `source_fidelity_report.json`, `build_fidelity_report.json`.
- [x] 1.5 Confirm no existing tests will break from additive publication gate changes.

## 2. Benchmark Fixture Contract and Model

- [x] 2.1 Define benchmark fixture JSON schema in `utils/toolkit_source_fidelity_benchmark.py`.
- [x] 2.2 Add fixture validation helper: required fields, threshold ranges, category completeness.
- [x] 2.3 Add fixture loading helper with fail-open missing-fixture behavior.
- [x] 2.4 Define per-category scoring result shape (pass/degraded/blocked/unknown per category).
- [x] 2.5 Define aggregate status computation (worst category wins; unknown treated as non-blocking).

## 3. Numillian Benchmark Fixture

- [x] 3.1 Create `data/benchmarks/The_Hidden_City_of_Numillian_benchmark.json`.
- [x] 3.2 Populate NPC preservation expectations: 23 named source NPCs, minimum 16 represented, minor/unused allowed with review note.
- [x] 3.3 Populate location preservation expectations: 13 source locations, exact names preserved.
- [x] 3.4 Populate puzzle preservation expectations: skull riddle, flooding room, kill-the-dog mindscape.
- [x] 3.5 Populate lore preservation expectations: gatepact, kobe protection.
- [x] 3.6 Populate tone preservation expectation: quirky character-driven hidden city, block generic conspiracy thriller.
- [x] 3.7 Define publication thresholds: pass at 90%/100%/100%/100%, degraded at 70%/85%/67%/50%.

## 4. Benchmark Runner

- [x] 4.1 Create `scripts/benchmark_accurate_ingest.py`.
- [x] 4.2 Implement `--module` flag for module-local execution.
- [x] 4.3 Implement `--benchmark` flag for fixture selection (defaults to Numillian).
- [x] 4.4 Implement category scoring from source graph artifacts.
- [x] 4.5 Implement aggregate status computation.
- [x] 4.6 Write `accurate_ingest_benchmark_report.json` to module workspace or output directory.
- [x] 4.7 Return `unknown` for modules without source graph artifacts (fail open).
- [x] 4.8 Return clear error for missing benchmark fixture (fail open).
- [x] 4.9 Support `--json` output flag for machine-readable results.
- [x] 4.10 Zero LLM provider calls in benchmark runner.

## 5. Publication Gate Composition

- [x] 5.1 Create `utils/toolkit_publication_gate_composer.py`.
- [x] 5.2 Implement three-dimensional gate composition: ready_status + publishable_status + source_fidelity_status.
- [x] 5.3 Implement worst-status-wins rule with explicit precedence.
- [x] 5.4 Implement degraded-with-waiver behavior: warning surfaced, waiver accepted, publication allowed.
- [x] 5.5 Implement blocked source-fidelity behavior: publication blocked regardless of other gates.
- [x] 5.6 Implement unknown source-fidelity behavior: fail open, no blocking.
- [x] 5.7 Implement feature flag check via `ENABLE_ACCURATE_INGEST_FINAL_BENCHMARK`.

## 6. Report Surfacing

- [x] 6.1 Add `source_fidelity_status` to `audit_module_publishability.py` output.
- [x] 6.2 Surface source-fidelity category breakdown in publishability report JSON.
- [x] 6.3 Add source-fidelity publication warnings/blocks to toolkit finisher report.
- [x] 6.4 Ensure existing `ready_status` and `publishable_status` remain unchanged.
- [x] 6.5 Ensure legacy modules without accurate-ingest artifacts report `unknown` and do not block.

## 7. Feature Flag

- [x] 7.1 Add `ENABLE_ACCURATE_INGEST_FINAL_BENCHMARK = True` to `model_config.py`.
- [x] 7.2 When flag is `False`, all source-fidelity checks degrade to `unknown`.
- [x] 7.3 When flag is `True`, benchmark and gate composition are fully active.
- [x] 7.4 Document flag in `config_template.py` with description.

## 8. Regression Tests

- [x] 8.1 Add `scripts/test_accurate_ingest_numillian_benchmark.py` for benchmark fixture validation.
- [x] 8.2 Add benchmark runner tests: fixture loading, category scoring, aggregate status, unknown fallback.
- [x] 8.3 Add publication gate composition tests: all status combinations, degraded-with-waiver, blocked, legacy unknown.
- [x] 8.4 Add feature flag tests: disabled flag returns `unknown`.
- [x] 8.5 Extend `scripts/test_audit_module_publishability.py` for source-fidelity dimension.
- [x] 8.6 Verify existing publishability audit tests still pass.

## 9. Verification

- [x] 9.1 Run `.venv/bin/python -m py_compile` on all modified files.
- [x] 9.2 Run `.venv/bin/python -m unittest -q scripts.test_accurate_ingest_numillian_benchmark`.
- [x] 9.3 Run `.venv/bin/python -m unittest -q scripts.test_audit_module_publishability`.
- [x] 9.4 Run `.venv/bin/python scripts/benchmark_accurate_ingest.py --module The_Hidden_City_of_Numillian --json`.
- [x] 9.5 Run `.venv/bin/python scripts/audit_module_publishability.py --module The_Hidden_City_of_Numillian --json`.
- [x] 9.6 Run `openspec validate toolkit-accurate-ingest-final-benchmark-publication-gate`.
- [x] 9.7 Run changed-file ASCII and whitespace checks.

## Implementation Notes

- Keep all benchmark measurement deterministic; no LLM provider calls.
- Keep publication gate additive to existing readiness and publishability contracts.
- Preserve legacy module fail-open behavior (unknown = no blocking).
- Use `.venv/bin/python` for all benchmark, publishability, and test commands.
- Do not mutate module data or create benchmark result files in test-only mode.
