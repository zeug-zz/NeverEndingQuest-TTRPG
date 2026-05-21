# toolkit-accurate-ingest-default-builder-routing Specification

## Purpose
TBD - created by archiving change toolkit-accurate-ingest-gui-stabilize-defaults. Update Purpose after archive.
## Requirements
### Requirement: Accurate-ingest GUI SHALL use ModuleBuilder as default authoring executor

Accurate-ingest GUI builds SHALL route build-ready packet/blueprint workspaces through the existing ModuleBuilder orchestration by default.

#### Scenario: Ready accurate-ingest build uses ModuleBuilder

- **GIVEN** an accurate-ingest GUI job has a normalized packet and build-ready blueprint artifacts
- **AND** no explicit seed-writer fallback or preview mode is enabled
- **WHEN** the packet build starts
- **THEN** the build SHALL call the ModuleBuilder executor path
- **AND** the build SHALL NOT call the deterministic seed-writer executor path.

#### Scenario: Describe-your-Adventure flow remains compatible

- **GIVEN** a non-accurate-ingest concept build uses the existing ModuleBuilder flow
- **WHEN** accurate-ingest default routing is stabilized
- **THEN** the concept build SHALL continue to use its existing ModuleBuilder path without requiring accurate-ingest source artifacts.

### Requirement: Accurate-ingest build mode SHALL be explicit

Accurate-ingest build results and progress payloads SHALL expose enough metadata to distinguish source-enhanced ModuleBuilder builds from seed-writer fallback or preview builds.

#### Scenario: ModuleBuilder mode reported

- **GIVEN** an accurate-ingest job is building through ModuleBuilder
- **WHEN** status or report metadata is produced
- **THEN** the build mode SHALL identify the path as source-enhanced ModuleBuilder or equivalent
- **AND** it SHALL NOT label the build as a seed-writer path.

#### Scenario: Existing status fields preserved

- **GIVEN** existing GUI code consumes status fields such as `status`, `stage`, `pipeline_status`, `progress_stage`, or `progress_message`
- **WHEN** build mode metadata is added
- **THEN** those existing fields SHALL remain present with compatible semantics.

