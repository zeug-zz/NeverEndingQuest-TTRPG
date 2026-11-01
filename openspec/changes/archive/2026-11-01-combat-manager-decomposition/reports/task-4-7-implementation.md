# Task 4.7 - Causal Trace Evidence Linkage

Status: software-only implementation and primary verification complete. No live rerun or gate verdict was performed.

## Implementation

- The existing Capture_Arena driver records `trace_start_offset` immediately
  before `start_game`. The manifest preserves the source-file byte offset,
  prefix digest and copy-span offset, allowing a resumed/pre-existing JSONL file
  to retain source coordinates after its run suffix is copied into the bundle.
- Named step snapshots carry `observation.runtimeTrace`. The before offset is
  sampled immediately before `user_input`; the after offset is sampled only
  after the driver's idle/quiet completion predicate. A cap/timeout without an
  idle completion records unavailable evidence and therefore cannot establish a
  causal span.
- `capture_evidence.parse_trace_positions` parses the actual copied JSONL bytes
  and attaches half-open `_source_byte_start` / `_source_byte_end` positions
  translated back to the original trace source. Positions are evidence metadata
  on parsed records only; the runtime writer schema and emitted events are
  unchanged. The report's latency summaries and default latency input/order are
  unchanged.
- `link_trace_events_to_steps` associates positioned runtime observations and
  deterministic fast-path decisions only when each complete byte span belongs
  to exactly one before/after step span. Missing positions, invalid/overlapping
  boundaries, partial crossings and duplicate event coverage are BLOCKED.
  Matching never uses input text, target/delta values, timestamps or event names
  as event identity.
- Smoke-case HP reconciliation now has a per-step ledger. Structured HP
  operations count only when their actual apply event is successful and linked
  to the containing step. Deterministic `/dmg` evidence additionally requires
  exactly one same-step actual deterministic fast-path decision, an actor equal
  to the persisted active PC, and a unique canonical per-step HP change. If the
  successful structured apply already represents that same step/entity delta,
  deterministic evidence corroborates it rather than counting it again.
  Unexplained/mismatched HP mutation is FAIL; unavailable or ambiguous evidence
  is BLOCKED. Existing failed-apply and final-validation checks remain
  independent failures.
- Focused fake-only tests are explicitly labelled `synthetic-test`; they cover
  both party sizes, mixed observation/decision sources, non-zero resume offsets,
  duplicate/overlap/missing positions, unknown structured mutations and actual
  failed apply outcomes. Default latency fixture scripts were not changed.

## Verification

All commands were provider-free and used `OPENSPEC_TELEMETRY=0 DO_NOT_TRACK=1`;
Python cache and test scratch were directed to project-local `tmp/`.

- `.venv/bin/python -m unittest -q scripts.test_capture_drive` - 40 tests PASS.
- `.venv/bin/python -m unittest -q scripts.test_combat_latency_baseline` - 24
  tests PASS in a separate process.
- `.venv/bin/python -m py_compile scripts/capture_drive.py
  scripts/capture_evidence.py scripts/combat_latency_report.py
  scripts/test_capture_drive.py` - PASS.
- `python scripts/check_ascii_compliance.py --summary-only` - 1,135 files
  scanned; zero violations.
- `openspec validate combat-manager-decomposition --strict` - valid.
- Scoped `git diff --check` - PASS.

No live server, provider/API call, sandbox preparation, primary review, or
evidence-bundle rewrite was performed. The primary-owned `180820` FAIL and
`175906` BLOCKED verdicts remain unchanged; Tasks 5.3 and 5.4 remain unchecked.

## Focused 4.7 ledger review corrections

- The HP ledger now validates every encounter creature and character-file HP
  cell as finite, integral, uniquely identified and present at each timeline
  boundary. Missing/malformed encounter or character records, missing target
  cells, duplicate rows, non-integral values, and boolean offsets/cells block
  evidence; values are never rounded or integer-truncated.
- Per-step changes are reconciled by source domain. Character apply events prove
  character-file deltas; encounter apply events prove encounter deltas. For
  player/NPC identities, a unique same-name encounter row is treated only as a
  canonical mirror: an equal same-step delta, or exact delayed delta at the
  next-step/run boundary, is documented as a mirror projection and contributes
  no second logical HP effect. Unequal mirrors fail; enemy rows are never
  treated as character mirrors or actor evidence.
- The ordered timeline now includes run-before, every step-before/after,
  inter-step continuity, and run-after. Only an exact pending PC/NPC mirror
  catch-up may change HP outside the step whose apply event was proven; any
  other between-step or final mutation fails. HP-capable apply events or
  deterministic fast-path events outside a valid step span block rather than
  disappearing from the ledger. Startup/provider/stage records remain
  non-mechanical.
