# combat-decision-trace-events Specification

## Purpose
Define the decision-event contract needed to measure deterministic combat
decisions and future decision-primitive shadow evaluation without authorizing
Jev, changing routing, or adding provider calls.

## Requirements

### Requirement: Decision events SHALL contain the four baseline fields

Each recorded decision event SHALL contain `decision_point`, `decision_source`,
`decision_latency_ms`, and `provider_call_avoided`.
`decision_source` SHALL be exactly one of `deterministic`, `llm_fallback`, or
`jev`. Enemy-resolution decisions SHALL additionally record a bounded
`decision_outcome` (`resolver_supported`, `whole_batch_fallback`, or
`resolver_disabled`) and a bounded `decision_reason` code. For a supported
enemy batch, `provider_call_avoided` SHALL indicate that deterministic
mechanics avoided the existing generation and validation work; the separate
narration-only provider request SHALL remain visible as an actual provider
call.

#### Scenario: Deterministic decision is recorded

- **WHEN** an existing deterministic decision path resolves a decision point
- **THEN** the event SHALL use `decision_source=deterministic`
- **AND** it SHALL record non-negative decision latency and whether a provider
  call was avoided

#### Scenario: Supported enemy batch decision is recorded

- **WHEN** Python completes eligibility planning for a supported enemy batch
- **THEN** the event SHALL use the stable `enemy_batch_resolution` decision
  point and `decision_outcome=resolver_supported`
- **AND** its reason code SHALL be bounded and SHALL NOT contain prompt text,
  names, or mutable game state
- **AND** provider avoidance SHALL NOT hide the narration-only provider event

#### Scenario: Whole enemy batch falls back

- **WHEN** an eligibility check declines deterministic resolution for any
  scheduled enemy action
- **THEN** exactly one decision event SHALL use
  `decision_outcome=whole_batch_fallback` and the bounded fallback reason
- **AND** the event SHALL NOT imply that any deterministic ledger entry was
  applied

#### Scenario: Resolver is disabled

- **WHEN** the rollback/configuration flag disables deterministic resolution
- **THEN** the decision event SHALL use `decision_outcome=resolver_disabled`
- **AND** the existing LLM path SHALL remain the routing authority

#### Scenario: Tactical plan is recorded

- **WHEN** a commander plan supplies candidate menu selections
- **THEN** the event SHALL use `decision_source=llm_tactical`
- **AND** it SHALL record non-negative decision latency and whether a provider
  call was avoided

### Requirement: Decision point names SHALL identify the observed seam

`decision_point` SHALL identify the bounded decision seam or operation being
measured, rather than embedding a prompt, full user message, or mutable game
state. The event SHALL be usable for aggregation across fixture runs.

#### Scenario: Multiple decisions use the same seam

- **WHEN** the same decision seam resolves in multiple turns
- **THEN** each event SHALL use a stable decision-point value
- **AND** the report SHALL be able to group those events without parsing prose

### Requirement: Decision source semantics SHALL remain distinct

`deterministic` SHALL mean the existing code path resolved the decision;
`llm_fallback` SHALL mean the existing flow fell through to its LLM path;
`jev` SHALL be reserved for a future authorized decision primitive and SHALL
NOT require Jev implementation in this change.

#### Scenario: LLM fallback is observed

- **WHEN** an existing deterministic or fast-path attempt falls through to the
  existing LLM path
- **THEN** the event SHALL use `decision_source=llm_fallback`
- **AND** instrumentation SHALL NOT add or remove a provider call

#### Scenario: Jev value is not implemented

- **WHEN** no Jev implementation exists in the runtime
- **THEN** no `jev` event SHALL be fabricated
- **AND** the schema SHALL still accept `jev` as a reserved source value

#### Scenario: Tactical plan is observed

- **WHEN** a commander plan supplies candidate menu selections
- **THEN** the decision event SHALL use `decision_source=llm_tactical`
- **AND** Python validation SHALL remain authoritative for the applied choices

### Requirement: Provider avoidance SHALL be explicit

`provider_call_avoided` SHALL be a boolean indicating whether the observed
decision avoided an otherwise applicable provider call. It SHALL describe the
existing path and SHALL NOT itself control routing.

#### Scenario: Fast path avoids a provider call

- **WHEN** an existing deterministic path completes without an applicable
  provider call
- **THEN** `provider_call_avoided` SHALL be true
- **AND** the decision outcome SHALL remain unchanged by tracing

#### Scenario: Fallback uses a provider call

- **WHEN** an existing decision falls through to its provider path
- **THEN** `provider_call_avoided` SHALL be false
- **AND** the existing provider outage and retry behavior SHALL remain intact

### Requirement: Decision trace failures SHALL be fail-open

