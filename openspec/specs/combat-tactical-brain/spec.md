# combat-tactical-brain Specification

## Purpose

Defines how an optional enemy-side commander selects legal squad tactics without taking mechanical authority from Python or exposing information outside the current encounter.

## Requirements

### Requirement: Encounter tactic tiers SHALL default to the deterministic rule tier

An enemy combatant MAY declare `tactics` as `rule` or `commander`; an omitted value SHALL mean `rule`. Only one living encounter leader with `tactics=commander` SHALL authorize a commander plan for the current enemy side.

#### Scenario: Legacy encounter omits tactic tier
- **WHEN** an enemy encounter entry has no `tactics` field
- **THEN** the enemy SHALL use the rule tier without a tactical-plan request

#### Scenario: A designated commander leads one enemy side
- **WHEN** exactly one living enemy has `leader=true` and `tactics=commander`
- **THEN** that leader SHALL be the sole commander for the current enemy side
- **AND** one plan MAY assign legal choices to every scheduled enemy actor on that side

#### Scenario: Commander authority is absent or ambiguous
- **WHEN** no living commander is designated, or multiple commanders are designated
- **THEN** the existing deterministic-resolver eligibility and whole-batch fallback rules SHALL remain authoritative
- **AND** the runtime SHALL NOT infer a commander from names, roles, or prose

### Requirement: Commander plans SHALL select only Python-issued menu options

Python SHALL build a bounded menu for each scheduled enemy actor and SHALL accept only a structured selection of menu option IDs. A tactical plan SHALL NOT supply attack rolls, damage, status changes, arbitrary targets, or free-form executable actions.

#### Scenario: Valid choices are selected
- **WHEN** the commander response selects one issued option ID for each actor it addresses
- **THEN** Python SHALL resolve the corresponding mechanics from the authoritative menu and combat state
- **AND** the plan response SHALL NOT mutate state directly

#### Scenario: Attack options declare cover compatibility
- **WHEN** Python projects an attack slot into the commander menu
- **THEN** each option SHALL expose `cover_compatible=true` only when its authored attack is classified as ranged
- **AND** the prompt SHALL allow an attack-plus-cover choice only when every selected attack option is marked compatible
- **AND** Python SHALL continue rejecting cover combined with any melee or unclassified attack, defaulting only that actor

#### Scenario: A choice is missing or invalid
- **WHEN** a choice is omitted, duplicated, malformed, or references an unknown actor or option
- **THEN** the affected actor SHALL use the rule-tier choice
- **AND** Python SHALL record one bounded default reason for that actor
- **AND** no invalid choice SHALL reach mechanical application

#### Scenario: Planner returns no usable choices
- **WHEN** every commander choice is rejected or a non-terminal planner failure occurs
- **THEN** all affected actors SHALL use rule-tier choices with bounded reasons
- **AND** the runtime SHALL NOT issue a second planner call for the batch

#### Scenario: Conditional flee choice is not authorized
- **WHEN** a plan selects an above-bloodied creature's conditional flee option without also selecting the issued commander withdrawal order
- **THEN** Python SHALL reject that flee selection
- **AND** the creature SHALL use its legal rule-tier choice with a bounded default reason

### Requirement: Commander planning SHALL use perception-limited encounter facts

The planner input SHALL contain only the current encounter's eligible actors, legal target and feature options, and bounded facts explicitly projected for that encounter. It SHALL omit campaign-wide or off-scene rosters, hidden facts, secrets, and unissued target or feature identities.

#### Scenario: Plan menu exposes legal targets only
- **WHEN** Python constructs target options for a commander plan
- **THEN** every target option SHALL be an actor already eligible under the deterministic resolver's current target rules
- **AND** the planner SHALL have no option ID for an excluded or unresolved target

#### Scenario: Hidden or absent information is unavailable
- **WHEN** a creature or fact is outside the current encounter projection or lacks an explicit legal option
- **THEN** it SHALL NOT appear in the tactical-plan input
- **AND** omission SHALL NOT be represented as a fabricated negative fact

#### Scenario: Eligible actor disposition is bounded and scoped

- **WHEN** an eligible actor has a monster-definition `description`
- **THEN** the plan projection MAY include that actor's own printable, whitespace-normalized disposition text, capped at 240 characters
- **AND** a missing or malformed description SHALL be omitted
- **AND** descriptions for absent actors, hidden facts, and unrelated creatures SHALL NOT be included
- **AND** disposition text SHALL inform choices only and SHALL NOT authorize an unissued option or alter Python-owned mechanics

### Requirement: Tactical planning SHALL not widen the enemy-batch provider path

For a supported commander batch that submits a plan request, the runtime SHALL make at most one logical tactical-plan call and no combat-validation call. An accepted batch SHALL retain the existing single narration call; tactical planning SHALL add no correction request or second plan call. A batch rejected by resolver preflight before plan submission SHALL retain the existing whole-batch generate-and-validate fallback.

