# core-runtime-usage-recovery Specification

## Purpose

Define safe per-attempt usage observation, legacy runtime telemetry integration, session-level reset/notification behavior, and bounded empty-response recovery during core chat migration.

## Requirements

### Requirement: Router Observer Is Optional and Per Call

A router call MAY receive an optional observer that sees immutable receipt metadata and trusted access to the raw SDK response for existing response consumers. With no observer, the call SHALL perform no observer-specific I/O or client construction.

#### Scenario: No observer preserves ordinary call behavior

- **WHEN** a caller invokes `llm.call()` without an observer
- **THEN** no observer adapter, tracker, or logging client SHALL be constructed for that call
- **AND** the existing facade return value and SDK retry default SHALL remain unchanged

#### Scenario: Receipt identifies each actual transport attempt

- **WHEN** a provider SDK invocation returns or raises
- **THEN** the observer SHALL receive one immutable event for that invocation with call/attempt identity, task, tier/profile, retry/fallback state, transport provider, requested/resolved model, usage/cost provenance, completeness, and elapsed time when known
- **AND** client-construction failures SHALL be distinguishable from SDK attempts

### Requirement: Observer Cannot Change Router Results or Stats

The router SHALL finalize its return value and accounting snapshot before invoking the observer, invoke the observer outside stats locks, and isolate ordinary observer exceptions. Observer work SHALL NOT mutate the returned response, trigger duplicate stats accounting, or change call success/failure.

#### Scenario: Observer fails after successful response

- **WHEN** the router receives a successful SDK response and the observer raises an ordinary exception
- **THEN** the original call SHALL return the same text or dictionary as without the observer
- **AND** router counters SHALL reflect the SDK call exactly once

#### Scenario: Observer handles transport error

- **WHEN** an actual SDK attempt raises before producing a response
- **THEN** the observer SHALL receive one error receipt for that attempt
- **AND** no successful usage event SHALL be fabricated

### Requirement: Runtime Tracking Uses Receipts Exactly Once

The migrated runtime adapter SHALL bridge response receipts to the existing global usage tracker, applicable API logger, and opt-in combat provider trace without duplicating call-site tracking. Router-local statistics SHALL remain a separate programmatic view and SHALL NOT be added to legacy usage, Debug, session, or rolling-week totals. This change SHALL NOT add a router-backed `/usage` UI. Reported zero cost SHALL remain actual; estimates and unknown costs SHALL be explicitly labelled.

#### Scenario: Every SDK response is adapted once

- **WHEN** a migrated SDK invocation returns a nonempty, empty, or malformed response
- **THEN** each applicable legacy tracker, API logger, and opt-in combat trace SHALL receive its per-call event exactly once
- **AND** migrated manual tracking SHALL NOT create a duplicate event

#### Scenario: Errors do not fabricate usage

- **WHEN** an SDK invocation raises or client construction fails
- **THEN** the applicable observer/error logging path SHALL retain the error receipt
- **AND** no successful usage event SHALL be fabricated

#### Scenario: Zero, estimated, and unavailable costs retain provenance

- **WHEN** a response reports finite non-negative cost zero, has only a verified estimate, or has no usable cost/rate
- **THEN** the adapter SHALL respectively preserve actual zero, label the estimate as estimated, or mark cost unpriced/incomplete
- **AND** unknown cost SHALL NOT be reported as actual zero

### Requirement: Session Reset and Fallback Notice Follow Runtime Launch Boundaries

A minimal shared launch helper SHALL reset router-local session stats and existing factory fallback-notification state once at each CLI or web runtime launch before its first core call. It SHALL NOT reset at campaign creation, `main_game_loop()` entry, turn/validator, save, load, resume, or restore recursion, and SHALL NOT reset the rolling-week ledger. A fallback notification SHALL be consumed once at the existing visible point.

#### Scenario: CLI and web launches reset before core calls

- **WHEN** CLI `main.main()` begins or web `web.web_interface.run_game_loop()` begins
- **THEN** each launch path SHALL invoke the shared reset before setup/hydration can lead to the first core request
- **AND** no router-backed `/usage` UI or legacy ledger reset SHALL be introduced

#### Scenario: Restore recursion is not a new runtime launch

- **WHEN** successful restore returns `restart` and `main_game_loop()` recursively re-enters
- **THEN** the launch reset SHALL NOT run again
- **AND** turn, validator, save/load, and resume paths SHALL NOT reset session stats

#### Scenario: Fallback message is surfaced once

- **WHEN** a scoped caller receives an available fallback notification
- **THEN** the message SHALL be consumed at the existing visible point exactly once
- **AND** subsequent response tracking SHALL not append a duplicate notice

### Requirement: Main Empty-Response Recovery Is Optional and Bounded Per Provider

The router SHALL expose optional empty-transient recovery only for ordinary main narrator text requests; it SHALL be disabled by default and rejected with `json_output=True`. Retry limit two permits at most three empty responses per provider, one fallback transition, and six SDK invocations total. The fallback flag/call cap never reset; only the per-provider response counter starts fresh on the sole fallback. Every received response SHALL be counted once.

#### Scenario: Preferred provider empties then fallback succeeds

- **WHEN** the preferred provider returns three empty responses and the sole fallback returns success
- **THEN** the call SHALL make no more than four SDK invocations
- **AND** all four responses SHALL have exactly one receipt/accounting event

#### Scenario: Both providers exhaust empty-response budgets

- **WHEN** preferred and fallback each return three empty responses
- **THEN** the call SHALL stop after six SDK invocations with no second fallback
- **AND** all six responses SHALL be counted and observed exactly once

### Requirement: Empty Recovery Separates Responses, Transport Errors, and Terminal Results

Client-construction failures SHALL emit no SDK-attempt receipt. SDK transport errors SHALL emit one error receipt and follow only the existing bounded transient-fallback policy; they are not empty responses. Quota, refusal, and content-filter outcomes SHALL stop recovery immediately.

#### Scenario: Constructor and transport errors remain bounded

- **WHEN** client construction fails or an SDK transport error occurs during opted-in recovery
- **THEN** no empty-response retry SHALL be charged for the failure
- **AND** the call SHALL remain within one fallback transition and six SDK invocations

#### Scenario: Terminal result bypasses all recovery

- **WHEN** quota/billing, refusal, or content-filter occurs on either provider
- **THEN** the call SHALL stop immediately without empty retry, fallback transition, or caller semantic retry

### Requirement: Core Callers Do Not Nest JSON Retry with Empty Recovery

A core caller that owns JSON parsing or semantic validation SHALL use the facade with `json_output=False` and SHALL NOT wrap it in the raw-SDK recovery helper.

#### Scenario: Caller-side JSON parsing remains the only JSON retry

- **WHEN** a core caller uses its existing JSON parsing or semantic validation loop
- **THEN** it SHALL call the facade with `json_output=False`
- **AND** the old raw-SDK recovery wrapper SHALL not surround a facade JSON retry loop
