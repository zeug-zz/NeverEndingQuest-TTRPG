# Spec Delta

## MODIFIED Requirements

### Requirement: Decision events SHALL contain the four baseline fields

Each recorded decision event SHALL contain `decision_point`, `decision_source`,
`decision_latency_ms`, and `provider_call_avoided`.
`decision_source` SHALL be exactly one of `deterministic`, `llm_fallback`, or
`jev`. Enemy-resolution decisions SHALL additionally record a bounded
`decision_outcome` (`resolver_supported`, `whole_batch_fallback`, or
`resolver_disabled`) and a bounded `decision_reason` code. For a supported
enemy batch, `provider_call_avoided` SHALL indicate that deterministic
mechanics avoided the existing generation and validation work; the separate
narration-only provider request SHALL remain visible as an actual provider
call.

#### Scenario: Deterministic decision is recorded

- **WHEN** an existing deterministic decision path resolves a decision point
- **THEN** the event SHALL use `decision_source=deterministic`
- **AND** it SHALL record non-negative decision latency and whether a provider
  call was avoided

#### Scenario: Supported enemy batch decision is recorded

- **WHEN** Python completes eligibility planning for a supported enemy batch
- **THEN** the event SHALL use the stable `enemy_batch_resolution` decision
  point and `decision_outcome=resolver_supported`
- **AND** its reason code SHALL be bounded and SHALL NOT contain prompt text,
  names, or mutable game state
- **AND** provider avoidance SHALL NOT hide the narration-only provider event

#### Scenario: Whole enemy batch falls back

- **WHEN** an eligibility check declines deterministic resolution for any
  scheduled enemy action
- **THEN** exactly one decision event SHALL use
  `decision_outcome=whole_batch_fallback` and the bounded fallback reason
- **AND** the event SHALL NOT imply that any deterministic ledger entry was
  applied

#### Scenario: Resolver is disabled

- **WHEN** the rollback/configuration flag disables deterministic resolution
- **THEN** the decision event SHALL use `decision_outcome=resolver_disabled`
- **AND** the existing LLM path SHALL remain the routing authority
