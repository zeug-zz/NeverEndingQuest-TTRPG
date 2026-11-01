# Task 5.4 - Final Software and Contract Verification

Status: **PASS on primary-supplied verification.** This report records evidence
supplied by the primary orchestrator; the builder did not rerun tests or
independently inspect runtime behavior.

## Primary-supplied verification

- Final software suite: **705 tests passed in 41 separate processes**, all
  passing with no skips. The two batches were 288 tests across the first 20
  processes and 417 tests across the remaining 21. Each unittest module was
  invoked in its own process with
  `PYTHONDONTWRITEBYTECODE=1 TMPDIR=project/tmp .venv/bin/python -m unittest -q`.
- The primary's coverage includes the fresh 131-test facade suite, 35 manager
  alias/lifecycle/initiative checks, the 73-test multi-PC suite, initiative
  identity/normalizer ownership proof, and the nine static / three frozen
  controls. The primary reports no altered runtime boundary and no relocated
  monolith.
- Compilation of 75 affected core/shim/utils/parameter/rig/test modules passed
  with `PYTHONPYCACHEPREFIX=tmp/g3-final-pycache`.
- `python3 scripts/check_ascii_compliance.py --summary-only` scanned 1,135
  files with zero violations; `git diff --check` passed; and strict CLI
  validation passed under `OPENSPEC_TELEMETRY=0 DO_NOT_TRACK=1`.
- AST inspection covered 265 functions, with the largest owners at 479 lines
  (`_run_combat_simulation_internal`), 474 (`validator`), and 413
  (`context`); the compatibility shim is 17 lines. All functions satisfy the
  600-line bound, and the nine real boundaries remain unchanged.
- The primary reports no owned listener on port 8360 and protected-root hashes
  unchanged across lifecycles. This confirms the reported isolation evidence;
  it is not a claim that this builder ran or independently observed a server.
- The modified phase-one normalization requirement is recorded as satisfied
  through both the legacy and new package APIs. Strict validation is recorded
  as passed after implementation.

## Scope and limitations

This completes Task 5.4 only and records the supplied final software/contract
evidence. It does not supersede the primary-owned G3 PASS recorded for Task 5.3,
claim completion of any later rollout phase, or change the retained unrelated
UI 8/9 baseline, unsafe-harness 3.3 history, root-fixture 3.6 uncertainty, or
any earlier failure history. No code, acceptance criterion, or raw live artifact
was changed by this report.
