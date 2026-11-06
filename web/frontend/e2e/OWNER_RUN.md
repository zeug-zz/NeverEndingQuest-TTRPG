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
  records the name and actual version for Player A, Player B, and the host UI
  context. WebKit is not a replacement for either required player engine. The
  gate writes no browser storage state, HAR, or trace archive. Console text is
  bounded and redacts password, cookie, authorization, and CSRF values. Do not
  add raw network or storage artifacts.
- Gameplay probes submit player and host inputs. The sandbox may process them
  through its configured provider path. Run only when that provider execution
  is separately authorized. If any provider is invoked, the reviewer must
  replace the driver's `not-observed` placeholder with the actual model and
  provider identity in `run.json` and `summary.json`; do not infer it from the
  browser or configuration.
- Inject `NEQ_N2_PLAYER_PASSWORD` and `NEQ_PLAYER_PASSWORD_VERIFIER` from the
  approved secret source without putting either value in command arguments,
  shell history, evidence, screenshots, or notes. The driver removes the plain
  login password from the managed host child's environment.

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
pair and no side effects. A run without `--manage-sandbox-host` leaves the three
lifecycle scenarios BLOCKED and cannot pass the gate.

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

## Approved live-run sequence

1. Confirm system Chrome and Playwright 1.65.0 Firefox are installed, the
   separate booking is active, ports 8360 and 8370 are unused, and provider
   execution is authorized. Record worktree/revision, OS, the fixed Chrome plus
   Firefox pairing, and party-size order. Do not install dependencies or browsers
   during this run.
2. Build the player bundle once from the project root:

   ```sh
   npm --prefix web/frontend run build
   ```

3. Prepare a fresh isolated sandbox for **one party size only**. Do not prepare
   while a managed host is running or while a bundle recovery directory remains:

   ```sh
   .venv/bin/python scripts/seed_combat_capture.py --prepare --party 1
   ```

4. Export the fixed endpoints and inject both credentials through the approved
   secret source. For example, a secret manager may populate these variables;
   never type either value into a shell command:

   ```sh
   export NEQ_N2_HOST_URL=http://127.0.0.1:8360
   export NEQ_N2_PLAYER_URL=http://127.0.0.1:8370
   # Inject NEQ_N2_PLAYER_PASSWORD and NEQ_PLAYER_PASSWORD_VERIFIER out of band.
   RUN_ID="p1-chrome-firefox-$(date -u +%Y%m%dT%H%M%SZ)-$$"
   ```

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

6. Only after the managed run exits and confirms teardown, prepare a fresh 4-PC
   sandbox and run its matching gate:

   ```sh
   .venv/bin/python scripts/seed_combat_capture.py --prepare --party 4
   RUN_ID="p4-chrome-firefox-$(date -u +%Y%m%dT%H%M%SZ)-$$"
   npm --prefix web/frontend run test:n2-gate -- \
     --party-size 4 --manage-sandbox-host \
     --evidence-dir "tmp/router-rollout/v2-network/n2-${RUN_ID}"
   ```

    Do not reuse the 1-PC sandbox or run the party sizes concurrently.

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

The lifecycle records are BLOCKED and the overall result is non-zero when the
driver is run without `--manage-sandbox-host`. Socket-only evidence never passes
the real-browser gate.

## Evidence review and teardown

Each unique `tmp/router-rollout/v2-network/n2-<run-id>/` contains:

- `run.json`: run/build SHA, Player A Chrome version, Player B Firefox version,
  separate host-context Chrome version, OS, party size, endpoint pair, scenario
  catalog, provider identity placeholder, and managed sandbox process ownership
  metadata (no passwords/verifiers).
- `summary.json`: aggregate PASS/FAIL/BLOCKED counts and the reviewed run
  identity.
- `scenarios.jsonl`: expected and observed assertions, per-scenario verdicts,
  UTC timestamps, and evidence paths.
- `screenshots/`: separate player/host UI snapshots, including uncertainty and
  post-restart resynchronization for the instance-change phase.
- `console.jsonl` and `playwright-test-results/`: bounded diagnostics; no HAR,
  browser storage state, or trace archive.

Review all records and screenshots before assigning the primary verdict. Check
the actual provider/model identity if any input invoked a provider, confirm the
original bundle digests, and verify both ports are free after the driver exits.
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
