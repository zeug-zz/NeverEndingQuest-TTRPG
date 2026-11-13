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
`n3-live-lifecycle-v3` with SHA-256
`01750d7e32a8140985a51ad8e0bc8616179c03a1930bcb280f9beb13fdb1acfc`; its rows,
caps, port rules, state-root policy,
live-window lock, evidence, and teardown rules are pinned together. Do not
change them between plan inspection, preflight, booking, and live execution.
A contract change needs review and a new manifest identity/digest.

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

    Confirm manifest ID `n3-live-lifecycle-v3`, digest, row order L01-L10,
    platform set, caps, ports, the one L03 startup narration allowance, and
    `is_gate_pass: false`. `plan` has no side effects.
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
6. Obtain the separate owner authorization and booking. The primary acquires
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
launches, one `up`, two tunnel creations, at most one provider attempt only
during the L03 startup narration, and zero automatic retries. L03 must emit
host-side Socket.IO `start_game` exactly once over polling with Origin
`http://127.0.0.1:8360`. Its `dm_main` receipt must resolve to
`openai/gpt-6-luna`; its priced cost must be at most USD 0.05, and cumulative
narration cost must remain at or below USD 1.00. Missing/unpriced receipts,
retries, extra or out-of-window attempts, and either cost-cap breach fail the
gate. The provider-free OD-6 preflight and offline tests still make no provider
calls. The live command fails fast on the first FAIL or infrastructure BLOCKED
and attempts teardown. Do not start another run or retry automatically.

The process exit status is not a verdict. Read the JSON result and the complete
evidence at `tmp/router-rollout/v2-network/n3/<run-id>/capture/`. Confirm all ten
rows are represented, `SHA256SUMS` verifies, the provider ledger contains
exactly one reservation attributed to the L03 startup window, the receipt
matches the frozen profile/model/task and cost limits, secrets and raw
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
