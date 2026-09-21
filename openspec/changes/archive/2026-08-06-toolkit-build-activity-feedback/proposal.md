## Why

Long-running Module Toolkit jobs currently show one frozen status sentence while normalization, adaptation authoring, ModuleBuilder generation, validation, finishing, or publication work continues. This makes healthy provider or Python processing look stalled, especially when an LLM call takes several minutes.

The GUI needs bounded cosmetic activity feedback without exposing raw stdout, provider payloads, or unverified progress claims.

## What Changes

- Add a reusable GUI activity-message rotation for long-running toolkit states.
- Rotate ASCII-only activity messages at a bounded five-second cadence while the authoritative job remains in the corresponding in-progress phase.
- Cover upload-job normalization, legacy packet/build/readiness/finishing states, adaptation phases, and the direct `module_progress` builder channel.
- Reset the message sequence when the phase changes and clear it on terminal, failed, blocked, or stopped states.
- Keep the existing blinking cursor as the ASCII `|` character.
- Keep existing job status, canonical phase, progress, terminal-state, and bounded-diagnostics payload contracts unchanged.
- Add provider-free source-contract and frontend syntax regression coverage for phase mapping, message rotation, clearing, and raw-payload non-exposure.

## Non-Goals

- Do not capture or proxy global stdout/stderr into the toolkit GUI.
- Do not render raw OpenAI, OpenRouter, HTTP, JSON response, credential, or source payload text.
- Do not claim that a particular sub-operation completed unless the authoritative backend phase reports it.
- Do not change build orchestration, retry budgets, provider parameters, publication gates, registry behavior, or campaign synchronization.
- Do not add a new user-facing mode selector or alter single-player gameplay behavior.

## Capabilities

### New Capabilities

- `toolkit-build-activity-feedback`: Defines bounded, phase-aware, cosmetic progress messages across all Module Toolkit build status channels.

### Modified Capabilities

- None. Existing phase and terminal-status capabilities remain authoritative and retain their current payload contracts.

## Impact

- `web/templates/module_toolkit.html` for the shared activity surface, phase/status mapping, cursor rendering, and direct `module_progress` handling.
- Existing toolkit GUI regression suites for source-contract and payload-redaction coverage.
- No new runtime dependency, API endpoint, database schema, provider call, or persisted artifact.
- Legacy and adaptation status payloads remain backward compatible; the change is presentation-only.

## Rollout And Fallback

- The activity line MUST fail open to the existing frozen status sentence if the activity element or mapping is unavailable.
- The existing status text and diagnostics MUST remain visible when activity rendering fails.
- Rollback consists of removing the activity presentation and retaining the current status polling behavior; no job or module state migration is required.

## Merge Safety And Compatibility

- Prefer one shared frontend helper and thin status-branch hooks over changes to backend job orchestration.
- Preserve existing legacy accurate-ingest and adaptation routing boundaries.
- Preserve direct ModuleBuilder behavior and single-player compatibility.
- Keep user-facing text ASCII-only for Windows console compatibility.
