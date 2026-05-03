# toolkit-mmg-npc-description-hygiene Specification

## ADDED Requirements

### Requirement: Authored Area Description Source

When checking `has_description` for a true NPC, the system SHALL search canonical area NPC entries for authored descriptions after compendium and temp-description sources are exhausted.

#### Scenario: NPC has description in backup area file but not in compendium
- **GIVEN** `Wounded Ranger Gareth` has a description in `TW001_BU.json#locations[TW06].npcs`
- **AND** no compendium or temp description exists
- **WHEN** `check_asset_status("wounded_ranger_gareth", "npc", ...)` runs
- **THEN** `has_description` SHALL be `true`

### Requirement: Description Generation Uses Available Helper

UI-driven NPC description generation SHALL NOT import a non-existent class.

#### Scenario: Operator triggers description generation for NPC
- **GIVEN** an NPC asset without a description
- **WHEN** `handle_generate_unified_assets` tries to generate the description
- **THEN** it SHALL use `utils.ai_client_factory.create_chat_client()` and `get_model_config()` directly
- **AND** it SHALL NOT import `NPCBuilder` from `core.generators.npc_builder`

### Requirement: Description Resolution Priority Order

When the MMG needs a true NPC description for generation or status check, it SHALL search in this order: `data/bestiary/npc_compendium.json`, `temp/npc_descriptions_<module>.json`, live area files, backup area files, then AI generation.

#### Scenario: Operator checks description status for true NPC present only in BU files
- **GIVEN** `Wounded Ranger Gareth` has a description in `TW001_BU.json`
- **AND** no compendium or live area description exists
- **WHEN** asset status is checked
- **THEN** the BU file description SHALL be found
- **AND** `has_description` SHALL be `true`

### Requirement: Description Generation Failure Marking

If explicit NPC description generation is requested and fails, the failure SHALL produce a clear log and generation_failure entry without preventing other assets from being processed.

#### Scenario: Generation fails for one NPC
- **GIVEN** two NPCs need descriptions
- **WHEN** generation fails for the first NPC
- **THEN** a failure entry SHALL be recorded for that NPC
- **AND** the second NPC SHALL still be attempted

### Requirement: Monster-Authoritative Slugs Do Not Become NPC Description Assets

The NPC description path SHALL NOT create or preserve a separate NPC asset classification for a slug that is module monster-authoritative.

#### Scenario: Same slug exists as backup NPC and module monster
- **GIVEN** `malarok_the_corruptor` has a module monster JSON/statblock
- **AND** stale backup area data contains an NPC entry for `Malarok the Corruptor`
- **WHEN** unified assets and description status are resolved
- **THEN** `malarok_the_corruptor` SHALL be resolved as a monster asset only
- **AND** NPC compendium lookup SHALL NOT make it appear as a true NPC asset

### Requirement: True NPCs Remain Eligible For NPC Description Generation

Suppressing monster-authoritative duplicate NPC rows SHALL NOT suppress unrelated true NPCs.

#### Scenario: Thornwood true NPC remains available
- **GIVEN** `wounded_ranger_gareth` is not module monster-authoritative
- **WHEN** unified assets and description status are resolved
- **THEN** `wounded_ranger_gareth` SHALL remain an NPC asset
- **AND** its authored description SHALL be discoverable from compendium, live area, backup area, or AI fallback according to the priority order

## SHOULD Guidance

- If the NPC slug already appears in `npc_compendium.json` with a description and is not module monster-authoritative, skip area file search.
- Cache BU-file-derived descriptions for true NPCs into `npc_compendium.json` on first lookup if the compendium entry is missing.
- Before using `npc_compendium.json`, check whether the slug is module monster-authoritative for the active module.
