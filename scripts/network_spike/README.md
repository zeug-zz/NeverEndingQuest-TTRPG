# N0 inert network fixture

This is a standalone, inert transport spike for the N0 feasibility gate. It
serves static files, a health check, a short-lived authenticated session, and a
counter/echo Socket.IO namespace. It does not import or read game modules,
campaigns, characters, party state, or configuration secrets.

## Scratch environment

Create the spike-only environment under the gitignored `tmp/` tree. Do not
install these packages into the repository `.venv` or change the product
requirements/lock files.

```sh
python3 -m venv tmp/n0/.venv
tmp/n0/.venv/bin/python -m pip install -r scripts/network_spike/requirements-spike.txt
```

## Run

Set a local fixture password in the environment, then start the fixture:

```sh
export N0_FIXTURE_PASSWORD='choose-a-local-test-password'
tmp/n0/.venv/bin/python scripts/network_spike/fixture_server.py
```

Alternatively, create a private scratch password file and pass its path (the
file takes precedence over the environment variable):

```sh
tmp/n0/.venv/bin/python scripts/network_spike/fixture_server.py \
  --password-file tmp/n0/fixture-password.txt
```

The server always binds to `127.0.0.1`. `--host` exists only to test refusal of
non-loopback addresses; any value other than `127.0.0.1` exits before binding.
`--port` defaults to `8370` and is intended only for local tests. When a public
tunnel route is active, provide its expected Host authority without a scheme:

```sh
tmp/n0/.venv/bin/python scripts/network_spike/fixture_server.py \
  --password-file tmp/n0/fixture-password.txt --public-host route.example
```

Only the configured loopback Host and optional public Host are accepted. The
matching origins are `http://127.0.0.1:<port>` and, when configured,
`https://<public-host>`. Forwarding headers are ignored. `POST /login` accepts
form-encoded or JSON credentials; `POST /logout` expires the cookie; `GET
/healthz` is an unauthenticated liveness check. The `/n0` Socket.IO namespace
requires the session cookie, emits `hello` and one-second `tick` events, and
returns bounded `echo` payloads through the acknowledgement. Connections to the
default `/` namespace are refused.

The session cookie is deliberately `Secure; HttpOnly; SameSite=Strict`. The
headless Python driver sends the returned cookie manually, so it does not test
browser cookie storage, acceptance, or transmission, nor browser navigation or
reconnect behavior. Browser-cookie behavior remains pending and is not proven by
the fixture or claimed as an N0 PASS. This fixture is not a production login
system.
Application logs contain only request method, path, status, and a redacted host
label; cookies, session tokens, and passwords are never logged. Forwarding
headers are ignored, including by Uvicorn (`proxy_headers=False` and
`forwarded_allow_ips=""`), because OpenTunnel forwards visitor-supplied headers
unchanged. Cookie attributes are unconditional and do not depend on the ASGI
scope scheme. Never put a real password in source control or logs. Do not log
or publish the random public route label; treat it as secret and redact it as
`<route>` in evidence.

## N0 platform driver

After installing the scratch dependencies, the orchestrator can run one
platform leg from the repository root. The requested platform must match the
detected OS; this command creates a tunnel and is the live leg owned by task
3.2, not by the local smoke check.

```sh
tmp/n0/.venv/bin/python scripts/network_spike/n0_driver.py --platform macos --run-id <run-id>
tmp/n0/.venv/bin/python scripts/network_spike/n0_driver.py --self-test
```

The driver downloads and verifies the pinned OpenTunnel v0.6.2 release against
both its embedded digest and `SHA256SUMS` on every run. After verification, it
extracts into a fresh private staging directory and atomically installs the
binary at `tmp/n0/opentunnel/v0.6.2/<asset-stem>/opentunnel`; the stable relative
path and extracted-binary SHA-256 are included in `evidence.json`. Reusing this
versioned path avoids giving a per-application firewall a new executable path
on every run. Evidence is written under `tmp/router-rollout/v2-network/`.

The driver starts only foreground `opentunnel serve` with the declarative
profile route. To mint the relay identity first, it invokes
`opentunnel --profile <profile> up` only with an empty, per-run `PATH` and first
proves that neither `launchctl` nor `systemctl` resolves there. It confirms the
identity, stops the unregistered background daemon with `down`, then writes the
route and starts foreground `serve`. It never invokes `route add`. At teardown
it stops `serve`, removes the route config, invokes `delete --yes`, and confirms
the identity is absent. TCP-connect, request-send, or DNS startup errors are
reported as BLOCKED with the stable binary path and a possible per-application
firewall cause such as LuLu; the driver does not retry those errors against the
relay. `--keep-tunnel-identity` may preserve remaining local files, but does not
retain the remote tunnel or hostname.

The OpenTunnel profile is `n0-<run-id>` with the run ID lowercased. A run ID
that cannot form a lowercase alphanumeric/hyphen profile name is rejected
before the OpenTunnel CLI is invoked.

The inert fixture and headless client do not exercise coexistence with the real
Python runtime. That remains pending for the later runtime-integration phase
and is not claimed as an N0 PASS.

## Owner-run Linux container leg

Agents must not run Docker for this leg. The repository owner runs the fixed
wrapper from the repository root after the macOS leg and reviews the resulting
artifacts; the wrapper is preparation and does not decide the N0 verdict:

```sh
bash scripts/network_spike/run_linux_leg.sh <run-id> [linux/arm64|linux/amd64]
```

