# Combat Latency Baseline - Tasks

## 1. Trace Foundation

- [x] 1.1 Add the opt-in trace writer and configuration gate with default OFF;
  target `utils/combat_latency_trace.py` and `model_config.py`; ensure the
  disabled path checks the gate before payload construction, file access, or
  writes. Verify with
  `.venv/bin/python -m unittest -q scripts.test_combat_latency_baseline`.
- [x] 1.2 Instrument existing combat stages and provider sites without changing
  call order, arguments, prompts, retries, or outcomes; target
  `utils/combat_latency_trace.py`, `core/managers/combat_manager.py`,
  `core/managers/multi_pc_combat.py`, `core/ai/combat_compressor.py`, and
  `core/ai/combat_compression_engine.py`. Verify with
  `.venv/bin/python -m py_compile utils/combat_latency_trace.py core/managers/combat_manager.py core/managers/multi_pc_combat.py`.
- [x] 1.3 Emit decision events containing `decision_point`,
  `decision_source` (`deterministic` | `llm_fallback` | `jev`),
  `decision_latency_ms`, and `provider_call_avoided`; target
  `core/managers/combat_manager.py`, `core/managers/multi_pc_combat.py`,
  `utils/combat_latency_trace.py`, and
  `scripts/test_combat_latency_baseline.py`, with Jev represented only as a
  future trace value and no Jev implementation. Verify with
  `.venv/bin/python -m unittest -q scripts.test_combat_latency_baseline`.

## 2. Fixed Measurement Fixtures

- [x] 2.1 Add a fixed MP smoke fixture for 4 PCs across 3 rounds with one enemy
  batch, exercising initiative/phase handling, PC action windows, enemy-batch
  processing, provider sites, compression, file operations, and decision-event
  capture. Target `scripts/combat_latency_fixtures.py` and
  `scripts/test_combat_latency_baseline.py`. Verify with
  `.venv/bin/python -m unittest -q scripts.test_combat_latency_baseline`.
- [x] 2.2 Add a fixed 1-PC party smoke fixture for 1 round, exercising the
  minimum-party tabletop path and confirming the trace remains observational.
  Target `scripts/combat_latency_fixtures.py` and
  `scripts/test_combat_latency_baseline.py`. Verify with
  `.venv/bin/python -m unittest -q scripts.test_combat_latency_baseline`.

## 3. Provider-Free Reporting

- [x] 3.1 Add `scripts/combat_latency_report.py` with a provider-free CLI that
  reads `debug/combat_turn_trace.jsonl`, validates bounded trace records, and
  reports stage timings, provider sites/latency/tokens, compression calls and
  cache hit rate, file reads/writes, NL fast-path hit/miss, decision sources,
  and baseline fixture summaries. Target
  `scripts/combat_latency_report.py` and
  `scripts/test_combat_latency_baseline.py`. Verify with
  `.venv/bin/python scripts/combat_latency_report.py --trace debug/combat_turn_trace.jsonl`.

## 4. Baseline Verification

- [x] 4.1 Capture and record the OpenAI-stack baseline from the fixed MP and
  1-PC party fixtures, including target ratification or adjustment notes, in
  `openspec/changes/combat-latency-baseline/design.md`, without adding report
  artifacts to `reports/`; use the local
  `debug/combat_turn_trace.jsonl` as measurement input only. Verify with
  `.venv/bin/python scripts/combat_latency_report.py --trace debug/combat_turn_trace.jsonl`.
  Blocked note (2026-09-21): the automated loop must not make provider calls, so the
  OpenAI-stack baseline requires an owner-executed live run. Execution path: tasks
  5.4-5.6 run that live capture through the scripted capture ensemble inside an
  isolated sandbox copy, then run the report script and record results in this
  change's `design.md`.
- [x] 4.2 Verify 1-PC party and multi-PC party smoke behavior and the existing
  combat suites, with no prompt or provider-call behavior changes. Target
  `scripts/combat_latency_fixtures.py`,
  `scripts/test_combat_latency_baseline.py`,
  `core/managers/combat_manager.py`,
  `core/managers/multi_pc_combat.py`,
  `core/ai/combat_compressor.py`, and
  `core/ai/combat_compression_engine.py`. Verify with
  `.venv/bin/python -m unittest -q scripts.test_multi_pc_combat scripts.c5_regression_combat scripts.test_combat_pc_action_parser scripts.test_combat_phase_integrity_precheck`.
  Verification note (2026-09-21): all four suites pass individually - 73/59/28/14. The
  combined command shows 2 pre-existing errors in
  `scripts/test_combat_pc_action_parser.py` (mock patches on `updates.*` fail when
  `test_multi_pc_combat`/`c5_regression_combat` run first). Reproduced unchanged on a
  clean HEAD worktree; it is test-isolation debt, not a regression from this change.
- [x] 4.3 Verify ASCII compliance, whitespace hygiene, and the disabled-path zero
  write/zero-overhead contract. Target
  `utils/combat_latency_trace.py`, `model_config.py`,
  `scripts/combat_latency_fixtures.py`,
  `scripts/combat_latency_report.py`, and
  `scripts/test_combat_latency_baseline.py`. Verify with
  `python3 scripts/check_ascii_compliance.py --summary-only && git diff --check`.
