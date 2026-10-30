# Design

## Context

See `proposal.md` for motivation. The approved layout and phase scope come from `plans/version-2/combat-manager-refactor.md` and `plans/combat-openrouter-alignment.md`. The existing facade is verified complete in `openspec/changes/llm-router-facade/reports/final-verification.md`; combat Tier 1 router migration follows this change.

Current source checks show `core/managers/combat_manager.py` at 5,584 lines, including a 2,594-line `_run_combat_simulation_internal` loop; `core/managers/multi_pc_combat.py` is approximately 2,783 lines. Legacy importers include `main.py`, `core/ai/action_handler.py`, web/debug paths, and tests. `scripts/test_multi_pc_combat.py` imports and patches old module surfaces, and `scripts/c5_regression_combat.py` reads source files and checks source anchors. These are deliberate compatibility constraints, not reasons to retain ownership in the old files.

The archived G1 baseline at `openspec/changes/archive/2026-09-22-combat-latency-baseline/design.md` is complete historical evidence based on `gpt-5.6-luna`. It is not repeated, refreshed, or relabeled by this change. No latency improvement is claimed here.

## Goals / Non-Goals

**Goals:**

- Move combat implementation into `core/combat/` and `core/combat/multi_pc/`, keeping old-path shims and supported import/monkeypatch behavior.
- Make per-session state explicit and extract the nine named responsibility stages so no mega-function remains under a new filename; preserve their current physical call order and call points.
- Preserve prompt bytes, runtime behavior, provider decisions, persistence operations, and regression meaning.
- Finish with `core/managers/combat_manager.py` below 100 lines and every combat-package function at or below 600 lines.
- Supply the bounded missing G3 seed/scenario and evidence-check support through the existing rig, then require primary-owned live acceptance for both party shapes.

**Non-Goals:**

- Router consumer migration, latency optimization or latency target claims, changing provider/retry policy, changing mechanics or commit protocol, or modifying any prompt. Existing observational trace timings may be preserved as evidence without claiming a performance win.
- New runtime modes or party-size gates, Jev decision runtime, dependencies, media, Titan, or a generalized capture framework. Bounded G3 extensions to the existing rig are in scope.
- Running live gameplay captures in this authoring task. The primary orchestrator owns G3 live verification using the existing Capture_Arena skill and isolated port-8360 copy.

## Decisions

### 1. Move ownership first, then extract behavior-preserving seams

Use the approved package layout:

```text
core/combat/
  __init__.py          public API
  session.py           encounter, manager, history, active PC, phase
  turn.py              ordered stage orchestration
  commands.py          deterministic combat command handlers
  decisions.py         PC-action decision seam
  prompts.py           prompt selection and assembly
  validation.py        combat validation and truth-pack integration
  persistence.py       existing apply/persist behavior boundaries
  narration.py         shared deterministic and generated narration
  initiative_tracker_ai.py
  multi_pc/
    __init__.py
    state.py
    turn_queue.py
    manager.py
    sync.py
    dm_note.py
```

`core/managers/combat_manager.py`, `multi_pc_combat.py`, and `combat_state_sync.py` become marked compatibility shims. Move/copy the actual implementation into the package with these shims first; treat this only as an intermediate task boundary. The change is not complete until the session boundary and nine stages are extracted, and the old implementation is not left as a second source of truth.

**Simplest alternative considered:** Keep the implementation in the old manager and split only helpers into a package. Rejected because it preserves the current ownership bottleneck and does not provide stable targets for the subsequent migration.

### 2. Use explicit session payloads and compatibility adapters

The session object is the owner for encounter, multi-PC manager, conversation history, active PC, and phase. Each stage receives explicit inputs and returns an explicit result/payload for its logical handoff; those handoffs do not prescribe physical execution order. History is projected from session state instead of rewriting `conversation_history[2]`, `[3]`, `[4]`, or equivalent fixed positions.

Mutable globals become session-owned state. Existing import and monkeypatch surfaces at old paths remain intentionally supported by narrow adapters/proxies that resolve to the active session or the currently injected test callback. They must not become a second mutable authority. Keep the established manager and callback context-manager test APIs where referenced. Do not use dynamic `exec`, source slicing, or string-generated code to manufacture compatibility.

