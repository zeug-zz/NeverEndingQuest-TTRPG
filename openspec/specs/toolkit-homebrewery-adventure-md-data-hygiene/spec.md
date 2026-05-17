# toolkit-homebrewery-adventure-md-data-hygiene Specification

## Purpose
TBD - created by archiving change toolkit-homebrewery-adventure-md-cleanup. Update Purpose after archive.
## Requirements
### Requirement: SHALL merge live file narrative data into BU-loaded structures

After loading data from `_BU` canonical files, the loader SHALL overlay narrative text fields (NPC descriptions, roles, factions; plot point descriptions; area descriptions; author; license) from the live file where BU entries are empty, missing, or substantially shorter.

#### Scenario: NPC description missing in BU, present in live

**Given** `module_context_BU.json` has `edda_coppervein` with empty description
**When** the live `module_context.json` has `edda_coppervein` with a 432-character description
**Then** the merged data SHALL use the 432-character description from the live file

#### Scenario: NPC description present in BU, shorter in live

**Given** `module_context_BU.json` has `archivist_automaton` with a 221-character description
**When** `module_context.json` has `archivist_automaton` with a 547-character description
**Then** the merged data SHALL use the 547-character description from the live file

#### Scenario: Author and license missing in BU

**Given** `module_context_BU.json` has empty `author` and `license` fields
**When** the live `module_context.json` has `"author": "Kuhal - Module derived from https://..."` and `"license": "https://creativecommons.org/licenses/by-nc-sa/4.0/"`
**Then** the merged data SHALL contain the live file's author and license values

#### Scenario: No live file exists for merge

**Given** a module with only `module_context_BU.json` (no live `module_context.json`)
**When** the loader runs
**Then** the merged data SHALL be identical to the BU data (no merge applied)

### Requirement: SHALL deduplicate areas by areaId

The area loader SHALL ensure each area (identified by `areaId`) appears at most once in the output, skipping duplicates introduced by loading both live and BU variants of the same area file.

#### Scenario: Duplicate area files

**Given** both `BA001.json` and `BA001_BU.json` exist in the areas directory
**When** `_prefer_bu()` redirects both to `BA001_BU.json`
**Then** the loaded areas list SHALL contain exactly one entry with `areaId="BA001"`

### Requirement: SHALL use areaName for location display names

The location section SHALL use the `areaName` field from area data as the primary display name, falling back to `locationName` then `areaId` when `areaName` is absent.

#### Scenario: areaName is present

**Given** an area with `"areaName": "The Aberrant Wastes"`
**When** the location section is built
**Then** the display name SHALL be "The Aberrant Wastes"

#### Scenario: areaName is absent

**Given** an area without an `areaName` field but with `"locationName": "Test Room"`
**When** the location section is built
**Then** the display name SHALL be "Test Room"

