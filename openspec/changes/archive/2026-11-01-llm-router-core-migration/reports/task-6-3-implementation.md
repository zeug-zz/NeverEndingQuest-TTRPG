# Task 6.3 - Offline Four-Key G4 Evaluation

Status: focused provider-free implementation and correction verification
completed for task 6.3; task 6.3 is checked after primary review. Overall change
accounting is 23/25 checked; all 15/15 inventoried operations remain routed. No
G4 live capture or primary PASS is claimed. Tasks 6.4 and 6.5 remain unchecked.

## Implementation

- Added an isolated `evaluate_g4_matrix` path in `scripts/capture_evidence.py`;
  G3's existing 18-key matrix, defaults, profile, and bare latency behavior are
  not changed. `--gate g3` remains the evaluator default and `--gate g4` selects
  exactly four keys: narrator-dialogue-travel P1/P4 and combat-smoke P1/P4.
- Corrected the fixed narrator case: startup's persisted CA01 opening is observed
  before gameplay, followed by five adjacent input turns with persisted rooms
  CA02, CA03, CA03/Mira, CA02, CA01. P4 actors are Acheron, Acheron, Merisiel,
  Merisiel, Merisiel; switch occurs at Mira. Expected locations and actor identity
  come from the approved `build_gate_profile` output, not a competing hardcoded
  evaluator sequence. Existing input/control limits and timeout bounds are
  unchanged.
- G4 capture now records a separate startup trace-byte span from the captured
  pre-start boundary through quiet readiness. Every actual provider row must
  pair to exactly one startup or input-step span; no unpaired row is dropped.
  Receipts before the first input are retained as `step: startup`. Deterministic
  `/att` and `/dmg` combat steps may have zero provider calls; a scoped
  natural-language combat step and Mira dialogue require actual SDK evidence.
- G4 bundles are checked for unique safe paths under `tmp/router-rollout/g4/`,
  actual artifact bytes/hashes (including checks), exact profile/seed/source
  identity, fixed bounds, complete snapshots/steps, persisted roster/active-PC/
  room identity, and receipt identity. Counts must be nonnegative integers and
  reconcile with transcript steps, controls, health reads, backend outputs,
  provider rows, and step snapshots. Declared input wording cannot prove travel.
  Mira must have a distinct backend response present in the retained transcript.
- Provider/task/model/fallback/cost provenance comes from actual byte-positioned
  receipts; manifest provider/model aggregates must match receipt observations.
  Receipt task is scenario-scoped and deterministic fast-path steps cannot claim
  SDK work. Unknown cost is allowed only with explicit unpriced provenance.
- Twenty matrix negative branches cover missing/duplicate keys, artifact tamper,
  wrong seed/roster/room, forged receipt projections, missing receipts, timeout,
  cap, underreported step/control/health/provider counts, boolean/non-integer
  counters, forged green checks with contradictory persisted state, actual
  unexpected fallback, and an echo-only Mira transcript. Receipt-level negatives
  also cover missing IDs/task/model, duplicate IDs/positions, unpaired/misaligned
  startup spans, wrong scoped task, unsupported cost claims, and deterministic
  combat receipt misuse. Positive cases cover startup receipt pairing, the real
  router(fake SDK)->adapter->real-writer startup/step path, legitimate zero-call
  deterministic steps, and actual/unpriced cost provenance.
- Four complete-contract driver bundles and the four-key matrix are evaluated in
  unit tests, but every generated bundle is explicitly synthetic and blocked
  only for synthetic evidence/transport. Missing/unavailable evidence is
  BLOCKED; contradictory observed assertions are FAIL; only a complete live
  candidate can be `READY_FOR_PRIMARY_REVIEW`, never primary PASS.
- Updated `.opencode/skills/neq-capture-arena/SKILL.md` with G4 commands,
  bounds, evidence contract, primary-review semantics, synthetic/live distinction,
  and the outstanding key-rotation prerequisite. Frontmatter/name and existing
  G3 raw-18/default latency guidance were preserved. The implementation's exact
  flag is `--gate g3|g4` (G3 default), matching current CLI source.

## Verification

| Command | Result |
|---|---|
| `OPENSPEC_TELEMETRY=0 DO_NOT_TRACK=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=tmp/task-6-3-correction-pycache TMPDIR=tmp .venv/bin/python -m unittest -q scripts.test_capture_drive` | PASS, 61 tests; provider/network/server-free |
| Separate focused guarded suites (capture, hydration, baseline, receipt adapter, router, benchmark, GPT-5.4, mini, Luna, inventory, request contracts) | PASS, 296 tests across 11 processes |
| `OPENSPEC_TELEMETRY=0 DO_NOT_TRACK=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=tmp/task-6-3-correction-pycache TMPDIR=tmp .venv/bin/python -m py_compile scripts/capture_drive.py scripts/capture_evidence.py scripts/combat_latency_fixtures.py scripts/test_capture_drive.py` | PASS |
| `python3 scripts/check_ascii_compliance.py --summary-only` | PASS, 0 violations across 1,146 files |
| `OPENSPEC_TELEMETRY=0 DO_NOT_TRACK=1 openspec validate llm-router-core-migration --strict` | PASS |
| `git diff --check` | PASS |

## Boundaries

- No server, API, provider, SDK, prepare/restore, reserved live path, campaign,
  credential/config inspection, or old-evidence cleanup was performed.
- Owner key rotation remains outstanding before live execution. Exposure history
  was retained; no live eligibility or runtime readiness is inferred from
  synthetic four-key fixtures.
- The earlier 6.1/6.2 accepted report text is preserved; each now includes an
  attributable correction note for the adjacent persisted narrator path and the
  startup receipt span. No G3, prompt-baseline, product behavior, or acceptance
  changes were made.
- Task 6.4 live G4 capture/review and task 6.5 final verification were not run.
- All 11 focused suite runs used empty credential config fixtures and fatal
  network/SDK/write guards before owner imports; the Luna direct-contract run
  additionally supplied only source-confirmed `LLM_PROVIDER="openai"`. No real
  credential/config value was read. Scratch/cache: `tmp/task-6-3-correction-pycache`; capture tests clean their unique
  project-local `tmp/` fixtures. No absolute `/tmp/` path was used.

## Primary verification addendum

Primary fresh verification retains the provider-free 296-test result above:
61 Capture_Arena, 14 hydration, 24 baseline, 15 adapter, 88 router, 6
benchmark, 10 GPT-5.4 contract, 6 mini shim, 41 Luna contract, 14 inventory,
and 17 request-contract tests, in 11 separate processes. Strict validation,
ASCII/whitespace, scoped diff, and no-ignored-cleanup checks passed.

The primary reviewed the five adjacent narrator turns after startup CA01:
CA02, CA03, Mira in CA03, CA02, CA01; the P4 Merisiel switch is at Mira. The
startup receipt span remains distinct from input-step spans. Review reconciled
actual receipt bytes with core task scope and raw counters; it retained 20
matrix negative branches and receipt-level negatives, and kept synthetic
candidates BLOCKED rather than treating them as live evidence.

A read-only run of the current G3 evaluator against the 18 actual selected
bundles in `tmp/router-rollout/g3-primary-matrix-20261017.json` returned 18/18
required and observed bundles `READY`, with no missing, not-ready, failed,
synthetic, duplicate, invalid, or receipt-chain-failure cases. The historical
G3 primary PASS is retained. This is a compatibility audit, not a new live
capture, not a G4 verdict, and not a waiver of G4 requirements.
