# toolkit-homebrewery-style-reference Specification

## Purpose
TBD - created by archiving change toolkit-homebrewery-style-definitions. Update Purpose after archive.
## Requirements
### Requirement: SHALL document all V3 template elements with examples

The style reference SHALL document every V3 formatting element used in the Python template module, with a real extracted example from local exemplars for each.

#### Scenario: Each template has a documented section with example

**Given** the Python template module `utils/homebrewery_style.py`
**When** `data/homebrewery_style_reference.md` is generated
**Then** every template constant exported by the Python module SHALL have a corresponding section in the reference document containing: element name, V3 snippet signature or syntax, parameters/placeholders, and an extracted example

### Requirement: SHALL include a quick-start section

The style reference SHALL include a quick-start section showing the minimal document skeleton for a V3 Homebrewery brew.

#### Scenario: Quick-start section

**Given** `data/homebrewery_style_reference.md`
**When** a developer reads the quick-start section
**Then** they SHALL see the complete minimal skeleton: metadata header, cover page, first content page with page break, and closing page number

### Requirement: SHALL document section ordering conventions

The style reference SHALL document the recommended ordering of document sections (cover, introduction, content pages, appendices, credits) as observed in the local exemplars.

#### Scenario: Section ordering documented

**Given** the style reference
**When** a developer reads the section ordering guidance
**Then** they SHALL understand the standard Homebrewery document structure and any ordering constraints (e.g., appendices always at end, credits before appendices)

### Requirement: SHALL note V3-vs-legacy differences

The style reference SHALL note key differences between V3 and legacy renderer formatting where they affect document structure, to prevent authors from mixing conventions.

#### Scenario: V3 vs legacy callouts

**Given** the style reference
**When** a developer reads about page numbering
**Then** they SHALL see a note that V3 uses `{{pageNumber,auto}}` (no surrounding div) while legacy uses `<div class='pageNumber auto'></div>`

### Requirement: SHALL be valid markdown

The style reference SHALL be valid GitHub-flavored markdown suitable for rendering in the repository and in any markdown viewer.

#### Scenario: Markdown validity

**Given** `data/homebrewery_style_reference.md`
**When** the file is parsed as markdown
**Then** it SHALL contain valid headings, code blocks, tables, and blockquotes with no syntax errors

