# Tasks

Run each named Python test module in a separate process. Provider-free tasks MUST use router/provider tripwires. Use the repository venv and project-relative scratch paths. Controller and prefetch flags remain false outside the isolated G5A Capture_Arena copy. The primary orchestrator owns all live G5A runs and the verdict.

## 1. Python-Legal Ally Menus and Perception

- [x] 1.1 Build active-ally selection, opaque legal menus, ally-scoped perception, loyalty defaults, and deterministic fallbacks. Cover hidden/enemy-only fact exclusion, invalid/missing choices, legal attacks and existing authored `take_cover` only when permitted by its Python contract, rejection of future spatial placeholders, and the absence of ally flee/surrender options. Primary evidence: standalone Python-issued immutable ally menus, ally-scoped perception, and loyalty defaults; no flee, surrender, Dodge, or future spatial actions. The primary independently ran menu 7, perception 3, and loyalty 3 in separate specified provider-tripwire processes. Builder heavy. `git diff --check` clean. Verify separately:
  - `PYTHONPATH=. PYTHONPYCACHEPREFIX=tmp/router-rollout/g5a/pycache .venv/bin/python -B -m unittest -q scripts.test_combat_ally_menu`
  - `PYTHONPATH=. PYTHONPYCACHEPREFIX=tmp/router-rollout/g5a/pycache .venv/bin/python -B -m unittest -q scripts.test_combat_ally_perception`
  - `PYTHONPATH=. PYTHONPYCACHEPREFIX=tmp/router-rollout/g5a/pycache .venv/bin/python -B -m unittest -q scripts.test_combat_ally_loyalty`
- [x] 1.2 Add default-off ally controller and prefetch flags with the deterministic-enemy-resolution dependency. Verify default-off inertness and invalid flag combinations. Primary evidence: default-off fail-closed dependency gates; provider-tripwire flags (3 tests) and enemy batch execution (21 tests) independently passed; `git diff --check` clean. Builder haiku with focused retry for tripwires. Verify with:
  - `PYTHONPATH=. PYTHONPYCACHEPREFIX=tmp/router-rollout/g5a/pycache .venv/bin/python -B -m unittest -q scripts.test_combat_ally_flags`

## 2. `/cmd`, Narrator Voice, and Ally Prefetch

- [x] 2.1 Parse `/cmd` in Python, validate active encounter NPCs, bound/sanitize directives, persist private typed input-history metadata, coalesce latest directives per ally, and acknowledge errors/acceptance in the established Narrator voice. Verify unknown/inactive names make no state change, `/cmd` does not end the PC phase or count as an action, no extra acknowledgement call is added, and an ally may reply through the existing batch narration request. Primary evidence: heavy builder with focused voice correction; independently verified provider-tripwire command 9, voice 5, turn commit 26, manager decomposition 36; `git diff --check` clean. Ally narration projection integration belongs to task 3.1:
  - `PYTHONPATH=. PYTHONPYCACHEPREFIX=tmp/router-rollout/g5a/pycache .venv/bin/python -B -m unittest -q scripts.test_combat_ally_command`
  - `PYTHONPATH=. PYTHONPYCACHEPREFIX=tmp/router-rollout/g5a/pycache .venv/bin/python -B -m unittest -q scripts.test_combat_python_combat_voice`
- [x] 2.2 Prefetch conditional ally intents during eligible PC phases and implement one directive/state-edge re-plan, two-background-request accounting, latest-order compilation against current menus, and no synchronous re-plan after the prefetched path is selected. Verify pending, failed, late, stale, and capped results without a live provider. Primary evidence: heavy builder with focused fail-closed correction; separate provider-tripwire tests independently passed for ally prefetch 14, ally command 13, tactical prefetch 22, and enemy batch execution 21; `git diff --check` clean.
  - `PYTHONPATH=. PYTHONPYCACHEPREFIX=tmp/router-rollout/g5a/pycache .venv/bin/python -B -m unittest -q scripts.test_combat_ally_prefetch`

## 3. Initiative-Oriented Ally Batches and Receipt Commit

