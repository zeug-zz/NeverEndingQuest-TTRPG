# Spec Delta

## Purpose

Defines how production chat activates OpenRouter Auto while retaining independent task routing, provider-family sampling rules, observable cost provenance, and a bounded direct-OpenAI recovery path.

## ADDED Requirements

### Requirement: Auto empty content is recovered, never returned

When the requested model is `openrouter/auto`, the router SHALL apply bounded empty-transient
recovery by default for all tasks, including JSON output, and SHALL NOT return `None` content to a
caller.

#### Scenario: Reasoning-only Auto response
- **WHEN** an Auto response has `finish_reason=stop` and null content
- **THEN** the router SHALL classify it as empty transient and retry within the existing per-provider bound
- **AND** after exhaustion it SHALL raise `EmptyProviderResponseError` within one fallback transition and six SDK invocations

#### Scenario: Direct OpenAI default unchanged
- **WHEN** the request is direct OpenAI and no `empty_retry_limit` is supplied
- **THEN** empty-transient recovery SHALL remain off

### Requirement: Factory-owned total request deadline

Each SDK attempt SHALL be bounded by a total wall-clock deadline of `API_TIMEOUT_SECONDS`, enforced
at the transport, regardless of response-body chunk cadence.

#### Scenario: Keep-alive body exceeds deadline
- **WHEN** a response body keeps delivering chunks past `API_TIMEOUT_SECONDS`
- **THEN** the attempt SHALL fail as a timeout transport error and follow the bounded transient-fallback policy

### Requirement: Auto JSON-contract requests use JSON mode without changing return semantics

`llm.call` SHALL accept a keyword-only `json_contract` boolean that defaults to false. When it is
true on an Auto attempt, the router SHALL request JSON mode. The router SHALL preserve raw-string
return behavior and reject non-boolean values before transport. Direct attempts and unmarked Auto
requests SHALL remain unchanged.

#### Scenario: Auto JSON-contract response remains a raw string
- **WHEN** an Auto request sets `json_contract=True` and the caller does not supply `response_format`
- **THEN** the provider request SHALL carry `response_format={"type":"json_object"}`
- **AND** the router SHALL return the provider content as a raw string without parsing it

#### Scenario: Direct OpenAI JSON-contract request is unchanged
- **WHEN** a direct-OpenAI request sets `json_contract=True`
- **THEN** the router SHALL NOT add a response format
- **AND** an Auto request that falls back to direct OpenAI SHALL NOT carry the router-added response format on the fallback attempt

#### Scenario: Auto request without a JSON contract is unchanged
- **WHEN** an Auto request sets `json_contract=False`
- **THEN** the router SHALL NOT add a response format

#### Scenario: Caller-supplied response format is preserved
- **WHEN** a request sets `json_contract=True` and supplies `response_format`
- **THEN** the router SHALL preserve the caller-supplied value without replacement

#### Scenario: Non-boolean JSON-contract signal is rejected
- **WHEN** `json_contract` is not a boolean
- **THEN** the router SHALL reject the request before provider transport

### Requirement: Validator Auto requests select the medium Auto Router cost tier

Configured response-validator tasks SHALL request the `medium` cost tier only through the
`auto-router` plugin on `openrouter/auto`. Configured tiers SHALL be validated before client
construction or transport against `low`, `medium`, `high`, `xhigh`, and `max`. A caller-supplied
`auto-router` plugin SHALL be preserved without duplication.

#### Scenario: Configured validator uses medium tier on Auto
- **WHEN** a configured response-validator task resolves to `openrouter/auto` and has no
  caller-supplied `auto-router` plugin
- **THEN** the request SHALL contain exactly one plugin with `id: "auto-router"` and
  `cost_tier: "medium"`

#### Scenario: Direct-OpenAI validator request has no Auto Router plugin
- **WHEN** a configured response-validator task resolves to direct OpenAI, including an Auto
  fallback attempt
- **THEN** the request SHALL contain no generated `auto-router` plugin or cost setting

#### Scenario: Invalid configured tier fails before transport
- **WHEN** a configured validator tier is not one of `low`, `medium`, `high`, `xhigh`, or `max`
- **THEN** the router SHALL raise `ValueError` before client construction or provider transport

