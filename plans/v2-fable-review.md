# V2 Fable Review: Program Optimisation and Implementation Plan

Status: Review output for the Overseer and owner. It authorizes nothing by itself.
Date: 2026-11-10. Baseline: `main` at `2a422fff`.
Audience: the Overseer session (overview s10). Program index:
[V2 narrative overview](v2-narrative-overview.md).
Scope: the v2 program (sequence, scope, contracts, gate overhead) checked against
the code as it stands. Out of scope: the relay/Overseer tooling drafts
(`plans/relay-plan.md`, `plans/skill.md`, `plans/references/`), runtime
performance tuning, and any change to an accepted ADR.

## 1. Purpose and authority

The eight v2 plans are sound on authority and contracts. What needs optimising is
the order of work and a small number of code foundations that every track will
otherwise build separately. This document turns that review into work packages
the Overseer can run.

- Precedence is unchanged: `AGENTS.md` > accepted ADRs > active OpenSpec changes >
  master plans > the index. This file sits below all of them. Where it disagrees
  with an owning plan, the owning plan stands until the owner approves a change.
- It is a review artifact, not a ninth master plan. It does not need an s4 entry
  in the index. Requirements stay in the owning plans; verdicts stay in s10.3.
- Each work package carries one approval class:
  - **STANDING**: the Overseer may proceed under the 2026-11-05 standing owner
    instruction (overview s10.1). Record it as "assumed (standing instruction)".
  - **RULED**: already authorized by a recorded ruling; unchanged by this review.
  - **OWNER**: needs a recorded owner approval first. It changes an owning plan's
    scope or order, opens a worktree, adds work outside the owning plans, or
    needs human judgement the plans reserve to the owner. Section 4 collects
    these into one decision sheet.
- Nothing here waives a gate, creates evidence, imputes a rating or reopens SP3b.

## 2. How to use this plan

1. Start with section 3.3 (what was not verified) and reconcile it against your
   own records. This review did not read the coordination mailbox, so N2 and
   mise-en-scene state is taken from overview s10 as merged at `2a422fff`.
2. Run the Wave 0 STANDING packages (FR-01, FR-02 part A, FR-04).
3. Put the section 4 decision sheet in front of the owner in one sitting. Record
   each answer in s10.1 and s10.4. An unanswered item keeps its stated default.
4. Run Waves 1 to 3 in order. Inside a wave, packages are independent unless a
   "Depends on" line says otherwise.
5. Every implementation package goes through an OpenSpec change and
   `openspec-build-loop`, with the owning plan's gates. Package text here is the
   seed for the proposal, not a substitute for it.
6. Line numbers below were read at `2a422fff`. Re-check a reference before
   quoting it in a ruling; section 10 lists what was checked directly.

## 3. Findings

### 3.1 Program findings

1. **Build speed is not the constraint.** The program has 54 phases across seven
   tracks. Five have a PASS (N0, N1, SP0, SP1, G0). Week 0 was 2026-10-28; N2
   implementation merged on 2026-11-07 and SP3 ran on 2026-11-05/06, against
   timeline bands of weeks 5-8 and 3-5 (overview s7). The limits are owner
   decisions, the single live window, and tracks that are not open.
2. **The critical path is parked behind SP4.** Narrator P1 and P2 own the event
   envelope, identity, fencing and save manifest (overview s5). Memory Pilot
   P1-P3, Builder MB3, TITAN, the spatial overlay and the Firelight live-state
   record all consume them. Worktree R "opens after the pilot gate" (overview
   s7), and SP4 waits on a 1,048-row D1 audit plus four owner choices. ADR-0034,
   the spatial decision the Narrator contracts needed, was accepted 2026-11-09.
3. **Live windows are being spent on defects a dry run would catch.** SP3 ended
   with 0 PASS from 26 attempted slots. Seven rows stopped on a host `NameError`
   present on `main` since 2026-03; others lacked a goblin template or lost
   transport (overview s10.2, SP3 closeout). SP3b closed BLOCKED on
   `ModuleNotFoundError: scripts` and a harness that stopped after its first
   path. N2's 30-attempt provider cap was documentation only (overview s10.3).
4. **No automated test tier exists.** There are about 430 `scripts/test_*.py`
   files (394 import `unittest`, none use pytest, about 32 are plain scripts),
   no single runner, and no CI workflow that runs a Python or frontend test.
   The three workflows cover ASCII, security scans and OpenCode comments.
5. **Four tracks will edit the same prompt and commit paths.** Spatial S2,
   Narrator P3/P4, `v2-context-views` and Firelight G4-G6 all touch prompt
   assembly in `main.py` (8,808 lines) and `core/ai/conversation_utils.py`.
   Section 8 lists the seams.
6. **Three tracks each need stable identity.** Narrator P1 (stable entity IDs in
   the envelope, `plans/v2-narrator.md:232`), Spatial S1 (module-qualified
   location and feature IDs, `plans/v2-spatial.md:132`) and Firelight G2
   (character, item, place, quest and condition IDs,
   `plans/v2-firelight-g0/design.md:138-152`). Party and possession paths are
   name-based today. No plan names a single owner for the grammar.
