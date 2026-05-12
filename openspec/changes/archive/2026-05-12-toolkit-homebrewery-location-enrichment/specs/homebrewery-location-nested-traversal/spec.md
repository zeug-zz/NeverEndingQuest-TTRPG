## Purpose

Traverse nested area.locations[] arrays in BU area files and resolve cross-area connectivity edges during data load.

## Requirements

## ADDED Requirements

### Requirement: Traverse nested locations array in BU area files

The data loader SHALL extract location records from `area.locations[]` when the array is present on loaded area dicts. Each location record SHALL be augmented with its parent area's identity fields (`_areaId`, `_areaName`, `_areaType`, `_areaDescription`, `_areaDangerLevel`, `_areaRecommendedLevel`, `_areaClimate`, `_areaTerrain`, `_areaSpatialVersion`) using the `_` prefix convention to avoid collision with authored location keys.

#### Scenario: BU area file with locations array

- **WHEN** `load_module_data()` loads an area JSON file where `area.locations` is a non-empty list
- **THEN** the area dict in `data["areas"]` SHALL contain its original `locations` array intact, preserving all 22+ per-location fields unchanged from the JSON source

#### Scenario: Flat area file without locations array

- **WHEN** `load_module_data()` loads an area JSON file where `area.locations` is absent or empty
- **THEN** the area dict in `data["areas"]` SHALL be stored as-is without modification
- **THEN** the area SHALL still be valid for rendering via flat-schema fallback

#### Scenario: Cross-area edge index construction

- **WHEN** `load_module_data()` processes areas with `locations[].areaConnectivity` and `locations[].areaConnectivityId` fields
- **THEN** the loader SHALL populate `data["_cross_area_edges"]` as a list of `(from_area_id, from_loc_id, to_area_id, to_loc_id)` tuples
- **THEN** edges where `areaConnectivityId` index exceeds array bounds SHALL be skipped with a warning

### Requirement: Area name to area ID resolution

The loader SHALL provide a `_resolve_area_name_to_id(areas, name)` helper that matches a human-readable area name (from `areaConnectivity`) to its `areaId` using exact string comparison against each area's `areaName` field.

#### Scenario: Exact match found

- **WHEN** `_resolve_area_name_to_id(areas, "The Aberrant Wastes")` is called
- **THEN** the function SHALL return `"AC001"`

#### Scenario: No match found

- **WHEN** `_resolve_area_name_to_id(areas, "Unknown Place")` is called
- **THEN** the function SHALL return `""` (empty string)
