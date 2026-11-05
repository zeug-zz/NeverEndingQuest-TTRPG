# N0 verdict

**Overall: PASS** (macOS arm64 PASS; Linux arm64 container PASS). N0 transport feasibility is demonstrated on both recorded platforms.

## macOS: PASS

Run `20261105t053750z`, `2026-11-05T05:37:50Z-05:39:58Z`; macOS 26.6.2 arm64, Python 3.13.18, OpenTunnel 0.6.2 darwin-arm64 (archive sha256 `3f4cf4d316db0e341b2995fd5cd44ba79a78aaee534f32199969152397c9e504`, extracted binary sha256 `39991ec74bc79e13917d5e7bc309870f7925d364808b33ec535fef2fc29eeaf8`), build `5519e87facc568fb4cac7e5c571300145dcfabfd` with untracked N0 files (dirty). Evidence: `tmp/router-rollout/v2-network/n0-macos-20261105t053750z/`. All 22/22 required checks PASS; route path `up_minted_then_serve`.

Orchestrator independent checks: public URL unreachable after teardown (TLS EOF); no opentunnel process; port 8370 free; port 8357 not listening; hostname, tunnel ID and password only in 0600 `*.private` files; no key material left under the run's xdg/home; tunnel identity deleted. Service registration basis: `sandbox_write_denied` (nono denies writes to `~/Library/LaunchAgents` before and after) plus `launchctl`/`systemctl` unresolvable on the `up` PATH.

Earlier macOS attempts (`20261105T040912Z`, `20261105t042331z`, `20261105t045041z`, `20261105t051152z`, `20261105t052841z`) were BLOCKED by driver defects, each corrected: invalid uppercase profile slug; nono observation stripped `NONO_CAP_FILE`/`HOME` and status case; `serve` cannot mint an identity at v0.6.2; LuLu outbound firewall blocked the per-run binary path (owner approved a rule for stable path `tmp/n0/opentunnel/v0.6.2/opentunnel-darwin-arm64/opentunnel`); status-based URL discovery; transient poll errors wrongly recorded as blockers. The `20261105t051152z` `tunnel.log` contains an unredacted (since deleted) tunnel ID; evidence is gitignored.

## Linux: PASS (arm64 container)

Owner runs `20261105t063713z` and `20261105t074630z` were linux-arm64/aarch64 on Linux 7.0.12-linuxkit. Both minted identity/certificate successfully, then `up` reported `background service did not start`. Foreground `serve` and the fixture were never started; gameplay was never involved. Archive SHA256 `3136e3b66157db18e2f2b86bdcbf1c88016b2daeee70c0396a5c9d188eb6f293` matched the pinned checksum. Build `5519e87facc568fb4cac7e5c571300145dcfabfd`, `dirty=true` from `host_file`.

Latest run artifacts: `tmp/router-rollout/v2-network/n0-linux-20261105t074630z/{evidence.json,tunnel.log,host-postcheck.txt}`. Clean shutdown PASS; remote identity deleted; route removed; no tracked PID; host-postcheck container ID list empty after `--rm`. `no_service_registration` failed because minting never completed, although the no-service-manager basis was proven.

Hypothesis only (unconfirmed): the runtime control socket/flock on a Docker Desktop macOS bind mount. Pinned upstream `daemon.rs`/`control.rs` require both. The previous driver removed `daemon.log` before preserving it, so the exact daemon failure is unknown.

Correction reviewed by primary: wrapper adds private `/run/n0` tmpfs (host user uid/gid, mode 0700, noexec/nosuid/nodev, 1 MiB); driver validates `--runtime-parent` and probes AF_UNIX plus flock before any relay operation. Failure blocks without consuming a tunnel creation. Redacted `daemon.log` is now preserved before cleanup. Default macOS runtime behavior is unchanged. This does not verify Linux transport or confirm a root cause.

Latest owner run `20261105t085831z`: driver hint FAIL, but primary classifies this attempt as external-download BLOCKED. GitHub returned HTTP 504 Gateway Time-out for pinned v0.6.2 `SHA256SUMS`; asset verification did not complete. `route_creation_path` was `not_started`; no binary, tunnel, or fixture started. Runtime-dir probe and gameplay transport checks were NOT RUN, so correction #6 remains untested on Linux. Evidence: `tmp/router-rollout/v2-network/n0-linux-20261105t085831z/evidence.json` and `host-postcheck.txt`. Clean shutdown PASS; host-postcheck showed an empty Docker container list after `--rm`, and the pinned image digest was unchanged (`python@sha256:281d39ff02e3b389401586134ff9e6572954687822a58055ec07a60ded4e0b7f`).

Superseded by run `20261105t090543z` below: the rerun was performed and Linux PASSES; the earlier 'Overall N0 remains BLOCKED' status for this attempt is historical only.

Run `20261105t090158z` was BLOCKED: driver hint BLOCKED; asset checksum PASS and runtime_dir_probe PASS (tmpfs/socket fix confirmed). Identity was minted, then the temporary `up` helper daemon (pid 27) stayed visible after `down` because the container ran Python as PID 1 without an init reaper, so clean_shutdown FAILed and foreground serve/fixture were not started. Identity was deleted and the container removed. Correction: wrapper adds `docker run --init`; no cleanup check was relaxed. Evidence: `tmp/router-rollout/v2-network/n0-linux-20261105t090158z/`.

