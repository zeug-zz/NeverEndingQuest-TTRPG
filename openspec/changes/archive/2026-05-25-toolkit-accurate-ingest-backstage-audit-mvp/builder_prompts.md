# Builder Prompts: Accurate-Ingest Backstage Audit MVP

## Step 1.1 Builder Prompt (full variant)

Implement OpenSpec `toolkit-accurate-ingest-backstage-audit-mvp` Step 1.1 only.

Goal: Add deterministic artifact discovery/parsing helpers and tests for read-only accurate-ingest audit inputs.

Allowed files:

- `utils/accurate_ingest_backstage_audit.py` (new)
- `scripts/test_accurate_ingest_backstage_audit.py` (new)
- `openspec/changes/toolkit-accurate-ingest-backstage-audit-mvp/tasks.md` (mark Step 1.1 complete only if verification passes)

Forbidden:

- Do not edit `modules/The_Hidden_City_of_Numillian/**` or any module artifact.
- Do not edit benchmark fixtures, `scripts/benchmark_accurate_ingest.py`, `scripts/audit_module_publishability.py`, `web/extensions/toolkit_homebrew_packet_builder.py`, ModuleBuilder/generator files, seed writer files, or finisher files.
- Do not add CLI execution, subprocess calls, LLM/provider calls, report refresh behavior, waivers, or runtime artifact writing in this step.
- Do not create `core/agents/backstage/` yet; shared harness extraction is out of scope.

Required MUSTs:

- Add a small helper module that can discover expected accurate-ingest audit input artifacts for a supplied module directory.
- Expected artifact keys SHALL include at least: `accurate_ingest_benchmark_report`, `toolkit_build_report`, `validation_report`, `source_fidelity_report`, and `build_fidelity_report`.
- Artifact discovery SHALL be read-only. It SHALL NOT create, modify, delete, normalize, or refresh any module files.
- Each discovered artifact summary SHALL include: artifact key, path, exists boolean, parse status (`ok`, `missing`, `invalid_json`, or equivalent), compact status fields, and a content hash for existing files where practical.
- JSON parsing SHALL fail open per artifact: corrupt optional JSON produces an evidence summary with parse failure, not a raised exception that aborts all discovery.
- Missing module directory SHALL be represented as a clear failure from the top-level collection helper; do not create the directory.
- Large raw report bodies SHALL NOT be embedded in returned summaries. Include compact status fields only.
- Tests SHALL prove read-only behavior by hashing or snapshotting fixture files before/after helper execution.

SHOULD guidance:

- Prefer dataclass-free simple dictionaries unless dataclasses materially improve clarity.
- Prefer pure Python standard library only: `json`, `hashlib`, `pathlib`, `datetime` if needed.
- Keep helper names explicit, for example `collect_accurate_ingest_audit_inputs(module_dir)` and `summarize_report_artifact(path, key)`.
- Compact status extraction SHOULD recognize common fields: `status`, `ready_status`, `publishable_status`, `source_fidelity_status`, `effective_publishable_status`, `summary`, and `error`.
- Tests SHOULD use `tempfile.TemporaryDirectory()` and small synthetic JSON files instead of production module files.

Acceptance matrix:

| Case | Expected outcome |
|---|---|
| All reports present and valid | All artifact summaries parse with `ok`, hashes present, compact statuses extracted. |
| Optional report missing | Summary exists with `exists=false` and parse status `missing`; collection continues. |
| Corrupt JSON report | Summary has parse status `invalid_json`, error text, hash if file exists; collection continues. |
| Missing module directory | Top-level result reports failed/missing module and does not create files. |
| Read-only safety | Fixture file hashes unchanged before/after helper call. |

Edit Strategy: Apply one anchored patch at a time, then run py_compile before the next patch. Do not use broad regex/script rewrites in indentation-sensitive files.

Verify:

```bash
.venv/bin/python -m py_compile utils/accurate_ingest_backstage_audit.py scripts/test_accurate_ingest_backstage_audit.py
.venv/bin/python -m unittest -q scripts.test_accurate_ingest_backstage_audit
openspec validate toolkit-accurate-ingest-backstage-audit-mvp
```

Report:

- Files changed
- Helper functions added
- Tests added and what cases they cover
- Commands run and exact results
- Any blockers or deviations

Stop: Do not implement CLI entrypoint, command execution, runtime output writing, report grouping, or recommendation generation. Those are later steps.

## Verification Gate After Builder Reports

- Compile command passes.
- Targeted unit test passes.
- `openspec validate toolkit-accurate-ingest-backstage-audit-mvp` passes.
- Diff touches only allowed files.
- No module artifacts modified.

## Next Step Ready

If Step 1.1 passes, proceed to Step 1.2: domain finding/report-disagreement builder.
