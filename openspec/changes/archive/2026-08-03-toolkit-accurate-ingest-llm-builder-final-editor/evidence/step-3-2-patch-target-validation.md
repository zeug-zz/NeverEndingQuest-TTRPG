# Step 3.2 Evidence: Final Reconciliation Patch Target Validation

Date: 2026-06-11

## 1. Files Added

- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/evidence/step-3-2-patch-target-validation.md` (this file)

## 2. Files Modified

- `utils/toolkit_llm_final_reconciliation.py` (~280 lines added: 2 new imports `fnmatch` and `posixpath`, 3 new diagnostic codes, 2 forbidden-pattern tuples, 1 carve-out constant, 6 pure helper functions, 1 main `validate_final_reconciliation_patch_targets` helper, 1 runner wiring helper `_apply_target_validation_to_runner_status`, and 2 call-site updates in `run_llm_final_editor`)
- `scripts/test_toolkit_llm_final_reconciliation.py` (~640 lines added: 12 new imports, 2 new fixtures `_ready_plan_with_target` and `_brief_with_surfaces`, 3 new test classes `TestTargetValidationHelpers` (21 tests), `TestValidateFinalReconciliationPatchTargets` (45 tests), `TestRunnerTargetValidationWiring` (9 tests))
- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/tasks.md` (Step 3.2 checked off with completion evidence)

## 3. Files Read (Context)

- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/proposal.md`
- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/design.md`
- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/tasks.md` (Step 1.x, 2.x, 3.1 evidence)
- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/specs/accurate-ingest-final-reconciliation-patch-contract/spec.md`
- `prompts/toolkit/final_reconciliation_builder_prompt.txt` (line 67-70: `target_file` field; line 71-84: forbidden targets; line 85-86: editable_surfaces whitelist)
- `utils/toolkit_final_reconciliation.py` (`editable_surfaces` defaults, `DEFAULT_EDITABLE_SURFACES` list)
- `utils/toolkit_llm_final_reconciliation.py` (Step 2.4 runner scaffold, Step 3.1 contract helper, parse wiring)
- `scripts/test_toolkit_llm_final_reconciliation.py` (Step 2.4 / 3.1 test scaffold)

## 4. Public Surface

### Constants (newly exported)

- `DIAGNOSTIC_CODE_FORBIDDEN_PATCH_TARGET = "forbidden_patch_target"`
- `DIAGNOSTIC_CODE_INVALID_PATCH_TARGET = "invalid_patch_target"`
- `DIAGNOSTIC_CODE_EDITABLE_SURFACES_MISSING = "editable_surfaces_missing"`

### Module-internal constants (not exported)

- `_FORBIDDEN_RUNTIME_TARGET_PATTERNS` (tuple of 6 patterns):
  exact: `module_plot.json`, `party_tracker.json`, `modules/world_registry.json`, `modules/campaign.json`
  glob: `player_quests_*.json`
  prefix: `encounters/`
- `_FORBIDDEN_SOURCE_MIDDLE_PATTERNS` (tuple of 7 patterns):
  exact: `source_graph.json`, `source_manifest.json`, `normalized_packet.json`, `MODULE_SUMMARY.md`
  glob: `blueprint_*.json`
  prefix: `accurate_ingest_audit_run/`, `agent_runs/`
- `_FORBIDDEN_AREAS_BASENAME_MUST_NOT_END_WITH = "_BU.json"` (carve-out for `areas/*.json`)

### New helper functions

Pure, no mutation, no filesystem, no provider:

- `_has_backslash(target)` -> bool
- `_is_absolute_path(target)` -> bool (POSIX `/`, Windows drive `^[A-Za-z]:`)
- `_has_path_traversal(target)` -> bool (segment-level `..` check)
- `_matches_forbidden_pattern(target, pattern)` -> bool (exact / glob `*` / directory prefix `/`)
- `_is_forbidden_target(target)` -> bool (runtime-only + source/middle + areas carve-out)
- `_target_matches_editable_surface(target, surface)` -> bool (exact / directory prefix / `fnmatch` glob)
- `validate_final_reconciliation_patch_targets(patch_plan, brief) -> (bool, diagnostics)` - main helper
- `_apply_target_validation_to_runner_status(parser_status, parser_diagnostics, patch_plan, brief) -> (status, diagnostics)` - runner wiring helper

## 5. Behavior

### Validation rules (in declared order)

1. `patch_plan` MUST be a `dict`. A non-dict plan is rejected with a single `invalid_patch_target` diagnostic.
2. `brief` MUST be a `dict`. A non-dict brief is rejected with a single `invalid_patch_target` diagnostic.
3. If `file_patches` is not a list, the helper returns `(True, [])` so the contract helper's shape error (Step 3.1) can be reported by its own diagnostic code without a confusing duplicate.
4. If `file_patches` is empty, the helper returns `(True, [])` WITHOUT requiring `editable_surfaces`. This preserves the Step 3.1 behavior for plans that legitimately emit zero patches.
5. If `file_patches` is non-empty, `brief["editable_surfaces"]` MUST be a non-empty list of non-empty strings. A missing / wrong-type / non-string-item / empty whitelist fails closed with a single `editable_surfaces_missing` diagnostic.
6. For each entry, the helper checks (in order):
   - entry MUST be a `dict`
   - `target_file` MUST be present and a string
   - the trimmed target MUST NOT be empty (and rejects whitespace-only)
   - the target MUST NOT contain a backslash (cross-platform safer)
   - the target MUST NOT be an absolute path (`/x`, `C:`, `C:\x`, `C:/x`, `z:bar`)
   - the target MUST NOT contain a `..` path component
   - the target MUST NOT be a runtime-only or source/middle forbidden pattern
   - the target MUST match at least one entry in `editable_surfaces` (exact, directory-prefix, or `fnmatch` glob)

