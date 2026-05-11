## Purpose

Define the correction of the actions sub-heading level within monster stat blocks from H3 to H4, matching the visual hierarchy where sub-sections within blockquotes should be one level deeper than the main stat block heading.

## ADDED Requirements

### Requirement: SHALL use H4 for Actions sub-heading in monster stat blocks

The `_build_monster_appendix()` function SHALL emit `> #### Actions` as the sub-heading for the actions section within monster stat block blockquotes, not `> ### Actions`.

#### Scenario: Actions sub-heading is H4

**Given** a monster with actions in the appendix
**When** the stat block is generated
**Then** the output SHALL contain `> #### Actions`

#### Scenario: Actions sub-heading is not H3

**Given** a monster with actions in the appendix
**When** the stat block is generated
**Then** the output SHALL NOT contain `> ### Actions`
