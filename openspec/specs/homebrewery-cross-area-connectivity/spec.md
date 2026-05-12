## Purpose

Build and surface cross-area connectivity edges from areaConnectivity/areaConnectivityId fields in both LLM prompts and deterministic rendering.

## Requirements


### Requirement: Build cross-area edge index during data load

The data loader SHALL parse `areaConnectivity` (list of human-readable area names) and `areaConnectivityId` (list of location IDs in the target area) from each location in `area.locations[]`. It SHALL resolve each area name to its canonical `areaId` via exact match on `area.areaName`. Resolved edges SHALL be stored in `data["_cross_area_edges"]` as `(from_area_id, from_loc_id, to_area_id, to_loc_id)` tuples.

#### Scenario: Valid cross-area edge

- **WHEN** `AC001/I03` has `areaConnectivity: ["The Blackcrag Marches"]` and `areaConnectivityId: ["I01"]`
- **THEN** `data["_cross_area_edges"]` SHALL contain `("AC001", "I03", "BA001", "I01")`

#### Scenario: Unresolvable area name

- **WHEN** a location has `areaConnectivity: ["Unknown Area"]` where no area has `areaName == "Unknown Area"`
- **THEN** the edge SHALL be skipped (not added to the index)
- **THEN** a warning SHALL be logged

#### Scenario: Mismatched array lengths

- **WHEN** `areaConnectivity` has 2 entries but `areaConnectivityId` has only 1
- **THEN** the loader SHALL pair entries up to the shorter array length
- **THEN** unpaired entries SHALL be skipped with a warning

### Requirement: Surface cross-area connectivity in deterministic rendering

The per-location connectivity line in the rendered output SHALL include cross-area destinations. For each cross-area edge originating from this location, the line SHALL include the target area name and target location ID.

#### Scenario: Location with both intra-area and cross-area connectivity

- **WHEN** a location has `connectivity: ["I02"]`, `areaConnectivity: ["The Blackcrag Marches"]`, `areaConnectivityId: ["I01"]`
- **THEN** the connectivity line SHALL read `*Connected to: Within area: I02; The Blackcrag Marches / I01*`

#### Scenario: Location with only cross-area connectivity

- **WHEN** a location has no `connectivity` but has `areaConnectivity: ["The Shuddering Wilds"]` and `areaConnectivityId: ["I01"]`
- **THEN** the connectivity line SHALL read `*Connected to: The Shuddering Wilds / I01*`

### Requirement: Include cross-area edges in LLM area overview prompt

The prompt for `_llm_area_overview()` SHALL include both incoming and outgoing cross-area connections when present. Outgoing edges SHALL be formatted as "Leads to: AreaName (LocationId)". Incoming edges SHALL be formatted as "Reachable from: AreaName (LocationId)".

#### Scenario: Area with both incoming and outgoing edges

- **WHEN** `BA001` has outgoing edge to `FG001/I01` and incoming edge from `AC001/I03`
- **THEN** the LLM prompt SHALL include text like `Leads to: The Abandoned Vaultways (I01) | Reachable from: The Aberrant Wastes (I03)`

#### Scenario: Area with no cross-area edges

- **WHEN** an area has no incoming or outgoing cross-area edges
- **THEN** the LLM prompt SHALL omit cross-area connectivity text entirely (no empty "Leads to:" or "Reachable from:" lines)