#### Scenario: Commander batch uses its bounded calls
- **WHEN** a commander plan is accepted and the batch is narrated
- **THEN** the batch SHALL use one logical plan call and one narration call
- **AND** it SHALL use no combat-validation call

#### Scenario: Rule-tier or per-actor default is used
- **WHEN** a commander choice defaults to the rule tier
- **THEN** Python SHALL continue from its deterministic plan without another plan call
- **AND** the existing narration-only path SHALL remain unchanged

#### Scenario: Resolver preflight declines before plan submission
- **WHEN** the existing resolver identifies an unsupported mechanic or lifecycle state before a commander request is submitted
- **THEN** the whole batch SHALL use the existing generate-and-validate path
- **AND** no tactical plan request SHALL be made for that batch

### Requirement: Self-preservation choices SHALL be per-creature and legally offered

For a supported commander-led batch, Python SHALL offer self-preservation options only to scheduled living creatures meeting the eligibility scenarios below. The commander itself is eligible. A commander-issued withdrawal order MAY authorize conditional flee choices above bloodied. Rule-tier sides and leader-down batches SHALL retain their existing 4b behavior.

#### Scenario: Bloodied creature can flee
- **WHEN** a scheduled living enemy has positive HP at or below 50% of its authoritative maximum HP
- **THEN** Python SHALL issue that creature a per-creature flee option
- **AND** choosing flee SHALL consume its action as Disengage, prevent opportunity attacks, and make it perform no attack that turn
- **AND** it SHALL leave combat at the end of its turn, when Python marks it `status=defeated` with `defeatReason=fled`, without modeling grid movement

#### Scenario: Commander orders a withdrawal
- **WHEN** the living commander selects an issued withdrawal order in the batch plan
- **THEN** conditional per-creature flee choices issued for scheduled living side members above bloodied SHALL become legal in that same plan
- **AND** each creature selecting flee SHALL resolve its own Disengage action and outcome

#### Scenario: Fleeing creature leaves later actor and target menus
- **WHEN** a creature completes its flee action and becomes `defeated`
- **THEN** it SHALL be excluded from subsequent turn actors and legal target menus
- **AND** no later action in the batch SHALL resolve for it

#### Scenario: Individual creature surrenders
- **WHEN** a scheduled living enemy at or below the 25% near-death boundary selects its issued surrender option
- **THEN** Python SHALL mark only that creature `status=defeated` with `defeatReason=surrendered`
- **AND** it SHALL be excluded from subsequent turn actors and legal target menus

#### Scenario: Commander side surrenders
- **WHEN** a living commander selects the issued side-level surrender option at the near-death boundary
- **THEN** Python SHALL mark every living enemy on that side `status=defeated` with `defeatReason=surrendered`
- **AND** the existing all-enemies-defeated exit and XP paths SHALL apply unchanged

#### Scenario: Commander flees and the next batch is leaderless
- **WHEN** the designated commander flees during a supported batch
- **THEN** the current batch SHALL use only its already-validated choices
- **AND** the next batch SHALL have no living commander and SHALL retain the existing 4b leader-down whole-batch decline/fallback behavior

#### Scenario: Rule-tier side reaches near death
- **WHEN** a rule-tier side reaches the existing 4b near-death boundary
- **THEN** the existing 4b whole-batch decline/fallback behavior SHALL remain unchanged

#### Scenario: Flee and surrender reuse existing exit and XP paths
- **WHEN** fleeing or surrendering leaves every enemy `defeated`
- **THEN** the existing all-enemies-defeated exit and XP paths SHALL run unchanged
- **AND** this change SHALL NOT alter the existing XP policy

### Requirement: Defeat reasons SHALL be schema-additive and available to narration

Encounter creatures MAY include `defeatReason` with values `fled` or `surrendered`; absence SHALL retain legacy defeat interpretation. The accepted narration context SHALL receive the resolved defeat reason for each affected creature and SHALL describe flight or surrender consistently with the Python-owned ledger.

#### Scenario: Flight is narrated from authoritative outcome
- **WHEN** a creature's resolved encounter entry has `status=defeated` and `defeatReason=fled`
- **THEN** narration context SHALL identify that creature as having fled
- **AND** narration SHALL NOT claim it was killed or leave it as an active combatant

#### Scenario: Surrender is narrated from authoritative outcome
- **WHEN** a creature's resolved encounter entry has `status=defeated` and `defeatReason=surrendered`
- **THEN** narration context SHALL identify that creature as having surrendered
- **AND** narration SHALL NOT claim it was killed or leave it as an active combatant

#### Scenario: Legacy defeat has no reason field
- **WHEN** an existing encounter creature has `status=defeated` without `defeatReason`
- **THEN** the encounter SHALL remain valid
- **AND** the runtime SHALL preserve its existing legacy defeat behavior
