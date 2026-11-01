## Purpose

Define the chat facade, bounded recovery, actual-model cost accounting, gated decision stub, and provider-free benchmark contract with owner-attested live candidate acceptance distinct from implementation verification.

## ADDED Requirements

### Requirement: Unified Chat Facade Entrypoint

The system SHALL provide a single internal facade entrypoint, `llm.call()`, for chat completions that accepts a `task` identifier, normalized `messages`, and optional call overrides (`json_output`, `temperature`, `max_tokens`, `retry_tier`), and SHALL return assistant content as text by default or a parsed dictionary when `json_output=True`.

#### Scenario: Text call returns content

- **WHEN** a caller invokes `llm.call(task=..., messages=...)` without `json_output`
- **THEN** the facade SHALL return the assistant message content as text
- **AND** the facade SHALL resolve model, params, provider preferences, and pricing from the active profile tier for that task

#### Scenario: Structured call returns parsed JSON

- **WHEN** a caller invokes `llm.call(..., json_output=True)`
- **THEN** the facade SHALL parse the assistant content as JSON and return a dictionary
- **AND** the facade SHALL attempt bounded retries before raising `LLMJSONError`

### Requirement: Direct OpenAI Compatibility And Approved Model Refresh

With `LLM_PROVIDER = "openai"`, facade calls SHALL use configurable `OPENAI_FALLBACK_MODEL = "gpt-6-luna"`, preserve existing task-specific parameter policy and returned content shape, and perform no production call-site migration. The intentional OpenAI model refresh and client timeout bound SHALL be the only approved existing-runtime behavior changes in this change.

#### Scenario: Direct-OpenAI posture resolves the fallback profile

- **WHEN** the actual provider is direct OpenAI and a task is routed through `llm.call()`
- **THEN** the facade SHALL resolve the `openai/fallback` profile tier for that task's complexity
- **AND** the request SHALL NOT include an OpenRouter `provider` field
- **AND** both simple and complex tasks SHALL default to `gpt-6-luna`

#### Scenario: No production call site is edited

- **WHEN** this change's implementation is reviewed
- **THEN** production files outside `model_config.py` and `utils/ai_client_factory.py` SHALL remain unmodified
- **AND** `utils/llm_router.py`, its provider-free tests, and the bake-off harness SHALL be the only additions

### Requirement: Router Is Transport-Only

The router SHALL be transport and orchestration only and MUST NOT mutate gameplay state, combat state, party tracker state, or persisted JSON files.

#### Scenario: Router used in a combat or narration flow

- **WHEN** a consumer uses router output to drive game actions
- **THEN** all state mutations SHALL remain in existing action handlers and managers
- **AND** the router SHALL NOT write to any module, encounter, or character file

### Requirement: Provider Error Classification and Outcome Policy

The router SHALL classify provider failures deterministically before returning or raising: quota or billing exhaustion is a hard stop, transient failures trigger at most one automatic fallback to direct OpenAI, JSON parse failures retry up to three fresh attempts, and unclassified errors are re-raised to the caller.

#### Scenario: Quota or billing failure hard-stops

- **WHEN** a call fails with a quota, billing, payment, or account-balance error
- **THEN** the router SHALL stop retrying and raise `GameLLMError` with an ASCII recovery message
- **AND** the error SHALL identify the failing task and model

#### Scenario: Transient failure falls back once

- **WHEN** a call fails with a retryable condition (timeout, connection failure, rate limit, 429, 502, 503, 504, or overload) and no fallback has been used for that call
- **THEN** the router SHALL retry once against the `openai/fallback` profile through a direct OpenAI client without the `provider` field
- **AND** the router SHALL increment the fallback counter and log the switch

#### Scenario: Fallback failure is terminal

- **WHEN** the fallback attempt also fails, or a retryable failure occurs after fallback was already used for that call
- **THEN** the router SHALL stop and re-raise the terminal error to the caller

#### Scenario: Fallback notification reaches the UI surface

- **WHEN** the router performs an automatic fallback
- **THEN** it SHALL record the event through the existing factory notification path so a single system message can be surfaced once per session
- **AND** the notification text SHALL be ASCII-only

#### Scenario: JSON retry exhausts attempts

- **WHEN** a `json_output=True` call returns content that cannot be parsed as JSON on all attempts
- **THEN** the router SHALL raise `LLMJSONError` naming the task
- **AND** each retry SHALL issue a fresh provider call rather than replaying the previous response

### Requirement: Cache-Aware Thread-Safe Usage Statistics