Failure to classify, serialize, or write a decision event SHALL NOT block or
alter the decision, combat state, prompt, or provider behavior.

#### Scenario: Decision event emission fails

- **WHEN** decision-event instrumentation raises an internal error
- **THEN** the original decision path SHALL continue
- **AND** no compensating provider call or game-state write SHALL occur

### Requirement: Validation routing outcomes SHALL be traceable

Each combat validation routing decision SHALL report whether LLM validation was skipped, its stable reason, and whether a provider call was avoided; the event SHALL NOT control routing.

#### Scenario: Deterministic prechecks allow a skip
- **WHEN** combat skips LLM validation after deterministic prechecks pass
- **THEN** the event SHALL record a deterministic source, a skip outcome, a reason, and `provider_call_avoided=true`

#### Scenario: Validation remains on the LLM path
- **WHEN** a deterministic precheck fails or an action is not eligible for skipping
- **THEN** the event SHALL record the non-skip outcome and its reason
- **AND** the event SHALL report `provider_call_avoided=false`

#### Scenario: Future Jev reason names remain reserved
- **WHEN** no Jev decision primitive is implemented
- **THEN** the runtime SHALL NOT emit `jev_residual_ok`, `jev_unavailable_fallback`, or `jev_low_confidence`
- **AND** those reason values SHALL remain reserved for separately authorized Jev work

### Requirement: NL PC-phase outcomes SHALL distinguish hit, miss, false positive, fallback, and unavailability

Eligible NL PC-phase decisions SHALL record a bounded outcome of hit, miss, false positive, or unavailable, and SHALL identify whether the existing LLM fallback ran; G5 reports SHALL calculate rates from observed events only.

#### Scenario: Supported action is applied deterministically
- **WHEN** an eligible parsed PC action is successfully applied
- **THEN** the event SHALL record a hit and `provider_call_avoided=true`

#### Scenario: Parser declines an action
- **WHEN** the parser does not recognize or fully parse an eligible action
- **THEN** the event SHALL record a miss and LLM fallback
- **AND** the action SHALL continue through the existing LLM path

#### Scenario: Parsed action cannot be applied
- **WHEN** the parser reports a handled action but deterministic application rejects it
- **THEN** the event SHALL record a false positive and LLM fallback
- **AND** the action SHALL continue through the existing LLM path

#### Scenario: Parser is unavailable
- **WHEN** the parser cannot be loaded for an eligible action
- **THEN** the event SHALL record `unavailable`, distinct from a parse miss
- **AND** the action SHALL continue through the existing LLM path

### Requirement: Deterministic `/att` hit decisions SHALL be traceable

The existing deterministic `/att` hit fast path SHALL emit the same bounded `combat_command_fast_path` decision event used by the `/dmg` fast path, including `provider_call_avoided=true`; this event is observational and SHALL NOT control routing.

#### Scenario: Attack hit records its fast-path decision
- **WHEN** `/att` resolves as a hit and records the pending-damage ledger event
- **THEN** the matching `combat_command_fast_path` decision SHALL be emitted before the hit branch returns
- **AND** it SHALL report `provider_call_avoided=true`
- **AND** the existing command result and routing behavior SHALL remain unchanged

### Requirement: Tactical decision events SHALL report bounded plan outcomes

Commander-plan events SHALL include bounded `tactical_plan_outcome`, optional `plan_origin`, and run-local per-actor default reasons. Standing-order events SHALL include bounded `standing_orders_outcome`, including `standing_orders_unavailable`. Events SHALL omit prompts, secrets, absolute paths, and unbounded narrative or game-state payloads.

#### Scenario: Commander plan is accepted or defaulted

- **WHEN** Python validates the commander plan for a batch
- **THEN** the event SHALL distinguish fully accepted, partially defaulted, and wholly rejected plans
- **AND** each actor default SHALL have one bounded reason code

#### Scenario: Standing-order outcome is observed

- **WHEN** a standing-order receipt is consumed, unavailable, failed, or invalidated
- **THEN** the event SHALL attribute the outcome to the same bounded batch correlation
- **AND** it SHALL record the bounded standing-order outcome and distinct background-request attribution without recording request content

### Requirement: Tactical plan-result events SHALL snapshot current bounded menus

Each `combat_tactical_plan_result` event SHALL include bounded `actor_ids` for
the current scheduled actor menus and `target_ids` for the current living-enemy
target catalog. Each list SHALL contain at most 32 unique run-local IDs matching
`actor_1` through `actor_32`; it SHALL contain no names or free text. G5T SHALL
derive later-menu removal from subsequent plan-result snapshots when present.

#### Scenario: A departed creature is absent from later menus

