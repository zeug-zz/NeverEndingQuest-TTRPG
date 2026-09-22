## Purpose

Define the model-agnostic routing data model: tiered `MODEL_PROFILES` v4, safe degradation for unknown or incomplete profiles, global and per-task selection, model-agnostic task complexity classification, and per-tier provider preferences that travel with the profile.

## ADDED Requirements

### Requirement: Tiered Profile Data Model

`model_config.py` SHALL define `MODEL_PROFILES` whose entries carry `complex` and `simple` tiers, where each tier provides `model`, `params`, `provider`, and `price_per_1k` blocks, plus profile-level `supports_json_mode` and `max_context` metadata; it SHALL also define `DEFAULT_PROFILE` with the same shape and `None` tier models.

#### Scenario: Known profile resolves both tiers

- **WHEN** routing resolves `production-2026-09` for a complex task and a simple task
- **THEN** each tier SHALL supply its own model, params, provider preferences, and pricing
- **AND** pricing SHALL include `cache_read` where the tier defines it

#### Scenario: Profile swap is config-only

- **WHEN** `ACTIVE_PROFILE` is changed to another defined profile key and the process restarts
- **THEN** subsequent routing SHALL select that profile's tier models
- **AND** no code change SHALL be required

### Requirement: Unknown or Incomplete Profiles Degrade Safely

Resolution SHALL fall back to `DEFAULT_PROFILE` when `ACTIVE_PROFILE` names a profile that does not exist, and SHALL treat missing tier fields as empty structures rather than failing the call.

#### Scenario: Unknown active profile

- **WHEN** `ACTIVE_PROFILE` names a key absent from `MODEL_PROFILES`
- **THEN** resolution SHALL use `DEFAULT_PROFILE` without raising
- **AND** the resolved model SHALL fall back to the caller-configured model when the profile tier model is `None`

#### Scenario: Missing tier fields

- **WHEN** a profile tier omits `params`, `provider`, or `price_per_1k`
- **THEN** resolution SHALL substitute empty structures
- **AND** the call SHALL still be attempted with the tier model

### Requirement: Global and Per-Task Selection

Routing SHALL select the tier from the active profile, or from the `openai/fallback` profile when the actual provider is direct OpenAI, and `TASK_OVERRIDES` SHALL be able to redirect a single task either to another profile or to an explicit model.

#### Scenario: Task override selects a profile

- **WHEN** `TASK_OVERRIDES` maps a task to a `profile` entry
- **THEN** that task SHALL resolve tiers from the named profile
- **AND** other tasks SHALL continue to use `ACTIVE_PROFILE`

#### Scenario: Task override selects an explicit model

- **WHEN** `TASK_OVERRIDES` maps a task to an explicit `model` entry
- **THEN** resolution SHALL use that model for the task
- **AND** resolution SHALL NOT apply the profile tier's `params` block to that call

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
