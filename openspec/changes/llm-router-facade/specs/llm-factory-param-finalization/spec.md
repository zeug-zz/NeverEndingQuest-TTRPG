## Purpose

Define factory-side chat parameter finalization: one normalized `extra_body` shape, a single `finalize_chat_params()` assembler that owns GPT-5 temperature policy and retry reasoning escalation, client-level timeout ownership for every chat client, and unchanged behavior for existing factory consumers.

## ADDED Requirements

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

The factory SHALL provide `finalize_chat_params(model, params=None, temperature=None, is_openrouter=False, retry_tier=None)` as the single assembler for chat kwargs: OpenRouter calls receive profile params plus the provided temperature, direct-OpenAI GPT-5 family calls omit temperature and apply the GPT-5 reasoning profile, and other direct-OpenAI models receive the platform temperature.

#### Scenario: GPT-5 omits legacy temperature

- **WHEN** `finalize_chat_params("gpt-5.6-luna", temperature=0.7, is_openrouter=False)` is called
- **THEN** the returned kwargs SHALL NOT contain `temperature`
- **AND** they SHALL contain the GPT-5 reasoning profile fields for the task family

#### Scenario: OpenRouter keeps temperature

- **WHEN** `finalize_chat_params("deepseek/deepseek-v4-flash-0731", temperature=0.7, is_openrouter=True)` is called
- **THEN** the returned kwargs SHALL contain `temperature` with the provided value
- **AND** they SHALL include the supplied profile params

#### Scenario: Non-GPT-5 OpenAI model keeps platform temperature

- **WHEN** a direct-OpenAI model outside the GPT-5 family is finalized with a temperature
- **THEN** the returned kwargs SHALL contain that temperature

### Requirement: Retry Reasoning Escalation Parity

Reasoning escalation for retry attempts SHALL travel through the `retry_tier` parameter of `finalize_chat_params()` and SHALL NOT appear in outgoing request kwargs; a direct-OpenAI GPT-5 call finalized with `retry_tier="high"` SHALL reproduce the legacy `get_chat_completion_params(task, ..., retry_tier="high")` reasoning kwargs for that task family.

#### Scenario: High retry tier escalates reasoning

- **WHEN** `finalize_chat_params(..., retry_tier="high", is_openrouter=False)` finalizes a GPT-5 model
- **THEN** the reasoning effort SHALL match the legacy shim's high-retry output for the task family
- **AND** `retry_tier` SHALL NOT be present in the returned kwargs

#### Scenario: Retry tier is not leaked to the SDK

- **WHEN** finalized kwargs are passed to `chat.completions.create`
- **THEN** the request SHALL contain no unknown `retry_tier` field

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

Legacy helpers (`get_model_config`, `get_chat_completion_params`, `create_chat_client`) SHALL remain importable with unchanged contracts, and their behavior with `LLM_PROVIDER = "openai"` SHALL be unchanged by this change.

#### Scenario: Legacy params shim output is unchanged on OpenAI

- **WHEN** `get_chat_completion_params()` is called with the direct-OpenAI posture after this change
- **THEN** the returned kwargs SHALL match the pre-change output for the same task and model

#### Scenario: Factory consumers still compile

- **WHEN** every production module that imports `utils.ai_client_factory` is compiled
- **THEN** compilation SHALL succeed without source edits to those modules
