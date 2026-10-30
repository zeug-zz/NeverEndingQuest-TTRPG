# Spec Delta

## ADDED Requirements

### Requirement: G5 SHALL add an isolated capture gate without changing defaults

The existing capture rig SHALL accept `g5` as an added gate and SHALL continue to default to `g3`; G3 and G4 selectors, fixture behavior, evidence paths, and evaluators SHALL remain unchanged.

#### Scenario: Capture runs without a gate argument
- **WHEN** the existing capture driver is invoked without `--gate`
- **THEN** it SHALL retain the existing G3 default and output contract

#### Scenario: G5 capture is selected
- **WHEN** an authorized capture is invoked with `--gate g5`
- **THEN** its evidence SHALL be written beneath `tmp/router-rollout/g5/<run-id>/`
- **AND** it SHALL NOT write into G1, G3, or G4 evidence roots

#### Scenario: Existing G3 and G4 evaluators run
- **WHEN** the existing G3 or G4 evidence is evaluated
- **THEN** its evaluator behavior and output SHALL remain byte-for-byte unchanged

### Requirement: G5 SHALL use the fixed 4-PC and 1-PC fixtures

Each G5 before and after capture SHALL use the existing default 4-PC latency script (historical label `4 PCs x 3 rounds + 1 enemy batch`), unchanged, and the existing 1-PC/one-round command script with the same seed and measurement method.

#### Scenario: G5 captures the multi-PC fixture
- **WHEN** the G5 multi-PC fixture is captured
- **THEN** it SHALL run the existing default 4-PC latency script (historical label `4 PCs x 3 rounds + 1 enemy batch`), unchanged
- **AND** observed rounds, steps, and enemy batches SHALL be recorded, not asserted beyond the script
- **AND** it SHALL preserve the existing phase, roster, initiative, and enemy-batch boundaries

#### Scenario: G5 captures the minimum-party fixture
- **WHEN** the G5 1-PC fixture is captured
- **THEN** it SHALL exercise one PC through one combat round
- **AND** it SHALL use the tabletop runtime without an MP-only roster setup

### Requirement: Capture_Arena Goblin fixtures SHALL declare one attack per turn

The existing Capture_Arena 1-PC and 4-PC encounter fixtures SHALL set the Goblin's existing `numAttacks` field explicitly to `1`, matching the SRD Goblin's one Scimitar OR Shortbow attack per turn and preventing selectable attack types from becoming multiple prerolls.

#### Scenario: The 1-PC encounter fixture is seeded
- **WHEN** the Capture_Arena 1-PC encounter fixture is seeded
- **THEN** the Goblin encounter data SHALL contain `numAttacks: 1`
- **AND** preroll setup SHALL not present two attacks for its Scimitar and Shortbow choices

#### Scenario: The 4-PC encounter fixture is seeded
- **WHEN** the Capture_Arena 4-PC encounter fixture is seeded
- **THEN** the Goblin encounter data SHALL contain `numAttacks: 1`
- **AND** preroll setup SHALL not present two attacks for its Scimitar and Shortbow choices

#### Scenario: General preroll count inference is considered
- **WHEN** fixture coverage identifies the generator's general attack-count inference defect
- **THEN** this change SHALL record it as an out-of-scope owner follow-up
- **AND** it SHALL NOT modify the general generator behavior

### Requirement: G5 evidence bundles SHALL support an auditable before/after pair

Each G5 bundle SHALL have a distinct run ID and record fixture, party size, seed, measurement method, provider/model identity, current worktree/source digest, and required capture artifacts.

#### Scenario: Before reference is recorded
- **WHEN** the G5 before capture is completed
- **THEN** its bundle SHALL be preserved under its unique G5 run directory before any runtime optimization edit
- **AND** it SHALL record the source digest and direct OpenAI `gpt-6-luna` identity

#### Scenario: After capture is recorded
- **WHEN** the G5 after capture is completed
- **THEN** it SHALL use a different run ID and the same fixture, party size, seed, provider/model, and measurement method as the before capture
- **AND** its trace and capture receipts SHALL be preserved in its own G5 run directory

#### Scenario: Before evidence is not available
- **WHEN** the required G5 before bundle is absent
- **THEN** optimization implementation tasks SHALL remain blocked
- **AND** a mock, builder report, or driver exit code SHALL NOT satisfy the live capture requirement

#### Scenario: Historical G1 evidence is referenced
- **WHEN** the G5 evidence bundle cites the archived G1 capture
- **THEN** it SHALL preserve G1's original gpt-5.6-luna identity
- **AND** it SHALL NOT relabel G1 as the G5 before capture
