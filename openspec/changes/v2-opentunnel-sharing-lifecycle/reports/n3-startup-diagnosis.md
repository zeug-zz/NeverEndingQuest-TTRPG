# N3 Startup DNS Diagnosis

## Ruling item

This records follow-up for `neq-n3-fixture-config-dns-20261115`, item 3.

## Test and hostname attribution

The initial failed attribution test is
`N3StartGameOfflineProofTests.test_proof_report_includes_sanitized_egress_attribution`
in `scripts/test_n3_start_game_offline_proof.py`. It configures the fake web
module's `egress_host` as `api.openrouter.ai`. `FakeClient.emit()` then calls
`socket.getaddrinfo(egress_host, 443)` while exercising `start_game`.

The test is intended to exercise `proof.run_proof()`'s `EgressGuard` refusal
and sanitized attribution. The prior builder reported that its initial failed
test run accidentally called the system resolver for `api.openrouter.ai`.
Packet emission is unknown; the available report and source do not establish
whether any DNS packet left the machine.

## Harness protection

The suite activates an offline resolver fence in `setUpModule()` before
importing the proof module. It replaces available `socket` name-lookup entry
points with standard `socket.gaierror` refusals and retains the original
function identities only for exact restoration; they are never called. A
permanent process audit hook refuses resolver audit events, including a
resolver call made through a saved or nested reference. At `tearDownModule()`
the socket and `unittest.mock` state is restored and the audit hook is disabled.
The teardown regression verifies restoration without performing DNS. The test
mock factory rejects attempts to mock resolver entry points, including nested
`patch.object`, dotted `patch`, `patch.dict`, and `patch.multiple` calls.

The negative regression deliberately calls `socket.getaddrinfo()` without an
`EgressGuard`, verifies the refusal and continued test execution, rejects
nested resolver mocks, and verifies the audit refusal boundary. Existing
`EgressGuard` refusal/attribution tests remain in place and assert that those
refusals do not fall through to the harness fence.
