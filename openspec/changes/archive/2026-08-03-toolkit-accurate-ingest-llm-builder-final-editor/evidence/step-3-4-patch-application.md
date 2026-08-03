# Step 3.4 Evidence: Safe Patch Application

Date: 2026-06-12

## 1. Files Added

- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/evidence/step-3-4-patch-application.md` (this file)

## 2. Files Modified

- `utils/toolkit_llm_final_reconciliation.py` (~520 lines added: 3 new imports, 5 patch-op constants + allowed-ops tuple, 2 apply-status constants, 7 diagnostic codes, 5 pure helpers (`_parse_json_path`, `_resolve_parent`, `_apply_op`, plus 5 per-op helpers), and the public `apply_final_reconciliation_patch_plan` helper)
- `scripts/test_toolkit_llm_final_reconciliation.py` (~1100 lines added: 11 new symbol imports, 3 stdlib imports for the tempdir fixture, 4 fixture helpers, 1 base class with per-test tempdir setup/teardown, 7 new test classes with 77 tests)
- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/tasks.md` (Step 3.4 checked off with completion evidence)

## 3. Files Read (Context)

- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/proposal.md`
- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/design.md` (Decision 3: Patch application is Python-gated; "Guidance Layer: prefer validating the entire patch plan before applying the first write to avoid partial mutation.")
- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/tasks.md` (Step 1.x, 2.x, 3.1-3.3 evidence)
- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/specs/accurate-ingest-final-reconciliation-patch-contract/spec.md` (valid-patch-plan scenario; forbidden-target scenario)
- `prompts/toolkit/final_reconciliation_builder_prompt.txt` (lines 67-70: patch op allowlist; lines 71-86: forbidden targets and editable_surfaces contract; lines 87-91: source-fidelity honesty)
- `utils/file_operations.py` (`_is_valid_filepath`, `safe_read_json`, `safe_write_json`, `AtomicFileWriter.write_json` for atomic-lock + atomic-replace behavior)
- `utils/toolkit_llm_final_reconciliation.py` (Step 2.4/3.1/3.2/3.3 scaffold: `_parse_runner_response`, `validate_final_reconciliation_patch_contract`, `validate_final_reconciliation_patch_targets`, `validate_final_reconciliation_source_fidelity_claim`)
- `scripts/test_toolkit_llm_final_reconciliation.py` (Step 2.4/3.1/3.2/3.3 test scaffold and conventions)

## 4. Public Surface

### Constants (newly exported)

Patch op constants (single source of truth for the op allowlist):

- `FINAL_RECONCILIATION_PATCH_OP_REMOVE_KEY = "remove_key"`
- `FINAL_RECONCILIATION_PATCH_OP_RENAME_KEY = "rename_key"`
- `FINAL_RECONCILIATION_PATCH_OP_SET_VALUE = "set_value"`
- `FINAL_RECONCILIATION_PATCH_OP_REMOVE_ARRAY_ENTRY = "remove_array_entry"`
- `FINAL_RECONCILIATION_PATCH_OP_MERGE_INTO_EXISTING = "merge_into_existing"`
- `FINAL_RECONCILIATION_ALLOWED_PATCH_OPS` (tuple of the five ops in prompt-declared order)

Apply-status constants:

- `FINAL_RECONCILIATION_APPLY_STATUS_APPLIED = "applied"`
- `FINAL_RECONCILIATION_APPLY_STATUS_FAILED = "failed"`

Step 3.4 diagnostic codes:

- `DIAGNOSTIC_CODE_INVALID_PATCH_PLAN = "invalid_patch_plan"`
- `DIAGNOSTIC_CODE_INVALID_OP = "invalid_op"`
- `DIAGNOSTIC_CODE_INVALID_JSON_PATH = "invalid_json_path"`
- `DIAGNOSTIC_CODE_MISSING_MODULE_DIR = "missing_module_dir"`
- `DIAGNOSTIC_CODE_TARGET_FILE_READ_FAILED = "target_file_read_failed"`
- `DIAGNOSTIC_CODE_TARGET_FILE_WRITE_FAILED = "target_file_write_failed"`
- `DIAGNOSTIC_CODE_PATCH_APPLICATION_FAILED = "patch_application_failed"`

