# Spec Delta

## ADDED Requirements

### Requirement: G5T SHALL provide separate named commander scenarios

The capture ensemble SHALL provide distinct named P1 and P4 commander scenarios using the dedicated Capture_Arena module.

#### Scenario: G5T P1 and P4 selectors run

- **WHEN** the operator selects `g5t-commander-p1` or `g5t-commander-p4`
- **THEN** the capture SHALL use the dedicated Capture_Arena fixtures and preserve artifacts under `tmp/router-rollout/g5t/<run-id>/`
- **AND** each scenario SHALL designate a Hobgoblin Captain commander and include goblins with explicit authored multiattack declarations
- **AND** each scenario SHALL include an explicitly authored cover feature
- **AND** it SHALL record party shape, scenario identity, seed, source revision, model/provider identity, expected and observed checks, and artifact paths

### Requirement: G5T tactical flags SHALL be isolated to its sandbox

G5T MAY enable the tactical brain and resolver flags only in its isolated Capture_Arena sandbox. The installed campaign and shipped defaults SHALL remain unchanged.

#### Scenario: G5T seeder enables only the isolated tactical path

- **WHEN** a G5T sandbox is seeded
- **THEN** tactical brain and resolver flags MAY be enabled in the sandbox only
- **AND** the installed campaign and shipped default flags SHALL remain unchanged
- **AND** selecting G5R SHALL retain its existing resolver-only patch behavior

### Requirement: Existing capture contracts SHALL remain unchanged

Adding G5T SHALL NOT modify existing P1/P4 action scripts or existing G1/G3/G4/G5/G5R fixture identities and evaluator behavior.

#### Scenario: Existing capture contracts are unchanged

- **WHEN** G5T selectors and fixtures are added
- **THEN** existing G1/G3/G4/G5/G5R fixture identities and evaluators SHALL retain their prior behavior
- **AND** the existing P1/P4 action scripts SHALL NOT be edited to represent commander cases

#### Scenario: G5T script supports the Extra Attack fixture

- **WHEN** the G5T P1 or P4 commander script is constructed
- **THEN** Acheron's fixture character SHALL declare the Extra Attack class feature and an equipped training blade with `1d6+2 slashing` damage
- **AND** P1 SHALL contain two Acheron attack/damage pairs in round 3, while P4 SHALL contain two pairs in round 2
- **AND** the covered-target attack/damage pair SHALL remain at steps 2 and 3 in both party shapes
- **AND** a missed covered attack SHALL skip only its paired damage row; a later same-PC attack and damage row SHALL remain eligible
- **AND** G5T step counts and request/control caps SHALL be derived from its revised script, without changing legacy gate fixtures or hashes

#### Scenario: G5T preserves legal damage and a bloodied Goblin decision

- **WHEN** the scripted Goblin and PC attacks are evaluated
- **THEN** each `/dmg` input SHALL be within the minimum-to-maximum non-critical total damage range parsed from the acting PC's declared weapon damage string
- **AND** the HP trajectory SHALL be checked for both hit and miss outcomes of the covered-target attack, including the driver's paired-damage skip on a miss
- **AND** a Goblin SHALL be alive at 3/7 HP at an `/end` in both covered-target branches for P1 and P4
- **AND** the Captain SHALL remain alive at 9/39 HP at a near-death `/end` so surrender remains legal; P4 SHALL have this opportunity at round 4 and again at round 5 after the goblins have fled or been defeated
- **AND** all enemies SHALL be defeated by the final scripted PC attacks in both branches
- **AND** each script SHALL follow those attacks with a distinct DM `/end` batch that runs existing combat-exit and XP handling
- **AND** the sent closing batch SHALL wait for `combat_exit_complete` before after-run capture; a closing batch after an earlier exit SHALL be recorded as skipped with `combat_ended`
- **AND** the script SHALL make flee and cover available as model choices, not forced outcomes

### Requirement: G5T SHALL script per-creature self-preservation evidence

Each named commander capture SHALL include an eligible per-creature flight choice and preserve authoritative evidence of its result.

#### Scenario: G5T flight is observable
- **WHEN** a scripted living creature flees in a G5T capture
- **THEN** its applied action SHALL be Disengage and it SHALL make no attack that turn
- **AND** its encounter status SHALL be `defeated` with `defeatReason=fled`
- **AND** it SHALL be absent from subsequent actor and target menus while the remaining encounter state stays coherent
