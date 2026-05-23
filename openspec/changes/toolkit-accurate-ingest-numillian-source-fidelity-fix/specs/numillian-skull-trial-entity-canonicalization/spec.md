## ADDED Requirements

### Requirement: Skull trial entities SHALL be preserved as canonical NPCs

The generated module SHALL preserve the three skull trial entities as source-faithful non-combat scene/puzzle actors.

#### Scenario: Red Skull is preserved as canon NPC

- **GIVEN** source markdown describes `Red Skull` as a speaking skull in the First Trial
- **WHEN** the module is generated
- **THEN** `module_context.json` SHALL contain a `red_skull` NPC entry with `name: "Red Skull"`.
- **AND** the entry SHALL NOT be converted into a hostile combat monster.

#### Scenario: Blue Skull is preserved as canon NPC

- **GIVEN** source markdown describes `Blue Skull` as a speaking skull in the First Trial
- **WHEN** the module is generated
- **THEN** `module_context.json` SHALL contain a `blue_skull` NPC entry with `name: "Blue Skull"`.

#### Scenario: Yellow Skull is preserved as canon NPC

- **GIVEN** source markdown describes `Yellow Skull` as a speaking skull in the First Trial
- **WHEN** the module is generated
- **THEN** `module_context.json` SHALL contain a `yellow_skull` NPC entry with `name: "Yellow Skull"`.

#### Scenario: Skull NPCs are not combat monsters

- **GIVEN** the three skulls are puzzle/scene actors
- **WHEN** the seed writer or monster generator processes encounter data
- **THEN** the skulls SHALL NOT be emitted as hostile monster entries with combat stats
- **AND** they MAY appear as non-hostile scene actors in location NPC lists.

### Requirement: Skull role and source context SHALL be preserved

Each skull NPC SHALL carry a source-derived role string reflecting its behavior in the First Trial.

#### Scenario: Red Skull role reflects speaking skull

- **GIVEN** source markdown includes `Red Skull: "My coins were earned by others."`
- **WHEN** `module_context.json` is generated
- **THEN** the `red_skull` NPC entry SHALL have `role` containing the speaking skull description.

#### Scenario: Blue Skull role reflects speaking skull

- **GIVEN** source markdown includes `Blue Skull: "Every day I watched the fools perform."`
- **WHEN** `module_context.json` is generated
- **THEN** the `blue_skull` NPC entry SHALL have `role` containing the speaking skull description.

#### Scenario: Yellow Skull role reflects speaking skull

- **GIVEN** source markdown includes `Yellow Skull: "I must ask rather than demand."`
- **WHEN** `module_context.json` is generated
- **THEN** the `yellow_skull` NPC entry SHALL have `role` containing the speaking skull description.
