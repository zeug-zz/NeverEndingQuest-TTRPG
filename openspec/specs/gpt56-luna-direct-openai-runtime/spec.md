# gpt56-luna-direct-openai-runtime Specification

## Purpose
Provides a controlled direct-OpenAI rollout of GPT-5.6 Luna while preserving the repository's existing GPT-5-family request compatibility, runtime observability, and rollback behavior.
## Requirements
### Requirement: Direct OpenAI model selection

The active direct-OpenAI GPT-5 runtime roles MUST resolve to the exact model ID `gpt-5.6-luna` after configuration is loaded.

#### Scenario: Runtime configuration selects Luna

- **WHEN** the application loads the active direct-OpenAI model configuration
- **THEN** narrator, combat, validation, and configured utility GPT-5 roles that previously selected GPT-5.4 Mini SHALL select `gpt-5.6-luna`
- **AND** no active alternate GPT-5 selector branch SHALL select `gpt-5.4-mini-2026-03-17`

### Requirement: GPT-5-family parameter compatibility

Requests using `gpt-5.6-luna` MUST continue through the existing GPT-5-family Chat Completions parameter policy.

#### Scenario: Main or combat request uses medium effort

- **WHEN** chat parameters are built for `gpt-5.6-luna` with a main narration or combat task
- **THEN** the request SHALL include `reasoning_effort="medium"`
- **AND** the request SHALL include the task's existing verbosity value
- **AND** the request SHALL omit legacy `temperature` and `top_p` by default

#### Scenario: Validation request preserves the existing low-effort profile

- **WHEN** chat parameters are built for `gpt-5.6-luna` with a validation task
- **THEN** the request SHALL preserve the existing low reasoning and low verbosity profile
- **AND** the request SHALL omit legacy `temperature` and `top_p` by default

#### Scenario: Retry escalation remains unchanged

- **WHEN** an existing GPT-5-family retry path requests high reasoning
- **THEN** the `gpt-5.6-luna` request SHALL use high reasoning effort
- **AND** no new retry count or retry routing policy SHALL be introduced by the model swap

### Requirement: Active model identity observability

The runtime's human-readable model identity and existing model-selection logging MUST identify Luna when Luna is selected.

#### Scenario: Model status identifies Luna

- **WHEN** the configured direct-OpenAI model is `gpt-5.6-luna`
- **THEN** display and diagnostic model-name helpers SHALL return a Luna-specific human-readable label
- **AND** model-selection diagnostics SHALL record `gpt-5.6-luna` as the selected model

### Requirement: Direct-OpenAI scope isolation

The change MUST not alter OpenRouter model selection or OpenRouter-specific request parameters.

#### Scenario: OpenRouter configuration remains unchanged

- **WHEN** the repository's OpenRouter configuration is inspected after this change
- **THEN** `OPENROUTER_CHAT_MODEL` and existing OpenRouter `thinking` request behavior SHALL remain unchanged
- **AND** no direct-OpenAI Luna model ID SHALL be substituted into the OpenRouter path by this change

### Requirement: Failure and rollback safety

An unavailable or rejected Luna model MUST fail through the existing provider/error handling path without silently selecting GPT-5.4 Mini.

#### Scenario: Provider rejects Luna

- **WHEN** direct OpenAI rejects a request for `gpt-5.6-luna`
- **THEN** the existing error and retry behavior SHALL surface or handle the failure
- **AND** the runtime SHALL NOT silently substitute `gpt-5.4-mini-2026-03-17`

#### Scenario: Operator rolls back the model

- **WHEN** an operator restores the prior model assignments and restarts the server
- **THEN** the application SHALL resume selecting `gpt-5.4-mini-2026-03-17`
- **AND** the GPT-5-family shim behavior SHALL remain available

### Requirement: Single-player and tabletop compatibility

The model swap MUST use the same configuration and request-parameter behavior in single-player and TABLETOP MODE paths.

#### Scenario: Both runtime modes use Luna

- **WHEN** the same active model configuration is loaded in single-player or TABLETOP MODE
- **THEN** the applicable GPT-5 runtime calls SHALL select `gpt-5.6-luna`
- **AND** no mode-specific gameplay or persisted-state migration SHALL be required