- [x] 3.1 Schedule hostile and ally batches in the approved initiative-group order, retain distinct ally plan/perception/narration calls, enforce at most one synchronous plan plus one narration per ally batch, and stage all side effects under the accepted input's existing `enemy_batch` manifest and receipt. Verify both initiative orders, 1-PC and 4-PC parties, replay/recovery, and unchanged hostile-batch behavior. Primary evidence: heavy builder with focused turn-handoff compatibility retry; provider-tripwire suites independently passed ally batch 4, ally commit 1 (P1/P4 recovery and receipt replay), enemy batch 21, turn commit 26, and multi-PC 75; `git diff --check` clean. Verify with:
  - `PYTHONPATH=. PYTHONPYCACHEPREFIX=tmp/router-rollout/g5a/pycache .venv/bin/python -B -m unittest -q scripts.test_combat_ally_batch`
  - `PYTHONPATH=. PYTHONPYCACHEPREFIX=tmp/router-rollout/g5a/pycache .venv/bin/python -B -m unittest -q scripts.test_combat_ally_commit`
  - `PYTHONPATH=. PYTHONPYCACHEPREFIX=tmp/router-rollout/g5a/pycache .venv/bin/python -B -m unittest -q scripts.test_combat_enemy_batch_execution`
  - `PYTHONPATH=. PYTHONPYCACHEPREFIX=tmp/router-rollout/g5a/pycache .venv/bin/python -B -m unittest -q scripts.test_combat_turn_commit`
  - `PYTHONPATH=. PYTHONPYCACHEPREFIX=tmp/router-rollout/g5a/pycache .venv/bin/python -B -m unittest -q scripts.test_multi_pc_combat`

## 4. G5A Fixture, Offline Report, and Compatibility

- [x] 4.1 Add `g5a-ally-p1` and `g5a-ally-p4` with an authored cover feature legally usable by an ally, provider-free evidence/report checks, and scripted damage validation against each declared 5th-edition weapon. Require an observed applied `take_cover` choice, not a future spatial placeholder. Primary evidence: heavy builder with scoped evidence-hooks correction; independently verified required suites (9/91/9/28/9/11/27), G1/G3(50)/G4/G5R, and all 9 prompt hashes golden parity PASS. G5T Gate10 JSON and text re-evaluation were byte-identical under `tmp/router-rollout/g5a/`. `git diff --check` clean. No live gate pass recorded.
  - `PYTHONPATH=. PYTHONPYCACHEPREFIX=tmp/router-rollout/g5a/pycache .venv/bin/python -B -m unittest -q scripts.test_combat_ally_g5a`
  - `PYTHONPATH=. PYTHONPYCACHEPREFIX=tmp/router-rollout/g5a/pycache .venv/bin/python -B -m unittest -q scripts.test_capture_drive`
  - `PYTHONPATH=. PYTHONPYCACHEPREFIX=tmp/router-rollout/g5a/pycache .venv/bin/python -B -m unittest -q scripts.test_combat_decomposition_contract`
  - `PYTHONPATH=. PYTHONPYCACHEPREFIX=tmp/router-rollout/g5a/pycache .venv/bin/python -B -m unittest -q scripts.test_combat_g5_report`
  - `PYTHONPATH=. PYTHONPYCACHEPREFIX=tmp/router-rollout/g5a/pycache .venv/bin/python -B -m unittest -q scripts.test_combat_tactical_schema`
  - `PYTHONPATH=. PYTHONPYCACHEPREFIX=tmp/router-rollout/g5a/pycache .venv/bin/python -B -m unittest -q scripts.test_combat_tactical_g5t`
  - `PYTHONPATH=. PYTHONPYCACHEPREFIX=tmp/router-rollout/g5a/pycache .venv/bin/python -B -m unittest -q scripts.test_combat_g5t_report`

## 5. Primary-Owned Live G5A Gate

