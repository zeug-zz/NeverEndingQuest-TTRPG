# Design: Adaptation Media Handoff Gate

## Context

`_maybe_relax_toolkit_media_only_gameplay_gate()` already implements the approved toolkit policy: when every gameplay blocker is a structural missing-media finding and every finding has an allowed manual-handoff outcome, the gate becomes a passing manual-handoff result with visible debt metadata. Legacy readiness applies this helper for `source="toolkit"`.

`run_adaptation_gate_composer()` currently calls `_run_gameplay_gate()` and normalizes its result directly. It therefore retains the nonzero subprocess exit as a blocker and never applies the established policy.

## Decisions

### 1. Reuse the existing policy

The adaptation composer SHALL import and apply the existing toolkit media-only relaxation to the extracted gameplay payload before normalization. No duplicate media classification or new allowlist is permitted.

The adaptation lane uses the same source policy value, `toolkit`, because it is a toolkit-owned staging build and the resulting debt is intended for the existing manual media workflow.

### 2. Preserve evidence and fail closed

The raw gameplay report MUST retain its subprocess exit code, raw bounded command evidence, blocker count, and media findings. The normalized gameplay gate MAY report `effective_status=pass` only when the helper marks `manual_handoff_only=true` and `reason=toolkit_structural_media_handoff_only`.

Normalization MUST preserve the nonzero exit code as telemetry and expose bounded media-debt fields without converting this exact approved handoff into a blocker. Any non-media blocker, mixed blocker set, missing structural finding, or unknown outcome remains blocked.

### 3. No runtime or publication changes

The change affects only adaptation gate evaluation and provider-free tests. It does not generate media, call a provider, alter module files outside the current staging revision, or bypass final publication gates.

## Verification

Tests SHALL cover:

- media-only `Missing base media` blockers with structural `provider_disabled_missing` findings -> effective pass/manual handoff;
- a mixed media plus non-media blocker -> blocked;
- missing monster JSON or strict gameplay findings -> blocked;
- raw `exit_code=1` and debt metadata remain visible;
- the reported Amphail fresh staging replay no longer produces `semantic_revision` solely from media debt.
