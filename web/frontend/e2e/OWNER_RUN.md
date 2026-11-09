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
  non-symlink path, `config.py` has exactly one top-level standalone literal
  `WEB_PORT = 8360` assignment (with an optional trailing Python `#` comment),
  and the original player manifest/assets match their recorded SHA-256 digests.
  Config validation parses Python syntax with the repository's fixed
  `.venv/bin/python` and never imports or executes `config.py`; only a generic
  pass/fail result is emitted.
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
- The default browser set is `chrome+firefox`: Player A is system Chrome
  launched by Playwright as `chromium.launch({ channel: "chrome" })`; Player B
  is Playwright Firefox from the pinned package. The facilitator UI uses a
  separate BrowserContext on Player A's Chrome instance. An explicit
  `--browsers chrome` run has one Chrome player plus the separate host context;
  it never launches Firefox or substitutes a second Chrome player. Every
  Firefox-dependent check is recorded `BLOCKED` with reason
  `firefox-unavailable-in-sandbox`, beside independent Chrome check results.
  Any such BLOCKED check prevents an overall PASS. `run.json` and
  `summary.json` record requested/run browser sets, actual versions for launched
  roles, and blocked checks. WebKit cannot replace either player engine. The
  gate writes no browser storage state, HAR, or trace archive. Console text is
  bounded and redacts password, verifier, cookie, authorization, and CSRF
  values. Request diagnostics retain only bounded metadata for exact
  player-origin `/socket.io/` requests; they never retain query strings, full
  URLs, or header/cookie values, and inaccessible header observations are
  `unknown`. Do not add raw network or storage artifacts.
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
- The restricted `--agent-run` path requires both `--manage-sandbox-host` and
  `--browsers chrome`. Use it only for the exact prepared project-local
  `tmp/combat_capture/` tree; the driver validates that root, the repository
  `.venv/bin/python`, and original bundle digests before generating anything.
  It rejects non-empty inherited `NEQ_N2_PLAYER_PASSWORD` or
  `NEQ_PLAYER_PASSWORD_VERIFIER` values, generates no credentials in dry-run,
  and creates a fresh password in-process. Python creates its verifier using
  stdin, not argv. The password is sent only to the Playwright child and the
  verifier only to the owned host child. Neither is written to argv, logs, or
  evidence. This mode does not change the owner-supplied credential path or the
  default `chrome+firefox` behavior.

## Fail-fast and stopped-run handling

- The driver validates the Playwright child exit/signal/error result and every
  required persisted scenario/check record before starting managed lifecycle
  scenarios. A failed child, timeout, missing/malformed required evidence,
  failed Chrome check, non-Firefox BLOCKED check, operator interruption, or
  provider-budget refusal/exhaustion stops further scenario dispatch.
- `server-instance-change`, `missing-bundle`, and `broken-bundle` run serially.
  After the first stop, every required scenario/check not executed is written as
  `BLOCKED` with the bounded stop cause; do not infer PASS from omitted records.
  The only expected non-stopping block is `firefox-unavailable-in-sandbox` on a
  Firefox-only check in an explicit Chrome-only run. Valid Chrome checks and
  managed lifecycle scenarios continue, but Firefox blocks still prevent an
  overall PASS.
- A stop does not skip cleanup: the driver still attempts bundle restoration,
  owned host/browser teardown, provider-ledger copy, and final run/summary
  evidence. Review the stop cause and all evidence before deciding what to do
  next. The driver does not automatically retry or resume; any separately
  authorized later invocation requires a new reviewed run and evidence path.
- If Playwright `beforeAll` fails, `setup-failure.json` is captured before page,
  context, or browser teardown. It contains only a fixed setup stage/category,
  expected/observed readiness, an optional early build ID, safe-or-skipped
  screenshot outcomes, and bounded request-diagnostic counts; never copy an
  exception string into evidence. Player screenshots require the fixed player
  origin, canonical `NeverEndingQuest player` heading, exact `Log out` button,
  no password field, and a known Connected/Disconnected/Connecting/loading
  status; disconnected but authenticated is eligible. Mask form/editable
  contents and recognized credential-bearing controls before capture. Login,
  unknown, or wrong-origin pages are explicitly skipped. Host screenshots still
  require the loaded host UI. A missing or empty
  `scenarios.jsonl` is expected only alongside a valid setup-failure record;
  malformed, unreadable, or contradictory results still fail closed. All
  required gameplay scenarios remain BLOCKED and unexecuted.
