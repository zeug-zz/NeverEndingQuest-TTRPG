# Handshake observation harness verification

## Ruling and scope

Ruling: `neq-n2-observe-harness-20261109` (design section 8). The committed,
opt-in `--observe-handshake` mode is for one P1 Chrome player login/handshake
observation. It is not a gameplay or N2 gate result. Task 6.2 remains unchecked;
this report makes no live-browser, post-merge CI, or N2 PASS claim.

The normal gate and observer share the canonical `loginPlayer` helper, including
its real Playwright `expect` dependency, locators, and waits. The official
`playwright/test` `expect` export is part of the observer's runtime import
preflight. This is not a source-extracted or inline login wrapper.

## Isolation and evidence contract

- Only one Chrome player, P1, ephemeral `--agent-run` credentials, and one
  handshake pass are permitted. No host browser/context/page, host UI HTTP
  request, gameplay input/action, P4, gate or lifecycle scenario, or retry.
- Host readiness on 8360 is TCP-only. The default N2 gate flow is unchanged.
- The managed provider ledger must be active before login. Reservations and
  refusals are checked before login, after the pass while active, and in the
  final copied ledger after teardown. Any reservation/refusal is FAIL;
  missing, invalid, or inactive evidence is BLOCKED, never evidence of zero.
  Guard-not-started/inactive remains distinct from active-zero.
- Setup evidence and pending bounded request diagnostics are persisted before
  page/browser close, including on setup failure. Only allowlisted,
  credential-safe fields are retained; unobservable Origin, Host, and
  session-cookie booleans remain `unknown`.
- Owned-host teardown, final exclusive bind-and-close probes for 8360 and 8370,
  final evidence, and existing booking/lock release are attempted. Any failure
  is recorded when possible and stops the run without retry.
- Scratch/logs are project-relative `tmp/n2/`; live evidence belongs under
  `tmp/router-rollout/v2-network/n2-handshake-observe/<run-id>/`.

## Verified implementation checks

Primary verification on the implementation worktree:

| Command | Result |
| --- | --- |
| `node --test web/frontend/e2e/*.node-test.mjs` | PASS — 84 tests |
| `npm --prefix web/frontend run typecheck` | PASS |
| `npm --prefix web/frontend test -- --run` | PASS — 27 tests |
| `npm --prefix web/frontend run build` | PASS |
| `npm --prefix web/frontend run test:e2e -- --list` | PASS — lists 11 scenarios; does not execute them |
| `npm --prefix web/frontend run test:n2-gate -- --dry-run --observe-handshake` | PASS — full runtime imports, including Playwright `expect` and canonical login helper |
| `OPENSPEC_TELEMETRY=0 DO_NOT_TRACK=1 openspec validate v2-react-player-vertical-slice --strict` | PASS |
| `python3 scripts/check_ascii_compliance.py --summary-only` | PASS — 909 files, zero violations |
| `git diff --check` | PASS |

Focused review found and fixed a late-write PASS bug. Heavy-focused follow-up
also corrected final-run/summary-write failures and missing/degraded diagnostic
handling to BLOCKED, and added a real disconnected-player DOM-metadata mock.
The dry-run's import preflight and side-effect checks do not establish live
reachability or handshake behavior.

## Not performed / outstanding

No host, browser, listener, provider, network request, booking, seed, or live
observation was started by this implementation. The dry-run is explicitly
side-effect-free. This software verification is not post-merge CI or a live
gate verdict. The primary owner must obtain a routine reviewed PR, green CI,
and protected merge; on the clean merged SHA, rerun the dry-run, then perform
exactly one booked primary P1 observation under the ruling's existing booking
and zero-provider requirements, preserve evidence, release the booking, and
stop. No retry is authorized.

Historical Chrome P1 setup remains FAIL and its image outcome remains unknown;
historical Firefox remains BLOCKED. Neither is changed or resolved here, and
no historical Origin behavior is inferred. The proposed CI job was not applied.

## Dated primary observation result — 2026-11-09

The single authorized primary observation ran from a clean worktree at
`d47bb72f9b4305013778d9cf28aff757af05bd9f` (Chrome 156.0.8078.80; client build
`e03cfac3a4f80cce1d4ad5a34259fe1d`). Evidence is under
`tmp/router-rollout/v2-network/n2-handshake-observe/n2-20261109T205225000Z-30d640e9/`.
The observation verdict is **FAIL**: setup reached `player_connection_wait`,
with the authenticated shell loaded but the player disconnected. The five
observed `GET /socket.io/` polling responses were HTTP 403; each diagnostic
records `origin_present=false`, `origin_matches_expected=false`,
`host_matches_expected=true`, and `session_cookie_present=true`. These describe
only the current request observations; raw headers were not retained, so they
do not establish historical browser headers or root cause and do not authorize
weakening Origin enforcement. Protocol version is null/unknown.

The active provider ledger was zero at every checkpoint (zero reservations and
refusals before login, after observation while active, and in the final copy);
the final ledger contains only its header and activation records, and the
monitor was active-zero. Provider identity was not invoked, observed as a zero
ledger after activation; this is not an unknown dispatch/outcome. The historical
image outcome remains unknown. Screenshot capture was skipped because the page
safety check was unavailable; there is no image, an explicit evidence gap.
Therefore this is not a PASS or completed N2 gate.

Managed owned-host stop was verified; driver and independent-primary exclusive
bind-close probes passed for ports 8360 and 8370, and the booking was released.
Optional `ps` PID corroboration was denied (`nono why /bin/ps read ALLOWED`),
which leaves the nono sandbox cause unconfirmed; no workaround or retry was
performed. Port proof and managed-stop evidence are retained. No host page/UI
HTTP, gameplay, P4, lifecycle, or operator manual retry occurred. Automatic
client polling during the configured 15-second Connected wait is part of the
observation, not an operator retry.

Preflight evidence copied into the run records clean merged 84 Node tests,
scenario listing, help/import dry run, P1 managed-bundle preparation checks,
and P1 managed-agent dry run as passing before booking. Tasks 6.2 and 6.9 remain
unchecked. No new gate is authorized and N3 remains forbidden. **STOP for the
owner's compatibility decision** on the current request/Origin boundary; no
fix or retry is authorized, and no ADR change is claimed as accepted.