#### Scenario: Existing caller plugin is preserved without duplication
- **WHEN** an Auto request has a caller-supplied `plugins` list containing an `auto-router` entry
- **THEN** the request SHALL preserve that entry and SHALL NOT add a duplicate `auto-router` entry

### Requirement: `dm_main` Auto requests select the medium Auto Router cost tier

Requests using task `dm_main` SHALL request `medium` through `auto-router` whenever the request
model is exactly `openrouter/auto`. Apply the tier regardless of prose/JSON-contract mode, including
`json_contract=True` narrator calls. Other task IDs SHALL retain their existing tier policy.
Direct-OpenAI requests, including fallbacks, SHALL NOT receive a generated plugin or cost setting.

#### Scenario: `dm_main` JSON-contract request uses medium tier on Auto
- **WHEN** a request uses task `dm_main`, has `json_contract=True`, resolves to `openrouter/auto`,
  and has no caller-supplied `auto-router` plugin
- **THEN** the request SHALL contain exactly one plugin with `id: "auto-router"` and
  `cost_tier: "medium"`

#### Scenario: `dm_main` prose request uses medium tier on Auto
- **WHEN** a prose request uses task `dm_main`, has `json_contract=False`, resolves to
  `openrouter/auto`, and has no caller-supplied `auto-router` plugin
- **THEN** the request SHALL contain exactly one plugin with `id: "auto-router"` and
  `cost_tier: "medium"`

#### Scenario: Other non-validator task keeps the default tier
- **WHEN** a task other than a configured validator or `dm_main` (for example `action_prediction`)
  resolves to `openrouter/auto`
- **THEN** the request SHALL contain no generated `auto-router` plugin or cost setting

#### Scenario: Direct-OpenAI `dm_main` request has no generated Auto Router plugin
- **WHEN** a `dm_main` request resolves to direct OpenAI, including an Auto fallback attempt
- **THEN** the request SHALL contain no generated `auto-router` plugin or cost setting

### Requirement: Production Auto activation is gated by G7

After a primary-owned G7 PASS, production chat SHALL use `LLM_PROVIDER = "openrouter"` and `ACTIVE_PROFILE = "production-auto"`.

#### Scenario: Activate after G7 passes
- **WHEN** the primary has recorded G7 PASS and the production runtime restarts with the approved configuration
- **THEN** narrator and combat chat SHALL request `openrouter/auto` through `production-auto`
- **AND** direct OpenAI SHALL remain available only as the configured fallback or explicit rollback posture

#### Scenario: G7 has not passed
- **WHEN** G7 is BLOCKED or FAIL
- **THEN** the production-default flip and all G9 live execution SHALL remain unperformed

### Requirement: Narrator, combat, and Titan routing remain independently configurable

The runtime SHALL allow `dm_main`, `combat_main`, and `titan_cycle` to select their profiles independently without changing another task's profile.

#### Scenario: Change one task profile
- **WHEN** one of `dm_main`, `combat_main`, or `titan_cycle` receives a profile override
- **THEN** only that task's resolved profile SHALL change
- **AND** Titan configuration SHALL NOT create or imply a Titan runtime

#### Scenario: Titan uses the configured task seam
- **WHEN** a provider-free test resolves `titan_cycle`
- **THEN** it SHALL select the configured Titan profile and use fake transport only
- **AND** no live Titan application run SHALL be required or claimed

### Requirement: Every production task has explicit family sampling policy

Every production chat task SHALL define explicit reasoning and non-reasoning sampling entries; an unconfigured production task SHALL NOT silently inherit a global sampling default.

#### Scenario: Production task policy coverage
- **WHEN** the configured task policies are compared with all production facade task identifiers
- **THEN** every identifier SHALL have both a reasoning-family and non-reasoning-family entry
- **AND** the non-reasoning entry SHALL contain an explicit numeric `temperature`
- **AND** `top_p` SHALL be omitted unless the task policy explicitly defines it

#### Scenario: Missing task policy
- **WHEN** a production task has no sampling policy entry
- **THEN** the request SHALL fail before provider transport with an explicit configuration error

