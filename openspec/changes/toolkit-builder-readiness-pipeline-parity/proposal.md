## Why

The Module Toolkit's older **Module Builder -> Describe your Adventure** path currently calls the shared toolkit finisher after raw `ModuleBuilder.build_module(...)`, but it skips the uploader's pre-finisher readiness convergence gate. This means legacy builder modules receive final readiness/publishability reporting, but they do not get the same bounded validator/repair/revalidation loop that the newer uploader path now uses before finishing.

This change is needed now because uploader validation/finishing has become the authoritative module quality pipeline, and the older builder inputs should not silently follow a weaker quality path just because their source is an inline narrative prompt instead of an uploaded `.md` or `.pdf` packet.

## What Changes

- Add a shared toolkit readiness entrypoint that can run the uploader-grade readiness convergence gate for modules produced by the legacy Describe your Adventure builder without requiring a Homebrew upload workspace.
- Route successful legacy builder output through readiness convergence before invoking the shared toolkit finisher.
- Keep uploader-only stages uploader-only:
  - source preflight,
  - normalization,
  - review packet generation,
  - source-rights classification,
  - packet-derived builder input.
- Preserve the shared finisher as the single final publication-facing reporting path for both builder and uploader flows.
- Persist legacy-builder readiness artifacts or an equivalent compact artifact set so report freshness, provenance, and failure diagnostics remain auditable.
- Update builder UI/status reporting so `module_complete` and `module_error` distinguish:
  - raw generation failure,
  - readiness repair failure,
  - finishing/publishability failure,
  - publishable success,
  - success with media handoff.
- Update stale copy that says post-build parity does not include semantic probes; the final finisher now runs publishability evaluation with semantic audit/probe gates.
- Add source-contract tests proving the Describe your Adventure path cannot bypass readiness convergence.

Non-goals:

- This change MUST NOT route legacy narrative prompts through Homebrew normalization or review packet generation.
- This change MUST NOT weaken validator, readiness, semantic, or publishability gates to make legacy builder modules pass.
- This change MUST NOT make sidebar rendering invoke live audits; sidebar consumers must continue reading persisted reports only.
- This change MUST NOT change live gameplay/runtime module loading semantics except through already-persisted module artifacts.
- This change SHOULD NOT redesign `ModuleBuilder` output generation; it should wrap post-build quality flow with minimal host edits.

## Capabilities

### New Capabilities
- `toolkit-builder-readiness-pipeline-parity`: legacy Module Builder narrative-input builds must use the same readiness convergence gate and final finisher contract as uploader packet builds, while preserving source-specific upstream stages.

### Modified Capabilities
- `toolkit-module-postbuild-finishing`: toolkit post-build finishing must be sequenced after readiness convergence for legacy builder builds, not invoked directly after raw generation as the only quality step.
- `toolkit-build-source-readiness-contract`: toolkit-source readiness provenance must support both uploader packet artifacts and legacy builder readiness artifacts without requiring watcher ingest sidecars.
- `toolkit-build-report-refresh-contract`: toolkit report freshness must identify readiness/finishing phase outcomes for legacy builder runs and must not mark a report current when readiness was skipped or failed.
- `module-publishability-reporting`: final builder/uploader reports must preserve readiness convergence outcome separately from final publishability outcome.

## Impact

- Affected code is expected in:
  - `web/web_interface.py` legacy socket builder path,
  - `web/extensions/toolkit_homebrew_readiness_gate.py` or a new shared wrapper around it,
  - `web/extensions/toolkit_module_finisher.py`,
  - `web/templates/module_toolkit.html`,
  - existing toolkit/uploader route tests and publication parity tests.
- The uploader route should remain functionally unchanged except for sharing any extracted readiness helper.
- The legacy builder path will become stricter: modules that previously reached final finisher directly may now stop earlier with explicit readiness failure details.
- Merge-safety impact MUST remain low:
  - keep host edits in `web/web_interface.py` thin and marked with `# TABLETOP MODE:`,
  - put reusable pipeline logic in extension modules,
  - avoid changing upstream builder internals unless there is no extension-safe alternative.
- SP/MP compatibility impact should be neutral because this is a toolkit authoring pipeline change, not a gameplay runtime change.
- Rollout risk:
  - readiness artifacts may be hard to adapt because the current readiness gate expects uploader workspace files,
  - stricter gating may expose existing builder defects that were previously hidden until publishability,
  - UI status may confuse operators if readiness and finishing failures are not clearly separated.
- Fallback strategy MUST be fail-closed and explicit:
  - if raw generation succeeds but readiness cannot run, the build must not be reported as complete,
  - if readiness fails, the finisher must not run unless the failure is explicitly classified as a non-blocking media handoff case already handled by the final finisher contract,
  - if report persistence fails, the UI must surface a degraded/error state rather than relying on stale sidebar truth.
