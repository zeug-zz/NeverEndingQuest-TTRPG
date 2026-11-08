<!-- SPDX-FileCopyrightText: 2024 MoonlightByte -->
<!-- SPDX-License-Identifier: Fair-Source-1.0 -->

# N2 browser gate: reviewed owner-run procedure

This is an operator handoff, not authorization to run the live gate. Obtain the
separate owner/Overseer review and record the live-window booking first. The N2
gate is serialized with S's SP3b: do not proceed until the booking is released
and port 8360 is available. Never use the installed campaign or port 8357.

## Scope and safety boundaries

- The only campaign tree the managed driver can start or alter is this
  repository's prepared `tmp/combat_capture/`. It validates that exact
  non-symlink path, `config.py` has exactly `WEB_PORT = 8360`, and the original
  player manifest/assets match their recorded SHA-256 digests.
- Do not start a host manually for a managed run. `--manage-sandbox-host`
  refuses occupied ports, starts the prepared sandbox with the repository
  `.venv/bin/python`, fixed loopback ports 8360/8370, and no browser auto-open,
  then terminates only the detached process group it created. It does not run
  seed/prepare or stop unrelated processes.
- During missing/broken-bundle phases, the driver stops its owned host and
  changes only `tmp/combat_capture/web/frontend/dist/`. It restores the original
  directory in `finally` and verifies the manifest plus every listed asset
  digest. A cleanup/restoration failure is a FAIL; preserve any
  `managed-*-original-dist` recovery directory under the run evidence and do
  not prepare over it until the original tree is restored.
- The gate always uses two different player browser instances: Player A is
  system Chrome launched by Playwright as `chromium.launch({ channel: "chrome" })`;
  Player B is Playwright Firefox from the pinned package. The facilitator UI
  uses a separate BrowserContext on Player A's Chrome instance. `run.json`
  records the commit SHA, clean-checkout state, and name and actual version for
  Player A, Player B, and the host UI context. WebKit is not a replacement for
  either required player engine. The gate writes no browser storage state, HAR,
  or trace archive. Console text is bounded and redacts password, verifier,
  cookie, authorization, and CSRF values. Do not add raw network or storage
  artifacts.
- Gameplay probes submit player and host inputs. The sandbox may process them
  through its configured provider path. Run only when that provider execution
  is separately authorized. If any provider is invoked, run the provider-identity
  extractor described below. It reads timestamped router response receipts and
  available provider trace records from the sandbox, scopes them to `run.json`,
  and writes a separate `provider-identity.json` sidecar. Never hand-edit
  `run.json` or `summary.json`; never infer provider, model, or attempt count
  from browser output or configuration. An absent or incomplete source remains
  `unknown` with its reason.
- The player password is read with Bash `read -rs` into an exported variable.
  The scrypt verifier is generated from that environment value, never from a
  command-line argument. `web/extensions/player/auth.py --make-verifier`
  accepts only the flag and reads the password using `getpass.getpass`; it has
  no password argument. The managed host child receives the verifier, while
  the driver removes the plain login password from the child's environment.
  Never put either value in shell history, evidence, screenshots, or notes.

## Static preflight (no browser, process, or evidence side effects)

From the repository root, run before the booking window. The dry-run must not
create its selected evidence directory:

```sh
npm --prefix web/frontend run test:e2e -- --list
npm --prefix web/frontend run test:n2-gate -- --help
npm --prefix web/frontend run test:n2-gate -- --dry-run --manage-sandbox-host
```

Confirm the scenario IDs below are listed. Stop if any command fails or the
dry-run reports anything other than the fixed `127.0.0.1:8360` / `127.0.0.1:8370`
pair and no side effects. A live run without `--manage-sandbox-host` is refused
before evidence creation or endpoint contact. The provider budget cannot be
applied safely to an externally started host; `--dry-run` remains available
without managed mode.

## Browser prerequisites

Before the live booking, confirm system Chrome is installed and launchable. The
frontend lockfile pins Playwright to 1.65.0; install its matching Firefox browser
before the run window with:

```sh
npx --prefix web/frontend playwright install firefox
```

The gate has no `--browser` selector: every run launches Chrome for Player A and
Playwright Firefox for Player B. WebKit is not selected by this gate and cannot
replace either required browser. The host UI runs in its own Chrome
BrowserContext. Do not install browsers or dependencies during the live run.

## Live-window lock and frozen caps

Acquire a separate shared live-window lock for each party-size run, before
starting its host. First use a clean `~/Projects/neq-v2-network` checkout at a
recorded SHA (post-merge `main` is preferred), and confirm ports 8360 and 8370
are free. Resolve the shared coordination directory and acquire the lock with
one atomic `mkdir`; if it fails, do not retry or start the gate:

