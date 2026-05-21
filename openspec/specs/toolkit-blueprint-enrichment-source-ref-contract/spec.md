# toolkit-blueprint-enrichment-source-ref-contract Specification

## Purpose
TBD - created by archiving change toolkit-accurate-ingest-llm-blueprint-enrichment. Update Purpose after archive.
## Requirements
### Requirement: Applied enrichment patches SHALL carry source refs or source-derived justification

Blueprint enrichment SHALL preserve source traceability for every accepted provider-backed patch.

#### Scenario: Patch with source ref is accepted

- **GIVEN** provider JSON proposes an allowed prose patch
- **AND** the patch includes a source ref or source-derived justification tied to bounded input excerpts
- **WHEN** patch validation and application run
- **THEN** the patch MAY be applied
- **AND** the applied result SHALL retain source traceability metadata or equivalent diagnostics.

#### Scenario: Patch without source support is rejected or degraded

- **GIVEN** provider JSON proposes a prose patch without source refs or source-derived justification
- **WHEN** output validation runs
- **THEN** the patch SHALL be rejected or the pass SHALL degrade with diagnostics
- **AND** the patch SHALL NOT be treated as a clean complete enrichment result.

### Requirement: Enrichment SHALL distinguish source interpretation from invention

Blueprint enrichment SHALL improve descriptions, motives, bindings, clues, and guidance from source evidence, but SHALL NOT invent major entities or replacement plotlines.

#### Scenario: Source-derived prose enrichment is allowed

- **GIVEN** a source excerpt describes an NPC, location, clue, puzzle, encounter, item, or tone marker
- **WHEN** enrichment proposes prose that summarizes or clarifies that source evidence
- **THEN** the patch MAY be accepted if it targets an allowed field and preserves source identity.

#### Scenario: Unsupported invention is rejected

- **GIVEN** enrichment proposes a new major NPC, faction, villain, location, ending, or plotline without source support
- **WHEN** validation runs
- **THEN** the patch SHALL be rejected or reported as degraded
- **AND** unsupported invention SHALL NOT enter canonical blueprint output.

