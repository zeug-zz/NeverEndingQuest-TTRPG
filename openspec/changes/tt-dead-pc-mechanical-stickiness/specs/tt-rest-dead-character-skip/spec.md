## ADDED Requirements

### Requirement: Ordinary rest shall skip dead characters

The rest automation SHALL NOT restore HP, spell slots, class features, hit dice, exhaustion, or death-save state for mechanically dead characters.

#### Scenario: Long rest targets a dead PC
- WHEN a long rest action targets a character with `status: dead`
- THEN rest processing SHALL skip that character
- AND SHALL NOT call character update mutation for restorative changes
- AND the character file SHALL remain dead with 0 HP and at least 3 failed death saves

#### Scenario: Short rest targets a dead PC
- WHEN a short rest action targets a character with `deathSaves.failures >= 3`
- THEN rest processing SHALL skip that character
- AND SHALL NOT refresh short-rest resources

#### Scenario: Alive long-rest behavior remains unchanged
- WHEN a long rest targets a living character with depleted HP, spell slots, features, or exhaustion
- THEN existing restoration behavior SHALL continue to apply

### Requirement: Rest skip reporting shall be explicit and non-blocking

Rest processing SHALL report skipped dead characters without failing the entire rest action for living party members.

#### Scenario: Mixed living and dead party rest
- WHEN a rest action targets both living and dead party members
- THEN living party members SHALL receive normal rest processing
- AND dead party members SHALL be reported as skipped with a dead-state reason
