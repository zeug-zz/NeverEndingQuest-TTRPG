## Why

Phase 1 of accurate ingest now creates deterministic `source_manifest.json` and `source_graph.json` artifacts before model normalization. The remaining fidelity problem is that the readable-source path still asks one LLM call to read the whole adventure, classify everything, preserve source truth, and emit a flat normalized packet. That single pass is too lossy for Numillian-style sources with many named NPCs, keyed locations, puzzles, trials, clues, and tone markers.

The next phase should replace one-shot full-source normalization with section-bounded, evidence-backed extraction and synthesis. The LLM should extract facts from bounded source sections, while Python owns orchestration, artifact persistence, degraded behavior, identity merging, topology synthesis, and packet compatibility.

## What Changes

- Add a multi-pass normalization plan that runs after deterministic source graph generation and before normalized packet synthesis.
- Add section-bounded extraction artifacts for readable Homebrew uploads.
- Add identity and alias adjudication artifacts for source graph candidates.
- Add plot, puzzle, clue, and trial topology synthesis artifacts.
- Add source-graph-backed normalized packet synthesis while preserving existing review packet compatibility.
- Keep the legacy one-shot normalizer path available as fallback.

## Capabilities

### New Capabilities

- `toolkit-section-bounded-source-extraction`: Readable source sections can be extracted independently with evidence refs and degraded per-section behavior.
- `toolkit-source-identity-adjudication`: Extracted entity candidates can be merged into canonical source identities without silently dropping aliases or ambiguous merges.
- `toolkit-source-plot-topology-synthesis`: Source plot, puzzle, clue, and trial atoms can be synthesized into topology artifacts instead of flattened prose.
- `toolkit-source-graph-packet-synthesis`: Existing normalized packets can be generated from source graph/synthesis artifacts while remaining compatible with current review validation.

## Non-Goals

- Do not implement the fidelity verifier or repair loop in this change.
- Do not add the review UI fidelity panel in this change.
- Do not add builder blueprint handoff in this change.
- Do not modify `ModuleBuilder` or `ModuleGenerator` in this change.
- Do not implement narrative enrichment in this change.
- Do not remove the existing legacy normalizer path.
- Do not archive this change until implementation and validation are complete.

## Impact

- **Affected code, later implementation:** `utils/toolkit_source_extraction.py`, `utils/toolkit_source_graph_synthesis.py`, `utils/toolkit_homebrew_normalizer.py`, `utils/toolkit_homebrew_upload_contract.py`, and new prompt/test files.
- **Runtime behavior, later implementation:** Normalization-required readable uploads will use source section extraction and synthesis before packet generation when accurate-ingest multipass mode is enabled.
- **Backward compatibility:** Existing normalized packet review behavior must remain valid. Workspaces lacking multipass artifacts must still load and validate through legacy paths.
- **SP/MP compatibility:** Toolkit-only change; no direct tabletop runtime behavior change.

## Rollout and Fallback

- Multipass normalization should be feature-flagged or fallback-safe during implementation.
- If one section extraction fails, the pipeline must preserve mechanical source graph artifacts and continue with degraded status when possible.
- If synthesis fails, the normalizer must fall back to the legacy one-shot path or fail closed with a reviewable report, depending on artifact persistence state.
- Provider failures must be observable in reports and must not silently mark source extraction successful.

## Review Notes

This change is intentionally the second accurate-ingest slice. It must not create later-phase artifacts for fidelity repair, builder handoff, build fidelity gates, or narrative enrichment beyond naming them as future dependencies.
