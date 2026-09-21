# Executor Prompts

## Implementation Boundary

Implement the LLM adaptation builder as a distinct build mode. Do not silently convert the existing accurate-ingest mode into adaptation mode without preserving an explicit legacy route.

## Required Reading

- `proposal.md`
- `design.md`
- All six files under `specs/`
- `tasks.md`
- `plans/adaptation-builder.md`
- `utils/toolkit_llm_final_reconciliation.py`
- `web/extensions/toolkit_homebrew_packet_builder.py`
- `web/extensions/toolkit_homebrew_readiness_gate.py`
- `web/extensions/toolkit_module_finisher.py`
- `utils/homebrewery_adventure_writer.py`
- `plans/version-2/world-narrative.md`

## Execution Rules

- The LLM may author adaptation content but may not directly write arbitrary live files.
- Python remains the authority for schema, mechanics, validation, reports, Markdown, registry, and campaign state.
- Build initial and revised candidates in staging or backup-safe targets.
- Treat source fidelity as provenance in adaptation mode, not as a publication veto.
- Keep semantic revision bounded and distinguish infrastructure failures from content failures.
- Use `.venv/bin/python` for tests and dependency-sensitive commands.
- Use atomic JSON operations and ASCII-only Python user-facing text.
- Do not commit, push, archive, or delete changes as part of task execution.

## Verification Output

For each task, report changed files, contract tests, staging/rollback evidence, publication-gate results, Markdown download evidence, and whether the legacy accurate-ingest route remains available.
