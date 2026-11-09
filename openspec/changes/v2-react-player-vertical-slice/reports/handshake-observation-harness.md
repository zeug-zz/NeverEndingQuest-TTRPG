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
