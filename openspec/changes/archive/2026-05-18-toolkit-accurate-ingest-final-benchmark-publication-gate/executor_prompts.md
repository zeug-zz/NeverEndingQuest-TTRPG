# Executor Prompts: Final Benchmark and Publication Gate Integration

## Section 1: Benchmark Fixture Contract

### Builder Prompt: Benchmark fixture model and Numillian fixture

```text
Implement Steps 2.1-2.5 and 3.1-3.7 only.

Goal:
Create the benchmark fixture contract model and the Numillian benchmark fixture data file.

Files to create:
- utils/toolkit_source_fidelity_benchmark.py (fixture schema, validation, loading, scoring model)
- data/benchmarks/The_Hidden_City_of_Numillian_benchmark.json (Numillian fixture)

Hard constraints (MUST):
- Benchmark fixture schema MUST define expectation categories with thresholds.
- Fixture validation MUST reject missing required fields.
- Fixture loading MUST fail open (return None/empty) when fixture file is missing.
- Per-category scoring MUST return one of: pass, degraded, blocked, unknown.
- Aggregate status MUST be the worst category status (blocked > degraded > pass > unknown).
- Numillian fixture MUST include all 5 categories with explicit per-category thresholds.
- Numillian NPC count MUST be 20, location count MUST be 13.
- Numillian puzzle list MUST include skull_riddle, flooding_room, kill_the_dog_mindscape.
- Numillian lore list MUST include gatepact, kobe_protection.
- Numillian tone expectation MUST be quirky_character_driven_hidden_city.
- Numillian blocked replacement MUST be generic_conspiracy_thriller.
- Zero LLM provider calls.

Allowed files only:
- utils/toolkit_source_fidelity_benchmark.py
- data/benchmarks/The_Hidden_City_of_Numillian_benchmark.json

Verification:
- .venv/bin/python -m py_compile utils/toolkit_source_fidelity_benchmark.py
- .venv/bin/python -c "from utils.toolkit_source_fidelity_benchmark import *; print('OK')"
- .venv/bin/python -c "import json; json.load(open('data/benchmarks/The_Hidden_City_of_Numillian_benchmark.json')); print('Valid JSON')"
```

## Section 2: Benchmark Runner

### Builder Prompt: Benchmark runner script

```text
Implement Steps 4.1-4.10 only.

Goal:
Create the deterministic accurate-ingest benchmark runner that compares ingested module artifacts against a benchmark fixture.

Files to create:
- scripts/benchmark_accurate_ingest.py

Hard constraints (MUST):
- MUST support --module flag for module-local execution.
- MUST support --benchmark flag for fixture selection (default Numillian).
- MUST support --json flag for machine-readable output.
- MUST load source graph artifacts from module workspace or module directory.
- MUST score each benchmark category against fixture thresholds.
- MUST compute aggregate status using worst-category-wins rule.
- MUST write accurate_ingest_benchmark_report.json to module workspace.
- MUST return source_fidelity_status: "unknown" when source graph artifacts are absent.
- MUST return clear error when benchmark fixture is missing.
- Zero LLM provider calls.
- Use .venv/bin/python for execution.

Allowed files only:
- scripts/benchmark_accurate_ingest.py

Verification:
- .venv/bin/python -m py_compile scripts/benchmark_accurate_ingest.py
- .venv/bin/python scripts/benchmark_accurate_ingest.py --help
- .venv/bin/python scripts/benchmark_accurate_ingest.py --module NonexistentModule --json
  (expect unknown or fixture-not-found, not crash)
- .venv/bin/python scripts/benchmark_accurate_ingest.py --module The_Hidden_City_of_Numillian --json
  (expect structured JSON output with status and category breakdown)
```

## Section 3: Publication Gate Composition

### Builder Prompt: Gate composition helper

```text
Implement Steps 5.1-5.7 only.

Goal:
Create the publication gate composition helper that integrates source-fidelity status with existing readiness and publishability checks.

Files to create:
- utils/toolkit_publication_gate_composer.py

Hard constraints (MUST):
- MUST compose three dimensions: ready_status, publishable_status, source_fidelity_status.
- MUST apply worst-status-wins rule with explicit precedence.
- MUST treat degraded + pass + pass as degraded (warning, not blocker).
- MUST treat blocked source-fidelity as publication blocker regardless of other gates.
- MUST treat unknown source-fidelity as non-blocking (fail open).
- MUST honor ENABLE_ACCURATE_INGEST_FINAL_BENCHMARK flag; when False, source-fidelity degrades to unknown.
- MUST NOT weaken existing ready_status or publishable_status semantics.
- MUST produce a structured output with final_status, warnings[], blockers[], and per-dimension status.

Allowed files only:
- utils/toolkit_publication_gate_composer.py

Verification:
- .venv/bin/python -m py_compile utils/toolkit_publication_gate_composer.py
- .venv/bin/python -c "from utils.toolkit_publication_gate_composer import *; print('OK')"
```

