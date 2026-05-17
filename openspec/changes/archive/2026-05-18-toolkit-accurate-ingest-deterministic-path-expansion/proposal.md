## Why

The deterministic Homebrewery importer currently recognizes only `## Room N: Title` blocks, so structured adventures that use common map-key headings such as `### 1. Brooksteps Inn` silently miss source locations or fall back to lossy LLM normalization. Phase 10 expands the deterministic path so source-faithful accurate ingest can mechanically preserve map-key structures before any LLM normalization or enrichment runs.

## What Changes

- Add a generalized deterministic content-block parser for Homebrewery/GMBinder markdown.
- Preserve existing `## Room N: Title` behavior while adding support for:
  - `### N. Location Name`
  - `### N - Location Name`
  - `#### N. Sub-location`
- Convert map-key and sub-location blocks into the importer-compatible location record shape consumed by existing deterministic emitters.
- Add conservative fallback routing so deterministic import succeeds only when enough structured blocks are found; otherwise the pipeline reports a clear fallback/error instead of silently skipping non-room structures.
- Preserve source graph/source manifest artifacts for deterministic imports where an artifact workspace is available or a source-graph helper can be called safely.
- Add regression coverage for map-key parsing, content-block fallback behavior, existing room-chain compatibility, and deterministic dry-run behavior.

Non-goals:

- MUST NOT modify `ModuleBuilder` or `ModuleGenerator` internals.
- MUST NOT add provider calls to deterministic parsing.
- MUST NOT weaken build/source fidelity gates.
- MUST NOT change runtime module schemas unless a later reviewed change explicitly requires it.
- MUST NOT remove support for the existing `## Room N: Title` importer contract.

Rollout and fallback:

- The deterministic parser MUST remain local and fail-closed for malformed structured input.
- If deterministic block confidence is insufficient, the importer MUST return a clear fallback/error status instead of emitting an incomplete deterministic module.
- Existing AI-driven import behavior remains available through the current non-deterministic path.

Merge-safety and SP/MP compatibility:

- Changes are limited to importer/toolkit paths and tests; gameplay runtime behavior is unaffected.
- Single-player and TABLETOP MODE module consumption remain compatible because emitted module artifacts retain existing schema shapes.
- Required host edits, if any, SHOULD be minimal and marked with `# TABLETOP MODE:` comments.

## Capabilities

### New Capabilities

- `toolkit-deterministic-content-block-parsing`: Generalized deterministic parser for room, map-key location, and sub-location markdown heading styles.
- `toolkit-map-key-location-import`: Conversion of map-key content blocks into importer-compatible location records and deterministic NEQ artifacts.
- `toolkit-deterministic-import-source-graph-preservation`: Source graph/source manifest preservation for deterministic import paths.
- `toolkit-deterministic-import-fallback-routing`: Explicit fallback/error routing when deterministic parsing cannot safely preserve structured source content.

### Modified Capabilities

- `homebrew-md-sequential-module-ingest`: Existing deterministic room-chain ingest expands from room-only parsing to content-block parsing while preserving room-chain behavior and sequential ID guarantees.

## Impact

- Affected code:
  - `core/importers/homebrewery_importer.py`
  - optional source graph helpers if already available through `utils/toolkit_source_manifest.py`
- Affected tests:
  - `scripts/test_homebrewery_importer.py`
  - new `scripts/test_content_blocks_fallback.py`
  - new `scripts/test_homebrewery_importer_map_key_locations.py`
- Affected docs/plans:
  - `plans/accurate-ingest.md` after implementation is complete.
- No external dependencies are required.
- No provider/LLM routing changes are required.
