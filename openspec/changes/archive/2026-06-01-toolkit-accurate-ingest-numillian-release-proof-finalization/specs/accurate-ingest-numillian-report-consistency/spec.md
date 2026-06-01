## ADDED Requirements

### Requirement: Final Reports Agree On Release Status

Numillian finalization SHALL align validation, benchmark/source-fidelity, toolkit build, and publishability reports before release readiness is claimed.

#### Scenario: Reports agree on pass
- **GIVEN** validation, benchmark, toolkit build report, and publishability outputs are refreshed
- **WHEN** final release proof is evaluated
- **THEN** their status fields SHALL agree that the module is ready/publishable/source-fidelity pass.

#### Scenario: Reports disagree
- **GIVEN** one report says pass and another says failed or blocked
- **WHEN** release proof is evaluated
- **THEN** release proof SHALL fail
- **AND** the stale or contradictory artifact SHALL be identified.

### Requirement: Legacy Runtime Files Are Not Required For Publication

Release proof SHALL not require ignored runtime state files for publication.

#### Scenario: Publication artifact review runs
- **GIVEN** Numillian has ignored runtime files such as live area state or live plot state
- **WHEN** publication readiness is evaluated
- **THEN** canonical artifacts SHALL be sufficient without `git add -f`
- **AND** runtime files SHALL remain excluded.

## SHOULD Guidance

Prefer script-owned report refresh over manual report edits whenever an existing script can regenerate the artifact.
