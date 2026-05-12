## Purpose

Generate LLM-authored DM-facing area overview prose that connects locations to plot, NPCs, monsters, and cross-area travel, with deterministic fallback.

## Requirements


### Requirement: Generate LLM area overview prose per area

The system SHALL provide a `_llm_area_overview(area, data)` function that calls the summarization LLM to generate 2-3 paragraphs of DM-facing narrative prose describing an area. The prompt SHALL include: area name, area type, area ID, truncated area description, per-location names with truncated descriptions and NPC/monster names, relevant plot points (matched by area ID in plot descriptions), and cross-area travel connections (both incoming and outgoing).

#### Scenario: Successful LLM area overview generation

- **WHEN** `_llm_area_overview()` is called for an area with 3 populated locations, plot points referencing the area ID, and cross-area edges
- **THEN** the function SHALL call `DM_SUMMARIZATION_MODEL` via `create_chat_client()`
- **THEN** the prompt SHALL contain the area name, type, truncated descriptions, NPC names, monster names, plot point IDs/titles, and cross-area connection names
- **THEN** the response text SHALL be returned wrapped in normal markdown paragraphs (not blockquoted)
- **THEN** the output SHALL pass through `sanitize_markdown_text()`

#### Scenario: LLM unavailable or throws exception

- **WHEN** the LLM call raises any exception (network error, timeout, provider error)
- **THEN** `_llm_area_overview()` SHALL catch the exception and return `None`
- **THEN** the locations section builder SHALL fall back to rendering `area.areaDescription` as body text for the area overview

#### Scenario: Empty location text prevents LLM call

- **WHEN** `_llm_area_overview()` is called for an area where all locations have empty descriptions and no NPCs or monsters
- **THEN** the function SHALL return `None` without making an LLM call

### Requirement: LLM prompt format excludes individual room listings

The LLM prompt SHALL instruct the model to NOT list individual room names in its output. The prompt SHALL direct the model to write in third-person present tense covering: atmosphere, plot connections, key NPCs and monsters, and cross-area travel paths.

#### Scenario: Prompt content contract

- **WHEN** the LLM prompt is constructed for any area
- **THEN** the prompt SHALL contain the phrase "Do NOT list individual room names" or equivalent
- **THEN** the prompt SHALL request third-person present tense
- **THEN** the prompt SHALL reference the area name, area type, location data, plot points, and cross-area connectivity

### Requirement: Fallback preserves areaDescription

When LLM generation fails or returns None, the locations section builder SHALL render the area's `areaDescription` field (if present) as plain paragraph text in place of the LLM overview. If `areaDescription` is also absent, no overview text SHALL be rendered and the section SHALL proceed directly to the metadata line and per-location details.

#### Scenario: LLM fails and areaDescription exists

- **WHEN** `_llm_area_overview()` returns `None` and `area.areaDescription` is a non-empty string
- **THEN** the rendered output SHALL include `areaDescription` as paragraph text below the area heading

#### Scenario: LLM fails and areaDescription is empty

- **WHEN** `_llm_area_overview()` returns `None` and `area.areaDescription` is empty or absent
- **THEN** the rendered output SHALL proceed directly from the area heading to the metadata line
