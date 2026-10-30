# Spec Delta

## Purpose

Defines the durable state expected before and after a process restart at each combat-turn commit, phase-synchronization, and success-publication boundary.

## ADDED Requirements

### Requirement: Restart SHALL Converge at Every Approved Turn Boundary

Restart recovery SHALL reuse the persisted `turn_id` and `applied_id`. It SHALL apply only missing mechanical effects, preserve the durable encounter phase snapshot, and never duplicate HP, resource, enemy, reward, or receipt effects.

#### Scenario: Restart follows any partial character-write prefix
- **GIVEN** an injected interruption occurs after a prefix of changed character files is atomically persisted and before the encounter write
- **AND** the pre-commit history record contains the valid manifest for the accepted turn
- **AND** persisted characters contain their turn effects and `last_combat_applied_id`, while remaining characters and encounter are pre-turn and the receipt is absent
- **WHEN** combat restarts through `start_game`
- **THEN** persisted character effects remain unchanged and SHALL NOT be applied again
- **AND** only missing character effects are applied before the encounter receipt is committed
- **AND** the stored success narration SHALL be published once with the original `applied_id`, without a provider call or re-planning

#### Scenario: Restart occurs before the first character write
- **GIVEN** an injected interruption occurs after the input and `turn_id` are durable but before any character write
- **AND** the pre-commit history record contains the valid manifest for the accepted turn
- **WHEN** combat restarts through `start_game`
- **THEN** no mechanical state SHALL be treated as applied
- **AND** the turn SHALL commit once using the original `turn_id` and derived `applied_id`
- **AND** the stored success narration SHALL be published once with that `applied_id`, without a provider call or re-planning

#### Scenario: Restart follows the encounter-last commit
- **GIVEN** an injected interruption occurs after the encounter write and before phase synchronization
- **WHEN** combat resumes
- **THEN** the receipt, character state, encounter state, round, and phase markers SHALL remain committed
- **AND** manager synchronization SHALL use that committed snapshot without replaying turn effects
- **AND** a matching history manifest SHALL be a no-op and need not republish success beyond the existing resume flow

#### Scenario: Restart follows phase synchronization but precedes success
- **GIVEN** an injected interruption occurs after phase synchronization and before success publication
- **WHEN** combat resumes
- **THEN** the committed receipt and phase snapshot SHALL remain unchanged
- **AND** no HP, resource, enemy, or reward effect SHALL be applied again

#### Scenario: Restart follows a success-publication interruption
- **GIVEN** an interruption occurs during or immediately after success publication
- **WHEN** the committed turn is replayed
- **THEN** the runtime SHALL preserve its receipt and committed state without reapplying effects
- **AND** any repeated success publication SHALL remain internally associated with the same `applied_id` without creating a new receipt

### Requirement: Commit Fault Injection SHALL Be Default-Off and Sandbox-Only

`COMBAT_TURN_COMMIT_FAULT_INJECTION_ENABLED` SHALL default to `False`. Runtime fault injection SHALL be denied unless explicitly enabled in the isolated `tmp/combat_capture/` sandbox; production and installed campaign state SHALL never be eligible.

#### Scenario: Fault injection is disabled by default
- **WHEN** the combat runtime starts without an explicit sandbox opt-in
- **THEN** no commit-boundary interruption SHALL be injected

#### Scenario: Fault injection is requested outside the isolated sandbox
- **GIVEN** the fault-injection flag is enabled outside `tmp/combat_capture/`
- **WHEN** the runtime evaluates the injection request
- **THEN** it SHALL deny the request before any gameplay-state write
- **AND** it SHALL continue without injecting a failure

#### Scenario: Provider-free tests inject each boundary
- **GIVEN** a provider-free test explicitly opts into the sandbox-only seam
- **WHEN** it injects each listed interruption boundary and restarts from durable files
- **THEN** observed files SHALL match the required post-restart state in the boundary table
- **AND** no provider or network client SHALL be constructed
