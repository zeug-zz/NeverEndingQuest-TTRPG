# llm-model-profile-routing Specification

## Purpose

Define configurable Auto and direct-OpenAI profiles, safe concrete defaults, independent narrator/combat/Titan selection, and portable request settings without maintaining a fixed downstream model roster.

## Requirements

### Requirement: Tiered Profile Data Model

`model_config.py` SHALL define tiered `MODEL_PROFILES` named `production-auto`, `titan-auto`, and `openai/fallback`, and a concrete `DEFAULT_PROFILE` equivalent to `production-auto`. Each tier SHALL carry `model`, `params`, `provider`, and `price_per_1k` mappings; Auto pricing SHALL be empty unless an explicit verified estimate is configured. Profile-level `supports_json_mode` and `max_context` metadata SHALL be optional rather than invented for a dynamically selected model.

#### Scenario: Known profile resolves both tiers

- **WHEN** routing resolves `production-auto` for a complex task and a simple task
- **THEN** each tier SHALL supply its own model, params, provider preferences, and pricing
- **AND** both tiers SHALL default to `openrouter/auto` without a fixed downstream model allowlist

#### Scenario: Profile swap is config-only

- **WHEN** `ACTIVE_PROFILE` is changed to another defined profile key and the process restarts
- **THEN** subsequent routing SHALL select that profile's tier models
- **AND** no code change SHALL be required

#### Scenario: Preferred direct-OpenAI model

- **WHEN** the direct-OpenAI or fallback profile is resolved
- **THEN** both tiers SHALL select `OPENAI_FALLBACK_MODEL`, whose default is `gpt-6-luna`
- **AND** no new active assignment SHALL introduce `gpt-5.4-nano`

### Requirement: Unknown or Incomplete Profiles Degrade Safely

Resolution SHALL fall back to `DEFAULT_PROFILE` when `ACTIVE_PROFILE` names a profile that does not exist, and SHALL treat missing tier fields as empty structures rather than failing the call.

#### Scenario: Unknown active profile

- **WHEN** `ACTIVE_PROFILE` names a key absent from `MODEL_PROFILES`
- **THEN** resolution SHALL use `DEFAULT_PROFILE` without raising
- **AND** a missing or `None` OpenRouter tier model SHALL resolve to `openrouter/auto`
- **AND** the unknown profile label SHALL NOT be sent as a model ID

#### Scenario: Missing tier fields

- **WHEN** a profile tier omits `params`, `provider`, or `price_per_1k`
- **THEN** resolution SHALL substitute empty structures
- **AND** a missing tier model SHALL use the concrete default for the actual provider

### Requirement: Global and Per-Task Selection

OpenRouter routing SHALL select the active profile tier and allow `TASK_OVERRIDES` to redirect a task to another profile or explicit model. Direct-OpenAI routing and automatic fallback SHALL always select `openai/fallback`, ignoring OpenRouter task overrides so no OpenRouter model slug is sent to a direct-OpenAI client.

#### Scenario: Task override selects a profile

- **WHEN** the actual provider is OpenRouter and `TASK_OVERRIDES` maps a task to a `profile` entry
- **THEN** that task SHALL resolve tiers from the named profile
- **AND** other tasks SHALL continue to use `ACTIVE_PROFILE`

#### Scenario: Task override selects an explicit model

- **WHEN** the actual provider is OpenRouter and `TASK_OVERRIDES` maps a task to an explicit `model` entry
- **THEN** resolution SHALL use that model for the task
- **AND** resolution SHALL NOT apply the profile tier's `params` block to that call

#### Scenario: Independent narrator combat and Titan configuration

- **WHEN** `dm_main`, `combat_main`, and `titan_cycle` are resolved under the default configuration
- **THEN** each SHALL target `openrouter/auto`, with `titan_cycle` selecting `titan-auto`
- **AND** changing one task override SHALL NOT change the other tasks' targets

#### Scenario: OpenRouter override is isolated from fallback

- **WHEN** an OpenRouter task override selects `openrouter/auto` or another vendor model and the request falls back to direct OpenAI
- **THEN** the fallback SHALL select `OPENAI_FALLBACK_MODEL` with direct-OpenAI parameters
- **AND** it SHALL discard OpenRouter-only settings

### Requirement: Model-Agnostic Task Complexity Classification

`model_config.py` SHALL expose `COMPLEX_TASKS` (renamed from `THINKING_ENABLED_TASKS`) with the same task identifiers, SHALL retain `THINKING_ENABLED_TASKS` as a backward-compatible alias during the transition, and SHALL express task complexity through profile tiers rather than model-specific feature flags.

#### Scenario: Complex task selects the complex tier

- **WHEN** a task is a member of `COMPLEX_TASKS`
- **THEN** resolution SHALL select the profile's `complex` tier
- **AND** a task outside that set SHALL select the `simple` tier

#### Scenario: Legacy alias remains importable

- **WHEN** legacy code imports `THINKING_ENABLED_TASKS`
- **THEN** the name SHALL resolve to the same task set as `COMPLEX_TASKS`
- **AND** existing import sites SHALL continue to compile without edits

### Requirement: Provider Preferences Travel With The Tier

Each resolved tier's `provider` block SHALL be transmitted as the OpenRouter `provider` request field when the actual provider is OpenRouter, and SHALL be omitted entirely for direct-OpenAI calls.

#### Scenario: OpenRouter posture attaches provider preferences

- **WHEN** the actual provider is OpenRouter and the tier defines a non-empty `provider` block
- **THEN** the outgoing request SHALL include that block as the `provider` field
- **AND** an empty block SHALL NOT be attached

#### Scenario: Direct-OpenAI posture omits provider preferences

- **WHEN** the actual provider is direct OpenAI
- **THEN** the outgoing request SHALL NOT include a `provider` field

### Requirement: Auto Settings Remain Configurable And Portable

Auto profiles SHALL default to empty model-specific params and provider preferences. Optional Auto settings SHALL use the `auto-router` plugin under SDK-compatible `extra_body`; the router SHALL NOT maintain or periodically refresh its own downstream model list.

#### Scenario: Auto request uses the virtual model

- **WHEN** a default narrator, combat, or Titan request is finalized for OpenRouter
- **THEN** its requested model SHALL be `openrouter/auto`
- **AND** no GPT-specific reasoning, verbosity, or legacy Kimi `thinking` field SHALL be injected by default

#### Scenario: Optional routing policy stays in config

- **WHEN** a profile explicitly configures documented `auto-router` settings such as `cost_tier` or `allowed_models`
- **THEN** the settings SHALL travel under `extra_body.plugins` with plugin ID `auto-router`
- **AND** direct-OpenAI calls SHALL omit those settings

### Requirement: Deprecated Selection Constants Remain Non-Authoritative

`OPENROUTER_STRATEGY`, `OPENROUTER_FULL_MODEL`, `OPENROUTER_MINI_MODEL`, and `OPENROUTER_CHAT_MODEL` SHALL remain importable with deprecation comments during the transition, and router routing SHALL NOT consult them.

#### Scenario: Deprecated constants are marked

- **WHEN** `model_config.py` is inspected
- **THEN** each deprecated constant SHALL carry a comment naming its replacement
- **AND** existing factory consumers SHALL keep working unchanged

#### Scenario: Router ignores deprecated strategy

- **WHEN** a call is routed through the facade
- **THEN** tier selection SHALL come from `MODEL_PROFILES` only
- **AND** `OPENROUTER_STRATEGY` SHALL NOT alter the resolved model
