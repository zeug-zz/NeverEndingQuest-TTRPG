## Purpose

Define one Python-owned canonical monster identity registry for adaptation references, while keeping quantity and scene manifestation semantics independent from filenames and stat-block identity.

## ADDED Requirements

### Requirement: Canonical registry is shared across adaptation stages

An adaptation build MUST construct one bounded canonical monster registry before closure and MUST use the same registry for location normalization, reusable-artifact lookup, materialization, identity verification, encounter binding, failure packets, and revision validation.

#### Scenario: Existing canonical identity resolves a group label

- **WHEN** the approved registry contains `Cave Guardian` and a source/location reference is `Cave guardians`
- **THEN** the reference MUST resolve to canonical identity `Cave Guardian`
- **AND** the raw label and source evidence MUST remain available in bounded provenance

### Requirement: Quantity is not identity

Structured quantity MUST be stored and validated independently from canonical monster identity and MUST NOT influence the canonical filename or stat-block slug.

#### Scenario: Amphail quantities remain stable

- **WHEN** the Amphail fixture contains K06 quantity `1`, K08 quantity `1`, and RTR001/K10 quantity `2`
- **THEN** those quantities MUST remain `1`, `1`, and `2` respectively after canonicalization
- **AND** no quantity-qualified or plural duplicate stat file may be generated

### Requirement: Canonical matching is bounded and source-grounded

Plural, group, and equivalent labels MAY map to one canonical identity only when that identity exists in the approved source/dossier/module registry or is already approved by Python. Ambiguous labels MUST remain unresolved and MUST NOT create a guessed identity.

#### Scenario: No plural duplicate artifact

- **WHEN** `Cave guardians` matches reusable `monsters/cave_guardian.json`
- **THEN** the reusable canonical artifact MUST be used
- **AND** `cave_guardians.json` MUST NOT be created

#### Scenario: Unsafe or ambiguous label

- **WHEN** a reference has no unique approved canonical identity
- **THEN** it MUST remain a bounded unresolved content diagnostic
- **AND** it MUST NOT be sent to blind legacy generation

### Requirement: Encounter binding uses the registry

Encounter seeds MUST bind through the same canonical registry rather than raw slug equality alone.

#### Scenario: Mixed wording binds consistently

- **WHEN** encounter seeds use singular, plural, or group wording for one approved identity
- **THEN** all safely matching seeds MUST bind to the same canonical artifact
- **AND** the report MUST retain raw wording and bound quantity data
