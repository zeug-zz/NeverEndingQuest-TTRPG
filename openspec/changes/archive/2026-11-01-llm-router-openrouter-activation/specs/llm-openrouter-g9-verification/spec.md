# Spec Delta

## Purpose

Defines bounded, reproducible G9 capture tooling and evidence needed to verify OpenRouter Auto routing, direct-OpenAI recovery, and rollback without confusing provider-free tests with live acceptance.

## ADDED Requirements

### Requirement: G9 tooling extends the existing Capture_Arena path

The existing seeder, socket driver, and evidence evaluator SHALL support a fixed `--gate g9` path without changing the defaults or contracts of existing gates.

#### Scenario: G9 gate selection
- **WHEN** a named capture is invoked with `--gate g9`
- **THEN** the seeder, driver, and evaluator SHALL use G9-specific profiles and evidence rules
- **AND** G3/G4/G5/G7 behavior and defaults SHALL remain unchanged

#### Scenario: Invalid G9 invocation
- **WHEN** a G9 command omits a required scenario, party size, or unique run directory
- **THEN** the command SHALL reject the invocation before starting or changing a server

### Requirement: G9 includes both party shapes and routing outcomes

The G9 live matrix SHALL require narrator and combat Auto captures, controlled fallback, and preferred-model rollback for both 1-PC and 4-PC parties.

#### Scenario: Auto matrix completeness
- **WHEN** the G9 matrix is evaluated
- **THEN** it SHALL contain `narrator-auto:p1`, `narrator-auto:p4`, `combat-auto:p1`, and `combat-auto:p4`
- **AND** each row SHALL observe requested and resolved model plus actual provider when available

#### Scenario: Controlled failure matrix completeness
- **WHEN** the G9 matrix is evaluated
- **THEN** it SHALL contain `transport-failure:p1` and `transport-failure:p4`
- **AND** each row SHALL prove one bounded direct-OpenAI fallback to `gpt-6-luna`

#### Scenario: Rollback matrix completeness
- **WHEN** the G9 matrix is evaluated
- **THEN** it SHALL contain `preferred-openai-rollback:p1` and `preferred-openai-rollback:p4`
- **AND** each rollback row SHALL use exactly one server restart before verifying direct `gpt-6-luna`

### Requirement: G9 evidence records actual model and cost completeness

Every live G9 run SHALL preserve a unique evidence bundle under `tmp/router-rollout/g9/<run-id>/` with response-derived model, provider, and cost observations.

#### Scenario: Accounted response evidence
- **WHEN** a G9 live request receives a response
- **THEN** its evidence SHALL record requested model, resolved model or explicit unknown, transport provider, observed upstream provider or explicit unknown, usage completeness, cost provenance, cost amount when available, and cost completeness
- **AND** reported, verified-estimated, and unpriced costs SHALL remain distinguishable

#### Scenario: Missing cost observation
- **WHEN** the provider supplies no usable cost and no verified resolved-model rate exists
- **THEN** the evidence SHALL retain the call as unpriced and incomplete
- **AND** the evaluator SHALL NOT treat missing cost as zero or infer a static Auto price

### Requirement: G9 evaluation rejects incomplete or contradictory evidence

The offline G9 evaluator SHALL accept only complete, correctly identified live candidate bundles and SHALL report readiness rather than a primary PASS verdict.

#### Scenario: Missing G9 evidence
- **WHEN** a required matrix row, response receipt, model/provider observation, cost provenance, transcript, server log, or required state evidence is missing
- **THEN** evaluation SHALL report the missing evidence and mark the matrix not ready

#### Scenario: Synthetic evidence
- **WHEN** a G9 bundle is produced with fake transport or declared model/provider values instead of live response evidence
- **THEN** evaluation SHALL identify it as synthetic or non-live and SHALL NOT mark the live row ready

#### Scenario: Complete G9 candidate matrix
- **WHEN** all eight required live rows have matching identities and complete required evidence
- **THEN** evaluation MAY report `READY_FOR_PRIMARY_REVIEW`
- **AND** it SHALL NOT emit or imply G9 PASS

### Requirement: G9 live execution is gated by G7 and owned by the primary

G9 live execution SHALL occur only after the primary records G7 PASS; only the primary orchestrator SHALL judge and record the G9 PASS, FAIL, or BLOCKED verdict.

#### Scenario: G7 remains blocked
- **WHEN** the current G7 verdict is BLOCKED or FAIL
- **THEN** no G9 live server run SHALL be started
- **AND** G9 SHALL remain incomplete regardless of provider-free test results

#### Scenario: Primary reviews complete evidence
- **WHEN** the primary reviews the complete live G9 matrix after G7 PASS
- **THEN** the primary SHALL record PASS, FAIL, or BLOCKED with evidence references and a reason in the owning change
- **AND** builder test results or evaluator readiness SHALL NOT be substituted for that verdict

### Requirement: G9 capture remains isolated from installed runtime state

Live G9 captures SHALL use a real sandbox copy under `tmp/combat_capture/`, port 8360, and `NEQ_OPEN_BROWSER=0`; rollout-only flags SHALL remain off outside that sandbox.

#### Scenario: Sandbox and evidence roots
- **WHEN** a primary-owned G9 live capture is prepared and run
- **THEN** it SHALL use only the sandbox on port 8360 and store evidence under the matching G9 run directory
- **AND** it SHALL NOT write to the installed campaign or use port 8357

#### Scenario: Titan task proof
- **WHEN** Titan configuration is verified for G9
- **THEN** verification SHALL use provider-free fake transport
- **AND** no live Titan runtime or scheduler SHALL be created or claimed
