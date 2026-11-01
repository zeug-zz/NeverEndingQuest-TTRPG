# combat-latency-smoke-fixtures Specification

## Purpose
Define fixed, repeatable smoke fixtures for the Phase 0 combat latency baseline.
The fixtures exercise both the multi-PC product path and the 1-PC party path
without changing production combat rules or provider behavior.

## Requirements

### Requirement: The MP fixture SHALL be fixed at four PCs, three rounds, and one enemy batch

The multi-PC latency fixture SHALL use four player characters, execute three
combat rounds, and include one enemy batch. Its actor roster, round count,
phase sequence, and command sequence SHALL be fixed and documented in the
fixture contract.

#### Scenario: MP baseline fixture runs

- **WHEN** the MP fixture is executed with tracing enabled
- **THEN** it SHALL exercise four PC action windows across three rounds
- **AND** it SHALL exercise one enemy-batch window
- **AND** it SHALL emit trace data sufficient to report stages, provider sites,
  compression, file operations, fast-path outcomes, and decisions

### Requirement: The MP fixture SHALL exercise TABLETOP MODE compliance boundaries

The MP fixture SHALL cover the existing initiative/phase gate, roster
integrity, legal PC actor handling, enemy-batch processing, and turn/round
boundaries relevant to latency measurement. The fixture SHALL not introduce
new mechanics or bypass existing combat guards.

#### Scenario: MP compliance remains intact

- **WHEN** the MP fixture completes
- **THEN** initiative and phase markers SHALL remain coherent
- **AND** all four PCs SHALL remain represented without duplicate roster entries
- **AND** the enemy batch SHALL use the existing combat path

### Requirement: The 1-PC party fixture SHALL be fixed at one combat round

The 1-PC party latency fixture SHALL execute one combat round through the
minimum-party tabletop path (ADR-0032). It SHALL be independent of the MP-only
roster setup and SHALL exercise the same observational trace gate.

#### Scenario: 1-PC party baseline fixture runs

- **WHEN** the 1-PC party fixture is executed with tracing enabled
- **THEN** it SHALL complete one combat round
- **AND** it SHALL emit reportable stage and provider-site trace data
- **AND** it SHALL preserve 1-PC party behavior and state authority

### Requirement: Fixtures SHALL support disabled-path verification

Each fixture SHALL be runnable with tracing disabled. The disabled run SHALL
perform zero trace writes and SHALL use the same combat actions and prompts as
the enabled run.

#### Scenario: Disabled fixture run

- **WHEN** either fixed fixture runs with the default trace gate OFF
- **THEN** no trace file SHALL be created or appended
- **AND** the combat result and provider-call behavior SHALL remain unchanged

### Requirement: Fixture failures SHALL identify the failed boundary

Fixture tests SHALL fail with bounded diagnostics that identify the fixture,
round or stage, and violated invariant. Fixture failure handling SHALL NOT add
provider calls or mutate production game state for reporting purposes.

#### Scenario: Fixture invariant fails

- **WHEN** a fixed fixture does not reach its required round, batch, or mode
- **THEN** the verification output SHALL identify the failed fixture contract
- **AND** the report path SHALL remain provider-free

### Requirement: Reusable Scripted Capture Ensemble

The change SHALL provide a reusable scripted capture ensemble for the live
baseline: a lean sandbox copy under `tmp/`, a dedicated `Capture_Arena` capture
module, and scripted capture scenarios (socket-driven driver primary;
`playwright-cli` documented as the browser alternative) that capture 4-PC and
1-PC traces and tear down cleanly. The ensemble SHALL be test tooling and SHALL
NOT change product runtime behavior. It SHALL also expose the G5R selector by
reusing the existing P1/P4 action scripts unchanged and run three distinct
captures per party shape beneath `tmp/router-rollout/g5r/<run-id>/`.

#### Scenario: Sandbox isolation

- **WHEN** the ensemble prepares or runs a capture
- **THEN** the installed tree SHALL remain unchanged
- **AND** all sandbox runtime state SHALL live under `tmp/`

#### Scenario: Capture module role

- **WHEN** a capture scenario needs an arena with walkable locations, combat
  hostiles, and NPC or feature objects
- **THEN** it SHALL use the dedicated `Capture_Arena` module
- **AND** no gameplay state from another installed module SHALL be required

#### Scenario: Scripted 4-PC and 1-PC captures

- **WHEN** the 4-PC and 1-PC scenarios are executed through scripted capture
  scenarios (socket-driven driver primary; `playwright-cli` documented as the
  browser alternative)
- **THEN** each scenario SHALL produce a trace usable by
  `scripts/combat_latency_report.py`

#### Scenario: G5R reuses fixed scenario scripts

- **WHEN** an operator selects G5R for either party shape
- **THEN** the ensemble SHALL use the existing P1/P4 action script and fixture
  identity without modifying its scripted actions
