## ADDED Requirements

### Requirement: Final reconciliation brief SHALL be persisted for editorial blockers

When final blocker classification finds editorial blockers and no fatal blockers, the accurate-ingest pipeline SHALL persist a workspace-local `final_reconciliation_brief.json` artifact.

#### Scenario: Editorial blocker produces brief

- **GIVEN** final blocker classification returns one or more editorial blockers
- **AND** no fatal blockers are present
- **WHEN** the packet builder handles the classification result
- **THEN** it SHALL write `final_reconciliation_brief.json` in the upload workspace
- **AND** the brief SHALL include job ID, module name, module directory, trigger reason, blocker list, source evidence references when available, and editable surfaces.

#### Scenario: Fatal blocker skips brief

- **GIVEN** final blocker classification returns a fatal blocker
- **WHEN** the packet builder handles the classification result
- **THEN** it SHALL NOT present the build as eligible for final reconciliation
- **AND** it SHALL keep the build blocked with fatal blocker diagnostics.

### Requirement: Final reconciliation brief SHALL not mutate source truth

Creating the final reconciliation brief SHALL NOT modify `source_graph.json`, `source_manifest.json`, normalized packet artifacts, builder blueprint artifacts, or backstage audit artifacts.

#### Scenario: Source artifacts remain unchanged

- **GIVEN** source artifacts exist in the upload workspace
- **WHEN** final reconciliation brief generation runs
- **THEN** the source artifacts SHALL remain unchanged on disk
- **AND** final reconciliation decisions SHALL be recorded in separate final reconciliation artifacts.
