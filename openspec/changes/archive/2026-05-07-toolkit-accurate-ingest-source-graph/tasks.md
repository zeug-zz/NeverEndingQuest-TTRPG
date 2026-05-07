## 1. Source Manifest Utility

- [x] 1.1 Add `utils/toolkit_source_manifest.py` with SPDX/header and public `build_source_manifest(...)` and `build_source_graph(...)` helpers.
- [x] 1.2 Implement heading hierarchy extraction with line ranges and parent/child context.
- [x] 1.3 Implement markdown table extraction or reuse existing table parsing logic through a shared helper.
- [x] 1.4 Implement map-key and room-style location candidate extraction.
- [x] 1.5 Implement conservative entity candidate extraction from bold spans, table cells, quoted names, and title-case proper noun patterns.
- [x] 1.6 Implement mechanic, puzzle/trial, item/treasure, encounter, and tone marker candidate extraction.

**Verification for 1.1-1.6**: `.venv/bin/python -m py_compile utils/toolkit_source_manifest.py` passes and focused source manifest unit tests pass.

## 2. Source Graph Contract

- [x] 2.1 Convert manifest candidates into typed source atoms with stable IDs.
- [x] 2.2 Add evidence references containing source path, section, line range, and bounded excerpt.
- [x] 2.3 Add initial `criticality` and `confidence` classification.
- [x] 2.4 Add graph summary counts for NPC, location, puzzle, encounter, item, and tone candidates.
- [x] 2.5 Ensure graph generation handles empty, malformed, or unusual markdown without raising uncaught exceptions.

**Verification for 2.1-2.5**: Tests cover normal markdown, empty markdown, table-heavy markdown, Numillian-style map-key markdown, and false-positive-prone proper nouns.

## 3. Workspace Artifact Persistence

- [x] 3.1 Extend `utils/toolkit_homebrew_upload_contract.py` workspace file helpers to include `source_manifest.json` and `source_graph.json`.
- [x] 3.2 Add atomic persistence helpers for source manifest and source graph artifacts.
- [x] 3.3 Preserve compatibility for workspaces that do not have these artifacts.

**Verification for 3.1-3.3**: `.venv/bin/python -m py_compile utils/toolkit_homebrew_upload_contract.py` passes and artifact helper tests verify paths and safe missing-artifact behavior.

## 4. Normalizer Integration

- [x] 4.1 In `utils/toolkit_homebrew_normalizer.py`, build source manifest and source graph before the existing LLM normalization call.
- [x] 4.2 Persist source graph artifacts when a workspace is available.
- [x] 4.3 Add source graph summary counts to `normalization_report`.
- [x] 4.4 If source graph generation fails, record degraded status and continue current normalization behavior.
- [x] 4.5 Do not change the existing normalized packet schema in this phase except for optional confidence/provenance notes if needed.

**Verification for 4.1-4.5**: `.venv/bin/python -m py_compile utils/toolkit_homebrew_normalizer.py` passes and normalizer tests prove legacy packet output remains review-valid.

## 5. Numillian Benchmark Foundation

- [x] 5.1 Add a focused benchmark/test fixture for Numillian-style markdown structure.
- [x] 5.2 Assert source graph captures at least 18 NPC candidates and 13 location candidates for the fixture.
- [x] 5.3 Assert the trial/puzzle candidates include skull riddle, flooding room puzzle, and mindscape/dog test cues when present in the fixture.
- [x] 5.4 Assert graph atoms include evidence references for captured NPCs, locations, and puzzles.

**Verification for 5.1-5.4**: `.venv/bin/python scripts/test_accurate_ingest_source_graph.py` passes.

## 6. Final Validation

- [x] 6.1 Run `.venv/bin/python -m py_compile utils/toolkit_source_manifest.py utils/toolkit_homebrew_upload_contract.py utils/toolkit_homebrew_normalizer.py`.
- [x] 6.2 Run all new accurate-ingest source graph tests.
- [x] 6.3 Run existing toolkit upload contract tests impacted by artifact helpers.
- [x] 6.4 Run `openspec validate toolkit-accurate-ingest-source-graph`.
