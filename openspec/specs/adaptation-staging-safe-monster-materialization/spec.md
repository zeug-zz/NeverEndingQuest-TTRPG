# adaptation-staging-safe-monster-materialization Specification

## Purpose
Ensure adaptation monster artifacts are reused, generated, validated, and reported inside the reserved staging tree without writing live module files before publication succeeds.

## Requirements

### Requirement: Adaptation Materialization Is Staging-Local

All monster artifacts created or copied during an adaptation build SHALL be written under the active adaptation staging directory.

#### Scenario: Canonical monster is generated during adaptation

- **WHEN** a canonical adaptation monster has no reusable schema-sufficient artifact and generation is explicitly allowed
- **THEN** the generated JSON SHALL be written under the staging directory
- **AND** the artifact SHALL be verified at its staging path before closure succeeds
- **AND** no file SHALL be written to `modules/<module_slug>/` as a side effect

#### Scenario: Adaptation build fails before publication

- **WHEN** an adaptation build fails during monster guardrail, closure, or readiness validation
- **THEN** the live module directory SHALL not contain monster artifacts created by that failed attempt

### Requirement: Materialization Is Reuse-First And Schema-Safe

Adaptation materialization SHALL prefer schema-sufficient existing module, reusable, or compendium artifacts before provider generation.

#### Scenario: Reusable artifact is available

- **WHEN** a canonical monster identity maps to a schema-sufficient reusable artifact
- **THEN** the artifact SHALL be copied or reused in staging
- **AND** the report SHALL identify the source as reused rather than generated

#### Scenario: Materialized artifact is incomplete

- **WHEN** a candidate monster artifact lacks required monster fields
- **THEN** it SHALL not count as resolved
- **AND** the report SHALL identify the missing or invalid artifact condition

#### Scenario: Exact reusable artifact is beyond the normal candidate budget

- **WHEN** an exact canonical reusable filename exists in a later supplied reusable root
- **THEN** materialization SHALL consider that exact match before applying any bounded diagnostic or scan budget
- **AND** the report SHALL identify the artifact as reused

#### Scenario: Reusable artifact uses a descriptive filename

- **WHEN** a reusable JSON filename contains quantity or descriptive text but its payload carries the exact canonical monster name
- **THEN** materialization SHALL be allowed to copy that payload into the canonical staging filename
- **AND** the copied artifact SHALL be schema-verified before closure

### Requirement: Canonical Stat Completion Is Bounded And Staging-Local

Provider-backed generation SHALL be available only for an already-approved canonical identity when the active adaptation generation policy permits it.

#### Scenario: Canonical stat block is generated from source context

- **WHEN** a canonical identity has no reusable schema-sufficient artifact and generation is enabled for the current building revision
- **THEN** the existing Module Builder LLM SHALL receive bounded source/encounter context and available 5e SRD exemplar guidance
- **AND** the generated artifact SHALL be written only under the active staging directory
- **AND** Python SHALL verify required fields and bounded output before closure

#### Scenario: Generation fails or returns an invalid artifact

- **WHEN** provider generation times out, fails, returns malformed JSON, or omits required fields
- **THEN** the reference SHALL remain unresolved
- **AND** the build result SHALL persist a bounded per-reference generation diagnostic
- **AND** no partial or invalid artifact SHALL satisfy closure

### Requirement: Legacy Materialization Destination Remains Compatible

The explicit output-directory mechanism SHALL be optional for legacy callers.

#### Scenario: Legacy caller omits output directory

- **WHEN** a non-adaptation caller invokes monster generation without an explicit output directory
- **THEN** the existing module-derived destination behavior SHALL remain unchanged