## Section 4: Report Surfacing and Feature Flag

### Builder Prompt: Integration into existing reports

```text
Implement Steps 6.1-6.5 and 7.1-7.4 only.

Goal:
Surface source-fidelity status in existing publishability audit and toolkit report outputs. Add feature flag.

Files to modify:
- scripts/audit_module_publishability.py (add source_fidelity_status dimension)
- model_config.py (add ENABLE_ACCURATE_INGEST_FINAL_BENCHMARK flag)
- web/extensions/toolkit_module_finisher.py (surface source-fidelity in report)
- config_template.py (document flag)

Hard constraints (MUST):
- Add source_fidelity_status to publishability audit JSON output under a new key.
- Include per-category breakdown when source graph artifacts are present.
- Existing ready_status and publishable_status keys and values MUST remain unchanged.
- Legacy modules without accurate-ingest artifacts MUST report source_fidelity_status: "unknown".
- Feature flag default MUST be True.
- When flag is False, source-fidelity checks MUST degrade to unknown.
- Toolkit finisher report MUST surface source_fidelity_status alongside existing status fields.
- Existing finisher report keys and values MUST remain unchanged.
- Additive-only changes; no removal of existing report fields.

Allowed files only:
- scripts/audit_module_publishability.py
- model_config.py
- web/extensions/toolkit_module_finisher.py
- config_template.py

Verification:
- .venv/bin/python -m py_compile scripts/audit_module_publishability.py model_config.py web/extensions/toolkit_module_finisher.py config_template.py
- .venv/bin/python scripts/audit_module_publishability.py --module The_Hidden_City_of_Numillian --json
  (expect source_fidelity_status in output)
- .venv/bin/python -c "from model_config import ENABLE_ACCURATE_INGEST_FINAL_BENCHMARK; print(ENABLE_ACCURATE_INGEST_FINAL_BENCHMARK)"
  (expect True)
```

## Section 5: Regression Tests

### Builder Prompt: Test suites for benchmark and publication gate

```text
Implement Steps 8.1-8.6 only.

Goal:
Create regression tests for the benchmark runner, publication gate composer, and publishability audit extensions.

Files to create:
- scripts/test_accurate_ingest_numillian_benchmark.py

Files to extend:
- scripts/test_audit_module_publishability.py

Hard constraints (MUST):
- Benchmark fixture tests MUST cover: valid fixture loading, missing fixture fail-open, invalid fixture rejection, per-category threshold validation.
- Benchmark runner tests MUST cover: fixture-based scoring, aggregate status computation, unknown fallback when artifacts absent, category-level pass/degraded/blocked derivation.
- Publication gate tests MUST cover: all status combinations from decision table, degraded-with-waiver (warning not blocker), blocked fidelity blocks, unknown fidelity non-blocking, feature flag disabled degrades to unknown.
- Publishability audit tests MUST verify source_fidelity_status field presence in JSON output without breaking existing assertions.
- Zero LLM provider calls.
- All tests MUST be deterministic.
- Use .venv/bin/python for test execution.

Allowed files only:
- scripts/test_accurate_ingest_numillian_benchmark.py
- scripts/test_audit_module_publishability.py

Verification:
- .venv/bin/python -m py_compile scripts/test_accurate_ingest_numillian_benchmark.py scripts/test_audit_module_publishability.py
- .venv/bin/python -m unittest -q scripts.test_accurate_ingest_numillian_benchmark
- .venv/bin/python -m unittest -q scripts.test_audit_module_publishability
```

## Section 6: Final Verification

### Builder Prompt: Full verification pass

```text
Run Steps 9.1-9.7 only. Do not modify code.

Goal:
Verify all implementation is complete, correct, and coherent.

Commands:
- .venv/bin/python -m py_compile on all modified/create files
- .venv/bin/python -m unittest -q scripts.test_accurate_ingest_numillian_benchmark
- .venv/bin/python -m unittest -q scripts.test_audit_module_publishability
- .venv/bin/python scripts/benchmark_accurate_ingest.py --module The_Hidden_City_of_Numillian --json
- .venv/bin/python scripts/audit_module_publishability.py --module The_Hidden_City_of_Numillian --json
- openspec validate toolkit-accurate-ingest-final-benchmark-publication-gate
- git diff --check
- .venv/bin/python scripts/check_ascii_compliance.py --summary-only (changed files only)

Report:
- Test counts and pass/fail.
- Numillian benchmark status.
- Numillian publishability status with source-fidelity dimension.
- Validation status.
- ASCII/whitespace status.
```
