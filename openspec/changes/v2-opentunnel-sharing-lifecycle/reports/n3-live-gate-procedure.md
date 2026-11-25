# N3 Live Lifecycle Gate: Primary Operator Procedure

This procedure is for the primary orchestrator after implementation review.
It does not authorize a live run. The primary must obtain separate owner
authorization and booking, and must first have a clean provider-free OD-6
preflight with zero infrastructure failures at the exact SHA to be run.
Builders and implementation verification must not run this procedure's live
command. A preflight, unit test, exit code, or macOS-only result is not an
overall N3 PASS.

## Frozen contract and platform verdict

The authoritative contract is
[`n3-live-gate-contract.md`](n3-live-gate-contract.md). The live manifest is
`n3-live-lifecycle-v4` with SHA-256
`b754bb6fe3fdd206fb96d68ea972c741fc524f0477db71a523792459772b8ee4`; its rows,
caps, port rules, state-root policy,
live-window lock, evidence, and teardown rules are pinned together. Do not
change them between plan inspection, preflight, booking, and live execution.
A contract change needs review and a new manifest identity/digest.
The v4 change requires a fresh exact-SHA OD-6 preflight and a new matching
booking; do not reuse a v3 preflight or lock record.

The live leg is macOS arm64 only, with party size 1, host port 8360, and player
port 8370. Linux arm64 remains `BLOCKED` with reason `owner-run-required` until
a separate owner-run leg completes. Therefore N3 remains pending/not PASS even
if every macOS row passes. Never use port 8357, the installed campaign, or the
facilitator's real OpenTunnel profile.

## Before booking

1. Use the repository root, `.venv/bin/python`, and exactly `PYTHONPATH=.`.
   Confirm the worktree is clean and select a new run ID matching
   `n3-[a-z0-9][a-z0-9-]{0,62}`. Record the exact 40- or 64-character lowercase
   SHA that will be booked.
2. Inspect the driver without starting the host, checking ports, creating
   evidence, or touching state:

   ```sh
   RUN_ID="n3-$(date -u +%Y%m%d-%H%M%S)-$$"
   SHA="$(git rev-parse HEAD)"
   PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python scripts/n3_live_lifecycle_gate.py --help
   PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python scripts/n3_live_lifecycle_gate.py plan
   ```

    Confirm manifest ID `n3-live-lifecycle-v4`, digest, row order L01-L10,
    platform set, caps, ports, one `start_game` event, exactly two ordered L03
    tasks (`action_prediction`, then `dm_main`), two provider attempts with no
    fallback, the USD 0.05 combined per-run cap, and `is_gate_pass: false`.
    `plan` has no side effects.
3. Prepare and validate a fresh isolated `Capture_Arena` copy at
   `tmp/combat_capture` using the repository's Capture_Arena preparation
   procedure (`scripts/seed_combat_capture.py --prepare --party 1`). Confirm it
   is not a symlink and has `WEB_PORT == 8360`. Do not substitute the installed
   campaign or a user campaign.
4. From the repository root, install the pinned companion into that prepared
   copy using the explicit operator-consent flags:

   ```sh
   PYTHONPATH=. .venv/bin/python -m \
     scripts.network_packaging.opentunnel_installer \
     --install-root tmp/combat_capture --install
   ```

   The live driver never installs or downloads the companion. Confirm the
   runtime manifest and digest resolve from `tmp/combat_capture` (a companion
   present only under the repository root is irrelevant):

   ```sh
   PYTHONPATH=. .venv/bin/python - <<'PY'
   from pathlib import Path
   from web.extensions.opentunnel_sharing.companion import (
       resolve_companion,
       verify_companion_digest,
   )
   from web.extensions.opentunnel_sharing.service import load_companion_manifest

   install_root = Path("tmp/combat_capture")
   manifest = load_companion_manifest(install_root)
   result = resolve_companion(
       install_root, manifest, system="Darwin", machine="arm64"
   )
   if (
       result.state != "resolved"
       or result.path is None
       or result.expected_sha256 is None
       or not verify_companion_digest(result.path, result.expected_sha256)
   ):
       raise SystemExit("Capture-copy companion digest verification failed.")
   print("Capture-copy companion digest verified:", result.expected_sha256)
   PY
   ```

5. Confirm the OD-6 provider-free preflight report has zero infrastructure
   failures, covers every required preflight row and teardown check, and binds
   the same SHA and run ID. Its expected path is
   `tmp/router-rollout/v2-network/n3/<run-id>/preflight/preflight.json`.
   Follow [`n3-lifecycle-gate-procedure.md`](n3-lifecycle-gate-procedure.md)
   for the preflight invocation. Preflight is not the live gate and does not
   prove public lifecycle behavior.
