# Proposal: Adaptation Media Handoff Gate

## Problem

A fresh adaptation staging build can have complete monster JSON closure while lacking generated base monster media. The established toolkit readiness policy classifies this as manual media handoff debt, but the adaptation gate composer invokes gameplay validation directly and does not apply that policy. The result is `gameplay_exit_code_1`, a mechanical semantic-revision outcome, and an unnecessary retry.

## Scope

- Reuse the existing toolkit-only media-handoff relaxation in the adaptation gate composer.
- Preserve the raw gameplay exit code and media-debt telemetry while making the effective readiness gate pass only for the exact media-only case.
- Keep all non-media gameplay blockers fail-closed.
- Add provider-free regression coverage and replay the reported Amphail staging shape without live-module writes.

## Non-Goals

- No weakening of schema, continuity, semantic, mechanical closure, or non-media gameplay gates.
- No automatic media generation or provider call.
- No change to legacy non-adaptation readiness behavior.
- No publication, registry, campaign, or live-module mutation.
