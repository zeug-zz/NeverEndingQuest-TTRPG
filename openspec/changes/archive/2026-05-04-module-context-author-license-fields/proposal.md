## Why

The Homebrew module ingest pipeline infers an `author` field from uploaded markdown/PDF content during the LLM normalization stage, but that value is never persisted to any durable module artifact (`module_context.json`). It exists only in the short-lived upload review workspace and is discarded after build. Module developers have no canonical place to record authorship or license metadata for modules.

## What Changes

- Add `"author": ""` and `"license": ""` fields to `module_context.json` as empty strings for human-in-the-loop fill
- Update both emission paths: `_emit_module_context()` (homebrew ingest) and `ModuleContext.to_dict()` (module builder)
- Provide a backfill script to add the fields to all existing module context files
- Module `module_context.json` becomes the copyright authority for the module; no changes to `module_plot.json` (runtime state)

## Capabilities

### New Capabilities

- `module-context-author-license`: `module_context.json` carries blank `author` and `license` string fields for the module developer to fill. Both emission paths (ingest and builder) emit the fields. A backfill script adds them to existing modules.

### Modified Capabilities

_None._

## Impact

- **Affected code**: `core/importers/homebrewery_importer.py` (+2 lines), `utils/module_context.py` (+6 lines)
- **New script**: `scripts/backfill_module_context_author.py` (backfill tool)
- **Affected files**: All `module_context.json` and `module_context_BU.json` files in existing modules (additive, zero-risk backfill)
- **No API changes**, no runtime behavior changes, no SP/MP compatibility impact
