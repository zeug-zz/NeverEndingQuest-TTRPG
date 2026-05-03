# toolkit-mmg-duplicate-authority-preference Specification

## ADDED Requirements

### Requirement: Monster Takes Actor And Media Authority

When an NPC slug and a MONSTER slug are identical and the slug is module monster-authoritative, the MONSTER entry SHALL be the canonical actor, statblock, and media authority for that entity.

#### Scenario: Backup data has both NPC and MONSTER entries for Bandit Captain Gorvek
- **GIVEN** module has `bandit_captain_gorvek` as a module monster JSON/statblock
- **AND** backup area data also has an NPC entry with the same slug
- **WHEN** the unified asset endpoint returns rows
- **THEN** it SHALL return one asset row for `bandit_captain_gorvek`
- **AND** that row SHALL have `type: "monster"`
- **AND** it SHALL NOT return a separate NPC row for that slug

### Requirement: Duplicate NPC Rows Are Suppressed, Not Completed By Delegation

The MMG report SHALL NOT require authority-delegated NPC audit rows for monster-authoritative duplicate slugs.

#### Scenario: Thornwood report is generated for Thane
- **GIVEN** `corrupted_ranger_thane` is module monster-authoritative
- **AND** stale backup NPC data exists for the same slug
- **WHEN** `module_media_generator_report.json` is generated
- **THEN** the report SHALL include the monster audit entry
- **AND** the report SHALL NOT include a duplicate NPC audit entry marked `authority_delegated`
- **AND** the report SHALL NOT count a missing NPC media obligation for that slug

### Requirement: Generation Targets Canonical Monster Rows Only

When the operator triggers MMG image generation, same-slug monster-authoritative actors SHALL be generated or skipped only as monster assets.

#### Scenario: Operator selects all missing Thornwood assets
- **GIVEN** `malarok_the_corruptor` is module monster-authoritative
- **WHEN** selected assets are sent for generation
- **THEN** `malarok_the_corruptor` SHALL be sent at most once
- **AND** the sent payload SHALL identify it as `type: "monster"`
- **AND** no `type: "npc"` generation target SHALL be sent for the same slug

### Requirement: Monster Authority Preserves Parley And Follower UX

Monster-authoritative actors SHALL remain narratively interactable and SHALL NOT be treated as combat-only solely because their asset authority is `monster`.

#### Scenario: Thane is captured and guides the party
- **GIVEN** `corrupted_ranger_thane` is module monster-authoritative
- **AND** the party captures or parlays with Thane instead of fighting him to death
- **WHEN** runtime state tracks him as a durable scene follower
- **THEN** `data/runtime/scene_followers.json` SHALL keep `entity_type: "monster"`
- **AND** the non-combat strip SHALL be allowed to display him when `current_location` matches the party and `visible_in_strip` is true
- **AND** this follower state SHALL NOT require an NPC asset row in MMG

### Requirement: Combat Commitment Still Uses Monster Routing

Formal combat with a monster-authoritative actor SHALL still use monster routing.

#### Scenario: Negotiation with Gorvek fails and combat starts
- **GIVEN** `bandit_captain_gorvek` is monster-authoritative
- **WHEN** a combat commitment point is reached
- **THEN** combat SHALL use `createEncounter.monsters[]` for Gorvek
- **AND** pre-combat dialogue/parley narration before that point SHALL remain valid

## SHOULD Guidance

- The frontend may display dialogue/parley hints on the monster row if useful, but should not reintroduce a duplicate NPC row.
- Transitional `media_authority` metadata may remain during migration, but tests should not require duplicate delegated NPC audit rows as final behavior.
