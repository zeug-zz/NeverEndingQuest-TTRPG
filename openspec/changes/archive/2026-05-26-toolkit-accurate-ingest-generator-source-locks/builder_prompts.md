# Builder Prompts: Accurate-Ingest Generator Source Locks

## Step 1.1 Builder Prompt (full variant)

```text
Implement OpenSpec `toolkit-accurate-ingest-generator-source-locks` Step 1.1 only.

Goal: Add provider-free regression tests proving source-enhanced `builder_input` includes `source_monster_refs` and `source_encounter_seeds` when the normalized packet contains those fields. This is a test-first step. Do not implement production extraction in this step.

Allowed files:
- `scripts/test_toolkit_homebrew_gui_unified_flow.py`
- `openspec/changes/toolkit-accurate-ingest-generator-source-locks/tasks.md` only to record Step 1.1 result after tests are added
- `openspec/changes/toolkit-accurate-ingest-generator-source-locks/builder_prompts.md` only if you need to append a short execution note

Forbidden files and behavior:
- Do not edit `web/extensions/toolkit_homebrew_packet_builder.py` in this step.
- Do not edit `core/generators/*` in this step.
- Do not modify Numillian module artifacts under `modules/The_Hidden_City_of_Numillian/`.
- Do not modify benchmark fixtures, benchmark runner logic, build-fidelity scanner logic, or source-fidelity thresholds.
- Do not call OpenAI, OpenRouter, or any live provider.
- Do not commit, push, or run destructive git commands.

Required implementation contract:
1. Add one or more deterministic tests near the existing accurate-ingest v2 packet builder integration tests.
2. The tests MUST construct or patch a v2 workspace/packet fixture containing:
   - `monster_refs`, including representative Numillian source terms such as `Alhoon`, `Illithid`, `Homunculus`, `Kenku`, `Nothic`, and `Charion`.
   - `encounter_seeds`, including source-derived text for the skull riddle trial, flooding room puzzle, dog test, and mindscape battle/attackers.
3. The tests MUST route through the source-enhanced ModuleBuilder path, not seed writer mode.
4. The tests MUST patch `_execute_module_builder(...)` so no live LLM or real build runs.
5. The tests MUST capture the `builder_input` argument passed to `_execute_module_builder(...)` or read the persisted `builder_input.json` from the temp workspace.
6. The tests MUST assert that `builder_input` includes:
   - `source_monster_refs` as a list containing the representative monster refs.
   - `source_encounter_seeds` as a list containing representative encounter seed text.
7. The tests MUST assert no leakage into legacy/non-source path if there is already a legacy-path test nearby; otherwise add a narrow assertion to an existing legacy-path test that source monster/encounter fields are absent when source-blueprint handoff is disabled.
8. Because this is test-first, the new test may fail before Step 1.2 implements extraction. If it fails, the failure MUST be specifically because `source_monster_refs` and/or `source_encounter_seeds` are absent, not because of fixture setup, provider calls, or unrelated exceptions.

MUST constraints from specs:
- Source-enhanced builder input SHALL preserve source monster references and encounter seeds when present in normalized packet or source blueprint artifacts.
- Tests SHALL be deterministic and provider-free.
- This change SHALL NOT require generation of `monsters/*.json` files.
- Legacy concept builds SHALL remain functional without source-specific fields.

SHOULD guidance:
- Prefer extending existing fixture helpers in `scripts/test_toolkit_homebrew_gui_unified_flow.py` rather than introducing a new test module.
- Keep fixture content compact and source-derived; do not paste full Numillian source text.
- Name tests clearly, for example `test_handoff_includes_source_monster_refs_and_encounter_seeds`.

Edit Strategy: Apply one anchored patch at a time, then run py_compile before the next patch. Do not use broad regex/script rewrites in indentation-sensitive files.

Verification commands:
1. `.venv/bin/python -m py_compile scripts/test_toolkit_homebrew_gui_unified_flow.py`
2. `.venv/bin/python -m unittest -q scripts.test_toolkit_homebrew_gui_unified_flow`
3. `openspec validate toolkit-accurate-ingest-generator-source-locks`

Expected verification outcome for this test-first step:
- `py_compile` MUST pass.
- `openspec validate` MUST pass.
- The targeted unittest may fail if production extraction is not yet implemented. If it fails, the failure MUST be the expected missing-field assertion for `source_monster_refs` / `source_encounter_seeds` only.

Required report format:
- Files changed.
- Tests added, with exact test names.
- Commands run and pass/fail results.
- If the unittest fails, quote the exact assertion failure and confirm it is the intended Step 1.2 implementation target.
- Confirm no production code, module artifacts, benchmark fixtures, or git state were modified.

Stop condition:
- Stop after Step 1.1 tests are added and verification evidence is reported. Do not implement Step 1.2 extraction.
```

## Verification Gate After Step 1.1

- [ ] Test file compiles.
- [ ] New tests are provider-free and source-contract focused.
- [ ] Failure, if any, is the intended missing-field failure.
- [ ] OpenSpec validates.
- [ ] No production code or module artifacts modified.

## Next Step Ready

After Step 1.1 is verified, proceed to Step 1.2: implement minimal extraction of monster refs and encounter seeds into `builder_input` without leaking into legacy/non-source paths.
