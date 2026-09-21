# adaptation-content-authority-boundary Specification

## Purpose
Define the ownership boundary for adaptation finalization so the LLM resolves bounded source-grounded content while Python remains the authority for safety, structure, and transactions.

## Requirements

### Requirement: Adaptation content authority is explicit

An `llm_adaptation` finalization attempt MUST assign content interpretation, quantity/encounter semantics, narrative remediation, and the final content-candidate readiness decision to the bounded LLM workflow, while Python MUST own rights/policy checks, paths, staging, schema validity, artifact identity/freshness, proposal validation, publication, and rollback.

#### Scenario: Content blocker reaches finalization

- **WHEN** a staged adaptation has a source-grounded monster identity or scene-semantics blocker that is eligible for bounded remediation
- **THEN** the blocker MUST be represented as a revision candidate for the LLM workflow
- **AND** Python MUST retain hard-gate and transaction authority

#### Scenario: Unsafe operation is proposed

- **WHEN** an LLM proposal includes an arbitrary path, raw patch, schema/ID/topology edit, rights change, registry/campaign mutation, or unapproved identity
- **THEN** Python MUST reject it
- **AND** the staging revision and live module state MUST remain unchanged

### Requirement: Scene prose and structured mechanics remain separate

Adaptation finalization MUST preserve bounded source scene prose and structured quantity/encounter fields as separate evidence. Python MUST NOT mechanically rewrite scene prose solely to make a quantity or identity check pass.

#### Scenario: Quantity and prose disagree

- **WHEN** a location has structured quantity `1` but its bounded prose describes multiple scene manifestations
- **THEN** the quantity MUST remain unchanged in the structural record
- **AND** the prose contradiction MUST be exposed as a bounded content diagnostic for LLM interpretation

### Requirement: Legacy behavior is isolated

The content-authority boundary MUST apply only to the adaptation route.

#### Scenario: Legacy builder executes

- **WHEN** a legacy accurate-ingest or non-adaptation ModuleBuilder path runs
- **THEN** its existing closure, content interpretation, diagnostics, and output behavior MUST remain unchanged
- **AND** no adaptation finalization metadata is required
