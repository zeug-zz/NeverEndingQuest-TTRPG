# Toolkit NPC Identity Canonicalization

## Purpose

Ensure toolkit/module-builder NPC extraction and description persistence use clean canonical NPC identities for durable IDs while preserving descriptive source labels as metadata.

## ADDED Requirements

### Requirement: Canonical NPC slugs MUST exclude appositive descriptions

Toolkit NPC identity normalization MUST derive durable NPC slugs from the clean identity only when a display label contains a comma-separated appositive description.

#### Scenario: Named NPC with role appositive

- **GIVEN** the authored NPC label `Arannis, vault scholar and alarmed archivist`
- **WHEN** the toolkit derives a durable NPC ID
- **THEN** the ID MUST be `arannis`
- **AND** the role/appositive text MUST NOT appear in the ID.

### Requirement: Source labels MUST be preserved as metadata

When canonicalization removes descriptive text from a durable ID, the original label MUST be preserved as additive metadata on extracted NPC payloads and compendium entries.

#### Scenario: Preserving descriptive label

- **GIVEN** the authored NPC label `Elaris, a diplomat of the Secrecy Council`
- **WHEN** the toolkit stores the NPC description in the compendium
- **THEN** the compendium entry MUST be keyed by `elaris`
- **AND** the entry MUST retain the source label or equivalent metadata.

### Requirement: Duplicate variants MUST merge under one canonical key

Repeated variants of a single named NPC MUST write to the same canonical compendium key and accumulate source labels rather than create duplicate descriptive keys.

#### Scenario: Kobe variants

- **GIVEN** labels `Kobe, guarded resident tied to the vault` and `Kobe, endangered key witness`
- **WHEN** both are processed by toolkit NPC persistence
- **THEN** both MUST resolve to the canonical key `kobe`
- **AND** both source labels MUST remain auditable in metadata.

### Requirement: Legacy descriptive IDs MUST remain readable

Manual or asynchronous toolkit requests that pass a legacy descriptive NPC ID MUST be canonicalized before lookup and write operations.

#### Scenario: Legacy GET request

- **GIVEN** a request for NPC ID `arannis,_vault_scholar_and_alarmed_archivist`
- **WHEN** the manual description endpoint looks up the NPC description
- **THEN** it MUST also check the canonical key `arannis`.

### Requirement: Monster normalization MUST remain unchanged

The NPC identity change MUST NOT alter monster/bestiary normalization helpers used by LLM classification.

#### Scenario: Monster classifier helper

- **GIVEN** a monster classification path using `_normalize_name_for_bestiary`
- **WHEN** NPC identity canonicalization is implemented
- **THEN** the monster helper behavior MUST remain unchanged.
