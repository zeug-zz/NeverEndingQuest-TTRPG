## Why

Phase 1 established deterministic source graph artifacts. Phase 2 added section-bounded extraction, identity adjudication, plot/puzzle topology synthesis, and source-backed normalized packet synthesis. Phase 3 added normalization fidelity audit and bounded packet repair. The next remaining fidelity risk is the builder handoff itself: the existing builder path can still consume a prose `builder_narrative.md` and re-expand the adventure creatively, losing source structure even after normalization fidelity passes.

This Phase 4 change should convert the Phase 2-3 artifact set into a source-locked `builder_blueprint.json` and a constrained builder handoff. The builder should receive explicit source rosters, plot topology, puzzle rules, source locks, and fidelity status instead of a short freeform summary. The purpose is not yet to rewrite the full module generator; the purpose is to make the current builder entrypoint consume a structured source plan and to prevent blocked/failed fidelity packets from entering the build path.

## What Changes

- Add builder blueprint generation from source graph, identity, topology, normalized packet, and fidelity artifacts.
- Add a fidelity precheck that refuses blueprint generation and builder handoff when Phase 3 reports blocked/failed fidelity or missing required source artifacts.
- Generate a source-locked `builder_narrative.md` from the blueprint for the current `ModuleBuilder.build_module(...)` text-entry handoff.
- Add `builder_input.json` metadata for blueprint identity, fidelity status, source lock settings, and source artifact paths.
- Update packet builder handoff to prefer blueprint-backed narrative when available and safe.
- Preserve legacy builder handoff behavior when accurate ingest blueprint mode is disabled or unavailable.

## Capabilities

### New Capabilities

- `toolkit-builder-blueprint-generation`: Source-backed normalization artifacts can be transformed into a canonical builder blueprint.
- `toolkit-source-locked-builder-narrative`: Builder narrative handoff can serialize blueprint content with explicit source locks and forbidden-invention guidance.
- `toolkit-blueprint-builder-input-handoff`: Builder input artifacts can carry blueprint path, fidelity status, and source-lock settings into the existing packet builder flow.
- `toolkit-blueprint-fidelity-precheck`: Builder blueprint and handoff generation can refuse blocked/failed fidelity states before module construction starts.

## Non-Goals

- Do not implement build-time fidelity gates in this change.
- Do not add the review UI fidelity panel in this change.
- Do not add narrative enrichment in this change.
- Do not remove the legacy one-shot normalizer or legacy builder handoff path.
- Do not perform a full deterministic module materializer rewrite in this change.
- Do not require broad `ModuleBuilder` or `ModuleGenerator` refactors beyond minimal handoff/prompt consumption needed for current builder entrypoints.
- Do not silently waive Phase 3 fidelity blockers.

## Impact

- **Affected code, later implementation:** `utils/toolkit_builder_blueprint.py` (new), `utils/toolkit_homebrew_upload_contract.py`, `utils/toolkit_homebrew_normalizer.py` or the normalization/build orchestration seam that persists `builder_narrative.md`, `web/extensions/toolkit_homebrew_packet_builder.py`, `model_config.py`, and new tests.
- **Runtime behavior, later implementation:** Readable-source Homebrew builds in accurate-ingest mode will generate and consume blueprint-backed builder handoff artifacts after normalization fidelity passes.
- **Backward compatibility:** Existing workspaces without blueprint artifacts must still build through legacy behavior when accurate-ingest blueprint handoff is disabled or unavailable.
- **SP/MP compatibility:** Toolkit-only change; no direct tabletop runtime gameplay behavior change.

## Rollout and Fallback

- Blueprint generation should be feature-flagged, for example `ENABLE_ACCURATE_INGEST_BLUEPRINT_HANDOFF`.
- If Phase 2-3 artifacts are missing, blueprint generation should fail closed for accurate-ingest mode and fall back only when legacy mode is explicitly active.
- If final fidelity status is `blocked` or `failed`, builder handoff must not proceed by default.
- If blueprint generation fails after clean fidelity, preserve all prior normalization/fidelity artifacts and return a reviewable error.
- If packet builder cannot load a blueprint, it may use legacy `builder_narrative.md` only when accurate-ingest blueprint mode is disabled or the workspace is explicitly marked legacy.

## Review Notes

This is the fourth accurate-ingest slice. It deliberately consumes Phase 2-3 outputs and stops before build-time fidelity gates. Later phases should verify whether the builder actually preserved the blueprint during module construction.
