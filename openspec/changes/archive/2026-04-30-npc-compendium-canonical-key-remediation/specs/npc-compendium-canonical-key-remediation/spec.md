# NPC Compendium Canonical Key Remediation

## Purpose

Define an operator-safe remediation workflow for existing descriptive NPC keys in `data/bestiary/npc_compendium.json`, using the canonical identity helper introduced by the toolkit NPC identity boundary fix.

## ADDED Requirements

### Requirement: Remediation MUST default to dry run

The remediation command MUST produce a planned-change report without mutating the compendium unless the operator explicitly passes `--apply`.

#### Scenario: Dry run reports changes without writes

- **GIVEN** a compendium fixture containing `arannis,_vault_scholar_and_alarmed_archivist`
- **WHEN** the operator runs the remediation command without `--apply`
- **THEN** the command MUST report a planned merge to `arannis`
- **AND** the fixture file MUST remain byte-for-byte unchanged

### Requirement: Descriptive NPC keys MUST merge into canonical identity keys

Entries whose key or name canonicalizes to a shorter identity key MUST be merged into that canonical entry.

#### Scenario: Numillian descriptive keys collapse to canonical keys

- **GIVEN** entries for `arannis,_vault_scholar_and_alarmed_archivist`, `elaris,_a_diplomat_of_the_secrecy_council`, `ilyra,_wardkeeper_adjudicator`, and `letharel,_the_silent_border_warden`
- **WHEN** remediation is applied
- **THEN** the resulting compendium MUST contain canonical keys `arannis`, `elaris`, `ilyra`, and `letharel`
- **AND** the descriptive legacy keys MUST not remain as top-level NPC keys after successful merge

### Requirement: Duplicate variants MUST merge under one canonical key

Multiple descriptive entries that canonicalize to the same NPC identity MUST merge into one canonical entry.

#### Scenario: Kobe variants merge deterministically

- **GIVEN** entries for `kobe,_a_guarded_resident_tied_to_the_vault`, `kobe,_endangered_key_witness`, and `kobe,_the_life_at_the_center_of_the_crisis`
- **WHEN** remediation is applied
- **THEN** the resulting compendium MUST contain one `kobe` entry
- **AND** every legacy key MUST be preserved in metadata
- **AND** role hints from each variant MUST be preserved in metadata

### Requirement: Merge MUST preserve descriptions and identity metadata

When legacy entries merge into a canonical entry, remediation MUST preserve source labels, source IDs, role hints, legacy IDs, and non-selected descriptions.

#### Scenario: Conflicting descriptions are not discarded

- **GIVEN** two entries that canonicalize to `kobe` and have different non-empty descriptions
- **WHEN** remediation is applied
- **THEN** one description MUST become the canonical description by deterministic precedence
- **AND** the other non-empty description MUST be preserved in alternate-description metadata

### Requirement: Apply mode MUST be atomic and auditable

When `--apply` is used, remediation MUST write safely and produce an audit trail.

#### Scenario: Applied remediation writes backup and report

- **GIVEN** a writable compendium file with descriptive keys
- **WHEN** the operator runs remediation with `--apply`
- **THEN** the command MUST create a backup or audit artifact before replacing the compendium
- **AND** the replacement MUST use atomic JSON write behavior
- **AND** the report MUST include legacy key to canonical key mappings

### Requirement: Remediation MUST remain opt-in

The application MUST NOT run compendium key remediation automatically during startup, toolkit listing, or asset generation.

#### Scenario: Runtime startup is unchanged

- **GIVEN** the remediation script exists
- **WHEN** the web app starts or toolkit routes execute
- **THEN** remediation MUST NOT run unless the operator invokes the script explicitly

### Requirement: Monster compendium MUST remain out of scope

The remediation script MUST NOT mutate `data/bestiary/monster_compendium.json` or monster normalization helpers.

#### Scenario: Monster compendium is untouched

- **GIVEN** the remediation command is run in dry-run or apply mode
- **WHEN** it selects input files
- **THEN** it MUST only target the configured NPC compendium path
- **AND** it MUST NOT read or write `monster_compendium.json`
