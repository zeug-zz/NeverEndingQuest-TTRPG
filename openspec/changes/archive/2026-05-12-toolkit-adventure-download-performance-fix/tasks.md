## 1. Serve Pre-Generated File

- [x] 1.1 Rewrite `get_module_adventure_markdown()` in `web/web_interface.py`: check `modules/<slug>/MODULE_SUMMARY.md` first; if exists and size >500 bytes, read and return directly with Content-Type + Content-Disposition headers
- [x] 1.2 If no pre-generated file (or file too short), fall back to `generate_homebrewery_adventure(slug)`, write result to `MODULE_SUMMARY.md`, then return
- [x] 1.3 Preserve existing 404 and 500 error handling from current endpoint
- [x] 1.4 Verify: `python3 -m py_compile web/web_interface.py` -> PASS

## 2. Button Loading State

- [x] 2.1 In `downloadAdventure()` in `module_toolkit.html`: capture button reference, set `textContent = 'Generating...'` + `disabled = true` before fetch
- [x] 2.2 In `finally` block (or both success/error paths): restore `textContent = 'Download Adventure'` + `disabled = false`
- [x] 2.3 Verify: `node --check` on extracted JS -> PASS

## 3. Smoke Verification

- [x] 3.1 Verify `modules/The_Ancients_Lab/MODULE_SUMMARY.md` exists on disk (>80KB)
- [x] 3.2 Verify `modules/The_Thornwood_Watch/MODULE_SUMMARY.md` exists on disk
- [x] 3.3 Verify `modules/The_Hidden_City_of_Numillian/MODULE_SUMMARY.md` exists on disk
- [x] 3.4 Verify 52 existing tests still PASS: `.venv/bin/python -m unittest scripts.test_homebrewery_adventure_writer -v`
- [x] 3.5 Verify `openspec validate toolkit-adventure-download-performance-fix` -> VALID
