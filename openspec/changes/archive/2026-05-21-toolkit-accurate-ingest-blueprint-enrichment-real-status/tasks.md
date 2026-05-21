# Tasks

## 1. Status Contract Foundation

- [x] 1.1 Add or confirm bounded enrichment status constants, including skipped, not_implemented, degraded, failed, and complete.
- [x] 1.2 Add regression tests proving disabled enrichment returns skipped and enabled placeholder/no-provider enrichment cannot return complete.
- [x] 1.3 Add regression tests proving pass exceptions and pass-level errors return degraded or failed with diagnostics.

## 2. Patch Validation And Application Safety

- [x] 2.1 Add or confirm tests that structural mutation patches are rejected and do not mutate target files.
- [x] 2.2 Add or confirm tests that allowed prose patches apply deterministically and appear in applied results.
- [x] 2.3 Add regression coverage that rejected patches force degraded status when routed through a pipeline result.

## 3. Report Contract

- [x] 3.1 Add or confirm `build_enrichment_report(...)` preserves status, reason, counts, and diagnostics for skipped/not_implemented/degraded/complete results.
- [x] 3.2 Add or confirm pass-level metadata is surfaced or counted in the report without breaking existing consumers.
- [x] 3.3 Add source-contract tests proving no-op enrichment cannot be represented as complete by report composition.

## 4. Integration Compatibility

- [x] 4.1 Confirm feature flags remain disabled by default in `model_config.py` and documented in `config_template.py`.
- [x] 4.2 Confirm packet builder/readiness callers treat skipped/not_implemented enrichment as non-blocking diagnostics unless structural mutation/error policy says otherwise.
- [x] 4.3 Confirm no live provider calls are required for tests.

## 5. Verification

- [x] 5.1 Run compile checks for modified Python files.
- [x] 5.2 Run targeted blueprint enrichment tests.
- [x] 5.3 Run relevant toolkit GUI/build parity tests.
- [x] 5.4 Validate the OpenSpec change.

## Suggested Verification Commands

```bash
.venv/bin/python -m py_compile utils/toolkit_blueprint_enrichment.py scripts/test_toolkit_blueprint_enrichment_patches.py
.venv/bin/python -m unittest -q scripts.test_toolkit_blueprint_enrichment_patches
.venv/bin/python -m unittest -q scripts.test_toolkit_module_build_publication_parity
openspec validate toolkit-accurate-ingest-blueprint-enrichment-real-status
```
