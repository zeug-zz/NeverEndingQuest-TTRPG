# Step 1.2 Regression Coverage Evidence: Path-Safety Lock/Errno 63 Class

Date: 2026-06-11
Scope: Test-first regression coverage for the `[Errno 63] File name too long`
class that surfaces when `safe_write_json` (and the underlying
`AtomicFileWriter`) is called with a non-path payload (dict / list /
serialized JSON string) where a file path is expected.

## 1. What Was Added

- New test file: `scripts/test_file_operations_path_safety.py`
- 4 test classes, 9 tests total
- ASCII-only test names and messages
- All tests are provider-free and do not require live services
- No production code modified in this step

### Test Classes

| Class | Tests | Purpose |
|---|---|---|
| `TestSafeWriteJsonRejectsPayloadAsFilepath` | 3 | **Expected red.** Proves `safe_write_json` MUST NOT construct a lock or temp path containing `str(payload)` markers when a dict / list / serialized JSON string is passed as the filepath. |
| `TestAtomicWriterLockPathDerivation` | 1 | Sanity: `acquire_lock` passes `filepath + '.lock'` to `os.open` and nothing else, for valid string filepaths. |
| `TestAtomicWriterTempPathDerivation` | 1 | Sanity: `write_json` opens `filepath + '.tmp'` and nothing else, for valid string filepaths. |
| `TestNormalFinalReconciliationPersistUnaffected` | 4 | Sanity: `persist_final_reconciliation_brief`, `persist_final_reconciliation_report`, and `safe_write_json` continue to succeed with valid `(workspace_dir, payload)` and `(str_path, data)` / `(Path, data)` usage. |

### Contract Tested

- **Payload-as-path is rejected safely.** A dict / list / serialized-JSON
  string passed where a file path is expected MUST NOT be interpolated
  into a lock or temp file name. The captured `os.open` and
  `builtins.open` path arguments MUST NOT contain any `str(payload)`
  marker (e.g. dict keys like `'a'`, list items like `item_0`, or JSON
  fragments like `{"large": "zzz...`) and MUST be bounded to < 255 chars.
- **Normal reconciliation persistence still works.** Valid
  `(workspace_dir, payload)` callers continue to write artifacts
  successfully.
- **Lock/temp path derivation is correct for string filepaths.** The
  helper appends only `'.lock'` or `'.tmp'` to the filepath; nothing
  else.

## 2. Test Run Results

```
$ .venv/bin/python -m unittest scripts.test_file_operations_path_safety -v

test_dict_as_filepath_does_not_produce_payload_lock_or_temp_path ... FAIL
test_list_as_filepath_does_not_produce_payload_lock_or_temp_path ... FAIL
test_serialized_json_string_as_filepath_does_not_produce_payload_lock_or_temp_path ... FAIL
test_lock_path_is_filepath_plus_lock_suffix ... ok
test_temp_path_is_filepath_plus_tmp_suffix ... ok
test_persist_brief_with_valid_workspace_succeeds ... ok
test_persist_report_with_valid_workspace_succeeds ... ok
test_safe_write_json_with_valid_string_path_succeeds ... ok
test_safe_write_json_with_valid_path_object_succeeds ... ok
----------------------------------------------------------------------
Ran 9 tests in 0.061s
FAILED (failures=3)
```

The 3 FAIL tests are the **expected red** regression that proves the
bug class exists. They will pass after Step 1.3 applies the production
fix in `utils/file_operations.py` (or the affected call site) to
validate the filepath argument before constructing any lock or temp
file name.

The 6 OK tests are sanity coverage that locks in the existing correct
behavior for string and `Path` filepaths and for the
`persist_final_reconciliation_brief` / `persist_final_reconciliation_report`
artifact write paths.

## 3. Sample Failure (Expected Red)

The first FAIL test produces this assertion, which directly
demonstrates the bug:

```
AssertionError: "'a'" unexpectedly found in
"{'a': 'xxx...', 'b': 'yyy...'}.lock" :
os.open received path containing payload marker "'a'":
"{'a': 'xxx...'"
```

The captured `lock_path` is the result of `str(dict)` being
concatenated with `".lock"`. With a payload of
`{"a": "x" * 200, "b": "y" * 200}`, `str(dict)` is 418 chars and the
resulting `lock_path` is 423 chars. On macOS HFS+ and many other
filesystems, the typical 255-character file name limit would trigger
`[Errno 63] File name too long` when the helper tries to
`os.open(lock_path, O_CREAT | O_EXCL | O_WRONLY)`.

## 4. Why This Is Test-First, Not A Fix

The Step 1.2 task explicitly forbids:
- Editing production code in this step
- Fixing `utils/file_operations.py` or any write-call implementation
- Implementing Step 1.3 or later

The 3 FAIL tests are intentional. They establish the contract:
*after Step 1.3, these tests must pass; if they do not, the production
fix did not actually close the bug class.*

The 6 OK tests are the guardrail: *if any of them fail after the
production fix is applied, the fix has regressed valid usage.*

## 5. No OS-Specific Path Limits Required

None of the tests depend on macOS HFS+ or Linux ext4 255-char name
limits. All 3 FAIL tests assert:

- No captured `os.open` / `builtins.open` path contains a substring
  that would be present in `str(payload)` (e.g. dict keys, list items,
  JSON fragments).
- No captured path is >= 255 chars.

These are contract-level assertions. They work the same on any OS and
on any filesystem.

## 6. ASCII Compliance

```
$ python3 scripts/check_ascii_compliance.py scripts/test_file_operations_path_safety.py

ASCII_CHECK scanned_files=1 files_with_violations=0 violations=0 fixed_files=0 fixed_chars=0
```

## 7. No Production Code Changed

`git status` on this step shows only the new test file and the
`tasks.md` update:

```
scripts/test_file_operations_path_safety.py | +370  (new file)
openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/tasks.md | evidence block added
```

No source code in `utils/`, `core/`, `web/`, `scripts/test_*.py`
(existing) was modified. No module artifacts, source graph,
normalized packet, blueprint, backstage audit, or archived boundary
artifacts were touched.

## 8. Verification Commands

```
.venv/bin/python -m py_compile scripts/test_file_operations_path_safety.py
    -> PASS

.venv/bin/python -m unittest scripts.test_file_operations_path_safety -v
    -> 6 PASS, 3 expected-red FAIL

.venv/bin/python -m unittest scripts.test_toolkit_final_reconciliation scripts.test_windows_safe_file_operations
    -> 65 PASS, 0 FAIL (no existing test broadened or changed)

openspec validate toolkit-accurate-ingest-llm-builder-final-editor
    -> VALID

python3 scripts/check_ascii_compliance.py scripts/test_file_operations_path_safety.py
    -> 0 violations
```

## 9. Step 1.2 Status

- [x] 1.2 Regression coverage added (this step)
- [ ] 1.3 Production fix (next step, will turn the 3 FAIL tests green)
- [ ] 1.4 Verify existing provider-free boundary tests still pass after
      the safety fix (depends on 1.3)
