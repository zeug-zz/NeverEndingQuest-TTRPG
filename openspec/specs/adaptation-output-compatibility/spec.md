# adaptation-output-compatibility Specification

## Purpose
Keep adaptation output deterministic and useful while preserving legacy diagnostics and existing provider/job-reporting contracts.

## Requirements

### Requirement: Adaptation output is deterministic and ASCII-safe

For the same stage result, adaptation progress and safe diagnostics MUST use stable field ordering, bounded values, and ASCII-compatible text. Raw stdout/stderr ordering MUST NOT be required for correctness.

#### Scenario: Repeated progress emission

- **WHEN** the same adaptation stage is reported repeatedly
- **THEN** emitted safe fields MUST remain bounded and deterministic
- **AND** no raw captured line or Unicode-only marker may be required

### Requirement: Legacy non-adaptation diagnostics are preserved

The output hygiene boundary MUST NOT remove safe meaningful diagnostics from legacy CLI, accurate-ingest, concept-builder, or single-player workflows.

#### Scenario: Legacy diagnostics regression

- **WHEN** existing non-adaptation diagnostic tests run outside an adaptation scope
- **THEN** their established safe output and failure codes MUST remain available
- **AND** no adaptation output guard metadata is required

### Requirement: Existing provider and job contracts remain green

Output hygiene MUST preserve provider lazy-log safety, adaptation job reporting, failure-code projection, and existing route payload shapes except for bounded redaction required by this change.

#### Scenario: Existing regression suites

- **WHEN** provider safety and adaptation job-reporting suites execute
- **THEN** they MUST pass without raw payload exposure
- **AND** meaningful adaptation stage/failure codes MUST remain visible