### Module-internal constants (not exported)

- `_INVALID_JSON_POINTER_ESCAPE_RE = re.compile(r"~[^01]")` - rejects `~` not followed by `0` or `1` (RFC 6901 violation).

### New helper functions

Pure, no mutation, no provider:

- `_parse_json_path(json_path) -> Optional[List[str]]` - parses an RFC 6901 JSON pointer subset (leading `/`, segments split on `/`, `~0`/`~1` decoded, invalid escapes rejected). Returns None on failure.
- `_resolve_parent(root, segments) -> (Optional[Any], Optional[Any], List[Dict[str, str]])` - walks `segments[:-1]` and returns `(parent_container, last_segment, diagnostics)`. Returns `(None, None, [diagnostic])` when an intermediate step fails.
- `_apply_op(content, op, segments, value) -> List[Dict[str, str]]` - dispatches a single op to the per-op helper. Returns a list of structured diagnostics (empty on success).
- `_apply_set_value_op(content, segments, value) -> List[Dict[str, str]]` - in-place set; allows new keys in dict parents.
- `_apply_remove_key_op(content, segments) -> List[Dict[str, str]]` - in-place remove; requires key to exist.
- `_apply_rename_key_op(content, segments, value) -> List[Dict[str, str]]` - in-place rename; requires old key to exist, new key to be a non-empty string, and destination not already present.
- `_apply_remove_array_entry_op(content, segments) -> List[Dict[str, str]]` - in-place remove; requires index in bounds.
- `_apply_merge_into_existing_op(content, segments, value) -> List[Dict[str, str]]` - shallow in-place merge via `dict.update`; target must be a dict and value must be a dict.

### New public function

- `apply_final_reconciliation_patch_plan(patch_plan, brief, module_dir=None) -> Dict[str, Any]` - the Step 3.4 public helper. Returns a dict with `status` (`applied`/`failed`), `changed_files` (list of relative target paths written), and `diagnostics` (list of structured `{"code", "message", "severity"}` dicts).

## 5. Behavior

### 4-phase pipeline contract

Phase 1: Validation (no writes)
1. `patch_plan` MUST be a dict
2. `brief` MUST be a dict
3. `patch_plan["status"]` MUST equal `ready`
4. `validate_final_reconciliation_patch_contract(patch_plan)` MUST return `is_valid=True`
5. `validate_final_reconciliation_patch_targets(patch_plan, brief)` MUST return `is_valid=True` (empty diagnostics)
6. `validate_final_reconciliation_source_fidelity_claim(patch_plan, brief)` MUST return `is_valid=True` (empty diagnostics on ready plan)

Phase 1b: Module-dir resolution
7. `effective_module_dir` is `module_dir` argument if not None, else `brief["module_dir"]`
8. `effective_module_dir` MUST be a non-empty string after `.strip()`

Phase 2: Load targets into memory (no writes)
9. Group `file_patches` by `target_file` (first-seen order, preserved)
10. For each unique target, call `safe_read_json(os.path.join(module_dir, target))` once
11. `None` from `safe_read_json` (missing or unreadable file) -> failed with `target_file_read_failed` diagnostic

Phase 3: Apply patches in memory (no writes)
12. For each file in first-seen order, dispatch every patch in declared order
13. Each patch is validated: op must be in allowed ops, json_path must parse, dispatch via `_apply_op`
14. Any per-op failure returns failed with structured diagnostic tagged with `[index] (target=..., op=..., path=...)`
15. No writes have occurred by the end of Phase 3

