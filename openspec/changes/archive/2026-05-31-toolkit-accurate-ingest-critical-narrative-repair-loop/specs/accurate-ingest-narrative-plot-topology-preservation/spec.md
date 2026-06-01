## ADDED Requirements

### Requirement: Plot Topology Preserves Adventure Arc

Accurate-ingest Builder output SHALL preserve adventure-arc plot progression separately from map-key location ordering.

#### Scenario: Numillian source has trials and a map key
- **GIVEN** the source contains Trial at the Door, First Trial, Second Trial, False Third Trial, True Third Trial, City of the Mind, and No-win Scenario
- **AND** the source also contains a 13-location map key
- **WHEN** Builder generates plot progression
- **THEN** plot points SHALL preserve the trial/adventure sequence
- **AND** map-key entries SHALL be represented as locations rather than replacing the plot arc.

### Requirement: Puzzle Components Stay Attached To Puzzle Context

Puzzle components SHALL remain attached to the puzzle/trial context in Builder output.

#### Scenario: skull_riddle has colored skulls
- **GIVEN** the source describes Red, Blue, and Yellow Skull clues
- **WHEN** Builder repair represents `skull_riddle`
- **THEN** those skulls SHALL be represented as puzzle components, clues, or interaction objects
- **AND** their presence SHALL not require standalone NPC status unless the Builder also justifies scene use.

### Requirement: Critical Objective Actors Stay Attached To Plot Context

Critical actors in objective/failure prose SHALL be linked to the relevant plot or scene surfaces.

#### Scenario: Kobe anchors the final no-win scenario
- **GIVEN** Kobe is the final trial rescue objective
- **WHEN** Builder repair represents Kobe
- **THEN** Kobe SHALL be present as a critical NPC or scene objective
- **AND** the final trial plot context SHALL reference protecting or rescuing Kobe without creating false destination phrases.

## SHOULD Guidance

The Builder should use concise plot titles and preserve detailed objective prose in descriptions or instructions to avoid semantic destination phrase debt.