The nine named stage responsibilities and their logical handoff sequence are:

1. input/phase gate
2. fast commands
3. PC action decision seam
4. context/prompt
5. provider retry
6. validation
7. apply/commit
8. phase transitions
9. narration/output

This logical sequence names responsibility boundaries; it does not prescribe a new physical execution pipeline. The validated legacy path remains authoritative for execution, mutation, persistence, and publication order. Its normal flow is: round metadata/phase preparation and save/compress; print narration and flush; apply immediate encounter actions while queueing character updates; perform post-batch phase and turn-queue bookkeeping; then apply consolidated character updates. The extracted stage owners may have pre- and post-substeps at those existing call points. No stage may move work across those points, change early-return/error outcomes, or introduce a synthetic final-narration shim. `decisions.py` returns distinct `declined` and `unavailable` results, both of which continue to the existing LLM path. It performs no new model or provider operation.

Task 3.5 extracts apply/commit and phase-transition responsibilities at their existing points without reordering mutation or persistence. Task 3.6 owns real narration/output at the legacy publication point and shares template selection with the natural-language parser and multi-PC facade; it does not force narration/output to run as a final physical stage.

### 3. Keep old behavior contracts at narrow owner APIs

Multi-PC `CombatStateManager`, `TurnQueueManager`, `MultiPCCombatManager`, and sync logic retain current data semantics and coordination. Move DM-note and narration helpers behind clear package APIs, with narration template selection shared by the natural-language parser and multi-PC facade. Move `initiative_tracker_ai.py` into combat only after confirming the current reference inventory; keep `status_manager.py` in `core/managers/` because it remains cross-cutting.

Do not edit prompt source. Verification compares static prompt file bytes and dynamically assembled prompt output for equivalent fixtures. Existing source-contract tests move their source anchors to the new owners while preserving assertions and diagnostic text.

### 4. Cleanup is evidence-gated and behavior-neutral

Remove a candidate dead function only after repository-wide reference checks include production importers and test APIs. Keep `set_combat_callback` if an existing callback or context-manager contract uses it. Replace bare exception handling with specific exceptions where possible; unexpected exceptions must be logged with the established stable diagnostic context. Replace `sys.exit` on library paths with a structured result. Convert combat telemetry prints to the enhanced logger without changing anchored `[COMBAT_LOOP]` strings. Cleanup is limited to the named paths; no general formatting or unrelated cleanup.

**Simplest alternative considered:** Leave the hygiene findings untouched for a later slice. Rejected because the approved decomposition explicitly includes these narrow integration hazards (process exit, error observability, dead functions, and duplicate narration selection) and they can be addressed as behavior-preserving seams here.

### 5. G3 is a primary-owned live evidence gate

The owner-approved capture workflow in `plans/combat-openrouter-alignment.md` and
`.opencode/skills/neq-capture-arena/SKILL.md` applies to this change. Before live
execution, tasks 4.3 and 4.4 extend only the existing seeder, driver and fixture/report
helpers with bounded named cases, state snapshots and required-check evidence.
Do not introduce a new runner, production decision/trace subsystem, optional LLM
judge, or generalized scenario DSL. Provider-free tooling tests use fake transports;
they do not substitute for live gameplay. Default latency scripts remain unchanged.

Both party shapes MUST cover `combat-smoke`, `initiative-pc`, `initiative-dm-tie`,
`death-save`, `surrender-exit` (separate surrender and explicit-exit branches), and
`resume-replay`. Wrong-actor death-save coverage is 4-PC-specific and is declared
before execution. Include eligible allied NPC and inactive-enemy filtering in a
bounded smoke fixture variant, distinct from the unchanged default latency fixture.
G3 replay covers already-completed turns under existing guards; interruptions at
the new receipt/commit boundaries belong to G7, not this structural implementation.

The primary runs the matrix after the focused tests/tooling pass. Each run uses a
real `tmp/combat_capture/` copy, port 8360, the repository venv and
`NEQ_OPEN_BROWSER=0`. Restart cases retain the same sandbox state and do not rerun
`--prepare` between stop and resume. Never use port 8357 or the installed campaign.

