# Builder Prompts: Accurate-Ingest Numillian Release-Proof Finalization

## Step 1.1 Builder Prompt (full variant)

Implement OpenSpec `toolkit-accurate-ingest-numillian-release-proof-finalization` Step 1.1 only.

Goal: Produce a diagnostic-only current-state report for Numillian finalization blockers without mutating module artifacts.

Allowed files:

- `openspec/changes/toolkit-accurate-ingest-numillian-release-proof-finalization/tasks.md` only to mark Step 1.1 complete after diagnostics are captured.
- A new diagnostic note under `plans/` only if needed, preferably `plans/accurate-ingest-numillian-release-proof-diagnostics.md`.

Forbidden:

- Do not edit `modules/The_Hidden_City_of_Numillian/**`.
- Do not edit `data/benchmarks/**`.
- Do not edit benchmark scanner logic, validation scripts, publishability scripts, or source-fidelity gates.
- Do not run ModuleBuilder, provider calls, MMG/media generation, or production rebuilds.
- Do not create waivers.
- Do not commit or push.

Required MUSTs:

- Run the current validation, benchmark, and publishability commands for `The_Hidden_City_of_Numillian`.
- Inspect whether `modules/The_Hidden_City_of_Numillian/monsters/` exists and whether source monster refs have module-local artifacts.
- Identify exact publishability blockers and classify them as semantic, monster materialization, report freshness, or publication-only.
- Confirm source-fidelity categories remain pass or report any regression.
- The diagnostic output SHALL be evidence-backed with command names and observed statuses.
- The step SHALL NOT mutate production module artifacts.

SHOULD guidance:

- Use context-mode execution for commands that may emit long JSON.
- Summarize JSON outputs programmatically instead of pasting full raw reports.
- Prefer a compact diagnostic markdown note if the findings are too long for a builder report.

Edit Strategy: Apply one anchored patch at a time. Do not use broad regex/script rewrites in indentation-sensitive files.

Verify:

- `.venv/bin/python core/validation/validate_module_files.py --module The_Hidden_City_of_Numillian`
- `.venv/bin/python scripts/benchmark_accurate_ingest.py --module The_Hidden_City_of_Numillian --json`
- `.venv/bin/python scripts/audit_module_publishability.py --module The_Hidden_City_of_Numillian --json`
- `openspec validate toolkit-accurate-ingest-numillian-release-proof-finalization`

Report:

- Commands run and exit codes
- Current statuses: validation, benchmark/source-fidelity, publishability, toolkit report if inspected
- Exact blockers by class
- Files changed, if any
- Recommended next patch target

Stop: Do not start Step 2.1 or modify module artifacts.

## Verification Gate After Builder Reports

- Confirm no production module artifacts changed.
- Confirm blockers are exact and evidence-backed.
- Confirm source-fidelity pass state was not regressed.
- Confirm the next patch target is narrow.

Next step after PASS: Step 2.1, close semantic blocker phrases with the smallest source-faithful module artifact patch.
