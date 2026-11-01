# Combat x OpenRouter Alignment Plan

> Archived 2026-10-31: Historical reference only; this document does not authorize new implementation. Current contracts and evidence live in OpenSpec. Older, optional, or future scope is not thereby declared shipped.

Updated: 2026-10-14
Status: EIGHT-CHANGE ROLLOUT IN PROGRESS; G2 verified, G3 implementation incomplete; orchestrator-owned capture gates required
Owner: Combat/tabletop runtime and LLM platform

Inputs:

- `plans/archive/combat-manager-refactor.md` (combat architecture and targets)
- `plans/archive/openrouter_llm_router_architecture.md` (v5 Auto routing contract)
- `openspec/changes/llm-router-facade/` (existing implementation-ready artifacts)

Authority: `AGENTS.md` governs repo-wide constraints; active OpenSpec artifacts
govern their change scope. This plan maps the approved work to changes and gates.
It does not authorize implementation without first authoring the owning change.

## 1. Settled Decisions And Evidence

| ID | Decision | Status / evidence |
|---|---|---|
| D1 | Combat package `core/combat/` and `core/combat/multi_pc/`, with old-path shims | Owner-confirmed 2026-09-21 |
| D2 | Fixed latency targets retained; compare only equivalent fixtures and model/provider identity | G1 archived design; current-model reference captured within build 4 |
| D3 / R2 | NL fast-path canary belongs to hot-path work; client timeouts belong to factory | Existing approved combat plan |
| D6 | Decision seams belong to owning changes; no separate pre-Jev change | Existing approved combat plan |
| R1 | Combat migration follows decomposition | Required interleave |
| R3 | Task/retry context is explicit through router/factory | `task_id` finalizer input; `retry_tier` escalation |
| S1 | One tabletop runtime, 1-PC regression floor plus multi-PC coverage | ADR-0032 |
| M1 | Preferred direct-OpenAI model is configurable `gpt-6-luna`; Nano is deprecated | Owner 2026-10-13; model refresh is intentional |
| M2 | Narrator/combat/Titan default to configurable `openrouter/auto` | Owner 2026-10-13; actual model/cost accounted from response |
| B1 | Live candidate bake-off accepted successful | Owner attestation 2026-10-13; no numerical report supplied |
| A1 | Activate at build 7, after migrations, hot-path measurement, and commit/replay work | Eight-change completion path requested by owner 2026-10-13 |
| A2 | Separate core and remaining chat migrations | Eight-change completion path requested by owner 2026-10-13 |
| A3 | Jev runtime promotion remains gated and outside this goal | Ordinary action predictor migrates as chat in build 5 |
| C1 | Primary orchestrator executes and judges isolated live capture gates | Owner 2026-10-14; runbook, scenario prerequisites and evidence matrix below |

Completed baseline:
`openspec/changes/archive/2026-09-22-combat-latency-baseline/design.md` records
G1 satisfied, fixed 1-PC/multi-PC captures, and ratified targets. Do not redo that
change or relabel its `gpt-5.6-luna` captures as new-model evidence. Build 4 captures
a `gpt-6-luna` pre-optimization reference to isolate structure from model changes.

B1 satisfies only live candidate selection. It does not complete facade software,
provider-free tests, transport smoke, or activation rollback. No mandatory repeated
bake-off; optional future benchmarking stays available.

## 2. Required Eight-Change Execution Order

| Build | OpenSpec change | Gate | Current state |
|---|---|---|---|
| 1 | `llm-router-facade` | G2 | Verified; final-verification report records 21 tasks and 131 tests; B1 accepted |
| 2 | `combat-manager-decomposition` | G3 | Artifacts strictly validated; implementation in progress; capture tooling and live gate pending |
| 3 | `llm-router-core-migration` | G4 | Author artifacts before implementation |
| 4 | `combat-latency-hot-path` | G5 | Author artifacts before implementation |
| 5 | `llm-router-remaining-callsite-migration` | G6 | Author artifacts before implementation |
| 6 | `combat-turn-commit-and-receipts` | G7 | Author artifacts before implementation |
| 7 | `llm-router-openrouter-activation` | G9 | Author artifacts before implementation |
| 8 | `llm-router-cleanup` | G10 | Author artifacts before implementation |

The owner-approved validation-context correction for G3 is a narrow exception to
dynamic validation-context byte parity only: committed Python state is distinct
from proposed candidate changes, candidate-derived `touchedChanges`/`ALREADY_APPLIED`
claims are not proof, and independently established prior applied events remain
trusted. Unrelated prompt/context bytes and extraction parity outside the named
correction remain mandatory. The eight-change sequence and all gates are unchanged;
this correction does not implement G7. See the owning decomposition OpenSpec
artifacts for task and test boundaries.

