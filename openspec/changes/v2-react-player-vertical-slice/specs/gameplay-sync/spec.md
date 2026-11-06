# Spec Delta

## ADDED Requirements

### Requirement: Host-originated gameplay changes SHALL use player-only projected events

After a canonical host-side transcript, active-PC, or initiative/combat change is committed, the server SHALL build a bounded player-safe projection and publish it through the existing ordered `player.event` contract. It SHALL NOT forward host-global emissions or attach player sockets to host broadcasts.

#### Scenario: Host transcript output is committed
- **WHEN** the host runtime commits new transcript output
- **THEN** authenticated player clients receive the projected transcript update once, in monotonic event order, with no host-only payload fields

#### Scenario: Host changes the active PC
- **WHEN** the host selects a PC through the canonical revisioned writer
- **THEN** player clients receive the committed active PC and revision as an ordered projection, while a stale or rejected write publishes no selection change

#### Scenario: Initiative or combat state changes
- **WHEN** the host runtime commits an initiative or combat update
- **THEN** player clients receive the current bounded player projection from canonical state, not a copied host event payload

#### Scenario: Host update races with snapshot hydration
- **WHEN** a canonical host update is committed while a player snapshot is captured or delivered
- **THEN** the existing snapshot cursor and replay boundary deliver the update in the snapshot or as a contiguous event without a missed or double-applied change
