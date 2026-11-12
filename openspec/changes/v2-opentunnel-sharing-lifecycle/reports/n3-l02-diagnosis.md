# N3 L02 Diagnosis

## Summary

N3 live attempt 3 (`n3-20261111-175359`, SHA `c51f572d`) was L02 **FAIL**:
`identity_initialization_contract_failed` with empty `observed`. There were 0
companion launches and 0 `identity_up` invocations. Classification: PRODUCT
defect, not harness or relay/firewall. This is iteration 2 of 3 for L02
diagnosis, not a gate verdict; N3 is not PASS.

## Evidence

Evidence is under
`tmp/router-rollout/v2-network/n3/l02-guard-tooling/runs/`; evidence
directories include `SHA256SUMS`. Diagnostics were local and provider-free:
no relay, provider, booking, or companion launch. The companion remained mode
644 during the run and was restored to 755; inode `16777234:305104355` and
SHA256 `39991ec74bc79e13917d5e7bc309870f7925d364808b33ec535fef2fc29eeaf2`
were verified.

- Run `n3-l02-diagnostic-20261112-073939-44852` guarded the real host on
  `127.0.0.1:8360` with a Python network/child guard. Child-launch, `192.0.2.1`,
  and non-local DNS canaries were refused and recorded. With synthetic blank-key
  config injected in memory, GET status was 200 with
  `state=initializing_required`, `identity_initialized=false`, and 0
  `identity_up_invocations`. The single original POST
  `initialize-identity {confirm:true}` returned HTTP 409,
  `reason=companion_unavailable`.
- That 409 follows from the mandated non-executable companion:
  `resolve_companion` returns `not_executable` via `os.access(..., X_OK)` at
  `web/extensions/opentunnel_sharing/companion.py:133-137`. The run could not
  reach the bootstrap precheck. It shows host/driver request shape,
  Host/Origin/CSRF/auth handling, and profile visibility were fine: the profile
  was ready and the route reached companion resolution.
- After stop, ports 8360/8370 were free by exclusive bind; there were no owned
  sockets, `nonloopback_guard_match_count=0`, and
  `unobserved_egress_count=0`.
- A read-only offline probe used the product `DefaultIdentityObserver` with a
  throwaway profile layout and capture-copy companion path; it launched no
  companion and used no network. Before the fix, service was
  `absent(observed_user_view)`, process and helper were
  `absent(native_process_info_complete)`, yet `_assess_observations` returned
  `unknown`. After the fix it returns `absent`.

## Root cause

`web/extensions/opentunnel_sharing/identity_bootstrap.py`
`_assess_observations` accepted an absent non-service observation only with
basis `proc_scan_complete` or `ps_snapshot_complete`. PR #152 introduced
`native_process_info_complete` in `_KNOWN_OBSERVATION_BASES` and returned it
from `parse_process_info_processes`, but did not add it to the assessor's
allowlist. On macOS, every precheck therefore became `unknown`, and
`initialize_identity` returned state `uncertain` / reason `precheck_unproven`
before invoking `up`. This explains attempt 3's counters. L02 expects HTTP 200,
reason `identity_initialized`, and 1 `identity_up_invocations`.

## Attribution of the blocked connection attempt

Guard-recorded `blocked_network` events in host and driver (and the earlier
unattributed count of one) are `socket.bind(("::1", port None))` calls from
`urllib3/util/connection.py` lines 127/137, its IPv6-availability probe during
import. The port allowlist refused them with `loopback_port_refused`. This was
loopback only: no non-loopback target and no packet left the machine. The
earlier interrupted diagnostic had no stack, so attribution of that single
event to this probe is consistent with, but not proven by, this evidence.

## Profile hypothesis

Refuted for the current gate path. With the prepared state root, the route
passed profile validation and reached companion resolution (409
`companion_unavailable`, not `profile_unavailable`). The earlier 409
`profile_unavailable` came from a diagnostic with an unprepared/absent state
root.

## Fix

PR on branch `fix/n3-identity-observation-basis` adds
`native_process_info_complete` to the accepted absent bases for non-service
observations, with no other trust change. Regression tests include end-to-end
`up` invocation. The live gate now records bounded host-API
`http_status`/`ok`/`reason`/`bootstrap_state`/`status_state`/
`identity_initialized`/`identity_up_invocations` in `observ` for L02 failures
and host-API contract failures in L03-L10. No secrets, bodies, or headers are
recorded.

## Limits/Not claimed

The Python-level guard plus netstat are risk-bounded observations accepted by
the Overseer (ruling `neq-n3-l02-risk-bounded-diagnostic-20261112`), not OS
egress containment. The fix is proven offline only; it remains unproven live
until attempt 4 (new booking, OD-6 preflight at the merged SHA). Linux arm64
remains BLOCKED owner-run-required. A recursive grep earlier may have opened
the capture `config.py` (process lapse, no content returned; Overseer ruling
`neq-n3-l02-audit-scope-20261112`).
