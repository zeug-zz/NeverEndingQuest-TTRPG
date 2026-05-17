# toolkit-homebrewery-adventure-md-format-corrections Specification

## Purpose
TBD - created by archiving change toolkit-homebrewery-adventure-md-cleanup. Update Purpose after archive.
## Requirements
### Requirement: SHALL use HTML comment metadata format

The `METADATA_TEMPLATE` SHALL produce metadata as an HTML comment block (`<!--\nmetadata\n...\n-->`) rather than a triple-backtick code fence. This SHALL be the format recognized by the Homebrewery editor for metadata detection.

#### Scenario: Metadata header format

**Given** `format_metadata("The Ancients Lab")` is called
**When** the output is generated
**Then** it SHALL start with `<!--` and end with `-->` and contain `renderer: V3` and `theme: 5ePHB`

#### Scenario: No backtick code fence in metadata

**Given** `format_metadata("Test")` is called
**When** the output is generated
**Then** the `renderer:` field SHALL NOT be inside triple backticks

### Requirement: SHALL use H1 headings for main sections

Top-level document sections (Plot Overview, NPC Gallery, Locations, Appendix headers) SHALL use `# Title` (H1 heading) for Homebrewery wide-block visual separation. Sub-sections within these blocks SHALL remain at lower heading levels.

#### Scenario: Main section headings

**Given** the generated adventure document
**When** the Plot Overview section begins
**Then** it SHALL be headed by `# Plot Overview`

#### Scenario: NPC Gallery heading

**Given** the generated adventure document
**When** the NPC Gallery section begins
**Then** it SHALL be headed by `# NPC Gallery`

### Requirement: SHALL use H3 for monster stat block names

Monster stat block names inside blockquote SHALL use `> ### Name` (H3, rendered as underlined in Homebrewery V3) rather than `> ## Name` (H2). The creature type/alignment line SHALL remain at the same level.

#### Scenario: Stat block heading level

**Given** a monster stat block for "Wolf"
**When** `format_monster_statblock(name="Wolf", ...)` is called
**Then** the output SHALL contain `> ### Wolf`

### Requirement: SHALL format monster actions with attack and damage lines

Each monster action with structured data SHALL be formatted as a complete 5e attack line: `***Action.*** *Melee/Ranged Weapon Attack:* +N to hit, reach X ft., one target. *Hit:* Y (ZdA + B) damage_type.` The attack type (Melee/Ranged) SHALL be inferred from the action name or damage type, defaulting to Melee.

#### Scenario: Wolf bite action

**Given** a Wolf monster with action `{"name":"Bite","attackBonus":4,"damageDice":"2d4","damageBonus":2,"damageType":"piercing"}`
**When** the stat block is generated
**Then** the output SHALL contain `***Bite.*** *Melee Weapon Attack:* +4 to hit, reach 5 ft., one target. *Hit:* 6 (2d4 + 2) piercing damage.`

#### Scenario: Action without attack bonus

**Given** an action with no `attackBonus` field
**When** the stat block is generated
**Then** the action SHALL be rendered with only name and description text, no attack line

### Requirement: SHALL separate special abilities from actions

Special abilities (passive traits, always-on effects) SHALL be rendered as `> ***Ability Name.*** Description.` blocks. Actions (attacks, activated abilities requiring an action) SHALL be separated under a `> ### Actions` sub-header within the blockquote.

#### Scenario: Wolf special abilities and actions

**Given** a Wolf with special abilities "Keen Hearing and Smell" and "Pack Tactics" and action "Bite"
**When** the stat block is generated
**Then** special abilities SHALL appear before the actions section, and "Bite" SHALL appear after `> ### Actions`

