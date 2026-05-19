## ADDED Requirements

### Requirement: Production Numillian SHALL be source-truth derived

The production `The_Hidden_City_of_Numillian` module SHALL be built or refreshed from the original source markdown or deterministic accurate-ingest artifacts derived from that markdown.

#### Scenario: Source markdown is the production authority

- **GIVEN** the production target is `modules/The_Hidden_City_of_Numillian/`
- **WHEN** the module is rebuilt, refreshed, or verified for publication
- **THEN** the source authority SHALL be `Local_Docs/modules/hombrew/modules/The Hidden City of Numillian.md`
- **AND** legacy v1 module content SHALL NOT be copied into production as the primary fix.

#### Scenario: Canonical artifact set exists

- **GIVEN** production Numillian is prepared for publication
- **WHEN** canonical artifacts are inspected
- **THEN** `module_context.json`, `module_context_BU.json`, `module_plot_BU.json`, `party_tracker_BU.json`, `areas/*_BU.json`, `map_*.json`, seed artifacts, validation report, source-fidelity report, benchmark report, toolkit build report, and generated docs SHALL exist when applicable
- **AND** runtime state files SHALL remain ignored and non-canonical.

#### Scenario: Canonical artifacts are trackable

- **GIVEN** production Numillian canonical artifacts are generated
- **WHEN** git ignore rules are evaluated
- **THEN** canonical files SHALL be trackable without `git add -f`
- **AND** runtime files SHALL remain ignored by normal publication rules.

### Requirement: Production Numillian SHALL preserve benchmark source content

Production Numillian SHALL preserve the required source content named by the benchmark fixture.

#### Scenario: Required source locations are preserved

- **GIVEN** the Numillian benchmark fixture expects 13 source locations
- **WHEN** production Numillian is benchmarked
- **THEN** all 13 source locations SHALL be preserved by original source name or approved mapping.

#### Scenario: Required source fixtures are preserved

- **GIVEN** the Numillian benchmark fixture includes required source expectations
- **WHEN** production Numillian is benchmarked
- **THEN** Trial-at-the-Door, skull riddle, flooding room puzzle, kill-the-dog mindscape, Gatepact lore, Kobe protection objective, and quirky source tone SHALL be present in canonical module artifacts.
