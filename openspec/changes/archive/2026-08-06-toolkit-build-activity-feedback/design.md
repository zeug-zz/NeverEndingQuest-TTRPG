## Context

The Module Toolkit currently has two long-running GUI status surfaces. Upload jobs are polled from the toolkit job endpoint and include legacy and adaptation phases. Direct text-description builds emit `module_progress` events through Socket.IO. The existing upload status renderer already owns the working cursor and has a normalization-only activity ticker, but adaptation and later build phases can leave one message unchanged for several minutes.

The backend phase and terminal fields are already the authoritative state contract. The activity line is intentionally cosmetic and must not become a second progress source.

## Goals / Non-Goals

**Goals:**

- Extend the existing activity surface across upload, adaptation, legacy, and direct-builder phases.
- Keep activity text bounded, ASCII-only, phase-appropriate, and safe to display.
- Make activity changes visible during long polling intervals without increasing backend or provider traffic.
- Preserve the existing status, diagnostics, progress percentage, and terminal-state behavior.
- Make phase changes and terminal transitions reset or clear activity deterministically.

**Non-Goals:**

- Do not capture global stdout or stderr.
- Do not add a per-job log stream or new API endpoint.
- Do not parse provider response text or debug logs for GUI display.
- Do not change backend orchestration, provider parameters, retry budgets, publication gates, registry writes, or campaign synchronization.

## Decisions

### Use one frontend activity state machine

The GUI SHOULD retain one shared activity state containing the active source channel, activity group, message index, and last-advance timestamp. Upload polling and direct `module_progress` events SHOULD call the same presentation helper rather than maintain separate message-rotation implementations.

The helper MUST treat backend status and phase as input only. It MUST NOT write to job state or infer completion from the selected message.

Alternative rejected: adding a global stdout bridge. Toolkit workers and the game loop have different lifecycles, global stream capture could interleave unrelated jobs, and provider debug output may contain raw payloads or credentials.

### Group phases by user-visible work

Stable phase groups SHOULD map to bounded message arrays rather than one message array per internal implementation step. The initial mapping should cover:

- Normalization and source extraction
- Adaptation source context, dossier authoring, and staging
- Adaptation module building and revision rebuilding
- Validation, readiness, deterministic repair, and semantic audit
- Legacy packet building and rebuild preparation
- Finishing, publishability, report agreement, and Markdown generation
- Registry verification, campaign availability, and rollback
- Direct-builder publication progress

Unknown in-progress phases MUST use a generic safe activity group. Adding a new backend phase must not make the GUI fail or expose the phase payload.

### Rotate on the existing frontend cadence

The existing status poll or Socket.IO progress event will trigger the helper, but elapsed-time gating will enforce a five-second minimum between message changes. The first message for a newly active group will display immediately. Repeated polls during a long provider call will not cause rapid flicker.

When the group changes, the index and timestamp will reset. Terminal, error, blocked, stopped, or missing-job paths will clear the activity line while leaving the base status and diagnostics intact.

### Keep status and activity visually separate

The authoritative status line will continue to own the working cursor, which will be the ASCII `|` character. The activity line will be a separate bounded DOM element so diagnostics JSON remains unchanged and activity text cannot be mistaken for a backend status.

The activity element will use text assignment rather than HTML interpolation. Messages will be static repository-owned strings and will not include raw job fields, provider text, source excerpts, or user-controlled content.

### Preserve adaptation redaction boundaries

The adaptation status renderer will continue to take precedence over legacy job rendering and will continue to expose only the bounded adaptation envelope. Activity selection will consume the sanitized phase/outcome fields already available to that renderer. The existing `raw_provider_payload_exposed: false` boundary remains unchanged.

### Test at the presentation contract boundary

Provider-free source-contract tests will verify:

- The ASCII cursor and activity element exist.
- Long-running legacy and adaptation phases select activity groups.
- Direct builder progress receives activity handling.
- Rotation is bounded and phase changes reset the sequence.
- Terminal and unknown states clear or use safe fallback text.
- Raw provider/debug payload text is not rendered by the activity path.

Inline JavaScript syntax, focused toolkit regressions, and repository ASCII compliance remain required verification gates.

## Risks / Trade-offs

- [Risk] Cosmetic text may appear more specific than the actual current sub-operation. -> Use broad work-group wording and never claim completion or exact sub-step success.
- [Risk] A phase mapping may become stale as new adaptation phases are added. -> Keep an explicit generic fallback and add mapping coverage to phase/status contract tests.
- [Risk] Shared activity state could be reset by interleaved upload and direct-builder events. -> Key state by source channel and clear only the channel that owns the displayed activity surface.
- [Risk] Activity updates could distract users during short phases. -> Enforce the five-second minimum and show the first message only when a phase is actually in progress.
- [Risk] Raw provider data could leak through an overly dynamic message path. -> Use static ASCII message arrays and `textContent` only; never derive activity text from response bodies.

## Migration Plan

1. Generalize the existing normalization activity helper and preserve its current message behavior.
2. Add phase/status group mappings for adaptation, legacy, readiness, finishing, publication, and direct-builder channels.
3. Replace the working cursor text with ASCII `|` in the shared status renderer.
4. Add provider-free source-contract assertions and run JavaScript syntax, toolkit regression, and ASCII checks.
5. Roll back by removing the activity element and helper hooks; existing status polling and job payloads require no migration.

## Open Questions

None. The activity text is intentionally cosmetic, static, and non-authoritative; wording can be refined without changing the contract.
