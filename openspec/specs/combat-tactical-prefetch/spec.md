# combat-tactical-prefetch Specification

## Purpose

Defines opt-in PC-phase standing orders that are evaluated against current Python-built menus at `/end`, with bounded re-planning, fail-open lifecycle, and request accounting separate from synchronous G5T acceptance.

## Requirements

### Requirement: Tactical standing-order prefetch SHALL be independently opt-in

Standing-order prefetch SHALL require `COMBAT_TACTICAL_PREFETCH_ENABLED=true`, `COMBAT_TACTICAL_BRAIN_ENABLED=true`, and `DETERMINISTIC_ENEMY_RESOLUTION_ENABLED=true`. The prefetch flag SHALL default to false. If any required flag is false, the PC phase SHALL make no background standing-order request; an eligible commander batch SHALL retain the existing synchronous plan path.

#### Scenario: Default flags leave prefetch inactive
- **WHEN** combat runs with default configuration
- **THEN** no tactical standing-order request SHALL occur during the PC phase
- **AND** the existing enemy-batch path SHALL remain unchanged

#### Scenario: Required resolver gate is disabled
- **WHEN** prefetch is configured on but deterministic enemy resolution is disabled
- **THEN** no tactical standing-order request SHALL occur
- **AND** the existing LLM enemy-batch path SHALL remain authoritative

### Requirement: Standing orders SHALL be submitted at PC-phase start and bound to one batch

When all required flags are enabled and an upcoming commander batch is identified, Python SHALL submit one initial background standing-order request when the PC phase starts: after initiative at combat start and after each enemy batch completes. Each request and result SHALL be bound to a bounded encounter ID, round-batch ID, and enemy roster identity. This batch binding SHALL NOT require equality of a full menu/perception snapshot fingerprint at `/end`.

#### Scenario: Eligible commander batch starts a PC phase
- **WHEN** the PC phase starts after initiative or after an enemy batch, all flags are enabled, and one upcoming commander batch is identified
- **THEN** the runtime SHALL submit one initial background standing-order request
- **AND** the receipt SHALL identify the encounter, round batch, and enemy roster identity

#### Scenario: PC actions never define phase completion
- **WHEN** one or more PCs take actions, including any number of attacks, during the PC phase
- **THEN** those action counts SHALL NOT trigger a standing-order request or signal that all PCs have acted
- **AND** the runtime SHALL wait for the human DM's `/end` to begin enemy planning

#### Scenario: No upcoming commander batch is identified
- **WHEN** no eligible upcoming commander batch can be identified at PC-phase start
- **THEN** the PC phase SHALL NOT submit a tactical standing-order request

### Requirement: Standing orders SHALL use a strict bounded conditional schema

The standing-order payload SHALL use a strict schema with no additional properties and bounded actor, clause, identity, and intent sizes. It SHALL identify at most 32 scheduled living enemy actors, each with zero to four ordered `{when, do}` clauses. The commander MAY provide at most one conditional withdrawal-order clause and one conditional side-surrender clause. Optional intent SHALL be capped at 160 characters and used only for narration or trace; no free text SHALL be consumed mechanically.

#### Scenario: Standing-order clauses are bounded and closed
- **WHEN** a standing-order response contains up to 32 actors with at most four clauses per actor and only the declared condition and action kinds
- **THEN** Python SHALL accept it for current-menu compilation
- **AND** optional intent text SHALL remain length-capped and narration/trace-only

#### Scenario: Conditions and actions use closed Python vocabulary
- **WHEN** a standing-order clause is evaluated
- **THEN** `when` SHALL be one of `always`, `self_bloodied`, `self_near_death`, `commander_down`, `cover_available`, or `ally_departed`
- **AND** per-actor `do` SHALL be `attack` (target identity and optional action name), `take_cover` (optional feature ID), `flee`, `surrender`, or `hold`
- **AND** commander clauses SHALL use only conditional withdrawal-order or side-surrender menu kinds

#### Scenario: Standing-order response violates the schema
- **WHEN** a response uses an unknown condition or action kind, adds an undeclared property, exceeds a bound, or supplies malformed identity data
- **THEN** the entire response SHALL be treated as schema-invalid
- **AND** no raw value SHALL reach mechanical application

### Requirement: Python SHALL compile standing orders against current legal menus at `/end`

At `/end`, Python SHALL compile standing orders against menus built from current authoritative state and apply only current option IDs. The candidate SHALL pass through the same validator and resolver as a synchronous plan with `decision_source=llm_tactical` and bounded `plan_origin=standing_orders`. Unmatched actors SHALL use rule-tier defaults with bounded reasons; Python SHALL remain authoritative, and no model planning call SHALL occur at `/end`.

#### Scenario: First matching legal clause compiles
- **WHEN** an actor's first conditionally eligible clause maps to a current legal menu option
- **THEN** Python SHALL compile that current option ID into the candidate plan
- **AND** it SHALL validate and resolve the candidate through the existing synchronous-plan path
- **AND** Python SHALL evaluate clauses in order and apply a commander side clause only when its corresponding current menu option is legal

#### Scenario: An earlier clause target is no longer legal
- **WHEN** an earlier clause's condition holds but its requested target or feature is absent from the current legal menu
- **THEN** Python SHALL skip that clause and evaluate the actor's next clause
- **AND** only a currently issued menu option ID MAY be compiled

#### Scenario: No clause maps to a legal current option
- **WHEN** no clause for an actor both holds and maps to a current legal menu option
- **THEN** the actor SHALL receive the rule-tier default with one bounded `default_reason`
- **AND** no illegal or unmappable clause SHALL reach the resolver

