## ADDED Requirements

### Requirement: Narrator prompt pairs SHALL agree on state authority contracts

Compressed and uncompressed narrator prompts SHALL agree on the authoritative action contracts for same-module travel, cross-module tracker updates, request-roll pause semantics, and scene follower state.

#### Scenario: Same-module movement contract is consistent

- **WHEN** prompt parity tests inspect compressed and uncompressed narrator prompts
- **THEN** both prompts SHALL identify `transitionLocation` as the action for same-module movement
- **AND** neither prompt SHALL present `updatePartyTracker` as the preferred same-module location setter

#### Scenario: Scene follower persistence contract is consistent

- **WHEN** prompt parity tests inspect follower-state guidance
- **THEN** both narrator prompts SHALL describe follower state as deterministic Python-managed state
- **AND** both SHALL align with `updateSceneFollower` or current follower persistence actions

### Requirement: Combat prompt pairs SHALL agree on phase and replay contracts

Compressed and uncompressed combat generation and validation prompts SHALL agree on combat phase authority, deterministic command replay prohibition, mutation routing, and combat exit conditions.

#### Scenario: Enemy phase has no active PC authority in prompt pair

- **WHEN** prompt parity tests inspect combat generation prompts
- **THEN** both compressed and uncompressed prompts SHALL state that ENEMY_PHASE has no active PC actor

#### Scenario: Already-applied replay prohibition is present in prompt pair

- **WHEN** prompt parity tests inspect combat generation and validation prompts
- **THEN** both prompt pairs SHALL prohibit mechanical ops that duplicate `[ALREADY_APPLIED]` deterministic command results

#### Scenario: Final defeat plus exit contract is present in validation prompt pair

- **WHEN** prompt parity tests inspect combat validation prompts
- **THEN** both validation prompts SHALL allow `exit` only when current or same-response post-ops hostile state contains no living hostiles

### Requirement: Runtime-injected context SHALL not contradict prompt contracts

Runtime-injected narrator and combat context blocks SHALL not contradict static prompt authority contracts for the same domain.

#### Scenario: Combat runtime context does not contradict ENEMY_PHASE prompt

- **GIVEN** combat phase is ENEMY_PHASE
- **WHEN** runtime combat context is assembled
- **THEN** it SHALL NOT include static or dynamic text that instructs a PC to act as the current actor
