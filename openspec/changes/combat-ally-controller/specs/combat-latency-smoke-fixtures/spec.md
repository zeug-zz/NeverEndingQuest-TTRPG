# Spec Delta

## ADDED Requirements

### Requirement: G5A SHALL use separate named ally-controller scenarios

The capture ensemble SHALL add distinct `g5a-ally-p1` and `g5a-ally-p4` scenarios in the isolated Capture_Arena module, each with at least one active allied NPC.

#### Scenario: The 1-PC G5A scenario runs
- **WHEN** the primary selects `g5a-ally-p1`
- **THEN** the fixture SHALL use a 1-PC party and at least one active allied NPC
- **AND** the scripted play SHALL include a valid `/cmd` directive that is honored in the ally's next plan
- **AND** the play SHALL include an observed legal authored `take_cover` choice under the existing Python cover contract

#### Scenario: The 4-PC G5A scenario runs
- **WHEN** the primary selects `g5a-ally-p4`
- **THEN** the fixture SHALL use a 4-PC party and at least one active allied NPC
- **AND** the scripted play SHALL include a valid `/cmd` directive that is honored in the ally's next plan
- **AND** the play SHALL include an observed legal authored `take_cover` choice under the existing Python cover contract

### Requirement: G5A captures SHALL prove ally-batch legality and call bounds

G5A SHALL report each accepted ally batch independently from hostile enemy batches and background requests, and SHALL fail closed on missing or ambiguous required observations.

#### Scenario: Ally batches meet their call and legality bounds
- **WHEN** an ally batch is evaluated in a G5A run
- **THEN** it SHALL have at most two synchronous provider calls for its plan and narration
- **AND** every applied ally choice SHALL be legal under the issued Python menu
- **AND** background prefetch requests SHALL be counted separately and SHALL NOT exceed two per ally batch

#### Scenario: G5A observes directive and current defensive behavior per party shape
- **WHEN** the three P1 runs or three P4 runs are aggregated
- **THEN** each party-shape aggregate SHALL contain at least one observed honored `/cmd` directive and one legal authored `take_cover` ally choice
- **AND** missing required observations SHALL be reported as BLOCKED rather than zero-filled or passed

#### Scenario: Allies never flee or surrender through the model path
- **WHEN** the six G5A runs are evaluated
- **THEN** no ally menu or applied model choice SHALL contain flee or surrender
- **AND** any observed ally flee or surrender SHALL fail the gate

### Requirement: G5A scripted combat damage SHALL be legal for its declared weapons

Every scripted damage input in the G5A scenarios SHALL be a legal 5th-edition non-critical damage value for the acting character's declared weapon.

#### Scenario: Scripted damage is checked against authored weapons
- **WHEN** the G5A fixture or report validates scripted `/dmg` inputs
- **THEN** each value SHALL fall within the legal damage range of that actor's declared weapon
- **AND** the check SHALL use the fixture's authored weapon data rather than a guessed damage range

### Requirement: G5A evidence SHALL be isolated and primary-owned

The primary orchestrator SHALL run three independent P1 and three independent P4 G5A captures on one source revision and preserve each run under `tmp/router-rollout/g5a/<run-id>/`.

#### Scenario: A primary G5A live run is captured
- **WHEN** a required G5A live run is authorized after provider-free verification
- **THEN** it SHALL use a real sandbox copy under `tmp/combat_capture/`, port 8360, and `NEQ_OPEN_BROWSER=0`
- **AND** its evidence SHALL record scenario, party, seed, source revision, model/provider identity, expected and observed checks, and artifact paths

#### Scenario: The primary reviews all six runs
- **WHEN** all six required G5A run bundles are available
- **THEN** the primary SHALL assign PASS, FAIL, or BLOCKED from the preserved evidence
- **AND** automated readiness or builder verification SHALL NOT be recorded as the live verdict

### Requirement: G5A SHALL preserve all pre-existing combat compatibility guards

Adding G5A SHALL NOT change the identities or byte-level outputs of G1, G3, G4, G5R, the nine legacy combat prompt hashes, or existing G5T behavior.

#### Scenario: Existing combat gates remain byte-identical
- **WHEN** G5A fixtures and tooling are added
- **THEN** the G1, G3, G4, and G5R compatibility guards SHALL remain byte-identical
- **AND** all nine legacy combat prompt hashes SHALL remain unchanged
- **AND** the existing G5T Gate10 offline re-evaluation SHALL remain byte-identical
- **AND** existing G5T and G5R evidence and goldens SHALL remain unchanged
