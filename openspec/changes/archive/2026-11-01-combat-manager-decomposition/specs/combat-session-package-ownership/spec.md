# Spec Delta

## Purpose

Defines the combat subsystem package boundary, old-path compatibility surface, and explicit ownership of state for an isolated combat session.

## ADDED Requirements

### Requirement: Combat package exposes stable legacy entry points

The combat subsystem SHALL expose its supported public API from `core/combat/` and SHALL preserve the legacy `core.managers` import paths as thin compatibility shims.

#### Scenario: Existing importer uses the legacy combat manager path
- **WHEN** a production importer or test imports a public combat symbol from `core.managers.combat_manager`
- **THEN** the same symbol and call contract SHALL resolve through the shim
- **AND** the shim SHALL contain fewer than 100 lines

#### Scenario: Existing multi-PC import and monkeypatch path remains usable
- **WHEN** a test or runtime integration imports or patches the existing multi-PC combat public surface through `core.managers.multi_pc_combat`
- **THEN** its documented symbols, callback behavior, and patch target effects SHALL remain available through the compatibility boundary

### Requirement: Combat session owns turn-scoped state

Each active combat session SHALL own its encounter, multi-PC manager, conversation history, active PC, and current phase without relying on mutable module-global session state.

#### Scenario: Session builds a prompt payload from owned state
- **WHEN** the combat runtime prepares a turn request
- **THEN** the history and phase inputs SHALL be derived from the owning session state
- **AND** prior conversation-history entries SHALL NOT be rewritten by literal numeric index

#### Scenario: Two sessions remain isolated
- **WHEN** separate combat sessions are active sequentially or concurrently
- **THEN** changing one session's encounter, history, active PC, or phase SHALL NOT change the other session's state

### Requirement: Existing multi-PC ownership boundaries remain coherent

The combat package SHALL retain the existing multi-PC facade, combat state, turn queue, synchronization, DM-note, and narration responsibilities behind explicit package APIs.

#### Scenario: Multi-PC queue and state are coordinated
- **WHEN** a combat turn reads or updates multi-PC phase and actor state
- **THEN** the existing facade coordination and state/turn-queue synchronization semantics SHALL be preserved

#### Scenario: Shared status manager remains cross-cutting
- **WHEN** combat status output or timers are requested
- **THEN** the existing `core.managers.status_manager` ownership and import path SHALL remain unchanged
