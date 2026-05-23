## ADDED Requirements

### Requirement: Build fidelity canonicalization SHALL strip trailing markdown punctuation

The `_normalize_name()` helper in `utils/toolkit_build_fidelity.py` SHALL strip common trailing markdown and table punctuation before comparing atom names against generated module entity names.

#### Scenario: Trailing colon is stripped

- **GIVEN** a source atom with `name: "Red Skull:"`
- **WHEN** `_normalize_name("Red Skull:")` is called
- **THEN** the result SHALL equal `_normalize_name("Red Skull")`.

#### Scenario: Trailing semicolon is stripped

- **GIVEN** a source atom with `name: "Caretaker Noll;"`
- **WHEN** `_normalize_name("Caretaker Noll;")` is called
- **THEN** the result SHALL equal `_normalize_name("Caretaker Noll")`.

#### Scenario: Trailing period is stripped

- **GIVEN** a source atom with `name: "Sister Mara."`
- **WHEN** `_normalize_name("Sister Mara.")` is called
- **THEN** the result SHALL equal `_normalize_name("Sister Mara")`.

#### Scenario: Multiple punctuation chars are all stripped

- **GIVEN** a source atom with `name: "The Guard!:"`
- **WHEN** `_normalize_name("The Guard!:")` is called
- **THEN** the result SHALL equal `_normalize_name("The Guard")`.

### Requirement: Punctuation normalization SHALL NOT collapse distinct names

The punctuation stripping SHALL be narrow and SHALL NOT cause distinct canonical names to become equal when they differ by meaningful content.

#### Scenario: Distinct compound names remain distinct

- **GIVEN** the names `"The Caretaker"` and `"The Caretaker / Procul"`
- **WHEN** both are normalized
- **THEN** the normalized values SHALL be different from each other.

#### Scenario: Names differing by slash remain distinct

- **GIVEN** the names `"Red Skull:"` and `"Red Skull (Wiseman)"`
- **WHEN** both are normalized
- **THEN** the normalized values SHALL be different.

### Requirement: Existing build-fidelity tests SHALL continue to pass

The punctuation normalization SHALL be additive. All existing fixture-based and behavioral build-fidelity tests SHALL continue to pass without modification.

#### Scenario: Caretaker Noll still matches

- **GIVEN** the existing `_write_base_accurate_workspace()` fixture with `"Caretaker Noll"`
- **WHEN** build-fidelity tests run
- **THEN** all existing assertions about Caretaker Noll presence SHALL pass
- **AND** no test fixture changes SHALL be required.

### Requirement: The three skull blocker entries from build-fidelity report SHALL produce clear diagnostic text

When the `Required npc 'Red Skull:'...` blocker appears, the colon in the refusal message SHALL be recognisable as source punctuation rather than sentence-ending punctuation.

#### Scenario: Refusal text for colon-bearing source atoms is distinguishable

- **GIVEN** a build-fidelity report with `Required npc 'Red Skull:'` in the refusal_reason
- **WHEN** the report is inspected
- **THEN** the trailing colon SHALL be identifiable as part of the source atom name, not sentence punctuation.