Before teardown preserve `tmp/router-rollout/g3/<run-id>/` with manifest (scenario/
seed/party/source-worktree/configured transport identity, timestamps and bounds),
verbatim transcript, owned-server log, trace/report, relevant read-only before/after
state snapshots and expected/observed assertion results. Record actual counts,
unknown model/cost data honestly, and no credential/config values. Dynamic prompt
byte-parity tests remain separate evidence; nondeterministic prose is checked for
state/flow consistency rather than literal equality.

For the single 4-PC `surrender-exit` / `surrender` capture, predeclare a
capture-only 300-second turn budget because this accepted-surrender flow performs
four serial prose XP updates and a summary. Keep its one-input, three-control
profile and every existing assertion unchanged. All other cases and defaults
remain at 150 seconds; production factory timeouts/retries, G5 targets and default
latency scripts do not change. This is a bound, not a timeout waiver: retain the
150-second primary-owned FAIL, do not resume its partial fixture, and use a newly
seeded full capture. A required cap/timeout or failed assertion at the declared
300-second bound still cannot PASS.

#### 5.3 Focused named-smoke timeout correction (2026-10-17)

The primary-owned 1-PC `combat-smoke` run
`tmp/router-rollout/g3/20261016T222759.252451Z-combat-smoke-p1-8a01bf24/`
remains **FAIL**. Its third free-text step reached the 150-second driver timeout
while the backend was still processing; the legacy flow then sent the fourth
`/end` input, which also reached its cap. The later third-step output arrived at
about 237 seconds after the legitimate fourth retry. Its trace offsets are
correctly unavailable as `idle_not_observed`; this is not a trace-offset defect.

For named `combat-smoke` and `combat-smoke-allied-inactive` only, across both
party shapes, explicitly allow a capture-only 300-second turn timeout. The
default remains 150 seconds. The named driver stops immediately after the first
step timeout or active-stream cap, including start timeout; it sends no later
gameplay input or active-PC switch, and returns nonzero while preserving the
partial evidence bundle through the existing `finally` path. Keep every script
input/order, 5/7 or 22/35 bound, and check unchanged. The existing 4-PC
`surrender-exit`/`surrender` 300-second allowance remains. No other named case,
bare legacy latency run, product behavior, production factory retry/timeout,
G5 threshold, or G3 acceptance criterion changes. A timeout/cap at 300 seconds
remains a failure; the old bundle is not resumed or rewritten.

Only the primary records final PASS/FAIL/BLOCKED and evidence references in task
5.3 and the overall goal plan. The legacy driver can exit 0 despite timeout warnings
and the report can exit 0 with degraded data. Neither proves acceptance: missing
required scenarios/checks/artifacts, required step caps/timeouts or failed assertions
keep G3 incomplete. Missing tooling/transport is BLOCKED; attributable failures get
focused builder fixes and reruns. A paused goal stays paused during guideline edits.

**Simplest alternative considered:** Treat the current default driver plus unit
tests as complete G3 evidence. Rejected because it does not explicitly exercise
both initiative outcomes, death saves, surrender/exit or restart replay, and does
not judge required gameplay assertions. The scoped extensions close those named
gaps without approving the broader tiers in `plans/capture-arena.md`.

### 6. Validation context separates committed state from candidate proposals

The primary-owned allied/inactive 1-PC evidence at
`tmp/router-rollout/g3/20261016T111137.037824Z-combat-smoke-allied-inactive-p1-0bebfaf6/`
shows that the validator treated candidate `touchedChanges` proposing Acheron HP
20->12 as already committed while the truth pack still reported HP 20. This
establishes the context-authority defect, but does not establish that the candidate
was otherwise valid; in particular, the report does not prove the initial
two-Goblin-attacks candidate valid. The observed failed bundle remains FAIL and is
not rewritten.

The validation context and only the strictly necessary explanatory validation
instructions may be corrected so that (a) the committed Python state snapshot is
the authority for current mechanics, (b) proposed candidate changes/operations
are separately labelled as uncommitted, and (c) neither candidate text nor its
`ALREADY_APPLIED` assertion or candidate-derived `touchedChanges` can establish
that an operation was applied. Genuine prior applied events, when independently
established by authoritative prior-state/evidence, remain trusted. No candidate-
derived `touchedChanges` may be inserted into the authoritative truth pack.

