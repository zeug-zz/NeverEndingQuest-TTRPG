# Spec Delta

## Purpose

Defines the production chat routing and caller-visible parity contract for the remaining G6 call sites before any provider activation.

## ADDED Requirements

### Requirement: Remaining Production Chat Uses The Facade

Every active production chat operation in the approved G6 inventory SHALL send its chat request through the shared LLM facade with an explicit task identifier.

#### Scenario: An inventoried chat operation runs
- **WHEN** an inventoried production operation requests chat completion
- **THEN** the operation SHALL call the facade rather than construct or invoke a provider chat transport itself
- **AND** the task identifier SHALL be explicit at the facade boundary

### Requirement: Chat Caller Behavior Remains Equivalent

Facade migration SHALL preserve the operation's current prompt bytes, request messages, response parsing, return shape, and deterministic side-effect order.

#### Scenario: A migrated operation receives a provider-free response
- **WHEN** a test supplies the same response content to the pre-migration and facade-backed operation
- **THEN** the facade request messages SHALL be byte-identical to the existing request messages
- **AND** the operation SHALL produce the same parsed result, return value, and ordered non-provider side effects

### Requirement: Existing Model And Provider Posture Is Preserved

The G6 migration SHALL use the existing direct-OpenAI configuration and SHALL NOT change model-profile selection or activate another provider.

#### Scenario: Existing runtime configuration is used
- **WHEN** `LLM_PROVIDER` is `"openai"` and the configured model is `gpt-6-luna`
- **THEN** migrated chat requests SHALL continue to use that configured direct-OpenAI model
- **AND** the migration SHALL NOT send an OpenRouter model or provider preference

### Requirement: Facade Parameter Policy Is Authoritative

Migrated calls SHALL use the existing task-aware facade/factory finalization policy and SHALL NOT restore legacy raw sampling kwargs that this policy omits for `gpt-6-luna`.

#### Scenario: A raw call supplied a legacy sampling value
- **WHEN** a migrated call previously supplied `temperature` or `top_p` directly to the SDK for `gpt-6-luna`
- **THEN** the facade SHALL apply its current reasoning-family parameter policy
- **AND** the migration SHALL NOT add a compatibility override to preserve those raw kwargs

### Requirement: Existing Retry And Failure Policy Is Preserved

Migration SHALL preserve each operation's existing retry budget, fallback transitions, and terminal error outcomes without adding a nested retry layer.

#### Scenario: A caller has local retry or fallback handling
- **WHEN** a provider-free test exercises an existing retryable, fallback, quota, refusal, or content-filter outcome
- **THEN** the same attempts and fallback transitions SHALL occur in the same order
- **AND** terminal outcomes SHALL NOT be converted into a successful fallback result

### Requirement: Media Transport Remains Separate From Chat

Chat operations in mixed-purpose modules SHALL migrate, while non-chat image, audio, speech, and other media transport SHALL remain unchanged.

#### Scenario: Chat writes a prompt for a media operation
- **WHEN** a chat operation generates text later consumed as an image prompt
- **THEN** that text-chat operation SHALL use the facade
- **AND** the subsequent image or audio transport SHALL remain outside the G6 migration

### Requirement: Shared Runtime Party Shapes Remain Supported

The migration SHALL preserve shared chat behavior for both the 1-PC regression floor and multi-PC parties without adding party-size or mode gates.

#### Scenario: Chat runs in either supported party shape
- **WHEN** the same shared runtime operation is exercised with a 1-PC or multi-PC party
- **THEN** routing SHALL use the same facade contract
- **AND** party identity, mechanics, and state behavior SHALL remain unchanged
