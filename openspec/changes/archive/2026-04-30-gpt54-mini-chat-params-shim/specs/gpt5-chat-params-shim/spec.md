# GPT-5 Chat Params Shim

## Purpose

Define a short-term Chat Completions parameter shim that lets GPT-5.4-mini gametest paths use GPT-5-style controls without broad router migration or legacy parameter sprawl.

## ADDED Requirements

### Requirement: Central Helper

The system SHALL provide a central helper for constructing task-aware Chat Completions parameter dictionaries.

#### Scenario: Helper returns spreadable params

- **GIVEN** a caller requests chat parameters for a task id
- **WHEN** the helper returns
- **THEN** the result SHALL be a flat dictionary suitable for `client.chat.completions.create(**params, messages=...)`
- **AND** the result SHALL include `model`

### Requirement: GPT-5 Legacy Sampling Omission

For GPT-5-style models, the helper SHALL omit legacy sampling controls by default.

#### Scenario: GPT-5-style model uses reasoning controls

- **GIVEN** the resolved model name begins with `gpt-5`
- **WHEN** chat parameters are built
- **THEN** the result SHALL include `reasoning_effort`
- **AND** the result SHALL include `verbosity`
- **AND** the result SHALL NOT include `temperature`
- **AND** the result SHALL NOT include `top_p`

### Requirement: Legacy Model Compatibility

For non-GPT-5 models, the helper SHALL preserve existing legacy temperature behavior.

#### Scenario: GPT-4-style model uses task temperature

- **GIVEN** the resolved model name does not begin with `gpt-5`
- **WHEN** chat parameters are built for a known task id
- **THEN** the result SHALL include the legacy task temperature
- **AND** the result SHALL NOT include GPT-5-only reasoning fields

### Requirement: Rollback Flag Default

The GPT-5 legacy-temperature rollback flag SHALL default to disabled.

#### Scenario: Default rollback setting

- **GIVEN** no operator override is applied
- **WHEN** GPT-5-style chat parameters are built
- **THEN** legacy `temperature` SHALL remain absent

#### Scenario: Explicit rollback setting

- **GIVEN** the rollback flag is explicitly enabled
- **WHEN** GPT-5-style chat parameters are built
- **THEN** the helper MAY include legacy `temperature`
- **AND** the helper SHALL still NOT include `top_p` unless a future change explicitly adds that behavior

### Requirement: Router Non-Interference

The shim SHALL NOT implement or replace the planned v2 provider/model-agnostic router.

#### Scenario: Router plan remains authoritative

- **GIVEN** this shim is implemented
- **WHEN** future router work begins
- **THEN** the shim SHALL be removable or absorbable into model profiles without changing gameplay contracts
- **AND** this shim SHALL NOT introduce a second high-level `llm.call()` abstraction

### Requirement: Limited Adoption Scope

The change SHALL limit call-site adoption to high-value gametest paths unless separately approved.

#### Scenario: Broad call-site migration is deferred

- **GIVEN** many direct Chat Completions call sites remain in the repository
- **WHEN** this change is implemented
- **THEN** low-traffic direct call sites MAY remain unchanged
- **AND** unchanged call sites SHALL be documented as deferred to the v2 router migration