G0 is scope-local worktree ownership review, not a demand to erase unrelated dirty
files. G8 / `combat-typed-resolver-expansion` is optional follow-on work and does not
block build 7. Image/audio cutover, Jev, new Titan runtime, and mode-flag removal
remain outside this eight-change goal.

### Gate Definitions

| Gate | Required evidence |
|---|---|
| G0 | Intended edit roots identified; unrelated local work preserved |
| G1 | Completed archived OpenAI baseline; use existing evidence |
| G2 | Approved model/profile config, factory task policy, Auto isolation, actual-cost accounting, provider-free router/harness tests; B1 already PASS |
| G3 | Combat suites, static/dynamic prompt byte parity and shims; primary-owned 1-PC/4-PC capture matrix including initiative, death saves, exit and resume replay |
| G4 | Core production chat routed; factory timeout and retry/task policy parity; primary-owned 1-PC/4-PC core narrator/combat captures |
| G5 | Primary-owned comparable current-model before/after captures meet ratified latency/call/write targets; skip/NL rates recorded |
| G6 | Fresh production chat inventory has no transport bypass, including action predictor and mixed-media prompt chat; tripwire/contracts intact |
| G7 | Owning artifacts define and verify character-first/encounter-last commit, post-commit phase work, and success publication; interrupted-write tests plus primary-owned restart captures converge without duplicate mechanics/receipts/rewards; code owns rounds |
| G9 | Primary-owned narrator/combat Auto captures for both party shapes, actual model/cost, controlled direct gpt-6-luna fallback and live rollback; Titan config/fake transport only |
| G10 | Deprecated plumbing removed, primary-owned full-session/save/resume captures and `/usage`/session/week accounting evidence, docs/OpenSpec checks pass |

### Primary-Owned Capture Matrix And Evidence Contract

Every listed live gate MUST be authored into its owning OpenSpec artifacts before
implementation. The primary orchestrator executes it after focused tests/tooling
pass, using `.opencode/skills/neq-capture-arena/SKILL.md`. Builders implement tooling
or focused fixes; neither their report nor a successful process exit owns the verdict.

| Gate | Required capture coverage | Acceptance focus |
|---|---|---|
| G3 | Both party shapes: `combat-smoke`, `initiative-pc`, `initiative-dm-tie`, `death-save`, `surrender-exit` (separate surrender/explicit-exit runs), `resume-replay` | Roster/actor identity, phase/round-start markers, Python death saves and HP, eligible non-PC batch, server remains alive after exit, no duplicate mechanics/rewards on resumed completed turns; static/dynamic prompt parity tests alongside captures |
| G4 | Both party shapes: narrator dialogue/travel and combat smoke, core task/retry/fallback-notification observations | Correct routed operations, authoritative state, preserved prompt/return/timeout/retry policy and displayed output; direct OpenAI remains selected |
| G5 | Equivalent 1-PC/4-PC fixed latency scripts before and after hot-path edits, same current model/provider/seed and measurement method | Ratified p50/call/write targets, per-action/batch attribution, validation skip and NL hit/miss rates; driver quiet-window time distinguished from work time |
| G7 | Both party shapes: preserved completed-turn replay and controlled interruption at approved character-first/encounter-last commit, post-commit phase-work, and success-publication boundaries; restart without reseeding | Owning artifacts specify intended ordering and expected/observed failure/replay state at each boundary; receipts/applied IDs, single HP/resource/enemy/reward effects, code-owned rounds; fault injection stays sandbox-only |
| G9 | Both party shapes: narrator/combat Auto, controlled transport failure to preferred direct OpenAI, and preferred-model live rollback | Requested versus resolved model, actual provider, finite reported/estimated/unpriced costs and completeness, bounded recovery, one-restart rollback; no live Titan runtime invented |
| G10 | Both party shapes: bounded full session with narration, combat, save and restart/resume; `/usage` plus Debug session/week observations | No duplicate mechanics/rewards/chat costs, coherent actual/estimated/unpriced accounting, media cost events preserved, save/restore and final runtime behavior |

G6 remains the complete production-operation inventory and focused migration tests;
it does not authorize an unrelated generator/media/Titan live capture matrix.