Phase 4: Write changed files (filesystem writes)
16. For each changed target, call `safe_write_json(full_path, in_memory_content)`
17. A write failure returns failed with `target_file_write_failed` diagnostic
18. Per the Step 3.4 spec, a write-phase failure on one file does NOT attempt rollback. Earlier files in the write phase MAY have already been written; this is documented as write-phase failure behavior.
19. The application phase itself (Phases 1-3) produced zero partial writes, so the in-memory changes that were applied cannot leak to disk for the failing file.

### Supported op behavior

- `set_value`: set value at `json_path`. Parent must be dict or list. For dict parents the last segment may name an existing key (overwrite) or a new key (insert); the segment is always treated as a string. For list parents the last segment must parse as a non-negative int that is in bounds.
- `remove_key`: delete object key at `json_path`. Parent must be dict; key must exist.
- `rename_key`: rename existing object key at `json_path` to `value` (the new key name). Parent must be dict; old key must exist; new key must be a non-empty string; destination must not already be present (fail-closed).
- `remove_array_entry`: remove array element at numeric index addressed by `json_path`. Parent must be list; index must parse as int and be in bounds.
- `merge_into_existing`: shallow merge dict `value` into dict at `json_path` via `dict.update`. Target must be dict; value must be dict. When both target and value carry a dict for the same key, the value's dict REPLACES the target's dict rather than recursing (documented as shallow-merge behavior).

### Return shape

```
{
  "status": "applied" | "failed",
  "changed_files": [<relative target path>, ...],   # always a fresh list
  "diagnostics": [{"code": <code>, "message": <msg>, "severity": <sev>}, ...]
}
```

### Input purity

The helper NEVER mutates the plan, brief, or module_dir inputs. The plan and brief are deepcopied in the purity test (`test_apply_does_not_mutate_inputs`) to lock this contract.

## 6. JSON pointer semantics

`_parse_json_path` implements the RFC 6901 subset used by the prompt:

- Paths must start with `/`
- `~0` decodes to `~`
- `~1` decodes to `/`
- Any other `~`-escape is rejected (invalid per RFC 6901)
- The single-character root path `/` is rejected (every op needs a parent container)
- Empty paths are rejected
- Non-strings are rejected

The path decoder intentionally does NOT support the `#` fragment or relative references. The LLM is contracted to emit absolute pointer paths per the prompt's HARD RULES item 7.

## 7. Test Coverage

- `TestPatchOpConstants` (7 tests) - pins each op constant value, the allowed-ops tuple order matching the prompt, and the apply-status constants.
- `TestJsonPathParsing` (9 tests) - simple / nested / array-index / escape-decoding paths; rejection of non-strings, empty strings, root-only `/`, non-pointer paths, and invalid escape sequences.
- `TestResolveParent` (8 tests) - walks into dict and list parents via int-segment, nested paths, and fail-closed rejections for missing dict keys, out-of-bounds indices, non-int indices, non-container traversal, and empty segments.
- `TestSetValueOp` (5 tests) - existing-key overwrite, new-key insert, array-index set, non-container parent failure, invalid array index failure.
- `TestRemoveKeyOp` (3 tests) - existing-key removal, missing-key failure, non-dict parent failure.
- `TestRenameKeyOp` (6 tests) - successful rename; failures for missing old key, non-string new key, empty new key, destination already present, non-dict parent.
- `TestRemoveArrayEntryOp` (4 tests) - index removal; failures for out-of-bounds index, non-int index, non-list parent.
- `TestMergeIntoExistingOp` (5 tests) - shallow merge into existing dict; failures for non-dict target, non-dict value, non-dict parent; shallow-merge non-recursion pinned.
- `TestApplyFinalReconciliationPatchPlan` (30 tests):
  - Per-op happy path: `test_apply_set_value_happy_path`, `test_apply_remove_key_happy_path`, `test_apply_rename_key_happy_path`, `test_apply_remove_array_entry_happy_path`, `test_apply_merge_into_existing_happy_path`
  - Multi-patch and multi-file: `test_apply_multiple_patches_to_same_file`, `test_apply_patches_to_two_separate_files`, `test_apply_empty_file_patches_returns_applied_with_no_changes`
  - Plan-level validation failures that write nothing: `test_apply_fails_when_plan_status_is_refused`, `test_apply_fails_when_plan_status_is_failed`, `test_apply_fails_on_contract_violation`, `test_apply_fails_on_target_violation`, `test_apply_fails_on_source_fidelity_violation`
  - Module-dir resolution: `test_apply_fails_when_module_dir_missing_from_brief`, `test_apply_fails_when_module_dir_is_empty_string`, `test_apply_uses_brief_module_dir_when_arg_none`, `test_apply_uses_arg_module_dir_over_brief`
  - File I/O failures: `test_apply_fails_on_missing_target_file`, `test_apply_fails_on_corrupt_target_file`
  - Per-op input validation: `test_apply_fails_on_invalid_op_writes_nothing`, `test_apply_fails_on_invalid_json_path_writes_nothing`, `test_apply_fails_on_missing_json_path_field_writes_nothing`
  - In-memory application phase failures: `test_apply_later_patch_failure_writes_nothing_to_any_file`, `test_apply_failure_preserves_earlier_in_memory_changes`
  - Write-phase failure: `test_apply_returns_failed_when_safe_write_json_fails` (mocks `safe_write_json` to return False on the second file)
  - Purity: `test_apply_does_not_mutate_inputs`, `test_apply_rejects_non_dict_patch_plan`, `test_apply_rejects_non_dict_brief`
  - Entry-shape rejections: `test_apply_rejects_non_dict_file_patch_entry`, `test_apply_rejects_non_string_target_file`

