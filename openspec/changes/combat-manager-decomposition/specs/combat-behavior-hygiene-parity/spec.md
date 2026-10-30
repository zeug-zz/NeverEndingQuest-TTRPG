# Spec Delta

## Purpose

Defines the behavior-preservation and hygiene boundary for moving combat logic into the package without changing the gameplay contract or the prompts supplied to models.

## ADDED Requirements

### Requirement: Combat prompt bytes remain identical

The decomposition SHALL preserve byte-for-byte equality of static combat prompt files and dynamically assembled combat prompt text for equivalent runtime inputs.

#### Scenario: Static prompt content is compared before and after the move
- **WHEN** the combat prompt assets are compared with their pre-decomposition versions
- **THEN** every combat prompt file SHALL be byte-identical

#### Scenario: Dynamic prompt output is built for equivalent state
- **WHEN** equivalent encounter, party, phase, active-PC, and history inputs are passed through the prompt assembly path
- **THEN** the resulting prompt messages and serialized text SHALL be byte-identical, including ordering and whitespace

### Requirement: Decomposition preserves combat runtime behavior

The package move and stage extraction SHALL preserve current mechanics, turn/phase transitions, action processing, persistence behavior, provider-call decisions, and emitted player-facing output for equivalent inputs.

#### Scenario: Initiative, death saves, roster, and enemy batch flow execute
- **WHEN** the existing initiative gates, death-save flow, party roster, or enemy batch path is exercised
- **THEN** the same state transitions, accepted actors, encounter mutations, and output SHALL result

#### Scenario: Provider and persistence operation budgets remain unchanged
- **WHEN** the same combat input is run before and after decomposition
- **THEN** the decomposition SHALL NOT add provider calls or runtime file writes
- **AND** existing call and write behavior SHALL remain within its prior policy

#### Scenario: Narration template selection has one shared behavior
- **WHEN** deterministic narration is requested by the multi-PC facade or natural-language action parser
- **THEN** both paths SHALL select and render the same template under equivalent inputs

### Requirement: Validation context distinguishes committed Python state from candidate proposals

The validation context SHALL label committed Python state separately from candidate proposals. Candidate claims, including `ALREADY_APPLIED` and derived `touchedChanges`, SHALL NOT establish application or enter the truth pack. Independently established prior applied events remain trusted. Changes are limited to this context and necessary explanatory instructions; unrelated prompt/context bytes and all other extraction parity remain identical.

#### Scenario: Proposed operation is not reported as committed
- **WHEN** a candidate proposes Acheron HP 20->12 while the authoritative Python snapshot remains HP 20
- **THEN** the validation context SHALL identify the proposal as uncommitted and retain HP 20 as current committed state
- **AND** candidate `touchedChanges` or an `ALREADY_APPLIED` claim SHALL NOT alter the authoritative truth pack
- **AND** the `HP20proposed-8` case SHALL remain distinct from `actualcommitted12`

#### Scenario: Genuine prior application remains authoritative
- **WHEN** an operation's prior application is independently established by authoritative state/evidence
- **THEN** the validation context SHALL retain that genuine prior applied event
- **AND** candidate claims alone SHALL NOT establish it

#### Scenario: Guarded payload coverage preserves boundaries
- **WHEN** focused before/after payload tests and the actual validation-call-payload test run
- **THEN** they SHALL cover `actualcommitted12` and `replaystillblocked`, PC/ally/both-party/ops-only/inventory/no-mutation cases, and unchanged unrelated prompt bytes
- **AND** fatal SDK, network, and outside-write tripwires SHALL remain armed
- **AND** the initial failed two-Goblin-attacks candidate SHALL remain unproven otherwise
- **AND** all 18 G3 required strict-reject checks and failed-bundle FAIL verdicts SHALL remain unaffected

### Requirement: Validation context includes bounded canonical non-PC combat facts

The dynamic validation request SHALL include bounded, read-only canonical attack/stat facts for relevant non-PC actors when available from generation sources. Facts SHALL identify the actor and source, remain separate from committed state and candidate proposals, and SHALL NOT derive from candidate/preroll text. Reuse existing caches/loaders; add no resolver/context framework or actor NLP/LLM service.

#### Scenario: Canonical actor facts reach the validation payload
- **WHEN** a 1-PC or 4-PC actual fake validation call includes a non-PC ally or enemy with canonical source data
- **THEN** the payload SHALL contain only bounded facts from the identity-matched generation source, including provenance
- **AND** source-backed attack bonuses and damage modifiers SHALL be distinguishable from pre-roll values
- **AND** candidate/preroll text SHALL NOT override or create canonical facts