Before G3, the existing driver/seeder/fixture/report helpers MUST gain the bounded
named scenarios and evidence checks in decomposition tasks 4.3/4.4. Default scripts
currently do not exercise every required G3 branch. Keep those tasks unchecked until
implemented and provider-free tested; planned scenario IDs/options are not claimed
to be available CLI features. Preserve original latency scripts for G5 comparison.

For each gate/scenario/party run, create a unique
`tmp/router-rollout/<gate>/<run-id>/` evidence bundle before teardown. It MUST include:

- Scenario/version or hash, party roster/size, seed, step list, timestamps and bounds;
  source HEAD plus relevant dirty-worktree digest, configured model/profile/provider,
  and actual resolved response models when observable (required for G9/G10).
- Verbatim transcript, owned-server log, trace/report, and read-only before/after
  sandbox snapshots needed for mechanical, history, save or receipt assertions.
- Required-check inventory with expected/observed values and evidence references;
  actual step/request/timeout counts, cost provenance/completeness where required,
  and primary `PASS`, `FAIL`, or `BLOCKED` verdict with a reason.

Raw evidence stays under `tmp/`; OpenSpec and the goal plan store concise verdicts
and artifact references. Never record credentials or treat synthetic metrics as live.
Missing scenarios/assertions, required step timeouts/caps, failed checks or degraded
required evidence cannot PASS. Driver exit 0/report exit 0 alone cannot PASS.
Expected lifecycle disconnects must be declared before execution, not retrospectively
used to dismiss a timeout. Sparse combat trace on narrator-only turns is non-applicable
only when their required transcript/state/model evidence is supplied explicitly.

Runs MUST use a real copy at `tmp/combat_capture/`, port 8360, repository venv and
`NEQ_OPEN_BROWSER=0`. Snapshot initial state, preserve evidence before cleanup, stop
only the owned sandbox process, and verify no capture writes reached the installed
campaign. Controlled restart scenarios retain their sandbox state and do not invoke
`--prepare` between interruption and resume. Teardown must not discard missing evidence.

An attributable failure is repaired through focused builder delegation, then the
primary reruns affected scenarios. Missing transport/tools/coverage is BLOCKED, not
permission to weaken the gate. Record each gate in its change and the overall goal
plan; no later phase may start with a required predecessor capture incomplete.
The goal must be active before live execution. Planning/guideline maintenance leaves
a paused goal paused. Existing G1 and owner-attested B1 remain accepted references;
this matrix does not require a repeated baseline or candidate bake-off.

## 3. Change Outlines

Each new change MUST have proposal, design, smallest justified capability set, and
dependency-ordered tasks with concrete verification. Scaffold through
`openspec new change`; use the project schema instructions. Reuse existing specs
where appropriate rather than creating duplicated capabilities. No later change
requires predecessor archiving: verified predecessor artifacts/deltas are usable
as dependencies until separately requested archive/spec sync.

### Build 1: `llm-router-facade`

Scope: model config refresh to `gpt-6-luna`; three Auto/fallback profiles; concrete
defaults; independent task overrides; task-aware parameter finalization; `extra_body`
normalization; client-level timeouts; `llm.call()`; unavailable `llm.decide()`;
actual-model/provider-cost stats; provider-free benchmark harness.

Use the existing three capabilities only: `llm-router-facade-api`,
`llm-model-profile-routing`, `llm-factory-param-finalization`.
No production consumer migration, combat edits, OpenRouter activation, or media cutover.
Owner-attested live acceptance is recorded in task 6.4. G2 software verification is
recorded in `openspec/changes/llm-router-facade/reports/final-verification.md`; do not
reopen it for the later live capture workflow.

### Build 2: `combat-manager-decomposition`

Scope: `core/combat/` package, `CombatSession`, nine named stages, multi-PC
subpackage, old-path re-export shims, dependency ownership, error/logging and dead
code cleanup. Preserve prompts byte-for-byte, mechanics, and active session behavior.
Repoint source-contract tests without weakening assertions.

Suggested capability grouping: package/shim/session ownership; named turn stages
and decision seam; behavior/hygiene parity. Gate G3. No prompt rewrite or latency
optimization in the structural change. Its existing driver/seeder/fixture/report
extensions are narrowly test tooling for G3 coverage, not new runtime behavior.
Complete the G3 capture prerequisites and matrix before closing this change.

### Build 3: `llm-router-core-migration`

Scope: named combat stages, `main.py`, `core/ai/action_handler.py`; task mapping,
timeout ownership, high-retry reasoning parity, prompt/return contracts, fallback
notifications, and session stats reset. Re-inventory actual calls rather than
enforcing historical 9/5/6 site counts.

