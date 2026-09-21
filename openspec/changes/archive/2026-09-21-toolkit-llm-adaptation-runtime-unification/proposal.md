## Why

The completed LLM adaptation scaffold provides the dossier, staging, validation, publication, Markdown, provenance, and rollback contracts, but the live Toolkit entry points do not invoke that path. Uploaded adventures still enter the legacy packet route, while the text-description builder writes directly through `ModuleBuilder` and bypasses adaptation staging and publication parity. Setting `ENABLE_LLM_ADAPTATION=True` therefore does not yet route a normal Toolkit build through the new builder.

This follow-up connects both existing inputs to the completed adaptation runtime so eligible adventure files and text descriptions can produce validated modules for world population without adding a second GUI mode or weakening Python-owned gates.

## What Changes

- Make `ENABLE_LLM_ADAPTATION=True` select the background adaptation route for eligible uploaded Markdown/PDF adventures and text-description builds; keep `False` as the explicit legacy accurate-ingest/direct-builder route.
- Add one Python-owned runtime adapter that creates bounded source context, attempt metadata, rights metadata, world-context provenance, and adaptation staging before authoring begins.
- Route uploaded adventure workspaces through `run_adaptation_authoring()` and pass the validated dossier, provenance, and staging target into the existing adaptation packet builder and finisher.
- Route the existing `start_build` text-description path through the same adaptation authoring, staging, readiness, publication, Markdown, registry, campaign, and rollback transaction when adaptation is enabled.
- Preserve the existing GUI actions and status surfaces; do not add an adaptation mode selector or require a new operator workflow.
- Treat user-authored text and an upload explicitly classified as `user_authored` as eligible input without asking the LLM to infer rights. Preserve supplied licensed/restricted classifications and review requirements.
- Replace the current adaptation handoff dead end (`llm_adaptation_not_implemented`) with the real authoring handoff; an author refusal or provider failure remains an explicit adaptation failure and never silently falls through to legacy generation.
- Harden the adaptation author request with a strict structured-output contract compatible with GPT-5-family routing, while retaining the existing Python dossier parser as the final authority.
- Persist bounded, safe refusal diagnostics and provider/model metadata so a refused dossier can be distinguished from transport, quota, parameter, or parser failures without exposing raw provider text or credentials.
- Add provider-free route/integration tests and a bounded real Jeremys Magic Shop smoke through the actual Toolkit job path.

## Capabilities

### New Capabilities

- `toolkit-adaptation-runtime-routing`: Defines feature-flagged background routing for uploaded adventure files and text-description builds without a new GUI mode.
- `toolkit-adaptation-source-input-handoff`: Defines bounded source-context, rights, world-context, attempt, authoring, dossier, and staging handoff for both input types.
- `toolkit-adaptation-author-provider-contract`: Defines GPT-5-family structured output, Python-owned dossier validation, refusal classification, and safe provider diagnostics.
- `toolkit-adaptation-runtime-publication`: Defines unified staged ModuleBuilder execution, readiness/finishing/publication reuse, and fail-closed behavior for the live Toolkit routes.

### Modified Capabilities

- None. The runtime route is an additive adaptation mode; existing legacy accurate-ingest and direct-builder behavior remains available when adaptation is disabled.

## Impact

- `web/routes/toolkit_homebrew_routes.py` for upload-job authoring, adaptation handoff, staging, and status propagation.
- `web/web_interface.py` for the existing text-description Socket.IO builder path and its shared readiness/finishing transaction.
- `web/extensions/toolkit_homebrew_packet_builder.py` for receiving the real dossier/provenance/staging inputs instead of returning the current not-implemented guard.
- A new adaptation runtime adapter under `web/extensions/` or `utils/` for shared upload and text-description orchestration.
- `utils/toolkit_adaptation_author.py` and adaptation prompt/parameter contracts for rights-aware structured output and bounded refusal telemetry.
- Existing adaptation staging, finisher, report, Markdown, registry, campaign, and rollback helpers from `toolkit-llm-adaptation-builder`; no duplicate publication implementation.
- `model_config.py` only as an operator-controlled feature gate; the slice MUST NOT silently change the operator's current setting or make adaptation active when the flag is false.
- Provider-free fixtures and route/integration regression suites, including the Jeremys Magic Shop source.
- No new GUI controls, no direct LLM writes to module files or runtime state, and no changes to player-facing gameplay mechanics.

## Rollout And Fallback

- `ENABLE_LLM_ADAPTATION=False` MUST preserve the current legacy paths.
- `ENABLE_LLM_ADAPTATION=True` MUST route eligible inputs through adaptation in the background; the existing GUI remains unchanged.
- A selected adaptation attempt that fails authoring, validation, staging, readiness, semantic review, Markdown, registry, campaign, or rollback verification MUST fail closed with diagnostics and MUST NOT silently run the legacy path.
- User-authored text and uploads carrying `user_authored` or approved licensed/project-owned rights metadata may proceed. Restricted or missing rights metadata MUST remain review-gated rather than being relabeled by the LLM.
- Provider refusals, quota errors, timeouts, dependency failures, invalid structured output, and parser failures MUST remain distinguishable and MUST NOT consume semantic revision budget unless the existing failure classifier explicitly permits revision.
- Rollback is disabling the feature flag and preserving the completed scaffold; no existing published modules, runtime registry entries, campaign state, or source uploads are rewritten by the route integration.

## Merge Safety And Compatibility

- Prefer a new extension adapter and thin hooks in the two existing host entry points.
- Mark required host-file changes with `# TABLETOP MODE:` comments.
- Reuse the completed adaptation publication transaction and existing legacy readiness/finisher contracts.
- Preserve single-player and TABLETOP MODE behavior outside the feature-gated adaptation route.
- Use atomic JSON writes and project-relative staging targets; keep `world_registry.json` and `campaign.json` runtime-only.
- Keep user-facing Python output and new prompt/test artifacts ASCII-only.
