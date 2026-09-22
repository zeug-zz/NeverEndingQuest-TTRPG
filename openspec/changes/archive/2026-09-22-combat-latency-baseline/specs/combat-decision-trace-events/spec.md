## Purpose

Define the decision-event contract needed to measure deterministic combat
decisions and future decision-primitive shadow evaluation without authorizing
Jev, changing routing, or adding provider calls.

## ADDED Requirements

### Requirement: Decision events SHALL contain the four baseline fields

Each recorded decision event SHALL contain `decision_point`,
`decision_source`, `decision_latency_ms`, and `provider_call_avoided`.
`decision_source` SHALL be exactly one of `deterministic`, `llm_fallback`, or
`jev`.

#### Scenario: Deterministic decision is recorded

- **WHEN** an existing deterministic decision path resolves a decision point
- **THEN** the event SHALL use `decision_source=deterministic`
- **AND** it SHALL record non-negative decision latency and whether a provider
  call was avoided

### Requirement: Decision point names SHALL identify the observed seam

`decision_point` SHALL identify the bounded decision seam or operation being
measured, rather than embedding a prompt, full user message, or mutable game
state. The event SHALL be usable for aggregation across fixture runs.

#### Scenario: Multiple decisions use the same seam

- **WHEN** the same decision seam resolves in multiple turns
- **THEN** each event SHALL use a stable decision-point value
- **AND** the report SHALL be able to group those events without parsing prose

### Requirement: Decision source semantics SHALL remain distinct

`deterministic` SHALL mean the existing code path resolved the decision;
`llm_fallback` SHALL mean the existing flow fell through to its LLM path;
`jev` SHALL be reserved for a future authorized decision primitive and SHALL
NOT require Jev implementation in this change.

#### Scenario: LLM fallback is observed

- **WHEN** an existing deterministic or fast-path attempt falls through to the
  existing LLM path
- **THEN** the event SHALL use `decision_source=llm_fallback`
- **AND** instrumentation SHALL NOT add or remove a provider call

#### Scenario: Jev value is not implemented

- **WHEN** no Jev implementation exists in the runtime
- **THEN** no `jev` event SHALL be fabricated
- **AND** the schema SHALL still accept `jev` as a reserved source value

### Requirement: Provider avoidance SHALL be explicit

`provider_call_avoided` SHALL be a boolean indicating whether the observed
decision avoided an otherwise applicable provider call. It SHALL describe the
existing path and SHALL NOT itself control routing.

#### Scenario: Fast path avoids a provider call

- **WHEN** an existing deterministic path completes without an applicable
  provider call
- **THEN** `provider_call_avoided` SHALL be true
- **AND** the decision outcome SHALL remain unchanged by tracing

#### Scenario: Fallback uses a provider call

- **WHEN** an existing decision falls through to its provider path
- **THEN** `provider_call_avoided` SHALL be false
- **AND** the existing provider outage and retry behavior SHALL remain intact

### Requirement: Decision trace failures SHALL be fail-open

Failure to classify, serialize, or write a decision event SHALL NOT block or
alter the decision, combat state, prompt, or provider behavior.

#### Scenario: Decision event emission fails

- **WHEN** decision-event instrumentation raises an internal error
- **THEN** the original decision path SHALL continue
- **AND** no compensating provider call or game-state write SHALL occur