Suggested capabilities: core routing parity; factory timeout/retry policy;
core usage/notification integration. Keep `LLM_PROVIDER = "openai"`. Gate G4.

### Build 4: `combat-latency-hot-path`

Scope: round-boundary rather than per-message LLM compression; deterministic stale
history trimming; validation-skip wiring; head/context memoization; one guarded
encounter sync per turn; write-on-change; debug capture gating; NL fast-path canary;
deterministic retry-shape policy. Existing numerical targets are in combat plan
section 1.1; keep archived G1 reference and current-model reference distinct.

Before optimization, capture equivalent `gpt-6-luna` fixture timings. Record
before/after stage/provider budgets, validation skip and NL hit/miss rates. Do not
claim a provider model change as a structural latency win. This capture belongs
inside build 4, not an extra change. Gate G5.

Compression-engine file ownership settles here; build 5 only migrates what remains.
Timeouts remain factory-owned; declarative effects are outside scope.

### Build 5: `llm-router-remaining-callsite-migration`

Scope: summaries/validation, startup interviews, web chat, generator/builders,
memory/diary/story compiler, updates, toolkit/adaptation/reconciliation utilities,
and remaining compression consumers. Compile and test each migrated tier.

Include `utils/action_predictor.py` as `llm.call(task="action_prediction", ...)`,
preserving its current boolean result and fail-open behavior. This supersedes its
old Jev-only exclusion; it does not authorize Jev. Inventory chat operations in
mixed image/audio files and migrate those chat operations only.

Gate G6: all production chat operations use the facade. Provider transport/factory
infrastructure and test fixtures are the only justified chat-call exclusions;
non-chat image/speech calls remain separate. Remove unused backup/tooling code
after reference checks. Configure `titan_cycle` without adding a Titan scheduler.

### Build 6: `combat-turn-commit-and-receipts`

Scope: reviewed single authoritative commit path: stage character updates first,
persist the encounter last, perform phase work after commit, and publish success only
after commit/phase completion; turn receipts/applied IDs, idempotent crash/restart,
and code-owned round advancement. This approved ordering change is deferred from G3
decomposition. Before implementation, this change's owning artifacts MUST define
the ordering and expected failure/replay observations at character write, encounter
write, post-commit phase work, and success publication boundaries. Preserve Python
state authority and existing replay guard contracts. Test interrupted writes and
resumed turns; no duplicate HP/resources, rewards, or enemy batch effects. Gate G7.

### Build 7: `llm-router-openrouter-activation`

Scope: `LLM_PROVIDER = "openrouter"`, `ACTIVE_PROFILE = "production-auto"`,
independent narrator/combat/Titan configuration, live transport/gameplay smoke,
actual-model cost accounting, and one-restart rollback to direct `gpt-6-luna`.

Successful candidate selection is already accepted; do not impose a new bake-off
or an additional routine approval round. Test the implemented request shape,
task policies, 1-PC and multi-PC play, and cost completeness. Verify fallback with
controlled failure injection and rollback with the live preferred OpenAI model.
If no Titan runtime exists, prove the task configuration and fake transport;
do not claim a live Titan application run. Gate G9.

### Build 8: `llm-router-cleanup`

Scope: remove unused selection constants/helpers, alias, legacy imports, retired
migration tooling and unused validator backup; retain necessary factory transport
and parameter/notification ownership. Add `/usage`, reconcile Debug session/week
chat costs with actual/estimated/unpriced provenance, preserve media cost events,
sync durable docs, and verify full session/save/resume behavior. Gate G10.

## 4. Accelerated Orchestrator Execution Contract

- Persist one overall goal plan with all eight phases and completion criteria before
  implementation. The current task never replaces the overall objective.
- Create missing artifacts just in time from these settled outlines; validate before
  implementing. No extra change for already-recorded owner decisions or bake-off.
- Delegate focused implementation tasks under `openspec-build-loop` verification
  when executing the orchestrator goal. Parallelize independent reads/checks/artifact
  preparation; serialize tasks that share files. Do not parallelize overlapping
  combat or factory mutations.
- Immediately record verified task/phase evidence and choose the next unfinished
  phase. Do not stop after the facade or merely after creating later artifacts.
- Use `.venv/bin/python`; keep source/output ASCII, atomic persistence, and 1-PC plus
  multi-PC regression coverage. Run each required check once; rerun only after
  relevant changes/failures. Provider-free tests never perform network calls.
