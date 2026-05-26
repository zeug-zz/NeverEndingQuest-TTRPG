# Accurate-Ingest Encounter Plan Monster Binding

## Purpose

Define how accurate-ingest encounter seeds preserve source monster bindings when source monster refs are present, and how unresolved diagnostics survive the binding pipeline.

## Requirements

### Requirement: Encounter Seeds Retain Source Monster Bindings

Accurate-ingest encounter seeds SHALL preserve source monster bindings when source monster refs are present and unambiguous.

#### Scenario: Encounter seed binds to materialized monster
- **GIVEN** an encounter seed references a source monster ref that has materialized to a canonical monster ID
- **WHEN** encounter binding runs
- **THEN** the encounter seed or encounter plan SHALL include the canonical monster ID
- **AND** the binding report SHALL include the encounter seed and source ref.

#### Scenario: Encounter seed keeps unresolved monster diagnostic
- **GIVEN** an encounter seed references a source monster ref that cannot be materialized safely
- **WHEN** encounter binding runs
- **THEN** the encounter seed SHALL remain present
- **AND** the unresolved monster ref SHALL be reported with that encounter seed
- **AND** the implementation SHALL NOT remove the seed to make reports look clean.

#### Scenario: Empty monster arrays are flagged when source refs exist
- **GIVEN** a source-enhanced build includes encounter seeds and source monster refs
- **WHEN** an encounter plan would otherwise have an empty monster array
- **THEN** the materialization/binding report SHALL record the empty binding as a blocker or warning
- **AND** the report SHALL include enough source context to diagnose the missing binding.

## SHOULD Guidance

Prefer additive binding metadata over broad blueprint or plot rewrites. Encounter binding should preserve source intent and avoid changing authored plot topology.
