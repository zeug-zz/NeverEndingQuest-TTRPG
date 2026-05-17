## Overview

Phase 10 expands deterministic Homebrewery ingest from a room-only parser into a source-faithful content-block parser. The implementation must preserve the existing deterministic artifact emitters and sequential ID behavior while allowing common map-key heading formats to become NEQ locations without first passing through lossy LLM normalization.

The guiding rule is: deterministic parsing may format source structure, but it must not creatively replace source structure. If the parser cannot confidently extract a usable structure, it must report fallback/error state rather than emit an incomplete module.

## Current State

`core/importers/homebrewery_importer.py` currently has:

- `_parse_room_blocks(semantic_text)` recognizing only `## Room N: Title`.
- `_build_intermediate_adventure(title, source_path, rooms)` expecting room-like records.
- `_generate_neq_ids(module_slug, rooms)` assigning sequential IDs from source order.
- deterministic import path in `import_homebrewery_adventure_to_module(...)` that fails with `no_rooms_found` if `_parse_room_blocks(...)` returns no rooms.

This works for Birble-style room chains but not for Numillian-style map-key headings.

## Decisions

### Decision 1: Add Content Blocks While Keeping Room Records Compatible

Introduce `_parse_content_blocks(semantic_text)` and keep `_parse_room_blocks(semantic_text)` as a compatibility wrapper or equivalent room-compatible output path.

Content block records SHOULD include:

```json
{
  "source_block_id": "stable_source_order_id",
  "source_block_kind": "room|map_key_location|sub_location",
  "source_heading_level": 2,
  "source_heading_text": "## Room 1: Entrance",
  "source_block_style": "room_colon|map_key_dot|map_key_dash|sub_location_dot",
  "source_number": 1,
  "source_title": "Entrance",
  "source_parent_title": "Map Key",
  "source_parent_number": null,
  "description": "...",
  "puzzle": "...",
  "solution": "...",
  "creatures": "...",
  "exit_comment": "...",
  "other_sections": {},
  "tables": [],
  "raw_content": "..."
}
```

The importer-compatible location object MUST continue to expose fields currently consumed by emitters:

- `source_room_number`
- `source_room_title`
- `name`
- `description`
- `puzzle`
- `solution`
- `creatures`
- `exit_comment`
- `other_sections`
- `tables`
- `raw_content`

Additional source metadata may be additive.

### Decision 2: Support Conservative Heading Styles

The parser MUST support these heading styles:

- `## Room N: Title`
- `### N. Location Name`
- `### N - Location Name`
- `#### N. Sub-location`

The parser SHOULD detect map-key sections conservatively:

- Prefer numbered `###` headings under parent headings containing terms such as `map`, `map key`, `locations`, `areas`, `district`, `city`, `town`, `dungeon`, or `region`.
- Also allow a dense run of numbered `###` headings when three or more compatible headings appear in source order.
- Do not parse numbered bullet lists as locations.
- Do not parse prose sentences as locations.

### Decision 3: Preserve Source Order, Not Numeric Order

All deterministic output ordering MUST follow source order. Numeric labels are display/provenance metadata only.

Examples:

- Source order `1, 2, 100` emits location IDs `...01, ...02, ...03`.
- Map-key order `1, 4, 2` emits in that exact source order.
- `####` sub-locations are emitted immediately after their parent block unless implementation chooses to nest them only as metadata; either path must be deterministic and tested.

### Decision 4: Fallback Routing Must Be Explicit

The deterministic path MUST distinguish:

- `deterministic_success`: enough room/map-key blocks were parsed and emitted.
- `deterministic_insufficient_structure`: source is readable but deterministic parsing found no safe content blocks.
- `deterministic_ambiguous_structure`: parser found conflicting or too-weak block candidates.

For `use_deterministic=True`, insufficient or ambiguous structure MUST return a clear error/fallback payload and MUST NOT emit partial module artifacts. For higher-level accurate-ingest orchestration, the same state MAY route to multi-pass LLM normalization in a later integration point.

### Decision 5: Preserve Source Graph Artifacts Where Available

If deterministic import has access to source graph/source manifest helpers or an artifact workspace, it SHOULD preserve deterministic source graph artifacts. This change does not require inventing a new source graph schema. It should reuse existing source graph helpers if safe; otherwise it must record enough content-block metadata for a later source graph stage to reconstruct evidence.

## Implementation Notes

Recommended helper functions:

- `_parse_content_blocks(semantic_text: str) -> List[Dict[str, Any]]`
- `_detect_content_headings(semantic_text: str) -> List[Dict[str, Any]]`
- `_heading_style_for_match(...) -> str`
- `_content_block_to_room_record(block: Dict[str, Any], ordinal: int) -> Dict[str, Any]`
- `_parse_location_blocks(semantic_text: str) -> List[Dict[str, Any]]` if a narrower public helper is useful for tests.
- `_build_deterministic_parse_result(semantic_text: str) -> Dict[str, Any]` if fallback state needs a structured envelope.

Existing functions that should remain usable:

- `_parse_room_blocks(...)`
- `_build_intermediate_adventure(...)`
- `_generate_neq_ids(...)`
- `import_homebrewery_adventure_to_module(...)`

## Test Strategy

Add or extend tests for:

- Existing `## Room N: Title` behavior remains unchanged.
- `### 1. Brooksteps Inn` produces a deterministic location record.
- `### 1 - Brooksteps Inn` produces a deterministic location record.
- `#### 1. Cellar` is attached to or emitted after its parent in source order.
- Mixed room and map-key headings preserve source order.
- Numeric labels do not determine NEQ IDs.
- Deterministic dry-run returns preview data for map-key sources.
- No structured headings returns a clear deterministic fallback/error and writes no artifacts.
- Presentation macro stripping remains compatible.
- Source graph/source metadata is preserved or exposed in intermediate records.

## Risks

| Risk | Mitigation |
|---|---|
| Parser over-promotes numbered headings from non-location sections. | Require heading-level patterns, parent section heuristics, or dense heading runs; test false positives. |
| Existing room importer behavior regresses. | Keep `_parse_room_blocks` compatibility tests and sequential ID tests. |
| Deterministic path emits incomplete modules. | Fail closed with explicit fallback/error status when structure is insufficient. |
| Source graph artifacts drift from parser output. | Reuse source metadata fields and source-order IDs; add source metadata tests. |

## Open Questions For Builder

- Should `####` sub-locations become separate NEQ locations, or nested metadata under parent locations? The default recommendation is separate NEQ locations in source order, with parent metadata retained, because gameplay navigation benefits from explicit location records.
- Should fallback to multi-pass LLM normalization be wired directly in `import_homebrewery_adventure_to_module(...)` or only reported for the higher-level uploader pipeline? The default recommendation is report-only in this slice unless a current caller already owns fallback routing.
