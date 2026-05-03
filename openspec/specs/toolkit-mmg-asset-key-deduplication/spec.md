# toolkit-mmg-asset-key-deduplication Specification

## Purpose
TBD - created by archiving change toolkit-mmg-asset-authority-collision-fix. Update Purpose after archive.
## Requirements
### Requirement: Type-Qualified Asset Key

The MMG frontend SHALL construct a qualified asset key as `"<type>:<id>"` for row identity, selection, and thumbnail DOM identity.

#### Scenario: Asset rows have stable type-qualified keys
- **GIVEN** the MMG table renders monster asset `bandit_captain_gorvek`
- **WHEN** the row is created
- **THEN** the MONSTER row SHALL use key `monster:bandit_captain_gorvek`
- **AND** a true NPC row, if present for a different slug, SHALL use key `npc:<npc_slug>`

### Requirement: Independent Selection

Selection state SHALL be tracked per qualified key.

#### Scenario: Selecting one asset does not select another asset
- **GIVEN** a module with a MONSTER row and a true NPC row
- **WHEN** the operator checks the MONSTER row
- **THEN** only the MONSTER row SHALL be selected
- **AND** the NPC row SHALL remain unchecked

### Requirement: Independent Thumbnail DOM IDs

Thumbnail DOM IDs SHALL include the qualified key to prevent cross-row overwrite.

#### Scenario: Loading a MONSTER thumbnail does not overwrite another row
- **GIVEN** MONSTER and true NPC rows are present in the MMG table
- **WHEN** `loadAssetThumbnail()` resolves the MONSTER thumbnail
- **THEN** the MONSTER row's thumbnail container SHALL be populated
- **AND** every other row's thumbnail container SHALL be unaffected

### Requirement: Media Folder Routing

`viewAssetMedia()` and `loadAssetThumbnail()` SHALL route to the correct media folder based on asset type.

#### Scenario: Viewing MONSTER Bandit Captain Gorvek
- **GIVEN** asset type `monster` and id `bandit_captain_gorvek`
- **WHEN** the operator clicks the image status icon
- **THEN** the modal SHALL load from `modules/<module>/media/monsters/bandit_captain_gorvek.jpg`

### Requirement: Backend Payload Compatibility

The unified asset endpoint SHALL continue returning `id`, `name`, and `type` as separate fields without embedding the type in `id`.

#### Scenario: API response preserves id and type fields
- **GIVEN** any module
- **WHEN** `/api/toolkit/modules/<module>/unified-assets` is called
- **THEN** each asset SHALL have `id` as the type-agnostic slug
- **AND** each asset SHALL have `type` as `"monster"` or `"npc"`

### Requirement: Qualified Keys Are Not A Duplicate-Row Requirement

Type-qualified keys SHALL NOT be used as justification to keep duplicate NPC rows for monster-authoritative actors.

#### Scenario: Thornwood has stale same-slug backup NPC data for a monster actor
- **GIVEN** `corrupted_ranger_thane` is module monster-authoritative
- **AND** backup area data also contains an NPC entry with the same slug
- **WHEN** unified assets are returned
- **THEN** the endpoint SHALL return the monster asset row
- **AND** the endpoint SHALL NOT return a separate NPC asset row for `corrupted_ranger_thane`

