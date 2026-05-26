# Accurate-Ingest Source Monster Materialization

## Purpose

Define how source-enhanced accurate-ingest builds materialize unambiguous source monster references into module-local monster artifacts or record explicit unresolved diagnostics.

## Requirements

### Requirement: Source Monster Refs Materialize Or Report Unresolved

Source-enhanced accurate-ingest builds SHALL materialize unambiguous source monster references into module-local monster artifacts or record explicit unresolved diagnostics.

#### Scenario: Unambiguous reusable monster ref materializes
- **GIVEN** a source-enhanced build artifact includes a source monster ref that maps to an existing reusable monster template
- **WHEN** monster materialization runs
- **THEN** a schema-valid module-local `monsters/*.json` artifact SHALL be written or reused
- **AND** the materialization report SHALL include the ref in reused or generated counts
- **AND** the report SHALL preserve the source ref or source evidence key.

#### Scenario: Missing monster ref is not silently dropped
- **GIVEN** a source-enhanced build artifact includes a monster ref with no safe reusable template
- **WHEN** monster materialization runs
- **THEN** the ref SHALL appear in unresolved diagnostics
- **AND** the materialization status SHALL be degraded or failed according to criticality
- **AND** no replacement monster identity SHALL be invented.

#### Scenario: NPC-like source name is not promoted without evidence
- **GIVEN** a source ref matches a named NPC or source character without monster/combatant evidence
- **WHEN** monster materialization runs
- **THEN** the ref SHALL NOT be written as a monster artifact
- **AND** the diagnostic SHALL identify the ambiguity or non-monster classification.

### Requirement: Monster Artifact Writes Are Schema-Safe

Materialized monster artifacts SHALL be valid according to the repository's monster/module validation expectations.

#### Scenario: Write failure is surfaced
- **GIVEN** a monster artifact cannot be written or validated
- **WHEN** materialization completes
- **THEN** the failure SHALL be reported explicitly
- **AND** later toolkit reports SHALL NOT claim full monster materialization success.

## SHOULD Guidance

Prefer reuse-first resolution from existing module, SRD, or bestiary-compatible sources before adding any new stat synthesis behavior.