### Requirement: Missing non-PC source facts remain unknown

Unavailable or invalid canonical facts SHALL remain explicitly unknown. The validation context SHALL NOT invent defaults, infer modifiers, mutate source/actor/candidate data, or persist context.

#### Scenario: Unavailable or invalid facts remain unknown
- **WHEN** canonical facts are missing, unknown, stale, malformed, or cannot be identity-matched
- **THEN** the validation context SHALL represent those facts as unknown and SHALL NOT invent defaults, infer modifiers, or substitute candidate/preroll values
- **AND** reading or formatting facts SHALL NOT mutate actor, encounter, source-map, or candidate data, nor persist validation context

### Requirement: Validation source handoff preserves compatibility boundaries

Canonical validation facts SHALL be assembled only for the validation request. Legacy callback/patch behavior and generation prompt bytes SHALL remain unchanged.

#### Scenario: Compatibility and byte boundaries remain intact
- **WHEN** guarded validation-context tests exercise both party sizes, ally/enemy identities, and existing legacy callback/patch surfaces
- **THEN** actual source data SHALL flow through the actual fake validation payload path
- **AND** all generation prompt bytes and frozen assets SHALL remain byte-identical
- **AND** Task 4.5 proposed-versus-committed and replay behavior SHALL remain unchanged
- **AND** retries, fail-open behavior, persistence/publication/G7 boundaries, and all 18 strict live rejection keys SHALL remain unchanged
- **AND** the primary-owned `172935` G3 failure SHALL remain FAIL until affected live rerun evidence is reviewed; no single-case PASS SHALL imply G3 PASS

### Requirement: Capture evidence is causally linked to per-step observations

The existing Capture_Arena rig SHALL preserve source-positioned trace evidence
and reconcile it only through uniquely linked events. Input text, target/delta
values, and aggregate final deltas alone SHALL NOT identify or prove an applied
event. Failed apply/final validation remain failures; mismatch is FAIL, while
missing/overlapping/ambiguous evidence is BLOCKED. Default latency inputs/order
and gameplay remain unchanged; no new runner is introduced.

#### Scenario: Per-step events reconcile once against state evidence

- **WHEN** actual JSONL events, source byte positions, step boundaries, snapshots,
  and structured operations are available for a run
- **THEN** each mechanically proven event SHALL be linked to one source span and
  one step reference and counted exactly once
- **AND** a causal mismatch SHALL fail, while missing/overlapping/ambiguous
  evidence SHALL block reconciliation
- **AND** neither input text nor target/delta matching nor aggregate final delta
  SHALL establish event identity or successful application

#### Scenario: Driver captures source positions at the required boundaries

- **WHEN** the existing driver starts a run and executes a scripted step
- **THEN** it SHALL record the run-start offset and that step's
  `runtimeTrace` byte offsets immediately BEFORE input and AFTER idle
- **AND** parsed actual JSONL observations SHALL retain their source byte
  positions and snapshots SHALL link by event/step references

#### Scenario: Existing failed evidence remains unchanged

- **WHEN** the latest primary review and prior incomplete evidence are recorded
- **THEN** `180820` SHALL remain FAIL and `175906` SHALL remain BLOCKED
- **AND** neither bundle SHALL be reconstructed, rewritten, or upgraded to PASS

### Requirement: Inventory container explanation preserves existing authority

The documentation and guarded evidence SHALL explain that `inventory_remove`
defaults to equipment unless `container="ammunition"` or
`item_type="ammunition"` is supplied. Equipment and ammunition SHALL remain
separate canonical containers; a candidate proper name alone SHALL NOT make an
operation applicable. No duplication, redirection, or new resource mechanics
are allowed. Existing precheck behavior remains authoritative until exact
rejected changes and structured operations are retained.

#### Scenario: Correct and wrong-default ammunition operations retain mechanics

- **WHEN** the actual fake validation payload includes the committed container
  and an ammunition removal operation
- **THEN** tests SHALL distinguish the explicit ammunition operation from an
  operation that omits the ammunition container/type
- **AND** the existing runtime default and its mechanical result SHALL remain
  unchanged; prose/name matching alone SHALL NOT redirect the operation

### Requirement: Rejected enemy-routing diagnostics are opt-in and bounded

