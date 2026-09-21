## Why

The adaptation convergence and monster-guardrail contracts are complete and verified in staging, but the live Toolkit entry points do not yet provide the production convergence callback. With `ENABLE_LLM_ADAPTATION=True`, a successful adaptation build can therefore stop at `finalization_callback_missing` instead of reaching its existing final gates. Canonical monster stat generation is also explicitly opt-in only in test/replay provenance, so the real operator path cannot exercise the approved-identity generation contract.

This change closes those production wiring gaps without reopening the completed convergence or monster-guardrail changes.

## What Changes

- Add one production adaptation callback adapter for the existing convergence seam.
- Make the callback deterministic-first: return a bounded no-provider success when no repairable blocker remains; call the configured provider only for a genuinely repairable bounded proposal request.
- Route the callback through the uploaded-adventure and text-description adaptation build paths while preserving the exact legacy paths when adaptation is disabled or ineligible.
- Validate provider proposals through the existing Python-owned convergence contract; preserve bounded failure classes for timeout, quota, dependency, malformed, rejected, and unavailable outcomes.
- Add an operator-controlled canonical monster stat-generation opt-in, defaulting to `False`, and carry it into adaptation provenance only when explicitly enabled.
- Preserve reuse-first materialization, approved canonical identity checks, staging-only writes, schema verification, and no legacy fallback.
- Add route-level provider-free regressions and a bounded live-build smoke contract for the enabled path.
- Document rollback by disabling the adaptation flag and retaining prior staging evidence.

### Non-Goals

- Do not reopen or rewrite `toolkit-adaptation-publication-convergence` or `toolkit-adaptation-monster-guardrail` requirements.
- Do not enable adaptation or canonical monster generation by default.
- Do not add a GUI mode or selector.
- Do not change legacy accurate-ingest, direct ModuleBuilder, single-player, or TABLETOP MODE gameplay behavior.
- Do not allow provider output to write module files, registry state, campaign state, coordinates, topology, identities, or schemas directly.
- Do not add a new provider architecture or bypass the existing client factory and GPT-5 parameter contract.

## Capabilities

### New Capabilities

- `toolkit-adaptation-production-convergence-routing`: Routes eligible enabled adaptation builds through a deterministic-first, bounded provider callback and preserves fail-closed staging behavior.
- `toolkit-adaptation-canonical-generation-opt-in`: Exposes explicit operator provenance for approved canonical monster stat completion while retaining a safe disabled default and staging-only verification.

### Modified Capabilities

- None. The completed convergence, monster-guardrail, and runtime-unification requirements remain the source contracts consumed by this integration change.

## Impact

- Production adaptation runtime and route handoff: `web/extensions/toolkit_adaptation_runtime.py`, `web/extensions/toolkit_text_adaptation_worker.py`, and `web/routes/toolkit_homebrew_routes.py`.
- Existing convergence and guardrail seams: `utils/toolkit_adaptation_publication_convergence.py`, `utils/toolkit_adaptation_monster_guardrail.py`, and `web/extensions/toolkit_homebrew_packet_builder.py`.
- Operator configuration/provenance: `model_config.py`, `config_template.py`, and adaptation handoff metadata.
- Provider use remains bounded and uses the existing AI client factory, configured GPT-5-family parameters, and existing timeout/error classification.
- Tests will use injected callbacks/builders for provider-free verification; any live smoke is explicit, bounded, and writes only project-local staging artifacts.
- Rollback remains flag-based: setting `ENABLE_LLM_ADAPTATION=False` routes future eligible inputs to legacy behavior, while failed adaptation attempts remain staging-local and non-publishable.
