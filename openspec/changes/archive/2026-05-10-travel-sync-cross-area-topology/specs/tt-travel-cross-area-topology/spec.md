## ADDED Requirements

### Requirement: Reconcile-first travel validation SHALL support authored cross-area same-module paths

Runtime travel state synchronization SHALL treat a same-module destination as topology-safe when an authored path exists from the current location to that destination, including paths that cross area boundaries through authored cross-area edges.

#### Scenario: Cross-area return route is accepted through authored graph

- **GIVEN** the party is at `NC02` in `The_Thornwood_Watch`
- **AND** module topology contains `NC02 -> NC01` and `NC01 -> TW05`
- **WHEN** narration or an inferred travel decision targets Bandit Stronghold (`TW05`)
- **THEN** reconcile-first travel validation SHALL treat `TW05` as topology-safe
- **AND** validation SHALL NOT fail solely because `TW05` is outside the current area.

#### Scenario: Direct and same-area routes remain valid

- **GIVEN** a destination is directly adjacent to the current location
- **OR** a destination is reachable under existing same-area rules
- **WHEN** reconcile-first travel validation evaluates the destination
- **THEN** the destination SHALL remain topology-safe under the existing behavior.

### Requirement: Cross-area safety SHALL be graph-based, not catalog-wide

Runtime travel validation SHALL NOT consider every known module location topology-safe merely because it appears in `module_locations`.

#### Scenario: Known but unreachable module location remains blocked

- **GIVEN** a destination exists in the current module catalog
- **AND** no authored graph path connects the current location to that destination
- **WHEN** reconcile-first travel validation evaluates the destination
- **THEN** validation SHALL reject the destination as not topology-safe.

#### Scenario: Unknown destination remains blocked

- **GIVEN** a destination name or ID cannot be resolved to an authored same-module location
- **WHEN** reconcile-first travel validation evaluates the destination
- **THEN** validation SHALL reject the destination
- **AND** SHALL preserve deterministic correction feedback.

### Requirement: Existing travel authority boundaries SHALL remain intact

Cross-area same-module reachability SHALL not bypass existing movement authority, cross-module transition rules, or same-location no-op protections.

#### Scenario: Cross-module destination still requires tracker flow

- **GIVEN** a destination belongs to another module
- **WHEN** reconcile-first travel validation evaluates it as normal same-module travel
- **THEN** validation SHALL NOT mark it topology-safe for `transitionLocation`
- **AND** cross-module travel SHALL continue to require the existing `updatePartyTracker` flow.

#### Scenario: Same-location no-op remains invalid

- **GIVEN** the destination resolves to the current location ID
- **WHEN** reconcile-first travel validation evaluates it
- **THEN** validation SHALL reject it as a no-op transition.

### Requirement: Scene follower guided travel SHALL honor present follower state and topology

Narration involving a present scene follower guiding the party SHALL be valid when the follower is listed in current scene follower truth and the target destination is reachable by authored same-module topology.

#### Scenario: Present follower guides toward reachable cross-area destination

- **GIVEN** `Corrupted Ranger Thane` is listed under `SCENE FOLLOWERS PRESENT HERE` at `NC02`
- **AND** Bandit Stronghold (`TW05`) is reachable from `NC02` by authored topology
- **WHEN** the narrator describes Thane guiding the party toward Bandit Stronghold or an intermediate safer route
- **THEN** validation SHALL NOT reject the response for follower absence
- **AND** validation SHALL NOT reject the response solely for cross-area topology.