- The primary runs the required capture matrix through the existing socket-driven
  Capture_Arena skill after focused tests. Preserve per-gate/run bundles before
  teardown, judge expected versus observed state, and record the verdict/paths in
  the owning change and goal plan. An incomplete capture blocks phase advancement.
- This goal authorizes live integration checks inside that isolated capture workflow
  when the user activates it. It does not authorize credential access or fabricated
  measurements. If configured transport is genuinely unavailable, report the
  specific blocker and leave the affected gate incomplete.
- No commit, push, archive, branch-history rewrite, or destructive Git cleanup.
  Do not erase unrelated dirty work. Optional resolver/Jev/media/Titan-runtime work
  does not silently enter the goal.

### Verification References

```bash
.venv/bin/python scripts/test_llm_router.py
.venv/bin/python scripts/benchmark_model_profiles.py --profile production-auto
.venv/bin/python -m unittest -q scripts.test_gpt54_chat_params_contract scripts.test_gpt54_mini_chat_params_shim
.venv/bin/python -m unittest -q scripts.test_multi_pc_combat
.venv/bin/python -m unittest -q scripts.c5_regression_combat
.venv/bin/python -m unittest -q scripts.test_combat_pc_action_parser
.venv/bin/python -m unittest -q scripts.test_combat_phase_integrity_precheck
python3 scripts/check_ascii_compliance.py --summary-only
openspec validate <change-id> --strict
openspec validate --specs
```

Run combat suites in separate processes where the archived baseline documents
cross-suite mock contamination. Adapt source paths after decomposition while
keeping assertions intact. New capability-focused tests and current model fixtures
are authored by their owning changes; historical script filenames are not model
selection authority.

## 5. Completion Criteria For The Eight-Change Goal

1. All eight changes have coherent artifacts, verified task completion, and strict
   validation; evidence is persisted in the overall goal plan.
2. All production chat calls use the facade, including action prediction and mixed
   media prompt-generation chat. Non-chat image/audio behavior stays separate.
3. Narrator/combat/Titan task defaults are independently configurable Auto profiles;
   direct OpenAI/fallback uses configurable `gpt-6-luna`.
4. Task-aware kwargs, bounded retry/timeout behavior, resolved-model accounting,
   `/usage`, and session/week cost completeness are verified.
5. Combat decomposition, comparable latency targets, authoritative commit/receipts,
   and no-duplicate crash/resume behavior pass required tests and party smoke.
6. Live OpenRouter integration and direct-OpenAI rollback pass in isolated captures;
   accepted candidate bake-off is not rerun as a prerequisite.
7. Deprecated plumbing is removed, docs are current, and the final phase is
   `llm-router-cleanup`. No required work is silently deferred to claim completion.
8. Every required live gate has primary-owned PASS evidence for its named scenarios
   and party shapes; G3/G4/G5/G7/G9/G10 captures are not replaced by exit codes,
   degraded required reports, mocks, or builder claims.

## 6. Deferred Work

Image/audio model selection and cutover are a separate follow-on OpenSpec change
using current catalogs, with independently configurable models. No stale roster,
prices, or endpoint assumptions are binding here. Browser TTS remains separate.

`combat-typed-resolver-expansion` is optional. Jev remains gated by its own
evaluation/authorization; the owner-attested chat bake-off does not satisfy its
decision-classifier gate. Titan scheduling/EGO/RATIO and `tt-single-runtime-unification`
are separate initiatives. None blocks the required eight-change chat rollout.
## Forward compatibility: V2 spatial combat

- G7 receipts reserve an optional `position_deltas` slot; see `combat-turn-commit-and-receipts` D6 and its `combat-turn-receipt-model` delta.
- Tactical-brain menu legality filters are the attachment point for future range, reach, line-of-sight, and movement-budget filtering. Once positions exist, prefetch receipt identity and re-plan conditions must include position; add that design note to `combat-tactical-brain` separately.
- `combat-ally-controller` and `combat-absent-pc-autopilot` proposals/designs MUST list movement/position as a known future input and MUST NOT hard-code a positionless model.
- Revisit positionless assumptions: abstract flee/Disengage without positional opportunity attacks; declared-but-unenforced weapon ranges (for example, Javelin 30/120); and G5T scripts, narration validator, and byte-identical goldens that assume positionless fights. Spatial work adds new gates rather than editing existing ones.
- Optional future ADR: Python owns positions and geometry, while the LLM perceives them through actor-scoped projections (an extension of ADR-0007).

None of this blocks current rollout work.
