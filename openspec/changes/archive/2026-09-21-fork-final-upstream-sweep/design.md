# Fork Final Upstream Sweep - Design

## Context

`plans/independent-fork.md` approves a two-part pivot: `fork-independence-pivot`
records governance, and this change completes the final behavior sweep. The
sweep is deliberately narrow: a legacy UI output-encoding port and bounded
empty-provider-completion recovery, plus a bounded inspection of upstream #240.

The local worktree already contains partially completed governance changes (ADR
files, guidance updates) and the `fork-independence-pivot` change artifacts;
this change does not depend on those edits being committed and does not modify
them.

## Upstream Reference Baseline

| Item | Value |
|---|---|
| Review date | 2026-09-21 |
| Previous upstream review point | `702796eb55` |
| Upstream tip at final review | `44f1458e1e` (2026-09-20) |
| Review window | 524 upstream commits (2026-08-05 through 2026-09-20) |
| Legacy UI reference | Upstream PR #399, merge commit `2940c9f0` |
| Provider empty-response reference | Upstream `3fa138f7` (issues #161/#162) |
| Provider error reissue reference | Upstream `3e6dbb6f` (issue #240) |
| Fork merge base | `c3604eb35a` (2026-02-19) |
| Fork HEAD at plan creation | `c4b16311` |

No upstream fetch is performed by this change. References are recorded from the
2026-09-21 repository review captured in `plans/independent-fork.md`.

## Goals / Non-Goals

**Goals:**

- Close the legacy template output-encoding gap with fork-native helpers.
- Add bounded, provider-free-tested empty-completion recovery at the fork
  provider boundary without hiding retry logic inside client construction.
- Preserve request shape, GPT-5.6 Luna behavior, fallback policy, and SP/MP
  routing.
- Record the #240 inspection outcome and close the upstream review ledger.

**Non-Goals:**

- No upstream template or provider code import.
- No global Chat Completions migration; only the narrator turn path is wired.
- No refusal/content-filter behavior redesign; those classes retain existing
  handling and are only excluded from empty-transient retry.
- No runtime data, module, or schema change.

## Decisions

### Legacy UI Safety Boundary

Two helpers are added in the legacy template script scope:

- `escapeLegacyHtml(value)` - returns a string safe for HTML text and quoted
  attribute contexts. `null`/`undefined` become `""`; numbers are stringified.
  Escapes `&`, `<`, `>`, `"`, `'`, and backtick. Ordinary game text is
  unchanged in rendered form because escapes are HTML entities.
- `legacyJsonAttribute(value)` - serializes a value with `JSON.stringify` and
  then applies `escapeLegacyHtml`, producing an attribute-safe JavaScript
  expression (for strings: `&quot;Name&quot;`). Handlers receive the same
  runtime value they receive today; the value can no longer terminate the
  attribute or the JS literal.

Call-site policy:

- Literal text and attribute insertion uses `escapeLegacyHtml(...)`.
- Inline handler string/structured arguments use `legacyJsonAttribute(...)`
  (JSON string literals are valid JavaScript string expressions, so handler
  signatures do not change).
- Canonical identity normalization (portrait slugs, routing names) remains a
  separate concern and is not replaced by escaping. Existing `normalizedName`
  slug behavior is preserved.

The helper set is applied to the highest-risk contexts enumerated in the task
list rather than every interpolation site; a broad template rewrite is out of
scope. Existing `.replace(/"/g, '&quot;')` quote-only escaping is replaced by
the shared helpers where those values are display text, attribute text, or
handler arguments.

### Provider Response Boundary

A new fork-native module `utils/provider_response_recovery.py` owns request
execution recovery. `create_chat_client()` remains client construction only.

Classification (`classify_chat_completion`):

- `empty_transient`: no `choices`, no usable message on the selected choice, or
  blank/whitespace-only content - with no refusal marker and no
  `content_filter` finish reason.
- `refusal`: `message.refusal` is a non-empty string.
- `content_filter`: `finish_reason == "content_filter"`.
- `ok`: usable non-blank text.

Recovery (`request_chat_completion_with_recovery`):

- Issues the request, retries only `empty_transient` results, up to
  `EMPTY_RESPONSE_RETRY_LIMIT = 2` retries, forwarding the exact same resolved
  parameters, messages, and timeout each attempt.
- Returns `ok` and non-transient (refusal/content-filter) responses unchanged.
- Raises `EmptyProviderResponseError` after the bounded retry is exhausted.
  The exception carries `attempts`, `context`, and an ASCII-only message with no
  raw provider payload.

Fallback integration:

- `handle_provider_error()` classifies `EmptyProviderResponseError` as
  retryable, so existing call-site fallback blocks trigger exactly as they do
  for retryable exceptions. Fallback requests issued through the helper are
  subject to the same bounded retry; a terminal empty fallback raises again.
- Terminal empty responses follow the same propagation semantics as existing
  non-retryable provider exceptions: the narrator path surfaces the
  deterministic exception instead of assigning blank content, so no empty
  assistant turn, action envelope, or success artifact can be persisted from an
  empty completion. This change is not a crash-handling redesign.

Wiring scope:

- `main.py` `get_ai_response()` narrator call sites: GPT-5 branch primary and
  fallback, and non-GPT5/OpenRouter branch primary and fallback.
- `core/managers/combat_manager.py`, `updates/update_character_info.py`, and
  other call sites are intentionally not rewired; they keep existing behavior
  and are candidates for a later fork change.

### Failure Classes

| Class | Detection | Behavior |
|---|---|---|
| Empty transient | no choices / no message / blank text, no refusal, no content filter | bounded retry, then deterministic `EmptyProviderResponseError` |
| Refusal | non-empty `message.refusal` | no retry; response returned unchanged (existing handling) |
| Content filter | `finish_reason == "content_filter"` | no retry; response returned unchanged (existing handling) |
| Rate limit / timeout / 5xx | provider exception text | unchanged `handle_provider_error` retryable path |
| Auth / quota / invalid request | provider exception text | unchanged non-retryable path |

### Observability

The helper emits bounded ASCII diagnostics: attempt number, stage (primary or
fallback), classification outcome, and terminal status. It MUST NOT log prompt
content, raw provider payloads, credentials, or request bodies. Logging failures
must not alter request behavior.

### #240 Inspection Record

The change performs a bounded code review of the fork provider error/fallback
state for the upstream #240 defect class ("completed provider error reissued").
If the fork already prevents reissuing completed errors, the outcome is recorded
in the change implementation notes and no code is added. If the same defect is
reproduced, the smallest fork-native fix and provider-free coverage are added.

## Risks / Trade-offs

- Risk: escaping breaks rendering for values that are intentionally HTML (for
  example `<br>` in tooltip parts). Mitigation: escape only data-derived values,
  keep intentional markup assembly in code, and run targeted smoke checks.
- Risk: handler argument serialization changes argument expression form.
  Mitigation: JSON literals evaluate to the same runtime values; verify with
  browser smoke and source contracts.
- Risk: bounded retry increases provider requests on persistent empty results.
  Mitigation: retry limit is 2 (3 attempts) for the primary stage only; terminal
  failures raise immediately.
- Risk: scope creep into unrelated call sites. Mitigation: tasks enumerate the
  exact wired call sites; regression suites confirm combat/character paths
  unchanged.

## Rollback

- Revert the UI helper/call-site group independently; retain helper tests if the
  regression is isolated to a call-site group.
- Revert `utils/provider_response_recovery.py` and the narrator wiring
  independently; remove the `handle_provider_error` classification extension in
  the same revert.
- No persistence or schema migration exists to reverse.
