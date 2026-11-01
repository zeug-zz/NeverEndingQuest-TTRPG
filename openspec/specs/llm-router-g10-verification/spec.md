# llm-router-g10-verification Specification

## Purpose
Defines the isolated G10 full-session evidence needed to verify router cleanup, usage accounting, and save/resume behavior without transferring the live verdict from the primary orchestrator.

## Requirements

### Requirement: G10 is gated by a primary-owned G9 PASS
Cleanup implementation and G10 live execution SHALL begin only after the activation change records primary-owned G9 PASS with accepted evidence.

#### Scenario: G9 is not PASS
- **WHEN** the activation change has no G9 verdict or records BLOCKED or FAIL
- **THEN** cleanup implementation SHALL NOT begin
- **AND** no G10 live capture SHALL be started

#### Scenario: G9 PASS is recorded
- **WHEN** the activation change records primary-owned G9 PASS with accepted evidence references
- **THEN** cleanup implementation and preparation for G10 MAY proceed

### Requirement: G10 SHALL cover full sessions for both party shapes
The G10 live matrix SHALL contain one bounded full-session capture for each 1-PC and 4-PC party.

#### Scenario: Required full-session coverage
- **WHEN** the primary executes the G10 matrix
- **THEN** both captures SHALL include narration, combat, save, restart/resume, `/usage`, and Debug session/week cost-provenance observations
- **AND** resumed state SHALL show no duplicate mechanics, rewards, or chat costs

### Requirement: G10 evidence SHALL be preserved per run
Each G10 capture SHALL preserve a unique evidence bundle under `tmp/router-rollout/g10/<run-id>/` before sandbox teardown.

#### Scenario: Complete run bundle
- **WHEN** a G10 capture finishes or fails
- **THEN** its bundle SHALL include scenario and party/seed identity, worktree and model/provider identity, expected-versus-observed checks, transcript, owned-server log, and required state/save-resume evidence
- **AND** required `/usage` and Debug observations SHALL include actual, estimated, or unpriced cost provenance and completeness

#### Scenario: Missing required evidence
- **WHEN** a required artifact, observation, scenario, or party shape is missing or contradictory
- **THEN** the run SHALL remain incomplete and SHALL NOT be marked PASS

### Requirement: Only the primary orchestrator SHALL judge G10
The offline evaluator SHALL report readiness only, and only the primary orchestrator SHALL record the G10 PASS, FAIL, or BLOCKED verdict.

#### Scenario: Evaluator sees complete evidence
- **WHEN** the offline evaluator finds all required G10 evidence
- **THEN** it MAY report readiness for primary review
- **AND** it SHALL NOT emit or imply G10 PASS

#### Scenario: Synthetic or degraded evidence
- **WHEN** required evidence is synthetic, degraded, timed out, or represented only by process exit status
- **THEN** the primary SHALL NOT record G10 PASS

### Requirement: G10 captures SHALL remain isolated from installed runtime state
Live G10 captures SHALL use an isolated Capture_Arena copy, port 8360, `NEQ_OPEN_BROWSER=0`, and the repository virtual environment.

#### Scenario: Capture sandbox and evidence roots
- **WHEN** a primary-owned G10 run is prepared and executed
- **THEN** it SHALL use a real copy under `tmp/combat_capture/`
- **AND** it SHALL preserve evidence under the matching `tmp/router-rollout/g10/<run-id>/` directory
- **AND** it SHALL NOT write to the installed campaign or use port 8357