### Requirement: Factory finalizes sampling by request family

The factory SHALL omit `temperature` and `top_p` for reasoning-family requests and SHALL apply the selected task's explicit values for non-reasoning requests.

#### Scenario: Direct reasoning-family request
- **WHEN** a task request resolves to the supported direct reasoning model `gpt-6-luna`
- **THEN** the outgoing request SHALL omit `temperature` and `top_p`
- **AND** the existing task reasoning and verbosity policy SHALL remain unchanged

#### Scenario: OpenRouter Auto request
- **WHEN** a production task is sent as `openrouter/auto` and the downstream model is not yet known
- **THEN** the factory SHALL use that task's explicit non-reasoning sampling entry
- **AND** the request SHALL use the task's configured `temperature`
- **AND** it SHALL include `top_p` only when that task's policy defines a value

#### Scenario: Compression keeps its non-reasoning temperature
- **WHEN** `compression` is finalized for a non-reasoning request
- **THEN** its configured temperature SHALL remain `0.3`
- **AND** its `top_p` SHALL come from the explicit compression policy entry

### Requirement: Transient transport fallback is bounded and direct

A classified transient OpenRouter transport failure SHALL use at most one fallback attempt through direct OpenAI `gpt-6-luna`; quota and billing failures SHALL remain terminal.

#### Scenario: OpenRouter transport failure
- **WHEN** an OpenRouter chat request fails with a classified transient transport error
- **THEN** the router SHALL make at most one direct-OpenAI fallback attempt using `gpt-6-luna`
- **AND** OpenRouter provider preferences and extensions SHALL NOT be sent to that fallback client

#### Scenario: Quota failure
- **WHEN** an OpenRouter request returns a quota or billing failure
- **THEN** the router SHALL stop without attempting direct-OpenAI fallback

### Requirement: Actual model and cost provenance remain observable

Each received response SHALL preserve requested model, resolved response model, actual transport provider, observed upstream provider when present, usage completeness, cost provenance, and cost completeness.

#### Scenario: OpenRouter reports actual model and cost
- **WHEN** an Auto response includes a concrete `response.model` and finite non-negative `usage.cost`, including zero
- **THEN** accounting SHALL retain `openrouter/auto` as requested and the response model as resolved
- **AND** it SHALL count the reported cost once as actual without adding an estimate

#### Scenario: Auto response has no usable cost
- **WHEN** an Auto response has no usable reported cost and no verified rate for its resolved model
- **THEN** accounting SHALL label the call unpriced, set cost completeness false, and retain token usage and known-cost subtotals
- **AND** it SHALL NOT use a blended Auto estimate or describe the call as free

#### Scenario: Resolved model has verified configured rates
- **WHEN** reported cost is absent and verified rates match the concrete resolved model
- **THEN** accounting SHALL label the derived amount estimated and mark that call priced
- **AND** it SHALL NOT apply a rate configured for a different model or for `openrouter/auto`

### Requirement: Operator rollback restores the preferred direct model

An operator rollback SHALL restore direct OpenAI `gpt-6-luna` after one server restart without changing prompts or gameplay mechanics.

#### Scenario: One-restart rollback
- **WHEN** the operator restores the direct-OpenAI provider posture and restarts the sandbox server once
- **THEN** subsequent narrator and combat requests SHALL resolve to direct OpenAI `gpt-6-luna`
- **AND** no OpenRouter-only request setting SHALL reach the direct client

### Requirement: Combat authority and compatibility remain unchanged

Provider activation SHALL preserve Python mechanical authority, `/end` ownership by the DM, 1-PC and 4-PC behavior, prompt bytes, all nine legacy prompt hashes, and G1/G3/G4/G5R goldens unless an explicit gate-specific approval authorizes a change.

#### Scenario: Provider changes without gameplay drift
- **WHEN** routing is exercised under the OpenRouter and direct-OpenAI postures
- **THEN** Python SHALL remain authoritative for mechanics and `/end` SHALL remain DM-owned
- **AND** the approved prompt hashes and G1/G3/G4/G5R goldens SHALL remain byte-identical for both party shapes
