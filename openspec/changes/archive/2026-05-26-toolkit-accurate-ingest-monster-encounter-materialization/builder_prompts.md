# Builder Prompts: Accurate-Ingest Monster Encounter Materialization

## Step 1.1 Builder Prompt (full variant)

Implement OpenSpec `toolkit-accurate-ingest-monster-encounter-materialization` Step 1.1 only.

Goal: Add provider-free tests that define the source monster materialization helper input/output contract using temp module fixtures and source monster refs.

Allowed files:

- `scripts/test_accurate_ingest_monster_materialization.py` (new preferred test file)
- `utils/accurate_ingest_monster_materialization.py` (minimal import-safe Step 1.1 stub only)
- Existing accurate-ingest test helpers only if needed for fixture setup
- `openspec/changes/toolkit-accurate-ingest-monster-encounter-materialization/tasks.md` only to mark Step 1.1 complete after tests are in place

Forbidden:

- Do not implement production materialization logic yet except for tiny import-safe stubs if required to make tests importable.
- Do not mutate `modules/The_Hidden_City_of_Numillian/**`.
- Do not run a production Numillian rebuild.
- Do not call LLM providers, ModuleBuilder live generation, seed writer builds, benchmark refresh, publishability refresh, or MMG/media generation.
- Do not change benchmark thresholds, benchmark fixture data, or scanner logic.
- Do not weaken validation, readiness, source-fidelity, build-fidelity, or publishability gates.

Required MUSTs:

- Tests SHALL be provider-free and deterministic.
- Tests SHALL use temp directories or isolated fixture data for module artifact writes.
- Tests SHALL define the expected helper contract for source monster refs: materialized/reused refs, unresolved refs, status, counts, and artifact paths.
- Tests SHALL include at least one unambiguous reusable monster-style ref and one unresolved odd source ref.
- Tests SHALL assert NPC-like/source-character names are not promoted to monsters without monster/combatant evidence.
- Tests SHALL assert no-source input returns pass/skipped/no-op without false blockers.

SHOULD guidance:

- Prefer test names that document behavior, for example `test_unambiguous_source_monster_ref_materializes_or_reports_reused`, `test_unresolved_source_monster_ref_is_not_silently_dropped`, and `test_no_source_refs_is_noop_compatible`.
- If an implementation stub is necessary, keep it minimal and clearly marked as a placeholder for Step 1.2.
- Use ASCII-only fixture names and output strings.
- Prefer assertions on report shape over exact prose wording.

Edit Strategy: Apply one anchored patch at a time, then run py_compile before the next patch. Do not use broad regex/script rewrites in indentation-sensitive files.

Verify:

- `.venv/bin/python -m py_compile scripts/test_accurate_ingest_monster_materialization.py`
- `.venv/bin/python -m py_compile utils/accurate_ingest_monster_materialization.py`
- `.venv/bin/python -m unittest -q scripts.test_accurate_ingest_monster_materialization`
- `openspec validate toolkit-accurate-ingest-monster-encounter-materialization`

Report:

- Files changed
- Test cases added and what contract each locks
- Commands run and results
- Any blockers or deviations

Stop: Do not implement Step 1.2 or production materialization behavior.

## Verification Gate After Builder Reports

- Confirm only allowed files changed.
- Confirm tests are provider-free and use temp fixtures.
- Confirm no production module artifacts changed.
- Confirm `openspec validate toolkit-accurate-ingest-monster-encounter-materialization` passes.

Next step after PASS: Step 1.2, implement the narrow helper/stub to satisfy the contract without broad report integration.