- The managed host's stdout/stderr streams are drained and discarded rather
  than retained. `managed-host-output.json` contains only bounded per-stream
  byte counters/truncation flags and process exit metadata accumulated across
  host restarts. Never add raw child output to run records, console output, or
  other evidence. The historical browser handshake root cause remains
  unconfirmed; an in-process missing-Origin reproducer does not establish what
  headers the historical browser sent.
- The actual Playwright child streams feed a bounded counter-only collector.
  `driver-output.json` contains capped stdout/stderr byte counts and truncation,
  exit status/signal, and a fixed spawn category; raw text and exception details
  are not persisted. Existing terminal output still uses its established
  credential-redaction path; do not add a raw driver log to evidence.

## Provider-free full pre-booking preflight

After the fix is merged, run this complete offline preflight from the clean
merged checkout before any booking. It prepares and checks a fresh 1-PC sandbox,
then repeats with a fresh 4-PC sandbox. It does not start a host, browser, or
provider request and creates no evidence. Never print or inspect `config.py`;
managed validation reads it privately and reports only pass/fail.

Do not call `assertGatePortsFree()` or `isLoopbackPortFree()` during this
preflight: both use a temporary socket bind. Use read-only `lsof` checks for
8360 and 8370 instead:

```bash
command -v lsof >/dev/null || { echo "lsof is required for the offline port check"; exit 1; }
check_n2_ports() {
  for port in 8360 8370; do
    if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null; then
      echo "Port $port is occupied; stop before booking"
      return 1
    fi
  done
}
check_n2_ports
```

Run the driver listing/help checks and the in-memory agent credential regression.
The credential test creates a throwaway password/verifier in memory, passes the
password only on child stdin, validates it with the real player auth parser, and
prints neither value:

```sh
npm --prefix web/frontend run test:e2e -- --list
npm --prefix web/frontend run test:n2-gate -- --help
node --test web/frontend/e2e/agent-run-credentials.node-test.mjs
```

For each party size, prepare a fresh sandbox and run the complete source/bundle/
identity preflight. `readWorkspaceIdentity()` obtains the clean SHA and
worktree state; `validateManagedSandboxRoot()`, `validateSandboxPython()`, and
`readVerifiedBundleSnapshot()` exercise the managed root, fixed project
interpreter, and bundle digest checks without creating a host. The dry run
checks the agent-run credential environment guard and prints a plan, but does
not generate credentials. Keep both inherited credential variables unset.

```bash
for party in 1 4; do
  .venv/bin/python scripts/seed_combat_capture.py --prepare --party "$party"
  node --input-type=module <<'NODE'
import { resolve } from "node:path";
import { validateManagedSandboxRoot, validateSandboxPython } from "./web/frontend/e2e/managed-host.mjs";
import { readVerifiedBundleSnapshot } from "./web/frontend/e2e/managed-lifecycle.mjs";
import { rejectInheritedAgentCredentials } from "./web/frontend/e2e/agent-run-credentials.mjs";
import { readWorkspaceIdentity } from "./web/frontend/e2e/workspace-identity.mjs";

const root = process.cwd();
const sandbox = validateManagedSandboxRoot(root, resolve(root, "tmp/combat_capture"));
validateSandboxPython(root);
readVerifiedBundleSnapshot(root, sandbox);
const identity = readWorkspaceIdentity(root);
if (identity.git_sha === "unknown" || identity.git_worktree_state !== "clean") {
  throw new Error("Preflight requires a readable SHA and clean worktree.");
}
rejectInheritedAgentCredentials(process.env);
console.log(JSON.stringify({
  git_sha: identity.git_sha,
  worktree: "clean",
  managed_sandbox: "valid",
  sandbox_python: "valid",
  player_bundle: "valid",
  agent_credentials: "inherited values absent",
}));
NODE
  (
    unset NEQ_N2_PLAYER_PASSWORD NEQ_PLAYER_PASSWORD_VERIFIER
    npm --prefix web/frontend run test:n2-gate -- \
      --dry-run --manage-sandbox-host --browsers chrome --agent-run --party-size "$party"
  )
  check_n2_ports
done
```

