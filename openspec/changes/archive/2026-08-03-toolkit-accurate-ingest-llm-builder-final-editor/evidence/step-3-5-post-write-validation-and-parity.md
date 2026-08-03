# Step 3.5 Evidence: Post-Write JSON Parse Validation and BU/Live Parity

Date: 2026-06-12

## 1. Files Added

- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/evidence/step-3-5-post-write-validation-and-parity.md` (this file)

## 2. Files Modified

- `utils/toolkit_llm_final_reconciliation.py`
  - 2 new diagnostic codes: `DIAGNOSTIC_CODE_WRITTEN_JSON_INVALID` and `DIAGNOSTIC_CODE_PARITY_COUNTERPART_WRITE_FAILED`.
  - 3 new pure helpers: `_compute_parity_counterpart(target)`, `_should_mirror_parity_write(counterpart, module_dir, editable_surfaces)`, `_validate_written_json(full_path, target)`.
  - 1 new module-internal constant: `_PARITY_BASENAMES` (frozenset pinning the canonical `module_context.json` <-> `module_context_BU.json` pair).
  - Modified `apply_final_reconciliation_patch_plan(...)` Phase 4 to: (a) re-open and parse every just-written file via `safe_read_json`; (b) when the parse fails, return failed with a `written_json_invalid` diagnostic; (c) when the just-written target is one side of a canonical static authored pair, mirror the same post-patch content to the counterpart when it already exists in the module dir OR is explicitly listed in `editable_surfaces`; (d) when the parity mirror write fails, return failed with a `parity_counterpart_write_failed` diagnostic; (e) when the parity mirror's post-write parse fails, return failed with a `written_json_invalid` diagnostic; (f) the mirror is skipped when both sides of a pair are in the patch plan (the second pass writes the counterpart in its own iteration).
  - Updated the public helper's docstring to document the new Step 3.5 behavior in Phase 4.
- `scripts/test_toolkit_llm_final_reconciliation.py`
  - 3 new import names: `DIAGNOSTIC_CODE_PARITY_COUNTERPART_WRITE_FAILED`, `DIAGNOSTIC_CODE_WRITTEN_JSON_INVALID`, plus helpers `_compute_parity_counterpart`, `_should_mirror_parity_write`, `_validate_written_json`.
  - 4 existing tests updated to pin `editable_surfaces` to the target only (so the new parity mirror does not incidentally fire and complicate the existing happy-path assertions): `test_apply_set_value_happy_path`, `test_apply_remove_key_happy_path`, `test_apply_rename_key_happy_path`, `test_apply_multiple_patches_to_same_file`. Each updated test now passes `editable_surfaces=["module_context.json"]` (or `["module_context_BU.json"]`) explicitly to scope the test to a single target.
  - 4 new test classes with 33 new tests (see Section 7 below).
- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/tasks.md` (Step 3.5 checked off with completion evidence)

## 3. Files Read (Context)

- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/proposal.md`
- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/design.md` (line 79 "Allowed target surfaces" listing canonical pairs; Decision 3 "Patch application is Python-gated")
- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/tasks.md` (Steps 1-3.4 evidence; Step 3.5 task spec)
- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/specs/accurate-ingest-final-reconciliation-patch-contract/spec.md`
- `AGENTS.md` "Module Publication Git Contract" (lines 388-409: canonical vs runtime file families; `map_*.json` is canonical static authored structure; `areas/*.json` and `module_plot.json` are runtime-only)
- `utils/toolkit_llm_final_reconciliation.py` (Step 3.4 apply helper, target/contract/source-fidelity validators, existing JSON path parser, existing `_target_matches_editable_surface` helper)
- `scripts/test_toolkit_llm_final_reconciliation.py` (Step 3.4 apply-helper test scaffold and conventions)
- `utils/file_operations.py` (`safe_read_json` for post-write re-read; `safe_write_json` semantics)