- [x] 4.4 Run the required OpenSpec validation and status checks after all other
  tasks remain reviewable and unchecked. Target
  `openspec/changes/combat-latency-baseline/proposal.md`,
  `openspec/changes/combat-latency-baseline/design.md`,
  `openspec/changes/combat-latency-baseline/tasks.md`, and the four files under
  `openspec/changes/combat-latency-baseline/specs/`.
  Verify with `openspec validate combat-latency-baseline --strict` and
  `openspec status --change combat-latency-baseline --json`.

## 5. Scripted Capture Ensemble (folded 2026-09-22)

- [x] 5.1 Create the dedicated reusable capture module `Capture_Arena` (tiny
  valid module: one area with walkable locations, a hostile group for combat,
  and NPC and feature objects for narration and checks) with canonical
  artifacts. Target `modules/Capture_Arena/`. Verify with
  `.venv/bin/python core/validation/validate_module_files.py --module Capture_Arena`.

- [x] 5.2 Create `scripts/seed_combat_capture.py`: lean sandbox copy at
  `tmp/combat_capture/` with `--prepare`/`--restore` and `--party 4|1`; copies
  app code plus `Capture_Arena` only; sets sandbox `WEB_PORT=8360` and
  `ENABLE_COMBAT_TURN_TRACE=True`; seeds `party_tracker.json`, character files,
  and a synthetic encounter (reusing `scripts/combat_latency_fixtures.py`
  payload builders rather than duplicating them), and sets
  `worldConditions.activeCombatEncounter` so combat auto-resumes. MUST never
  write to the installed tree. Target `scripts/seed_combat_capture.py`. Verify
  with `.venv/bin/python scripts/seed_combat_capture.py --prepare --party 4`,
  `.venv/bin/python scripts/seed_combat_capture.py --restore`, and
  `git status --short` showing no installed-tree changes.

- [x] 5.3 Document the capture ensemble as a local skill and checklist with
  BOTH execution paths: the socket-driven driver as the primary execution path
  and `playwright-cli` as the browser alternative (blocked in the current
  session sandbox); start/stop commands with `NEQ_OPEN_BROWSER=0`; selectors
  and wait heuristics; 4-PC and 1-PC scripted scenarios; evidence capture;
  teardown; and extension points for future narration/other gameplay captures.
  Target `.opencode/skills/neq-capture-arena/SKILL.md`. Verify with
  `grep -n "playwright-cli" .opencode/skills/neq-capture-arena/SKILL.md` and
  `grep -n "NEQ_OPEN_BROWSER=0" .opencode/skills/neq-capture-arena/SKILL.md`.

- [x] 5.3a Create `scripts/capture_drive.py`, the socket-driven capture driver (`python-socketio` client plus the `/api/party/set_active` REST call): emits `start_game`, sends per-turn `user_input` with `character`, waits for per-turn completion (first output + quiet window, processing-aware), logs a transcript, and preserves the trace to a caller-specified path. Target `scripts/capture_drive.py`. Verify with `.venv/bin/python -m py_compile scripts/capture_drive.py`, `.venv/bin/python scripts/capture_drive.py --help`, and a dry-run against an unused port that exits non-zero without a traceback.

- [x] 5.4 Execute the 4-PC live capture via the ensemble and preserve the trace
  to `tmp/combat_baseline_mp.jsonl`; no artifact is written under `reports/`.
  Target `tmp/combat_baseline_mp.jsonl`. Verify with
  `.venv/bin/python scripts/combat_latency_report.py --trace tmp/combat_baseline_mp.jsonl`.

- [x] 5.5 Execute the 1-PC live capture via the ensemble and preserve the trace
  to `tmp/combat_baseline_one_pc.jsonl`. Target
  `tmp/combat_baseline_one_pc.jsonl`. Verify with
  `.venv/bin/python scripts/combat_latency_report.py --trace tmp/combat_baseline_one_pc.jsonl`.

- [x] 5.6 Run `scripts/combat_latency_report.py` on both traces; record the
  baseline and target ratification or adjustment in `design.md`; close gate G1.
  Target `openspec/changes/combat-latency-baseline/design.md`. Verify with the
  two report commands from 5.4 and 5.5, then
  `openspec validate combat-latency-baseline --strict`.

Requirement trace: tasks 5.1-5.6 implement `Reusable Scripted Capture Ensemble`
in `specs/combat-latency-smoke-fixtures/spec.md`; tasks 5.4-5.6 are the
execution path for the blocked task 4.1 and gate G1.

## Guidance

- Tasks SHOULD be implemented in order because later measurements are invalid
  if the disabled-path or prompt-byte invariants are not established first.
- No task authorizes prompt edits, game-state mutation, Jev implementation,
  auto-commit, auto-push, or report-directory creation. Live provider calls are
  authorized only for capture tasks 5.4-5.5 inside the isolated sandbox copy;
  all other tasks remain provider-free.
