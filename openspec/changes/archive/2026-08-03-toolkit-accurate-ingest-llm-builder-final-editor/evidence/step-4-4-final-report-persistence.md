# Step 4.4: Final Report Persistence

## Status

**COMPLETED** - 2026-06-12.

## Objective

Persist `final_reconciliation_report.json` with the LLM's `decisions`,
the apply-phase `changed_files`, the schema-validation outcome, the
publishability outcome, the report-agreement outcome, and the locked
`source_fidelity_effective_status: reconciled_degraded`. The on-disk file
must be byte-compatible with the archived boundary's report contract so
the legacy `utils.toolkit_final_reconciliation.is_final_reconciliation_accepted(...)`
oracle still recognizes it.

## Files Touched

- `utils/toolkit_llm_final_reconciliation.py` (added Step 4.4 helpers,
  constants, and one narrow bug fix in the persister)
- `scripts/test_toolkit_llm_final_reconciliation.py` (expanded Step 4.3
  shape test + 3 new test classes with 35 new tests)
- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/tasks.md`
  (Step 4.4 marked checked with this evidence)

## Production Changes (utils/toolkit_llm_final_reconciliation.py)

### Status-name and diagnostic-code constants

- `FINAL_RECONCILIATION_REPORT_STATUS_ACCEPTED = "accepted"`
- `FINAL_RECONCILIATION_REPORT_STATUS_NOT_ACCEPTED = "not_accepted"`
- `FINAL_RECONCILIATION_REPORT_STATUS_INVALID_ORCHESTRATOR_RESULT = "invalid_orchestrator_result"`
- `FINAL_RECONCILIATION_REPORT_PERSIST_STATUS_WRITTEN = "written"`
- `FINAL_RECONCILIATION_REPORT_PERSIST_STATUS_FAILED = "failed"`
- `FINAL_RECONCILIATION_REPORT_PERSIST_STATUS_NOT_ACCEPTED = "not_accepted"`
- `FINAL_RECONCILIATION_REPORT_PERSIST_STATUS_INVALID = "invalid"`
- `DIAGNOSTIC_CODE_REPORT_BUILD_FAILED = "report_build_failed"`
- `DIAGNOSTIC_CODE_REPORT_PERSIST_FAILED = "report_persist_failed"`
- `DIAGNOSTIC_CODE_NOT_ACCEPTED = "not_accepted"`

### Bounded report knobs

- `FINAL_RECONCILIATION_REPORT_DECISIONS_MAX_ITEMS = 50`
- `FINAL_RECONCILIATION_REPORT_DIAGNOSTIC_MESSAGE_MAX_LENGTH = 200`
- `FINAL_RECONCILIATION_REPORT_DIAGNOSTIC_MAX_ITEMS = 20`

### Version pin (legacy-compatible)

Imported `REPORT_VERSION` from `utils.toolkit_final_reconciliation` so the
on-disk file matches `accurate_ingest_final_reconciliation_report.v1`. The
import is wrapped in a defensive try/except so the module remains
importable in environments where the legacy helper is unavailable.

### Pure helpers

- `_is_orchestrator_result_accepted(orchestrator_result)` - returns
  `True` only when the orchestrator result is a dict with
  `status == "accepted"`.
- `_extract_accepted_step42_payload(orchestrator_result)` - returns a
  shallow copy of `accepted_result` or `None`.
- `_extract_accepted_patch_plan(orchestrator_result)` - returns a shallow
  copy of `accepted_patch_plan` or `None`.
- `_truncate_diagnostics_for_report(diagnostics)` - caps diagnostics at
  `MAX_ITEMS` and per-message `MAX_LENGTH` with trailing `"..."` marker.
- `_truncate_decisions_for_report(decisions)` - caps decisions at
  `MAX_ITEMS` with deep copies via `dict(...)` / `list(...)`.
- `_build_accepted_report_base_shape()` - canonical accepted base shape
  with `version`, `status: "accepted"`, `reconciliation_status: "accepted"`,
  `source_fidelity_effective_status: "reconciled_degraded"`,
  `playable_publication_candidate: True`, and empty `decisions`,
  `changed_files`, `validation_after_reconciliation`,
  `publishability_after_reconciliation`, `report_agreement_after_reconciliation`,
  `notes`, `diagnostics`.
- `_build_non_accepted_report_shape(status_value, diagnostics)` - same
  canonical shape but with `source_fidelity_effective_status: "blocked"`
  and `playable_publication_candidate: False`.

### Public helpers

- `build_accepted_final_reconciliation_report(orchestrator_result, brief)`
  - consumes the Step 4.3 orchestrator result and emits the compact
  report. Accepted path fills the report from the Step 4.2 accepted
  payload (`apply_result.changed_files`, compact `validation_after_reconciliation`
  summary, four-field `publishability_after_reconciliation`, two-field
  `report_agreement_after_reconciliation`) and the
  `accepted_patch_plan.decisions`. Non-dict orchestrator results fail
  closed with `invalid_orchestrator_result` and a `report_build_failed`
  diagnostic. Non-accepted dict results fail closed with `not_accepted`
  and a `not_accepted` diagnostic. Never mutates inputs, never raises.

- `persist_accepted_final_reconciliation_report(module_dir, orchestrator_result, brief)`
  - composes the build helper with the existing provider-free
  `utils.toolkit_final_reconciliation.persist_final_reconciliation_report`
  helper. Returns a stable 6-key shape
  `{status, path, report, error, diagnostics, bytes}`. Fail-closed
  contract: non-accepted orchestrator results and invalid inputs write
  NOTHING. Missing/empty `module_dir` returns `failed` with a
  `report_persist_failed` diagnostic. Persist-helper exceptions and
  non-`written` underlying statuses are surfaced via the same diagnostic.
  `Path` objects and strings are both accepted as `module_dir`.

### Latent bug fix (narrow, in Step 4.4 scope)

The Step 4.4 `persist_accepted_final_reconciliation_report` had
`del brief  # Reserved for future extension.` at the top, which left
the local name `brief` unbound before the inner
`build_accepted_final_reconciliation_report(orchestrator_result, brief)`
call, raising `UnboundLocalError` on every persist. The `del` is
replaced with a docstring-preserving comment so the brief is forwarded
verbatim to the build helper. The build helper explicitly ignores the
brief today; the parameter is reserved for Step 5. This is a narrow
fix scoped to the Step 4.4 persister; no retry behavior, packet
builder, finisher, or prompt was changed.

