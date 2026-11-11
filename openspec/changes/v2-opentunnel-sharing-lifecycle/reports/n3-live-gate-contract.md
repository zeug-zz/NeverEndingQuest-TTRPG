# N3 Live Lifecycle Gate Contract

## Authority and freeze

This report is the authoritative frozen contract for the primary-owned N3 live lifecycle gate (Tasks 6.2-6.6). Its live manifest id is `n3-live-lifecycle-v2`. The driver manifest and its digest MUST identify exactly the row definitions, frozen limits, state-root policy, and safety boundaries below. A change to a row, cap, platform verdict rule, or safety boundary requires a reviewed contract revision and a new manifest identity/digest; a builder MUST NOT silently reinterpret this report.

The authorized L01/L02 and L03/L05 observation clarifications were frozen as `n3-live-lifecycle-v1` with manifest SHA-256 `5c17c8e9187140b5d662bdb07e2e13704fef637ae45a6d71e4689ea1d790cde1`. This reviewed contract revision moves gate state outside the repository/evidence tree to satisfy the profile socket-path limit and to prevent teardown from owning the broader evidence directory; L10 now requires removal of only the unique run root and removal of the shared namespace only when empty. The manifest identity is therefore advanced to `n3-live-lifecycle-v2`, whose exact manifest SHA-256 is `a9bb1f3f23df1cd216f627dd1974f7a4702da6d533e7f39a4603ca0d30ca3693`.

## Platform and run environment

- This live run covers macOS arm64 only. Party size is 1.
- Linux arm64 rows are recorded `BLOCKED` with reason `owner-run-required` until a separate owner-run Linux leg is completed. The gate-level N3 verdict remains pending/not PASS while any required platform is BLOCKED.
- Use an isolated Capture_Arena copy at `tmp/combat_capture`, prepared with `scripts/seed_combat_capture.py --prepare --party 1` and validated as the N2 managed host does: the copy is non-symlink and `WEB_PORT == 8360`.
- The host binds `127.0.0.1:8360`; the player listener binds `127.0.0.1:8370`; set `NEQ_OPEN_BROWSER=0`.
- Never run port 8357 or the installed campaign. The facilitator's real profile MUST NOT be touched.
- Place the gate-owned XDG state root outside the repository, Python environment, campaign data, and run evidence. On macOS use `~/Library/Caches/neq-n3g/<id8>`; on an approved non-macOS owner-run use `$XDG_CACHE_HOME/neq-n3g/<id8>`, falling back to `~/.cache/neq-n3g/<id8>`. `<id8>` is the first eight lowercase hexadecimal characters of `sha256(run_id)`. The driver rejects symlinks, wrong ownership, an existing run root, unsafe containment, and a Unix socket path of 104 bytes or more before side effects. Evidence records only `<id8>` and `sha256(os.fsencode(state_root))`, never the raw state path. L10 removes only the unique run root and removes `neq-n3g` only if empty. After preparing the isolated copy, the operator installs the pinned companion into `tmp/combat_capture`; its binary path is `tmp/combat_capture/runtime/opentunnel/v0.6.2/opentunnel-darwin-arm64/opentunnel`. The driver verifies the runtime manifest and digest beneath this capture-copy install root before host launch and never installs or downloads the companion. A companion installed only beneath the repository root does not satisfy this requirement.

The live run requires a separate approved authorization/booking and a clean OD-6 preflight with zero infrastructure failures at the exact SHA to be run. The booking, preflight report, and SHA are bound by the live-window lock record below. The driver MUST refuse to proceed before side effects if those prerequisites or the lock checks fail.

## Frozen caps and execution policy

| Limit | Frozen value |
| --- | --- |
| Driver wall-clock time | At most 3,600 seconds |
| Per-row wall-clock time | At most 300 seconds; L05 at most 420 seconds |
| Companion `serve` launches | At most 4 |
| Companion `up` invocations | At most 1 |
| Relay tunnel creations | At most 2; enforce using launch/up counters plus override attempts, and report the observed count |
| Provider attempts | 0. Set the sandbox host provider budget to 0; if 0 is unsupported, use 1 as the ceiling and any provider-ledger reservation/attempt is FAIL. |
| Automatic retries | 0 |

Fail fast on the first FAIL or infrastructure BLOCKED and guarantee teardown. The known Linux `owner-run-required` platform leg is recorded as BLOCKED and keeps the gate-level verdict pending; it does not authorize a PASS for the macOS leg or overall N3.

