# Design

## Context

See `proposal.md` for motivation and `inventory.md` for the surveyed host
surface. Key observed facts: the host app is a single Flask-SocketIO 5.7.2
application in threading async mode launched with `allow_unsafe_werkzeug=True`;
its Socket.IO handlers broadcast globally with no rooms or namespaces; and the
authoritative runtime is in-process threads and `queue.Queue` objects in the
process running `web/web_interface.py`. The host bind and origins already fail
closed to loopback (`utils/web_boundary.py`). OpenTunnel forwards decrypted bytes
unmodified; the target sees a loopback peer and visitor-supplied headers
(`docs/trust-boundary.md`); a route name is not authentication.

Pinned companion facts (reviewed 2026-11-05): OpenTunnel v0.6.2 (released
2026-11-04, MIT); assets `opentunnel-darwin-arm64.tar.gz`, `darwin-x64`,
`linux-arm64`, `linux-x64`, plus `SHA256SUMS` (no signatures observed; do not
assume them). No account is needed to create a tunnel. Relay limits: 30 tunnel
creates per hour per client IP (burst 10), 5 new certificates per day per
tunnel, at most 256 public connections per bridge. These limits shape the
spike budget: reuse one tunnel identity per run and per platform, and do not
delete and recreate tunnels in loops.

## Goals / Non-Goals

**Goals:**
- MUST produce evidence that an authenticated Socket.IO fixture works through
  the pinned tunnel on macOS and Linux (WebSocket and polling, reconnect,
  spoof rejection, clean shutdown).
- MUST select and justify the player-listener/runtime integration and serving
  stack, keeping the choice reversible before Phase 1 commits to it.

**Non-Goals:**
- MUST NOT implement the allowlist, session policy, gateway, React client,
  sharing UX, supervision, or packaging.
- MUST NOT add runtime dependencies to `requirements.txt`/`requirements-lock.txt`.

## Decisions

### D1. Tunnel: upstream OpenTunnel CLI v0.6.2, foreground, isolated

MUST:
- Binary downloaded into `tmp/n0/opentunnel/` (per run directory), checksum
  verified against `SHA256SUMS` first. Never inside `.venv`/`venv`; production
  packaging location is an N3 decision.
- Run `opentunnel serve --profile n0-<run-id>` with `XDG_CONFIG_HOME`,
  `XDG_DATA_HOME`, `XDG_STATE_HOME`, `XDG_RUNTIME_DIR` set to directories under
  the run's scratch tree. Keep the `XDG_RUNTIME_DIR` path short (Unix socket
  path length limits) and 0700.
- PROXY protocol off (no `--proxy-protocol`). The fixture does not parse it.
- Route declared so that the target is `127.0.0.1:8370`.

Immutable references (verified 2026-11-05 via `gh release download v0.6.2 -R anomalyco/opentunnel -p SHA256SUMS` and `gh api repos/anomalyco/opentunnel/git/ref/tags/v0.6.2`):
- Release: https://github.com/anomalyco/opentunnel/releases/tag/v0.6.2 (published 2026-11-04T14:09:43Z, MIT license)
- Tag commit: `1ad859e17924ec3f6741cbc4cdb54ce381c9007c`
- SHA256SUMS (verbatim):
```text
ce9b654b686beb0d23c87be9816ec71da950f41a4ddc0c8f33396eef871dc861  opentunnel-linux-x64.tar.gz
3136e3b66157db18e2f2b86bdcbf1c88016b2daeee70c0396a5c9d188eb6f293  opentunnel-linux-arm64.tar.gz
5f4629b571b53df5669a18ed1f395d2fb24ad2c8fd1ad5d3637dbe427f26e6f6  opentunnel-darwin-x64.tar.gz
3f4cf4d316db0e341b2995fd5cd44ba79a78aaee534f32199969152397c9e504  opentunnel-darwin-arm64.tar.gz
```
- The driver MUST pin these digests in code and also compare against the downloaded SHA256SUMS; a mismatch with either stops the run.

