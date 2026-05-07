## Why

The Module Builder uploader currently loses most of the original adventure when a readable markdown or PDF source is routed through the normalization-required path. The Numillian case shows the failure clearly: a source with roughly 20 named NPCs, 13 keyed locations, distinctive trial/puzzle structure, Gatepact lore, and quirky character-driven tone was normalized into a packet that let the builder replace almost all of that source truth with a generic alternate adventure.

The immediate root problem is that the pipeline asks one LLM call to discover, classify, preserve, and summarize the whole adventure, then passes a short builder narrative to `ModuleBuilder`. Before adding richer builder handoff or enrichment, the pipeline needs a durable source-truth foundation: a deterministic source manifest and source graph that record what the original source actually contains.

## What Changes

- Add a source manifest/source graph foundation for readable Homebrew uploads.
- Mechanically extract heading hierarchy, markdown tables, map-key locations, room-style locations, bold/quoted/proper-noun candidates, checks, hazards, treasure, encounters, puzzle/trial candidates, and tone markers.
- Persist source graph artifacts in the Homebrew workspace before LLM normalization.
- Add evidence references to each source atom using source path, section, line range, and excerpt.
- Add initial criticality classification so later phases can distinguish required source truth from false-positive proper nouns.
- Add a Numillian benchmark fixture/test proving the source graph captures the source's named NPCs, keyed locations, and trial/puzzle candidates before any LLM call.

## Capabilities

### New Capabilities

- `toolkit-source-graph-foundation`: Readable Homebrew uploads produce evidence-backed source manifests and source graphs before model normalization or module building.

## Non-Goals

- Do not replace the current normalizer LLM call in this change.
- Do not add multi-pass LLM extraction in this change.
- Do not implement fidelity repair loops in this change.
- Do not change `ModuleBuilder` behavior in this change.
- Do not auto-apply narrative enrichment in this change.
- Do not modify generated module schemas.

## Impact

- **Affected code**: `utils/toolkit_source_manifest.py` (new), `utils/toolkit_homebrew_normalizer.py`, `utils/toolkit_homebrew_upload_contract.py`, focused tests and benchmark fixture code.
- **Runtime behavior**: Normalization-required readable uploads persist additional source-truth artifacts, but existing normalization/build behavior remains compatible.
- **Backward compatibility**: Existing normalized packets and workspaces without source graph artifacts remain valid.
- **SP/MP compatibility**: Toolkit-only change; no direct tabletop runtime behavior change.
- **Risk**: Low-medium. The main risk is false-positive extraction noise, mitigated by confidence and criticality fields.

## Fallback Strategy

If source graph generation fails, the upload path MUST fail open to the existing normalization flow with a degraded warning in the normalization report. Artifact persistence failures MUST still fail closed when they prevent reviewable state from being written, following existing normalizer artifact rules.
