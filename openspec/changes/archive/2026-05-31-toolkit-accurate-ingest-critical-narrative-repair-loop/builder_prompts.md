# Builder Prompts: Accurate-Ingest Critical Narrative Repair Loop

## Step 1.1 Builder Prompt (full variant)

Implement OpenSpec `toolkit-accurate-ingest-critical-narrative-repair-loop` Step 1.1 only.

Goal: Add or extend deterministic inspection that compares critical source narrative requirements against live module JSON, with Numillian as the first proof case.

Allowed files:

- A new or existing utility under `utils/` for critical omission evidence.
- A new or existing script under `scripts/` for running the evidence pass.
- A new or existing test module under `scripts/test_*.py`.
- `openspec/changes/toolkit-accurate-ingest-critical-narrative-repair-loop/tasks.md` only to mark Step 1.1 complete after verification.

Forbidden:

- Do not manually patch `modules/The_Hidden_City_of_Numillian/**` to add Kobe or `skull_riddle`.
- Do not edit benchmark fixtures, benchmark scanner thresholds, validation gates, or publishability gates.
- Do not use `MODULE_SUMMARY.md` as source-fidelity repair input.
- Do not run provider/LLM Builder calls in this step.
- Do not commit or push.

Required MUSTs:

- The evidence pass SHALL read the source markdown and final live module JSON.
- It SHALL detect Kobe as a missing critical prose actor when she appears in final trial objective/failure prose but is absent from NPC/scene surfaces.
- It SHALL detect `skull_riddle` as a missing critical puzzle when the source contains the first skull trial but final plot/puzzle surfaces do not preserve it.
- It SHALL include bounded source excerpts or source references sufficient for a later Builder repair brief.
- It SHALL classify the issue as evidence for Builder repair, not as a Python/manual patch instruction.
- It SHALL be deterministic and provider-free.

SHOULD guidance:

- Prefer a data shape like `{module_slug, critical_omissions: [...], source_refs: [...], target_surfaces: [...]}`.
- Prefer reusable helpers over a one-off Numillian-only script, but Numillian-specific expectations may be used in tests.
- Keep source excerpts compact and ASCII-safe when printed.

Edit Strategy: Apply one anchored patch at a time. For each touched Python file, run `.venv/bin/python -m py_compile <file>` before the next patch. Do not use broad regex/script rewrites in indentation-sensitive files.

Verify:

- `.venv/bin/python -m py_compile <modified-python-files>`
- `.venv/bin/python -m unittest -q <new-or-modified-test-module>`
- Run the new evidence script/entrypoint against `The_Hidden_City_of_Numillian` and print a compact summary proving Kobe and `skull_riddle` are detected as critical omissions.
- `openspec validate toolkit-accurate-ingest-critical-narrative-repair-loop`

Report:

- Files changed.
- Command outputs and statuses.
- The compact omission summary for Kobe and `skull_riddle`.
- Confirmation that no module JSON was repaired or manually patched.

Stop: Do not start Step 1.2, repair brief generation, or Builder repair integration.

## Verification Gate After Builder Reports

- Confirm the evidence pass is deterministic and provider-free.
- Confirm Kobe and `skull_riddle` are detected from source/live JSON mismatch.
- Confirm no module artifacts were manually repaired.
- Confirm tests cover the current Numillian failure mode.

Next step after PASS: Step 1.2, capture Numillian evidence including source excerpts and missing output surfaces.
