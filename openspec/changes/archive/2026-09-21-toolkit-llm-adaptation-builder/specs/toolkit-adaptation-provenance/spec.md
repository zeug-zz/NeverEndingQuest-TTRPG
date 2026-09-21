## Purpose

Defines the provenance, rights classification, adaptation status, and attribution metadata required to distinguish an NEQ adaptation from literal source-fidelity output.

## ADDED Requirements

### Requirement: Adaptation provenance is persisted

Every adaptation attempt MUST persist the source title, source hash, rights classification, adaptation mode, attempt identity, timestamp, model metadata, and final adaptation status.

#### Scenario: Successful adaptation provenance

- **WHEN** an adapted module completes publication
- **THEN** its module metadata and adaptation report contain the source and adaptation provenance fields

#### Scenario: Failed adaptation provenance

- **WHEN** an adaptation fails before publication
- **THEN** the attempt workspace retains failure provenance without creating a completed module record

### Requirement: Adaptation notice is explicit

Completed adapted modules and their readable Markdown credits MUST include the exact notice `Adapted for NEQ-TTRPG`.

#### Scenario: Notice in module metadata

- **WHEN** a completed module is inspected
- **THEN** its adaptation metadata contains the required notice

#### Scenario: Notice in Markdown credits

- **WHEN** a completed adventure summary is downloaded
- **THEN** its credits contain the required notice

### Requirement: Source fidelity is not misrepresented

Adaptation reports MUST identify literal source fidelity as not applicable or informational and MUST NOT claim a clean source-fidelity pass merely because the adapted module is playable.

#### Scenario: Playable adaptation with omissions

- **WHEN** an adapted module intentionally omits or reinterprets source material and passes publication gates
- **THEN** publication succeeds with an adaptation status and an honest non-literal source-fidelity claim

#### Scenario: False fidelity claim

- **WHEN** an LLM response claims literal source fidelity without evidence of that contract
- **THEN** Python rejects or normalizes the claim before publication reporting

### Requirement: Rights policy can block publication

The adaptation pipeline MUST preserve the upload rights classification and MUST block publication when policy requires rights review and no acceptable classification is present.

#### Scenario: Accepted user-authored source

- **WHEN** the source has an accepted user-authored or otherwise permitted rights classification
- **THEN** adaptation may proceed and records that classification

#### Scenario: Missing rights classification

- **WHEN** the source rights classification is required but unavailable
- **THEN** the adaptation remains blocked and no registry entry is created
