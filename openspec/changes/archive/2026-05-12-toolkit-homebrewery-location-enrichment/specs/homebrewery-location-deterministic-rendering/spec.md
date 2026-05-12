## Purpose

Render per-location markdown sections with all authored fields (description, features, NPCs, monsters, DM guidance, etc.) in deterministic order.

## Requirements

## ADDED Requirements

### Requirement: Render per-location section with all authored fields

The locations section builder SHALL render each location from `area.locations[]` as a markdown subsection. For each location, the builder SHALL render the following fields when present, in this order: description, danger level, accessibility, adventure summary, features, DC checks, plot hooks, traps, doors, loot, encounters, NPCs, monsters, connectivity, dmInstructions.

#### Scenario: Location with full authored data

- **WHEN** a location has `description`, `dmInstructions`, `npcs`, `monsters`, `features`, `dcChecks`, `plotHooks`, `traps`, `doors`, `lootTable`, `encounters`, `connectivity`, `areaConnectivity`, `areaConnectivityId`, `dangerLevel`, `accessibility`, `adventureSummary`
- **THEN** the rendered output SHALL include each field in a consistently formatted block
- **THEN** the `description` SHALL be rendered as plain markdown paragraph text
- **THEN** the `dmInstructions` SHALL be rendered under a `**DM Guidance:**` header in full, without truncation
- **THEN** `features` SHALL be rendered as a bullet list with bold feature names and colon-separated descriptions
- **THEN** `dcChecks` SHALL be rendered as a bullet list under `**DC Checks:**`
- **THEN** `plotHooks` SHALL be rendered as a bullet list under `**Plot Hooks:**`
- **THEN** `npcs` SHALL be rendered as a bullet list under `**NPCs:**` with attitude in parentheses
- **THEN** `monsters` SHALL be rendered as a bullet list under `**Monsters:**` with description after `--`
- **THEN** connectivity SHALL be rendered as a single `*Connected to:*` line composing intra-area `connectivity` and cross-area `areaConnectivity / areaConnectivityId` pairs

#### Scenario: Location with sparse data

- **WHEN** a location has only `name` and `description`
- **THEN** the rendered output SHALL include only the heading, description, and a trailing `---` separator
- **THEN** empty field categories SHALL NOT produce empty headers (e.g., no "**NPCs:**" section with no NPCs)

#### Scenario: Flat-schema area without locations array

- **WHEN** an area has no `locations` array but has top-level `description` or `dmInstructions`
- **THEN** the builder SHALL treat the area itself as a single location, using `areaName` as the location name and `areaId` as the location identifier

### Requirement: Area-level header with metadata line

Each area in the locations section SHALL begin with an `## AreaName (AreaCode)` heading followed by area overview prose and a metadata line.

#### Scenario: Area with type and recommended level

- **WHEN** an area has `areaType: "dungeon"` and `recommendedLevel: "3-5"`
- **THEN** the metadata line SHALL read `**Area Type:** Dungeon | **Recommended Level:** 3-5`

#### Scenario: Area with minimal metadata

- **WHEN** an area has no `areaType` and no `recommendedLevel`
- **THEN** the metadata line SHALL read `**Area Type:** Unknown`

### Requirement: ASCII-only output compliance

All rendered location content SHALL pass through `sanitize_markdown_text()` before output. The function SHALL strip or replace non-ASCII characters to ensure the output is safe for Windows cp1252 environments.

#### Scenario: Non-ASCII characters in location description

- **WHEN** a location description contains Unicode em-dashes, curly quotes, or special characters
- **THEN** `sanitize_markdown_text()` SHALL replace them with ASCII equivalents
- **THEN** the output SHALL pass a `.encode("ascii")` check