This is the sole narrow exception to extraction dynamic-validation-context byte
parity. Static prompt assets, all unrelated dynamic prompt/context bytes, and all
extraction parity outside this named correction remain byte-identical. Frozen
baseline goldens/history are not wholesale rewritten. Schema, public returns,
mechanics, physical execution/mutation/persistence/publication order, retries,
provider-call behavior, and fail-open policies remain unchanged. G7 commit,
receipt, and replay-boundary work is not implemented by this correction.

Before final gates, guarded tests must compare before/after payloads and establish
that a proposed HP 20->12 change is not already applied; retain the
`HP20proposed-8` distinction, the `actualcommitted12`/`replaystillblocked` cases,
PC/ally/both-party/ops-only/inventory/no-mutation cases, and an actual validation
call payload with fake fatal SDK/network/outside-write tripwires. They must also
prove unchanged unrelated prompt bytes. Keep all 18 G3 strict-reject checks
unaffected; failed bundles stay FAIL and affected live cases require primary-owned
reruns. The initial failed two-Goblin-attacks candidate remains unproven otherwise.

**Simplest alternative considered:** Treat candidate-provided `touchedChanges` or
`ALREADY_APPLIED` claims as evidence of application. Rejected because the cited
primary diagnostic shows a candidate proposal being confused with the unchanged
authoritative HP 20 snapshot. Rewriting all prompt bytes or frozen baseline
history is also rejected; the approved exception is limited to the dynamic
validation context and its necessary explanatory instructions.

### 7. Validation receives bounded canonical non-PC combat facts

The latest primary-owned allied/inactive 1-PC review at
`tmp/router-rollout/g3/20261016T172935.595209Z-combat-smoke-allied-inactive-p1-38096c35/primary-review.json`
is a distinct **FAIL** from the Task 4.5 candidate/committed-state defect. It
reports that validation rejected source-backed Blairen +3 and Goblin +4 attack
bonuses and damage modifiers as absent from its authoritative context; the
actual validation request contained preroll names/values but no canonical
attack/stat facts. Task 4.5 remains checked and unchanged. The review does not
establish an accepted allied/enemy cohort and does not waive any G3 check.

Task 4.6 may add a bounded, transient, read-only source-facts section to the
actual dynamic validation request. Resolve only non-PC identities already
present in the encounter/eligible roster against the exact canonical data
sources already used for generation. Prefer an already-loaded NPC template or
monster map only when identity and source match the current generation inputs;
otherwise use the existing NPC character-state/template loader or existing
`ModulePathManager` plus `safe_json_load` monster path, reading the same module
source generation used. Do not create a resolver, context framework, actor
classifier, or new NLP/LLM service. Keep the facts bounded to source-backed
identity and attack/stat fields relevant to validation (for example attack
bonus, attacks and spellcasting entries, damage dice/type, and the source
identity/provenance). Preserve field-level unknown/missing/stale/malformed
status explicitly; do not compute or substitute defaults, inferred bonuses,
candidate assertions, or pre-roll values as canonical facts.

The source-facts section is distinct from the committed Python state truth pack
and from uncommitted candidate text/operations. Candidate and preroll text may
identify a topic to check but are never authoritative. Facts are assembled for
validation only: no mutation, persistence, or generation-context change is
allowed. Keep legacy validation callback arguments and patch behavior unchanged,
all generation prompt bytes byte-identical, the completed 4.5 boundary,
physical execution/mutation/persistence/publication order, retries, provider
policy, fail-open error handling, G7 boundaries, and the strict 18-key live
criteria unchanged. Failed evidence remains FAIL and only the primary may
rerun affected live cases.

Guarded tests for 4.6 must feed actual canonical source data through the actual
fake validation payload path and cover 1-PC/4-PC rosters, ally/enemy identity,
unknown/missing/stale/malformed facts without invented values, candidate and
preroll non-authority, deep no-mutation, legacy callbacks, byte-for-byte
generation prompt parity and frozen assets. They must preserve the 4.5
candidate-vs-committed and genuine-replay checks. Only after those gates may the
primary rerun the affected allied/inactive live case; no G3 PASS is implied by
the software tests or a single rerun.

