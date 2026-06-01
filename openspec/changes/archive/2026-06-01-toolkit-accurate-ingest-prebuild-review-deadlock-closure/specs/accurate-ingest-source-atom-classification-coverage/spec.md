## ADDED Requirements

### Requirement: Source Atom Classification SHALL Cover Common Markdown Structure

Accurate-ingest source atom extraction MUST classify common adventure markdown structure without promoting every heading or prose fragment into a blocking source entity.

#### Scenario: Heading locations are recognized

- **GIVEN** source markdown contains location headings such as `### Bridge of Sacrifice`
- **WHEN** source atoms are extracted
- **THEN** those headings SHALL be available as location source context
- **AND** they SHALL NOT require mandatory pre-build human approval solely because fidelity diagnostics reference them.

#### Scenario: Escaped numbered room headings are recognized

- **GIVEN** source markdown contains escaped numbered room headings such as `#### 1\\. Chapel`
- **WHEN** source atoms are extracted
- **THEN** the room title SHALL be available as room or location source context
- **AND** the numeric escape syntax SHALL NOT cause the room title to be dropped.

#### Scenario: Appendix headings are not required entities

- **GIVEN** source markdown contains appendix or reference headings such as `Appendix A`
- **WHEN** source atoms are classified
- **THEN** appendix headings SHALL be classified as section/reference structure
- **AND** they SHALL NOT become required NPC, location, or monster blockers.

### Requirement: Source Atom Classification SHALL Separate Prose Fragments From Entities

Accurate-ingest fidelity diagnostics MUST avoid treating incomplete prose phrases as required source entities.

#### Scenario: Prose fragment is not a blocker

- **GIVEN** extracted text includes a fragment such as `gathered around a`
- **WHEN** source atom classification runs
- **THEN** the fragment SHALL NOT be promoted to a required NPC, location, puzzle, or monster
- **AND** it SHALL NOT block blueprint generation.

#### Scenario: NPC-like and monster-like names remain source context

- **GIVEN** source text includes names such as `Nomadic Merchant`, `Guard Dog`, `Lesser Black Knife Assassin`, or `Lion Guardian`
- **WHEN** source atom classification runs
- **THEN** those atoms MAY be retained as NPC or creature/monster source context
- **AND** unresolved status before build SHALL be diagnostic metadata rather than mandatory human approval by default.
