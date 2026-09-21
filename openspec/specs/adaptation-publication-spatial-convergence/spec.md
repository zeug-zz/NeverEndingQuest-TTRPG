# adaptation-publication-spatial-convergence Specification

## Purpose
Ensures generated adaptation maps and connectivity represent playable topology without discarding authored travel relationships or weakening structural validation, while providing deterministic blocker evidence to the bounded finalization loop.

## Requirements

### Requirement: Staging topology is normalized before publication gates

The adaptation pipeline MUST validate and normalize authored map coordinates and connectivity in staging before readiness, gameplay, or publishability checks run.

#### Scenario: Non-adjacent logical edge is present

- **WHEN** a map contains a connectivity edge between cells that are not cardinally adjacent
- **THEN** the pipeline MUST preserve the authored relationship as a logical area/module connection or other supported topology representation
- **AND** it MUST remove the invalid direct-grid interpretation before schema validation

#### Scenario: Edge cannot be safely reclassified

- **WHEN** a connectivity edge cannot be classified as a valid grid edge or an unambiguous logical connection
- **THEN** the pipeline MUST retain a bounded diagnostic and fail the structural readiness gate
- **AND** it MUST NOT silently delete the edge

### Requirement: Spatial normalization is staging-local and deterministic

Spatial normalization MUST write only to the current adaptation staging revision, use deterministic inputs, and preserve source and module artifact provenance.

#### Scenario: Normalization succeeds

- **WHEN** all topology changes are deterministic and schema-compatible
- **THEN** the normalized maps MUST remain inside the staging revision
- **AND** the convergence report MUST identify changed files, preserved logical edges, and validation status

#### Scenario: Normalization fails

- **WHEN** a spatial normalization operation raises an error or produces invalid output
- **THEN** the current build result MUST persist a concrete spatial failure code
- **AND** live module files MUST remain unchanged
