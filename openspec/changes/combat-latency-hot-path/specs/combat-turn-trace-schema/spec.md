# Spec Delta

## ADDED Requirements

### Requirement: G5 trace records SHALL identify the capture run and work unit

Every G5 trace record SHALL include its distinct `run_id`; provider and file-operation records SHALL also identify the originating `action_id` or `batch_id` when that work unit applies.

#### Scenario: Provider call is attributed to a PC action
- **WHEN** a provider call occurs while processing a captured PC action
- **THEN** its trace record SHALL include the run and action identifiers
- **AND** reports SHALL be able to count that call for the action

#### Scenario: File operation is attributed to an enemy batch
- **WHEN** a tracked file operation occurs while processing the captured enemy batch
- **THEN** its trace record SHALL include the run and batch identifiers
- **AND** reports SHALL be able to count that operation for the batch

#### Scenario: Trace attribution is bounded
- **WHEN** G5 identifiers are emitted
- **THEN** they SHALL identify runs and work units without embedding full prompts, user messages, secrets, or unbounded game state

### Requirement: G5 capture steps SHALL preserve both timing measurements

Each G5 PC action and enemy-batch completion record SHALL report separate non-negative work-only and quiet-window elapsed durations; neither duration SHALL be substituted for the other.

#### Scenario: Driver quiet window inflates step elapsed time
- **WHEN** a captured step includes a driver quiet-window wait
- **THEN** the evidence SHALL preserve both work-only and quiet-window elapsed durations
- **AND** the report SHALL use work-only timing for the corresponding latency target while displaying both measurements

#### Scenario: No quiet-window inflation occurs
- **WHEN** the measured step completes without a quiet-window wait
- **THEN** both timing fields SHALL still be reported from their own measurement boundaries
- **AND** neither missing value SHALL be fabricated as zero
