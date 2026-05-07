# Executor Prompts

## Builder Prompt - Full Variant

Implement OpenSpec change `toolkit-accurate-ingest-source-graph` only. This is Phase 1 of accurate Homebrew ingest and MUST create a deterministic source-truth foundation before any multi-pass LLM extraction, fidelity repair, builder blueprint, or narrative enrichment work.

Goal: Add source manifest and source graph artifact generation for readable Homebrew uploads routed through normalization-required workflow, while preserving the existing normalizer and builder behavior.

Allowed files:
- `utils/toolkit_source_manifest.py` (new)
- `utils/toolkit_homebrew_upload_contract.py`
- `utils/toolkit_homebrew_normalizer.py`
- focused tests under `scripts/`, preferably `scripts/test_accurate_ingest_source_graph.py`
- small fixture data embedded in tests or under an existing test-safe fixture path

Forbidden scope:
- Do not replace the existing LLM normalizer flow.
- Do not implement multi-pass LLM extraction.
- Do not implement fidelity repair loops.
- Do not modify `ModuleBuilder` behavior.
- Do not auto-apply narrative enrichment.
- Do not modify module JSON schemas.
- Do not commit or push.

Required implementation contract:
1. Add `utils/toolkit_source_manifest.py` with the required SPDX/project header and public helpers:
   - `build_source_manifest(source_text: str, source_path: str = "") -> Dict[str, Any]`
   - `build_source_graph(source_text: str, source_path: str = "", source_hash: str = "") -> Dict[str, Any]`
2. The manifest MUST mechanically extract headings, tables, map-key locations, room-style locations, entity candidates, mechanic/check candidates, puzzle/trial candidates, item/treasure candidates, encounter candidates, and tone marker candidates.
3. The source graph MUST convert candidates into typed source atoms with stable IDs, `type`, `name` where applicable, `summary`, `criticality`, `confidence`, `source_refs`, and `metadata`.
4. Evidence refs MUST include source path, section context, line range where available, and a bounded excerpt.
5. Criticality MUST be conservative: numbered map-key and room-style locations default to `required`; broad proper-noun-only candidates MUST NOT default to `required`.
6. Extend `utils/toolkit_homebrew_upload_contract.py` with workspace file entries and persistence helpers for `source_manifest.json` and `source_graph.json`, without breaking old workspaces.
7. Update `utils/toolkit_homebrew_normalizer.py` so readable source normalization builds and persists source graph artifacts before the existing LLM call. If graph generation fails, record degraded source graph status and continue existing normalization behavior.
8. Add source graph summary counts to the normalization report when available.
9. Add a Numillian-style regression fixture/test proving the graph captures at least 18 NPC candidates, 13 location candidates, and puzzle/trial cues for skull riddle, flooding room, and mindscape/dog test when present in the fixture.

Constraints:
- Use `.venv/bin/python` for project-dependent verification commands.
- Use `safe_write_json`/existing artifact persistence patterns for JSON artifact writes.
- Keep new Python console/log text ASCII-only.
- Preserve existing normalized packet schema and `validate_review_packet(...)` compatibility.
- Prefer small helpers and deterministic parsing over broad LLM or regex rewrites.
- Edit Strategy: apply one anchored patch at a time, then run `py_compile` before continuing if a Python file becomes complex.

Expected edge cases:
- Empty markdown should produce an empty/degraded graph without uncaught exceptions.
- Malformed tables should not crash extraction.
- Headings without content should still preserve heading metadata.
- Proper nouns from generic prose should be low-confidence ambiguous/minor candidates unless stronger evidence exists.
- Workspaces missing new artifacts should remain readable by legacy review code.

Verification commands:
```bash
.venv/bin/python -m py_compile utils/toolkit_source_manifest.py utils/toolkit_homebrew_upload_contract.py utils/toolkit_homebrew_normalizer.py
.venv/bin/python scripts/test_accurate_ingest_source_graph.py
openspec validate toolkit-accurate-ingest-source-graph
```

If existing toolkit upload contract tests are available and touched by the artifact helper changes, also run the narrowest relevant existing suite, for example:

```bash
.venv/bin/python scripts/test_toolkit_module_build_publication_parity.py
```

Report format:
- List files changed.
- Summarize source graph artifact shape.
- Report Numillian-style fixture counts for NPC/location/puzzle candidates.
- Paste verification command results.
- Note any intentionally deferred work for the later multi-pass/fidelity/blueprint changes.

## Verification Prompt

Verify `toolkit-accurate-ingest-source-graph` by checking that source graph artifacts are generated before normalization, all source atoms include evidence refs, map-key and room-style locations are mechanically detected, proper-noun-only candidates are not over-promoted to required, legacy normalized packets still validate, modified Python files compile, the Numillian-style source graph regression passes, and `openspec validate toolkit-accurate-ingest-source-graph` is valid.
