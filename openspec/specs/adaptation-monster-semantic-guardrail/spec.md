# adaptation-monster-semantic-guardrail Specification

## Purpose
Ensure LLM adaptation builds distinguish canonical monster identities from encounter prose, NPCs, allies, and other narrative content before structural monster validation or materialization, while allowing bounded stat completion for identities Python has already approved.

## Requirements

### Requirement: Adaptation Monster References Are Canonicalized

An `llm_adaptation` build SHALL normalize each generated location monster entry against bounded canonical monster vocabulary before monster closure runs.

#### Scenario: Descriptive creature phrase maps unambiguously

- **WHEN** a location monster entry contains a quantity and descriptive suffix that unambiguously identifies a canonical creature
- **THEN** the structural monster reference SHALL use the canonical creature identity
- **AND** the original descriptive information SHALL remain available in authored encounter or location narrative content

#### Scenario: NPC or ally phrase is not materialized as a monster

- **WHEN** a location monster entry identifies an NPC, ally, worker, or other non-monster scene entity without explicit canonical monster evidence
- **THEN** the entry SHALL NOT be sent to monster stat-block materialization
- **AND** the result SHALL record its non-monster classification or unresolved diagnostic

#### Scenario: Ambiguous phrase cannot be safely mapped

- **WHEN** a location monster entry cannot be deterministically mapped to one canonical monster identity
- **THEN** the adaptation monster guardrail SHALL record the original entry and source location
- **AND** the build SHALL not invent or silently substitute a monster identity

### Requirement: Adaptation References Bind To Encounter Seeds

The adaptation guardrail SHALL report whether canonical source adversaries resolve to schema-sufficient monster artifacts and whether encounter seeds bind to those references.

#### Scenario: Source adversary resolves and binds

- **WHEN** an adaptation encounter seed names a canonical adversary with a schema-sufficient artifact
- **THEN** the guardrail report SHALL mark the adversary as resolved
- **AND** the encounter seed SHALL be marked bound to that artifact

#### Scenario: Source adversary remains unresolved

- **WHEN** an adaptation encounter seed contains an adversary that cannot be safely resolved
- **THEN** the guardrail report SHALL list the unresolved adversary and encounter seed
- **AND** the build SHALL fail with a concrete semantic monster reference diagnostic

### Requirement: Approved Canonical Identities May Receive Bounded LLM Mechanics

The adaptation guardrail SHALL invoke the existing Module Builder LLM only to generate a stat block for a canonical identity already approved by deterministic dossier, source, or normalization evidence, and MAY omit generation when the active policy disallows it.

#### Scenario: Approved canonical monster has no reusable stat block

- **WHEN** an approved canonical monster has no schema-sufficient staging, reusable, or compendium artifact and the current adaptation policy permits generation
- **THEN** the LLM MAY generate mechanics for that identity using bounded source/encounter context and available 5e SRD exemplar guidance
- **AND** Python SHALL verify the returned stat block before closure
- **AND** the LLM SHALL not rename, substitute, or add another monster identity

#### Scenario: Provider proposes an unapproved identity

- **WHEN** generated output introduces a monster identity that was not in the approved canonical reference set
- **THEN** Python SHALL reject the identity
- **AND** the rejected identity SHALL not be written or sent to generic closure

### Requirement: Legacy Builds Are Isolated

The adaptation semantic guardrail SHALL apply only to `llm_adaptation` builds.

#### Scenario: Legacy module build runs

- **WHEN** a non-adaptation ModuleBuilder build executes
- **THEN** the existing legacy monster closure behavior SHALL remain available
- **AND** no adaptation guardrail report SHALL be required for success
