# mmg-creature-to-npc-authority-resolution Specification

## Purpose
TBD - created by archiving change mmg-creature-extraction-npc-authority-guard. Update Purpose after archive.
## Requirements
### Requirement: MMG authority resolution is module-local

The MMG unified-assets endpoint and MMG report generation SHALL decide NPC/monster asset authority using only target-module authored sources and module-local media/statblock artifacts.

The authority decision SHALL NOT depend on current runtime campaign state such as `party_tracker.json`, scene follower state, active party membership, or current location.

#### Scenario: Current party does not affect MMG asset classification

- **GIVEN** a target module contains an authored NPC named `Blarg`
- **AND** the current runtime `party_tracker.json` contains unrelated party members or party NPCs
- **WHEN** `/api/toolkit/modules/<module>/unified-assets` is called
- **THEN** `Blarg` classification SHALL be derived from the target module's authored data only
- **AND** changing current party membership SHALL NOT change whether `Blarg` is returned as `npc` or `monster`

### Requirement: Creature and visibleHostiles extraction tracks weak provenance

The MMG unified-assets endpoint SHALL extract candidate monster names from `location.creatures` and `location.visibleHostiles` in area `_BU.json` files, but those sources SHALL be treated as weak monster-candidate provenance unless the slug is also explicitly module monster-authoritative.

For `location.creatures`:
- The string SHALL be split on commas.
- Each token SHALL be trimmed of leading/trailing whitespace and trailing periods.
- Parenthetical qualifiers SHALL be stripped from each token before slug normalization.
- Empty tokens after stripping SHALL be skipped.

For `location.visibleHostiles`:
- Each entry SHALL be treated as a dict.
- The monster name SHALL be taken from `entry.name` when present, or `entry.monsterType` as fallback.
- Empty or missing names SHALL be skipped.

#### Scenario: creatures field with NPC role qualifiers

- **WHEN** a location has `"creatures": "Ma (commoner), Blarg (half-orc), Skeletons, Red (The Crimson Binder)"`
- **THEN** the extracted weak candidate tokens after stripping SHALL include `Ma`, `Blarg`, `Skeletons`, and `Red`
- **AND** those weak candidates SHALL NOT by themselves suppress matching NPC rows

#### Scenario: visibleHostiles with name field

- **WHEN** a location has `"visibleHostiles": [{"name": "Wight", "monsterType": "Undead"}]`
- **THEN** the extracted weak candidate name SHALL be `Wight`

#### Scenario: visibleHostiles with monsterType fallback

- **WHEN** a location has `"visibleHostiles": [{"monsterType": "Skeleton"}]` and no `name` field
- **THEN** the extracted weak candidate name SHALL be `Skeleton`

### Requirement: Explicit module monster authority is distinguished from weak candidates

A slug SHALL be treated as explicitly module monster-authoritative when it appears in a module-local monster statblock or an explicit structured monster source.

Explicit module monster authority sources SHALL include:
- `modules/<module>/monsters/<slug>.json`
- structured `location.monsters` entries in scanned module area files
- module-local monster seed or closure artifacts that are already treated as module monster authority

Weak `creatures` or `visibleHostiles` extraction SHALL NOT promote a slug to explicit monster authority by itself.

#### Scenario: structured monster remains authoritative

- **WHEN** a location has `"monsters": [{"name": "Wight", "count": 2}]`
- **THEN** `wight` SHALL be explicitly monster-authoritative
- **AND** the monster asset row SHALL be preserved

#### Scenario: weak creature candidate is not explicit authority

- **WHEN** a location has `"creatures": "Blarg (berserker)"`
- **AND** there is no module monster JSON or structured `location.monsters` entry for `blarg`
- **THEN** `blarg` SHALL NOT be explicitly monster-authoritative

### Requirement: NPC authority includes module context, area NPCs, and safe aliases

The MMG unified-assets endpoint SHALL build an NPC authority set from module-local authored NPC sources, including:
- `module_context.json -> npcs`
- `module_context_BU.json -> npcs`, when present
- `npcs_seed.json`, when present
- area `location.npcs[].name` entries from files used by MMG asset scanning