Stop on any failure, unknown SHA, dirty worktree, invalid sandbox/interpreter,
bundle digest mismatch, inherited credential, dry-run error, or occupied port.
This preflight does not acquire a lock, bind a socket, create credentials, start
the driver live, or authorize booking. After both party sizes pass, preserve the
exact SHA and outputs for the owner/Overseer review.

## Static preflight (no browser, process, or evidence side effects)

From the repository root, run before the booking window. The dry-run must not
create its selected evidence directory:

```sh
npm --prefix web/frontend run test:e2e -- --list
npm --prefix web/frontend run test:n2-gate -- --help
npm --prefix web/frontend run test:n2-gate -- --dry-run --manage-sandbox-host
( unset NEQ_N2_PLAYER_PASSWORD NEQ_PLAYER_PASSWORD_VERIFIER; npm --prefix web/frontend run test:n2-gate -- --dry-run --manage-sandbox-host --browsers chrome --agent-run )
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

The default is `chrome+firefox`, launching Chrome for Player A and Playwright
Firefox for Player B. `--browsers chrome` is an explicit reduced-coverage mode
for the sandbox decision: it runs Chrome-applicable assertions in one Chrome
player and records all Firefox-dependent checks as BLOCKED. It can never produce
an overall PASS. Do not install or launch Firefox for this Chrome-only run;
Firefox work is separate. WebKit is not selected and cannot replace either
required browser. The host UI runs in its own Chrome BrowserContext. Do not
install browsers or dependencies during a live run.

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
RUN_ID="p${PARTY_SIZE}-chrome-$(date -u +%Y%m%dT%H%M%SZ)-$$"
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
        "browsers": ["player-a:system-chrome", "host:system-chrome"],
        "browser_set": "chrome",
        "default_browser_set": "chrome+firefox",
        "firefox_check_reason": "firefox-unavailable-in-sandbox",
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

1. For the default `chrome+firefox` set, confirm system Chrome and Playwright
   1.65.0 Firefox are installed. For the current Chrome-only sandbox decision,
   use only Chrome and do not install or launch Firefox. In either mode, confirm
   the separate booking and lock are active, ports 8360 and 8370 are unused, the
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

4. For the ordinary owner-supplied `chrome+firefox` run, export the fixed
   endpoints and prepare credentials in the approved Bash shell. Use a fresh
   Bash shell for each party-size run and do not enable command tracing
   (`set -x`); the EXIT trap clears both credentials when the run shell closes:

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

   For the restricted Chrome-only sandbox agent run, use a fresh shell with no
   non-empty owner password/verifier variables and do not execute the credential
   setup above. The driver validates sandbox confinement before generating its
   ephemeral credentials; dry-run mode generates none.

5. Run the 1-PC gate. The driver starts the sandbox host itself; do not launch
   `run_web.py` separately:

   ```sh
   npm --prefix web/frontend run test:n2-gate -- \
     --party-size 1 --manage-sandbox-host \
     --evidence-dir "tmp/router-rollout/v2-network/n2-${RUN_ID}"
   ```

    This retains the default Chrome+Firefox player pair and separate Chrome
    host context. The Chrome-only sandbox agent mode instead uses:

    ```sh
    unset NEQ_N2_PLAYER_PASSWORD NEQ_PLAYER_PASSWORD_VERIFIER
    export NEQ_N2_HOST_URL=http://127.0.0.1:8360
    export NEQ_N2_PLAYER_URL=http://127.0.0.1:8370
    npm --prefix web/frontend run test:n2-gate -- \
      --party-size 1 --manage-sandbox-host --browsers chrome --agent-run \
      --evidence-dir "tmp/router-rollout/v2-network/n2-${RUN_ID}"
    ```

    Chrome assertions still run in this mode; every Firefox-dependent check is
    recorded BLOCKED, so overall status cannot be PASS. Runs are serial; never
    share one arena or port pair across concurrent runs.

6. Only after the managed 1-PC run exits, provider identity is extracted, the
   first booking is released, and teardown is confirmed, start a fresh Bash
   shell. Repeat steps 1-5 with `PARTY_SIZE=4` and `--party 4`, which creates a
   new run ID, lock booking, and isolated sandbox:

   ```sh
    .venv/bin/python scripts/seed_combat_capture.py --prepare --party 4
    PARTY_SIZE=4
     RUN_ID="p${PARTY_SIZE}-chrome-$(date -u +%Y%m%dT%H%M%SZ)-$$"
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

