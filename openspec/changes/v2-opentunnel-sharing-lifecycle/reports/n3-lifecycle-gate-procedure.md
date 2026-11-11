# N3 Lifecycle Gate: Primary Owner Procedure

This procedure describes the provider-free preflight only. The later live N3
gate remains primary-orchestrator-owned under Task 6.2 and requires its separate
authorization and booking. A clean preflight is never a live-gate PASS.

## Frozen contract

The committed `scripts/n3_lifecycle_gate.py` owns the ten-row manifest and its
SHA-256 digest. Its frozen caps are ten total row attempts, one attempt per row,
300 seconds per row, 3,600 seconds per run, zero automatic retries, zero
provider attempts, and zero relay connections. The only supported platform keys
are `darwin-arm64` and `linux-arm64`. Do not edit the rows, caps, ports, or
platform set between preflight and a later live run. A contract change requires
a new review and a new manifest digest.

The rows cover sharing-off/local play, one-time identity initialization,
explicit start and authenticated local player session, duplicate start,
stubbed relay loss and recovery, credential rotation, explicit stop, host
service restart with sharing still off, route/session revocation, and clean
teardown. The preflight uses the real `PlayerSharingService`,
`SharingController`, and `PlayerSecurity` with injected listener, companion,
profile, clock, and port/lock fakes. It copies only the repository's
`modules/Capture_Arena` source into the unique evidence directory. It does not
read or modify an installed campaign.

## Preconditions and invocation identity

Run from the clean repository root on one of the approved platform pairs. Use
the repository virtual environment and set exactly `PYTHONPATH=.`. Choose a new
run ID and record the exact 40- or 64-character SHA that the later booking will
name. The preflight refuses a dirty worktree, a SHA mismatch, another CWD or
`PYTHONPATH`, an unsupported platform, an invalid manifest digest, or an
existing evidence path.

First inspect the invocation plan without creating evidence, probing ports,
acquiring a lock, copying Capture_Arena, or starting the loopback health host:

```sh
RUN_ID="n3-$(date -u +%Y%m%d-%H%M%S)-$$"
SHA="$(git rev-parse HEAD)"
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python scripts/n3_lifecycle_gate.py preflight --help
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python scripts/n3_lifecycle_gate.py preflight \
  --run-id "$RUN_ID" --sha "$SHA" --dry-run
```

The dry-run is invocation validation only. It does not establish readiness or a
PASS. Stop if its manifest digest or exact-SHA identity differs from the value
to be reviewed.

## Provider-free OD-6 preflight

Obtain primary/owner approval to occupy the shared preflight window. The command
checks ports 8360 and 8370 with read-only `lsof` observations, then atomically
acquires the existing `git-common-dir/neq-coordination/live-window.lock` using
the N2 `holder.json` and `bookings.log` ordering. Do not remove a lock after an
ownership, listener, evidence, or teardown failure; preserve it for primary
review. The helper's local health endpoint is bound only to `127.0.0.1:8360`;
port 8370 must stay free during preflight. No port-probe path binds a socket.

Run once, with the same run ID and SHA used in dry-run:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python scripts/n3_lifecycle_gate.py preflight \
  --run-id "$RUN_ID" --sha "$SHA"
```

The harness uses a stubbed companion and no provider, relay, DNS, or public
network. It exercises every frozen lifecycle row, checks the owned 8360 host
and free 8370 player port, stops on missing rows or infrastructure/cap
failures, and always attempts teardown. It does not create a production player
listener or run gameplay. The real authenticated N1 security boundary is
exercised in-process with a synthetic credential that is never written to
evidence. The later live task must still verify a real isolated Capture_Arena
host and player listener on each approved platform.

Evidence is written under
`tmp/router-rollout/v2-network/n3/<run-id>/preflight/preflight.json` by the
repository's atomic JSON writer. It records the exact command, CWD,
`PYTHONPATH`, SHA, source/dependency/route identity hashes, manifest digest,
expected-versus-observed row results, port ownership observations, caps, and
teardown. Credential, verifier, session, cookie, CSRF, invitation, and URL
values are redacted. The temporary Capture_Arena copy is removed after its hash
and row results are captured.

`READY_FOR_PRIMARY_REVIEW` means only that the provider-free preflight evidence
is complete. `FAIL` or `BLOCKED`, a missing row, any infrastructure failure,
cap breach, or incomplete teardown prevents booking; there is no automatic
retry. Even a clean preflight leaves `gate_verdict` as `PENDING` and
`is_gate_pass` false. The primary reviews the report at the exact SHA before
considering the separate Task 6.2 booking. Never use port 8357, the installed
campaign, or `tmp/combat_capture` for this procedure.