The NPC authority set SHALL include canonical slugs and safe aliases for labels with parenthetical or appositive qualifiers.

#### Scenario: parenthetical NPC alias matches weak creature token

- **GIVEN** module context or area NPC data contains `Ma (Margaret Thornfield)`
- **WHEN** `creatures` contains `Ma (commoner)`
- **THEN** NPC authority SHALL include alias `ma`
- **AND** the weak monster candidate `ma` SHALL be treated as the same authored NPC

#### Scenario: appositive NPC alias matches weak creature token

- **GIVEN** area NPC data contains `Red, The Crimson Binder`
- **OR** module context contains `Red (The Crimson Binder)`
- **WHEN** `creatures` contains `Red`
- **THEN** NPC authority SHALL include alias `red`

### Requirement: Conflict resolution preserves the correct actor authority

After all module-local sources are scanned, the MMG unified-assets endpoint SHALL apply source-aware conflict resolution.

Rules:
- If a slug has explicit monster authority and NPC authority, keep the monster asset row and suppress the duplicate NPC asset row.
- If a slug has NPC authority and only weak monster-candidate provenance, keep the NPC asset row and drop the weak monster candidate.
- If a slug has weak monster-candidate provenance only, keep the monster asset row.
- If a slug has NPC authority only, keep the NPC asset row.

#### Scenario: Night NPC creature token remains NPC

- **GIVEN** `Blarg` is authored as an NPC in module-local NPC authority sources
- **AND** `creatures` contains `Blarg (berserker)`
- **AND** `blarg` has no explicit monster authority
- **WHEN** unified assets are returned
- **THEN** `blarg` SHALL appear as exactly one asset row with `type: "npc"`
- **AND** no `type: "monster"` row for `blarg` SHALL be returned

#### Scenario: Thornwood monster-authoritative actor remains monster

- **GIVEN** `corrupted_ranger_thane` has explicit module monster authority
- **AND** backup area data also contains an NPC entry with the same slug
- **WHEN** unified assets are returned
- **THEN** `corrupted_ranger_thane` SHALL appear as exactly one asset row with `type: "monster"`
- **AND** no `type: "npc"` row for `corrupted_ranger_thane` SHALL be returned

#### Scenario: Weak-only true monster survives

- **GIVEN** `creatures` contains `Skeleton`
- **AND** `skeleton` is not NPC-authoritative
- **WHEN** unified assets are returned
- **THEN** `skeleton` SHALL appear as a monster asset candidate

### Requirement: MMG report mirrors unified-assets authority

The MMG report builder SHALL apply the same source-aware authority rules used by the unified-assets endpoint. It SHALL NOT globally prefer monster audit rows for every same-slug collision.

#### Scenario: Report keeps NPC for weak creature collision

- **GIVEN** assets include an NPC row for `blarg`
- **AND** a weak creature-derived monster candidate for `blarg` exists
- **WHEN** `module_media_generator_report.json` is generated
- **THEN** the report SHALL keep the NPC audit row
- **AND** it SHALL NOT add a missing monster media obligation for `blarg`

#### Scenario: Report keeps monster for explicit monster authority

- **GIVEN** assets include a monster-authoritative row for `bandit_captain_gorvek`
- **AND** stale NPC hint data exists for the same slug
- **WHEN** `module_media_generator_report.json` is generated
- **THEN** the report SHALL keep the monster audit row
- **AND** it SHALL NOT add a duplicate NPC media obligation for that slug

### Requirement: location.monsters extraction remains authoritative

The existing extraction from structured `location.monsters` SHALL remain supported and SHALL be classified as explicit monster authority. This change SHALL NOT weaken or remove structured monster extraction behavior.

#### Scenario: location.monsters extraction unchanged

- **WHEN** a location has `"monsters": [{"name": "Wight", "count": 2}]`
- **THEN** the final assets SHALL contain `wight` with `type: "monster"`
- **AND** this result SHALL not depend on whether `creatures` or `visibleHostiles` also mention `Wight`