## Chrome-only `--agent-run` booking and live review

This is a separate, narrower agent-run procedure; it does not replace or alter
the owner-supplied `chrome+firefox` path above. The primary Chrome headless
channel smoke is already PASS, but it is only a smoke check, not N2 evidence.
The ruling at `2026-11-08T11:03:59Z` authorizes this bounded Chrome-only
procedure. **The PR still requires Overseer approval before any live run.**
Apply the s10.2 port prechecks below immediately before atomic lock acquisition;
the booking window is at most three hours.

Use a fresh run ID and a distinct evidence directory for each invocation. The
following is the same `live-window.lock`, `holder.json`, and `bookings.log`
contract as the owner-run procedure, with the agent-run holder and gate fields:

```bash
cd ~/Projects/neq-v2-network
C="$(git rev-parse --path-format=absolute --git-common-dir)/neq-coordination"
LOCK="$C/live-window.lock"
PARTY_SIZE=1
RUN_ID="p${PARTY_SIZE}-agent-chrome-$(date -u +%Y%m%dT%H%M%SZ)-$$"
RUN_EVIDENCE="tmp/router-rollout/v2-network/n2-chrome/${RUN_ID}"
command -v lsof >/dev/null || { echo "lsof is required for the s10.2 port pre-check"; exit 1; }
for port in 8360 8370; do
  if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null; then
    echo "Port $port is occupied; do not acquire the N2-chrome lock"
    exit 1
  fi
done
mkdir "$LOCK" || { echo "Live-window lock is held; do not retry acquisition"; exit 1; }
python3 - "$C" "$LOCK" "$PARTY_SIZE" "$RUN_EVIDENCE" <<'PY'
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

coordination, lock, party_size, evidence = sys.argv[1:]
start = datetime.now(timezone.utc).replace(microsecond=0)
record = {
    "booking_id": f"N2-chrome-{start.strftime('%Y%m%dT%H%M%SZ')}",
    "holder": "N agent-run",
    "gate": "N2-chrome",
    "authorizing_ruling": "2026-11-08T11:03:59Z",
    "window_start": start.isoformat().replace("+00:00", "Z"),
    "window_end": (start + timedelta(hours=3)).isoformat().replace("+00:00", "Z"),
    "frozen_caps": {
        "window_hours": 3,
        "outbound_httpx_attempts_per_party_size_run": 30,
        "party_size": int(party_size),
        "browsers": ["player-a:system-chrome", "host:system-chrome"],
        "browser_set": "chrome",
        "default_browser_set": "chrome+firefox",
        "firefox_check_reason": "firefox-unavailable-in-sandbox",
    },
}
lock_path = Path(lock)
line = json.dumps(record, sort_keys=True, separators=(",", ":"))
with (lock_path / "holder.json").open("x", encoding="ascii") as stream:
    stream.write(line + "\n")
with (Path(coordination) / "bookings.log").open("a", encoding="ascii") as stream:
    stream.write(line + "\n")
print(record["booking_id"], evidence)
PY
```

After booking, build the approved bundle if needed, prepare a fresh sandbox for
this party size, and run exactly one managed Chrome invocation. Do not start a
host manually. Keep owner credentials unset; `--agent-run` generates credentials
only after managed-sandbox preflight. Do not use `set -x`.

```bash
npm --prefix web/frontend run build
.venv/bin/python scripts/seed_combat_capture.py --prepare --party "$PARTY_SIZE"
(
  unset NEQ_N2_PLAYER_PASSWORD NEQ_PLAYER_PASSWORD_VERIFIER
  export NEQ_N2_HOST_URL=http://127.0.0.1:8360
  export NEQ_N2_PLAYER_URL=http://127.0.0.1:8370
  npm --prefix web/frontend run test:n2-gate -- \
    --party-size "$PARTY_SIZE" --manage-sandbox-host --browsers chrome --agent-run \
    --evidence-dir "$RUN_EVIDENCE"
)
node web/frontend/e2e/provider-identity.mjs --evidence-dir "$RUN_EVIDENCE"
```