## 4. Public Surface

### Constants (newly exported)

Step 3.5 diagnostic codes:

- `DIAGNOSTIC_CODE_WRITTEN_JSON_INVALID = "written_json_invalid"` - emitted when a just-written file cannot be re-read as JSON.
- `DIAGNOSTIC_CODE_PARITY_COUNTERPART_WRITE_FAILED = "parity_counterpart_write_failed"` - emitted when the parity mirror's `safe_write_json` returns False.

### Module-internal constants (not exported)

- `_PARITY_BASENAMES = frozenset({"module_context.json", "module_context_BU.json"})` - source of truth for the canonical `module_context` parity pair.

### New helper functions

Pure, no mutation, no provider:

- `_compute_parity_counterpart(target) -> Optional[str]` - given a relative target path, returns the canonical parity counterpart or `None` when no parity rule applies. Supports `module_context.json` <-> `module_context_BU.json` and `map_<base>.json` <-> `map_<base>_BU.json`. Deliberately returns `None` for `areas/FOO_BU.json` (would map to runtime-only `areas/FOO.json`) and `module_plot_BU.json` (would map to runtime-only `module_plot.json`). Preserves directory prefix when present.
- `_should_mirror_parity_write(counterpart, module_dir, editable_surfaces) -> bool` - returns `True` when the counterpart already exists in the module directory OR is explicitly listed in `editable_surfaces` (exact, directory-prefix, or glob form, reusing the existing `_target_matches_editable_surface` helper from Step 3.2).
- `_validate_written_json(full_path, target) -> List[Dict[str, str]]` - re-opens a just-written file via `safe_read_json` and returns an empty list on success or a single `written_json_invalid` diagnostic on failure. This is JSON parse validation only (per the Step 3.5 task spec); schema validation is owned by Step 4.1.

### Modified public function

- `apply_final_reconciliation_patch_plan(patch_plan, brief, module_dir=None) -> Dict[str, Any]` - Phase 4 extended with two new guarantees after every successful `safe_write_json`:
  1. Post-write JSON parse validation: the just-written file is re-opened; parse failure surfaces a `written_json_invalid` diagnostic. The target is NOT added to `written_files` on parse failure.
  2. BU/live parity mirror: when the just-written target is one side of a canonical static authored pair, the same post-patch content is mirrored to the counterpart when applicable. The mirror itself is subject to the same post-write JSON parse validation.

## 5. Behavior

### Post-write JSON parse validation (Phase 4 step 1)

- Runs after every successful `safe_write_json` call (both for the main target and for the parity mirror).
- Re-opens the file via `safe_read_json`. Returns `None` on parse failure.
- On parse failure: returns `{"status": "failed", "changed_files": [...already-written files...], "diagnostics": [written_json_invalid diagnostic]}`.
- On success: continues to the next iteration (parity mirror or next target).
- The target is NOT added to `written_files` on parse failure, signaling the file is in an inconsistent state.

### BU/live parity mirror (Phase 4 step 2)

Mirroring rules (locked in `_compute_parity_counterpart`):

| Target | Counterpart |
| --- | --- |
| `module_context.json` | `module_context_BU.json` |
| `module_context_BU.json` | `module_context.json` |
| `map_<base>.json` | `map_<base>_BU.json` |
| `map_<base>_BU.json` | `map_<base>.json` |
| `areas/FOO_BU.json` | `None` (no mirror; live area is runtime) |
| `module_plot_BU.json` | `None` (no mirror; live plot is runtime) |
| anything else | `None` |

Mirror applicability check (in `_should_mirror_parity_write`):

- Counterpart already exists in the module directory (`os.path.isfile(...)`) -> mirror.
- Counterpart is explicitly listed in `editable_surfaces` (exact, directory-prefix, or glob form) -> mirror.
- Otherwise -> no mirror.

Mirror execution semantics:

- The same `target_contents[target]` in-memory content is written to the counterpart via `safe_write_json`.
- The counterpart path uses the same `os.path.join(effective_module_dir, counterpart)` derivation, so the path-safety rules from Step 1.3 apply.
- A mirror write failure surfaces `parity_counterpart_write_failed`.
- A mirror post-write parse failure surfaces `written_json_invalid`.
- The mirror is SKIPPED when both sides of a pair are in the patch plan (`if counterpart in changed_targets: continue`) so the second pass writes the counterpart in its own iteration with its own patches.
- Successful mirror writes include the counterpart in `changed_files`.

### Why these specific pair rules

The AGENTS.md "Module Publication Git Contract" (lines 388-409) defines the canonical vs runtime file families:

- `module_context.json` and `module_context_BU.json` are both canonical/publication artifacts.
- `map_*.json` is static authored structure (not runtime state); `map_*_BU.json` is also canonical.
- `areas/*.json` (except `*_BU.json`) is runtime-only and was rejected by the Step 3.2 target validator.
- `module_plot.json` is runtime-only and was rejected by the Step 3.2 target validator.

The mirror ONLY fires for the first two pairs (where both sides are canonical). The latter two pairs are deliberately excluded so a final-editor run cannot accidentally write to runtime-only files. This matches the task spec's "Do NOT mirror" rules.

## 6. Return Shape

`apply_final_reconciliation_patch_plan(...)` return shape is preserved:

```
{
  "status": "applied" | "failed",
  "changed_files": [<relative target path>, ...],
  "diagnostics": [{"code": <code>, "message": <msg>, "severity": <sev>}, ...]
}
```

The `changed_files` list is now a fresh list that includes:

- The original targets that were successfully written and passed post-write validation.
- Any parity mirror counterparts that were successfully written and passed post-write validation.

