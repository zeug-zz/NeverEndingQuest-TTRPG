# Task 2.1 Supervised Verification

## Result: PASS (bounded adapter/evidence-reconciliation scenario only)

The provider-free supervised E01/1-PC run at source
`cca4a4c833c15427eb11c78112d3a7aa75ad81a7` exercised one real host startup
and one scripted transport exchange. The retained evidence reconciled through
the validator after the narrow controller LF correction.

| Check | Expected | Observed |
| --- | --- | --- |
| Guard and interpreter | Exact venv/controller/host canaries; deny canary is the only non-loopback attempt | Passed |
| Provider boundary | Stub responses; no upstream request or allowance use | One exchange completed; 9 stub calls |
| Process accounting | Complete guarded census; no uncovered run PID | Complete; no uncovered PIDs |
| Ports and lock | Bind proofs free on 8360/8370; owned lock released | Both free; lock released |
| Evidence reconciliation | Validator reconciles retained run evidence | Passed after controller LF correction |

**Command form:** the supervised provider-free controller/host invocation used
the repository `.venv/bin/python`, with the exact guarded venv invocation and
controller/host canaries. This was not the 26-row integration command and does
not establish full row coverage.

Evidence:
- Profile evidence:
  `tmp/router-rollout/live-gate-preflight/fr11-21-real-e01-01/preflight/rows/pf-fr11-21-real-e01-01-E01/profile-evidence.json`
  SHA-256 `839007b73f86844a52523c513ed38f87755552526df3604b4fe900285ff901c2`.
- Teardown evidence SHA-256:
  `fcebdbbfea81db0b02c21eac764d23ae2aac73ba7e6be467dd527c75b5602050`.
- Preserved state snapshot is under the same run's `preflight/` evidence tree.

## Full 26-row acceptance: BLOCKED / NOT RUN

This supervised E01 run does not verify all 26 planned rows' full scripted host
paths, fixture resolution, declared party sizes, lifecycle profiles, and first
scripted exchanges. Disconnected-location rows and both party sizes are not
established by this single-row run. Four replacement-only reserves remained
unactivated. All declared profiles remain MISSING; the full integration
verification is outstanding and booking is ineligible. This is not a live-gate
PASS and authorizes no booking.

Focused integration tests: 23 PASS. Profile tests: 94 PASS after targeted and
full rerun; an initial transient timeout did not reproduce.
