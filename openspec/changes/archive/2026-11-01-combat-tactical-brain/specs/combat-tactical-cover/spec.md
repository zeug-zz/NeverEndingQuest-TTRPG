# Spec Delta

## Purpose

Defines explicit location cover affordances and encounter-scoped cover effects so every code-owned attack uses one authoritative effective-AC calculation.

## ADDED Requirements

### Requirement: Tactical cover features SHALL be explicitly authored

Location data MAY contain `tacticalFeatures` entries with a unique `featureId`, `name`, `kind=cover`, `coverType` (`half` or `three_quarters`), and non-empty `usableBy` combatant kinds. Runtime SHALL NOT infer cover from prose, grid cells, or actor positions.

#### Scenario: Valid cover feature is loaded
- **WHEN** a current location contains a schema-valid cover feature
- **THEN** Python SHALL make it available only to combatant kinds listed by `usableBy`
- **AND** no location without an explicit feature SHALL gain a cover option

#### Scenario: Cover feature is missing or malformed
- **WHEN** a feature ID, cover type, or eligible combatant kind cannot be resolved
- **THEN** Python SHALL NOT issue a cover option for that feature
- **AND** it SHALL NOT infer an alternative feature or position

### Requirement: Cover state SHALL be encounter-scoped

An encounter combatant MAY record a valid cover reference. Cover SHALL remain encounter-only; its persistence and in-combat clearing SHALL follow the applied-choice scenarios below. Effective-AC lookup SHALL apply cover only to a creature in the currently active encounter while combat is in progress.

#### Scenario: Combatant selects authored cover
- **WHEN** a combatant selects a legal cover menu option
- **THEN** Python SHALL persist the feature identity and cover type in the final encounter projection
- **AND** the existing batch write count SHALL NOT gain an additional file write

#### Scenario: Encounter exits
- **WHEN** the existing combat-exit lifecycle completes
- **THEN** cover on the completed encounter SHALL remain unused because it is no longer the active in-progress encounter
- **AND** effective-AC lookup for a later or different encounter SHALL NOT read or apply the completed encounter's cover
- **AND** the exit lifecycle SHALL NOT add an encounter-cover cleanup write
- **AND** character-sheet AC SHALL remain unchanged

#### Scenario: A new or restarted encounter begins
- **WHEN** a new encounter starts, including a restart after a completed encounter
- **THEN** its combatants SHALL begin without cover carried from the completed encounter
- **AND** stale cover fields MAY be cleared only within an existing start-of-encounter write, without adding a write

#### Scenario: Cover is retained after a ranged attack
- **WHEN** a covered combatant's subsequent applied choice is hold, a ranged weapon attack, or selecting the same cover feature again
- **THEN** its valid cover reference SHALL persist across the batch boundary
- **AND** the final encounter projection SHALL include the cover state without an additional file write

#### Scenario: A different cover feature replaces the prior feature
- **WHEN** a covered combatant selects a different legal cover feature
- **THEN** the final encounter projection SHALL replace the prior feature ID and cover type with the selected feature
- **AND** it SHALL do so within the batch's single final encounter write

#### Scenario: Ranged attacks may combine with taking cover

- **WHEN** an actor selects all of its listed ranged attack slots and appends one legal `take_cover` option
- **THEN** Python SHALL resolve the selected attacks and the movement choice in the same turn
- **AND** the final encounter projection SHALL retain the selected cover feature
- **AND** no additional raw write SHALL be added for the cover choice

#### Scenario: A cover-only choice remains valid and multiple cover choices are rejected

- **WHEN** an actor selects exactly one legal `take_cover` option without selecting attack slots
- **THEN** Python SHALL apply the movement choice
- **AND** when a plan selects more than one `take_cover` option for one actor, Python SHALL default that actor's choice without applying cover

#### Scenario: Cover combined with melee is rejected

- **WHEN** an actor selects `take_cover` together with any melee attack slot
- **THEN** Python SHALL reject that actor's combined choice and use its legal rule-tier choice
- **AND** the rejected cover selection SHALL NOT update the final encounter projection

#### Scenario: Melee attack clears cover
- **WHEN** a covered combatant's subsequent applied choice is a melee weapon attack
- **THEN** Python SHALL clear both `coverType` and `coverFeatureId` in the batch's single final encounter projection
- **AND** later attacks SHALL use base AC unless the combatant selects cover again

#### Scenario: Flight, surrender, defeat, or death clears cover
- **WHEN** a covered combatant flees, surrenders, is defeated, or dies
- **THEN** Python SHALL clear both `coverType` and `coverFeatureId` in the batch's single final encounter projection
- **AND** no additional persistence write SHALL be added for cover cleanup

#### Scenario: Unknown authored attack classification clears cover
- **WHEN** authored action data does not unambiguously classify a weapon attack as ranged
- **THEN** Python SHALL treat that attack as melee for cover lifetime
- **AND** it SHALL clear the cover reference in the batch's single final encounter projection

### Requirement: Code-owned attacks SHALL use effective AC

For an attack against a combatant with valid encounter cover, Python SHALL add the cover bonus to the existing authoritative base AC: `+2` for half cover and `+5` for three-quarters cover. Cover bonuses SHALL NOT stack, and malformed or stale cover references SHALL provide no bonus.

#### Scenario: PC attacks an enemy behind cover
- **WHEN** the PC `/att` path resolves an enemy with valid encounter cover
- **THEN** its hit comparison SHALL use the enemy's authoritative base AC plus the cover bonus
- **AND** the displayed or recorded result SHALL match that effective AC

#### Scenario: Enemy attacks a PC behind cover
- **WHEN** the deterministic enemy resolver attacks a PC with valid encounter cover
- **THEN** its hit comparison SHALL use the PC's authoritative base AC plus the cover bonus
- **AND** the resulting ledger SHALL record the effective AC used

#### Scenario: Cover is invalid, stale, inactive, or absent
- **WHEN** the target has no valid cover reference, the referenced feature is malformed or stale, or its encounter is not currently active and in progress
- **THEN** the attack SHALL use the existing base-AC behavior without a cover bonus
- **AND** Python SHALL record a bounded cover diagnostic when tracing is enabled

#### Scenario: Attack range is derived from authored action data
- **WHEN** an authored action includes explicit range/type data or an unambiguous weapon name
- **THEN** Python SHALL use that data to classify the attack as ranged or melee for cover lifetime
- **AND** absent or ambiguous classification SHALL default to melee

#### Scenario: G5T Goblin Shortbow remains ranged for cover retention

- **WHEN** the G5T Goblin uses its authored Shortbow action
- **THEN** its action data SHALL declare `attackType=ranged` and normal/long ranges of 80/320 feet
- **AND** the Goblin's explicit multiattack declaration SHALL select that Shortbow action
- **AND** a covered Goblin's applied Shortbow attack SHALL retain its valid cover reference for the next batch

#### Scenario: G5T Captain Javelin is explicitly ranged

- **WHEN** the G5T Hobgoblin Captain uses its authored Javelin multiattack
- **THEN** the action data SHALL declare the thrown attack as ranged with normal/long ranges of 30/120 feet
- **AND** its projected attack options SHALL be marked `cover_compatible=true`
- **AND** its authored Longsword attack SHALL remain incompatible with combining attacks and cover
