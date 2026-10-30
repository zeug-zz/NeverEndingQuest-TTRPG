# Task 4.4 - Capture Evidence and Required-Check Evaluation

Status: **Revised implementation submitted for planner review. Task 4.4 remains unchecked. No new live capture or G3 verdict.**

## Implementation

- Kept the existing Capture_Arena driver/report path and added only the
  cohesive provider-free `scripts/capture_evidence.py` helper. Named runs require
  a unique `tmp/router-rollout/g3/<run-id>/`, an existing project-`tmp/`
  `--state-root`, and an explicit `--chain-id` for both resume phases. URL,
  profile, IDs, output paths, symlinks, state root and optional owned-server log
  are validated before transport construction. There is still no runner-side
  prepare/start/stop/restore or server/campaign repair.
- Read-only snapshots retain the actual initial encounter ID after combat exit;
  there are no guessed encounter aliases. Every sent step gets before/after
  snapshots carrying the control input/actor and bounded completion facts.
  Snapshots cover whitelisted party, selected encounter, named PC/ally character,
  history and save records. Each allowlisted file is checked for symlink/path
  escape before reading. Missing/malformed records and non-finite HP/XP/death
  counters are explicit invalid evidence. No `config.py`, environment keys, or
  campaign state outside the selected sandbox is read.
- Preserved transcript, owned-server log, trace, provider-free report, state
  snapshots and derived check records by bundle-relative reference. Artifact
  paths are checked for containment/symlinks, actual bytes and SHA-256 against
  the manifest; step snapshots are mandatory for each sent step. Trace copy,
  report degradation, server-log safety/copy failure and missing artifacts are
  recorded and block readiness. Server logs containing credential/config-like
  assignments or bearer/key patterns are not copied; the run is blocked instead.
- The manifest records scenario/profile hash and version, normalized immutable
  seed identity, party, actual selected encounter, source HEAD plus relevant
  runtime/adapter/model-factory dirty and untracked hashes, all nine combat
  prompt hashes, configured metadata with provenance, unknown actual response
  model/provider when not observable, validated transport, bounds, timestamps,
  attempted/called/sent/blocked controls, step caps/timeouts, separate read-only
  health-probe count, trace-derived provider-event count or `unknown`, and bundle
  artifact hashes. Safe public `model_config.py` literals are read through AST
  only; private config/environment data is never imported or parsed.
- Added only `ENABLE_COMBAT_TURN_TRACE`-gated observations through the existing
  trace utility and existing phase/action helpers: initiative accepted/invalid
  and marker states; pending death-save actor/roll outcome and before/after
  counters; actual retry-stage `valid_response`; and the pre-
  `apply_reported_round_transition` phase/round/opening-marker plus actual
  non-PC cohort carried to post-application completion. Batch records use only
  explicit `actor`/`actorName` with field provenance and a separate flat
  `affected_entities` list for character/target/ops/changes-mention provenance.
  Character names, targets and prose matches are never promoted to actor identity.
  Empty action lists are valid if the accepted eligible cohort completes once.
  Trace-off checks verify no trace file write. No mechanics, prompts, provider
  choices, response schema, persistence behavior, or default latency scripts changed.
- `observed_checks` now reads the actual step snapshots and runtime trace events.
  It checks exact PC identities, per-command `/dmg N` target HP deltas, invalid
  initiative/death-save state holds, wrong-actor rejection, one legal save on
  the pending PC only, PC initiative without an opening batch, DM tie batch
  count/eligibility/marker return, actual eligible allied/inactive cohort filtering
  with explicit actor-subset validation only when typed actors exist,
  exit branch and encounter clearing, read-only `/api/party` server health,
  HP/XP reconciliation, and completed/replay mechanical state plus retained
  history. Missing observations stay `BLOCKED`; observed wrong outcomes are
  `FAIL`.
- Character state snapshots read nested `spellcasting.spellSlots`, actual
  class-feature uses, top-level ammunition and schema-backed equipment
  ammunition/consumable/charge records. Absent values remain absent, not zero.
  Named-only seeding records known `experience_points: 0`; bare/default latency
  fixture bytes remain unchanged. Wrong-actor death-save comparison excludes
  only `active_character` from mechanical equality, records the permitted
  scripted-PC selection transition, and still compares pending actor, HP/saves,
  phase/round and resources.
- Resume complete/replay identity separates immutable source/party/seed/profile/
  transport/chain identity from mutable effects. The chain must be non-empty,
  sandbox/source/party/seed/transport-identical and have the correct phase roles.
  Complete-after mechanical projection must equal replay-before and replay-after;
  history continuity compares ordered role/content digests for stable
  user/assistant messages, with known system/dynamic-head exclusions recorded by
  reason. Append-only restart messages and dynamic system-head changes pass;
  same-length replacement and missing history block/fail. Raw timestamps, bytes
  and hashes are diagnostic only and cannot hide a mechanical difference.