Owner run `20261105t090543z` (2026-11-05 09:05:51Z-09:07:39Z): Linux 7.0.12-linuxkit aarch64/glibc 2.36 in Docker Desktop, Python 3.13.18, OpenTunnel 0.6.2 linux-arm64; build `5519e87facc568fb4cac7e5c571300145dcfabfd` (`host_file` dirty). Evidence: `tmp/router-rollout/v2-network/n0-linux-20261105t090543z/`. All 23/23 required checks have expected/observed results and PASS; blockers empty and hint PASS. Pinned container digest `sha256:281d39ff02e3b389401586134ff9e6572954687822a58055ec07a60ded4e0b7f`; OpenTunnel archive digest matches pinned `SHA256SUMS` (`3136e3b66157db18e2f2b86bdcbf1c88016b2daeee70c0396a5c9d188eb6f293`), binary digest `7876ca698377c11b56781e5577258aa6b73ae763a062fbcdebfa14df2d9edac1`.

The runtime tmpfs override and pre-mint socket/flock probe passed; init reaped the previously stuck helper (pid 28). `no_service_manager` was established (PID 1 docker-init, no systemctl/systemd runtime, isolated service files empty, no new/tracked PID). Route path was `up_minted_then_serve`. Wrong/missing login returned 401; accepted login returned 200 with Secure/HttpOnly/Strict/Max-Age cookie; invalid Origin returned 403 and invalid Host 421; forwarding headers were ignored. Unauthenticated and origin-spoofed sockets were refused with zero events. WebSocket and polling negotiated and returned hello/tick, echo acknowledgement matched, and the existing client reconnected in 2.048s on the same URL and received a tick after tunnel restart.

Clean shutdown passed: fixture/tunnel stopped, route removed, identity deleted, public URL unreachable, port 8370 free, no tracked PIDs, helper 28 absent. `host-postcheck` reports dockerexit0, no remaining container ID, and unchanged pinned repository digest. State directories had zero files; both private files were mode 0600. Independent post-run public probe was unreachable; redacted daemon log retains service-stop evidence. No campaign or host surface was imported or exposed.

Earlier blocked Linux attempts remain historical records above and do not represent the current verdict.

## Scope limitations

Linux evidence demonstrates container feasibility only, not native clean-install/update proof (N3). Existing x64 release artifacts were not exercised and are not certified. No gameplay, external-network browsers, React, or real-runtime coexistence was demonstrated (later N1/N4). Tasks 5.1 (final verification) and 5.2 (decision log) are complete in `tasks.md`. Overseer re-checked the gate from evidence.json and ruled N0 PASS on 2026-11-05.

## Platform verdict summary

| Platform | Verdict | Evidence |
| --- | --- | --- |
| macOS arm64 | PASS (22/22 required checks) | `tmp/router-rollout/v2-network/n0-macos-20261105t053750z/` |
| Linux arm64 container | PASS (23/23 required checks) | `tmp/router-rollout/v2-network/n0-linux-20261105t090543z/` |

## Overseer rulings (2026-11-05)

- N0 fixture uses port 8370 (Capture Arena/8360 applies from N4 or any real-gameplay drive).
- macOS live window booked and used.
- Semgrep local runs redirect state to `tmp/` with `--metrics=off` (CI authoritative).
- The shared Hindsight bank is intended.
- N0 transport gate PASS (macOS `20261105t053750z` 22/22; Linux arm64 container `20261105t090543z` 23/23), re-checked from evidence.json.
- D1 guarded startup (empty-PATH `up` -> `status` -> `down`, isolated XDG profile, declarative route plus foreground `serve`, `delete --yes` at teardown) APPROVED for N0 and N1 spike use. Production startup/packaging remains an N3 decision; the empty-PATH guard and stable LuLu binary path are test mechanisms, not shipped facilitator UX.
- Live window released after both teardowns.
- N1 owns the dependency decision, the lock file and pip-audit.

## Post-gate CI remediation (PR #89)
- CodeQL on PR #89 raised three high alerts in the spike code: py/polynomial-redos (fixture_auth token-part regex), py/clear-text-storage-sensitive-data for the fixture password file (`password.private`), and py/clear-text-storage-sensitive-data at the driver `append_log` sink.
- Fixes: token parts are now length-bounded (980 characters, derived from the 1024-character token cap less the 43-character signature and separator) and checked against a fixed alphabet without a regex; the driver no longer writes the fixture password to disk and passes it only to the fixture child via `N0_FIXTURE_PASSWORD` in a fixture-only environment allowlist, keeping it in redaction values.
- The `append_log` alert was traced to a synthetic self-test sentinel that is redacted before writing; no code change was made for it, and its disposition depends on the CodeQL rescan.
- Verification after remediation: fixture unittest 12 tests OK; driver self-test 63 PASS, 0 FAIL; local fixture smoke on 127.0.0.1:8370 (healthz 200, correct login 200, wrong login 401, port freed); ASCII 0 violations; Bandit hook passed.
- The live macOS and Linux gate runs predate this change and were not repeated; the remediation changes only the in-process password handoff and token-part validation, which the offline checks cover.
