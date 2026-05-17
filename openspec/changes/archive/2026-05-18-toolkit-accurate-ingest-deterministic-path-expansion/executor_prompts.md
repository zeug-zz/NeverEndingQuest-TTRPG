# Executor Prompts: Toolkit Accurate-Ingest Deterministic Path Expansion

These prompts are for a builder model implementing Phase 10. Execute in order. Preserve all MUST constraints from proposal, design, specs, and tasks.

## Prompt 1: Parser Foundation

**Verbosity Tier:** full

```text
Implement the generalized deterministic content-block parser for `core/importers/homebrewery_importer.py`.

Goal:
Replace room-only detection with a parser that recognizes existing room headings and common map-key heading styles while preserving current room-chain behavior.

MUST:
- Add `_parse_content_blocks(semantic_text)` or an equivalent helper.
- Support `## Room N: Title`.
- Support `### N. Location Name`.
- Support `### N - Location Name`.
- Support `#### N. Sub-location` with parent context.
- Preserve source order exactly.
- Preserve source number/title/heading/style/raw content metadata.
- Do not parse numbered list items as locations.
- Do not call providers.
- Keep `_parse_room_blocks(...)` backward compatible.

SHOULD:
- Use small helper functions for heading detection and block slicing.
- Reuse `_extract_subsections(...)` and `_extract_markdown_tables(...)` where possible.
- Keep content-block records close to the current room-record shape to reduce downstream changes.

Verification after this prompt:
- `.venv/bin/python -m py_compile core/importers/homebrewery_importer.py`
- Existing `scripts/test_homebrewery_importer.py` should still pass or fail only because new tests are not added yet.
```

## Prompt 2: Map-Key Conversion And Deterministic Import Routing

**Verbosity Tier:** full

```text
Wire generalized content blocks into deterministic import routing.

Goal:
Make map-key source files produce importer-compatible records and deterministic dry-run/build outputs without requiring LLM normalization.

MUST:
- Convert content blocks into existing room/location record keys consumed by `_build_intermediate_adventure(...)` and emitters.
- Preserve existing fields: source_room_number, source_room_title, name, description, puzzle, solution, creatures, exit_comment, other_sections, tables, raw_content.
- Add additive metadata for source_block_kind, source_block_style, source_heading_level, source_heading_text, source_parent_title/source_parent_number where available.
- Update deterministic branch in `import_homebrewery_adventure_to_module(...)` to use generalized content blocks.
- Preserve dry-run behavior and include map-key block/location count in preview.
- Preserve existing AI-driven path when `use_deterministic=False`.
- Do not alter ModuleBuilder or ModuleGenerator.

SHOULD:
- Keep old `no_rooms_found` wording where useful, but add deterministic status detail such as `deterministic_insufficient_structure`.
- Keep failures fail-closed and artifact-free for deterministic mode.

Verification after this prompt:
- `.venv/bin/python -m py_compile core/importers/homebrewery_importer.py`
- Focused dry-run smoke with temp map-key markdown if tests are not written yet.
```

## Prompt 3: Source Metadata And Fallback Semantics

**Verbosity Tier:** full

```text
Harden source metadata preservation and deterministic fallback semantics.

Goal:
Ensure deterministic parsing preserves source evidence for later source graph/fidelity phases and fails closed when structure is insufficient.

MUST:
- Preserve source metadata in intermediate records for every parsed block.
- If no safe blocks are found, return a clear deterministic insufficient-structure status and do not emit artifacts.
- If ambiguous structure is detected, return a clear ambiguous-structure status and do not emit artifacts.
- Ensure map-key source metadata can be used later by source graph/fidelity reports.
- Do not weaken build fidelity gates.

SHOULD:
- Reuse existing source graph helper APIs if safe and already available.
- If source graph helper integration would be too invasive, keep this slice to metadata preservation and document helper integration as future work.

Verification after this prompt:
- Inspect returned error/fallback payloads.
- Confirm deterministic failures do not create module directories/files in temp tests.
```

## Prompt 4: Regression Tests

**Verbosity Tier:** full

```text
Add focused tests for Phase 10 deterministic path expansion.

MUST add/extend tests for:
- Existing `## Room N: Title` behavior remains compatible.
- `### 1. Brooksteps Inn` parses as map-key location.
- `### 1 - Brooksteps Inn` parses as map-key location.
- `#### 1. Cellar` preserves parent context.
- Mixed room/map-key structures preserve source order.
- Source numbers are provenance only; NEQ IDs remain sequential.
- Numbered bullet lists are not promoted to locations.
- Deterministic dry-run works for map-key source.
- Insufficient structure returns deterministic fallback/error and writes no artifacts.
- AI-driven path remains available when deterministic mode is false.

Recommended files:
- Extend `scripts/test_homebrewery_importer.py` for compatibility/parser basics.
- Add `scripts/test_homebrewery_importer_map_key_locations.py`.
- Add `scripts/test_content_blocks_fallback.py`.

MUST NOT:
- Call external providers.
- Invoke real ModuleBuilder in success-path tests unless mocked.
- Write outside temp directories.

Verification:
- `.venv/bin/python -m unittest -q scripts.test_homebrewery_importer`
- `.venv/bin/python -m unittest -q scripts.test_homebrewery_importer_map_key_locations`
- `.venv/bin/python -m unittest -q scripts.test_content_blocks_fallback`
```

## Prompt 5: Final Verification And Closure

**Verbosity Tier:** concise

```text
Run the final Phase 10 verification gate.

Commands:
- `.venv/bin/python -m py_compile core/importers/homebrewery_importer.py scripts/test_homebrewery_importer.py scripts/test_homebrewery_importer_map_key_locations.py scripts/test_content_blocks_fallback.py`
- `.venv/bin/python -m unittest -q scripts.test_homebrewery_importer`
- `.venv/bin/python -m unittest -q scripts.test_homebrewery_importer_map_key_locations`
- `.venv/bin/python -m unittest -q scripts.test_content_blocks_fallback`
- `openspec validate toolkit-accurate-ingest-deterministic-path-expansion`
- `git diff --check`
- Changed-file ASCII check.

Report:
- Files changed.
- Parser heading styles supported.
- Deterministic fallback behavior.
- Test results.
- Any residual risks or deferred source graph integration notes.
```
