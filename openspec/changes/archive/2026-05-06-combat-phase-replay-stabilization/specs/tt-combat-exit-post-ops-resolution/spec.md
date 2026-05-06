## ADDED Requirements

### Requirement: Combat exit guard SHALL evaluate supported same-response enemy defeat ops

When a combat response includes `exit` while current encounter state still has living hostiles, deterministic phase-integrity validation SHALL simulate supported same-response enemy ops before deciding whether exit is premature.

Supported initial ops SHALL include `hp_delta`, `set_hp`, and `set_status` for enemy targets.

#### Scenario: Exit allowed after same-response final defeat

- **GIVEN** the encounter has one living hostile with 8 HP
- **WHEN** a combat response includes `updateEncounter.ops` setting that hostile to 0 HP or defeated status
- **AND** the same response includes `exit`
- **THEN** deterministic phase-integrity validation SHALL allow the response to proceed

#### Scenario: Exit blocked when hostiles remain after simulation

- **GIVEN** the encounter has two living hostiles
- **WHEN** a combat response defeats only one hostile and includes `exit`
- **THEN** deterministic phase-integrity validation SHALL reject the response

#### Scenario: Exit blocked when relevant HP op is malformed

- **GIVEN** the encounter has a living hostile
- **WHEN** a combat response includes `exit`
- **AND** the proposed HP op for that hostile has a malformed amount
- **THEN** simulation SHALL be indeterminate
- **AND** deterministic phase-integrity validation SHALL reject exit with correction guidance

### Requirement: Exit simulation SHALL be conservative

Exit simulation SHALL NOT default malformed or unknown relevant enemy state to defeated. If current state has living hostiles and proposed ops cannot be confidently applied, exit SHALL remain blocked.

#### Scenario: Unknown relevant target does not allow exit

- **GIVEN** the encounter has a living hostile named `Bandit Captain`
- **WHEN** a combat response includes `exit` and an enemy defeat op targeting an unknown or ambiguous name
- **THEN** deterministic phase-integrity validation SHALL NOT treat the known hostile as defeated
- **AND** exit SHALL be rejected while that hostile remains living