## 8. Verification

- `.venv/bin/python -m py_compile utils/toolkit_llm_final_reconciliation.py scripts/test_toolkit_llm_final_reconciliation.py` -> PASS
- `.venv/bin/python -m unittest scripts.test_toolkit_llm_final_reconciliation -v` -> **307 PASS, 0 FAIL** in 0.028s (was 230, +77)
- `.venv/bin/python -m unittest scripts.test_toolkit_final_reconciliation scripts.test_toolkit_report_agreement scripts.test_windows_safe_file_operations scripts.test_file_operations_path_safety` -> **106/106 OK** in 0.092s (no regression in dependent suites)
- `python3 scripts/check_ascii_compliance.py utils/toolkit_llm_final_reconciliation.py scripts/test_toolkit_llm_final_reconciliation.py` -> `ASCII_CHECK scanned_files=2 files_with_violations=0 violations=0`
- `openspec validate toolkit-accurate-ingest-llm-builder-final-editor --strict` -> VALID
- `openspec validate --specs` -> 364/364 PASS (no spec regression)

## 9. Scope Confirmation

- No live provider call in tests: confirmed (mock_provider_output short-circuit; all 307 tests pass without network).
- No packet-builder integration: confirmed (no edits to `web/extensions/toolkit_homebrew_packet_builder.py` or any other packet-builder file in this step).
- No schema validation after write: confirmed (Step 3.5 is reserved for that; this step uses only `safe_read_json`/`safe_write_json` for I/O).
- No readiness/publishability/report-agreement gates: confirmed (no call to readiness/publishability helpers; Section 4 is reserved).
- No report persistence: confirmed (no call to `persist_final_reconciliation_report(...)`; Step 4.4 is reserved).
- No live filesystem leak in tests: confirmed (every `TestApplyFinalReconciliationPatchPlan` test uses `_TempModuleDirTestCase` which creates a unique tempdir in `setUp` and removes it in `tearDown`).
- ASCII-only: confirmed (0 violations across both files).
- No mutation of inputs: confirmed (purity test `test_apply_does_not_mutate_inputs` deepcopies the plan and brief before the call and asserts equality after).
- Whole-plan validation before any write: confirmed (Phases 1-3 produce zero writes; only Phase 4 calls `safe_write_json`).
- No partial writes from the application phase: confirmed (`test_apply_later_patch_failure_writes_nothing_to_any_file` asserts the on-disk file is unchanged after an in-memory application phase failure on patch index 1).
