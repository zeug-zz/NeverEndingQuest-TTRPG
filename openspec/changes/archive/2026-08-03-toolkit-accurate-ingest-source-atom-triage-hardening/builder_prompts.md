# Builder Prompts

This file follows `openspec-plan-to-builder` full-tier prompt style. Use one step at a time; after each builder report, verify before emitting the next prompt.

---

**Step 1.1 Builder Prompt** (full variant)

Implement OpenSpec `toolkit-accurate-ingest-source-atom-triage-hardening` Step 1.1 only.

Goal: Add provider-free regression tests reproducing the Well-style false NPC atom class before production changes.

Allowed files:

- `scripts/test_source_atom_triage_hardening.py` (new)
- If needed only for imports/fixture reuse, read existing files but do not edit production code.

Forbidden:

- Do not modify `utils/toolkit_source_manifest.py`, `utils/toolkit_entity_candidate_triage.py`, `utils/toolkit_builder_blueprint.py`, or `utils/toolkit_final_reconciliation.py` in this step.
- Do not call live LLM providers.
- Do not mutate production module artifacts.
- Do not weaken existing tests or thresholds.

Required:

- Create an inline synthetic markdown fixture with a trap/effect table that includes these false NPC terms: `level 11-16 Complex Trap, Deadly`, `Well`, `Ruin`, `Awaken`, `Menace`, `Enrage`, `Enthrall`, `Irradiate`, `Overwhelm`, plus at least two full effect sentences including `Mundane objects worth at least 1 gp become sentient and hostile.`
- Add tests that run existing production helpers where possible: `build_source_manifest(...)`, `build_source_graph(...)`, `_extract_entity_candidates(...)`, and/or downstream triage/blueprint helpers.
- Add at least one test that currently demonstrates the false-positive class, e.g. one or more false terms appear as NPC/entity candidates or produce required NPC roster candidates.
- Add a true-positive fixture with identity-bearing table headers and real NPC names such as `Wayne`, `Irene Laughing-Eyes`, and `Treever`; assert these names remain extractable.
- Mark expected-red tests clearly in method names or docstrings if they fail before Step 2/3 production fixes.

Constraints:

- Tests must be provider-free, deterministic, ASCII-only, and tempdir-backed if they write files.
- Use `.venv/bin/python` for verification.
- Keep helper functions in the test file unless a production helper is required by later steps.

Edit Strategy: Apply one anchored patch at a time, then run compile/tests before reporting.

Verify:

- `.venv/bin/python -m py_compile scripts/test_source_atom_triage_hardening.py`
- `.venv/bin/python -m unittest scripts.test_source_atom_triage_hardening -v`
- `python3 scripts/check_ascii_compliance.py scripts/test_source_atom_triage_hardening.py`
- `openspec validate toolkit-accurate-ingest-source-atom-triage-hardening --strict`

Output:

- Report test classes and test count.
- Identify which tests are expected red before production fixes.
- Confirm no production files were changed.

**Verification Gate (after builder reports):**

- [ ] New test file compiles.
- [ ] Tests reproduce false-positive class or document expected-red behavior.
- [ ] True NPC fixture preserves table-based NPC extraction.
- [ ] No production code touched.
- [ ] OpenSpec validates strictly.

**Next Step Ready:** Step 1.2 / Step 1.3 test expansion, then Step 2.1 source manifest helper implementation.

---

**Step 2.1-2.3 Builder Prompt** (full variant)

Implement OpenSpec `toolkit-accurate-ingest-source-atom-triage-hardening` Steps 2.1 through 2.3 only, after Step 1 tests are reviewed.

Goal: Harden `utils/toolkit_source_manifest.py` so effect/result/description table cells do not become NPC candidates while identity-bearing table cells still do.

Allowed files:

- `utils/toolkit_source_manifest.py`
- `scripts/test_source_atom_triage_hardening.py`
- `scripts/test_accurate_ingest_source_graph.py` only if existing tests require narrowly updated expectations.

Forbidden:

- Do not change blueprint, final-editor, or packet-builder code in this step.
- Do not add exact Well-only string exclusions as the primary implementation.
- Do not lower existing Numillian source graph preservation requirements.

Required:

- Add pure helper(s) that classify table headers as identity-bearing vs effect/mechanics-bearing.
- Update `_extract_entity_candidates(...)` table-cell loop to register cells only from identity-bearing table contexts.
- Preserve true NPC extraction from identity tables.
- Ensure false Well effect labels and effect prose do not appear as NPC/entity candidates from table cells.

Verify:

- `.venv/bin/python -m py_compile utils/toolkit_source_manifest.py scripts/test_source_atom_triage_hardening.py`
- `.venv/bin/python -m unittest scripts.test_source_atom_triage_hardening -v`
- `.venv/bin/python -m unittest scripts.test_accurate_ingest_source_graph -q`
- `openspec validate toolkit-accurate-ingest-source-atom-triage-hardening --strict`

Output:

- Summarize helper names and changed extraction behavior.
- Report false-positive and true-positive test results.
- Note any existing source-graph tests updated and why.

**Verification Gate (after builder reports):**

- [ ] False table/effect cells no longer become NPC candidates.
- [ ] True table NPC names still extract.
- [ ] Existing source graph tests pass or changes are justified.
- [ ] OpenSpec validates strictly.

**Next Step Ready:** Step 3 entity triage non-actor prefilter.

---
