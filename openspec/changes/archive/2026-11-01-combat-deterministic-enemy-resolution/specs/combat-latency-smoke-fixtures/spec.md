# Spec Delta

## MODIFIED Requirements

### Requirement: Reusable Scripted Capture Ensemble

The change SHALL provide a reusable scripted capture ensemble for the live
baseline: a lean sandbox copy under `tmp/`, a dedicated `Capture_Arena` capture
module, and scripted capture scenarios (socket-driven driver primary;
`playwright-cli` documented as the browser alternative) that capture 4-PC and
1-PC traces and tear down cleanly. The ensemble SHALL be test tooling and SHALL
NOT change product runtime behavior. It SHALL also expose the G5R selector by
reusing the existing P1/P4 action scripts unchanged and run three distinct
captures per party shape beneath `tmp/router-rollout/g5r/<run-id>/`.

#### Scenario: Sandbox isolation

- **WHEN** the ensemble prepares or runs a capture
- **THEN** the installed tree SHALL remain unchanged
- **AND** all sandbox runtime state SHALL live under `tmp/`

#### Scenario: Capture module role

- **WHEN** a capture scenario needs an arena with walkable locations, combat
  hostiles, and NPC or feature objects
- **THEN** it SHALL use the dedicated `Capture_Arena` module
- **AND** no gameplay state from another installed module SHALL be required

#### Scenario: Scripted 4-PC and 1-PC captures

- **WHEN** the 4-PC and 1-PC scenarios are executed through scripted capture
  scenarios (socket-driven driver primary; `playwright-cli` documented as the
  browser alternative)
- **THEN** each scenario SHALL produce a trace usable by
  `scripts/combat_latency_report.py`

#### Scenario: G5R reuses fixed scenario scripts

- **WHEN** an operator selects G5R for either party shape
- **THEN** the ensemble SHALL use the existing P1/P4 action script and fixture
  identity without modifying its scripted actions
- **AND** it SHALL preserve three unique run IDs and the required per-run
  evidence under the G5R evidence root

#### Scenario: Trace capture and teardown

- **WHEN** a capture completes or fails
- **THEN** the trace SHALL be preserved to a local path under `tmp/`
- **AND** the ensemble SHALL stop the sandbox server and restore sandbox state

#### Scenario: Documented reuse

- **WHEN** a future narration or other gameplay capture is needed
- **THEN** the documented skill and checklist SHALL provide the start/stop
  commands, selectors, and extension points to run it without new test
  infrastructure
