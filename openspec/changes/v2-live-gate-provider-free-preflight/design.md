# Design

## Context

See proposal.md for motivation and `specs/live-gate-preflight/spec.md` for the contract. SP3 already has a row runner, sandbox launcher, host worker, and router-receipt observer. The observer records routing activity but does not supply responses, so it cannot alone meet FR-11's provider-free full-path requirement. The dedicated preflight is separate from the ordinary provider-free pilot test suite: it deliberately exercises the isolated host on port 8360 under the live-window lock, never port 8357, while keeping live booking and pilot-evidence paths distinct.

## Goals / Non-Goals

**Goals:**
- Reuse all 26 frozen SP3 planned rows and the existing sandbox/host lifecycle rather than create a second row driver; leave four replacement-only reserve slots unactivated.
- Exercise a fail-closed stub at the host's routing boundary and prove it cannot reach an upstream provider.
- Make each PF check, row outcome, identity hash, lock transition, and teardown result auditable in a preflight-only report.
- Compare the pinned pre-#105 source with the exact SHA resolved from a separately refreshed origin/main immediately before comparison, never the feature-branch `HEAD`.

**Non-Goals:**
- Run or authorize a live gate, send provider requests, change SP3/SP3b evidence, revise the counterbalance, or score/rate pilot output.
- Change production gameplay, core routing, provider configuration, or runtime defaults.

## Decisions

1. **Keep orchestration in the capture-tooling boundary.** Extend the existing row-runner/launcher/worker path with a preflight controller and reuse the existing driver and receipt evidence. Do not duplicate row orchestration. Install the deterministic stub before the host can dispatch a routed call; any attempted real client/request fails closed. If this cannot be achieved in the isolated tooling boundary, stop rather than add a core-runtime hook or weaken provider-free acceptance. The simplest alternative, receipt observation without a stub, cannot provide provider-free responses.

2. **Declare profiles before observing a preflight, bound to call-site content.** Store a versioned startup/resume call profile for each required fixture-party pair, tied to the 26 planned row identities. A measured lifecycle declaration binds to call-site content, not a commit SHA (Overseer ruling `neq-w1-profile-binds-callsite-content-20261117`): it records fixture and party, each call site (repo-relative path, line, file sha256, count), the total, the sha256 of the stub and driver files that produced the counts, and a provenance manifest of run id and evidence sha256 only. Declarations carry no absolute or `tmp/` path and no source SHA, command, or PYTHONPATH; such a declaration is rejected. Matching is fail-closed: a row matches only when the call sites observed in that preflight run equal the declaration exactly (same sites, counts, total) and every listed file, stub, and driver hash is identical; any difference reports `profile_mismatch` naming what differed, which means re-measure, never a pass. The preflight report that authorizes a booking is unchanged by this: it stays bound to the exact SHA to be run with zero infrastructure failures (FR-11). The run compares receipts to that declaration; a missing profile or a profile learned from the same run blocks readiness. Existing `provider_call` controls and authoritative SP3 receipts are inputs to profile review, not permission to infer unrecorded values or reopen SP3b. Reserve-only rows are not scenarios and remain untouched.

3. **Refresh and freeze the comparison target separately.** The planning base resolved from `refs/remotes/origin/main` is `8d1a9e1ce5d9acda8fb7ff36d8866d28aaaf5624`; retain it as context only, not as the acceptance target. Immediately before comparative execution, a separate preparation step explicitly refreshes origin/main, resolves its full SHA, and freezes that SHA as the comparison input. The comparison runner uses only the frozen SHA and local project-relative `tmp/` snapshots; it performs no fetch, remote lookup, or provider request. If either commit is unavailable locally, block rather than access the network. Compare the 26 planned rows against that target and pre-#105 control `5999af374ded4f56b21b25d68fc10f9520444b51`, sequentially under the shared live-window lock. Leave all four replacement-only reserve slots unactivated. Never substitute feature-branch `HEAD`; preserve the old-source `NameError` result as a non-bookable regression control and write no pilot evidence.

4. **Treat preflight as report-only qualification.** Acquire the shared 8360 live-window lock before binding the host and release it after teardown. Capture the exact intended live command, working directory, and `PYTHONPATH`; source SHA; `requirements-lock.txt` identity; and a canonical, secret-free routing-policy identity hash. Store evidence only below `tmp/router-rollout/<gate>/<run-id>/preflight/`. Report `READY_FOR_BOOKING` only if all PF checks pass with zero infrastructure failures; that label is not a booking ruling or a live-gate PASS. Require the later booked run to match all three identities. The simplest alternative, a dry run that does not bind the real ports or take the lock, would leave PF5/PF9 and the booking boundary untested.

5. **Test stop policy with injected conditions.** Use injected counters, clock, and infrastructure outcomes to show attempt-cap, time-cap, and three-consecutive-infrastructure-failure behavior. These checks exercise the actual driver policy without waiting for live caps, sending providers, or debiting live attempt allowance. Normal preflight traversal separately proves continuation beyond the first path and row.

### Running the preflight

`scripts/live_gate_preflight_run.py` is the runnable entry point; it assembles every `run_preflight_rows_supervised` input from existing helpers and starts hosts only through the controller. `--mode same-sha` (default) binds the report to the clean checkout HEAD and is the normal exact-SHA preflight. `--mode comparison --application {frozen-origin-main,pre-105-control} --tool-sha SHA --tool-tree TREE` verifies the tool tree and the frozen application worktree, runs with the application SHA, and yields a comparison-only report (never booking eligible, no resume checkpoints). Before every lifecycle sandbox preparation, which precedes each host start, a load gate requires 1-minute load < 10 and 5-minute load < 20, waiting at most 30 minutes (checked every 60 s); on timeout no further host starts, the report is BLOCKED, and the summary names `LOAD_GATE`.

## Risks / Trade-offs

- **A stub can hide a real provider integration defect** -> Keep the report explicitly preflight-only; require a separate owner-authorized live run and exact identity match for gate evidence.
- **A missing or stale lifecycle profile can produce a misleading clean result** -> Bind profiles to frozen row identities and to call-site, stub, and driver content hashes, and fail closed on missing or mismatched entries.
- **Port contention can prevent a valid host check** -> Acquire the shared lock and verify required ports before launch; record a blocked preflight rather than reusing a listener.

## Migration Plan

No production migration is required. Implementation adds the preflight contract/tooling and updates the capture skill plus the concise `AGENTS.md` booking rule. Existing pilot rows, counters, results, and evidence remain unchanged.

## Open Questions

None. The lifecycle profile values must be source-backed and declared during implementation; the contract already specifies that missing values block readiness.