- **AND** it SHALL preserve three unique run IDs and the required per-run
  evidence under the G5R evidence root

#### Scenario: Trace capture and teardown

- **WHEN** a capture completes or fails
- **THEN** the trace SHALL be preserved to a local path under `tmp/`
- **AND** the ensemble SHALL stop the sandbox server and restore sandbox state

#### Scenario: Documented reuse

- **WHEN** a future narration or other gameplay capture is needed
- **THEN** the documented skill and checklist SHALL provide the start/stop
  commands, selectors, and extension points to run it without new test
  infrastructure

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

### Requirement: G5T SHALL provide separate named commander scenarios

The capture ensemble SHALL provide distinct named P1 and P4 commander scenarios using the dedicated Capture_Arena module.

#### Scenario: G5T P1 and P4 selectors run

- **WHEN** the operator selects `g5t-commander-p1` or `g5t-commander-p4`
- **THEN** the capture SHALL use the dedicated Capture_Arena fixtures and preserve artifacts under `tmp/router-rollout/g5t/<run-id>/`
- **AND** each scenario SHALL designate a Hobgoblin Captain commander and include goblins with explicit authored multiattack declarations
- **AND** each scenario SHALL include an explicitly authored cover feature
- **AND** it SHALL record party shape, scenario identity, seed, source revision, model/provider identity, expected and observed checks, and artifact paths

### Requirement: G5T tactical flags SHALL be isolated to its sandbox

G5T MAY enable the tactical brain and resolver flags only in its isolated Capture_Arena sandbox. The installed campaign and shipped defaults SHALL remain unchanged.

#### Scenario: G5T seeder enables only the isolated tactical path

- **WHEN** a G5T sandbox is seeded
- **THEN** tactical brain and resolver flags MAY be enabled in the sandbox only
- **AND** the installed campaign and shipped default flags SHALL remain unchanged
- **AND** selecting G5R SHALL retain its existing resolver-only patch behavior

### Requirement: Existing capture contracts SHALL remain unchanged

Adding G5T SHALL NOT modify existing P1/P4 action scripts or existing G1/G3/G4/G5/G5R fixture identities and evaluator behavior.

#### Scenario: Existing capture contracts are unchanged

- **WHEN** G5T selectors and fixtures are added
- **THEN** existing G1/G3/G4/G5/G5R fixture identities and evaluators SHALL retain their prior behavior
- **AND** the existing P1/P4 action scripts SHALL NOT be edited to represent commander cases

#### Scenario: G5T script supports the Extra Attack fixture

- **WHEN** the G5T P1 or P4 commander script is constructed
- **THEN** Acheron's fixture character SHALL declare the Extra Attack class feature and an equipped training blade with `1d6+2 slashing` damage
- **AND** P1 SHALL contain two Acheron attack/damage pairs in round 3, while P4 SHALL contain two pairs in round 2
- **AND** the covered-target attack/damage pair SHALL remain at steps 2 and 3 in both party shapes
- **AND** a missed covered attack SHALL skip only its paired damage row; a later same-PC attack and damage row SHALL remain eligible
- **AND** G5T step counts and request/control caps SHALL be derived from its revised script, without changing legacy gate fixtures or hashes

#### Scenario: G5T preserves legal damage and a bloodied Goblin decision

- **WHEN** the scripted Goblin and PC attacks are evaluated
- **THEN** each `/dmg` input SHALL be within the minimum-to-maximum non-critical total damage range parsed from the acting PC's declared weapon damage string
- **AND** the HP trajectory SHALL be checked for both hit and miss outcomes of the covered-target attack, including the driver's paired-damage skip on a miss
- **AND** a Goblin SHALL be alive at 3/7 HP at an `/end` in both covered-target branches for P1 and P4
- **AND** the Captain SHALL remain alive at 9/39 HP at a near-death `/end` so surrender remains legal; P4 SHALL have this opportunity at round 4 and again at round 5 after the goblins have fled or been defeated
- **AND** all enemies SHALL be defeated by the final scripted PC attacks in both branches
- **AND** each script SHALL follow those attacks with a distinct DM `/end` batch that runs existing combat-exit and XP handling
- **AND** the sent closing batch SHALL wait for `combat_exit_complete` before after-run capture; a closing batch after an earlier exit SHALL be recorded as skipped with `combat_ended`
- **AND** the script SHALL make flee and cover available as model choices, not forced outcomes

### Requirement: G5T SHALL script per-creature self-preservation evidence

Each named commander capture SHALL include an eligible per-creature flight choice and preserve authoritative evidence of its result.

#### Scenario: G5T flight is observable
- **WHEN** a scripted living creature flees in a G5T capture
- **THEN** its applied action SHALL be Disengage and it SHALL make no attack that turn
- **AND** its encounter status SHALL be `defeated` with `defeatReason=fled`
- **AND** it SHALL be absent from subsequent actor and target menus while the remaining encounter state stays coherent
