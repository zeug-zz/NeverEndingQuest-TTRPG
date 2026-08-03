## ADDED Requirements

### Requirement: Bogus source atoms SHALL not remain as required final module structure

When the LLM Builder final editor accepts that a source-fidelity blocker is caused by a bogus source atom, the final module SHALL not preserve that atom as a required location, NPC, puzzle, clue, item, encounter, or plot structure unless the editor creates a valid playable element intentionally.

#### Scenario: Well-like trap headings are removed from required locations

- **GIVEN** blockers include required locations named `Trigger`, `Passive Element`, and `Active Element`
- **AND** source evidence shows those names are trap mechanics headings rather than playable locations
- **WHEN** final reconciliation is accepted
- **THEN** those names SHALL NOT remain required final module locations
- **AND** they MAY be dropped as bogus structure or preserved as mechanics, trap rules, hazard instructions, plot notes, or DM guidance.

#### Scenario: Real missing element may be created or merged

- **GIVEN** a source atom is a real missing playable element
- **WHEN** final reconciliation determines it is necessary for playability
- **THEN** the final editor MAY create or merge that element into whitelisted canonical module artifacts
- **AND** deterministic validation SHALL prove the resulting module remains valid.

#### Scenario: Bogus atoms do not poison Narrator-facing topology

- **GIVEN** a blocker was accepted as a section heading, table label, language heading, or mechanics heading
- **WHEN** final module topology and Narrator-facing location structures are generated or reported
- **THEN** the bogus atom SHALL NOT appear as a playable location solely because it appeared in source-fidelity blocker evidence.
