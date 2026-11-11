# Spec Delta

## Purpose

Defines isolated, reproducible tooling for preparing and evaluating the preregistered mapping pilot without changing production gameplay, published content, or model routing.

## ADDED Requirements

### Requirement: Preregistration integrity gates sandbox fixture generation
The tooling MUST verify every listed source hash in `plans/v2-mapping-pilot-prereg/MANIFEST.sha256` before generating pilot fixture output. Generated module data and scoring properties MUST remain inside the `tmp/combat_capture/` sandbox copy and MUST NOT enter the repository's `modules/` tree or published-module catalog.

#### Scenario: Frozen source files verify
- **WHEN** pilot fixture generation starts with matching preregistration files
- **THEN** it generates the spatial fixture module and expected-property files deterministically inside `tmp/combat_capture/` only

#### Scenario: Frozen source hash mismatches
- **WHEN** any listed fixture, script, rubric, README, or counterbalance hash differs from the manifest
- **THEN** generation fails before changing pilot fixture output and reports the mismatched relative path

#### Scenario: Sandbox fixture module is generated
- **WHEN** all four preregistered truth fixtures are seeded
- **THEN** the sandbox contains a module representation for them and derived expected-property files, while `modules/published_modules.json` and repository `modules/` remain unchanged

### Requirement: Opt-in seeding preserves the existing default
Mapping-pilot seeding MUST require explicit pilot options, accept only seeds listed in the frozen counterbalance, support both 1-PC and 4-PC parties, and record the effective seed. Invoking the existing seeder without pilot options MUST preserve its prior behavior and output bytes.

#### Scenario: Existing seeder invocation omits pilot options
- **WHEN** the seeder is invoked through its existing default path
- **THEN** no mapping-pilot fixture, arm, or seed behavior is activated and its prior seeded bytes remain unchanged

#### Scenario: Preregistered row is seeded
- **WHEN** an explicit pilot fixture, arm, party size, and allowed preregistered seed are supplied
- **THEN** the selected fixture is seeded for the requested 1-PC or 4-PC roster and the effective seed is recorded in sandbox metadata

#### Scenario: Seed or option is outside the preregistration
- **WHEN** a pilot seed, fixture, arm, or party size is not permitted by the preregistered contract
- **THEN** the seeder rejects the request before mutating sandbox state

### Requirement: Prototype layouts respect party knowledge and viewpoint
The prototype layout contract MUST preserve stable location, feature, NPC, and exit identities while exposing only facts the party can perceive or already knows from the current viewpoint. Hidden facts and unperceived exits MUST NOT be projected; unknown destinations MUST be labelled `unknown`, layout positions MUST be labelled `schematic`, and distances MUST appear only when explicitly authored.

#### Scenario: Party viewpoint changes
- **WHEN** a 4-PC row changes its active PC or viewpoint
- **THEN** the projection uses that viewpoint's permitted facts without changing shared party knowledge or relocating stable anchors

#### Scenario: Hidden contents and unperceived exits exist
- **WHEN** a layout contains hidden facts, or an exit is not perceived by the party
- **THEN** those facts and exits are absent from the packet, and their absence is not described as proof of nonexistence

#### Scenario: Destination or distance is unknown
- **WHEN** the fixture marks a destination unknown or has no authored distance
- **THEN** the packet labels the destination unknown and emits no inferred distance

### Requirement: B and D projections are deterministic and semantically equivalent
B MUST render explicit relationship statements. D MUST render an ASCII schematic plus the same relationship statements from the same filtered facts, with no additional facts. Both MUST include the exact shared instruction: `Use these places as the stable stage of the scene. Refer to landmarks naturally when relevant; do not recite the map, coordinates or this note.` The packet bytes and hash MUST be deterministic for the same inputs.

#### Scenario: B and D use the same filtered projection
- **WHEN** B and D are rendered from one fixture, party, viewpoint, and turn snapshot
- **THEN** their semantic facts and instruction text are identical, with only the D schematic added

#### Scenario: Re-render uses unchanged inputs
- **WHEN** the same projection is rendered more than once
- **THEN** each representation has identical bytes and the same packet hash

### Requirement: Sandbox adapter isolates arms and preserves packet identity
The adapter MUST run only through an explicit sandbox launcher option and MUST wrap the existing DM-note and combat-prompt seams without editing core files. Arm A MUST disable augmentation. B/D packets MUST remain byte-identical through normal prompt construction, validation retries, and transitions within one logical turn, and each prompt use MUST be represented in per-turn packet-hash evidence.

#### Scenario: Arm A is selected
- **WHEN** arm A is seeded and the sandbox launcher starts
- **THEN** the adapter is disabled and both the DM note and combat prompt are byte-identical to their unwrapped outputs

#### Scenario: B or D is selected for exploration
- **WHEN** a sandbox exploration prompt is built
- **THEN** the selected projection is added at the DM-note seam and no production prompt source is modified

#### Scenario: D is selected for combat
- **WHEN** a sandbox combat prompt is built
- **THEN** the D zone schematic and its relationship statements are added at the combat-prompt seam; B is not run as a combat arm

#### Scenario: A logical turn retries or transitions
- **WHEN** the same logical turn invokes a prompt again for validation retry or location transition
- **THEN** the adapter reuses the first packet bytes and records the same packet hash for that turn

#### Scenario: Existing sandbox seam cannot be verified
- **WHEN** the initial seam verification fails in the sandbox copy
- **THEN** implementation stops without adding a core hook; any environment-gated `# TABLETOP MODE:` hook requires explicit owner approval in a separately authorized scope

