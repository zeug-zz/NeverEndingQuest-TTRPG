## Context

`module_context.json` is a canonical (committed, static) module metadata file. It is emitted by two code paths:
1. **Homebrew ingest**: `core/importers/homebrewery_importer.py:_emit_module_context()`
2. **Module builder**: `utils/module_context.py:ModuleContext.to_dict()` → saved by `core/generators/module_builder.py:1155`

Neither path includes `author` or `license` fields, despite the ingest pipeline's LLM normalizer extracting an `author` value from uploads. That value is discarded after the review workspace.

## Goals / Non-Goals

**Goals:**
- Add `"author": ""` and `"license": ""` as empty-string fields to `module_context.json` in both emission paths
- Provide a backfill script for existing modules
- `module_context.json` serves as the module's copyright authority (human-in-the-loop fill)

**Non-Goals:**
- Do NOT auto-populate `author` from the ingest normalizer's LLM output (human review gate is correct; LLM inferred author may be wrong)
- Do NOT add fields to `module_plot.json` (it is runtime-mutated state)
- Do NOT add a formal JSON schema for `module_context.json` structure
- Do NOT enforce non-empty values as a build gate

## Decisions

**Decision 1: `module_context.json` over `module_plot.json`**
- `module_plot.json` is runtime-mutated player state (quests, plot points) and gitignored. `module_context.json` is canonical static metadata and committed.
- Rationale: Authorship/license is static module metadata, not runtime state. Putting it in `module_context.json` avoids hydration-preservation complexity.

**Decision 2: Two separate fields (`author`, `license`) over a combined string**
- Clean separation of creator identity from legal terms. Machine-parseable if needed later.
- Default empty string `""` — human fills in. No default license text (different modules may have different licenses).

**Decision 3: No auto-population from ingest normalizer**
- The LLM normalizer's `author` extraction is advisory (human-review-gated). Auto-writing it to a canonical artifact bypasses the human review step.
- The review UI already shows `author` during the upload review gate — the human can copy it manually.

## Risks / Trade-offs

- [Risk] Module build with empty `author`/`license` → Mitigation: not a risk — fields are intentionally blank for human fill.
- [Risk] Existing tests break on new dict keys → Mitigation: no existing tests assert exact key sets of `module_context.json`; `get()` access patterns are unaffected by additive keys.
- [Risk] BU files become stale if only `module_context.json` is backfilled → Mitigation: backfill script targets both `.json` and `_BU.json` files.

## Migration Plan

1. Implement code changes (2 files, +8 lines total)
2. Run backfill script on all existing modules (additive only)
3. Verify `module_builder.py` BU backup path propagates new fields naturally (`shutil.copy2`)
4. No rollback needed (additive change, zero risk)
