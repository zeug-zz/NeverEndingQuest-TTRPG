# accurate-ingest-modulebuilder-monster-closure Specification

## Purpose
TBD - created by archiving change toolkit-accurate-ingest-modulebuilder-structural-repair. Update Purpose after archive.
## Requirements
### Requirement: Accurate-Ingest ModuleBuilder Closes Monster References

Source-enhanced accurate-ingest ModuleBuilder builds SHALL close structured monster references before final reconciliation routing.

#### Scenario: Referenced monster file is present before validation
- **GIVEN** a source-enhanced ModuleBuilder build emits an area, encounter seed, or location with a structured monster reference
- **WHEN** the post-build structural repair stage runs
- **THEN** the module SHALL contain a schema-valid module-local `monsters/*.json` artifact for that monster reference before full validation runs
- **AND** the repair report SHALL record whether the artifact was reused, generated, or already present.

#### Scenario: Unresolved required monster blocks the build
- **GIVEN** a source-enhanced ModuleBuilder build emits a required monster reference that cannot be safely resolved
- **WHEN** the post-build structural repair stage completes
- **THEN** the build SHALL be blocked with an explicit unresolved monster diagnostic
- **AND** final-editor reconciliation SHALL NOT be invoked for that build.

#### Scenario: Existing ModuleGenerator closure parity is preserved
- **GIVEN** existing ModuleGenerator monster closure behavior for non-accurate-ingest builds
- **WHEN** the shared monster closure helper or adapter is introduced
- **THEN** existing ModuleGenerator closure tests SHALL continue to pass
- **AND** accurate-ingest ModuleBuilder builds SHALL produce equivalent `monster_closure_report.json` semantics or a documented compatible report.

### Requirement: Monster Closure Does Not Invent Unsupported NPC Monsters

Monster closure SHALL NOT promote NPC-like source names into monster artifacts without combatant evidence.

#### Scenario: NPC-like source name is ambiguous
- **GIVEN** a source name appears as an NPC or scene entity without monster evidence
- **WHEN** monster closure evaluates the name
- **THEN** the name SHALL NOT be silently materialized as a monster artifact
- **AND** the report SHALL include an ambiguity or non-monster diagnostic.

