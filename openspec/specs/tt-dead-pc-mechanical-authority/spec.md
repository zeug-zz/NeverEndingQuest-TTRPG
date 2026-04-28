## Purpose

Define the mechanical dead-state authority rules ensuring dead PCs stay dead through normalization, preventing accidental revival by generic HP changes.

## Requirements

### Requirement: Dead PC state shall be mechanically sticky

The runtime SHALL treat a PC as mechanically dead when `status` is `dead` or `deathSaves.failures` is at least 3.

#### Scenario: Explicit dead status with positive HP
- WHEN a character has `status: dead`
- AND `hitPoints` is greater than 0
- THEN normalization SHALL keep the character dead
- AND SHALL set `hitPoints` to 0
- AND SHALL preserve at least 3 failed death saves

#### Scenario: Three failed death saves with stale status
- WHEN a character has `deathSaves.failures >= 3`
- AND `status` is not `dead`
- THEN normalization SHALL set `status` to `dead`
- AND SHALL prevent positive HP from reviving the character

#### Scenario: Living stale unconscious repair remains valid
- WHEN a character has positive HP
- AND does not have `status: dead`
- AND has fewer than 3 failed death saves
- AND has stale unconscious state
- THEN normalization SHALL repair the character to alive
- AND MAY reset death saves as existing behavior does

### Requirement: Character update synchronization shall not revive dead PCs by generic HP changes

Character update death-save synchronization SHALL preserve explicit mechanical death unless a dedicated resurrection/corruption state action is used.

#### Scenario: Generic update sets HP on a dead PC
- WHEN a character update produces positive HP for a character with `status: dead`
- THEN the sync layer SHALL keep `status: dead`
- AND SHALL set HP back to 0
- AND SHALL NOT reset death-save failures below 3

#### Scenario: Generic update sets HP on a three-failure PC
- WHEN a character update produces positive HP for a character with `deathSaves.failures >= 3`
- THEN the sync layer SHALL keep the character mechanically dead
- AND SHALL NOT treat the update as resurrection
