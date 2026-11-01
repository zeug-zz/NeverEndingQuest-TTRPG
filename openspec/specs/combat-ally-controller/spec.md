# combat-ally-controller Specification

## Purpose
Defines how allied NPCs receive bounded tactical choices and player directives in combat while Python retains authority over legality, mechanics, persistence, and initiative progression.

## Requirements

### Requirement: Active allied NPCs SHALL resolve in a separate initiative-positioned batch

The ally controller SHALL schedule only active encounter NPCs in its own batch, separate from hostile enemy batches, and SHALL place that batch according to the initiative-group result.

#### Scenario: The DM group wins initiative
- **WHEN** the DM group wins initiative for the round
- **THEN** the combat order SHALL be hostile enemies, allied NPCs, then PCs
- **AND** the ally controller SHALL use a distinct ally batch between the hostile and PC phases

#### Scenario: The PC group wins initiative
- **WHEN** the PC group wins initiative for the round
- **THEN** the combat order SHALL be PCs, allied NPCs, then hostile enemies
- **AND** the ally controller SHALL use a distinct ally batch between the PC and hostile-enemy phases

#### Scenario: An NPC is not active
- **WHEN** an encounter NPC is unconscious, dead, defeated, departed, or has zero HP
- **THEN** Python SHALL exclude that NPC from the ally batch
- **AND** no plan option SHALL permit that NPC to act

### Requirement: Ally plans SHALL select only Python-issued legal options

Python SHALL build a bounded per-actor option menu and SHALL accept only issued opaque option IDs; the model SHALL NOT supply mechanics, targets, coordinates, or executable free text.

#### Scenario: A legal ally option is selected
- **WHEN** an ally plan selects an issued option ID from the current immutable menu
- **THEN** Python SHALL resolve the selected option using authoritative encounter and character state
- **AND** the model response SHALL NOT mutate combat state directly

#### Scenario: An ally choice is missing or illegal
- **WHEN** a choice is missing, malformed, duplicated, or names an unknown actor or option
- **THEN** Python SHALL apply its deterministic rule-based default for the affected actor
- **AND** Python SHALL record one bounded default reason
- **AND** no invalid choice SHALL reach mechanical application

### Requirement: Ally perception SHALL exclude enemy-only and hidden facts

The ally-plan projection SHALL contain only bounded ally-scoped facts, current legal options, applicable player directives, and facts available to the allied actors; it SHALL omit enemy-private plans, hidden facts, and unrelated campaign data.

#### Scenario: The ally plan receives a scoped projection
- **WHEN** Python builds an ally-plan request
- **THEN** the request SHALL identify only its scheduled allied actors and currently legal target options
- **AND** enemy-private plans, hidden or off-scene facts, full module rosters, and unrelated prompts SHALL be absent
- **AND** omission SHALL NOT be represented as a fabricated negative fact

#### Scenario: A directive belongs to one ally
- **WHEN** a pending `/cmd` directive names one active ally
- **THEN** the directive SHALL be projected as guidance for that ally only
- **AND** it SHALL NOT become a command or a forced action for any actor

### Requirement: Current ally actions SHALL use existing Python effect contracts

The current ally menu SHALL expose only options with an existing Python legality and effect contract, including legal attacks and the existing authored `take_cover` option when its current contract permits it. The ally controller SHALL NOT introduce new defensive mechanics in this change. Future spatial movement/protection placeholders SHALL NOT be issued as current menu or prefetch options and SHALL NOT be mechanically applied.

#### Scenario: An ally chooses an existing legal defensive option
- **WHEN** an ally selects an issued authored `take_cover` option that is legal under the existing Python cover contract
- **THEN** Python SHALL apply only the effect represented by that option's current legal contract
- **AND** the Narrator SHALL describe no mechanical effect absent from the resolved state

#### Scenario: A future spatial placeholder is not an issued action
- **WHEN** a plan or prefetch response names a documented placeholder such as `move_to_cover`, `interpose_for_ally`, or `guard_ally` that is absent from the current Python menu
- **THEN** Python SHALL treat it as an unknown option and use the existing deterministic fallback
- **AND** Python SHALL NOT simulate movement, apply a positional effect, or claim that the tactic occurred
- **AND** the placeholder SHALL remain documentation only until a later change defines its position and effect contracts

### Requirement: `/cmd` SHALL record a bounded directive without ending the PC phase

Python SHALL parse `/cmd <AllyName> <free text>`, validate the named active encounter NPC, sanitize and bound the directive, and associate it with that ally's next plan.

#### Scenario: A valid ally directive is accepted
- **WHEN** a PC submits `/cmd <active ally name> <non-empty text>` during combat
- **THEN** Python SHALL record sanitized text of at most 240 characters for that ally's next plan
- **AND** the UI SHALL acknowledge the directive
- **AND** the directive SHALL guide but SHALL NOT force the ally's choice