6. Complete the provider-free preintegrate proof and four-check seed guard
   before booking. Choose a fresh run ID and confirm its report does not
   already exist:

   ```sh
   PREINTEGRATE_RUN_ID="n3-$(date -u +%Y%m%dT%H%M%SZ)-$$"
   PREINTEGRATE_REPORT="tmp/router-rollout/v2-network/n3/start-game-proof/${PREINTEGRATE_RUN_ID}/preintegrate.json"
   if [ -e "$PREINTEGRATE_REPORT" ] || [ -L "$PREINTEGRATE_REPORT" ]; then
     echo "RUN-ID-ALREADY-USED" >&2
     exit 2
   fi
   PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python \
     scripts/n3_start_game_offline_proof.py \
     --mode preintegrate \
     --sandbox-root tmp/combat_capture \
     --run-id "$PREINTEGRATE_RUN_ID"
   ```

   Run this provider-free seed guard now, then repeat it after all other
   booking checks and immediately before creating the lock or writing the
   booking:

   ```sh
   PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python - <<'PY'
   import json
   import sys
   from pathlib import Path
   from scripts.n3_start_game_offline_proof import check_capture_seed_provider_free

   check_names = (
       "registry_has_no_unregistered_modules",
       "provider_free_startup_seed",
       "no_active_combat",
       "no_history_user_messages",
   )
   checks = check_capture_seed_provider_free(
       Path("tmp/combat_capture").resolve(strict=True)
   )
   result = {
       name: isinstance(checks, dict) and checks.get(name) is True
       for name in check_names
   }
   print(json.dumps(result, sort_keys=True, separators=(",", ":")))
   if not all(result.values()):
       print("SEED-CHECK-FAILED", file=sys.stderr)
       raise SystemExit(1)
   PY
   ```

   Both runs of all four checks must pass; do not bypass either.
7. Run the provider-free websocket transport precheck:

   ```sh
   PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python \
     scripts/n3_live_lifecycle_gate.py precheck-websocket
   ```

   Require exit status 0 and `"available": true`. If unavailable, the output
   names `websocket-client`; stop without booking. The check starts no host or
   tunnel and makes no provider calls.
8. Obtain the separate owner authorization and booking. The primary acquires
   the shared `git-common-dir/neq-coordination/live-window.lock` using the
   exact `holder.json`/`bookings.log` protocol and fields in the contract; the
   driver does not acquire, release, or repair the lock. Confirm the booking,
   active window, preflight path, run ID, SHA, ports, and frozen caps match.
   Stop if any value is missing, expired, or mismatched.

The driver rechecks the seed and active `n3-luna`/`openai/gpt-6-luna` profile
from the isolated capture before starting the host. These checks are static and
fail closed; do not substitute a different capture or model profile.

## Gate-owned state and safety checks

The driver creates a private per-run XDG state root outside the repository,
campaign, Python environment, and evidence tree. On macOS its default is
`~/Library/Caches/neq-n3g/<id8>`. For an approved non-macOS owner-run the base is
`$XDG_CACHE_HOME`, or `~/.cache` when unset, followed by `/neq-n3g/<id8>`.
`<id8>` is the first eight lowercase hex characters of `sha256(run_id)`. The
driver refuses symlinks, wrong ownership, an existing run root, unsafe
containment, or a profile Unix socket path of 104 bytes or more before host
side effects. Do not redirect state into the repository, evidence directory,
campaign, `.venv`, or `venv`, and do not manually reuse or remove a pre-existing
`<id8>` path.

Evidence records only the state-root `id8` and a SHA-256 digest of its encoded
path; it never records the raw cache path. L10 deletes only that run's state
root. It removes the shared `neq-n3g` namespace only if it is still the same
private directory and is empty; unrelated cache entries are retained.

## Harness diagnostics (observation only)

Per ruling `neq-n3-attempt12-l03-counters-20261117`, the driver now captures
bounded, observation-only diagnostics that never change row order, caps,
deadlines, or pass/fail logic (except the dedicated environment-load abort
below). The frozen manifest digest is unchanged by this instrumentation.

- Caught `HostApiError` reason codes (including `host_api_action_invalid`,
  `host_api_payload_invalid`, `host_api_payload_too_large`,
  `host_api_timeout_invalid`, and `managed_host_ownership_failed`) now
  propagate into `failure_diagnostic.reason_code` instead of falling back to
  `unclassified_reason`.
- Each row's `observed.step_timings` records a bounded, fixed-allowlist set
  of sub-step elapsed seconds (`context.monotonic()`-based, max
  `MAX_STEP_TIMING_ENTRIES` entries).
