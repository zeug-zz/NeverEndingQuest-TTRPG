# Proposal

## Why

SP3 exposed harness failures that were discovered only during live work, including an import failure, incomplete row continuation, transport loss, fixture omissions, and a host `NameError` fixed by #105. FR-11 moves those checks into a provider-free preflight and makes a clean report at the exact SHA a prerequisite for any later live booking, without treating preflight as gate evidence.

## What Changes

- Add a provider-free preflight for the 26 frozen SP3 planned scenario rows, exercising each full scripted host path on an isolated `Capture_Arena` copy with a stub router; the four replacement-only reserve slots remain unactivated.
- Make PF1-PF9 observable acceptance checks: invocation identity, full row coverage, fixture resolution, declared lifecycle call profiles, transport exchange, injected stop rules, continuation, frozen identity, and teardown.
- Require the live-window lock on port 8360, record no provider calls or consumed live attempt allowance, and write preflight evidence under `tmp/router-rollout/<gate>/<run-id>/preflight/`.
- Require a zero-infrastructure-failure report at the exact SHA to be run before a live booking ruling. Compare pre-#105 commit `5999af374ded4f56b21b25d68fc10f9520444b51` with the full SHA resolved from `refs/remotes/origin/main` after a separate refresh immediately before comparison, then freeze that SHA. Planning base `8d1a9e1ce5d9acda8fb7ff36d8866d28aaaf5624` is context only, not the acceptance target. The comparison/preflight uses local snapshots offline; the old-source control is not booking-eligible and produces no pilot evidence.
- Add the concise FR-11 booking rule to `AGENTS.md` during a later implementation; this proposal does not edit files outside this change directory.

**Non-goals:** No live gate, provider request, pilot rerun, reserve-slot activation, transcript rating, scoring, fixture or counterbalance change, production gameplay change, or claim of a gate PASS. The comparison tests preflight behavior only.

## Capabilities

### New Capabilities
- `live-gate-preflight`: Defines provider-free preflight behavior, booking eligibility, and its evidence contract independently from pilot execution and scoring.

### Modified Capabilities
- None.

## Impact

- Later implementation is expected to add isolated tooling and provider-free tests under `scripts/`, update `.opencode/skills/neq-capture-arena/SKILL.md` and the one-line `AGENTS.md` booking rule, and add the capability contract in this change.
- Uses the 26 planned rows from the frozen SP3 30-slot counterbalance and existing sandbox/host capture boundaries; the four replacement-only slots and pilot artifacts remain unchanged. Both 1-PC and 4-PC rows remain in scope; no gameplay compatibility behavior changes.
- No new dependency or provider-routing change is proposed.
