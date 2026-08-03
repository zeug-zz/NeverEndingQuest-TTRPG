# Step 1.3 Evidence - Path/Lock Safety Fix

**Date:** 2026-06-11
**Step:** 1.3 - Fix the lock/path safety bug in the smallest safe location
**Status:** COMPLETED

## Files Changed

- `utils/file_operations.py` (production fix)
- `scripts/test_file_operations_path_safety.py` (minimal test alignment)
- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/tasks.md` (mark complete)

## Production Fix Summary

### 1. New validation helper (`utils/file_operations.py`)

Added `_is_valid_filepath(filepath)` that accepts:

- `os.PathLike` values (e.g. `pathlib.Path`).
- `str` values that are NOT serialized JSON dict / list payloads.
- `None` is rejected.
- Non-path payloads (`dict`, `list`, `tuple`, `set`, `int`, `float`, `bool`, `bytes`,
  and any other non-str / non-PathLike) are rejected.
- Strings beginning with `{` or `[` that also parse as JSON dict / list are rejected
  (proving the spec contract: serialized-JSON strings must not be used verbatim as
  lock / temp paths).

### 2. `AtomicFileWriter.write_json` updated

Now calls `_is_valid_filepath(filepath)` BEFORE `str(filepath)` and BEFORE any
`lock_path` / `temp_path` construction. On rejection it logs a structured `ERROR`
and returns `False` without raising through `safe_write_json`.

This guarantees the spec's "no lock/temp path may be built from payload content"
contract: rejection happens before `acquire_lock` (which would have called
`os.open`) and before `open(temp_path, 'w', ...)` would have been called.

### 3. Scope kept minimal

- `read_json` was NOT changed. Spec covers writes only; the bug class
  (`[Errno 63] File name too long`) is specific to write lock / temp paths.
- `acquire_lock` / `release_lock` were NOT changed. They are called only
  after `write_json` validated the path, so the lock path derivation test
  (`TestAtomicWriterLockPathDerivation`) continues to pass.
- Valid callers (relative / absolute / `Path` / `os.PathLike`) remain
  compatible - `_is_valid_filepath` returns `True` for them and
  `str(filepath)` then handles `Path` -> `str` conversion as before.

## Test Alignment

The Step 1.2 tests in `TestSafeWriteJsonRejectsPayloadAsFilepath` previously
asserted `len(captured) > 0` so that they could compare payload markers against
the captured path. After the production fix, the helper short-circuits
BEFORE any `os.open` / `builtins.open` call, so no path is captured.

The minimal change in `_assert_no_payload_markers_in_captured` accepts BOTH:

1. **Outcome 1 (safer, what the production fix delivers)**: helper rejects
   non-path input before any `os.open` / `builtins.open` call, so `captured`
   is empty. This is the spec's preferred outcome.
2. **Outcome 2 (still valid)**: helper falls through to lock/temp path
   construction. Every captured path must still be free of payload markers
   and bounded to `< 255` chars.

The spec explicitly allows this update:
> "If your fix rejects before any `os.open` / `open` call, update those tests
> minimally so zero captured paths is accepted as the safer outcome."

No other test bodies, assertions, or contract semantics were changed.

## Verification

```
.venv/bin/python -m py_compile utils/file_operations.py scripts/test_file_operations_path_safety.py
```
-> PASS

```
.venv/bin/python -m unittest scripts.test_file_operations_path_safety -v
```
-> 9 PASS, 0 FAIL

```
.venv/bin/python -m unittest scripts.test_toolkit_final_reconciliation scripts.test_windows_safe_file_operations
```
-> 65 PASS, 0 FAIL (no regression)

```
openspec validate toolkit-accurate-ingest-llm-builder-final-editor
```
-> VALID

## Sample Log Output (Confirms Safer Outcome)

From the dict-as-filepath regression test (Step 1.2 `TestSafeWriteJsonRejectsPayloadAsFilepath.test_dict_as_filepath_does_not_produce_payload_lock_or_temp_path`):

```
ERROR:utils.file_operations:Refusing to write JSON: filepath argument is not a valid path (type=dict). This usually means a payload was passed where a file path was expected.
```

- No `os.open` call was made.
- No `builtins.open` call was made.
- No `*.lock` or `*.tmp` paths were constructed.
- `[Errno 63] File name too long` is unreachable from this code path.

The list-as-filepath and serialized-JSON-string-as-filepath variants produce
analogous rejections (only the `type=...` field differs).

## No Unrelated Production Files Changed

`git diff --stat` confirms only the three intended files were modified:
- `utils/file_operations.py`
- `scripts/test_file_operations_path_safety.py`
- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/tasks.md`

No module artifacts, source graph, normalized packet, blueprint, backstage
audit, or archived artifacts were touched. No public persistence semantics
for valid str / Path / PathLike inputs were changed.
