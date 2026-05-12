## Purpose

Define the deterministic generation of Homebrewery V3 adventure markdown documents from NeverEndingQuest module JSON data. The generator reads module context, plot, area, monster, and map data and assembles a complete Homebrewery brew document using templates from `utils/homebrewery_style.py`.

## Requirements

### Requirement: SHALL read from canonical module backup files

The generator SHALL read module data from `_BU` (backup/canonical) files where available, falling back to live files only when no `_BU` variant exists. This ensures the adventure document reflects the authored module, not the current gameplay session state.

#### Scenario: Reading plot data from backup file

**Given** a module at `modules/The_Ancients_Lab/`
**When** `module_plot_BU.json` exists
**Then** the generator SHALL read plot data from `module_plot_BU.json`, not `module_plot.json`

#### Scenario: Falling back to live file when no backup exists

**Given** a module where `areas/AC001_BU.json` does not exist but `areas/AC001.json` does
**When** the generator loads area data
**Then** it SHALL read from `areas/AC001.json`

### Requirement: SHALL produce valid V3 Homebrewery metadata header

The generated document SHALL begin with a YAML metadata block containing `renderer: V3`, `theme: 5ePHB`, and a `title` derived from the module name.

#### Scenario: Metadata header

**Given** any module with a module directory name
**When** `generate_homebrewery_adventure()` is called
**Then** the output SHALL start with a metadata block containing at minimum `title`, `renderer`, and `theme` fields

### Requirement: SHALL produce a cover page

The generated document SHALL include a front cover page with the module title, an optional subtitle, a `{{banner HOMEBREW}}` snippet, and `{{pageNumber,auto}}`.

#### Scenario: Cover page

**Given** a module with a display name
**When** the cover page is generated
**Then** it SHALL contain `{{frontCover}}`, the module title in heading format, `{{banner HOMEBREW}}`, and `{{pageNumber,auto}}`

### Requirement: SHALL produce an introduction section

The generated document SHALL include an introduction section after the cover page, containing adventure overview text, background and hook information, and any DM guidance available from module context.

#### Scenario: Introduction section

**Given** a module with NPC descriptions and plot context
**When** the introduction is generated
**Then** it SHALL include the module's narrative premise and intended level range

### Requirement: SHALL produce a plot overview section

The generated document SHALL include a plot overview summarizing all plot points from `module_plot_BU.json` with their titles and descriptions, preserving the authored plot chain order.

#### Scenario: Plot overview with 13 plot points

**Given** The Ancients Lab module with 13 plot points
**When** the plot overview is generated
**Then** it SHALL include all 13 plot points with titles and descriptions, ordered PP001 through PP013

### Requirement: SHALL produce an NPC gallery section

The generated document SHALL include an NPC gallery listing all NPCs from `module_context.json` with their names, descriptions, roles, and factions. NPCs with multi-playline role strings SHALL have their role text included verbatim.

#### Scenario: NPC gallery with 9 NPCs

**Given** The Ancients Lab module with 9 NPCs
**When** the NPC gallery is generated
**Then** it SHALL include all 9 NPCs with their descriptions, roles, and factions

### Requirement: SHALL produce a locations section

The generated document SHALL include a locations section listing all area locations with their names, connectivity information, and any available description text. Areas with empty descriptions SHALL be noted with a placeholder message.

#### Scenario: Locations with sparse data

**Given** The Ancients Lab areas with empty description fields
**When** the locations section is generated
**Then** it SHALL list each location by name and connectivity, with a note that room descriptions are not yet authored

### Requirement: SHALL produce a monster stat block appendix

The generated document SHALL include a monster appendix containing Homebrewery-formatted stat blocks for every monster referenced in the module's `monsters/` directory, using `format_monster_statblock()` from `utils/homebrewery_style.py`.

#### Scenario: Monster appendix

**Given** a module with monster JSON files in `monsters/`
**When** the monster appendix is generated
**Then** each monster SHALL be rendered as a Homebrewery stat block with ability scores, HP, AC, speed, senses, traits, and actions

### Requirement: SHALL include author and license attribution in credits

The generated document SHALL include a credits section containing the `author`
and `license` fields from `module_context.json`, formatted as a Homebrewery V3
`{{credits}}` block. The author field SHALL be parsed to extract a display name
and optional source URL. The license field SHALL be rendered as a clickable link.
If the fields are missing, the section SHALL still appear with a placeholder
indicating attribution is unavailable. The credits SHALL also include an SRD
5.2.1 attribution line.

#### Scenario: Author and license present

**Given** The Ancients Lab module with
  `"author": "Kuhal - Module derived from https://homebrewery.naturalcrit.com/share/SyBdnURLNZ"`
  and `"license": "https://creativecommons.org/licenses/by-nc-sa/4.0/"`
**When** the credits section is generated
**Then** the output SHALL contain the `{{credits}}` snippet followed by a
  formatted attribution block with the author name, source URL, and license
  link

#### Scenario: Author or license missing

**Given** a module with no `author` or `license` field in module_context
**When** the credits section is generated
**Then** the output SHALL contain `{{credits}}` with a note that attribution
  information was not found in the module metadata

#### Scenario: License is a URL

**Given** a license value that is a URL
**When** the credits section is generated
**Then** the URL SHALL be rendered as a clickable markdown link

### Requirement: SHALL handle missing data gracefully

The generator SHALL produce a valid markdown document even when some source data is missing or empty. Instead of failing, it SHALL insert deterministic placeholder text noting the absence.

#### Scenario: Missing NPC data

**Given** a module with no NPCs in `module_context.json`
**When** the NPC gallery is generated
**Then** it SHALL produce a section noting "No NPC data available for this module"

### Requirement: SHALL be importable and callable programmatically

The `utils/homebrewery_adventure_writer.py` module SHALL export `generate_homebrewery_adventure()` as its primary entry point, accepting a module slug string and returning the complete markdown document as a string.

#### Scenario: Programmatic usage

**Given** the writer module installed in `utils/`
**When** `from utils.homebrewery_adventure_writer import generate_homebrewery_adventure` is called
**Then** the function SHALL be importable and callable without side effects

### Requirement: SHALL produce ASCII-safe output

The generated markdown SHALL contain only ASCII characters. Any non-ASCII module data SHALL be passed through `sanitize_markdown_text()` from `utils/homebrewery_style.py`.

#### Scenario: Non-ASCII character handling

**Given** module NPC data containing non-ASCII characters
**When** the adventure document is generated
**Then** all non-ASCII characters SHALL be replaced with ASCII-safe equivalents