### Orchestrator shape (Step 4.3)

The Step 4.3 orchestrator was already producing the 9-key canonical
shape (the `accepted_patch_plan` field is the new Step 4.4 entry that
the report builder reads for `decisions`). The previous Step 4.3
evidence file said "8-key shape" by mistake; the implementation has
always emitted 9 keys. Step 4.4's test update
(`TestStep43OrchestratorOutputShape.test_top_level_shape_keys_are_stable`)
now pins the 9-key canonical shape with an inline comment that names
Step 4.4 as the owner of the `accepted_patch_plan` field.

## Test Changes (scripts/test_toolkit_llm_final_reconciliation.py)

### Step 4.3 shape test update

- `TestStep43OrchestratorOutputShape.test_top_level_shape_keys_are_stable`:
  expected key set expanded from 8 to 9 keys to include
  `accepted_patch_plan`. Inline comment names Step 4.4 as the owner.

### New test classes (35 new tests, all provider-free)

- `TestStep44Constants` (13 tests) - pins every Step 4.4 status name,
  diagnostic code, and bounded report knob.
- `TestStep44BuildAcceptedReport` (12 tests) - exercises
  `build_accepted_final_reconciliation_report`:
  - accepted report shape keys and values
  - accepted report passes the legacy `is_final_reconciliation_accepted`
    oracle
  - `decisions` list comes from the patch plan
  - `changed_files` list comes from the apply phase
  - `validation_after_reconciliation` carries the compact
    `{status, success_rate, passed, failed, error_count}` shape
  - `publishability_after_reconciliation` carries the four
    publishability fields verbatim from the gates payload
  - `report_agreement_after_reconciliation` carries
    `{status, playable_publication_status}` from the agreement
  - `source_fidelity_effective_status` is locked to `reconciled_degraded`
  - rejected orchestrator returns `not_accepted` report (legacy oracle rejects it)
  - non-dict inputs (None, str, int, list) all fail closed with
    `invalid_orchestrator_result` and a `report_build_failed` diagnostic
  - builder never mutates the orchestrator result or brief