- [x] 5.1 After Tasks 1-4 pass and the primary authorizes capture, run three independent P1 and three independent P4 captures on one source revision. Prepare each run in an isolated `tmp/combat_capture/` copy, enable flags only there, start only the owned server on port 8360 with `NEQ_OPEN_BROWSER=0`, and preserve each complete bundle under `tmp/router-rollout/g5a/<run-id>/`. For each run, the primary uses the matching party/scenario pair and unique run ID:
  - `.venv/bin/python scripts/seed_combat_capture.py --prepare --party 1 --scenario g5a-ally-p1`
  - `.venv/bin/python scripts/seed_combat_capture.py --prepare --party 4 --scenario g5a-ally-p4`
  - From `tmp/combat_capture/`: `NEQ_OPEN_BROWSER=0 NEQ_G5_CAPTURE_RUN_ID=<run-id> .venv/bin/python -c 'import run_web; run_web.main()'`
  - `.venv/bin/python scripts/capture_drive.py --gate g5a --party 1 --scenario g5a-ally-p1 --run-dir tmp/router-rollout/g5a/<run-id> --state-root tmp/combat_capture --server-log tmp/router-rollout/g5a/server-<run-id>.log --url http://localhost:8360`
  - `.venv/bin/python scripts/capture_drive.py --gate g5a --party 4 --scenario g5a-ally-p4 --run-dir tmp/router-rollout/g5a/<run-id> --state-root tmp/combat_capture --server-log tmp/router-rollout/g5a/server-<run-id>.log --url http://localhost:8360`
  - After all six bundles exist: `.venv/bin/python scripts/capture_evidence.py --gate g5a --run-dir tmp/router-rollout/g5a/<p1-run-1> --run-dir tmp/router-rollout/g5a/<p1-run-2> --run-dir tmp/router-rollout/g5a/<p1-run-3> --run-dir tmp/router-rollout/g5a/<p4-run-1> --run-dir tmp/router-rollout/g5a/<p4-run-2> --run-dir tmp/router-rollout/g5a/<p4-run-3>`

  Review the observed honored `/cmd`, a legal authored `take_cover` choice per party-shape aggregate, at most two synchronous calls per accepted ally batch, separately capped background requests, 100% legal applied choices, no ally flee/surrender, and legal scripted damage. The automated report is readiness evidence only; the primary records PASS/FAIL/BLOCKED and does not waive missing observations. Primary review: **G5A PASS**; see [`reports/g5a-verdict.md`](reports/g5a-verdict.md). Six independent bundles are same-source, with required observations verified against before/after snapshots and traces. Prior G5A attempts remain preserved as failed/blocked evidence and are not counted toward this verdict.

## 6. Final Integration Verification

- [x] 6.1 Run the full focused ally test set in separate processes, compile every touched Python module, then verify strict OpenSpec, ASCII compliance, and whitespace. Final primary rerun: 87 separate test processes, 1,633 tests, 0 failures, 0 skips; exact per-process evidence is recorded in `tmp/router-rollout/g5a/final/baseline-rerun-results.json`. Focused test invocation prefix: `PYTHONPATH=. PYTHONPYCACHEPREFIX=tmp/router-rollout/g5a/pycache .venv/bin/python -B -m unittest -q <test-module>` (one process per module). Python compile passed for all 237 changed Python files. ASCII compliance passed (878 files, 0 issues); strict OpenSpec validation passed; `git diff --check` was clean. The nine legacy prompt hashes and G1/G3(50)/G4/G5R goldens passed; G5T Gate10 JSON and text were byte-identical. Final matrix `tmp/router-rollout/g5a/g5am8-matrix-final.json` was READY with zero blockers, using the same source after teardown. The capture sandbox is absent, no listener remains on port 8360, and controller/prefetch defaults are off. The rerun followed test-only harness/profile corrections; these were applied before the clean rerun. No implementation behavior was changed by those corrections.

## Scope Resolution

Per approved owner direction, `combat-absent-pc-autopilot` is subsumed by the ally controller. Converting a PC to an allied NPC or handing over an absent player's character, and PC/NPC character-sheet conversion, remain out of scope. No separate autopilot runtime, scaffold, or gate is required. Dodge and spatial defensive mechanics are excluded.