Inputs (patch_plan, brief, module_dir) are never mutated. The in-memory content is written to the parity counterpart as a COPY (the same `target_contents[target]` reference is used; the counterpart file is re-opened by `safe_write_json`'s atomic write).

## 7. Test Coverage

New tests added in 4 new test classes (33 tests total, all provider-free):

- `TestComputeParityCounterpart` (11 tests) - pins the parity counterpart for `module_context.json` <-> `module_context_BU.json`, `map_FOO.json` <-> `map_FOO_BU.json`, `map_atlus.json` round-trip, runtime-only `areas/FOO_BU.json` returns `None`, `module_plot_BU.json` returns `None`, `module_plot.json` returns `None`, unrelated targets return `None`, non-string inputs return `None`, empty string returns `None`.
- `TestShouldMirrorParityWrite` (7 tests) - uses a per-test tempdir; pins existence-on-disk behavior, in-editable-surfaces behavior, glob match, absent-and-not-listed, invalid inputs return `False`, non-list `editable_surfaces` does not raise, non-string items in the list are skipped but valid strings still match.
- `TestValidateWrittenJson` (4 tests) - uses a per-test tempdir; valid JSON returns empty diagnostics, corrupt JSON returns diagnostic, missing file returns diagnostic, invalid full_path returns diagnostic.
- `TestPostWriteValidationAndParity` (11 tests, all extend `_TempModuleDirTestCase`):
  - `test_apply_post_write_json_parse_validation_succeeds` - valid write passes validation.
  - `test_apply_fails_on_written_json_invalid_post_write` - mock `safe_write_json` to write garbage; result is failed with `written_json_invalid`.
  - `test_apply_mirrors_module_context_to_module_context_BU` - both files updated.
  - `test_apply_mirrors_module_context_BU_to_module_context` - reverse direction.
  - `test_apply_mirrors_map_FOO_to_map_FOO_BU` - both map files updated.
  - `test_apply_mirrors_map_FOO_BU_to_map_FOO` - reverse map direction.
  - `test_apply_does_not_mirror_bu_area_to_live_area` - `areas/FOO_BU.json` patch does NOT create `areas/FOO.json`.
  - `test_apply_does_not_mirror_bu_plot_to_live_plot` - `module_plot_BU.json` patch does NOT create `module_plot.json`.
  - `test_apply_fails_on_parity_counterpart_write_failure` - first write succeeds, mirror write returns `False`, result is failed with `parity_counterpart_write_failed`.
  - `test_apply_fails_on_parity_counterpart_invalid_post_write` - first write succeeds with valid JSON, mirror write returns `True` but writes garbage, result is failed with `written_json_invalid`.
  - `test_apply_skips_parity_mirror_when_both_sides_in_plan` - both `module_context.json` and `module_context_BU.json` in plan; no double-write; each file updated to its own value.

Existing tests updated to keep the parity mirror from incidentally firing (4 tests, all extending `_TempModuleDirTestCase`):

- `test_apply_set_value_happy_path`, `test_apply_remove_key_happy_path`, `test_apply_rename_key_happy_path`, `test_apply_multiple_patches_to_same_file` - each now passes `editable_surfaces=["module_context.json"]` (or `["module_context_BU.json"]`) explicitly to scope the test to a single target. The existing assertion `result["changed_files"] == ["module_context.json"]` (or `["module_context_BU.json"]`) is preserved.

## 8. Verification

- `.venv/bin/python -m py_compile utils/toolkit_llm_final_reconciliation.py scripts/test_toolkit_llm_final_reconciliation.py` -> PASS
- `.venv/bin/python -m unittest scripts.test_toolkit_llm_final_reconciliation -v` -> **340 PASS, 0 FAIL** in 0.040s (was 307; +33 new tests; 4 existing tests updated to pin editable_surfaces for parity)
- `.venv/bin/python -m unittest scripts.test_toolkit_final_reconciliation scripts.test_toolkit_report_agreement scripts.test_windows_safe_file_operations scripts.test_file_operations_path_safety` -> **106/106 OK** in 0.097s (no regression in dependent suites)
- `python3 scripts/check_ascii_compliance.py utils/toolkit_llm_final_reconciliation.py scripts/test_toolkit_llm_final_reconciliation.py` -> `ASCII_CHECK scanned_files=2 files_with_violations=0 violations=0`
- `openspec validate toolkit-accurate-ingest-llm-builder-final-editor --strict` -> VALID
- `openspec validate --specs` -> 364/364 PASS (no spec regression)

## 9. Scope Confirmation

- No live provider call in tests: confirmed (all 33 new tests are provider-free; `safe_write_json` and `safe_read_json` are mocked where needed).
- No packet-builder integration: confirmed (no edits to `web/extensions/toolkit_homebrew_packet_builder.py` or any other packet-builder file in this step).
- No schema validation: confirmed (Step 4.1 is reserved for module schema validation; this step uses only `safe_read_json` for JSON parse validation).
- No readiness/publishability/report-agreement gates: confirmed (no call to readiness/publishability helpers; Section 4 is reserved).
- No report persistence: confirmed (no call to `persist_final_reconciliation_report(...)`; Step 4.4 is reserved).
- No live filesystem leak in tests: confirmed (every new test uses `tempfile.mkdtemp` in `setUp` and `shutil.rmtree` in `tearDown`).
- ASCII-only: confirmed (0 violations across both files).
- No mutation of inputs: confirmed (the parity mirror uses the same in-memory `target_contents[target]` reference; the helper does not modify `patch_plan`, `brief`, or `module_dir`).
- Parity mirror scope: confirmed (`module_context.json` <-> `module_context_BU.json` and `map_<base>.json` <-> `map_<base>_BU.json` only; runtime-only `areas/*.json` and `module_plot.json` excluded).
- Path-safety rules: confirmed (counterpart path uses `os.path.join(effective_module_dir, counterpart)`; no traversal; no absolute paths).