Each invocation gets its own fail-closed 30 outbound HTTPX attempt budget and
ledger; the 31st attempt is refused before send. Never pool or carry budget
between invocations. There are no retry loops. Permit at most one
infrastructure-only retry per party size, and only when the failed invocation
produced no gameplay output. A retry uses a new run ID, evidence directory,
booking, and fresh 30-attempt ledger. Do not retry gameplay/provider activity,
an assertion failure, or an invocation that produced gameplay output. Complete
party size 1, extract provider identity, verify teardown, and release its booking
before preparing and booking party size 4; never run them concurrently. After
party 1's release, set the following values and repeat the port prechecks,
atomic booking, managed run, extraction, teardown, and release blocks above for
party 4. If using a fresh shell, reinitialize `C` and `LOCK` as in the booking
block and use this `PARTY_SIZE` value instead of its initial `1`:

```bash
PARTY_SIZE=4
RUN_ID="p${PARTY_SIZE}-agent-chrome-$(date -u +%Y%m%dT%H%M%SZ)-$$"
RUN_EVIDENCE="tmp/router-rollout/v2-network/n2-chrome/${RUN_ID}"
```

Before releasing either booking, require the managed driver to have exited and
verify that both listeners are gone:

```bash
for port in 8360 8370; do
  if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null; then
    echo "Port $port still has a listener; do not release the booking"
    exit 1
  fi
done
```

Then use the release block above with this run's `$RUN_EVIDENCE`; it appends the
release record before removing `holder.json` and the lock. Review evidence under
`tmp/router-rollout/v2-network/n2-chrome/<run-id>/`. Firefox-dependent checks
remain BLOCKED, so at most the Chrome portion may be judged PASS by the Overseer
after review. This does not pass N2: keep N2 and OpenSpec task 6.2 open.

## Required scenario and assertion matrix

Each party-size run must produce a record for every ID below; any missing or
failed assertion is FAIL, not waived. Scenario records classify each browser
check independently. In Chrome-only mode every Firefox-dependent check is
BLOCKED with reason `firefox-unavailable-in-sandbox`; it is not silently waived,
and Chrome passes do not make the overall run PASS:

| Scenario ID | Required observation |
| --- | --- |
| `party-coherence` | Chrome Player A's snapshot party members and active PC match the host Chrome context's canonical `request_party_data` response; when requested, independent Firefox Player B agrees too. Host gameplay controls remain available. |
| `host-transcript-ordering` | A host UI input appears once in Chrome and, when requested, Firefox transcripts, after the previous cursor and in strictly increasing sequence order. |
| `active-pc-sync-switch-race` | Chrome selection is validated; when Firefox is requested, both clients synchronize and 4-PC competing selections at one revision converge to one accepted revision increment. For 1-PC, only the canonical PC is selectable. |
| `sheets-initiative-combat-busy-state` | The approved active-PC sheet, seeded initiative/combat order, and displayed busy/ready state match canonical snapshots. |
| `repeated-request-id` | Reusing the same request ID returns the original accepted receipt and adds one transcript input, not two. |
| `busy-input` | Chrome receives a visible busy result for the rejected item without transcript append; independent Firefox concurrency is checked when requested. |
| `refresh-reconnect` | Chrome, and when requested Firefox, resynchronize after refresh/reconnect; unsent drafts are not replayed. |
| `server-instance-change` | With player page(s) still open, the owned host restarts. Chrome, and when requested Firefox, visibly retains uncertainty, does not replay the request, and resynchronizes to a new instance ID and expected party. |
| `missing-bundle` | Only sandbox `web/frontend/dist` is absent during host restart; host UI remains usable, the player listener is unreachable/port-free in the available browsers, and original digests are restored. |
| `broken-bundle` | One sandbox asset digest is corrupted during host restart; host UI remains usable, player startup fails closed in available browsers, and original digests are restored. |
| `host-only-route-event-and-bundle-probes` | Each requested player browser's origin refuses host-only HTTP/socket probes and its loaded JavaScript has no privileged host markers. |

The driver refuses live mode without `--manage-sandbox-host`, because it cannot
enforce the provider budget on an external process. Socket-only evidence never
passes the real-browser gate.

## Evidence review and teardown

Owner-supplied runs use `tmp/router-rollout/v2-network/n2-<run-id>/`. The
Chrome-only `--agent-run` evidence root is
`tmp/router-rollout/v2-network/n2-chrome/<run-id>/`. Both contain:

- `run.json`: run/build SHA, clean-checkout state, requested/run browser sets,
  actual versions for each launched player/host role, browser-specific blocked
  checks, OS, party size, endpoint pair, scenario catalog, provider identity
  placeholder, and managed sandbox process ownership metadata (no
  passwords/verifiers), plus
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
- `summary.json`: aggregate PASS/FAIL/BLOCKED counts, requested/run browser
  sets, launched-role versions, blocked checks, and the reviewed run identity.
- `scenarios.jsonl`: expected and observed assertions, per-check and per-scenario
  verdicts, UTC timestamps, and evidence paths.
- `setup-failure.json` when `beforeAll` fails: a fixed-stage, credential-safe
  setup record. Missing/empty scenario-results status is separately retained in
  `run.json`; it is not confused with malformed JSON.
- `request-diagnostics.jsonl` when exact player-origin `/socket.io/` events are
  observable, plus their bounded counts/truncation summary in `run.json`.
- `managed-host-output.json` for managed runs: counters-only stdout/stderr
  observations and bounded process metadata; raw host output is discarded.
- `driver-output.json`: bounded counters for the actual Playwright child streams
  and safe exit/spawn metadata only; raw driver text is not persisted.
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

- `0`: all requested browser assertions pass, no required check is blocked, and
  managed teardown/restoration checks pass. Chrome-only mode cannot return 0
  because Firefox-dependent coverage remains BLOCKED.
- `1`: an assertion, browser, evidence, managed-host, restoration, or runner
  failure occurred.
- `2`: at least one lifecycle scenario is BLOCKED because managed mode was not
  enabled. BLOCKED is not a PASS.

## Inert P1 handshake observation

The committed `--observe-handshake` mode is a single P1 Chrome player login and
Socket.IO handshake observation. It is not the N2 gate, does not run gameplay,
host UI, or lifecycle scenarios, and cannot produce an N2 PASS. It infers the
managed Chrome `--agent-run` path; inherited owner credentials are refused.
Require a routine reviewed PR, green CI, and protected merge. Before any live
booking, run this dry-run on the clean protected-merged SHA:

```sh
npm --prefix web/frontend run test:n2-gate -- --dry-run --observe-handshake
```

The dry-run imports the complete observer runtime, including the official
`playwright/test` `expect` export and the shared `loginPlayer` helper, but does
not generate credentials, contact endpoints, bind ports, start processes or
browsers, seed the sandbox, or create evidence. Stop if any import or tripwire
check fails. The primary then performs exclusive bind-and-close probes for
8360/8370 and acquires the existing coordination lock with holder `N agent-run`,
gate `N2-handshake-observe`, this ruling, and a maximum 60-minute window. Do not
change the shared booking/lock implementation.

For the sole authorized live observation, prepare a fresh isolated P1
`tmp/combat_capture` sandbox, keep both owner credential variables unset, and
use a unique run ID under
`tmp/router-rollout/v2-network/n2-handshake-observe/<run-id>/`:

```sh
RUN_ID="n2-$(date -u +%Y%m%dT%H%M%S)000Z-$(node -e 'process.stdout.write(require("node:crypto").randomBytes(4).toString("hex"))')"
unset NEQ_N2_PLAYER_PASSWORD NEQ_PLAYER_PASSWORD_VERIFIER
export NEQ_N2_HOST_URL=http://127.0.0.1:8360
export NEQ_N2_PLAYER_URL=http://127.0.0.1:8370
npm --prefix web/frontend run test:n2-gate -- \
  --observe-handshake \
  --evidence-dir "tmp/router-rollout/v2-network/n2-handshake-observe/${RUN_ID}"
```

The mode uses only the player page and TCP-only readiness for host port 8360.
Any provider reservation/refusal is FAIL; an absent, invalid, or inactive
ledger is BLOCKED, never zero. No retry is allowed. After teardown, confirm the
driver's final bind-and-close probes and preserve all evidence. The primary
releases the existing booking/lock only after cleanup and port review, then
reports the observed booleans exactly (`unknown` remains `unknown`) and STOPs.
Preserve the historical Chrome setup FAIL and unknown image outcome; this
observation does not retry the N2 gate or close task 6.2.