7. **A packet alone is not shown to stop invented spatial facts.** SP3's content
   failures (invented destinations for unknown doors, unauthored relocation,
   unsupported distances) occurred in every arm. Any early spatial slice has to
   pair the packet with a Python-side check and be measured, not assumed.

### 3.2 Code findings

| Area | Observation | Consequence |
| --- | --- | --- |
| Commit identity | `core/combat/turn_commit.py` (848 lines) already has `turn_id`, `applied_id`, a validated commit manifest and turn receipts for combat. The N1 player transport has its own command/receipt/snapshot contract in `web/extensions/player/contracts.py` | Narrator P1 should generalise these, not add a third identity scheme |
| Event store | `memory_events` (`core/memory/memory_db.py:198`) has no campaign, timeline-generation, turn/commit, schema-version or correction-link column. `memory_event_provenance` (line 327) was not read | The P1 envelope needs a migration; P0 must map fields before proposing columns |
| Identity index | `entities` and `entity_aliases` tables exist (`memory_db.py:138,151`); `_build_party_member_identity_map` is in `conversation_utils.py:324` | A base exists for an alias index; canonical records still own the IDs |
| Compression | Twelve modules, 5,272 lines, under `core/ai/` and `utils/compression/`, plus `session_diary.py`, `location_summarizer.py` and `combat_compressor.py`. `utils/compression/agnostic_conglomerator.py` (564 lines) has no reference in tracked code. `core/ai/conversation_compression.py` (173 lines) has no runtime importer | Narrator P4 replaces summarisers it has not yet inventoried; two modules are removal candidates |
| Persistence | 84 direct `json.dump(` sites in 45 runtime files against 200 `safe_write_json(` sites. `main.py`'s ten are debug dumps, logs and one temp file. `conversation_utils.py:1256` writes `modules/conversation_history/chat_history.json` non-atomically | Fencing and Firelight receipts assume atomic state writes; the sites need classifying |
| Spatial base | `utils/authoritative_state_packet.py:181` already builds known and adjacent locations; `core/ai/atlas_builder.py` and the atlas rebuild at `conversation_utils.py:856` inject the full atlas each turn; the DM-note exits block is at `main.py:7511` | S1a and S2a have existing code to wrap rather than replace |
| Party-size debt | `MULTIPLAYER_MODE` appears 42 times in 9 runtime files; about 12 are live gates. ADR-0032's deferred inventory is dated 2026-09-21 and its `main.py` line numbers no longer match | The dedicated unification change is small, and its inventory needs a refresh |
| Firelight | No bridge, pin file or `core/rules/firelight/` in the checkout. G0 ran no Firelight command | The 100 ms p50 / 250 ms p95 budget is a proposal with no fork measurement |
| Docs | `AGENTS.md:66-67` lists `test_compression.py` and `analyze_telemetry.py`; neither file exists | A documented quality command cannot be run |

### 3.3 Not verified by this review

- N2 gate progress and mise-en-scene status after the s10 text at `2a422fff`.
- Test-suite health and duration. No test was run.
- Which of the 84 direct writes persist state (only `main.py` and one
  `conversation_utils.py` site were inspected).
- Whether any script references `core/ai/conversation_compression.py`.
- Whether Narrator P2's manifest and fencing work can merge ahead of the
  Hindsight service (FR-33). The plan text allows it on a first reading only.
- Where today's load-time repair writes live (`plans/v2-spatial.md:134`).
  `utils/location_path_finder.py` has two direct `json.dump(` sites and is a
  likely place; this was not confirmed.
- The task counts for active OpenSpec changes (tooling 16/16, offline 5/5,
  execution 8/10, mise-en-scene 10/14, N2 22/23) come from a search pass.
