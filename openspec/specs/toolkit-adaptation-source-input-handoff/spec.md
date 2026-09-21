# toolkit-adaptation-source-input-handoff Specification

## Purpose
Defines the Python-owned handoff that makes uploaded adventures and text descriptions equivalent bounded inputs to the completed adaptation authoring and staged ModuleBuilder contracts.

## Requirements

### Requirement: Both input types produce bounded source context

The runtime SHALL convert an approved uploaded adventure or a submitted text description into bounded source context containing a stable source identity, source kind, source profile evidence, rights metadata, and attempt identity before provider authoring begins.

#### Scenario: Uploaded Markdown or PDF context

- **WHEN** an upload has passed its existing intake and review requirements
- **THEN** Python SHALL provide the adaptation author with a bounded digest/context representation
- **AND** SHALL preserve the original source hash and source kind without sending unbounded raw source

#### Scenario: Text description context

- **WHEN** a text-description build is accepted
- **THEN** Python SHALL compute a source identity and bounded source context from the submitted description
- **AND** SHALL classify the input as user-authored without requiring the LLM to infer ownership

### Requirement: Rights metadata is Python-owned

The runtime SHALL pass the supplied rights classification and review state into adaptation authoring and SHALL reject provider attempts to change those values.

#### Scenario: User-authored input

- **WHEN** an upload or text description is classified as `user_authored`
- **THEN** Python SHALL pass the corresponding non-pending review state to the author request
- **AND** the dossier identity SHALL retain that classification

#### Scenario: Restricted source

- **WHEN** an input is classified as third-party copyright restricted or requires operator review
- **THEN** the runtime SHALL preserve the review requirement
- **AND** SHALL prevent a provider response from making the source build-ready by changing the rights fields

### Requirement: Authoring precedes ModuleBuilder

The runtime SHALL obtain and Python-validate a build-ready adaptation dossier before reserving a final adaptation build target or invoking ModuleBuilder.

#### Scenario: Valid dossier handoff

- **WHEN** the adaptation author returns a schema-valid build-ready dossier with matching source and rights identity
- **THEN** Python SHALL persist the attempt-scoped dossier/provenance artifacts
- **AND** SHALL pass the validated dossier into staged ModuleBuilder execution

#### Scenario: Invalid dossier handoff

- **WHEN** the author response is malformed, identity-mismatched, non-build-ready, or exceeds bounds
- **THEN** the runtime SHALL stop before ModuleBuilder execution
- **AND** SHALL retain bounded attempt diagnostics without creating a completed module

### Requirement: World context remains read-only

The input handoff SHALL carry only the completed scaffold's bounded world-context provenance and SHALL not expose direct campaign, registry, mechanical, or arbitrary file-write operations to the provider.

#### Scenario: Unavailable world context

- **WHEN** approved world context is unavailable
- **THEN** authoring SHALL receive an explicit unavailable/fallback provenance status
- **AND** SHALL not claim world-seed grounding
