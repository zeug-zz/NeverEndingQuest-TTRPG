## Purpose

Define DM Note death visibility rules ensuring dead PC mechanical truth is exposed in both full and condensed stat blocks.

## Requirements

### Requirement: DM Note shall expose dead PC mechanical truth

The DM Note PC stat formatter SHALL display explicit status and death-save truth for dead or dying PCs.

#### Scenario: Full stats for dead PC
- WHEN a full PC stat block is generated for a dead PC
- THEN the output SHALL include a clear dead status marker
- AND SHALL include death-save failure state
- AND SHALL identify the line as mechanical truth or DM Note truth

#### Scenario: Condensed stats for dead PC
- WHEN a condensed PC stat block is generated for a dead PC
- THEN the output SHALL include compact dead status
- AND SHALL include compact death-save state

#### Scenario: Healthy living PC remains concise
- WHEN a healthy living PC stat block is generated
- THEN the formatter SHOULD avoid unnecessary death-save noise
- AND SHALL continue to show HP and condition truth as before