```bash
cd ~/Projects/neq-v2-network
C="$(git rev-parse --path-format=absolute --git-common-dir)/neq-coordination"
LOCK="$C/live-window.lock"
PARTY_SIZE=1
RUN_ID="p${PARTY_SIZE}-chrome-firefox-$(date -u +%Y%m%dT%H%M%SZ)-$$"
RUN_EVIDENCE="tmp/router-rollout/v2-network/n2-${RUN_ID}"
command -v lsof >/dev/null || { echo "lsof is required for the port pre-check"; exit 1; }
for port in 8360 8370; do
  if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null; then
    echo "Port $port is occupied; do not acquire the N2 lock"
    exit 1
  fi
done
mkdir "$LOCK" || { echo "Live-window lock is held; do not retry"; exit 1; }
```

Immediately after `mkdir` succeeds, create `holder.json` and append the same
JSON line to `bookings.log`. Use holder `owner-run for N`, gate `N2`, and
authorizing reference `rulings/N.md` at `2026-11-06T18:55:13Z`, item 3. Freeze
 a maximum three-hour window and a **30 outbound HTTPX attempt budget per
 party-size run**. In managed mode the driver injects the budget, a unique
 sandbox-local ledger path, and the run ID into the owned `tmp/combat_capture`
 host. The host validates the isolated root and installs a sync/async HTTPX
 pre-dispatch guard; each non-loopback request reserves a slot under a
 cross-process file lock before transport send. SDK retries, router fallbacks,
 direct OpenAI image/TTS calls, background requests, and inherited-environment
 child processes use the same ledger. Loopback is not counted. If activation is
 partial, invalid, outside the isolated root, or the ledger cannot be reserved,
 the Python dispatch process refuses startup or refuses the request; it never
 continues unbudgeted. The 31st attempt is recorded as a refusal and is not
  sent. Both the gate driver and the Playwright suite require a matching
  active-ledger record before launching gameplay browser input, so direct
  `test:e2e` runs without managed enforcement fail before browser startup. The
  driver copies the ledger into run evidence after teardown and makes any refusal
  a FAIL with its reason. There is no manual Ctrl-C cap boundary and no unbudgeted
  non-managed gameplay mode.

 `provider-identity.json` remains a separate receipt-derived identity artifact:
 it extracts model/provider observations and may report an unknown or
 incomplete receipt count. It neither reserves budget nor substitutes for the
 transport ledger. Freeze the browser matrix: Player A system Chrome, Player B
 Playwright 1.65.0 Firefox, and host UI system Chrome. There are no operator
 retry loops or gate reruns. The repeated-request-ID scenario deliberately sends
 the same command twice but queues one input; it is not permission to retry a
 provider call.

For one party-size run, set `PARTY_SIZE` and `RUN_EVIDENCE` to that run's
values, then write the holder and acquisition line immediately after the lock
directory is created:

```bash
python3 - "$C" "$LOCK" "$PARTY_SIZE" "$RUN_EVIDENCE" <<'PY'
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

coordination, lock, party_size, evidence = sys.argv[1:]
start = datetime.now(timezone.utc).replace(microsecond=0)
record = {
    "booking_id": f"N2-N-{start.strftime('%Y%m%dT%H%M%SZ')}",
    "holder": "owner-run for N",
    "gate": "N2",
    "authorizing_ruling": "rulings/N.md@2026-11-06T18:55:13Z#3",
    "window_start": start.isoformat().replace("+00:00", "Z"),
    "window_end": (start + timedelta(hours=3)).isoformat().replace("+00:00", "Z"),
    "frozen_caps": {
        "window_hours": 3,
        "outbound_httpx_attempts_per_party_size_run": 30,
        "party_size": int(party_size),
        "browsers": ["player-a:system-chrome", "player-b:playwright-firefox-1.65.0", "host:system-chrome"],
    },
}
holder_path = Path(lock) / "holder.json"
line = json.dumps(record, sort_keys=True, separators=(",", ":"))
with holder_path.open("x", encoding="ascii") as stream:
    stream.write(line + "\n")
with (Path(coordination) / "bookings.log").open("a", encoding="ascii") as stream:
    stream.write(line + "\n")
print(record["booking_id"], evidence)
PY
```

After managed teardown, verify both ports are free, append a release entry with
the booking ID, release time, and evidence path to `bookings.log`, remove
`holder.json`, then `rmdir "$LOCK"`. Do not release while a listener remains.
Repeat the acquire/run/release sequence for the other party size.