- The existing `hp_delta_snapshot_reconciliation` check now reports the full
  source-positioned step ledger, mirror justifications and canonical run
  deltas by source; it cannot report PASS from an aggregate `-4` while omitting
  the separately observed `-16`. The only added required check ID is
  `causal_trace_linkage`; existing check IDs/counts and failed-apply / final
  validation failure dominance are preserved.
- Added synthetic-only regressions for same-step and next-step mirror sync,
  wrong mirror values, unexplained inter-step/end changes, unassigned HP events,
  missing/nonfinite/fractional/bool HP values, duplicate character identities,
  missing encounter/target cells, boolean step offsets, and FAIL dominance over
  missing proof. Fake trace events and state records carry `fixture=synthetic-test`.

Latest provider-free verification (each unittest suite in its own process,
`OPENSPEC_TELEMETRY=0 DO_NOT_TRACK=1`, project-local `TMPDIR=tmp` and
`PYTHONPYCACHEPREFIX=tmp/pycache`): Capture_Arena driver **47 PASS**;
combat-latency baseline **24 PASS**. Final compile, ASCII, strict OpenSpec and
scoped diff checks are recorded in the invocation result. No live run or verdict
was produced; `180820` remains FAIL, `175906` remains BLOCKED, and Tasks 4.7,
5.3 and 5.4 remain unchecked.

## Focused review follow-up

- Mirror projection is restricted to actual encounter rows typed `player` or
  `npc`; enemy rows cannot acquire a character mirror. Both same-step and
  next-step catch-up record the unique name, source domain, exact integral delta
  and projection justification. Initial/final mirror disagreement is FAIL.
- The ledger validates source cells on run-before, every step edge and
  run-after; checks HP-cell inventory continuity between all edges; and reports
  canonical full-run source totals alongside each step's proven effects. A
  successful structured operation with no matching HP cell blocks, invalid or
  fractional operation values do not truncate, and unassigned HP-capable events
  block. Any unexplained between-step/end change fails.
- Existing check IDs/counts are preserved except for the single approved new
  `causal_trace_linkage` check. The full ledger is the existing
  `hp_delta_snapshot_reconciliation` check, so it cannot present a partial
  apply delta as the whole-run observed total. Failed apply and failed final
  validation checks remain FAIL even when causal proof is also BLOCKED.
- Additional synthetic-only tests verify same-step and delayed-to-next-step
  mirroring, wrong mirror HP, inter-step and end mutations, unassigned events,
  malformed/duplicate cells, boolean offsets, missing encounter/target rows,
  full `-16` source/step accounting (`six -2` deterministic operations plus one
  successful structured `-4` operation), and failure dominance with missing
  positions. No live trace was used or modified.

## Final arithmetic correction

- Whole-run ledger aggregation now removes zero-valued keys only after retaining
  every per-step operation, proof and mirror row. Thus a proven damage `-2`
  followed by proven healing `+2` reconciles to the canonical run net of zero;
  an added unexplained `-1` still fails. This is exercised using both 1-PC and
  4-PC schema-shaped synthetic state fixtures and two correctly source-positioned
  structured apply events. No per-step evidence is dropped or normalized.

## Final verification after focused review

- Capture_Arena driver tests: **47 passed**; combat latency baseline tests:
  **24 passed**, each in its own process.
- `py_compile` passed for driver, evidence checker, report helper and capture
  tests. ASCII scan: 1,135 files, zero violations. Strict OpenSpec validation
  passed. Scoped `git diff --check` and report whitespace check passed.
- No live capture was run. Thus no real-world delayed mirror cadence or new
  primary-owned live verdict is claimed; only fake, schema-shaped evidence
  fixtures exercised these cases. `180820` remains FAIL; `175906` remains
  BLOCKED. At this report's original implementation-verification checkpoint,
  Tasks 4.7, 5.3 and 5.4 remained unchecked; the subsequent primary
  software-only verification is recorded below.

## Primary software-only verification

- Primary source review passed the causal-offset ledger, strict continuity,
  mirror projection, missing-cell handling, and net-zero reconciliation. This
  review did not change or reinterpret any live evidence.
- Fresh provider-free verification passed **193 tests in 13 separate
  processes**: Capture_Arena driver 47, combat-latency baseline 24, validation
  stage 13, truth pack 8, character-ops contract 21, phase integrity 18,
  canonical validation facts 3, trace writer 1, decomposition/static parity 9,
  routing 11, replay guards 7, prompt authority 7, and bootstrap 24.
- Primary reviewed the current source/document contract. Strict source/doc
  verification had already passed. Task 4.7 is therefore checked as a
  **software-only** task; this is not a live rerun or G3 verdict.
- The retained individual allied 1-PC `175525` PASS is unchanged. The
  `180820` FAIL and `175906` BLOCKED verdicts remain unchanged; no new live/G3
  PASS is claimed. Tasks 5.3 and 5.4 remain unchecked.
