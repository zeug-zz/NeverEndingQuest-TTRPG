## ADDED Requirements

### Requirement: Critical Repair Requires Live Source-Fidelity Pass

Release verification SHALL use live module JSON and refreshed reports after Builder repair.

#### Scenario: Numillian repair completes
- **GIVEN** Builder repair has updated module artifacts
- **WHEN** source-fidelity benchmark runs
- **THEN** it SHALL report NPC 23/23 and puzzle 3/3 from live module JSON
- **AND** stale prior reports SHALL NOT be accepted as proof.

### Requirement: Reports Agree After Repair

Validation, benchmark/source-fidelity, toolkit build, and publishability reports SHALL agree on final status after repair.

#### Scenario: One report says pass and another says blocked
- **GIVEN** report artifacts disagree after repair
- **WHEN** release proof is evaluated
- **THEN** release proof SHALL fail
- **AND** the stale or contradictory report SHALL be identified.

### Requirement: Remaining Blockers Are Classified Separately

Remaining schema, media, or publication blockers SHALL be classified separately from critical narrative repair.

#### Scenario: Kobe and skull_riddle pass but schema still fails
- **GIVEN** source-fidelity passes after repair
- **AND** schema validation still reports unrelated issues
- **WHEN** final status is reported
- **THEN** source-fidelity repair SHALL be marked complete
- **AND** schema blockers SHALL be listed as separate follow-up items.

## SHOULD Guidance

Prefer a compact final proof note that records command names, statuses, and exact artifact paths changed by the Builder repair pass.
