# Tasks: Toolkit Accurate-Ingest Deterministic Path Expansion

## 1. Artifact And Current-State Review

- [x] 1.1 Review `plans/accurate-ingest.md` Phase 10 acceptance criteria.
- [x] 1.2 Review existing `core/importers/homebrewery_importer.py` deterministic path from source load through `_parse_room_blocks`, `_build_intermediate_adventure`, `_generate_neq_ids`, dry-run preview, and `_emit_neq_artifacts`.
- [x] 1.3 Review existing tests in `scripts/test_homebrewery_importer.py` and identify coverage to preserve.
- [x] 1.4 Confirm no provider calls or `ModuleBuilder` internals are needed for this change.

## 2. Generalized Content-Block Parser

- [x] 2.1 Add `_parse_content_blocks(semantic_text)` or equivalent helper in `core/importers/homebrewery_importer.py`.
- [x] 2.2 Support existing `## Room N: Title` headings.
- [x] 2.3 Support map-key dot headings: `### N. Location Name`.
- [x] 2.4 Support map-key dash headings: `### N - Location Name`.
- [x] 2.5 Support sub-location headings: `#### N. Sub-location` with parent context.
- [x] 2.6 Preserve source order exactly; do not sort by source number.
- [x] 2.7 Avoid promoting numbered bullet lists or prose into location blocks.
- [x] 2.8 Preserve raw content, source heading text, heading level, heading style, source number, source title, and parent metadata where available.

## 3. Importer-Compatible Record Conversion

- [x] 3.1 Add conversion helper from content block to current room/location record shape.
- [x] 3.2 Preserve existing keys consumed by emitters: `source_room_number`, `source_room_title`, `name`, `description`, `puzzle`, `solution`, `creatures`, `exit_comment`, `other_sections`, `tables`, and `raw_content`.
- [x] 3.3 Add additive metadata keys for source block kind/style/heading/parent without breaking existing emitters.
- [x] 3.4 Keep `_parse_room_blocks(...)` backward compatible for existing tests/callers.
- [x] 3.5 Ensure `_build_intermediate_adventure(...)` accepts converted map-key records without room-only assumptions causing failures.

## 4. Deterministic Path Routing And Fallback

- [x] 4.1 Update deterministic branch in `import_homebrewery_adventure_to_module(...)` to use generalized content-block parsing.
- [x] 4.2 Replace `no_rooms_found`-only failure semantics with explicit deterministic structure status, while preserving backward-compatible error readability.
- [x] 4.3 Ensure insufficient/ambiguous structure writes no module artifacts in deterministic mode.
- [x] 4.4 Ensure non-deterministic AI-driven path remains unchanged when `use_deterministic=False`.
- [x] 4.5 Ensure dry-run preview works for map-key sources and reports parsed location/block count.

## 5. Source Metadata / Source Graph Preservation

- [x] 5.1 Preserve source metadata in intermediate records sufficient for source graph reconstruction.
- [x] 5.2 Defer direct source graph helper integration; Phase 10 uses preserved source metadata (`_source_block_metadata`) as the compatibility bridge for future source graph stages.
- [x] 5.3 If helper integration is out of scope for this slice, document that source metadata preservation is the compatibility bridge and add tests for the metadata fields.
- [x] 5.4 Ensure this change does not weaken source/build fidelity gates.

## 6. Regression Tests

- [x] 6.1 Extend `scripts/test_homebrewery_importer.py` for content-block parser compatibility and existing room behavior.
- [x] 6.2 Add `scripts/test_homebrewery_importer_map_key_locations.py` covering dot headings, dash headings, source-order preservation, source-number provenance, dry-run preview, and emitted artifact compatibility.
- [x] 6.3 Add `scripts/test_content_blocks_fallback.py` covering insufficient structure, ambiguous structure, no artifact writes, and AI-driven path availability.
- [x] 6.4 Add tests proving numbered lists/prose are not promoted to locations.
- [x] 6.5 Add tests proving sub-location parent metadata is preserved.
- [x] 6.6 Add tests proving map-key records retain source metadata needed by source graph/fidelity stages.

## 7. Verification

- [x] 7.1 Run `.venv/bin/python -m py_compile core/importers/homebrewery_importer.py scripts/test_homebrewery_importer.py scripts/test_homebrewery_importer_map_key_locations.py scripts/test_content_blocks_fallback.py`.
- [x] 7.2 Run `.venv/bin/python -m unittest -q scripts.test_homebrewery_importer`.
- [x] 7.3 Run `.venv/bin/python -m unittest -q scripts.test_homebrewery_importer_map_key_locations`.
- [x] 7.4 Run `.venv/bin/python -m unittest -q scripts.test_content_blocks_fallback`.
- [x] 7.5 Run `openspec validate toolkit-accurate-ingest-deterministic-path-expansion`.
- [x] 7.6 Run changed-file ASCII and whitespace checks.

## Implementation Notes

- Keep implementation local to importer/toolkit paths.
- Preserve current deterministic artifact schema outputs unless a test proves additive metadata is necessary.
- Do not call LLM providers in deterministic parsing tests.
- Do not run broad integration tests that may invoke `ModuleBuilder` or external providers unless explicitly mocked or approved.