The platform defaults to `linux/arm64`; select `linux/amd64` only when that is
the intended Linux architecture. The run ID must match
`^[a-z0-9][a-z0-9-]{0,31}$`; uppercase IDs are rejected before Docker runs. The
default run ID uses the lowercase UTC form `YYYYMMDDtHHMMSSz`.
Only the validated run ID and Docker platform are owner-selected. The wrapper
pins `python:3.13-slim-bookworm@sha256:281d39ff02e3b389401586134ff9e6572954687822a58055ec07a60ded4e0b7f`,
derives the container UID/GID and host build identity itself, and writes the
identity as `sha=<40-or-64-hex>` and `dirty=0|1`. The driver accepts that
two-line file only when its exact keys, SHA, and dirty value validate; otherwise
it records an unknown build identity.

The container has a read-only root filesystem, no Linux capabilities,
no-new-privileges enforcement, bounded memory/CPU/processes, the default bridge network for release
and relay egress, and no published ports, host networking, host PID namespace,
devices, or Docker socket. Its only host bind mounts are
`scripts/network_spike/` read-only and the fresh run scratch directory
`tmp/n0/linux-leg/<run-id>/` read-write. The run-specific host build identity is
written to `n0/build-identity.txt`; the Linux driver validates and uses it only
when Git is unavailable inside the container. The driver self-test also checks
the `/proc` process-snapshot fallback and both passing and failing
`no_service_manager` evidence; these offline checks do not replace the live leg.

On Linux, `XDG_RUNTIME_DIR` is created under a per-run directory in the
container-local `/run/n0` tmpfs, not on the Docker Desktop host bind mount. The
wrapper mounts that parent as a 1 MiB tmpfs owned by the container UID/GID with
mode 0700 and passes it using `--runtime-parent /run/n0`. The driver accepts the
override only when it is absolute, existing, non-symlink, current-user-owned,
exactly mode 0700, and outside the repository tree. Before `opentunnel up`, it
probes `flock` and AF_UNIX bind/listen/connect; failure records BLOCKED and
does not attempt identity creation. `env.json` and `evidence.json` record the
basis as `override_tmpfs` or `project_tmp`, without recording the override path.
macOS retains the default `tmp/n0/r`.

If identity minting or foreground `serve` fails, or before teardown commands
remove the daemon or state, the driver copies bounded daemon-log tails through
the existing redaction into `daemon.log.redacted` (mode 0600). A short redacted
tail is included in the identity-minting observation.

Docker `--init` reaps orphaned children from the temporary OpenTunnel `up`
daemon; the driver's existing strict PID-liveness checks remain unchanged and
the wrapper does not signal extra processes. For reference, the wrapper's
complete fixed Docker invocation is below. The
wrapper substitutes only its validated platform/run ID, the repository and
run-specific mount paths, and the host-derived numeric UID/GID; the image,
security options, mounts, and container command are fixed:

```sh
docker run --rm --init \
  --name "neq-n0-linux-$run_id" \
  --pull=missing \
  --platform "$docker_platform" \
  --network bridge \
  --read-only \
  --cap-drop=ALL \
  --security-opt=no-new-privileges:true \
  --pids-limit=128 \
  --memory=2g \
  --cpus=2 \
  --user "$host_uid:$host_gid" \
  --tmpfs /tmp:rw,nosuid,nodev,noexec,size=256m,mode=1777 \
  --tmpfs "/run/n0:rw,nosuid,nodev,noexec,size=1m,mode=0700,uid=$host_uid,gid=$host_gid" \
  --mount "type=bind,source=$repo_root/scripts/network_spike,target=/workspace/scripts/network_spike,readonly" \
  --mount "type=bind,source=$run_root,target=/workspace/tmp" \
  --env "N0_RUN_ID=$run_id" \
  --env HOME=/workspace/tmp/n0/home \
  --workdir /workspace \
  "$image" \
  /bin/sh -ec '
    mkdir -p /workspace/tmp/n0/home /workspace/tmp/n0/pip-cache
    python3 -m venv /workspace/tmp/n0/.venv
    PIP_CACHE_DIR=/workspace/tmp/n0/pip-cache \
      /workspace/tmp/n0/.venv/bin/python -m pip install \
        --disable-pip-version-check --no-input \
        -r /workspace/scripts/network_spike/requirements-spike.txt
    exec /workspace/tmp/n0/.venv/bin/python \
      /workspace/scripts/network_spike/n0_driver.py \
      --platform linux --run-id "$N0_RUN_ID" \
      --runtime-parent /run/n0
  '
```

After Docker exits, the wrapper writes `host-postcheck.txt` into the evidence
bundle (or the run scratch if the driver produced none). It records the run exit
status, the exact-name container query (expected empty), image repo digests,
`uname -a`, and UTC time. The wrapper moves the driver's evidence bundle to
`tmp/router-rollout/v2-network/n0-linux-<run-id>/` after the container exits;
the private route file remains inside that gitignored bundle. Its remaining
container scratch, including the venv and downloaded OpenTunnel asset, stays
under `tmp/n0/linux-leg/<run-id>/` for owner review. A nonzero Docker/driver exit
is retained even when evidence was written. Do not treat a successful wrapper
exit or self-test as the orchestrator's platform verdict.

## Evidence

The N0 driver preserves run artifacts under
`tmp/router-rollout/v2-network/n0-<platform>-<run-id>/`. See
`openspec/changes/v2-network-transport-feasibility/design.md`, decision D5, for
the evidence layout and redaction requirements.