- Each row's `observed.load_samples` records bounded 1/5/15-minute
  `os.getloadavg()` samples (row start, every `LOAD_SAMPLE_INTERVAL_SECONDS`,
  and row end; max `MAX_LOAD_SAMPLES_PER_ROW` entries, `unavailable` on
  `OSError`). `run.json` carries a bounded `environment_load_summary` (max
  1-minute load observed, sample count) for the whole run.
- If the 1-minute load average exceeds `LOAD_ABORT_ONE_MINUTE_THRESHOLD` for
  `LOAD_ABORT_CONSECUTIVE_SAMPLES` consecutive samples, the active row stops
  and is recorded `BLOCKED` with reason `environment_load` (never
  `FAIL`/`PASS`); normal teardown still runs and later rows fail-fast
  `BLOCKED` as usual.
- Teardown now also attempts identity cleanup when the host is stopped or
  unresponsive outside the L10 golden path (the attempt-12 incident: an L03
  `host_counters_unavailable` BLOCKED row left a live companion identity
  behind because teardown only ran cleanup on an unconfirmed companion
  start). If this run's own gate state root never had any profile artifacts
  (for example an early L01 failure before identity init), cleanup records
  `identity_cleanup_result = "not_needed"` and runs no companion command;
  this is a clean no-op, not a refusal. Otherwise cleanup is attempted only
  when the owner record and profile/path both match this run; any mismatch
  refuses with no companion command run.

## One authorized live run

Run once only, from the clean repository at the booked SHA, with the active
booking and lock in place:

```sh
RUN_ID="<booked-run-id>"
SHA="<booked-full-sha>"
BOOKING_ID="<booking-id>"
PREFLIGHT="tmp/router-rollout/v2-network/n3/${RUN_ID}/preflight/preflight.json"
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python scripts/n3_live_lifecycle_gate.py run \
  --run-id "$RUN_ID" \
  --sha "$SHA" \
  --booking-id "$BOOKING_ID" \
  --preflight-report "$PREFLIGHT" \
  --party-size 1
```

The live command starts the owned host on `127.0.0.1:8360`, performs the
contracted public lifecycle observations through the player listener on
`127.0.0.1:8370`, and can create a real public tunnel. It allows at most 3,600
seconds total, 300 seconds per row (420 for L05), four companion `serve`
launches, one `up`, two tunnel creations, exactly two provider attempts only
during the L03 startup window, and zero automatic retries. L03 must emit
host-side Socket.IO `start_game` exactly once over polling with Origin
`http://127.0.0.1:8360`. The ordered task receipts must be exactly
`action_prediction` then `dm_main`, each from profile `n3-luna`, resolving to
`openai/gpt-6-luna`, with one attempt and no fallback. Both receipts must be
complete and priced; their combined cost must be at most USD 0.05. Cumulative
`dm_main` narration cost must remain at or below USD 1.00. Missing, repeated,
extra, reversed, out-of-list, refused, retried, fallback, unpriced, or
out-of-window attempts/receipts, and either cost-cap breach fail the gate. The
provider-free OD-6 preflight and offline tests still make no provider calls.
The live command fails fast on the first FAIL or infrastructure BLOCKED and
attempts teardown. Do not start another run or retry automatically.

The process exit status is not a verdict. Read the JSON result and the complete
evidence at `tmp/router-rollout/v2-network/n3/<run-id>/capture/`. Confirm all ten
rows are represented, `SHA256SUMS` verifies, the provider ledger contains
exactly two reservations attributed to the L03 startup window, the two receipts
match the frozen ordered tasks/profile/model, each has no retry or fallback,
and their combined cost and cumulative narration cost meet the frozen limits.
Secrets and raw
managed-host/narration output are absent, and teardown proves the identity,
processes, ports, public reachability, and state root were handled as
contracted. The L03 startup/readiness result must remain recorded even if a
cost assertion fails. Preserve the redacted evidence for primary review. A
FAIL or BLOCKED stops the rollout for review; at most three separately approved
harness iterations are allowed only for a failure attributed to the harness.
Do not repeat a product, security, credential, budget, or uncertain-ownership
failure.

Even when all macOS rows pass, report the macOS platform result separately and
keep overall N3 pending/not PASS while Linux is `owner-run-required` BLOCKED.
Do not claim N4 gameplay/browser coverage, installer readiness, release
readiness, or overall lifecycle completion from this gate.

## Provider-free L03 startup wait proof