- Automated per-run `READY_FOR_PRIMARY_REVIEW` no longer requires a prior
  `primary_reviewed` flag; final primary verdict remains `PENDING`. The offline
  `capture_evidence.py --run-dir ...` matrix helper loads and validates bundle
  bytes, reconstructs fixed profile contracts, recomputes checks from snapshots
  and trace events, and aggregates exactly 18 keys. It ignores caller-provided
  status strings. Synthetic transport is determined by explicit constructor
  injection provenance and is always live-ineligible. Missing bundles/cases,
  duplicate keys, stale files, caps, timeouts, degraded evidence, failed checks,
  identity mismatch or synthetic evidence prevent matrix readiness.
- Runtime trace is captured as a per-run suffix: pre-`start_game` byte offset,
  prefix digest and file identity are retained; reset, replacement, truncation or
  prefix mutation is non-PASS. Replay waits for output, idle processing, a quiet
  interval and the existing roster-matching read-only `/api/party` route. Only a
  predeclared observation-only replay with a verified trace gate, intact empty
  fresh span/report, startup readiness/health and before/after state/history may
  mark its empty trace `non_applicable`. It remains a diagnostic empty report;
  older trace rows/counts/provider data are never borrowed.

## Verification

Provider-free only. No live server, `--prepare`, external API, installed
campaign write, or G3 capture was run in this builder task.

- `TMPDIR="$PWD/tmp" PYTHONPYCACHEPREFIX="$PWD/tmp/pycache" .venv/bin/python -m py_compile scripts/capture_drive.py scripts/capture_evidence.py scripts/test_capture_drive.py scripts/combat_latency_report.py core/combat/turn.py core/combat/combat_manager.py core/combat/persistence.py utils/combat_latency_trace.py` -> PASS.
- `OPENSPEC_TELEMETRY=0 DO_NOT_TRACK=1 TMPDIR="$PWD/tmp" PYTHONPYCACHEPREFIX="$PWD/tmp/pycache" .venv/bin/python -m unittest -q scripts.test_capture_drive` -> 27 tests PASS. Includes actual temp-bundle complete/replay HP 20->19->19 success; reseed-to-20, extra HP delta, nested slot 1->0, XP delta, same-length history replacement, append-only/dynamic-head history, missing-history, source/party/chain mismatch negatives; forged-check/stale-artifact rejection; real-manager ENEMY_PHASE cohort retained across round prep to PC_PHASE; PC-win/DM-tie single accepted batch/empty-action and marker checks; invalid/wrong-actor/legal saves with permitted UI selection; allied/inactive cohort and explicit actor-vs-target separation; surrender/explicit-exit HP/XP/handoff/health checks; trace prefix/reset/non-applicable empty replay; symlink/non-finite HP; trace-off no-write and injected fake transport isolation.
- `OPENSPEC_TELEMETRY=0 DO_NOT_TRACK=1 TMPDIR="$PWD/tmp" PYTHONPYCACHEPREFIX="$PWD/tmp/pycache" .venv/bin/python -m unittest -q scripts.test_combat_latency_baseline` -> 24 tests PASS, separate process; default latency fixture unchanged.
- `scripts.test_combat_phase_integrity_precheck` -> 14 tests PASS, separate process.
- `scripts.test_combat_persistence_phase_stages` -> 10 tests PASS, separate process.
- `scripts.test_combat_manager_decomposition_contract` -> 34 tests PASS, separate process.
- `capture_drive.py --help`, `capture_evidence.py --help`, invalid-profile/path preflight contracts, and `openspec validate combat-manager-decomposition --strict` -> PASS; no live CLI run.
- `python3 scripts/check_ascii_compliance.py --summary-only` -> PASS (753 files scanned, 0 violations); tracked `git diff --check` plus whitespace scan of new files -> PASS.

## Remaining evidence boundary

- These checks establish tooling and fake-bundle behavior, not live gameplay. The
  parent-owned live G3 matrix and final primary verdict remain outstanding and
  are not claimed here. `task 4.4` remains unchecked pending planner verification;
  Task 5.1 remains pending.
- Live batch membership is evaluated from the actual pre-transition eligible
  non-PC cohort and one accepted logical batch/completion. Explicit `actor` or
  `actorName` fields, when present, must belong to that cohort; targets and
  affected entities are separate and are never treated as actors. Missing
  explicit actor receipts alone do not block because the runtime schema has no
  typed actor receipt contract. Provider/model resolution remains unknown unless
  runtime response metadata exposes it; the requested model is never substituted.
- Scratch fixtures and correct-prefix bytecode use project-local `tmp/` (including
  the retained diagnostic `tmp/task4-4-latency-test.log`). One earlier compile
  command misspelled `PYTHONPYCACHEPREFIX` and generated ignored `.pyc` files in
  `scripts/__pycache__/` (`capture_drive`, `capture_evidence`,
  `test_capture_drive`, `combat_latency_report`), `core/combat/__pycache__/`
  (`turn`, `combat_manager`, `persistence`) and
  `utils/__pycache__/combat_latency_trace`. They were not cleaned because the
  task explicitly prohibits cleanup.