Every violation is reported in a single pass. The helper never short-circuits on the first violation so callers can surface every target issue at once.

### Forbidden target lists

Runtime-only (rejected regardless of whitelist):
- `module_plot.json` (live state)
- `party_tracker.json` (live state)
- `player_quests_*.json` (live state, glob)
- `encounters/` (any path under encounters/)
- `modules/world_registry.json` (campaign state)
- `modules/campaign.json` (campaign state)
- `areas/*.json` unless basename ends with `_BU.json` (carve-out for canonical backups)

Source/middle pipeline artifacts (rejected regardless of whitelist):
- `source_graph.json` (source extraction artifact)
- `source_manifest.json` (source extraction artifact)
- `normalized_packet.json` (middle pipeline artifact)
- `blueprint_*.json` (middle pipeline artifact, glob)
- `accurate_ingest_audit_run/` (any path under audit run dir)
- `agent_runs/` (any path under agent runs dir)
- `MODULE_SUMMARY.md` (downstream prose, not source of truth)

### Editable_surfaces match forms

Brief whitelist entries support three match forms:

- **Exact**: `target == surface`
- **Directory prefix**: `surface.endswith("/")` and `target.startswith(surface)` (e.g. `areas/`)
- **Glob**: `fnmatch.fnmatch(target, surface)` (e.g. `areas/*_BU.json`, `map_*.json`)

### Runner wiring

- Mock-provider path and live-provider path both call `_apply_target_validation_to_runner_status(...)` after `_parse_runner_response(...)`.
- For `ready` plans: target failure escalates status to `RUNNER_STATUS_INVALID_PATCH_CONTRACT` and appends the target diagnostics.
- For `refused` / `failed` plans: target failure preserves the original status (mirrors Step 3.1 semantics) and appends the target diagnostics.
- For early-failure statuses (invalid_json / missing_required_keys / invalid_brief / provider_failed / param_resolution_failed): target validation is skipped because there is no usable patch plan.
- The legacy `error` field is recomputed via `_build_error_message_for_status(...)` and continues to use the `invalid_patch_contract` aggregation format from Step 3.1.

### Step 3.1 behavior preserved

- Empty `file_patches` does not require `editable_surfaces`.
- Non-list `file_patches` is owned by the contract helper; target validation returns success so the contract helper can emit its own `invalid_file_patches` diagnostic without a confusing duplicate.
- The existing Step 3.1 test `test_file_patches_path_contents_pass_in_step_3_1_step_3_2_will_reject` continues to pass unchanged.

## 6. Verification

- `.venv/bin/python -m py_compile utils/toolkit_llm_final_reconciliation.py scripts/test_toolkit_llm_final_reconciliation.py` -> PASS
- `.venv/bin/python -m unittest scripts.test_toolkit_llm_final_reconciliation -v` -> **185 PASS, 0 FAIL** in 0.009s
- `.venv/bin/python -m unittest scripts.test_toolkit_final_reconciliation scripts.test_windows_safe_file_operations scripts.test_file_operations_path_safety` -> **74/74 OK** in 0.079s (Step 1.4 regression set, no regression)
- `python3 scripts/check_ascii_compliance.py utils/toolkit_llm_final_reconciliation.py scripts/test_toolkit_llm_final_reconciliation.py` -> `ASCII_CHECK scanned_files=2 files_with_violations=0 violations=0`
- `openspec validate toolkit-accurate-ingest-llm-builder-final-editor --strict` -> VALID
- `openspec validate --specs` -> 364/364 PASS (no spec regression)

## 7. Scope Confirmation

- No live provider call in any test (all runner tests use `mock_provider_output=...`).
- No packet-builder / finisher integration (this step is pure helper + runner wiring).
- No source-fidelity claim validation (owned by Step 3.3).
- No patch application / write (owned by Step 3.4).
- No changed-JSON validation (owned by Step 3.5).
- No filesystem reads or writes from the helper or the runner wiring helper.
- No mutating callers' `patch_plan` or `brief` inputs.
- ASCII-only source: 0 violations across both files.

## 8. Test Counts

Baseline (Step 3.1): 110 tests
New tests in Step 3.2:
- `TestTargetValidationHelpers` (21 tests)
- `TestValidateFinalReconciliationPatchTargets` (45 tests)
- `TestRunnerTargetValidationWiring` (9 tests)
Step 3.2 total: **185 tests** (+75)
All pass with no live provider call.
