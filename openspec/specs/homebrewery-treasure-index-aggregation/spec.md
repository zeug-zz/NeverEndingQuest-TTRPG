## Purpose

Aggregate all location lootTable entries into a deduplicated quick-reference treasure index in the Treasures appendix.

## Requirements


### Requirement: Aggregate lootTable entries from all locations into a treasure index

The system SHALL provide a `_build_treasure_index()` function that walks every `area.locations[].lootTable` across all loaded areas and produces a deduplicated markdown bullet list. Each unique item name SHALL appear once with its source location(s) appended in parentheses.

#### Scenario: Module with lootTable entries across multiple locations

- **WHEN** `load_module_data("The_Ancients_Lab")` has 35 lootTable entries spread across 12 locations in 4 areas
- **THEN** `_build_treasure_index()` SHALL produce a markdown list with at most 35 unique items
- **THEN** each line SHALL include the item name and the source location ID `(AreaCode/LocationId)`
- **THEN** identical items found in multiple locations SHALL be combined into one line with all location IDs listed

#### Scenario: Module with no lootTable data

- **WHEN** no location in any area has a non-empty `lootTable`
- **THEN** `_build_treasure_index()` SHALL return an empty string
- **THEN** the appendix SHALL fall back to a note stating no curated treasure data is available

#### Scenario: Deduplication by normalized name

- **WHEN** two locations both have a lootTable entry named "warped silver brooch" and "Warped Silver Brooch" respectively
- **THEN** the deduplication SHALL treat them as the same item (case-insensitive, whitespace-smashed)
- **THEN** the output SHALL list the item once with both source location IDs

### Requirement: Replace stub text in _build_items_appendix with aggregated index

The `_build_items_appendix()` function SHALL call `_build_treasure_index()` and render its output in place of the hardcoded stub text. The section header `# Appendix A: Treasures` and pagination prefix SHALL be preserved.

#### Scenario: Rich treasure data available

- **WHEN** `_build_treasure_index()` returns a non-empty markdown list
- **THEN** the appendix SHALL render the header `# Appendix A: Treasures` followed by the aggregated list
- **THEN** the old stub text "Item and treasure data is generated during gameplay" SHALL NOT appear

#### Scenario: No treasure data available

- **WHEN** `_build_treasure_index()` returns an empty string
- **THEN** the appendix SHALL render a fallback message indicating no curated treasure data is available for this module
- **THEN** the appendix SHALL NOT crash or omit the section entirely

### Requirement: Output format contract

Each bullet line in the treasure index SHALL follow the format `- **Item Name** — description text (AreaCode/LocationId)`. When no description is present in the lootTable entry, only the item name and location SHALL be rendered.

#### Scenario: Loot entry with description

- **WHEN** a lootTable entry is `{"item": "Warped Silver Brooch", "value": "25 gp", "description": "faintly vibrating"}`
- **THEN** the rendered line SHALL be `- **Warped Silver Brooch** — faintly vibrating, 25 gp (AC001/I01)`

#### Scenario: Loot entry as plain string

- **WHEN** a lootTable entry is the string `"Prototype Cure Vial"`
- **THEN** the rendered line SHALL be `- **Prototype Cure Vial** (AC001/I02)`

### Requirement: ASCII compliance

All rendered treasure content SHALL pass through `sanitize_markdown_text()` before output. The output SHALL be safe for Windows cp1252 environments.

#### Scenario: Non-ASCII characters in treasure descriptions

- **WHEN** a lootTable description contains Unicode characters
- **THEN** `sanitize_markdown_text()` SHALL replace them with ASCII equivalents
- **THEN** the appendix output SHALL pass a `.encode("ascii")` check