`scripts/n3_l03_startup_wait_proof.py` is a provider-free diagnostic for the
L03 startup wait's real-runtime signal (the Socket.IO `status_response`
`game_started` flip that replaced the `/api/player-sharing/status`
`local_runtime` flag, which only ever becomes `True` once player sharing is
turned ON -- something the startup wait never does). It proves two things:

1. `--self-test` (provider-free, no real host, no real network, no sandbox):
   runs the real gate driver function,
   `scripts.n3_live_lifecycle_gate._start_local_game_runtime`, against a
   synthetic in-process Socket.IO/HTTP host built entirely inside the script,
   with a valid but reservation-free provider ledger. It proves the driver's
   wait genuinely depends on a real `status_response.game_started` flip
   (observed `True` after `status_response` carries it), not on
   `local_runtime` (observed `False` throughout via a loopback-bridged real
   Flask-test-client route call), and that it does not spuriously PASS: with
   `game_started`/`runtime_alive` real but no usage receipts ever recorded
   (the self-test's synthetic host never writes telemetry), the driver
   correctly ends with `_failed("startup_provider_task_receipt_missing")`.

2. Real-host mode (never run by this agent; the primary runs it, and it is
   never a gate pass or a substitute for the live L03 gate row): delegates
   the sandboxed real-host lifecycle to the already-reviewed, **unmodified
   call contract** of `n3_start_game_offline_proof.run_startup_diagnostic()`,
   which proves the real host's `game_started` flip and `game_output`
   delivery with the two startup router tasks stubbed locally (no priced
   provider call, no egress). No `host_importer` is ever passed -- passing
   one marks that tool's own `real_host_imports` tripwire unverified
   (`real_host_importer = host_importer is None`), which would BLOCK its
   verdict for a reason unrelated to this proof, as discovered when an
   earlier revision of this proof incorrectly passed one. Instead this
   script passes only `run_startup_diagnostic()`'s new, optional,
   exception-safe `observe_running_host` keyword (default `None`, leaving
   that function's behavior byte-identical when unset). That hook,
   `observe_real_host()`, is called by the diagnostic itself, with its own
   real Socket.IO test client and the real imported `web.web_interface`
   module, strictly after startup narration has been observed and strictly
   before the diagnostic queues its own shutdown input -- i.e. while the
   real host is still running. The hook: (a) emits a real `request_status`
   through that same real client and records the real `status_response`
   payload, expecting `game_started=True`; (b) builds the real
   `/api/player-sharing/status` projection from that same real web module's
   Flask app test client (no profile/identity creation, no writes outside
   the sandbox) and records `local_runtime`, expecting `False`. The hook
   never imports `scripts.n3_live_lifecycle_gate` or any other repository
   module itself -- it uses only the client and web module objects it is
   given. Any hook exception or non-mapping/unbounded return fails the
   diagnostic's own report closed (its verdict stays `BLOCKED`, its
   `observation_failure` field names the failure) and never alters its
   tripwire accounting or `real_host_importer` flag.

   Two further root causes surfaced from a real-host run and were fixed
   without touching `run_startup_diagnostic()`'s own call contract beyond the
   additive facade described next:

   - **Event stealing.** The hook was originally handed the diagnostic's own
     raw Socket.IO test client. Calling `client.get_received()` from the hook
     (to read `status_response`) pops every pending event off that client's
     queue, including the later `game_started`/`game_output` events the
     diagnostic's own event scan still needs -- so observing the host made
     the diagnostic fail with `startup narration output was not delivered
     within the bound`. The fix: `run_startup_diagnostic()` now hands the
     hook a small `_ObservationClient` facade exposing only `emit()` and
     `get_received()`; the facade's `get_received()` delegates to the real
     client and also appends every returned event, unmodified, to a
     `hook_drained_events` list owned by `run_startup_diagnostic()` itself.
     The diagnostic's own later event scan reads
     `list(hook_drained_events) + client.get_received()`, so no event the
     hook drained is ever lost.

   - **Wrong local_runtime path.** `observe_real_host()` originally read
     `status.get("local_runtime")` from the `/api/player-sharing/status`
     projection. The real route (`web/routes/player_sharing_routes.py`,
     `_status_projection`) never puts `local_runtime` at that top level; it
     is a boolean under `status.checks.local_runtime`. Reading the wrong
     path always returned `None`, which the hook recorded as the fixed
     `"non_bool"` reason, which the wrapper then always scored as
     `sharing_local_runtime_false=False` -- a built-in FAIL regardless of the
     real host's state. `_sharing_status_projection()` is rewritten to read
     `status["checks"]["local_runtime"]` and to return a small, bounded,
     always-attributable mapping: `http_status` (int), `json_decoded` (bool),
     `ok` (bool), `status_present` (bool), `checks_present` (bool), and
     `local_runtime` -- a real `bool` when found, else a fixed reason string
     (`http_error`, `json_invalid`, `status_missing`, `checks_missing`, or
     `non_bool`). `observe_real_host()` surfaces all of these bounded fields
     in its observation mapping, and `_compose_worker_result()` carries the
     reason forward as an optional `sharing_local_runtime_reason` field in
     this proof's own result (and folds it into the `FAIL` reason string), so
     a 503 `service_unavailable` from the real route, or any other shape
     mismatch, is reported honestly and attributably -- never as a silent
     `False`, and never as a `PASS`.

   A second root cause surfaced after the `host_importer` fix: this script's
   own module scope imported `scripts.n3_live_lifecycle_gate` (needed only by
   `--self-test`) unconditionally, and that import pulls
   `web.extensions.opentunnel_sharing.native_process_info`, and therefore the
   repository's `web`/`utils` packages, into the running process's
   `sys.modules`. `run_startup_diagnostic()`'s own sandboxed-import tripwire
   then correctly refused to count `real_host_imports` as verified, because
   `web.web_interface` was effectively already importable from outside the
   sandbox. The fix is structural: `scripts.n3_live_lifecycle_gate` is now
   imported lazily, only inside the functions `--self-test` actually calls,
   and real-host mode itself runs as a parent process plus a short-lived
   `--worker` subprocess, mirroring `n3_start_game_offline_proof.py`'s own
   `--diagnostic-worker` split. The parent (`run_real_host_proof`) validates
   arguments, runs `n3_start_game_offline_proof.run_guard_self_test()` exactly
   as that script's own `main()` does, resolves this proof's own result path
   and refuses to proceed if it already exists, then launches a fresh worker
   interpreter (cwd `REPO_ROOT`, a credential-free environment from
   `n3_start_game_offline_proof._startup_diagnostic_worker_environment()`,
   stdin/stdout/stderr discarded, a bounded timeout) that has never imported
   the gate module or `web`/`utils`. That worker calls
   `run_startup_diagnostic(..., observe_running_host=observe_real_host,
   isolated_worker=True)` directly, composes a small, strictly bounded
   verdict mapping from the diagnostic's own report (`_compose_worker_result`),
   and writes only that bounded mapping to this proof's own result file (the
   full diagnostic report is written separately, by `run_startup_diagnostic`
   itself, under `startup_diagnostic.json` next to it). The parent reads that
   result file back and strictly re-validates it -- bounded file size, and
   every field checked against a fixed key/type allowlist
   (`_validate_worker_result`: no missing or extra keys, `verdict` one of
   `PASS`/`BLOCKED`/`FAIL`, every boolean field strictly `bool`, every string
   field bounded and non-empty) -- before trusting or printing it. A worker
   crash, timeout, missing result file, oversized result file, or malformed
   result file all resolve to an explicit `BLOCKED` verdict from the parent,
   never a silent pass. This script's own final verdict is `PASS` only if the
   diagnostic's own verdict is `PASS` AND the hook's recorded
   `status_response.game_started` is `True` AND the hook's recorded
   `local_runtime` is `False` AND no provider/network attempt was ever
   counted by the diagnostic; otherwise it reports `BLOCKED` (diagnostic
   itself did not PASS, or the worker/result path failed) or `FAIL`
   (diagnostic PASSed but a hook check did not) with an explicit fixed
   reason. It never re-runs the gate driver's own `_start_local_game_runtime`
   against this real host, because doing so would require a second, separate
   real game start and would hit the host's "already starting or running"
   guard.

Run commands:

```sh
# Provider-free self-test (any agent may run this)
.venv/bin/python -m scripts.n3_l03_startup_wait_proof --self-test

# Real-host mode (primary only; never run against the installed campaign or
# port 8357 -- uses the capture-arena sandbox convention, default
# tmp/combat_capture, port 8360)
.venv/bin/python -m scripts.n3_l03_startup_wait_proof \
  --sandbox-root tmp/combat_capture \
  --run-id n3-l03-startup-wait-proof-4 \
  --startup-timeout 30
```

The self-test writes its own JSON report under
`tmp/router-rollout/v2-network/n3/l03-startup-wait-proof/<run-id>/`.
Real-host mode writes that same bounded wrapper result (written by its
`--worker` subprocess, re-validated and printed by its parent process) plus
the underlying diagnostic's own, separately written report under
`<same-dir>/startup_diagnostic.json`. Neither mode substitutes for, implies,
or counts toward a live L03 gate PASS.