- **WHEN** G5T observes a later plan result after a flee or surrender
- **THEN** it SHALL compare the departed actor ID against the later `actor_ids`
  and `target_ids` lists
- **AND** it SHALL NOT infer menu removal from the self-preservation event alone

#### Scenario: A later fallback batch proves a departed creature is excluded

- **WHEN** a subsequent enemy batch has no plan-result snapshot and its
  `enemy_batch_resolution` decision uses `deterministic`, `llm_fallback`, or
  `jev`
- **THEN** G5T MAY derive removal only from exactly one matching
  `combat_action_batch` with `validation_accepted=true` and
  `enemy_phase_batch=true`, where the departed creature's normalized name is
  absent from `eligible_non_pc_cohort`, `explicit_actor_records`, and
  `affected_entities`
- **AND** an `llm_fallback` batch SHALL also have exactly one accepted
  `combat_validation_result` whose `eligible_non_pc_cohort` matches the action
  batch cohort
- **AND** the persisted encounter entry SHALL establish the same actor as
  `status=defeated` with the observed `defeatReason`
- **AND** missing, malformed, or ambiguous fallback evidence SHALL remain
  `BLOCKED`

### Requirement: Applied tactical choices SHALL have bounded legality observations

With tracing enabled, any commander choice with a final-ledger outcome SHALL
emit one `applied_choice_legality` event with bounded applied/legal counts.
Python SHALL recheck issued menu IDs; an unissued ID counts as applied but not
legal. Emit no such event when no choice was applied.

#### Scenario: Applied choices are checked against the issued menu

- **WHEN** a commander choice has an outcome in the final resolver ledger
- **THEN** the trace SHALL report its applied count and independently verified
  legal count for the same bounded batch
- **AND** an unissued option ID that nevertheless produces a ledger outcome
  SHALL make the legal count lower than the applied count

### Requirement: Commander follow-through SHALL have bounded observations

When tracing is enabled, every commander-planned batch SHALL emit one
`commander_squad_follows_orders` event with bounded actor-choice counts (0..32)
and boolean `followed_orders`. True means all accepted choices match final
ledger outcomes; rejected choices count as neither accepted nor applied.

#### Scenario: No commander choice was applied

- **WHEN** a commander plan is rejected or no accepted choice has a final-ledger
  outcome
- **THEN** the batch SHALL emit no `applied_choice_legality` observation
- **AND** its squad-followthrough event SHALL retain bounded zero counts when
  the batch was commander-planned

### Requirement: Tactical decision observations SHALL remain bounded and fail-open

Decision observations SHALL contain no actor names, prompts, secrets, absolute
paths, or free-text game state. Tracing SHALL be opt-in and fail-open: disabled
tracing writes nothing, and trace construction failure SHALL NOT affect
mechanics or combat.

#### Scenario: Trace observations are bounded and fail-open

- **WHEN** decision tracing is disabled or observation construction fails
- **THEN** disabled tracing SHALL write no observation and construction failure
  SHALL NOT alter combat mechanics or combat flow
- **AND** any emitted observation SHALL contain only bounded identifiers,
  reason codes, enums, booleans, and counts

### Requirement: Tactical cover outcomes SHALL be traceable

When decision tracing is enabled, cover selection, application, and expiration SHALL emit bounded cover outcomes identifying the run-local combatant, authored feature ID, cover type, and applied or expired state. An absent or malformed feature SHALL be represented by a bounded reason code rather than inferred details.

#### Scenario: Cover applies and expires

- **WHEN** authored cover changes a target's effective AC and later expires
- **THEN** trace events SHALL identify the applied and expired observations
- **AND** the effective-AC bonus SHALL be reportable without copying the encounter payload

#### Scenario: Cover instrumentation fails

- **WHEN** cover event construction or serialization fails
- **THEN** cover mechanics and combat SHALL continue unchanged
- **AND** no compensating provider call or state write SHALL occur

### Requirement: Self-preservation outcomes SHALL use a bounded trace enum

Each applied per-creature self-preservation outcome SHALL be traceable as `self_preservation_outcome=fled` or `self_preservation_outcome=surrendered`, matching the encounter creature's `defeatReason`. Events SHALL identify only a bounded run-local actor and batch; they SHALL NOT copy prompts or unbounded game state.

#### Scenario: Creature flees
- **WHEN** Python applies a legal flee choice
- **THEN** the trace SHALL report `self_preservation_outcome=fled`
- **AND** the encounter projection SHALL persist `defeatReason=fled`

#### Scenario: Creature surrenders
- **WHEN** Python applies an individual or side-level surrender choice
- **THEN** each affected creature's trace SHALL report `self_preservation_outcome=surrendered`
- **AND** each affected encounter entry SHALL persist `defeatReason=surrendered`
