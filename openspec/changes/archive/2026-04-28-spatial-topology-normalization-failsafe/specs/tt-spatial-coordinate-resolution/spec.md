# TT Spatial Coordinate Resolution

## Purpose

Add a deterministic topology-normalization failsafe for spatial adjacency failures that cannot be honestly solved by coordinate relayout alone. The failsafe preserves authored rooms and inserts visible connector nodes so final module content satisfies the same strict spatial validation contract.

## ADDED Requirements

### Requirement: Remediation SHALL insert deterministic connector nodes for unresolved spatial edges

When coordinate-only solving fails with unresolved authored edges, the remediation pipeline SHALL be able to transform each unresolved direct edge into a connector path made of real module nodes. The generated connector path SHALL be validated like ordinary module topology.

#### Scenario: Unresolved edge becomes a connector path

- GIVEN authored rooms A and B are connected
- AND coordinate-only solving cannot place A and B cardinal-adjacent
- WHEN topology normalization runs
- THEN it creates a generated connector node C
- AND replaces the direct A-B edge with A-C and C-B edges
- AND the final coordinates place A-C and C-B at Manhattan distance 1
- AND A and B both remain present as authored rooms

### Requirement: Generated connectors SHALL carry visible provenance

Generated connector nodes SHALL include deterministic provenance identifying that they were created by spatial remediation, why they were created, and which source edge they normalize.

#### Scenario: Connector provenance records source edge

- GIVEN topology normalization creates connector C for source edge A-B
- WHEN the connector is written to module content
- THEN C includes `spatial_remediation.generated=true`
- AND C includes `reason="non_embed_edge"`
- AND C includes `source_edge` containing A and B
- AND C includes `method="deterministic_connector_insertion"`

### Requirement: Topology normalization success SHALL be post-validation only

The remediation pipeline SHALL NOT report success until the normalized topology passes the same strict spatial coordinate validation and map/area parity checks used for ordinary module publication.

#### Scenario: Failed post-validation emits structural debt

- GIVEN connector insertion runs
- AND post-normalization validation still finds non-cardinal edges or parity drift
- WHEN remediation reports its result
- THEN it reports `author_structural_debt`
- AND it includes exact blocking edges or parity findings
- AND it does not mark the module publishable because of connector insertion alone

### Requirement: LLM advisory flavor SHALL NOT be required for validity

LLM involvement in topology normalization SHALL be optional and advisory. Python SHALL be able to create valid connector nodes using deterministic templates without LLM output.

#### Scenario: LLM unavailable uses deterministic template

- GIVEN topology normalization needs a connector
- AND no LLM provider is available or advisory mode is disabled
- WHEN remediation runs
- THEN Python selects a deterministic connector archetype and name
- AND remediation can still pass validation without LLM output

#### Scenario: Invalid LLM suggestion cannot mutate topology

- GIVEN advisory LLM flavor suggests an unsupported connector shape or invalid topology mutation
- WHEN Python validates the suggestion
- THEN the suggestion is rejected
- AND deterministic templates are used instead
- AND canonical module topology remains Python-owned

### Requirement: Same-coordinate multi-plane rooms SHALL be deferred

The failsafe SHALL NOT place two rooms at the same X/Y coordinate to represent separate dimensions unless a future schema and validator contract introduces explicit spatial layers such as `plane`, `layer`, or `dimension`.

#### Scenario: Portal connector avoids coordinate overlap

- GIVEN a mirror portal or dimensional threshold connector is selected
- WHEN coordinates are emitted
- THEN every location still has a unique coordinate in the current 2D grid
- AND dimensional flavor is represented by the connector node, not overlapping coordinates
