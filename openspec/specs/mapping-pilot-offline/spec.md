# mapping-pilot-offline Specification

## Purpose
Defines reproducible offline mapping-pilot artifacts: source-bound D1 proposals and review evidence, plus preregistered fixture and D1 sketches with blank SP4 rating sheets.

## Requirements

### Requirement: D1 location selection SHALL be deterministic and stratified

The D1 selection SHALL include exactly 7 locations from `Keep_of_Doom`, 6 from `The_Thornwood_Watch`, and 7 from `The_Pumpkin_Kings_Curse`. Within each module, locations SHALL be grouped by their authored area type, location IDs sorted within each type, and selected round-robin across the types until the module quota is met.

#### Scenario: Selection meets the fixed module quotas
- **WHEN** the selector reads the three approved modules and their authored area records
- **THEN** it emits the fixed 7/6/7 module counts using the authored area types and deterministic ordering
- **AND** repeating selection over identical source bytes emits the same location order

#### Scenario: A module cannot supply its fixed quota
- **WHEN** the selector cannot find enough eligible locations for one approved module
- **THEN** it refuses the selection rather than silently reducing a quota or substituting a module

### Requirement: D1 selection SHALL bind locations to source provenance

Before any provider call, the selection record SHALL bind every selected location to its module, authored area type, source path or paths, SHA-256 for each source file, and the repository commit observed when selection was recorded. The D1 runner SHALL verify those source hashes before calling the provider.

#### Scenario: Selection record is created before live execution
- **WHEN** a valid D1 selection is finalized
- **THEN** its record contains each location's source paths and matching SHA-256 values plus the repository commit
- **AND** the record exists before the first provider call can occur

#### Scenario: Selected source bytes changed after selection
- **WHEN** the D1 runner finds a source file whose SHA-256 differs from the selection record
- **THEN** it refuses to make a provider call using that selection

### Requirement: D1 routed calls SHALL preserve route and usage receipts

Each cartographer client invocation SHALL use the existing `production-auto` route without pinning a downstream model or changing model configuration. Its receipt evidence SHALL retain requested and resolved model, transport and observed provider, fallback status, usage, and usage completeness; unavailable values SHALL remain explicitly unknown. A router failure or quota outcome SHALL be retained as a failed invocation and consume one D1 call slot.

#### Scenario: Routed D1 invocation returns
- **WHEN** the live adapter sends one cartographer prompt through the existing router
- **THEN** the client returns the router's JSON result to cartography
- **AND** the D1 evidence contains every receipt event and its route and usage fields, preserving unknown values

#### Scenario: Routed D1 invocation fails
- **WHEN** the existing router reports an error or quota outcome for a cartographer prompt
- **THEN** the failure and available receipt fields are retained, the invocation consumes one call slot, and no new fallback policy is introduced by the adapter

### Requirement: D1 execution SHALL require a valid selection and stay within its evidence boundary

The D1 runner SHALL refuse execution without a valid selection record and SHALL stop before issuing a 61st cartographer client invocation. D1 run artifacts SHALL be written only below `tmp/router-rollout/mapping-pilot/d1/<run-id>/`; no D1 output SHALL be written to `modules/`.

#### Scenario: D1 run is requested without its selection record
- **WHEN** the D1 command is invoked without a valid selection record
- **THEN** it refuses before invoking the client or making a provider call

#### Scenario: D1 call cap is reached
- **WHEN** the durable D1 ledger already contains 60 client invocations
- **THEN** the runner refuses another invocation and preserves the existing ledger and audit evidence

#### Scenario: D1 run writes artifacts
- **WHEN** the D1 runner persists selection-bound proposals, receipts, and audit data
- **THEN** every run artifact is inside that run's D1 evidence directory and no file under `modules/` is modified

### Requirement: D1 audit evidence SHALL leave owner judgments unfilled

The D1 audit sheet SHALL expose proposed feature claims, exit-side claims, and explicit visibility, perceivability, or sightline claims from layout data for owner review. It SHALL display the S3 threshold of at least 85% owner-audited precision and zero invented exits separately from observed values. Per-claim owner ratings and aggregate precision values SHALL remain blank until the owner supplies them; the tooling SHALL NOT invent audit judgments or issue the S3 decision.

#### Scenario: Audit sheet is generated for D1 proposals
- **WHEN** the runner generates an audit sheet from proposal results
- **THEN** it lists the available feature, exit-side, and explicit visibility/perceivability/sightline claims with blank owner-rating fields
- **AND** owner precision numerator, denominator, and percentage remain blank
- **AND** the threshold is shown as criteria, not a result or verdict

### Requirement: M1 outputs SHALL cover the preregistered fixture and D1 sketch set

The M1 run SHALL render all four frozen fixture layouts and each preregistered P1/P4 viewpoint where the fixture defines one, plus every validated D1 layout. It SHALL write sketches and a separate owner rating sheet below `tmp/router-rollout/mapping-pilot/m1/<run-id>/`; the sheet SHALL show the 3.5 legibility/usefulness decision threshold and SHALL state that sketch format is visible, so blinding is partial.

#### Scenario: M1 run renders the complete input set
- **WHEN** the M1 generator receives the frozen fixtures and D1 run results
- **THEN** it emits a sketch for each of the four fixtures, each fixture-defined P1/P4 viewpoint, and each validated D1 layout
- **AND** it emits no D1 sketch for a layout that did not validate

#### Scenario: M1 owner rating sheet is generated
- **WHEN** the M1 generator writes the owner review packet
- **THEN** the sheet has separate legibility and usefulness fields, each blank and bounded to ratings 1 through 5
- **AND** it identifies 3.5 as the threshold for both legibility and usefulness without deciding whether the threshold is met
- **AND** it discloses that sketch format is visible and makes no full-blinding claim
- **AND** no rating value is prefilled
