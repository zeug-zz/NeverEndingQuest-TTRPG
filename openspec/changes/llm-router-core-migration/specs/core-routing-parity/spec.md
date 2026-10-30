# Spec Delta

## Purpose

Define how the inventoried core production chat operations move behind the shared router without changing their observable prompt, parsing, runtime, or caller contracts.

## ADDED Requirements

### Requirement: Scoped Core Chat Uses Explicit Router Tasks
Every active scoped core production chat operation SHALL call `llm.call()` with its explicit legacy task identifier and SHALL NOT construct or invoke a provider SDK client at the caller. The scope is the 15 semantic operations in `reports/core-chat-inventory.md`, including each documented primary/fallback/helper transport variant.

#### Scenario: Scoped operation routes through facade
- **WHEN** a scoped main, combat, or action-handler chat operation issues a provider request
- **THEN** it SHALL use `llm.call()` with its mapped task identifier
- **AND** no caller-owned SDK transport branch for that operation SHALL remain

#### Scenario: Dormant helper remains source-compatible
- **WHEN** either dormant main.py transition helper is retained during this migration
- **THEN** its signature, prompt construction, return/fallback behavior, and parse behavior SHALL remain compatible while its provider request is routed through the facade

### Requirement: Factory Owns Model, Client, and Timeout Policy
Scoped callers SHALL NOT supply a provider SDK model, timeout, or provider fallback client. The router/factory SHALL resolve the model from configured task profiles and retain the configured 120-second total and 10-second connect timeout as the sole transport timeout owner.

#### Scenario: Caller no longer overrides model or timeout
- **WHEN** a scoped operation calls the facade
- **THEN** the facade SHALL receive the task, messages, and supported task-level options only
- **AND** the factory SHALL resolve the configured profile model and transport timeout

#### Scenario: Configured default remains direct OpenAI
- **WHEN** the core migration runs with the approved runtime configuration
- **THEN** the selected provider SHALL remain direct OpenAI
- **AND** a normal successful request SHALL not invoke fallback

### Requirement: Caller-Visible Request and Response Contracts Are Preserved
Migration SHALL preserve the exact messages and prompt content, ordering, output parsing, state/action flow, public callbacks, errors/fail-open decisions, and caller-visible return shape for each inventoried operation, except for router-owned model and timeout resolution.

#### Scenario: Narrator and action-handler response parity
- **WHEN** a fake router returns the same assistant text as the prior transport
- **THEN** the caller SHALL produce the same parsed output, state/action decision, callback sequence, and return value as its legacy contract

#### Scenario: Combat stage return parity
- **WHEN** a fake router returns the same content for bootstrap, turn retry, validation, summary, or initiative generation
- **THEN** each stage SHALL retain its existing parse/validation and stage-result contract
- **AND** prompts/messages SHALL remain byte-identical

### Requirement: Main Routing Decisions and Retry Semantics Remain Stable
`get_ai_response()` SHALL preserve intelligent-routing enablement, the action-prediction boolean's simple-versus-full choice, and forced full choice for validation retry and module-creation prompts. Existing semantic retry limits and high-reasoning validation retry conditions SHALL remain caller-owned and unchanged; `retry_tier="high"` SHALL reach the factory on the existing qualifying combat retry.

#### Scenario: Main simple/full selection remains intact
- **WHEN** prediction says no actions are required and intelligent routing is enabled for an ordinary first attempt
- **THEN** the simple model tier SHALL be requested
- **AND** action-required prediction, module creation, validation retry, or disabled routing SHALL retain the existing full-choice behavior

#### Scenario: Existing combat retry escalation is retained
- **WHEN** the existing combat validation retry qualifies for high reasoning
- **THEN** the facade call SHALL carry the high retry tier consumed by factory policy
- **AND** no new high-reasoning escalation condition SHALL be introduced

### Requirement: Terminal Provider Outcomes Bypass Caller Retry and Mutation Paths
Quota/billing, refusal, and content-filter outcomes SHALL be represented as explicit terminal errors and SHALL bypass every legacy broad-catch fallback, semantic/validation retry, fail-open-to-valid path, and action/application stage. Quota classification SHALL use the existing router classifier; callers SHALL NOT add message-string quota heuristics. Existing nonterminal retry/fail-open behavior and public return shapes SHALL remain unchanged.

#### Scenario: Terminal outcome in main narrator or validator
- **WHEN** main response generation or `validate_ai_response()` receives quota, refusal, or content-filter terminal outcome
- **THEN** no fallback or semantic/validation retry SHALL run
- **AND** the outcome SHALL NOT be returned as valid or accepted assistant output

#### Scenario: Terminal outcome in combat owners
- **WHEN** combat bootstrap, normal turn, or combat validation receives quota, refusal, or content-filter terminal outcome
- **THEN** no broad catch or configured semantic retry SHALL convert it to a valid response
- **AND** no action or mechanical state mutation SHALL be applied from that response

#### Scenario: Terminal outcome in action-handler owners
- **WHEN** starting-location analysis, location-transition narration, or NPC movement receives quota, refusal, or content-filter terminal outcome
- **THEN** no caller fallback branch SHALL run and no decision/action SHALL be assumed or applied
- **AND** nonterminal parsing and failure contracts SHALL remain unchanged

#### Scenario: Terminal transition narration stops after the committed transition boundary
- **WHEN** location-transition narration in `process_action` receives quota, refusal, or content-filter after the deterministic location commit, traveling-follower synchronization, transition-marker append, and pre-narration history save
- **THEN** those already-committed pre-narration effects SHALL remain and SHALL NOT be rolled back or replayed
- **AND** the request SHALL make one SDK attempt with no fallback or retry
- **AND** no assistant narration SHALL be appended or saved, no transition-success narration SHALL be published, and no further action/state mutation SHALL occur
- **AND** the transition branch's prompt bytes, event order, callback contract, and nonterminal fallback SHALL remain unchanged