- `TestStep44PersistAcceptedReport` (10 tests) - exercises
  `persist_accepted_final_reconciliation_report` against a unique
  tempdir per test (`_Step44TempModuleDirTestCase`):
  - accepted persist writes `final_reconciliation_report.json` and
    returns `status: "written"`, `path: <absolute path>`, `bytes: > 0`
  - on-disk file is byte-compatible with the legacy contract and
    passes `is_final_reconciliation_accepted`
  - persisted report includes the canonical 6-key set plus the
    6 spec-required fields
  - non-accepted orchestrator writes NOTHING (no file, status not
    `written`, `path: None`, `bytes: 0`)
  - invalid orchestrator writes NOTHING
  - missing/empty `module_dir` writes NOTHING with
    `report_persist_failed` diagnostic
  - `Path` objects are accepted alongside plain strings
  - persister never mutates the orchestrator result or brief

All 35 new tests pass with no live provider call and no real
`modules/<slug>/` artifact touched (each test uses a unique
`tempfile.mkdtemp()` module dir torn down in `tearDown`).

## Test Counts

| Step | Cumulative | Delta | Notes |
|------|-----------|-------|-------|
| 4.3 baseline | 484 | - | - |
| **4.4** | **519** | **+35** | 13 constants + 12 builder + 10 persister |

## Verification

- `.venv/bin/python -m py_compile utils/toolkit_llm_final_reconciliation.py scripts/test_toolkit_llm_final_reconciliation.py` -> PASS
- `.venv/bin/python -m unittest scripts.test_toolkit_llm_final_reconciliation -v` -> **519 PASS, 0 FAIL** in 0.075s
- `.venv/bin/python -m unittest scripts.test_toolkit_final_reconciliation scripts.test_toolkit_report_agreement scripts.test_windows_safe_file_operations scripts.test_file_operations_path_safety` -> **106/106 OK** in 0.086s (no regression in dependent suites)
- `python3 scripts/check_ascii_compliance.py utils/toolkit_llm_final_reconciliation.py scripts/test_toolkit_llm_final_reconciliation.py` -> `ASCII_CHECK scanned_files=2 files_with_violations=0 violations=0`
- `openspec validate toolkit-accurate-ingest-llm-builder-final-editor --strict` -> VALID

## Acceptance Oracle Pin

The Step 4.4 helper output passes the archived boundary's acceptance
oracle. The check is verified at three levels:

1. **Builder-only (in-memory):**
   `TestStep44BuildAcceptedReport.test_accepted_report_passes_legacy_acceptance_check`
   asserts that the dict returned by
   `build_accepted_final_reconciliation_report(accepted_result, brief)`
   returns `True` from the legacy
   `is_final_reconciliation_accepted(...)` oracle.

2. **Persister outcome (in-memory):**
   `TestStep44PersistAcceptedReport.test_persisted_report_passes_is_final_reconciliation_accepted`
   asserts that the `report` field of the persister outcome dict passes
   the same oracle.

3. **Persister on-disk (round-trip):**
   `TestStep44PersistAcceptedReport.test_accepted_persists_final_reconciliation_report_json`
   re-reads the just-written `final_reconciliation_report.json` from
   the temp module dir and confirms the round-tripped report passes the
   oracle too.

## Source-Fidelity Honesty

The built report's `source_fidelity_effective_status` is locked to
`reconciled_degraded` (per the archived boundary's contract). The
helper refuses to emit `pass` / `clean_pass` / `clean` /
`source_fidelity_pass` even if the LLM drifts to one of those values;
the Step 3.3 source-fidelity-claim validator already rejects those
variants upstream. The lock is verified by
`test_accepted_report_includes_source_fidelity_effective_status`.

## What Step 4.4 Does NOT Do (out of scope for this step)

- Does NOT integrate with the packet builder. Step 5.1 owns that.
- Does NOT call any provider. The helper consumes the Step 4.3
  orchestrator result directly.
- Does NOT touch `modules/<slug>/` directly. The persist helper writes
  to a caller-supplied `module_dir`; Step 5 will wire it to the real
  packet-builder path.
- Does NOT change retry behavior. Step 4.3 owns the bounded-retry
  orchestrator and Step 4.4 only consumes its result.
- Does NOT add new top-level shape keys to the orchestrator beyond
  `accepted_patch_plan`, which is the read-only handoff to the
  report builder.

## Follow-up

Step 5 (Packet Builder Integration) wires
`persist_accepted_final_reconciliation_report` into
`web/extensions/toolkit_homebrew_packet_builder.py` so accepted
reconciliation writes the report into the real module dir during the
packet-build flow. Step 6 (Well of Ruin and Safety Tests) adds
end-to-end regression coverage for the accepted path using a synthetic
Well of Ruin fixture.
