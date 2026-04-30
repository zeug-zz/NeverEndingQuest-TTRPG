# Will-o'-Wisp Safe Slug

## ADDED Requirements

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

`Murder_at_the_Drowning_Lass` SHALL store Will-o'-Wisp monster media under runtime-safe slug filenames, not apostrophe-bearing filenames.

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

### Requirement: Murder_at_the_Drowning_Lass reference integrity passes

The module validation gate SHALL resolve `Will-o'-Wisp` references to `monsters/will_o_wisp.json`.

#### Scenario: Reference integrity resolves Will-o'-Wisp JSON

Given `modules/Murder_at_the_Drowning_Lass/monsters/will_o_wisp.json` exists  
And `WM001.json` references `Will-o'-Wisp`  
When `core/validation/validate_module_files.py --module Murder_at_the_Drowning_Lass --json` runs  
Then reference integrity SHALL NOT report `expected monsters/will_o__wisp.json`