The router SHALL maintain locked session statistics separating fresh prompt, cached prompt, and completion tokens. It SHALL prefer finite non-negative provider-reported `usage.cost` in USD, attribute usage to the actual response model, and use configured pricing only as an explicitly labelled estimate when provider cost is absent. Missing cost and pricing SHALL be reported as unpriced, not as a fabricated free or fixed-price Auto call.

#### Scenario: Auto reports actual model and actual cost

- **WHEN** a request to `openrouter/auto` returns a concrete response model and `usage.cost`
- **THEN** `by_model` SHALL attribute tokens and cost to that concrete model
- **AND** the total SHALL include the reported cost exactly once, without also adding a static estimate
- **AND** diagnostic metadata SHALL distinguish the requested Auto slug from the resolved model

#### Scenario: Cache reads are costed separately

- **WHEN** provider cost is absent, configured model pricing exists, and a response reports `prompt_tokens` and `prompt_tokens_details.cached_tokens`
- **THEN** fresh tokens SHALL be costed at the tier prompt rate
- **AND** cached tokens SHALL be costed at the tier `cache_read` rate when present, otherwise at the prompt rate

#### Scenario: Missing dynamic cost is visible

- **WHEN** an Auto response has tokens but no usable cost or configured pricing
- **THEN** token accounting SHALL still succeed and `unpriced_calls` SHALL increase
- **AND** `cost_complete` SHALL be false and the numeric cost total SHALL remain a known-cost subtotal
- **AND** a missing actual response model SHALL use an explicit unknown-model bucket

#### Scenario: Concurrent updates remain consistent

- **WHEN** multiple threads record usage concurrently
- **THEN** `llm.get_usage_stats()` SHALL return internally consistent totals
- **AND** the returned dictionary SHALL be a copy that does not expose internal mutable state

#### Scenario: Session reset

- **WHEN** a session starts and calls `llm.reset_usage_stats()`
- **THEN** counters and per-model and per-task maps SHALL reset to zero
- **AND** statistics SHALL remain available for the session

#### Scenario: Missing usage metadata is tolerated

- **WHEN** a provider response carries no usage metadata
- **THEN** the call SHALL succeed and counters SHALL remain consistent

### Requirement: Decisions Primitive Fails Closed

The router SHALL expose `llm.decide()` as an unavailable, gated stub: it SHALL perform no provider call, SHALL reject all inputs by raising `GameLLMError` whose message documents the `unavailable` status and the pending decomposition gate, and SHALL NOT be called from any production code path in this change.

#### Scenario: Decide stub rejects a call

- **WHEN** any caller invokes `llm.decide(...)`
- **THEN** it SHALL raise `GameLLMError` identifying the decisions primitive as `unavailable`
- **AND** no provider client SHALL be created

#### Scenario: Production code does not call decide

- **WHEN** the provider-free test suite scans production modules
- **THEN** no production module SHALL import or call `llm.decide()`
- **AND** only tests and future gated changes SHALL reference the primitive

### Requirement: Bake-Off Gate Is Provider-Free By Default

The router workstream SHALL ship a bake-off harness (`scripts/benchmark_model_profiles.py`) that scores profile tiers on fixed production-shaped fixtures, makes zero provider calls by default, and exposes real provider calls only behind an explicit `--live` opt-in that never runs in CI.

#### Scenario: Default run makes no provider calls

- **WHEN** the harness runs without `--live`
- **THEN** it SHALL use bundled fixtures and a fake transport
- **AND** it SHALL complete without any network request or API key

#### Scenario: Live mode is explicit and bounded

- **WHEN** `--live` is passed and OpenRouter is configured
- **THEN** the harness MAY issue real calls for the selected profile
- **AND** it SHALL fail with a clear message rather than silently degrading when provider configuration is absent

#### Scenario: Gate criteria are reported

- **WHEN** the harness evaluates `production-auto` for narrator and combat fixtures
- **THEN** it SHALL report JSON-validity rate, latency, throughput, token usage, cache-read rate, and cost per call per candidate
- **AND** new optional live comparisons SHALL use configurable `gpt-6-luna` as the OpenAI reference and actual reported Auto model/cost
- **AND** fake-transport results SHALL NOT be presented as measured live quality, latency, or cost

#### Scenario: Owner-attested bake-off is accepted without repetition

- **WHEN** implementation evaluates the recorded 2026-10-13 owner instruction that the live bake-off completed successfully
- **THEN** the live candidate-acceptance portion of G2 SHALL be treated as PASS without a mandatory rerun
- **AND** provider-free implementation checks and later live activation smoke SHALL remain required
- **AND** no missing benchmark measurements SHALL be invented
