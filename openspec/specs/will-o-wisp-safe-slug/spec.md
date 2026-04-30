# will-o-wisp-safe-slug Specification

## Purpose
TBD - created by archiving change murder-drowning-lass-will-o-wisp-safe-slug. Update Purpose after archive.
## Requirements
### Requirement: Validator monster slug normalization matches runtime

`ModuleValidator._normalize_monster_name()` SHALL normalize monster names using the same effective rules as `ModulePathManager.get_monster_path()` and `updates.update_character_info.normalize_character_name()`.

#### Scenario: Will-o'-Wisp normalizes consistently

Given the monster display name `Will-o'-Wisp`  
When the validator normalizes the name  
Then the result SHALL be `will_o_wisp`

#### Scenario: Apostrophe normalization matches runtime

Given the monster display name `Bob's Monster`  
When the validator normalizes the name  
Then the result SHALL be `bob_s_monster`

#### Scenario: Hyphen normalization matches runtime

Given the monster display name `Hyphenated-Monster`  
When the validator normalizes the name  
Then the result SHALL be `hyphenated_monster`

### Requirement: Murder_at_the_Drowning_Lass uses safe Will-o'-Wisp media filenames

`Murder_at_the_Drowning_Lass` SHALL store and resolve Will-o'-Wisp monster media under runtime-safe slug filenames, not apostrophe-bearing filenames.

#### Scenario: Gameplay media audit finds Will-o'-Wisp base media

Given the module references `Will-o'-Wisp`  
And `modules/Murder_at_the_Drowning_Lass/media/monsters/will_o_wisp.jpg` exists  
When `scripts/audit_module_gameplay.py --module Murder_at_the_Drowning_Lass --json` runs  
Then it SHALL NOT report missing base media for `will_o_wisp`

#### Scenario: Gameplay media audit finds Will-o'-Wisp thumbnail media

Given the module references `Will-o'-Wisp`  
And `modules/Murder_at_the_Drowning_Lass/media/monsters/will_o_wisp_thumb.jpg` exists  
When `scripts/audit_module_gameplay.py --module Murder_at_the_Drowning_Lass --json` runs  
Then it SHALL NOT report missing thumb media for `will_o_wisp`

#### Scenario: MMG unified asset scan resolves Will-o'-Wisp media

Given the module references `Will-o'-Wisp`  
And `modules/Murder_at_the_Drowning_Lass/media/monsters/will_o_wisp.jpg` exists  
And `modules/Murder_at_the_Drowning_Lass/media/monsters/will_o_wisp_thumb.jpg` exists  
When `/api/toolkit/modules/Murder_at_the_Drowning_Lass/unified-assets` scans module assets  
Then the returned monster asset for `Will-o'-Wisp` SHALL have id `will_o_wisp`  
And `has_image` SHALL be true  
And `has_thumbnail` SHALL be true  
And the scan SHALL NOT return an asset id `will-o'-wisp`

#### Scenario: MMG final report uses safe Will-o'-Wisp media slug

Given an MMG final media report audits a monster asset named `Will-o'-Wisp`  
And module-local files exist as `will_o_wisp.jpg` and `will_o_wisp_thumb.jpg`  
When the report is built  
Then the asset audit SHALL use id `will_o_wisp`  
And it SHALL mark image and thumbnail media present  
And it SHALL NOT list `Will-o'-Wisp` as missing media because of `will-o'-wisp` filename lookup

### Requirement: Murder_at_the_Drowning_Lass reference integrity passes

The module validation gate SHALL resolve `Will-o'-Wisp` references to `monsters/will_o_wisp.json`.

#### Scenario: Reference integrity resolves Will-o'-Wisp JSON

Given `modules/Murder_at_the_Drowning_Lass/monsters/will_o_wisp.json` exists  
And `WM001.json` references `Will-o'-Wisp`  
When `core/validation/validate_module_files.py --module Murder_at_the_Drowning_Lass --json` runs  
Then reference integrity SHALL NOT report `expected monsters/will_o__wisp.json`

### Requirement: MMG frontend handles apostrophe-bearing display names safely

The Module Media Generator frontend SHALL render and interact with apostrophe-bearing asset display names without using apostrophe-bearing display text as an unsafe DOM ID or unescaped inline JavaScript argument.

#### Scenario: Will-o'-Wisp thumbnail DOM uses safe asset id

Given the MMG receives an asset with id `will_o_wisp` and name `Will-o'-Wisp`  
When the asset table renders  
Then the thumbnail container id SHALL be `asset-thumb-will_o_wisp`  
And it SHALL NOT be `asset-thumb-will-o'-wisp`

#### Scenario: Will-o'-Wisp media click handler remains valid

Given the MMG receives an asset with id `will_o_wisp` and name `Will-o'-Wisp`  
When image or thumbnail status controls are clickable  
Then clicking the control SHALL request media for asset id `will_o_wisp`  
And the display title MAY show `Will-o'-Wisp`  
And the apostrophe in the display name SHALL NOT break JavaScript parsing or event handling

### Requirement: MMG generation normalizes submitted monster assets server-side

MMG image generation SHALL normalize monster asset IDs server-side before bestiary lookup, image generation, module media destination writes, progress events, and failure records.

#### Scenario: Stale Will-o'-Wisp payload still writes safe filenames

Given a stale browser submits a monster asset id `will-o'-wisp` with name `Will-o'-Wisp`  
When MMG image generation processes the asset  
Then the server SHALL normalize the working asset id to `will_o_wisp`  
And generated or copied media SHALL target `will_o_wisp.jpg` and `will_o_wisp_thumb.jpg`  
And generation progress or failure records SHALL report asset id `will_o_wisp`

