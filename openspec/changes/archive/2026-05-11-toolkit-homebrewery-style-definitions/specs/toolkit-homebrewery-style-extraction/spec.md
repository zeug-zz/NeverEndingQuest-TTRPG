## Purpose

Define the deterministic extraction of Homebrewery V3 formatting conventions from local exemplar files. This capability ensures the format vocabulary is observationally derived from real published brews rather than assumed from documentation.

## ADDED Requirements

### Requirement: SHALL extract V3 metadata header conventions

The extraction SHALL identify the standard YAML metadata header format used by V3 brews, including required fields (`title`, `renderer`, `theme`) and optional fields (`description`, `tags`, `systems`).

#### Scenario: V3 metadata header extracted from Elden Ring exemplar

**Given** the Elden Ring brew at `Local_Docs/modules/hombrew/modules/Elden Ring D&D_ Call of Grace.md`
**When** the extraction analyzes the metadata block
**Then** it SHALL produce a `METADATA_TEMPLATE` constant containing `renderer: V3` and `theme: 5ePHB`

### Requirement: SHALL extract cover page conventions

The extraction SHALL identify the V3 cover page pattern including `{{frontCover}}` snippet, title/subtitle heading hierarchy, background image placement with curly-brace position syntax, `{{banner HOMEBREW}}` snippet, and `{{pageNumber,auto}}` snippet.

#### Scenario: Cover page conventions from multiple exemplars

**Given** the Elden Ring and March Across Haleroth V3 brews
**When** the extraction analyzes cover page sections
**Then** it SHALL produce `COVER_PAGE_TEMPLATE` containing all four snippets and heading placeholders

### Requirement: SHALL extract page and column break conventions

The extraction SHALL identify `\page` as the page break directive and `\column` as the column break directive, both used standalone on their own line.

#### Scenario: Page break detection across all V3 files

**Given** all 7 V3 brews
**When** the extraction scans for page break patterns
**Then** it SHALL confirm `\page` followed by `{{pageNumber,auto}}` is the universal pattern

### Requirement: SHALL extract monster stat block conventions

The extraction SHALL identify the V3 monster stat block format: HR-delimited (`___` or `---`), blockquote-wrapped (`> ## Name`), ability score table (`|STR|DEX|...|`), and action blocks within the same blockquote.

#### Scenario: Monster stat block from Hostis Humani Generis

**Given** the Hostis Humani Generis V3 brew containing stat blocks
**When** the extraction analyzes stat block sections
**Then** it SHALL produce `MONSTER_STATBLOCK_TEMPLATE` with ability table and action formatting

### Requirement: SHALL extract item block conventions

The extraction SHALL identify the V3 item/treasure block format: HR-delimited blockquote with `>#### Name`, `>**Rarity**`, and property text.

#### Scenario: Item block pattern

**Given** V3 brews containing magic item descriptions
**When** the extraction analyzes item sections
**Then** it SHALL produce `ITEM_BLOCK_TEMPLATE` matching the observed pattern

### Requirement: SHALL extract image placement syntax

The extraction SHALL identify the V3 curly-brace image placement syntax (`{position:absolute,...}`) and image mask snippets (`{{imageMaskEdge7,--offset:13%,--rotation:0 ...}}`).

#### Scenario: Image placement from Elden Ring covers and inline art

**Given** the Elden Ring brew containing multiple image placement examples
**When** the extraction analyzes image directives
**Then** it SHALL produce helpers for `format_image_placement()` and document `IMAGE_MASK_SNIPPETS`

### Requirement: SHALL extract table of contents and wide content snippets

The extraction SHALL identify `{{toc,...}}` and `{{wide ...}}` snippet usage patterns.

#### Scenario: TOC and wide snippets

**Given** V3 brews using TOC and wide content snippets
**When** the extraction analyzes snippet usage
**Then** it SHALL produce `TABLE_OF_CONTENTS_TEMPLATE` and `WIDE_CONTENT_WRAPPER` constants

### Requirement: SHALL produce Python template module

The extraction SHALL produce `utils/homebrewery_style.py` containing all identified templates as Python string constants with `str.format()` placeholders and helper functions for assembling complete document sections.

#### Scenario: Template module compiles and exports expected symbols

**Given** the completed `utils/homebrewery_style.py`
**When** the module is imported
**Then** it SHALL export all template constants and helper functions documented in the style reference

### Requirement: SHALL fail-open on online Homebrewery documentation fetch

If the Homebrewery website fetch fails (HTTP 406 or other non-2xx), the extraction SHALL proceed using local exemplars only and log a degraded-status warning.

#### Scenario: Homebrewery site unavailable

**Given** `https://homebrewery.naturalcrit.com` returns a non-2xx status
**When** the extraction runs
**Then** it SHALL log a warning and continue with local exemplar analysis only
