## ADDED Requirements

### Requirement: Critical Omission Evidence Produces Builder Repair Brief

When critical narrative omissions are detected, the backstage audit or briefing layer SHALL produce a Builder-facing repair brief.

#### Scenario: Numillian has missing Kobe and skull_riddle
- **GIVEN** critical omission detection reports Kobe and `skull_riddle`
- **WHEN** the repair brief is generated
- **THEN** the brief SHALL include each missing item, criticality, source excerpts, and target output surfaces
- **AND** it SHALL state that the LLM Builder must perform source-faithful synthesis.

### Requirement: Repair Brief Forbids Python Narrative Invention

Repair briefs SHALL forbid Python/manual narrative invention as the repair mechanism.

#### Scenario: Brief is consumed by Builder step
- **GIVEN** a repair brief exists
- **WHEN** the repair step begins
- **THEN** the brief SHALL instruct that Python provides evidence and constraints only
- **AND** the LLM Builder SHALL be responsible for narrative reconstruction from source.

### Requirement: Repair Brief Is Bounded And Auditable

Repair briefs SHALL be compact enough for Builder consumption while retaining auditability.

#### Scenario: Source excerpt is included
- **GIVEN** source text around a critical omission is long
- **WHEN** the brief serializes the excerpt
- **THEN** it SHALL bound excerpt length
- **AND** it SHALL preserve source path and line/reference metadata when available.

## SHOULD Guidance

Prefer JSON plus markdown summary output: JSON for deterministic tests and markdown for Builder readability.