After confirming both ports are free with the same `lsof` check, append the
release record before removing the holder and lock:

```bash
python3 - "$C" "$LOCK" "$RUN_EVIDENCE" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

coordination, lock, evidence = sys.argv[1:]
lock_path = Path(lock)
holder_path = lock_path / "holder.json"
holder = json.loads(holder_path.read_text(encoding="ascii"))
release = {
    "event": "release",
    "booking_id": holder["booking_id"],
    "released_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    "evidence_path": evidence,
}
with (Path(coordination) / "bookings.log").open("a", encoding="ascii") as stream:
    stream.write(json.dumps(release, sort_keys=True, separators=(",", ":")) + "\n")
holder_path.unlink()
lock_path.rmdir()
PY
```

## Approved live-run sequence

1. Confirm system Chrome and Playwright 1.65.0 Firefox are installed, the
   separate booking and lock are active, ports 8360 and 8370 are unused, the
   checkout is clean, and provider execution is authorized. The driver enforces
   and records the clean SHA. Do not install dependencies or browsers during
   this run.
2. Build the player bundle once from the project root:

   ```sh
   npm --prefix web/frontend run build
   ```

3. Prepare a fresh isolated sandbox for **one party size only**. Do not prepare
   while a managed host is running or while a bundle recovery directory remains:

   ```sh
   .venv/bin/python scripts/seed_combat_capture.py --prepare --party 1
   ```

4. Export the fixed endpoints and prepare the credentials in the approved Bash
   shell. Use a fresh Bash shell for each party-size run and do not enable
   command tracing (`set -x`); the EXIT trap clears both credentials when the
   run shell closes:

   ```bash
   IFS= read -r -s -p "Player password: " NEQ_N2_PLAYER_PASSWORD
   printf '\n'
   export NEQ_N2_PLAYER_PASSWORD
   NEQ_PLAYER_PASSWORD_VERIFIER="$(.venv/bin/python - <<'PY'
   import os
   from web.extensions.player.auth import make_verifier

   print(make_verifier(os.environ["NEQ_N2_PLAYER_PASSWORD"]))
   PY
   )"
   export NEQ_PLAYER_PASSWORD_VERIFIER
   trap 'unset NEQ_N2_PLAYER_PASSWORD NEQ_PLAYER_PASSWORD_VERIFIER' EXIT
   export NEQ_N2_HOST_URL=http://127.0.0.1:8360
   export NEQ_N2_PLAYER_URL=http://127.0.0.1:8370
   ```

   `auth.py --make-verifier` is an alternate interactive CLI that accepts no
   password positional argument and uses `getpass.getpass`; never pass the real
   password on its command line.

5. Run the 1-PC gate. The driver starts the sandbox host itself; do not launch
   `run_web.py` separately:

   ```sh
   npm --prefix web/frontend run test:n2-gate -- \
     --party-size 1 --manage-sandbox-host \
     --evidence-dir "tmp/router-rollout/v2-network/n2-${RUN_ID}"
   ```

    One invocation exercises the fixed Chrome/Firefox player pair and the
    separate Chrome host context. Runs are serial; never share one arena or port
    pair across concurrent runs.

6. Only after the managed 1-PC run exits, provider identity is extracted, the
   first booking is released, and teardown is confirmed, start a fresh Bash
   shell. Repeat steps 1-5 with `PARTY_SIZE=4` and `--party 4`, which creates a
   new run ID, lock booking, and isolated sandbox:

   ```sh
    .venv/bin/python scripts/seed_combat_capture.py --prepare --party 4
    PARTY_SIZE=4
    RUN_ID="p${PARTY_SIZE}-chrome-firefox-$(date -u +%Y%m%dT%H%M%SZ)-$$"
    RUN_EVIDENCE="tmp/router-rollout/v2-network/n2-${RUN_ID}"
    npm --prefix web/frontend run test:n2-gate -- \
      --party-size 4 --manage-sandbox-host \
      --evidence-dir "tmp/router-rollout/v2-network/n2-${RUN_ID}"
    ```

    Do not reuse the 1-PC sandbox or run the party sizes concurrently.

7. After each managed driver run exits and teardown is confirmed, extract
   provider identity to a separate file. Do not edit the driver evidence:

   ```sh
   node web/frontend/e2e/provider-identity.mjs \
     --evidence-dir "$RUN_EVIDENCE"
   ```

   Preserve `provider-identity.json` beside `run.json` and `summary.json`, then
   release that run's lock only after verifying both ports are free. If the
   attempt total is unknown, preserve the reason and do not replace it with zero.

