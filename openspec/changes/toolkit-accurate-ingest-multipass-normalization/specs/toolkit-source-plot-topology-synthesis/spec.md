## ADDED Requirements

### Requirement: Plot topology synthesis SHALL preserve source order and dependencies

Multipass normalization SHALL synthesize plot topology from source graph atoms and section facts without inventing replacement plotlines.

#### Scenario: Source order is preserved without stronger dependency evidence

- **GIVEN** source plot beats appear in a clear document order
- **AND** no source evidence states a different dependency order
- **WHEN** plot topology synthesis runs
- **THEN** the topology SHALL preserve source order
- **AND** inferred transitions SHALL be marked as assumptions, not facts.

#### Scenario: Unsupported replacement plotline is not synthesized as fact

- **GIVEN** no source evidence supports a major faction, villain, or alternate plot spine
- **WHEN** plot topology synthesis runs
- **THEN** the topology SHALL NOT add that replacement plotline as source fact
- **AND** any optional inference SHALL be marked as an assumption or omitted.

### Requirement: Puzzle, clue, and trial chains SHALL be structured

Source-defined puzzles, clues, and trials SHALL be represented as structured topology where source evidence exists.

#### Scenario: Trial sequence remains structured

- **GIVEN** the source defines a trial or puzzle sequence with setup, prompt, rule, solution, or consequence
- **WHEN** topology synthesis runs
- **THEN** the topology SHALL preserve those pieces as structured fields
- **AND** it SHALL NOT flatten the sequence into summary prose only.

#### Scenario: Clue dependency is linked to supported puzzle or beat

- **GIVEN** a clue reveals a puzzle solution, plot dependency, or objective
- **WHEN** topology synthesis runs
- **THEN** the clue SHALL link to the supported puzzle, beat, or objective when evidence supports the relationship.

### Requirement: Topology reports SHALL expose assumptions and unresolved gaps

The topology report SHALL distinguish source facts from assumptions and unresolved gaps.

#### Scenario: Missing transition is represented as assumption

- **GIVEN** two source beats appear adjacent but no explicit transition is stated
- **WHEN** topology synthesis links them
- **THEN** the link SHALL be marked as an assumption
- **AND** the report SHALL preserve the source evidence that motivated the assumption.

#### Scenario: Unresolved ending or failure state remains reviewable

- **GIVEN** a source implies but does not fully specify an ending, failure state, or consequence
- **WHEN** topology synthesis runs
- **THEN** the report SHALL list the unresolved item for review
- **AND** it SHALL NOT invent a definitive source outcome.