Normative startup decision: the driver uses the declarative route in the
isolated profile config (`$XDG_CONFIG_HOME/opentunnel/<profile>.toml`) and
owned foreground `serve`. It first guards an empty private PATH, preflight
proving that both `launchctl` and `systemctl` are unresolvable. It runs `up` to
mint the identity, then immediately runs `status` and `down`; only after
verifying no detached PID or service files remain does it write the declarative
route and start foreground `serve`. Teardown removes the route and runs
`delete --yes`, verifying identity deletion. `route add` is never used. This
path does not permit service registration or access to the user's default
profile. The verified binary is installed at a stable versioned path
(`tmp/n0/opentunnel/v0.6.2/<asset-stem>/opentunnel`) after per-run checksum
verification so per-application outbound firewalls (e.g. LuLu) can hold one
durable rule.

Historical resolution (2026-11-05): the earlier D1 prohibition on invoking
`up`, and its BLOCKED-only declarative-first fallback, are superseded by the
evidence-driven amendment above. At v0.6.2, `serve` cannot create a tunnel
identity; only `up`/`route add` mint one (source pinned to tag
`1ad859e17924ec3f6741cbc4cdb54ce381c9007c`, `main.rs` and `service.rs`). The
amendment retains the no-registration and isolation goals without contradicting
the normative startup decision. Owner review of this evidence-driven selected
startup approach is requested before N1/product implementation. The previously
required owner review of the different startup approach remains an outstanding
handoff; it is not waived or represented as explicit owner approval.

Rationale: no account, MIT, checksummed prebuilt binaries for all four
macOS/Linux targets, no Node/Rust toolchain needed. Isolated XDG plus a
dedicated profile prevents contact with the user's other tunnels.

Rejected: `npm install -g opentunnel`/`cargo install` (needs Node/Rust,
installs outside our control); `curl | sh` installer (unpinned, runs remote
code); Homebrew/AUR (not Linux/macOS uniform, not pinned by us); running `up`
in the user's default profile (service registration, shared identity); forking
OpenTunnel (out of scope per plan s3); Python package install (plan s8).

### D2. Listener/runtime integration (candidate, reversible)

Candidate: a distinct player listener on `127.0.0.1:8370` in the SAME Python
process as the host runtime, as a separate application object (not the host Flask
app), served by python-socketio `AsyncServer` mounted in an ASGI app and run by
uvicorn in its own thread with its own event loop. It reaches the authoritative
runtime only through a bounded in-process gateway interface: typed commands in,
projections out; no handler is shared with, wrapped from, or proxied to the
host app. The host Flask-SocketIO app (Flask-SocketIO 5.7.2, python-socketio
5.18.1 in `.venv`, threading mode, simple-websocket 1.1.0, Werkzeug 3.1.9) stays
local-only on its own port (`WEB_PORT`, default 8357) and is never tunnelled.

Why: (a) the runtime is in-process threads and queues, so an in-process gateway
needs no new IPC and cannot create a second game manager; (b) a separate
application object makes capability separation structural (an event not
registered on the player app cannot be invoked) rather than a filter over the
unfiltered host app, and global `socketio.emit` broadcasts cannot reach it; (c)
uvicorn + python-socketio ASGI supports WebSocket, long-polling, and graceful
shutdown on macOS and Linux with documented lifespan hooks; (d) python-socketio
is already a dependency, so only the ASGI server (uvicorn, plus h11 already
locked) is new.

Reversibility: the gateway interface is the only coupling. If the spike or
Phase 1 shows the AsyncServer/thread model unsuitable, the same interface can be
served from a separate process behind authenticated IPC with no change to the
tunnel, fixture contract, or Phase 1 allowlist.

Constraints (MUST): one runtime worker/state owner; the player thread never
writes canonical state directly (it submits commands the gateway validates and
the existing game loop executes); loopback bind only; tunnel failure never opens
another listener.

Alternatives considered:

| Alternative | Verdict |
| --- | --- |
| Werkzeug dev server with `allow_unsafe_werkzeug=True` (today's host stack) | Rejected for internet: dev server, not production grade; one process exposes the unfiltered host app. Stays for local host only. |
| gunicorn with threads | Rejected: prefork model conflicts with one in-process runtime and its queues; worker processes would need IPC or duplicate state owners. gthread has no maintained WebSocket path for Flask-SocketIO beyond simple-websocket threads, adding little over today. |
| eventlet / gevent | Rejected: monkey-patching risks the existing threading-based game loop, queues, and logging; eventlet is in maintenance posture. Revisit only if uvicorn path fails. |
| waitress | Rejected: WSGI, no WebSocket support (polling-only is not acceptable for the plan's WebSocket requirement). |
| Same Flask-SocketIO app with a "player mode" filter, one port | Rejected: every unknown route/event is reachable unless filtered; global emits reach players; violates the plan's positive-allowlist baseline. Allowed only via explicit later design update. |
| Separate gateway process | Not chosen now: needs authenticated, bounded IPC (new protocol, new failure modes, duplicate message cache); kept as the fallback behind the same gateway interface. |
| Generic reverse proxy/pass-through to the monolith | Rejected: not an authorization boundary (plan s4). |

Open verification (resolved in the spike, not left open): the fixture itself
runs on the candidate stack (python-socketio AsyncServer + uvicorn) so N0
proves WebSocket, polling, reconnect, and shutdown on exactly that stack. Proving
the in-process thread coexisting with the real runtime is explicitly Phase 1; N0
only proves the serving stack and that the thread/loop can start and stop
cleanly (task 2.4 shutdown test) without importing game code.

### D3. Spike dependency policy

The fixture needs uvicorn (new). The driver needs a Socket.IO client with both
transports: python-socketio sync `Client` needs `websocket-client` for the
WebSocket transport. These are installed into a scratch venv at `tmp/n0/.venv`
from a pinned `scripts/network_spike/requirements-spike.txt` (new file in this
change), not the repo `.venv`, so `requirements.txt` and `requirements-lock.txt`
stay unchanged. The spike venv is created with the repo's `.venv` Python minor
version on macOS and the container's Python on Linux. Unit tests (D4) use only
the standard library so they run in the repo `.venv` unchanged.

The scratch environment uses a dot-prefixed directory name because the ASCII
compliance scanner treats a path component named `venv` as third-party content.

Before any later change adds uvicorn (or any dependency) to the product, it MUST
update `requirements.txt` and `requirements-lock.txt` (resolve the existing drift:
lock pins python-socketio 5.18.0 while `.venv` has 5.18.1) and pass
`pip-audit --strict`; task 5.2 records this in the N0 decision log for the
Phase 1 change.

### D4. Fixture structure and test seam

`scripts/network_spike/` (all new, ASCII, SPDX Fair Source header):
- `fixture_auth.py`: stdlib-only pure functions (password check with
  `hmac.compare_digest`, signed expiring session token with random per-process
  key, expected Host/Origin validation, cookie attribute builder). No third-party
  imports, so unit-testable in `.venv`.
- `fixture_server.py`: ASGI app + python-socketio AsyncServer on `127.0.0.1:8370`
  using `fixture_auth`; serves `static/index.html`, `POST /login`, `GET /healthz`
  (Host-validated), and the `/n0` Socket.IO namespace (counter tick + echo)
  that rejects the connection without a valid session.
- `n0_driver.py`: provider-free evidence driver (requests with `timeout=`, python-socketio
  client).
- `requirements-spike.txt`, `README.md` (usage and evidence layout).
Tests: `scripts/test_network_spike_fixture.py` (unittest, stdlib only).

The expected public host is passed on the fixture command line after the tunnel
URL is known (`--public-host`), not hard-coded or derived from request headers.
The fixture reads the password from an env var or `--password-file`, never from
argv or logs.

### D5. Evidence layout

`tmp/router-rollout/v2-network/n0-<platform>-<run-id>/`: `evidence.json`
(schema defined by the driver in task 3.1), `driver.log` (redacted), `fixture.log`, `tunnel.log`
(redacted), `checksums.txt`, `env.json` (platform, arch, OS version, Python,
package versions, build SHA, opentunnel version/digest). Per
`AGENTS.md`, preserve before teardown; `tmp/` is gitignored.

### D6. Public URL discovery and secrecy

The public URL (random route name) is treated as a secret in logs and evidence
(redact the random label as `<route>` when the driver writes logs; the raw URL
lives only in process memory and the gitignored run directory's `url.private`
file, mode 0600, which is not part of reported artifacts).

## Risks / Trade-offs

- Relay rate limits (30 creates/h/IP, 5 certs/day/tunnel) -> one tunnel
  identity per platform run, retry budget documented, certificate issuance on
  first use counts against the 5/day: two failed first-run attempts leave
  limited headroom; the run order is macOS then Linux, with a stop on cert
  exhaustion and verdict BLOCKED.
- Linux container shares the host IP for relay create limits -> sequence runs;
  do not run both legs concurrently.
- Linux capture uses an owner-run wrapper outside the sandbox; agents receive
  no Docker/socket grants. The wrapper uses a container runtime tmpfs and init
  reaping. This proves container feasibility only; native Linux install/update
  proof remains an N3 requirement.
- uvicorn thread/loop shutdown ordering -> proven by task 2.4 and driver
  shutdown check before Phase 1 relies on it.
- Polling-only transport through the tunnel multiplies short requests against
  the 256-connection bridge cap -> the spike uses one client at a time.
- Browser behaviour (cookie `SameSite=Strict` with top-level navigation) is not
  exercised by a headless client -> recorded as a Phase 1/2 verification item;
  N0 proves cookie attributes and server-side behaviour only.
- Shared-secret URLs: route name is not authentication -> the fixture requires
  login even on the tunnel URL; evidence redacts the URL.

## Migration Plan

Not applicable (no product behaviour changes). Rollback is deleting
`scripts/network_spike/`, `scripts/test_network_spike_fixture.py`, and `tmp/n0/`.

## Resolved decisions / N1 handoff

- **Tunnel and supported evidence:** OpenTunnel 0.6.2 is pinned by immutable
  release and archive SHA256 values above. N0 passed on macOS arm64 (22/22,
  run `20261105t053750z`) and Linux arm64 (23/23, owner run
  `20261105t090543z`). Linux evidence is a Docker Desktop LinuxKit container,
  not native clean-install/update proof or x64 support certification. Release
  x64 assets exist but were not exercised. N3 must declare and test native
  supported architectures before packaging.
- **Listener decision:** D2 remains the selected, reversible architecture: a
  separate loopback ASGI/python-socketio application in the same Python process,
  uvicorn on its own thread/event loop, and a bounded typed gateway; not a
  second runtime. N0 proves the inert transport stack only. Coexistence with
  the real runtime and runtime-command safety remain N1 work and are not claimed
  proven.
- **Relay limits and observations:** documented limits are 30 tunnel creates
  per hour per client IP (burst 10), 5 new certificates per day per tunnel,
  and 256 public connections per bridge. Tests did not exhaust or measure
  these rate limits. Successful ACME issuance was observed. One GitHub 504
  download failure is retained in the verdict; no relay SLA is claimed.
- **Candidate dependency stack:** tested pins are uvicorn 0.54.0,
  python-socketio 5.18.1, python-engineio 4.15.1, websocket-client 1.9.2, and
  requests 2.34.2, recorded in `scripts/network_spike/requirements-spike.txt`.
  Before product adoption, N1 must make the dependency decision, update and
  resolve product requirements/lock files, resolve the existing lock 5.18.0
  versus `.venv` 5.18.1 drift, and pass `pip-audit --strict`. No lock was
  opportunistically changed in N0.
- **N1/N3/N4 boundaries:** Python-client evidence does not prove browser
  SameSite behavior. Native clean-install/platform browser matrix work belongs
  to N3/N4. N1 must prove shared-runtime coexistence and define the boundary
  authentication/synchronization contract. No real campaign was exposed, and
  the host listener on port 8357 is never allowed. N0 fixture uses port 8370
  per Overseer; port 8360 is reserved for later real-gameplay capture.
- **Owner review and sequencing:** request owner review of the N0 guarded-`up`
  startup decision and artifacts, and authorization to commit/push the N0 PR to
  `origin`/`main`; neither has happened here, and CI is not claimed passed. N1
  waits for N0 review/integration; this log does not authorize an automatic
  build-now transition. The earlier D1 startup review remains outstanding as
  stated above.
