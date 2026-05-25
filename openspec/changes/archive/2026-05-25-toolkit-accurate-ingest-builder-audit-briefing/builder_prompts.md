# Builder Prompts

## Step 1.1 Builder Prompt (full variant)

Implement OpenSpec `toolkit-accurate-ingest-builder-audit-briefing` Step 1.1 only.

Goal: Add an audit-run artifact loader and task identity validator for existing backstage audit run directories.

Allowed files:

- `scripts/prepare_builder_from_backstage_audit.py`
- `scripts/test_builder_audit_briefing.py`
- `openspec/changes/toolkit-accurate-ingest-builder-audit-briefing/tasks.md`

Forbidden:

- Do not edit `modules/**`.
- Do not edit existing backstage audit implementation files unless a test exposes an unavoidable import/contract bug.
- Do not call LLM providers, ModuleBuilder, seed writer, benchmark refresh, publishability refresh, readiness repair, media generation, or module finishing.
- Do not write `builder_brief.json` or `builder_prompt_context.md` yet; those are Step 2.
- Do not implement lane classification yet; that is Step 3.1.

Required MUSTs:

- Create a narrow script module that can load a provided audit run directory containing `run.json`, `evidence.json`, `audit_report.json`, and `recommendation.json`.
- Add a helper such as `load_audit_run_artifacts(run_dir: Path) -> dict` that parses the four JSON files and returns a structured dict.
- Add validation that fails clearly when any required artifact is missing.
- Add validation that `run.json.task_id`, `audit_report.json.task_id`, and `recommendation.json.task_id` match.
- Include artifact source paths in returned metadata.
- Keep this read-only: loading and validation must not write any files.

SHOULD guidance:

- Prefer pure helper functions in the script so later steps can reuse them.
- Use explicit exception messages rather than broad `Exception` swallowing.
- Keep JSON parsing compact; no full report body copying beyond loading the existing artifacts.

Edit Strategy: Apply one anchored patch at a time, then run py_compile before the next patch. Do not use broad regex/script rewrites in indentation-sensitive files.

Tests to add:

- Valid temp audit run loads all four artifacts.
- Missing artifact raises a clear missing-artifact error and writes nothing.
- Task ID mismatch raises a clear task-identity error and writes nothing.
- Returned metadata includes artifact paths.

Verification:

```bash
.venv/bin/python -m py_compile scripts/prepare_builder_from_backstage_audit.py scripts/test_builder_audit_briefing.py
.venv/bin/python -m unittest -q scripts.test_builder_audit_briefing
openspec validate toolkit-accurate-ingest-builder-audit-briefing
```

After verification:

- Mark Step 1.1 complete in `tasks.md` with exact evidence.
- Stop. Do not proceed to Step 1.2.

Report:

- Files changed
- Commands run
- Test results
- Any blockers or deviations