## Shared live-window lock protocol

The shared lock is `git-common-dir/neq-coordination/live-window.lock`, a directory containing a single-line JSON `holder.json` and `bookings.log`. The PRIMARY acquires and releases the lock; the driver never acquires or releases it.

`holder.json` MUST contain these fields:

| Field | Required value/meaning |
| --- | --- |
| `booking_id` | Booking identity; must match `--booking-id` |
| `holder` | Exactly `N agent-run` |
| `gate` | Exactly `N3-live` |
| `authorizing_ruling` | The ruling authorizing this booking |
| `window_start` | Authorized live-window start |
| `window_end` | Authorized live-window end |
| `run_id` | Must match `--run-id` |
| `evidence` | Exactly `<run>/capture` for this run |
| `preflight_report` | Must match `--preflight-report` |
| `head` | Full commit SHA; must match `--sha` |
| `frozen_caps` | `{party_size: 1, platform: "macos-arm64", provider_dispatch_attempts: 0, max_tunnel_creations: 2, max_companion_launches: 4, window_hours: <= 3}` |

Before side effects and between rows, the driver verifies the record against the CLI arguments (`--booking-id`, `--run-id`, `--sha`, and `--preflight-report`), the fixed contract values, the approved booking, and the active window. The window MUST NOT be expired. A mismatch or expired window is refused/BLOCKED before proceeding; the driver does not modify the lock.

## Approved relay-loss injection

The only approved relay-loss injection is SIGKILL of the positively identified owned companion child process. The target MUST be a child or descendant of the owned host PID, its executable realpath MUST equal the installed companion path, its UID MUST equal the current UID, and its process start time MUST be after the host start. No other process may be signalled. This tests the same process-death that the supervisor must handle and uses no network manipulation. If the target cannot be positively identified, do not signal a process; record the row BLOCKED.

## Sandbox-only recovery-attempt override

`NEQ_N3_GATE_MAX_RECOVERY_ATTEMPTS` accepts an integer from 1 through 3 and is honored only when all of the following are true:

1. The process runs in the isolated `tmp/combat_capture` copy, which is non-symlink.
2. Configured `WEB_PORT == 8360`.
3. `NEQ_N3_GATE_RUN_ID` matches `^[a-z0-9-]{8,64}$`.

Otherwise the override is ignored with a bounded reason code. The effective number of attempts MUST never exceed the production default of 5. Backoff delays are unchanged. The live driver sets the override to `1`. Outside the valid isolated gate context, production uses its existing default and behavior unchanged.

## Frozen live rows

For every row, an observed unmet PASS criterion with complete and reliable evidence is FAIL. BLOCKED means the required precondition or observation cannot safely be established because of an infrastructure/evidence limitation; it is not a substitute for a failed assertion. The driver stops at the first FAIL or infrastructure BLOCKED, preserves evidence, and attempts guaranteed teardown.

### L01 — `sharing-off-local-play`

- **Precondition:** Owned host is up; sharing is OFF.
- **Action:** Query `GET /api/player-sharing/status`; inspect listener, companion process, and public exposure.
- **Expected observations (PASS):** Status is `off` or `initializing_required` (both sharing-inactive); port 8370 is not listening; no companion process exists; there is no public exposure.
- **Planner clarification (2026-11-11):** `off` and `initializing_required` are both acceptable sharing-inactive status states. This does not relax the required closed player port, absent companion, or no-public-exposure checks.
- **BLOCKED conditions:** Host ownership or the required status/listener/process/public-exposure observations cannot be established safely. Any positive evidence of an unexpected listener, companion, or public exposure is FAIL.

### L02 — `identity-init-once`

- **Precondition:** Owned host is up; the dedicated profile identity is uninitialized; sharing is OFF.
- **Action:** POST `initialize-identity` with `{confirm:true}`, then call it a second time.
- **Expected observations (PASS):** The first call initializes only after a real guarded `up -> status -> down`; the host API reports `identity_initialized=true` and `identity_up_invocations=1`; post-checks show no residual helper or service-manager entry. The second call reports `identity_initialized=true`, an already-initialized reason, and `identity_up_invocations` remains exactly 1.
- **Planner clarification (2026-11-11):** Observe only the existing host API projection (`identity_initialized`, `identity_up_invocations`, and exposed `reason`); do not require internal `bootstrap_state` because it is not projected.
- **BLOCKED conditions:** The companion operation or positive post-checks for helper/service-manager cleanup cannot be performed or observed safely. A failed/extra `up`, missing cleanup, or unexpected second initialization is FAIL.