#### Scenario: An unknown or inactive ally is named
- **WHEN** `/cmd` names no encounter NPC or names an unconscious, dead, defeated, or departed NPC
- **THEN** Python SHALL return a clear error through the combat response path
- **AND** it SHALL make no directive or combat-state change

#### Scenario: `/cmd` is not a PC action or phase transition
- **WHEN** Python accepts a `/cmd` directive
- **THEN** it SHALL NOT end the PC phase, consume a PC action, or limit later PC attacks
- **AND** the human DM SHALL retain control of `/end`

#### Scenario: Directives coalesce before the bounded re-plan
- **WHEN** multiple valid directives for one ally arrive before the batch's one re-plan request is submitted
- **THEN** Python SHALL coalesce them to the latest directive for that ally
- **AND** after that re-plan request is submitted, another same-batch `/cmd` SHALL receive a clear no-state-change response

### Requirement: Ally standing orders SHALL be prefetched with a bounded lifecycle

When enabled and an upcoming ally batch is identifiable, Python SHALL prefetch bounded conditional ally intents during the PC phase, with one initial request and at most one state-edge or directive-triggered re-plan per ally batch.

#### Scenario: An eligible ally batch starts its PC-phase prefetch window
- **WHEN** an eligible upcoming ally batch is identified at PC-phase start and ally prefetch is enabled
- **THEN** Python SHALL submit one background request bound to encounter, batch, and ally-roster identity
- **AND** the request SHALL receive only an immutable bounded prompt projection

#### Scenario: A directive or major state edge permits one re-plan
- **WHEN** a valid `/cmd` directive or an accepted major state-edge trigger occurs before the re-plan is submitted
- **THEN** Python MAY submit one re-plan for the same ally batch
- **AND** the batch SHALL never exceed two background requests
- **AND** PC action counts SHALL NOT trigger a request

#### Scenario: Prefetched orders are compiled at the ally batch
- **WHEN** Python reaches the ally batch after prefetch was selected
- **THEN** it SHALL compile the orders against current Python-built menus
- **AND** it SHALL make no synchronous planner request at that boundary
- **AND** missing, invalid, or unavailable orders SHALL use rule-based defaults

#### Scenario: No prefetch request was selected
- **WHEN** prefetch is disabled or the ally batch was ineligible and no request was submitted
- **THEN** the eligible ally controller MAY use its single synchronous plan request
- **AND** the ally batch SHALL retain the same plan-legality and call-budget rules

### Requirement: Accepted ally batches SHALL remain within the provider-call budget

Each accepted ally batch SHALL make at most one synchronous plan request and one narration request, with no combat-validation or correction request; router-owned retry and terminal behavior SHALL remain unchanged.

#### Scenario: An ally batch is planned and narrated
- **WHEN** a supported ally batch uses synchronous planning
- **THEN** it SHALL make at most one plan request and one narration request
- **AND** it SHALL make zero combat-validation requests

#### Scenario: The plan is missing or unusable
- **WHEN** the planner is unavailable or returns missing or illegal choices
- **THEN** Python SHALL use deterministic rule defaults without a second plan request
- **AND** narration SHALL describe only the final applied ledger

### Requirement: Ally effects SHALL use the existing combat-turn receipt path

Allied mechanical effects SHALL be staged with the accepted combat input and committed through the existing character-first, encounter-last manifest and receipt path; an ally batch SHALL NOT create a parallel writer or receipt protocol.

#### Scenario: A hostile batch and ally batch resolve from one accepted input
- **WHEN** one accepted combat input schedules both hostile and ally batches
- **THEN** Python SHALL stage their effects under that input's existing `turn_id` and `applied_id`
- **AND** one manifest and one receipt SHALL cover the combined final encounter projection and changed-character effects
- **AND** the runtime SHALL publish success only after the receipt-bearing encounter write and post-commit synchronization

#### Scenario: A committed ally batch is replayed
- **WHEN** the same accepted input is recovered or replayed after its receipt is durable
- **THEN** Python SHALL apply no allied effect or reward a second time
- **AND** it SHALL NOT append a duplicate receipt

### Requirement: Ally controller and prefetch flags SHALL remain default-off

`COMBAT_ALLY_CONTROLLER_ENABLED` and `COMBAT_ALLY_PREFETCH_ENABLED` SHALL default to false; the controller SHALL require deterministic enemy resolution, and prefetch SHALL additionally require the controller flag.

#### Scenario: Shipped defaults leave ally control inactive
- **WHEN** combat runs with shipped default flags
- **THEN** no ally plan or ally-prefetch request SHALL occur
- **AND** existing combat behavior SHALL remain unchanged

#### Scenario: G5A enables flags only in its sandbox
- **WHEN** the primary prepares an isolated G5A Capture_Arena copy
- **THEN** the controller flags MAY be enabled in that copy only
- **AND** shipped defaults and installed campaign state SHALL remain unchanged