### 8. Link causal evidence before reconciling mechanical application

The primary-owned 1-PC/4-PC allied-inactive review at
`tmp/router-rollout/g3/20261016T180820.039042Z-combat-smoke-allied-inactive-p4-fe3b7936/primary-review.json`
is **FAIL**. Its checker found that the expected encounter `hp_delta` of -4
was compared with the aggregate observed Goblin Alpha delta of -16, although six
successful deterministic damage operations of 2 each explain -12. The primary
explicitly requires causal-span linkage to avoid double counting; the successful
apply evidence and other validation failures remain independent FAIL evidence.
The earlier `175906` review remains **BLOCKED** because evidence generation
crashed before complete checks/report artifacts; it is not reconstructed as a
PASS. Both primary-owned bundles/reviews remain unchanged.

Task 4.7 may extend only the existing driver/parser/checker. Record per-step
`runtimeTrace` byte offsets immediately BEFORE input and AFTER idle, and record
the run-start trace offset. Parse actual JSONL observations with their source
byte positions. Link step snapshots to observations using source positions and
explicit event/step references, never target or delta as event identity. The
ledger reconciles proven PC deterministic damage and successful structured
apply operations exactly once: mismatches are FAIL; missing positions, overlap,
or ambiguity are BLOCKED. Input alone and final aggregate deltas alone are not
proof, and no event can be counted twice. Failed apply and failed final
validation remain failures. Default latency inputs/order are unchanged; there
is no runtime gameplay behavior or new runner.

### 9. Explain inventory container authority; keep rejection diagnosis opt-in

Task 4.8 documents the existing mechanical rule in
`updates/update_character_info.py`: `inventory_remove` defaults to equipment
unless `container="ammunition"` or `item_type="ammunition"` is explicit.
Equipment and ammunition remain separate canonical containers. A candidate
proper name alone does not make an operation applicable. Do not duplicate
ammunition into equipment, redirect operations, or add resource mechanics.
Preserve actual precheck rules until exact rejected changes and structured
operations can be retained.

The only new diagnostic is an opt-in, bounded capture of actual rejected
changes, structured operations, and reason, and only when the existing trace
gate is enabled. Trace-off adds no extra I/O; do not retain full prompts,
configuration keys, unbounded payloads, provider data, or add I/O when disabled.
The goal-prose mirror guard failure is currently unproven as an
attacker-victim false positive, and the latest body is missing; do not claim the
diagnostic proves that cause or change the heuristic routing policy. Tests must
use the actual fake validation payload, preserve its contract and committed
container, distinguish the correct ammunition operation from the existing
wrong-default mechanical behavior, and verify bounded trace-on data and no
trace-off I/O.

Neither task changes the existing 18 live strict-rejection checks, any live
verdict, or primary ownership of 5.3. These are evidence/diagnostic corrections,
not new game behavior or acceptance waivers.

### 10. Correct only proven validation-context authority conflicts

The primary-owned 1-PC review at
`tmp/router-rollout/g3/20261016T225308.339122Z-combat-smoke-allied-inactive-p1-efaad448/primary-review.json`
remains **FAIL**. Its report records two `updateEncounter` rejections for
`Goblin takes 7 damage, HP 18->11. Blairen hits Goblin. Goblin misses Acheron.`
and `Goblin takes 7 damage, HP 18->11. Goblin's scimitar attack against
Acheron misses.` The current `_changes_text_targets_non_enemy` checks for a
non-enemy name anywhere plus any explicit mutation pattern anywhere, so the
attack recipient is mistaken for the mutation recipient. This evidence proves
the specific false-positive path, not that either candidate is valid. The
review also records a prospective handoff conflict: pre-response `ENEMY_PHASE`
and pending actors cause Guard 2 to reject a PC prompt even when a full enemy
batch candidate would hand off after that batch. The captured operations in
the rejection diagnostic were normalized to `"[truncated]"` by the real trace
writer; no operation details may be inferred from that diagnostic.

Task 4.9 may correct only these three validation-context authority issues:

- Classify prose mutations by canonical target/recipient and their local
  clause, not by unrelated names or mutation phrases elsewhere in the text.
  Retain rejection of proven PC/allied HP, condition, and resource mutations,
  including a genuine PC HP mutation whose value/change is continued across
  sentences. Canonical identity comes from authoritative encounter/actor
  context, never a candidate-created name/identity. Unknown or ambiguous prose
  is not grounds for an early rejection; it continues to the existing full
  semantic validation. Do not add general actor NLP, a resolver, or a service.
  All structured operation target checks remain strict and unchanged.
- Guard 2 may defer its current mid-batch PC-prompt rejection only for a
  complete NPC-batch response at the existing exact, code-owned `Enemies turn.`
  user-input seam, with canonical eligible-actor coverage and existing
  permissible round/handoff conditions. The classifier must not trust a
  candidate-supplied completion flag. Deferral only reaches the existing
  mandatory full semantic validator: it cannot return overall-valid, accept or
  apply a batch, or advance phase/round from candidate claims. The semantic
  validator must still reject omitted/skipped actors, invalid round changes,
  premature PC actions, and other invalid completion/handoff claims. Legacy,
  partial, missing-actor and ambiguous mid-batch prompts remain hard rejects.
  Guard 1 (including genuine forbidden-PC action), Guard 3 exit/replay, Guard 4
  round increment and other phase prechecks remain strict. Keep the existing
  validation callback shape and avoid a new framework or public callback.
- Flatten only the bounded diagnostic representation of actual structured
  operations so the real trace writer preserves action index and top-level
  scalar field/value evidence (including operation, creature/target and delta)
  within the existing depth/byte bounds. Keep bounded actual changes, reason,
  counts and truncation flags. Trace-off must perform no extra I/O. This is
  diagnostic-only and does not make old truncated operations retrospectively
  known.

The focused tests must prove the false-positive examples proceed to actual full
validation, while genuine PC/allied mutation (including cross-sentence HP),
all structured non-enemy targets, legacy/mid-batch partial cases, and strict
phase/exit/replay paths remain rejected. An eligible full NPC batch must reach
the actual fake semantic provider call; a false semantic response must still be
rejected. Tests must prove missing/skipped actors, invalid rounds, and premature
PC actions remain rejected even when candidate prose claims completion. The
real-writer regression must prove exact operation/creature/delta survive,
actual changes/reason/truncation metadata remain bounded, trace-off performs no
I/O, and character JSON bytes are unchanged. No mechanics, schema, operation
resolver, retries, fail-open policy, generation bytes, source-backed
300-second capture budget, default 150-second budget, or live acceptance
criteria change. All 18 strict-rejection keys and the `225308` FAIL remain
retained; Tasks 5.3 and 5.4 remain unchecked pending primary review/rerun.

### 11. Capture bounded HP-ledger evidence without inferring missing operations

The primary-owned `233336` review remains **BLOCKED** solely because a successful
`update_encounter` apply has `ops: null` and a depth-truncated returned state.
Correct the prior hypothesis in this report while retaining its initial review
and trace history: this is not a Blairen prose-HP event. The bundle remains
unchanged, and the missing-operation blocker cannot be waived. Guard 4.9's NPC
acceptance correction remains intact. The reviewed state includes Acheron 20 to
13 from structured `hp_delta: -7` with its character/encounter mirror, Goblin 20
to 18 from the PC deterministic `-2`, and Blairen unchanged at 12.

Task 4.10 may extend only the existing opt-in `combat_apply_result` observation
on the `process_combat_action_batch` `updateEncounter` branch. Reuse the caller's
already-loaded `encounter_data` as pre-call context, copy only the bounded,
read-only HP maps before invoking the existing updater, and capture the
canonical `updated_encounter_data` returned by that same call as returned
persisted state. Keep the capture inside the existing observation; add no
resolver, cache, framework, or provider call. With tracing off, add no
payload-construction trace, I/O, or helper calls; the existing trace-on
observation may carry the bounded HP metadata. Preserve updater
arguments/returns, schema, mutation, persistence and publication order,
mechanics, and client policy. Metadata must
label preloaded context separately from returned persisted state and must not
claim either was candidate-generated.

