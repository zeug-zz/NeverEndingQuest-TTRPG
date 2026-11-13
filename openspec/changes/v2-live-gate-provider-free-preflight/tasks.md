# Tasks

## 1. Declare profiles and establish the provider-free boundary

- [x] 1.1 Define a versioned startup/resume call profile for every required fixture-party pair across the 26 planned rows from authoritative source evidence; reject missing or unsupported entries, leave replacement-only reserves untouched, and verify coverage and source binding with `.venv/bin/python scripts/test_live_gate_preflight_profiles.py`.
- [ ] 1.2 Add the isolated fail-closed router stub and invocation-identity checks at the capture worker boundary; verify command, working directory, and `PYTHONPATH` mismatch blocks before seeding, and that routed calls produce stub responses with zero upstream requests, provider budget, or live-attempt use via `.venv/bin/python scripts/test_live_gate_preflight.py`.

## 2. Exercise row coverage and driver controls

- [ ] 2.1 Integrate the preflight controller with the existing SP3 row runner, launcher, worker, and driver; verify all 26 planned rows' full scripted host path, fixture resolution, declared party size, lifecycle profile, and first scripted transport exchange, including disconnected-location rows and both party sizes, while leaving four replacement-only reserves unactivated, with `.venv/bin/python scripts/test_live_gate_preflight_integration.py`.
- [ ] 2.2 Add driver fault-injection tests for the attempt cap, time cap, and pause after three consecutive infrastructure failures, plus continuation beyond the first path and row; verify with `.venv/bin/python scripts/test_live_gate_preflight.py` using injected counters and clock without consuming live allowance.

## 3. Persist identity and preflight-only evidence

- [ ] 3.1 Record source SHA, dependency-lock identity, secret-free routing identity, invocation identity, per-row outcomes, provider-free result, and PF status in the required preflight evidence directory; verify exact-identity booking eligibility and mismatch rejection with `.venv/bin/python scripts/test_live_gate_preflight.py`.
- [ ] 3.2 Acquire and release the shared live-window lock around host startup and teardown, preserve failure evidence, and check ports 8360 and 8370; verify lock contention blocks launch and successful teardown leaves no listener using `.venv/bin/python scripts/test_live_gate_preflight_integration.py`.

## 4. Verify the source comparison and publish the operating rule

- [ ] 4.1 Immediately before comparison, refresh origin/main separately using an explicit `origin` fetch, resolve the full `refs/remotes/origin/main` SHA, and freeze it as `FROZEN_MAIN_SHA`; planning base `8d1a9e1ce5d9acda8fb7ff36d8866d28aaaf5624` is context only. Run identical coverage for the 26 planned rows against pre-#105 SHA `5999af374ded4f56b21b25d68fc10f9520444b51` and the frozen SHA using local `tmp/` snapshots, with reserves unactivated; verify the report uses the frozen SHA, comparison/preflight performs no network access, `NameError` appears on E06 and E13-E18 only in the non-bookable old-source control, and no pilot evidence is written with `.venv/bin/python scripts/test_live_gate_preflight_comparison.py --main-sha "$FROZEN_MAIN_SHA"`.
- [ ] 4.2 Update `.opencode/skills/neq-capture-arena/SKILL.md` and add the one-line `AGENTS.md` rule requiring a clean provider-free preflight at the exact SHA before booking; verify the documented evidence path, lock requirement, and no-PASS/no-booking distinction against the spec.
- [ ] 4.3 Run the complete focused preflight suites and `OPENSPEC_TELEMETRY=0 DO_NOT_TRACK=1 openspec validate change v2-live-gate-provider-free-preflight --strict`; verify all tests pass, no provider calls occur, no live gate is run, and validation reports no warnings or errors.