The existing enemy-routing precheck and heuristic policy SHALL NOT change.
With the existing trace gate enabled, diagnostics MAY retain only bounded actual
rejected changes, structured operations, and reason; when disabled, capture
SHALL add no I/O. Full prompts, configuration keys, unbounded payloads, provider
data, and disabled-gate I/O SHALL NOT be captured. The alleged goal-prose mirror
false positive is unproven and SHALL NOT be stated as fact.

#### Scenario: Trace gate controls the rejection diagnostic

- **WHEN** a rejection occurs with trace disabled or enabled
- **THEN** disabled tracing SHALL add no extra I/O
- **AND** enabled tracing SHALL preserve bounded actual changes/operations and
  reason only, with the existing rejection outcome unchanged
- **AND** tests SHALL assert the exact captured changes match the actual fake
  validation payload and SHALL NOT claim an unproven prose-mirror cause

### Requirement: Prose mutation routing uses canonical recipients and local clauses

The enemy-routing prose precheck SHALL reject only proven PC/allied mutations
linked to canonical recipients and local clauses. Ambiguous prose SHALL continue
to full semantic validation; structured non-enemy operation checks remain strict.

#### Scenario: Enemy changes plus PC as attack recipient are not PC mutations

- **WHEN** `updateEncounter` changes say `Goblin takes 7 damage, HP 18->11` and
  separately narrate `Blairen hits Goblin` or `Goblin's scimitar attack against
  Acheron misses`
- **THEN** Acheron SHALL NOT be classified as the recipient of the Goblin HP
  mutation solely because Acheron appears as an attack recipient
- **AND** the candidate SHALL continue through the existing full semantic
  validation; the precheck SHALL NOT accept it
- **AND** classification SHALL use canonical encounter/actor identities, not
  candidate-created identities, and SHALL NOT add general actor NLP, a resolver,
  or a service

#### Scenario: Genuine non-enemy prose mutations remain rejected

- **WHEN** prose explicitly mutates canonical PC/allied HP, conditions, or
  resources, including a PC HP change whose recipient/value relation continues
  across sentences
- **THEN** the enemy-routing precheck SHALL reject the proven non-enemy
  mutation
- **AND** structured operations targeting any non-enemy SHALL remain rejected
- **AND** unknown or ambiguous prose SHALL proceed to full semantic validation
- **AND** canonical recipient identity SHALL come from authoritative
  encounter/actor context, not candidate claims

### Requirement: HP-ledger evidence is bounded and does not waive missing operations

The existing opt-in encounter-apply observation MAY capture bounded,
read-only HP evidence and SHALL label pre-call context separately from the
canonical returned persisted state. Evidence and checker decisions SHALL be
fail-closed: incomplete or ambiguous proof cannot establish zero HP effect.
Capture SHALL preserve existing runtime, persistence, and callback contracts.

#### Scenario: Complete zero-HP metadata projection can resolve only its own block

- **WHEN** a positioned, unique encounter operation has a complete projection
  that proves zero HP delta and agrees with canonical pre-step state and prior
  causally proved writes, with no ambiguous same-store writes
- **THEN** the ops-absent block MAY be cleared for that operation only
- **AND** the returned-state source is labelled as returned persisted state and
  the pre-call source as preloaded context
- **AND** observed state or prose intent alone SHALL NOT prove the operation

#### Scenario: Incomplete or contradictory HP evidence stays fail-closed

- **WHEN** HP prose has no structured expected ops, an operation projection is
  missing/mismatched, its target is unknown, actor identity is missing/invalid/
  duplicate/truncated, or same-store writes are ambiguous
- **THEN** the operation SHALL remain BLOCKED unless a proven mismatch or
  unexplained overall mutation requires FAIL
- **AND** a failed apply SHALL remain FAIL
- **AND** expected HP SHALL NOT be inferred from observed deltas or prose
- **AND** character/encounter mirror accounting and all 18 strict checks SHALL
  remain in force
- **AND** the capture SHALL add no provider call, resolver, cache, or framework
- **AND** when tracing is off, capture SHALL add no payload-construction trace,
  I/O, or helper calls; the existing trace-on observation MAY carry bounded HP
  metadata
- **AND** updater arguments/returns, schema, mutation-persistence-publication
  order, mechanics, and client policy SHALL remain unchanged

#### Scenario: Provider-free callback-to-checker evidence uses the real writer

- **WHEN** focused provider-free checks run through a real persistence callback,
  real function fake updater, real trace writer, and actual parser/
  `observed_checks`
- **THEN** they SHALL prove a zero-HP metadata update and structured character
  HP differences for separate actors, including a character/encounter mirror
  and PC deterministic damage
- **AND** they SHALL cover non-zero, absent, invalid, duplicate,
  provenance-mismatched, and failed-apply evidence