The trace representation is flat, compact, and bounded by the real writer's
depth/byte limits. It records `hp_before`, `hp_after`, status, counts,
truncation, and provenance. Missing, invalid, duplicate, or depth/byte-truncated
actor identities are explicitly incomplete and are never defaulted or
reconstructed. A checker may clear an ops-absent block only when the positioned,
unique encounter operation has a complete projection that proves zero HP delta
and is consistent with the canonical pre-step state and all prior causally
proved writes; there may be no other ambiguous same-store writes. Prefer
conservative restriction over sequence inference. Non-zero-HP prose without
structured expected ops, incomplete or mismatched projections, unknown targets,
or duplicate ambiguity remain BLOCKED. Failed apply remains FAIL and unexplained
overall mutation remains FAIL. Never derive expected HP from observed state or
parsed prose mechanics. Preserve HP mirror accounting and all 18 strict checks.

Provider-free proof must use a real persistence callback (with a real function
fake updater), the real trace writer, and the actual parser/`observed_checks`.
Cover a zero-HP metadata update and structured character HP changes for distinct
actors, including mirror and PC deterministic damage; also cover non-zero,
absent, invalid, duplicate, provenance-mismatched, and failed-apply evidence.
Prove before-call evidence survives an updater that mutates its input. With
tracing off, prove zero extra I/O/helper calls, deep no-mutation, and unchanged
public callback order and generated bytes. Fatal SDK/network/BaseException
tripwires must be armed before imports and before any writes. Keep all generated
paths project-relative under `tmp/`.

This is an unchecked planning amendment only. Keep Tasks 5.3 and 5.4 unchecked,
retain the corrected initial hypothesis and raw `233336` BLOCKED bundle, and
require fresh affected primary-owned live evidence after software tests. Do not
rewrite the raw bundle or alter checked 4.5-4.9 status, 5.3/5.4 status, the 300-
second named capture exceptions, bare 150-second bound, G5, or any G3 verdict.
The telemetry gate remains `OPENSPEC_TELEMETRY=0 DO_NOT_TRACK=1`; additions and
scoped diff review are ASCII-only and stop at the exact Task 4.10 text boundary.

## Risks / Trade-offs

- **[Risk]** A physical move can break existing monkeypatches even when imported symbol names still resolve. -> **Mitigation:** Preserve deliberate old-path patch targets and verify current context-manager and monkeypatch tests in the same task that establishes each shim/owner API.
- **[Risk]** Moving code in bulk may preserve the monolith under a new name. -> **Mitigation:** Package relocation is explicitly intermediate; session ownership and each named stage are separate required tasks, and final verification measures function sizes and locates stage owners.
- **[Risk]** Static source assertions can be weakened accidentally during anchor migration. -> **Mitigation:** Repoint only file/symbol anchors, retain assertion semantics and expected stable strings, then run the existing suites in isolated processes.
- **[Risk]** Dynamic prompt serialization may drift despite unchanged prompt files. -> **Mitigation:** Compare prompt outputs under equivalent deterministic input fixtures byte-for-byte.

## Migration Plan

1. Establish package modules and compatibility shims while moving implementation ownership, including the multi-PC and sync files and the verified combat-only initiative helper.
2. Extract explicit session state and replace module-global state and fixed history-index rewrites with session-derived payloads.
3. Extract the nine named responsibility stages without imposing their logical handoff sequence as physical call order; preserve the validated legacy call points and execution/mutation/persistence/publication sequence, repointing related source contracts alongside each owner move.
4. Apply only verified cleanup and implement the bounded G3 rig prerequisites; run focused combat/tooling suites as separate processes, source/prompt parity checks, compile/ASCII checks, and strict OpenSpec validation.
5. When the goal is active, the primary runs and judges every required G3 scenario/party capture through the existing skill, preserves each run bundle before teardown, and records expected/observed checks and PASS/FAIL/BLOCKED. Incomplete capture coverage prevents handoff to core migration.

Rollback is by reverting the decomposition change's implementation commits as a unit; there is no data migration, new persisted schema, prompt change, or provider activation to reverse. Do not archive or commit as part of this change's delegated artifact work.

## Open Questions

None. The package boundary, stage order, behavior-parity gate, and primary-owned live verification path are settled by the approved plan.
