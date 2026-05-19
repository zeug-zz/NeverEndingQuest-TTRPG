## ADDED Requirements

### Requirement: MODULE_SUMMARY SHALL be final-derived output

`MODULE_SUMMARY.md` SHALL reflect final audited module content and SHALL NOT be used as source truth or source-fidelity repair input.

#### Scenario: Summary is generated after module finishing

- **GIVEN** production Numillian has been built or refreshed
- **WHEN** `MODULE_SUMMARY.md` is generated
- **THEN** it SHALL be derived from final module artifacts after materialization and finishing
- **AND** it SHALL NOT be used to alter source-fidelity scoring.

#### Scenario: Summary cannot repair missing source content

- **GIVEN** canonical module artifacts are missing required source locations, NPCs, puzzles, lore, or tone
- **WHEN** `MODULE_SUMMARY.md` contains that missing content
- **THEN** source-fidelity SHALL still be based on canonical module/source artifacts
- **AND** the summary content alone SHALL NOT convert source-fidelity to pass.

#### Scenario: Summary avoids stale v1 drift

- **GIVEN** the old Numillian v1 archive is present
- **WHEN** production `MODULE_SUMMARY.md` is inspected
- **THEN** it SHALL reflect production module content
- **AND** SHALL NOT include stale v1-only plot replacements or generic conspiracy-thriller drift unless present in current audited production artifacts.

### Requirement: Summary download SHALL remain presentation-only

Adventure markdown download SHALL serve existing summary content as presentation output without triggering source-fidelity repair.

#### Scenario: Disk summary is served

- **GIVEN** `modules/The_Hidden_City_of_Numillian/MODULE_SUMMARY.md` exists and is valid
- **WHEN** the adventure markdown download endpoint is used
- **THEN** the endpoint MAY serve the file directly from disk
- **AND** SHALL NOT regenerate or mutate canonical module JSON as part of the download.