## Required scenario and assertion matrix

Each party-size run must produce a record for every ID below; any missing or
failed assertion is FAIL, not waived:

| Scenario ID | Required observation |
| --- | --- |
| `party-coherence` | Player A (Chrome) and Player B (Firefox) are independent browser instances, show the expected 1-PC/4-PC party and same active PC, and a separate Chrome BrowserContext has host gameplay controls. |
| `host-transcript-ordering` | A host UI input appears once in both player transcripts, after the previous cursor, with strictly increasing message sequence. |
| `active-pc-sync-switch-race` | A selection synchronizes to both clients; 4-PC competing selections at one revision converge to one accepted revision increment. For 1-PC, the sole PC remains the only selectable option. |
| `sheets-initiative-combat-busy-state` | The approved active-PC sheet, seeded initiative/combat order, and displayed busy/ready state match canonical snapshots. |
| `repeated-request-id` | Reusing the same request ID returns the original accepted receipt and adds one transcript input, not two. |
| `busy-input` | Concurrent submissions produce a visible busy result for the rejected item and do not append it. |
| `refresh-reconnect` | Refresh and offline/online reconnect resynchronize from the server; an unsent draft is not replayed. |
| `server-instance-change` | With the player page still open, the owned host restarts. The pending input becomes visibly uncertain; its request ID is not sent again, its transcript marker is not duplicated, and a fresh login/snapshot has a different instance ID and the expected party. |
| `missing-bundle` | Only the sandbox `web/frontend/dist` is absent during host restart; host gameplay UI remains usable, the player listener is unreachable/port-free, and original manifest/asset digests are restored. |
| `broken-bundle` | One manifest-listed sandbox asset is corrupted during host restart; host gameplay UI remains usable, player startup fails closed, and original manifest/asset digests are restored. |
| `host-only-route-event-and-bundle-probes` | Player origin refuses the host-only HTTP/socket probes and loaded player JavaScript has no privileged host markers. |

The driver refuses live mode without `--manage-sandbox-host`, because it cannot
enforce the provider budget on an external process. Socket-only evidence never
passes the real-browser gate.

## Evidence review and teardown

Each unique `tmp/router-rollout/v2-network/n2-<run-id>/` contains:

- `run.json`: run/build SHA, clean-checkout state, Player A Chrome version,
  Player B Firefox version, separate host-context Chrome version, OS, party
  size, endpoint pair, scenario catalog, provider identity placeholder, and
  managed sandbox process ownership metadata (no passwords/verifiers), plus
  provider-budget activation, reservation/refusal counts, and ledger-copy status.
- `provider-attempt-ledger.jsonl`: the sandbox transport ledger copied after
  managed teardown. Its activation/header and per-request reservation/refusal
  records contain process, time, host, method, and path without query strings;
  it contains no headers, request bodies, or credentials. Preserve refusal rows
  even when the gate fails.
- `provider-identity.json`: extractor-generated provider/model identities,
  observed attempt rows, count completeness, source availability, and explicit
  unknown reasons. It is a separate sidecar; `run.json` and `summary.json` are
  never hand-edited.
- `summary.json`: aggregate PASS/FAIL/BLOCKED counts and the reviewed run
  identity.
- `scenarios.jsonl`: expected and observed assertions, per-scenario verdicts,
  UTC timestamps, and evidence paths.
- `screenshots/`: separate player/host UI snapshots, including uncertainty and
  post-restart resynchronization for the instance-change phase.
- `console.jsonl` and `playwright-test-results/`: bounded diagnostics; no HAR,
  browser storage state, or trace archive.

Review all records and screenshots before assigning the primary verdict. Check
`provider-identity.json` if any input invoked a provider, confirm the original
bundle digests, and verify both ports are free after the driver exits.
The driver stops only its own host group; it does not stop arbitrary processes.
Preserve evidence before any owner-controlled sandbox cleanup. If managed
teardown or bundle restoration fails, leave the evidence/recovery copy intact,
record FAIL/BLOCKED, and resolve the cleanup before preparing another sandbox.
The primary orchestrator owns the final gate verdict; a zero driver exit alone
does not replace review.

## Exit codes

- `0`: all browser assertions pass, no lifecycle scenario is blocked, and
  managed teardown/restoration checks pass.
- `1`: an assertion, browser, evidence, managed-host, restoration, or runner
  failure occurred.
- `2`: at least one lifecycle scenario is BLOCKED because managed mode was not
  enabled. BLOCKED is not a PASS.