#### Scenario: `/end` consumes orders without a planner call
- **WHEN** Python consumes a completed standing-order set at `/end`
- **THEN** it SHALL compile against current menus without making a model planning call
- **AND** the compiled result SHALL use `decision_source=llm_tactical` and `plan_origin=standing_orders`

### Requirement: Standing-order re-plans SHALL be event-triggered and capped per batch

During a PC phase, Python MAY submit at most one re-plan per batch for a major state change. The batch cap SHALL be two background requests (one initial request plus one re-plan), and PC action counts SHALL NOT trigger requests. A newer completed, schema-valid order set SHALL supersede the prior set; the prior completed set SHALL remain usable until replacement completes.

#### Scenario: A major state change permits one re-plan
- **WHEN** one of the named major state changes occurs during the PC phase and the batch has used fewer than two background requests
- **THEN** Python MAY submit one re-plan bound to the same encounter and round batch
- **AND** it SHALL bind that request to the current enemy roster identity
- **AND** named changes are commander defeat/departure, an enemy newly bloodied or near-death, a targeted PC dropping to 0 HP or leaving, or an enemy roster change

#### Scenario: Re-plan limit is reached
- **WHEN** the initial request and one re-plan have already been submitted for a batch
- **THEN** no further background standing-order request SHALL be submitted for that batch

#### Scenario: Newer completed orders replace older orders
- **WHEN** a newer schema-valid standing-order set completes for the same batch
- **THEN** it SHALL supersede the older completed set
- **AND** the older completed set SHALL remain usable until the newer set completes

### Requirement: Unavailable submitted standing orders SHALL fail open without synchronous replanning

Once the eligible standing-order path is selected for a batch, Python SHALL NOT wait at `/end` or submit a synchronous planner request when no completed schema-valid order set is available, including when requests are pending, failed, cancelled, expired, or schema-invalid. All actors SHALL use rule-tier defaults and the bounded outcome `standing_orders_unavailable`.

#### Scenario: No usable order set is complete by `/end`
- **WHEN** no background request for the batch has completed with a schema-valid order set by `/end`
- **THEN** Python SHALL NOT wait or make a synchronous plan request
- **AND** every actor SHALL use a rule-tier default with the bounded `standing_orders_unavailable` outcome

#### Scenario: An earlier valid order set exists while a re-plan is pending
- **WHEN** a re-plan is pending or fails but an older completed schema-valid order set remains for the same batch
- **THEN** Python SHALL keep the older order set available
- **AND** any clauses it applies SHALL still be mapped only against current legal menus

### Requirement: Disabled or ineligible prefetch SHALL preserve synchronous planning

If prefetch is disabled or the batch is ineligible and no standing-order request was submitted, the existing eligible commander path SHALL make its single synchronous plan request unchanged. This fallback SHALL NOT be used after the eligible standing-order path has been selected and a background request is pending or unavailable.

#### Scenario: Prefetch was not submitted
- **WHEN** prefetch is disabled or the batch is ineligible and no background request was submitted
- **THEN** the eligible commander path MAY make its existing single synchronous planner request
- **AND** the batch SHALL retain its existing synchronous call invariant

### Requirement: Standing-order receipts SHALL be bounded, invalidated, and fail open

Receipts SHALL be process-local, protected by a lock, and governed by a bounded deadline. Python SHALL invalidate receipts on encounter exit or batch completion; late results SHALL be ignored without state writes or attribution to a later batch. A worker SHALL receive only immutable bounded request data and SHALL NOT mutate combat state. Receipt, worker, or tracing failures SHALL fail open, and router-owned retry and terminal behavior SHALL remain unchanged.

#### Scenario: Encounter or batch ends before a request completes
- **WHEN** combat exits or the identified batch completes before a background request finishes
- **THEN** its receipt SHALL be invalidated without waiting for provider cancellation
- **AND** any late result SHALL be ignored without a state write or later-batch attribution

#### Scenario: Worker completes after the current roster changes
- **WHEN** a background worker returns after its receipt was invalidated or superseded
- **THEN** the worker SHALL NOT write combat state
- **AND** the late result SHALL NOT be consumed as another batch's orders

#### Scenario: Receipt or trace handling fails
- **WHEN** receipt creation, completion tracking, or tracing fails
- **THEN** combat SHALL continue without blocking the turn
- **AND** the selected standing-order path SHALL fail open to rule-tier defaults

### Requirement: Background standing-order accounting SHALL be separate from synchronous G5T acceptance

Background standing-order requests SHALL have a distinct trace site/attribution and SHALL be counted and capped separately from per-batch synchronous requests, with no more than two background requests per batch. Primary G5T acceptance SHALL retain its existing limit of at most two synchronous requests per accepted batch. Optional prefetch captures SHALL report background standing-order counts and outcomes separately and SHALL NOT be required for or mixed into primary G5T acceptance.

#### Scenario: Primary G5T acceptance is measured without prefetch
- **WHEN** primary G5T acceptance is evaluated with prefetch disabled
- **THEN** the existing synchronous request limit SHALL remain at most two per accepted batch
- **AND** no background standing-order observation SHALL be required for primary PASS

#### Scenario: Optional standing-order requests are reported separately
- **WHEN** an optional prefetch capture includes an initial request or re-plan
- **THEN** the trace and report SHALL count those background requests under their own site/attribution, separately from synchronous requests
- **AND** the report SHALL show their per-batch count and bounded outcomes without changing primary acceptance