### L03 — `issue-access-start-auth-entry`

- **Precondition:** Owned host is up; identity initialization has passed; sharing is OFF.
- **Action:** Issue access, start sharing, copy the invitation, and exercise the player boundary over the public URL. Keep the one-time plaintext credential and invitation URL in memory only.
- **Expected observations (PASS):** `issue-access` returns plaintext once; start returns ready; `copy-invitation` returns an HTTPS URL. Over that PUBLIC URL, the player shell returns 200; an unauthenticated protected request returns 401, 403, or 404, is not a 2xx/3xx response, and has a bounded body free of gameplay, state, or session data (including snapshot fields). A 2xx/3xx response or any data-bearing response is FAIL. Host-only paths (`/api/player-sharing/*`, host routes, and host socket events) are refused/404 under the public Host. Login with the credential and exact Host/Origin succeeds and the cookie has Secure, HttpOnly, and SameSite. An authenticated Socket.IO websocket to `/player` receives initial state. A wrong credential is rejected and a forged Origin is rejected.
- **Planner clarification (2026-11-11):** N1 deliberately returns 404 for unauthenticated protected player paths, including `GET /api/player/snapshot`; accepting 404 preserves the N1 boundary. This clarifies the L03 observation criterion only and does not change product behavior.
- **BLOCKED conditions:** The public URL/client path or any required boundary observation cannot be reached or measured safely. Any secret persisted or logged, public host-surface access, rejected valid login, accepted invalid credential/Origin, or missing required cookie/socket property is FAIL.

### L04 — `duplicate-start-idempotent`

- **Precondition:** Sharing is ready for one owned generation with one listener and one owned companion process.
- **Action:** Invoke start a second time and observe generation, owned processes, and listener count.
- **Expected observations (PASS):** The second start returns current state, preserves the same generation, and leaves exactly one owned companion process and one listener.
- **BLOCKED conditions:** Generation identity or positive process/listener ownership/count cannot be established. A new generation, duplicate process, or duplicate listener is FAIL.

### L05 — `relay-loss-bounded-recovery`

- **Precondition:** Sharing is ready; the owned host and companion ancestry are known; the target child satisfies every approved relay-loss injection identity check.
- **Action:** Inject relay loss only by the approved SIGKILL method above, then observe status, invitation, public URL, recovery, host health, and sessions.
- **Expected observations (PASS):** Status becomes degraded within the health interval; the invitation is withdrawn and copy-invitation is refused; the public URL stops serving the player; bounded recovery returns to ready within the overridden policy; host port 8360 health remains unaffected throughout. Recovery restarts only the companion and re-verifies readiness; it does not restart the player listener, so existing valid player sessions are preserved by design. Record, but do not pass/fail on, whether the pre-loss authenticated cookie/socket still works over the public URL (expected observation: the cookie remains valid; the socket must be re-established by the client). PASS additionally requires a fresh authenticated login over the public URL to work after recovery, a request using a stale pre-recovery Origin/Host to be accepted only if it equals the freshly bound origin (record whether the public origin changed), and no unauthenticated access to be possible. The expected result is recovered ready; observed bounded failed/exhausted recovery is FAIL.
- **Planner clarification (2026-11-11):** Recovery is companion-only and preserves the player listener; pre-loss cookie/socket observations are recorded rather than gated, while fresh login, freshly bound origin, and unauthenticated-access checks remain PASS requirements. This clarifies the L05 evidence contract only and does not change product behavior.
- **BLOCKED conditions:** The exact owned child cannot be positively identified (do not signal), or required health/public/session observations cannot be safely collected. Any signal to another process is a safety failure and FAIL.

### L06 — `credential-rotation-revocation`

- **Precondition:** Sharing is ready; a valid old credential, authenticated session/cookie, and connected L03 socket exist in memory only.
- **Action:** Rotate access; test old cookie/session and old credential over the public URL; then test the new credential after readiness.
- **Expected observations (PASS):** Rotation returns a new plaintext credential once; the old cookie/session is rejected; the old credential is rejected; the new credential is accepted after readiness; the L03 socket is disconnected and receives no further events.
- **BLOCKED conditions:** Public authentication/session/socket state cannot be observed reliably. Any old credential/session accepted, new credential rejected after readiness, old socket continuing to receive events, or secret disclosure is FAIL.

