# llm-factory-param-finalization Specification

## Purpose

Define task-aware chat parameter finalization, portable Auto request settings, GPT-5 compatibility and preferred gpt-6-luna reasoning policy, bounded clients, and legacy consumer compatibility apart from the approved OpenAI model refresh.

## Requirements

### Requirement: Normalized Extra Body Shape

`get_model_config()` SHALL return `extra_body` in the nested SDK-compatible shape `{"extra_body": {...}}` on every code path, so `params.update(extra_body)` yields valid Chat Completions kwargs and never a top-level `thinking` keyword.

#### Scenario: Strategy path returns the nested shape

- **WHEN** an OpenRouter strategy path builds additional request parameters
- **THEN** `extra_body` SHALL be nested under the `extra_body` key
- **AND** the resulting kwargs SHALL NOT contain a top-level `thinking` entry

#### Scenario: Override path is consistent

- **WHEN** a `TASK_OVERRIDES` entry supplies provider parameters
- **THEN** `extra_body` SHALL use the same nested shape as every other path

#### Scenario: Direct-OpenAI path stays empty

- **WHEN** the actual provider is direct OpenAI
- **THEN** `extra_body` SHALL be an empty mapping

### Requirement: Chat Parameter Finalization

The factory SHALL provide `finalize_chat_params(model, params=None, temperature=None, is_openrouter=False, retry_tier=None, *, task_id)` as the single assembler for chat kwargs. It SHALL use explicit task context for direct-OpenAI reasoning-family policy, preserve legacy GPT-5 support and apply that task policy to `gpt-6-luna`, omit legacy sampling controls by default for those models, and merge portable OpenRouter extensions under `extra_body`.

#### Scenario: Preferred OpenAI model receives task policy

- **WHEN** `finalize_chat_params("gpt-6-luna", temperature=0.7, is_openrouter=False, task_id="combat_validation")` is called
- **THEN** the returned kwargs SHALL NOT contain `temperature`
- **AND** they SHALL contain the existing validation-family reasoning and verbosity policy
- **AND** narration, summary, and compression tasks SHALL receive their own task-family policy rather than a single global default

#### Scenario: Legacy GPT-5 support is preserved

- **WHEN** a legacy GPT-5 model is finalized with the same task and retry context
- **THEN** its task-policy kwargs SHALL match the existing legacy shim for that model

#### Scenario: OpenRouter keeps temperature

- **WHEN** `finalize_chat_params("openrouter/auto", temperature=0.7, is_openrouter=True, task_id="dm_main")` is called
- **THEN** the returned kwargs SHALL contain `temperature` with the provided value
- **AND** they SHALL include the supplied profile params

#### Scenario: Other OpenAI models keep platform temperature

- **WHEN** a direct-OpenAI model outside the supported reasoning families is finalized with a temperature
- **THEN** the returned kwargs SHALL contain that temperature

### Requirement: Retry Reasoning Escalation Parity

Reasoning escalation SHALL use explicit `task_id` and `retry_tier` factory inputs, neither of which SHALL appear in outgoing kwargs. Direct-OpenAI GPT-5 and `gpt-6-luna` retries SHALL preserve the existing high-reasoning escalation policy; OpenRouter Auto SHALL NOT receive direct-OpenAI `reasoning_effort` or `verbosity` fields.

#### Scenario: High retry tier escalates reasoning

- **WHEN** `finalize_chat_params(..., retry_tier="high", is_openrouter=False, task_id="combat_main")` finalizes a supported direct-OpenAI reasoning model
- **THEN** the reasoning effort SHALL match the legacy shim's high-retry output for the task family
- **AND** `retry_tier` SHALL NOT be present in the returned kwargs

#### Scenario: Retry tier is not leaked to the SDK

- **WHEN** finalized kwargs are passed to `chat.completions.create`
- **THEN** the request SHALL contain neither `retry_tier` nor `task_id`

#### Scenario: Auto extensions are SDK-compatible

- **WHEN** portable OpenRouter profile params include reasoning, provider preferences, or Auto plugins
- **THEN** the factory SHALL merge them under the SDK's `extra_body` mapping
- **AND** it SHALL NOT leak them as unsupported top-level SDK kwargs

### Requirement: Client-Level Timeout Ownership

`model_config.py` SHALL define `API_TIMEOUT_SECONDS` and `API_CONNECT_TIMEOUT_SECONDS`, and both chat client constructors in `ai_client_factory.py` SHALL apply an `httpx.Timeout` using those constants in place of the SDK default wait; this change SHALL NOT add per-call timeout arguments at call sites.

#### Scenario: Direct-OpenAI client is bounded

- **WHEN** `create_chat_client()` builds the direct-OpenAI client
- **THEN** the client SHALL carry an `httpx.Timeout` with the configured total and connect values

#### Scenario: OpenRouter client is bounded

- **WHEN** `create_chat_client()` builds the OpenRouter client
- **THEN** the client SHALL carry the same configured timeout policy
- **AND** the OpenRouter base URL and default headers SHALL be preserved

#### Scenario: No new dependency

- **WHEN** timeout support is implemented
- **THEN** it SHALL use the `httpx` library already supplied by the `openai` SDK
- **AND** no new third-party dependency SHALL be added

### Requirement: Existing Factory Consumers Keep Current Behavior

Legacy helpers SHALL remain importable with unchanged signatures. For the same supplied legacy model and task, their parameter output SHALL remain compatible apart from the new client timeout bound. Active direct-OpenAI chat model assignments in `model_config.py` SHALL receive the owner-approved refresh to `gpt-6-luna`; no other model substitution SHALL be introduced under the compatibility claim.

#### Scenario: Legacy params shim output is unchanged on OpenAI

- **WHEN** `get_chat_completion_params()` is called with the direct-OpenAI posture after this change
- **THEN** the returned kwargs SHALL match the pre-change output for the same task and model

#### Scenario: Factory consumers still compile

- **WHEN** every production module that imports `utils.ai_client_factory` is compiled
- **THEN** compilation SHALL succeed without source edits to those modules