- Superseded phrases in the s10.5 goal prompts ("merged by the owner", "booked
  with the Overseer", "per-worktree Hindsight namespace") were noted on a first
  reading and not re-located by line.

## 4. Owner decision sheet (one sitting)

Each item has a recommendation and a default that applies if it is not approved.

| ID | Decision | Recommendation | Default if not approved |
| --- | --- | --- | --- |
| OD-1 | How SP4 closes (FR-05) | Rate the seven rateable transcripts in the sitting. Record D1 as not audited and take the pilot's own fallback: new layouts come only from the Builder plus a small hand-authored set (`plans/v2-mapping-pilot.md:361`). Decide format in the S1b proposal, combat granularity and enforcement at SC0, and the data pipeline at S3/MB0 | SP4 stays open; S1 and later remain unproposable in practice |
| OD-2 | Open worktree R after the Narrator P0 gate instead of after the pilot gate | Approve. ADR-0034 settled spatial authority; S2 keeps first ownership of the exits block and atlas injection | R waits for SP4 |
| OD-3 | Confirm Narrator P0 and Firelight G1 may run in the main checkout; name the G1 toolchain and release download; ratify the G0 latency budget before G1 measures | Approve both. Neither is in the 2026-11-05 approvals list, though overview s7 schedules them | Neither starts |
| OD-4 | Replace worktree G's "after pilot SP3" condition | Replace with "after the G1 gate and the shared identity contract, with no frozen-configuration study in flight in S". SP3 collection is closed and SP3b is CLOSED BLOCKED | G waits on a condition that cannot change |
| OD-5 | New change: provider-free test runner and CI tier (FR-10) | Approve in main, advisory in CI first | Tests stay manual and per-change |
| OD-6 | Live-gate preflight rule (FR-11), including a one-line `AGENTS.md` addition | Approve. No booking ruling without a clean preflight at the SHA to be run | Windows keep finding harness defects |
| OD-7 | Run `tt-single-runtime-unification` now (FR-16) | Approve, before the Narrator P0 baseline capture, so the baseline measures the runtime that will exist | Every v2 phase regresses two code paths; the baseline measures a path due for removal |
| OD-8 | Narrator plan review: rename gate IDs N0-N6; extend P0 deliverables (FR-12); order P2 so manifest and fencing merge first (FR-33) | Approve the rename and P0 extension now. Approve the P2 order only after P0 confirms it | Gate IDs keep colliding with Network N0-N4 |
| OD-9 | Spatial plan review: split S1 into S1a and S1b (FR-21); add S2a (FR-31) | Approve. S1a needs no format decision | S1 waits whole on the format decision |
| OD-10 | Extend `v2-context-views` to start with a behaviour-preserving prompt-assembly extraction (FR-23); new change for atomic-write remediation (FR-24) | Approve both in main, before R reaches P3 | Four tracks edit `main.py` prompt code directly |
| OD-11 | Concurrency: at most three worktree goals at once (N, S/SB, R), with G replacing N when N retires; Builder MB0-MB1 held to Wave 4 | Approve. Owner review time is the limit, not builder capacity | As the index reads today |
| OD-12 | One seeded 1-PC and one four-PC capture session may feed more than one track's evidence where the scenario requirements of each owning plan are met in full | Approve as a rule; each ledger still judges its own rows | One window per track per gate |

## 5. Work packages

### Wave 0: reconcile and decide

#### FR-01 Ledger and index reconciliation (STANDING)

Where: overview s5, s6, s7, s10. One docs PR.

1. Reconcile the N2 row and the S row of s10.2/s10.3 from your own records.
2. Rebuild the s10.2 table from `git worktree list`. At review time: N is a
   detached HEAD at `c8d0b185`; S is on `feature/v2-llm-staging-study-prep` at
   `43e4c809`; `tmp/overseer/main-baseline` (detached `1a94e364`) is unlisted.
3. Add s10.3 rows for Narrator P0 and Firelight G1 as pending, each stating
   whether it is approved (OD-3).
4. Make s10.4 the complete list of pending owner actions: D1 audit, seven
   transcript ratings, format, combat granularity and enforcement, data
   pipeline, any Section 2 live evaluation, and the OD items above. Today it
   lists one item while s10.2 lists several more.
5. s5: replace "drafted at pilot SP4; accepted before S1 starts" with "ADR-0034,
   accepted 2026-11-09". Change "Network P1" to "Network N1" at overview lines
   180 and 187.
6. s7: add a dated revision note with actual dates beside the week bands. Do not
   rewrite the bands until the OD answers are recorded; then replace them with
   the gate-keyed order in section 6.
7. s10.5: do not edit the prompt of an open goal. Add a short note under the
   heading listing phrases that later s10.1 rulings superseded.
8. Leave s9.7 alone: `plans/v2-spatial.md` stays provisional until SP4 is
   recorded. That marking is correct today.

Acceptance: every s10.2 row matches `git worktree list`; every s10.4 item traces
to a ruling or an OD row; no verdict changes without evidence.

#### FR-02 Owning-plan status lines and ID hygiene

Part A (STANDING), editorial only:

- `plans/v2-server-client-network.md:3,8`: replace the DRAFT status with a
  pointer to overview s10.3. Point at the ledger rather than restating
  verdicts, so the line cannot drift again.
- `plans/v2-spatial.md:60`: "ADR needed ... SP4 drafts it" becomes a reference
  to accepted ADR-0034.
- `plans/v2-firelight-g0/design.md:3-9`: add one line noting ADR-0033 was
  accepted 2026-11-05.
- "Network P1" becomes "Network N1" at `plans/v2-spatial.md:203,292` and
  `plans/v2-firelight.md:224`.

Part B (OWNER, OD-8): rename Narrator gates N0-N6 to "Gate P0" through
"Gate P6" at `plans/v2-narrator.md` lines 522-528, 543, 558, 575, 577, 591,
608, 624, 632, 641, 819, 826, 857 and 858. Lines 819 and 826 are inside the
goal objective and completion criteria that the R goal quotes verbatim, so this
must land before the R goal is opened. It changes names only.

Acceptance: `grep -nE '\bN[0-6]\b' plans/v2-narrator.md` returns nothing;
`grep -n 'Network P1' plans/*.md` returns nothing.

#### FR-03 Dead commands in `AGENTS.md` (OWNER, quick confirm)

1. Run `git log --diff-filter=D --name-only -- test_compression.py
   analyze_telemetry.py` to find when they went and whether they moved.
2. Replace lines 66-67 with the successor commands, or remove them.
3. When FR-10 lands, add the runner command in the same block.

#### FR-04 Archive finished pilot changes (STANDING; session S performs it)

1. Confirm task state with `openspec list`. Archive `v2-mapping-pilot-tooling`
   and `v2-mapping-pilot-offline` if every task is checked. Archiving records
   the change as complete; it does not move SP2 to PASS.
2. `v2-mapping-pilot-execution` has unchecked tasks and SP3b is CLOSED BLOCKED.
   Stop point: ask whether to archive it with the BLOCKED record or leave it
   open. Do not check a task to make it archivable.

#### FR-05 SP4 closeout (OWNER, OD-1)

Where: worktree S, under the existing S goal.

1. S assembles one sitting packet: the seven rateable transcripts, the M1
   results already recorded, the D1 summary (20 attempts, 11 validated, 9
   invalid layouts, 1,048 claim rows unaudited) and the decision sheet.
2. S writes the SP4 report with the module-data requirements and gap list that
   s10.3 "SP4 handoff to the Module Builder" already specifies.
3. The owner rates the transcripts and answers OD-1. If D1 is recorded as not
   audited, S criterion 4 is met through its "reported blocked with evidence"
   branch (`plans/v2-mapping-pilot.md:435`), the 85 percent precision gate is
   recorded as not assessed, and S3 backfill stays closed.
4. The Overseer records the SP4 verdict from that evidence, lifts the
   provisional marking on `plans/v2-spatial.md`, resolves its `[pilot: ...]`
   placeholders with the recorded outcomes, and closes the S goal.

Do not: impute a rating, rerun a content-failed row, reopen SP3b, touch the
frozen preregistration, or treat a deferred format choice as a format selected
by pilot evidence.

### Wave 1: foundations that spend no gameplay budget

#### FR-10 Provider-free test runner and CI tier (OWNER, OD-5)

Where: main checkout. New change (suggested name `test-runner-ci-tier`).
Why: findings 3 and 4. Non-goals: fixing quarantined tests, moving files,
adopting pytest.

1. **Inventory (read-only).** Enumerate every test file. Classify by static
   markers: `unittest` or plain script; use of the tripwire helpers
   (`scripts/core_chat_test_safety.py`, `scripts/combat_tactical_test_support.py`);
   provider or network markers (25 files matched at review time); browser use;
   whether the import chain needs `config.py`.
2. **Baseline run** at a recorded SHA. Run each file in its own process with the
   existing convention, `PYTHONPATH=. .venv/bin/python -m unittest
   scripts.<module>` (overview line 677). Per-process isolation is required:
   co-loading tripwire-armed suites is a known limitation. Provider keys are
   absent from the environment. Record pass, fail, error, timeout and duration
   under `tmp/test-runs/<run-id>/`.
3. **Manifest** `scripts/test_manifest.json`. One entry per file with a tier:
   - `core`: provider-free and deterministic; runs in CI;
   - `slow`: provider-free but long; runs on demand;
   - `manual`: needs a provider, network, browser or live window;
   - `quarantine`: fails at the baseline SHA; carries a reason, the first-seen
     SHA and an owner.
   A test file missing from the manifest fails the run, so new tests are always
   classified.
4. **Runner** `scripts/run_tests.py` with `--tier`, `--jobs`, `--timeout` and
   `--report`. Subprocesses use argument lists, never a shell string. Output is
   ASCII with `[PASS]` and `[FAIL]`; the file carries the SPDX header and type
   hints. Add `scripts/test_run_tests.py` for the runner itself.
5. **CI** `.github/workflows/python-tests.yml` on pull requests and pushes to
   `main`. Actions pinned to commit SHAs with provenance recorded in the PR.
   Install from `requirements-lock.txt`. If tests need a `config.py`, CI copies
   `config_template.py` in the workspace only; nothing is committed. Run the
   `core` tier and upload the report. The check starts advisory.
6. **Frontend job**: `npm ci`, typecheck and unit tests inside `web/frontend/`
   using the scripts already in its `package.json`. Coordinate with N, which
   owns that directory; no frontend source changes.
7. After ten consecutive green runs on `main`, ask the owner to make the check
   required. Branch protection is an owner action.

Acceptance: one documented command reproduces the baseline counts; every
quarantine entry has a reason; a deliberately failing test fails the run (shown
by the runner's own test); the report shows no provider call; wall time is
recorded. Stop points: any new package or action beyond those named in the
approved proposal; any test that can only pass with a secret.

#### FR-11 Live-gate preflight (OWNER, OD-6)

Where: main checkout; capture tooling under `scripts/` and
`.opencode/skills/neq-capture-arena/SKILL.md`.
Why: finding 3. A preflight is a provider-free dry run of the whole gate against
a stubbed router on an isolated Capture Arena copy. It is its own evidence
class and never a gate PASS.

Each check answers a failure already on the record:

| Check | What it proves | Failure it answers |
| --- | --- | --- |
| PF1 Invocation identity | The run starts from the exact command, working directory and `PYTHONPATH` the live run will use | SP3b `ModuleNotFoundError: scripts` |
| PF2 Row coverage | Every scenario row runs end to end on the host path, including locations without same-area connectivity | SP3 landscape rows, host `NameError` |
| PF3 Fixture completeness | Every module file, party and monster template a row references resolves in the seeded copy | SP3 C01 missing goblin template |
| PF4 Lifecycle call profile | Startup and resume provider-call counts per fixture and party match the declared profile | SP3 C02-C08 unexpected call; SP3b profiles |
| PF5 Transport | The driver connects and completes the first scripted exchange for every row | SP3 E03-E05 lost transport |
| PF6 Stop rules | The attempt cap, time cap and three-consecutive-infrastructure pause each trigger under fault injection, enforced by the driver | Missed pause deviation; N2 documentation-only cap |
| PF7 Continuation | The harness proceeds past the first path and row | SP3b harness stopped after one path |
| PF8 Identity freeze | One source, dependency and routing identity hash is recorded; the live run must match it | Seven mid-matrix re-freezes |
| PF9 Teardown | Clean teardown and no listener on 8360 or 8370 | Lock hygiene |

Rules to record in s10.1 once approved:

- No ruling authorizes a live booking without a preflight report showing zero
  infrastructure failures at the SHA to be run.
- A preflight starts a server on 8360, so it takes the live-window lock like any
  other run. It spends no provider budget and no attempt allowance.
- Preflight evidence goes under `tmp/router-rollout/<gate>/<run-id>/preflight/`.

Acceptance: the preflight, run against the SP3 row set at a pre-#105 SHA,
reports the `NameError` rows; run at current `main` it does not. Use a
`tmp/` checkout for the old SHA. This is a test of the tool, not a pilot rerun,
and produces no pilot evidence.

#### FR-12 Narrator P0, extended (OWNER, OD-3 and OD-8)

Where: main checkout, docs under `plans/v2-narrator-p0/` (mirroring
`plans/v2-firelight-g0/` and `plans/v2-memory-pilot-p0/`). The P0 tasks and gate
in `plans/v2-narrator.md:530-545` are unchanged. The additions below make P0
the place where the cross-track contracts are fixed once.

- **A. Event envelope field map.** Read `core/combat/turn_commit.py`,
  `web/extensions/player/contracts.py`, `memory_events` and
  `memory_event_provenance` in `core/memory/memory_db.py`, and the receipt
  design in `plans/v2-firelight-g0/design.md:154-198`. Deliver one table:
  envelope field, existing source, migration needed, consuming tracks. Reuse
  `turn_id` and commit identity where they exist. Firelight receipts supply
  commit identity for engine-decided changes (overview line 400).
- **B. One identity contract** for Narrator P1, Spatial S1 and Firelight G2,
  co-reviewed by all three. Recommended starting position, for P0 to ratify:
  - an ID is minted once, stored in the canonical owner record (character JSON,
    module area and map files, encounter files), and never derived from a
    display name;
  - authored things (locations, features, authored NPCs, monster definitions,
    quests) are module-qualified; things created in play (PCs, item instances,
    effect instances) are campaign-scoped;
  - legacy names and bare IDs resolve through an alias index; evaluate the
    existing `entities` and `entity_aliases` tables for that role. The index is
    never the source of truth;
  - the contract lists every kind Firelight's typed IDs require, and states how
    an ID survives rename, NPC-to-PC promotion (ADR-0018) and module
    transition.
- **C. Hotspot seam map.** Extend section 8 of this document into a reviewed
  table of functions, owners and merge order.
- **D. Baseline.** Per-block byte counts and cached-token logging (C7), then
  reference captures at 1-PC and four-PC. The logging is a runtime change: mark
  it `# TABLETOP MODE:`, put it behind a `debug_config.py` category, and prove
  with a test that the messages sent are byte-identical with it on and off. The
  captures need a live window, so FR-11 comes first, and FR-16 if OD-7 is
  approved.
- **E. Compression inventory.** One row per mechanism: caller, trigger, input,
  output destination, model call, and whether the diary or Story readers depend
  on it. Flag `agnostic_conglomerator.py` and `conversation_compression.py` as
  removal candidates. Removal itself belongs to P4 or a small cleanup change.
- **F. Persistence inventory.** Classify all 84 direct `json.dump(` sites as
  persisted state, debug or log output, or temp file. This feeds FR-24.
- **G. Budgets** are ratified before any candidate measurement, as the plan
  already requires.

Acceptance: the Narrator plan's P0 gate, plus A, B, C, E and F reviewed. B is
signed by the Spatial and Firelight plan owners in the same review.

#### FR-13 Firelight G1 offline spike (OWNER, OD-3)

Where: `scripts/` and `tmp/` only; no runtime hook
(`plans/v2-firelight.md:202`).

1. Before measuring, the owner ratifies or amends the proposed budget: p50
   100 ms, p95 250 ms, at most two calls per turn
   (`plans/v2-firelight-g0/design.md:200-217`). The Narrator's
   no-retrospective-relaxation rule should apply here too.
2. A ruling names the toolchain and the release download. Treat the archive as
   untrusted: its own empty directory under `tmp/`, checksums verified against
   the published `SHA256SUMS` before anything runs.
3. Build from the pin. Project worlds from seeded 1-PC and four-PC Capture
   Arena copies. Measure p50 and p95 call latency and world-source size,
   including the 10,000-item stress case. Replay a recorded session's inventory
   and resource changes.
4. Answer the G0 gap list with evidence: the 28-day campaign calendar against
   the 30-day effect counter, coin double-count, the missing rest scheduler,
   route durations, derived versus stored totals, duplicate effects and
   receipt-less retries (`plans/v2-firelight-g0/gap-inventory.md:280-291`).

Gate (unchanged): latency fits the ratified budget; the owner reviews the gap
list. Add a G1 row to s10.3.

#### FR-14 Memory Pilot P0 close (STANDING; approved 2026-11-05 as Stage 0 docs)

Deliver the fixture, rubric and budget contracts that s10.3 records as
outstanding, under `plans/v2-memory-pilot-p0/`. Read-only work on `tmp/`
copies; no installed database is queried; the withdrawn producer request stays
withdrawn.

#### FR-15 N2 live gate, then N3 (RULED)

Unchanged. Testers remain the first priority. The N2 cap-enforcement proof is an
instance of PF6; if FR-11 is approved before the gate runs, use it.

#### FR-16 Single-runtime unification (OWNER, OD-7)

Where: main checkout. Change name from ADR-0032: `tt-single-runtime-unification`.
Its precondition, "after the router/combat workstreams land", was met at B0.

1. Refresh the ADR-0032 deferred inventory. Sites seen at review time:
   `main.py:2820, 5115, 8023, 8069`; `core/generators/combat_builder.py:164`;
   `core/combat/multi_pc/manager.py:56, 347, 2402`; `utils/pc_manager.py:119-148`;
   `web/web_interface.py:1089-1119`;
   `utils/compression/multi_pc_conversation_compressor.py:598`;
   `utils/multi_pc_dm_note.py:55`; `config_template.py:86`; and the
   `len(party_members) > 1` gates the ADR lists.
2. State the target for each site: the tabletop path always runs, and a one-PC
   party is its minimum. Decide in the proposal how an existing `config.py`
   that sets the flag to `False` is treated; do not add a new gate.
3. Golden prompt tests at 1-PC and four-PC before and after. One-PC prompts will
   change for installs that ran with the flag off; say so in the proposal.
4. Coordinate the `web/web_interface.py` site with N.
5. Land it before the FR-12 baseline capture and before R opens.

Acceptance: no runtime reference to `MULTIPLAYER_MODE` outside a documented
compatibility read; focused tests at both party shapes; the live capture the
proposal requires, judged by the primary orchestrator.

### Wave 2: first runtime contracts

#### FR-20 Narrator P1 in worktree R (OWNER, OD-2)

Tasks and gate as in `plans/v2-narrator.md:547-560`. Land it as three PRs so
the other tracks can rebase early:

1. identity registry and migrations (contract FR-12 B);
2. envelope and commit hooks, generalising `core/combat/turn_commit.py`;
3. backfill, anchors and delivery repair.

PR 1 merging is the trigger for S1a event IDs, Firelight G2 and worktree M.

#### FR-21 Spatial S1a and S1b (OWNER, OD-9; SB goal in worktree S after SP4)

- **S1a (no format decision needed).** Module-qualified stable location and
  feature IDs with legacy aliases; a read-only graph loader, with today's
  load-time repair writes moved to explicit, previewable remediation; the
  `SpatialService` query API over existing `map_*.json` and area files. Build
  on `core/managers/location_manager.py`, `utils/location_path_finder.py`,
  `utils/authoritative_state_packet.py` and the validators in
  `core/validation/validate_module_files.py`. Exit: collision-safe IDs across
  all published modules; loading writes nothing; 1-PC and four-PC regression;
  module validators pass.
- **S1b.** The scene layout schema, after the format decision and the results
  of `v2-mise-en-scene-authoring-projection-evaluation`; the campaign spatial
  overlay through a canonical JSON writer that the Narrator save manifest later
  adopts (`plans/v2-spatial.md:142-144`); movement, discovery and feature
  changes as committed events after FR-20 PR 2.

The S1 exit criteria are unchanged; S1 passes only when both halves do. The
mise-en-scene change finishes under its existing rulings and is not disturbed.

#### FR-22 Firelight G2 in worktree G (OWNER, OD-4)

Content as in `plans/v2-firelight.md:203`. Prerequisites restated: G1 gate,
identity contract FR-12 B, and FR-20 PR 1 merged. At the next Firelight plan
review, state that shadowing covers the G4-G6 families only; G3 families are
new state with nothing to shadow (`plans/v2-firelight-g0/design.md:108-114`).

#### FR-23 `v2-context-views` as the prompt-assembly seam (OWNER, OD-10)

Where: main checkout, before R reaches P3 and before S2.

- **Step 1, extraction with no behaviour change.** Move prompt assembly behind
  one module that composes named, ordered blocks. Blocks seen at review time:
  campaign summaries (`conversation_utils.py:96`), module atlas (`:856`, via
  `core/ai/atlas_builder.py`), character data (`:995`), companion memory packets
  (`:466-575`), the DM note and its exits block (`main.py:7511`,
  `utils/multi_pc_dm_note.py`), the authoritative state packet, the validation
  prompt (`main.py:1577`), DM-note truncation (`main.py:3195`), the atlas filter
  (`main.py:4827-4930`) and the combat prompt path
  (`core/combat/turn_commit.py:114`). Each block reports its byte count, which
  also delivers FR-12 D. Golden tests capture the outgoing message list for
  seeded 1-PC and four-PC fixtures before the change and require byte-identical
  output after it.
- **Step 2, the context views themselves**, as overview s8.4 lists them: compact
  validator evidence, one mention per fact, fixed instructions in the system
  prompt, typed history markers. Measured against the P0 baseline.

The seam is mechanical. Layering policy, the cacheable prefix and the Archivist
remain Narrator P4's; co-review the block interface with the P0 packet
contract so P4 is not pre-empted. After Step 1, S2, P3, P4 and G4-G6 add or
change a block instead of editing `main.py`.

#### FR-24 Atomic persistence remediation (OWNER, OD-10)

Where: main checkout. Depends on FR-12 F.

1. Convert every site classified as persisted state to `safe_write_json` or the
   canonical writer for that record. `conversation_utils.py:1256` is the first
   known case.
2. Leave debug dumps, JSONL logs and temp files; annotate each with a one-line
   reason.
3. Add a guard test with an allowlist so a new direct state write fails.
4. Sequence the edits file by file around active worktrees; `core/combat/`
   sites wait for the SC owner.

Acceptance: no unclassified direct write in runtime code; guard test in the
`core` tier.

### Wave 3: first things players notice

| ID | Package | Class | Notes |
| --- | --- | --- | --- |
| FR-30 | Network N4, invited testers | RULED sequence | Unchanged |
| FR-31 | Spatial S2a | OWNER, OD-9 | See below |
| FR-32 | Firelight G3: storage, trade, charged items | Per the G goal | Joins a tester build only if merged before the tagged SHA (overview s7) |
| FR-33 | Narrator P2, ordered | OWNER, OD-8 | See below |
| FR-34 | Memory Pilot P1-P2 on the 240-fragment bundle, worktree M | OWNER (worktree M) | Opens after FR-20 PR 1 merges, as the index already says |

**FR-31 Spatial S2a.** Depends on S1a and FR-23 Step 1. A Narrator spatial
packet built from existing topology: exits with known or explicitly unknown
destinations, adjacency, and open-fact markers in ADR-0034's provenance terms.
Pair it with a Python-side check, carried as evidence in the existing
validation call, that flags narration asserting a destination for an unknown
exit or relocating an anchor. S2a replaces the names-only exits block and the
per-turn full atlas with the packet and a compact orientation summary. It is
measured on the pilot's exploration rubric at 1-PC and four-PC. It makes no
claim to pass S2: the bounded packet format, `querySpatial` and the S2 exit
thresholds wait for S1b.

**FR-33 Narrator P2 order.** Inside P2, merge the manifest, snapshot, timeline
fencing and campaign-switching task (`plans/v2-narrator.md:570-571`) first, as
"P2a". Hindsight service lifecycle, retain-to-recall and clean-host import
follow as "P2b". The P2 gate is unchanged and still needs the real service.
The proposed change is to the prerequisite other tracks quote: Memory Pilot P3,
Builder MB3, the S1b overlay and the Firelight live-state record would wait on
"P2a merged" instead of the P2 gate. FR-12 must first confirm that the manifest
can carry bank-registry and ingestion fields as empty until P2b
(`plans/v2-narrator.md:477-490`). If it cannot, drop this package.

### Wave 4 and later

Order as the owning plans give it:

- S1b, S3, S4; SC0-SC2; G4-G5; Narrator P3-P4; Pilot P3-P4; TITAN P0; Builder
  MB0-MB2.
- Then Narrator P5-P6; SC3-SC4; G6; TITAN P2 onward; MB3-MB5; S5.

Builder MB0-MB1 need no TITAN runtime, Hindsight service or production seed and
stay clear of the hotspots. They can move earlier whenever the owner has review
time for a fourth stream (OD-11).

## 6. Revised order

```text
Wave 0  FR-01 ledger | FR-02 status + IDs | FR-03 AGENTS | FR-04 archive
        owner sitting: OD-1..OD-12 ; FR-05 SP4 closeout -> S goal closes
Wave 1  main: FR-10 runner+CI ; FR-11 preflight ; FR-16 unification
        main: FR-12 Narrator P0 (A,B,C,E,F docs -> D baseline after FR-11, FR-16)
        main: FR-13 G1 (budget ratified first) ; FR-14 Pilot P0 close
        N:    FR-15 N2 gate -> N3
Wave 2  main: FR-23 step 1 seam -> step 2 context views ; FR-24 atomic writes
        R:    FR-20 P1 (PR1 identity -> PR2 envelope -> PR3 backfill)
        S/SB: FR-21 S1a (after SP4) -> S1b (format + P1 PR2)
        G:    FR-22 G2 (G1 gate + identity + P1 PR1)
Wave 3  N: N4 testers ; SB: FR-31 S2a ; G: FR-32 G3
        R: FR-33 P2a -> P2b ; M: FR-34 Pilot P1-P2
Wave 4+ as the owning plans order it
```

What moves compared with overview s6 and s7:

- R opens on the Narrator P0 gate, not the pilot gate.
- G opens on the G1 gate and the identity contract, not on "pilot SP3".
- S1a is separable from the format decision.
- One identity contract and one prompt-assembly seam land before the tracks
  that depend on them, instead of inside whichever track gets there first.
- Unification lands before the baseline that every later comparison uses.

## 7. Live-window rules

1. Preflight before booking (FR-11).
2. Caps are enforced by the driver and proven by PF6. A cap that exists only in
   a document does not count.
3. Shared sessions (OD-12): a session may serve more than one ledger only when
   each owning plan's scenario, party-shape and evidence requirements are met in
   full for that row. Each ledger records its own verdict.
4. Book in this order when requests collide: Network gates (testers), then
   baseline captures that other tracks compare against, then track gates.
5. Unchanged: isolated Capture Arena copy, port 8360, `NEQ_OPEN_BROWSER=0`, the
   repository venv, evidence preserved before teardown, and the primary
   orchestrator judges.

## 8. Hotspot ownership and merge order

| Surface | Location | First owner | Then |
| --- | --- | --- | --- |
| Party-size gates | `main.py:2820, 5115, 8023, 8069` and the files in FR-16 | FR-16 | Nobody; the gates are gone |
| Prompt assembly | `main.py:4981` (`get_ai_response`), `conversation_utils.py:575` (`update_conversation_history`) | FR-23 Step 1 | Tracks add blocks |
| Exits block and atlas | `main.py:7511`, `conversation_utils.py:856`, `main.py:4827-4930` | S2a/S2 (overview s7) | Narrator P3/P4 rebase onto it |
| Validation prompt | `main.py:1577` | FR-23 Step 2 | G4-G6 remove rule sections per cutover |
| Commit and receipts | `core/combat/turn_commit.py`, `updates/update_character_info.py` | FR-20 PR 2 | G2 bridge; SC for `core/combat/` |
| Event store | `core/memory/memory_db.py` migrations | FR-20 | Pilot P1-P3 extend the same chain; no second chain |
| Compression | `core/ai/*compression*`, `utils/compression/` | Narrator P4 | Cleanup of the two unused modules may go earlier as its own small change |
| Player web | `web/extensions/player/`, `web/frontend/` | N | S4 and SC4 only through the Network protocol |
| Host web | `web/web_interface.py` | N until N2 merges | Builder host changes coordinate with N |

Rules that already hold and stay: small PRs per phase; rebase the other
worktrees after each merge; the Narrator branch stays out of `web/` until N2
merges; `core/combat/` belongs to SC.

## 9. Risks and limits

- **Review load.** This plan adds five small changes in main (FR-10, 11, 16,
  23, 24) while N and S are active. If the owner's review time is short, the
  order of value is FR-11, FR-10, FR-23, FR-16, FR-24.
- **FR-16 changes one-PC prompts** for installs that ran with the flag off. It
  needs its own live regression and must not ride along with another change.
- **FR-23 could pre-empt Narrator P4.** Step 1 is limited to byte-identical
  extraction for that reason.
- **FR-33 may not hold.** It depends on a manifest design that P0 has not yet
  written.
- **S2a may not move the rubric.** SP3 gives no evidence that a packet helps. If
  the measurement shows no improvement, record that and keep the Python-side
  check, which has value on its own.
- **Quarantine can hide regressions.** The manifest is reviewed in every PR that
  touches it, and no entry is added without a reason and a first-seen SHA.

Not proposed, deliberately: reopening SP3b; any installed-campaign operation;
drive-by `MULTIPLAYER_MODE` edits outside FR-16; changes to N3 or N4 scope;
waiving or merging any gate; changes to accepted ADRs.

## 10. Verification record

Checked directly at `2a422fff` on 2026-11-10:

- File sizes for `main.py`, `web/web_interface.py`, `core/ai/action_handler.py`,
  `core/combat/combat_manager.py`, `updates/update_character_info.py` and the
  twelve compression modules (`wc -l`).
- `MULTIPLAYER_MODE` sites (`git grep -n`, Python outside `scripts/`).
- `json.dump(` and `safe_write_json(` counts (`git grep -c` over `core/`,
  `utils/`, `updates/`, `web/`, `main.py`); the ten `main.py` sites and
  `conversation_utils.py:1246-1260` by reading.
- Compression module importers by fixed-string search outside `scripts/`;
  `agnostic_conglomerator` across all tracked files outside `plans/`,
  `openspec/` and `docs/`.
- `memory_db.py` table list and the `memory_events` column list.
- `core/combat/turn_commit.py` and `utils/authoritative_state_packet.py`
  function lists; `conversation_utils.py` function list.
- Workflow files: no line mentions `unittest`, `pytest`, `test_`, `npm test`,
  `npm run`, `npm ci`, `vitest` or `playwright`.
- `AGENTS.md:66-67` against the tracked file list.
- `git worktree list`.
- Plan text: overview s6, s7, s8.4, s9, s10.1-s10.4; Narrator s14 P0-P2 and the
  N-gate line list; Spatial S1 and S2; ADR-0032 deferred inventory; pilot
  completion criterion 4 and the D1 fallback row; "Network P1" references.

Taken from search and extraction passes, not re-read line by line: phase tables
for TITAN, Memory Pilot and Module Builder; Firelight G0 design and gap
inventory details; the Network N3-N4 text; OpenSpec task counts; the test-file
style counts. Confirm these before quoting them in a ruling.