### L07 — `stop-sharing`

- **Precondition:** Sharing is ready with an owned route, listener, companion, and active session.
- **Action:** Stop sharing and inspect the public URL, port 8370, companion, sessions, and host health.
- **Expected observations (PASS):** The public URL no longer reaches the player service; port 8370 is closed; the companion is reaped; sessions are invalid; the host remains healthy.
- **BLOCKED conditions:** Route, port, process, session, or host-health observations cannot be safely established. Any remaining reachability, listener, owned process, or valid session is FAIL.

### L08 — `host-exit-restart`

- **Precondition:** Owned host is running with sharing active and its host PID/process ownership is positively established.
- **Action:** Send SIGTERM to the owned host with a bounded wait; inspect cleanup; restart the host and inspect sharing state/reconciliation.
- **Expected observations (PASS):** After exit, ports 8360 and 8370 are free, no companion is orphaned, and the owner record is cleared. After restart, sharing is OFF, reconciliation is clean, and sharing does not auto-start.
- **BLOCKED conditions:** The host PID cannot be positively established or the required port/process/owner-state observations cannot be made. Do not signal an uncertain PID. Any orphan, uncleared owner record, occupied port, or automatic sharing start is FAIL.

### L09 — `revoke-access`

- **Precondition:** Identity is already initialized and sharing can be started again without identity bootstrap.
- **Action:** Start sharing again, verify no new `up` invocation, then revoke access and attempt login/service access.
- **Expected observations (PASS):** Start uses the existing identity with no new `up`; after revoke, login fails closed and no unauthenticated service is available.
- **BLOCKED conditions:** Identity/bootstrap counters or post-revoke public authentication/service behavior cannot be observed reliably. A new `up`, successful revoked login, or unauthenticated service is FAIL.

### L10 — `clean-teardown`

- **Precondition:** The run's gate-owned profile and any gate remote tunnel identity are positively identified; the installed companion path is verified.
- **Action:** Stop sharing; stop the host; delete the gate remote tunnel identity using the installed companion's `delete --yes` with the gate profile environment only; verify deletion via status; verify ports are free and no run processes remain; remove only the gate state root; remove its `neq-n3g` parent only if empty; verify the public URL is unreachable afterwards.
- **Expected observations (PASS):** The gate remote identity is deleted and confirmed absent; ports are free; no run processes remain; only the unique gate state root is removed and its `neq-n3g` parent is removed only if empty; the public URL is unreachable; the installed companion remains in place.
- **BLOCKED conditions:** Ownership of the profile/identity/process or the status/port/public-reachability evidence cannot be established safely. Any deletion outside the gate profile, remaining process/state/port/public reachability, or removal of the installed companion is FAIL.

## Evidence layout, redaction, and verdicts

Write evidence under `<run>/capture` with these artifacts:

- `run.json`
- `rows.jsonl`
- `summary.json` with per-platform verdicts
- A provider ledger copy
- Managed-host output counters only; never raw managed-host output
- `SHA256SUMS`

The state tree is not stored under the evidence directory. `run.json` records
`gate_state_root_id8` and `gate_state_path_sha256`; the raw cache path is not
written to any evidence artifact. On macOS, the default path is
`~/Library/Caches/neq-n3g/<id8>`; Linux remains owner-run-only and uses
`$XDG_CACHE_HOME/neq-n3g/<id8>` or `~/.cache/neq-n3g/<id8>`. Symlinked or
wrong-owner roots, a pre-existing `<id8>` root, repository/venv containment,
or a profile socket path at least 104 bytes long are refused before side
effects. Teardown deletes only `<id8>` and removes `neq-n3g` only when empty.

Redact invitation host/URL, tunnel IDs, credentials, cookies, and CSRF tokens. Evidence MUST NOT contain raw managed-host output or secret values. PASS is allowed only when all required rows PASS on that platform; a BLOCKED row prevents platform PASS. A process exit code never establishes PASS. Since Linux arm64 remains `owner-run-required` BLOCKED until a separate owner-run leg, N3 remains pending/not PASS until every required platform is complete.

## Iteration policy

Allow at most three harness iterations for a FAIL attributed to the harness. Do not automatically retry. A product, security, credential, or budget issue stops the run and is reported; it is not classified as a harness iteration. Every stopped run still attempts guaranteed teardown and preserves redacted evidence.