- **AND** evidence captured before the updater SHALL survive updater mutation of
  its input
- **AND** flat evidence SHALL include `hp_before`, `hp_after`, status, counts,
  truncation, and provenance within real-writer depth/byte bounds
- **AND** missing, invalid, duplicate, or truncated actor identities SHALL be
  explicitly incomplete and never defaulted or reconstructed
- **AND** trace-off SHALL prove zero extra I/O/helper calls, deep no-mutation,
  unchanged public callback order, and unchanged generated bytes
- **AND** fatal SDK, network, and `BaseException` tripwires SHALL be armed before
  imports and before writes, and generated paths SHALL remain project-relative
  under `tmp/`
- **AND** telemetry SHALL use `OPENSPEC_TELEMETRY=0 DO_NOT_TRACK=1`; scoped
  additions/diff boundaries SHALL be ASCII-only

### Requirement: Complete enemy-batch handoff defers only to full validation

Guard 2 SHALL defer a mid-batch PC prompt only for a code-identified complete
NPC batch with canonical actor coverage and permissible round/handoff shape.
Deferral reaches mandatory full semantic validation; candidate claims never
accept/apply or advance phase/round. Other phase, exit, replay, and forbidden-PC
action checks remain strict.

#### Scenario: Code-identified complete NPC batch reaches full semantic validation

- **WHEN** code-owned `Enemies turn.` input and canonical pending-actor coverage
  identify a complete proposed NPC batch with permissible round/handoff shape
- **THEN** Guard 2 SHALL defer its mid-batch prompt rejection only far enough to
  invoke the existing full semantic validator
- **AND** the actual fake validator's false feedback SHALL still reject the
  candidate
- **AND** candidate claims alone SHALL NOT mark it valid, accept/apply it, or
  advance phase/round
- **AND** no candidate-supplied completion flag or claim SHALL qualify the
  response; the existing `Enemies turn.` seam, callback shape, mechanics,
  ordering, retries, and fail-open policy remain unchanged

#### Scenario: Partial or invalid batch and other phase violations stay strict

- **WHEN** a legacy/partial/missing-actor batch prompts for a PC, or a candidate
  has skipped actors, invalid round advancement, premature PC action, forbidden
  PC action, illegal exit, or replay violation
- **THEN** the existing applicable hard rejection/semantic failure SHALL remain
  effective even if candidate prose claims the batch completed
- **AND** no callback shape or public API SHALL change
- **AND** callback shape, mechanics, ordering, retries, and fail-open policy
  SHALL remain unchanged

### Requirement: Trace diagnostics preserve bounded flat operation evidence

When the existing trace gate is enabled for an enemy-routing rejection, the
diagnostic SHALL retain bounded actual changes, reason, counts/truncation flags,
and flattened actual structured-operation fields, including action index and
operation/creature-or-target/delta values, within existing depth and byte bounds.
It SHALL NOT infer unavailable operation data or add trace-off I/O.

#### Scenario: Real trace writer preserves operation identity without state writes

- **WHEN** the actual validation rejection diagnostic is sent through the real
  trace writer with a structured operation
- **THEN** the bounded diagnostic SHALL preserve the exact operation, creature
  or target, delta, and action index, alongside actual changes/reason and
  truncation metadata
- **AND** trace-off SHALL add no I/O and the character JSON bytes SHALL remain
  unchanged
- **AND** previously captured `[truncated]` nested operations SHALL remain
  unknown and SHALL NOT be reconstructed

#### Scenario: Existing live gates remain in force

- **WHEN** Tasks 4.7 and 4.8 are verified in software
- **THEN** all 18 G3 strict-rejection checks and their criteria SHALL remain
  unchanged
- **AND** Tasks 5.3 and 5.4 SHALL remain unchecked until their existing gates
  are independently satisfied

### Requirement: Cleanup preserves supported diagnostics and library control flow

Combat cleanup SHALL retain stable diagnostic strings used by regression contracts and SHALL return structured control outcomes rather than terminating the hosting process from a combat library path.

#### Scenario: Combat diagnostic anchor remains stable
- **WHEN** a regression assertion observes an existing `[COMBAT_LOOP]` diagnostic
- **THEN** the diagnostic text SHALL remain stable unless the assertion is deliberately migrated without weakening its semantic check

#### Scenario: Combat library requests session termination
- **WHEN** the combat runtime reaches an existing terminal exit path
- **THEN** it SHALL return a structured result to its caller
- **AND** it SHALL NOT terminate the hosting process with `sys.exit`