### Requirement: Combat zone ledger is shadow-only
The combat ledger MUST derive zones, adjacency, elevation, pairwise cover, occupants, engagement groups, movement allowances, and deterministic enemy policy from `fixtures/combat_stage_tavern.json`. It MUST record observations without vetoing narration, attacks, movement, or changing mechanical combat state.

#### Scenario: 1-PC or 4-PC combat row starts
- **WHEN** a preregistered combat fixture is initialized
- **THEN** party and enemy placements, engagement groups, and tie-break policy match the selected party-size fixture

#### Scenario: Movement hint is returned
- **WHEN** a sandbox combat response includes the optional top-level `movement_hint` with `from`, `to`, `disengage`, and `cover_sought`
- **THEN** tooling records and checks it against adjacency and the one-step standard or two-step extended allowance, without adding a gameplay action or vetoing the response

#### Scenario: Movement hint is invalid or absent
- **WHEN** a hint is invalid, or the response contains no hint
- **THEN** the ledger records invalid or missing observation data and does not change mechanical state or invent a move

#### Scenario: Narration contradicts ledger truth
- **WHEN** observed narration conflicts with engagement, cover, line of sight, elevation, actor placement, or movement allowance
- **THEN** the contradiction is counted in the shadow trace and the narration remains unmodified

### Requirement: Scoring preserves preregistered measures and caps
Scoring MUST implement the preregistered objective measures, separate regression guards, unknown-not-zero cost handling, per-arm resolved-model distributions, and hard request/time accounting. It MUST flag a resolved-model share difference of at least 10 percentage points from arm A and report any per-arm fallback-share or unknown-model-share difference.

#### Scenario: Spatial or combat score has no denominator
- **WHEN** a row has no spatial references or no observed combat rounds for a rate
- **THEN** the rate is reported as `not estimable`, never zero

#### Scenario: Cost or token data is unavailable
- **WHEN** input/output token, cost, or latency data is unknown or incomplete
- **THEN** that measure remains `unknown` and is not represented as zero

#### Scenario: Candidate arm has a route imbalance
- **WHEN** a resolved-model share differs from arm A by at least 10 percentage points, or fallback/unknown-model incidence differs by arm
- **THEN** the scorer flags and reports the imbalance as a confound without pinning a downstream model

#### Scenario: Live request or time cap is reached
- **WHEN** a pilot row reaches 35 provider attempts or 25 minutes, or the matrix reaches 800 attempts or 6 hours
- **THEN** no further pilot request is sent and the row or matrix remains failed or blocked with actual counts preserved

#### Scenario: Per-row evidence is written
- **WHEN** a pilot row's evidence bundle is finalized
- **THEN** evidence is stored under `tmp/router-rollout/mapping-pilot/<gate>/<run-id>/` with source/worktree identity, fixture/script/scenario hashes, arm/party/seed, requested and resolved route identity, exact packets and hashes, transcript, state snapshots, zone trace, expected/observed checks, cap counts, logs, and verdict

### Requirement: M1 sketches use the filtered projection
The M1 renderer MUST produce deterministic ASCII sketches for preregistered fixtures and validated D1 layouts using the same party-knowledge filter, schematic labels, and authored relationships as the packet projection. It MUST NOT infer metric distances or add web/client behavior.

#### Scenario: Fixture sketch is rendered
- **WHEN** M1 renders a fixture for a party viewpoint
- **THEN** only the viewpoint-filtered anchors and relationships appear with schematic labelling

#### Scenario: D1 sketch is rendered
- **WHEN** M1 renders a validated D1 layout
- **THEN** the sketch contains only the validated layout's anchors and relations and does not add inferred exits or distances

### Requirement: D1 cartographer tooling is bounded and non-publishing
D1 tooling MUST support Python extraction for about 20 locations from three configured published modules, a per-location prompt, validation of IDs, exits against the existing graph, and layout schema shape, plus audit-sheet generation. Any future live run MUST be capped at 60 calls, use an injected client, and write only under project-relative `tmp/`; live execution is not part of this change's build and requires later owner go-ahead.

#### Scenario: Provider-free D1 tooling test
- **WHEN** extraction, prompt construction, validation, or audit-sheet generation is tested
- **THEN** a fake client is used and no provider call or write to `modules/` occurs

#### Scenario: D1 live call cap is exhausted
- **WHEN** a later owner-authorized D1 run reaches 60 calls
- **THEN** it makes no further call and preserves the partial audit output under `tmp/`

#### Scenario: D1 layout fails validation
- **WHEN** a proposed layout contains duplicate or unknown IDs, exits absent from the existing graph, or invalid schema shape
- **THEN** the validator rejects that layout and the audit sheet records the specific validation issue

### Requirement: Pilot tooling stays within repository and runtime boundaries
Pilot Python source MUST carry the repository Fair Source SPDX header and remain ASCII-only. Pilot JSON state writes MUST use existing atomic helpers. All generated files MUST use project-relative `tmp/` paths; production defaults, `model_config.py`, core files, published modules, installed campaign, `web/`, `MULTIPLAYER_MODE`, party-size gates, and port 8357 MUST remain unchanged.

#### Scenario: Provider-free validation suite runs
- **WHEN** the pilot tooling test suite is run
- **THEN** tests make no provider calls, cover every fixture for both 1-PC and 4-PC dry seeding, and include arm-A byte-parity checks

#### Scenario: Production boundary is checked
- **WHEN** the tooling change is verified
- **THEN** changes are limited to `scripts/` and this OpenSpec change, and no server is started or port 8357 inspected or used
