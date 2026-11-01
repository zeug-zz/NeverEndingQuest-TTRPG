# core-live-verification Specification

## Purpose

Define a bounded, reproducible G4 Capture_Arena extension that proves routed core narrator and combat behavior with primary-owned evidence while retaining the existing G3 gate contract.

## Requirements

### Requirement: Gate Selector Preserves G3 and Adds Only G4

The existing capture rig SHALL accept a fixed `--gate` selector with `g3` as the unchanged default and `g4` as the only added gate. G4 evidence SHALL be written beneath `tmp/router-rollout/g4/`; existing G3 paths, defaults, 18 raw bundle compatibility, and standalone latency/G5 scripts SHALL remain unchanged.

#### Scenario: Default invocation remains G3 compatible

- **WHEN** the existing capture rig is invoked without `--gate`
- **THEN** it SHALL select G3 and preserve its existing CLI, fixtures, evidence layout, and report behavior

#### Scenario: G4 uses a separate evidence root

- **WHEN** the rig runs an authorized G4 capture
- **THEN** its unique run bundle SHALL be rooted at `tmp/router-rollout/g4/<run-id>/`
- **AND** it SHALL NOT overwrite or reclassify G3 or latency artifacts

### Requirement: G4 Requires Four Named Core Captures

The G4 matrix SHALL require `narrator-dialogue-travel` and `combat-smoke` for both one-PC and four-PC parties. Each run SHALL record exact roster/active-PC identity, scenario/seed, routed operation receipts, selected provider/model observations, and expected-versus-observed checks.

#### Scenario: G4 matrix includes each operation and party shape

- **WHEN** the G4 matrix is evaluated
- **THEN** all four required keys SHALL be present: `narrator-dialogue-travel:p1`, `narrator-dialogue-travel:p4`, `combat-smoke:p1`, and `combat-smoke:p4`
- **AND** missing or mismatched identity/evidence SHALL leave the key incomplete

#### Scenario: Normal G4 path observes configured transport

- **WHEN** a narrator or combat capture succeeds under the approved configuration
- **THEN** receipts SHALL show direct OpenAI and the selected/resolved model when available
- **AND** an unexpected fallback, missing required receipt, or unsupported cost claim SHALL prevent PASS

### Requirement: Narrator Capture Uses Separate Fixed Safe Scenarios

The narrator matrix SHALL isolate CA01 initial-scene/no-active-combat from peaceful SANDBOX-only CA02 transition coverage and use CA03's authored Mira area NPC. Sandbox seed and live inputs SHALL remain consistent through BU hydration without changing root-authored data or production mechanics.

#### Scenario: Peaceful CA02 seed survives hydration

- **WHEN** the sandbox narrator fixture is prepared
- **THEN** it SHALL transform the copy at `tmp/combat_capture/modules/Capture_Arena/areas/CTR001_BU.json` and the corresponding `CTR001.json` live-area input so seeding and later `initialize_game_files_from_bu` hydration produce the same peaceful scene
- **AND** copied plot/context SHALL change only if fixture consistency requires it; root-authored `_BU` files SHALL remain unchanged
- **AND** the fixture SHALL NOT patch a running server or add magic flags

#### Scenario: Five-turn narrator dialogue and travel path

- **WHEN** the named narrator scenario runs
- **THEN** it SHALL start at CA01 with no active combat, visit named CA02 and CA03 rooms, ask Mira a shrine question, return through CA02 to CA01, and use the four-PC active-PC switch to Merisiel where specified
- **AND** the five-turn sequence, roster, and character identifiers SHALL remain exact

#### Scenario: Narrator bounds and fixture safety

- **WHEN** the narrator capture is prepared or executed
- **THEN** the applicable limits SHALL be at most 6 inputs and 8 controls for one PC, or 6 inputs and 9 controls for four PCs, with initial start and active-PC switch included in the declared control budget
- **AND** each narrator turn SHALL have the predeclared 300-second capture-only cap
- **AND** read-only health observations SHALL be separately bounded and counted

#### Scenario: Mira record follows the actual reader requirement

- **WHEN** the capture needs Mira data to exercise dialogue
- **THEN** the fixture SHALL use CA03's authored area NPC and actual runtime read path
- **AND** it SHALL seed a canonical schema-valid NPC record with the reader's required fields only if that reader requires persisted NPC data
- **AND** it SHALL NOT create an unnecessary PC character file or generate media

#### Scenario: G4 location projection is an explicit tooling addition

- **WHEN** the narrator evidence is evaluated
- **THEN** G4 tooling SHALL add allowlisted read-only `currentLocation` and `currentLocationId` projection fields (not assumed to exist in the current rig) and compare them with source-derived expected room IDs
- **AND** persisted party/active-PC state SHALL match the declared case without ignored flags or production changes

### Requirement: Combat Capture Uses Existing Bounded Smoke Contracts

G4 combat smoke SHALL reuse the deterministic seeded combat scenario with five inputs/seven controls for one PC and twenty-two inputs/thirty-five controls for four PCs, with a 300-second capture-only turn cap for both. A random encounter SHALL NOT be treated as the named seeded Goblin Alpha fixture.

#### Scenario: Combat evidence matches the declared seed

- **WHEN** a combat-smoke capture is run
- **THEN** the actual seed, roster, encounter identity, and active party shape SHALL match the declared fixture
- **AND** expected combatant identity SHALL not be inferred from a separately randomized encounter

#### Scenario: Combat capture reaches a required cap or timeout

- **WHEN** an input, control, read-only health observation, or declared capture cap times out, exceeds its limit, or lacks required data
- **THEN** the run SHALL be marked FAIL or BLOCKED with a named fail-stop reason
- **AND** no further queued input SHALL be sent

### Requirement: G4 Evidence Is Primary-Owned and Source-Grounded

G4 evidence SHALL be derived from persisted sandbox projections and actual router receipts, not from declarations, input echoes, or synthetic accounting. Capture tooling SHALL provide allowlisted current-location/current-location-ID projections, expected room identity checks, actual NPC response distinct from input echo, party/active-PC checks, and receipt-backed task/retry/fallback/usage observations.

#### Scenario: State and NPC assertions use observations

- **WHEN** a G4 bundle reports travel, dialogue, party, or active-PC evidence
- **THEN** it SHALL reference read-only persisted projected state and actual backend NPC response separately from input echo
- **AND** unsupported, missing, or mismatched observations SHALL fail or block the check

#### Scenario: Primary evaluates after focused tests

- **WHEN** the G4 tooling and provider-free tests are complete
- **THEN** the primary orchestrator SHALL execute and judge the required fresh narrator and seeded combat captures
- **AND** a builder report, mock, synthetic receipt, process exit code, or declared expected value SHALL NOT constitute live PASS evidence