#### Scenario: Candidate dead function is considered for removal
- **WHEN** cleanup evaluates a function identified as dead code
- **THEN** removal SHALL occur only after repository reference checks confirm no supported caller or test API depends on it

### Requirement: Bounded Capture Arena tooling covers the G3 matrix

The change SHALL extend the existing Capture_Arena seeder, socket driver and
fixture/report helpers with bounded named G3 scenarios and required evidence
checks, without changing product mechanics/provider policy or default latency
scripts. Tooling tests SHALL be provider-free and SHALL cover failures as well as
successful observations. A new parallel runner or generalized capture framework
SHALL NOT be required.

#### Scenario: Initiative and combat smoke cases are declared
- **WHEN** G3 capture tooling is prepared for 1-PC and 4-PC parties
- **THEN** named cases SHALL cover deterministic attack/damage, unique complete PC roster, active-PC identity, eligible living non-PC batches and phase/round-start markers
- **AND** invalid initiative input SHALL hold the gate, a known PC-group win SHALL enter PC_PHASE without an opening batch, and a known DM-group tie SHALL set then clear the opening marker after the eligible opening batch
- **AND** a bounded variant SHALL exercise allied-NPC participation and inactive-enemy exclusion without altering the default latency fixture

#### Scenario: Death saves and exit paths are exercised
- **WHEN** the death-save and separate surrender/explicit-exit cases run for both party shapes
- **THEN** invalid death-save rolls SHALL be rejected and a valid roll SHALL update only the seeded pending PC
- **AND** wrong-actor death-save input SHALL be rejected in the declared 4-PC subcase
- **AND** accepted surrender and explicit exit SHALL clear the active encounter and return to narration without duplicate damage/rewards or terminating the server

#### Scenario: Completed mechanical state survives restart replay
- **WHEN** the owned sandbox server is stopped and restarted after a preserved completed turn
- **THEN** the same encounter/state SHALL resume without reseeding
- **AND** completed HP/resource changes, enemy effects and historical combat-summary rewards SHALL NOT be applied again
- **AND** new commit-boundary interruption/receipt cases SHALL remain owned by the later G7 change

#### Scenario: Tooling rejects incomplete or synthetic acceptance
- **WHEN** fake-transport tests supply missing snapshots/checks, failed assertions, required step caps/timeouts or degraded required trace data
- **THEN** the evidence checks SHALL expose those failures and SHALL NOT produce a complete live PASS
- **AND** simulated observations SHALL remain labelled synthetic, not live gameplay evidence

### Requirement: Primary-owned live evidence is required for G3 acceptance

The primary orchestrator SHALL execute and judge the complete named G3 matrix for
1-PC and 4-PC parties after prerequisite tests/tooling pass. Runs SHALL use a real
`tmp/combat_capture/` copy, port 8360, `NEQ_OPEN_BROWSER=0` and the repository venv.
No capture SHALL use port 8357 or write installed campaign state. Each run SHALL
preserve its evidence before teardown under `tmp/router-rollout/g3/<run-id>/`.

#### Scenario: A live run has attributable evidence
- **WHEN** the primary reviews a G3 run
- **THEN** its bundle SHALL identify scenario/version, party/seed, source HEAD plus relevant dirty-worktree digest, configured model/provider, timestamps, declared bounds and actual step/request/timeout counts
- **AND** it SHALL contain verbatim transcript, owned-server log, runtime trace/report, relevant before/after sandbox state, expected/observed assertion results and concrete evidence references without credential/config values
- **AND** dynamic prompt byte-parity tests SHALL remain required alongside state/flow observations rather than literal equality of nondeterministic prose

#### Scenario: Exit zero does not establish a live PASS
- **WHEN** a driver or report exits 0 but a required scenario, assertion or artifact is missing, a required step caps/times out, or required evidence is degraded
- **THEN** G3 SHALL remain incomplete and SHALL NOT be marked PASS
- **AND** the primary SHALL record FAIL for an observed acceptance failure or BLOCKED for unavailable transport/tools/prerequisite coverage

#### Scenario: Gate verdict and lifecycle are recorded
- **WHEN** all required live scenarios/checks are reviewed
- **THEN** the primary SHALL record PASS, FAIL or BLOCKED with expected/observed outcomes and evidence paths in the owning change and overall goal plan before phase advancement
- **AND** attributable failures SHALL receive a focused fix and primary rerun of affected scenarios
- **AND** guideline/planning maintenance SHALL leave a paused goal paused and SHALL NOT count as live gate completion
