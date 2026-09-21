## Purpose

Defines the provider-neutral request contract that keeps GPT-5-family build-time calls compatible while preserving existing behavior for other model families.

## ADDED Requirements

### Requirement: GPT-5 build requests use supported parameters

GPT-5-family build-time Chat Completions requests MUST omit legacy `temperature` and `top_p` values unless the provider contract explicitly supports them, and MUST include the configured GPT-5 reasoning and verbosity profile.

#### Scenario: Direct GPT-5 builder request

- **WHEN** a build-time caller selects a GPT-5-family direct-OpenAI model
- **THEN** the request contains the task profile and does not contain unsupported legacy sampling parameters

#### Scenario: Compatible non-GPT-5 request

- **WHEN** a build-time caller selects a model family that supports the configured sampling override
- **THEN** the request preserves the caller's compatible sampling behavior

### Requirement: Build task profiles remain stable

The request contract MUST resolve reasoning and verbosity from the caller's task identity rather than from a global build default.

#### Scenario: Validation task

- **WHEN** a build-time validation call requests its validation task profile
- **THEN** the request uses the validation reasoning and verbosity settings

#### Scenario: Creative builder task

- **WHEN** a ModuleBuilder generation call requests its builder task profile
- **THEN** the request uses the builder reasoning and verbosity settings

### Requirement: Request compatibility is provider-preserving

The compatibility boundary MUST preserve existing OpenRouter model identifiers and provider-specific request fields.

#### Scenario: OpenRouter build request

- **WHEN** the configured provider is OpenRouter
- **THEN** the request retains the existing OpenRouter model and thinking/request shape

#### Scenario: Provider switch after configuration

- **WHEN** the same task is resolved for direct OpenAI and OpenRouter
- **THEN** only provider-supported fields differ and task identity remains unchanged
