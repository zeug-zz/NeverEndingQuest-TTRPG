## Why

Phase 4 (`toolkit-accurate-ingest-blueprint-builder-handoff`) added the source-locked builder blueprint layer, but verification found two blockers before Phase 5 can safely begin.

First, the normalizer can persist the blueprint-derived `builder_narrative.md` and then overwrite it later with the legacy lossy builder narrative. This defeats the purpose of the source-locked handoff because `ModuleBuilder.build_module(...)` may receive the old concept-summary narrative instead of the `SOURCE-FAITHFUL BUILD LOCK` narrative.

Second, packet-builder handoff behavior and tests do not clearly distinguish accurate-ingest workspaces that require a blueprint from old legacy workspaces that legitimately have no blueprint artifacts. The current tests can also call the real builder path when a mock executor should be used, risking real `ModuleBuilder` and provider execution during regression runs.

## What Changes

- Harden normalizer persistence so a ready blueprint narrative remains the final `builder_narrative.md` artifact and return payload.
- Define a deterministic required-blueprint classification for packet-builder handoff.
- Fail closed when accurate-ingest source/fidelity artifacts imply blueprint handoff is required but no ready blueprint exists.
- Preserve legacy packet-builder behavior only for genuinely legacy workspaces or explicit disabled blueprint mode.
- Harden packet-builder tests so unit tests never call real `ModuleBuilder` or provider-backed generation paths.
- Add regression coverage proving the blueprint narrative is not overwritten by legacy narrative generation.

## Capabilities

### New Capabilities

- `toolkit-blueprint-narrative-persistence`: Ready blueprint narratives remain authoritative through final normalizer artifact persistence.
- `toolkit-blueprint-required-vs-legacy-handoff`: Packet builder distinguishes accurate-ingest required-blueprint workspaces from legacy workspaces.
- `toolkit-packet-builder-test-isolation`: Packet-builder tests are isolated from real builder/provider execution.

## Non-Goals

- Do not implement Phase 5 build-time fidelity gates.
- Do not add the review UI fidelity panel.
- Do not add narrative enrichment or module content rewriting.
- Do not refactor `ModuleBuilder` or `ModuleGenerator` internals.
- Do not remove legacy packet builder support.
- Do not archive Phase 4 in this slice unless verification later confirms it is complete.

## Impact

- **Affected code, later implementation:** `utils/toolkit_homebrew_normalizer.py`, `web/extensions/toolkit_homebrew_packet_builder.py`, `scripts/test_packet_builder_blueprint_handoff.py`, and new/updated normalizer regression tests.
- **Runtime behavior:** Accurate-ingest workspaces with Phase 2-4 artifacts fail closed if blueprint handoff is missing or non-ready. Legacy workspaces without accurate-ingest artifacts continue to build through the legacy path.
- **Backward compatibility:** Existing legacy packet workspaces remain supported when they do not carry accurate-ingest source/fidelity artifacts or blueprint mode is disabled.
- **SP/MP compatibility:** Toolkit-only change; no direct tabletop runtime gameplay behavior change.

## Rollout and Fallback

- The existing `ENABLE_ACCURATE_INGEST_BLUEPRINT_HANDOFF` flag remains the rollback switch.
- If disabled, packet builder uses the existing legacy `builder_narrative.md` path.
- If enabled and source/fidelity artifacts prove this is an accurate-ingest workspace, missing or blocked blueprint status fails closed with a reviewable error.
- Tests must use injected executors or explicit no-call assertions so rollback/testing never spends provider calls.

## Review Notes

This is a hardening slice for Phase 4, not Phase 5. It should be completed before starting Phase 5 because Phase 5 would otherwise audit builder output against a handoff artifact that may already have been overwritten.
