## ADDED Requirements

### Requirement: Readable Homebrew uploads SHALL support section-bounded extraction

Readable Homebrew upload sources routed through accurate-ingest multipass normalization SHALL split source text into bounded extraction units derived from source manifest heading hierarchy and safe chunking rules.

#### Scenario: Section extraction units preserve source context

- **GIVEN** a readable markdown upload has a source manifest with heading hierarchy
- **WHEN** extraction units are built
- **THEN** each extraction unit SHALL include source hash, section ID, heading path, line range, and bounded source text
- **AND** each unit SHALL include mechanical atom hints for atoms whose evidence overlaps that section.

#### Scenario: Section extraction does not receive the whole source by default

- **GIVEN** a source contains multiple top-level or second-level sections
- **WHEN** a section extraction model call is prepared
- **THEN** the prompt payload SHALL include only the selected section or bounded chunk
- **AND** it SHALL NOT include the full source text unless an explicit fallback mode is recorded.

### Requirement: Section facts SHALL be evidence-backed

Section extraction SHALL produce facts only when they can be tied to source evidence.

#### Scenario: Extracted fact includes source evidence

- **GIVEN** a section contains an NPC, location, clue, puzzle rule, or plot beat
- **WHEN** section extraction captures that fact
- **THEN** the fact SHALL include a source reference or source atom reference
- **AND** the fact SHALL include a bounded source excerpt or line range when available.

#### Scenario: Uncertain fact is marked ambiguous

- **GIVEN** the model cannot determine whether a candidate is an NPC, location, clue, or flavor term
- **WHEN** it emits an extraction result
- **THEN** the result SHALL mark the fact as `ambiguous`
- **AND** it SHALL NOT promote the fact to required source truth.

### Requirement: Section extraction SHALL degrade per section

Provider or parse failure for one extraction unit SHALL NOT discard all extraction work.

#### Scenario: One section provider call fails

- **GIVEN** multiple extraction units exist
- **AND** one section extraction provider call fails
- **WHEN** extraction completes
- **THEN** successful section artifacts SHALL remain available
- **AND** the failed section SHALL be recorded with degraded status
- **AND** source graph generation SHALL NOT be marked fully successful for that section.

#### Scenario: Malformed section output is rejected safely

- **GIVEN** a model returns prose or malformed JSON for a section
- **WHEN** the output is parsed
- **THEN** the section SHALL be marked degraded
- **AND** the pipeline SHALL preserve prior mechanical source graph artifacts.
