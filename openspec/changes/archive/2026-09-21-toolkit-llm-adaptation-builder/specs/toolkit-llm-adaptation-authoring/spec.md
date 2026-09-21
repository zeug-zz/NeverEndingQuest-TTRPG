## Purpose

Defines how readable source material is interpreted into a bounded NEQ-TTRPG adaptation dossier that ModuleBuilder can use without requiring literal source-atom preservation.

## ADDED Requirements

### Requirement: Adaptation selects a playable source profile

The adaptation author MUST classify readable source material into a playable profile such as adventure, catalogue, location, lore, encounter, or sandbox before producing the dossier.

#### Scenario: Catalogue source

- **WHEN** a source is primarily an item catalogue without room structure
- **THEN** the dossier uses a catalogue or shop profile and does not promote every item heading to a location

#### Scenario: Adventure source

- **WHEN** a source contains an adventure premise and progression
- **THEN** the dossier uses an adventure profile with an adapted premise, progression, and starting context

### Requirement: Adaptation emits a versioned dossier

The adaptation author MUST return strict JSON containing a version, adapted title, source hash, source profile, level range, starting location, playable content seeds, retained elements, omitted elements, original adaptation elements, assumptions, warnings, and rights metadata.

#### Scenario: Valid dossier

- **WHEN** the provider returns a complete adaptation response
- **THEN** the response can be parsed and persisted as an attempt-scoped adaptation dossier

#### Scenario: Invalid dossier

- **WHEN** the provider returns malformed JSON or omits required dossier fields
- **THEN** the adaptation attempt fails closed with structured diagnostics and no ModuleBuilder publication starts

### Requirement: Adaptation separates source evidence from creative additions

The dossier MUST distinguish retained source elements, intentionally omitted source elements, and original NEQ adaptation elements.

#### Scenario: Intentional omission

- **WHEN** the author omits a source element because it does not fit the selected playable profile
- **THEN** the omission is recorded and is not reported as a source-fidelity error

#### Scenario: Original connective material

- **WHEN** the author adds an NEQ hook, faction, NPC, or plot connection
- **THEN** the addition is marked as original adaptation content

### Requirement: ModuleBuilder receives adaptation context without source locks

The build handoff MUST provide the adaptation dossier and bounded context to ModuleBuilder while treating source candidates as non-mandatory evidence.

#### Scenario: Item catalogue handoff

- **WHEN** a catalogue dossier is handed to ModuleBuilder
- **THEN** ModuleBuilder can create a coherent shop or location module without materializing all source headings as rooms

#### Scenario: Legacy accurate-ingest handoff

- **WHEN** a job explicitly selects legacy accurate-ingest mode
- **THEN** the existing source-locked handoff remains available and adaptation behavior is not silently applied
