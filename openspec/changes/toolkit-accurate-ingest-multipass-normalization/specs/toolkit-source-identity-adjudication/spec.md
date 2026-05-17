## ADDED Requirements

### Requirement: Source identity adjudication SHALL preserve original names and aliases

Readable-source multipass normalization SHALL convert mechanical candidates and section facts into canonical identities without losing original source display names.

#### Scenario: Canonical identity preserves display name

- **GIVEN** a named NPC or location appears in a table, heading, bold span, or section extraction
- **WHEN** identity adjudication creates a canonical identity
- **THEN** the canonical identity SHALL preserve the original display name
- **AND** aliases SHALL be stored separately from the display name.

#### Scenario: Alias merge requires evidence

- **GIVEN** two names may refer to the same entity
- **WHEN** identity adjudication considers merging them
- **THEN** the merge SHALL include evidence references explaining the decision
- **AND** it SHALL NOT merge solely because the names are superficially similar.

### Requirement: Ambiguous identity merges SHALL be reviewable

Ambiguous identity decisions SHALL be surfaced rather than silently resolved.

#### Scenario: Ambiguous merge is not silently applied

- **GIVEN** two candidates have insufficient evidence for a confident merge
- **WHEN** identity adjudication runs
- **THEN** the report SHALL list the merge as ambiguous or unresolved
- **AND** both source identities SHALL remain available for downstream review.

#### Scenario: Duplicate evidence is retained

- **GIVEN** a canonical identity is supported by multiple source refs
- **WHEN** identity adjudication merges references
- **THEN** the resulting identity SHALL retain the merged evidence refs
- **AND** it SHALL not drop table, heading, or extraction evidence.

### Requirement: Criticality refinement SHALL remain conservative

Identity adjudication SHALL refine criticality without over-promoting weak proper-noun candidates.

#### Scenario: Strong evidence can promote source-critical identity

- **GIVEN** a named entity appears in a map key, NPC table, quest text, dialogue, or puzzle/plot section
- **WHEN** criticality is refined
- **THEN** the identity MAY become `required` or `major` with evidence.

#### Scenario: Proper-noun-only candidate remains non-required

- **GIVEN** a candidate appears only through broad proper noun matching
- **WHEN** criticality is refined
- **THEN** it SHALL NOT become `required` without additional evidence.
