## Purpose

Gate builder blueprint generation and handoff on final normalization fidelity status so blocked/failed fidelity states cannot silently enter the build path.

## Requirements

### Requirement: Blueprint handoff SHALL be gated by final normalization fidelity status

Accurate-ingest blueprint generation and builder handoff SHALL refuse final normalization states that are blocked, failed, or unverifiable for required source truth.

#### Scenario: Clean fidelity allows blueprint generation

- **GIVEN** `normalization_fidelity_report.json` exists
- **AND** final fidelity status is clean or repaired with no remaining blocking findings
- **WHEN** blueprint fidelity precheck runs
- **THEN** blueprint generation SHALL be allowed.

#### Scenario: Blocked fidelity refuses blueprint generation

- **GIVEN** final fidelity status is blocked or failed
- **WHEN** blueprint fidelity precheck runs
- **THEN** blueprint generation SHALL be refused
- **AND** `builder_blueprint_report.json` SHALL include the fidelity refusal reason.

#### Scenario: Missing source artifacts refuse accurate-ingest blueprint mode

- **GIVEN** `normalized_packet.json` exists
- **AND** source graph, identity, topology, or fidelity artifacts required for blueprint generation are missing
- **WHEN** accurate-ingest blueprint precheck runs
- **THEN** blueprint generation SHALL be refused
- **AND** the report SHALL NOT claim source-blueprint readiness.

### Requirement: Degraded fidelity SHALL be handled explicitly

Degraded fidelity SHALL not be treated as clean by default.

#### Scenario: Degraded without blockers may proceed with warnings

- **GIVEN** final fidelity status is degraded
- **AND** no required source blockers remain
- **WHEN** blueprint precheck runs
- **THEN** blueprint generation MAY proceed
- **AND** the blueprint report SHALL preserve degradation warnings.

#### Scenario: Degraded with required blocker refuses generation

- **GIVEN** final fidelity status is degraded
- **AND** required source blockers remain
- **WHEN** blueprint precheck runs
- **THEN** blueprint generation SHALL be refused.

### Requirement: Fidelity precheck SHALL preserve legacy fallback boundaries

Fidelity precheck SHALL distinguish accurate-ingest blueprint mode from legacy builder mode.

#### Scenario: Legacy mode bypasses blueprint requirement

- **GIVEN** accurate-ingest blueprint handoff is disabled
- **AND** a workspace lacks fidelity artifacts
- **WHEN** legacy builder handoff runs
- **THEN** the absence of blueprint artifacts SHALL NOT break legacy behavior
- **AND** no source-blueprint readiness SHALL be claimed.
