# LLM Router Facade - Design

## Context

The router plan (`plans/version-2/openrouter_llm_router_architecture.md`, v4.0) defines a
thin facade over the existing `utils/ai_client_factory.py` infrastructure. This change
implements Phase 0 (config and factory prep) and Phase 1 (facade, unit tests, bake-off
harness) only. No call site is migrated, and `LLM_PROVIDER` stays `"openai"`.

The interleave with `plans/version-2/combat-manager-refactor.md` section 3.1 is binding:
combat Phase 0 latency baseline -> this change's Phase 0/1 -> combat Phase 1 decomposition
-> router Phase 2 Tier 1 migration. This change authors the client-level timeout bound and
the `retry_tier` channel that combat migration later depends on, but it does not touch
combat code.

## Architecture Boundaries (MUST)

```
Callers (later changes only)
        |
        v
utils/llm_router.py      ORCHESTRATION
  llm.call / llm.decide    profile-tier resolution, error classification,
                           fallback decision, JSON retry, usage stats
        |
        v
utils/ai_client_factory.py   PARAM FINALIZATION + CLIENT OWNERSHIP
  create_chat_client           provider-appropriate client, client-level timeout
  finalize_chat_params         profile params + GPT-5 policy + retry_tier
  get_chat_completion_params   legacy shim, unchanged for existing consumers
  handle_provider_error        retryable classification + fallback notification state
        |
        v
model_config.py          CONFIGURATION DATA
  MODEL_PROFILES v4            tiered model + params + provider + pricing
  COMPLEX_TASKS                model-agnostic complexity classification
  TASK_OVERRIDES               per-task profile or explicit model
  API_TIMEOUT_SECONDS          client-level timeout constants
```

Ownership rules:

- The router MUST NOT build provider clients or invent sampling rules; it resolves
  configuration and delegates kwargs assembly to the factory.
- The factory MUST own provider quirks (GPT-5 temperature omission, reasoning profiles,
  `extra_body` shape, timeouts) so those rules live in one place.
- `model_config.py` MUST remain data: profiles, classification, overrides, constants.
- The router MUST NOT mutate gameplay state, combat state, party tracker state, or
  persisted JSON.

Simplest alternative considered: extend `get_chat_completion_params()` into the routing
entrypoint and skip a new module. Rejected because the facade must also own error classes,
fallback orchestration, JSON retry, and session usage stats; folding those into the
factory would blur the param-assembly boundary that the 39 existing factory consumers
depend on. A second alternative, migrating call sites in the same change, was rejected by
the interleave: combat call sites only become named stages after
`combat-manager-decomposition`.

## Behavior-Neutral-On-OpenAI Guarantee (MUST)

With `LLM_PROVIDER = "openai"`:

- Resolution selects the `openai/fallback` profile regardless of `ACTIVE_PROFILE`, so the
  configured OpenAI models and GPT-5 parameter policy are exactly today's behavior.
- No `provider` request field is attached (direct OpenAI ignores it, but it must not be
  sent).
- All existing factory helpers keep their current signatures and outputs.
- No production module imports `utils/llm_router.py`; the facade is only exercised by its
  provider-free tests until later migration changes.

The regression floor is the provider-free router suite plus the existing factory contract
suites (`scripts/test_gpt54_chat_params_contract.py`,
`scripts/test_gpt54_mini_chat_params_shim.py`). Gameplay smoke is deferred to the first
migration change because no runtime path changes here.

## Profile Resolution Flow

1. Read `COMPLEX_TASKS`, `ACTIVE_PROFILE`, `TASK_OVERRIDES`, `TASK_TEMPERATURES`, and
   `MODEL_PROFILES` / `DEFAULT_PROFILE` from `model_config`.
2. Determine the actual provider via the factory's `_get_actual_provider()`.
   - OpenRouter: profile key = `TASK_OVERRIDES[task]["profile"]` if present, else
     `ACTIVE_PROFILE`.
   - Direct OpenAI: profile key = `"openai/fallback"` (overrides may still redirect).
3. Look up the profile; an unknown key resolves to `DEFAULT_PROFILE`.
4. Select the `complex` tier when the task is in `COMPLEX_TASKS`, otherwise `simple`.
5. Resolve model: explicit `TASK_OVERRIDES[task]["model"]` wins; else tier model; else the
   profile key as last resort. Tier `params` apply only when no explicit model override.
6. Attach the tier `provider` block only on OpenRouter calls; attach tier pricing for usage
   accounting.
7. Fallback resolution (`_resolve_fallback`) always uses the `openai/fallback` profile and
   is used with a direct OpenAI client.

## Error Classification and Fallback Flow

| Class | Detection | Outcome |
|---|---|---|
| Quota / billing | message contains quota, billing, payment, `insufficient_quota`, usage-limit, or account-balance terms | hard stop: raise `GameLLMError` with a recovery message naming the task and model |
| Transient | timeout, connection, rate limit, 429, 502, 503, 504, overloaded, unavailable, bad gateway, internal server error | at most one automatic fallback to the `openai/fallback` profile with a direct OpenAI client, no `provider` field, no legacy temperature |
| JSON parse | `json_output=True` content fails parsing | retry the provider call up to three attempts, then raise `LLMJSONError` |
| Other | anything else | re-raise to the caller |

Rules:

- Fallback is bounded to one attempt per call. A second retryable failure raises.
- Quota detection is checked before retryable detection, so a quota message that also
  contains rate-limit wording hard-stops.
- Fallback notification reuses `handle_provider_error()` / `get_fallback_notification()`
  so a single ASCII system message can be surfaced once per session, matching current
  factory behavior.
- Each JSON retry issues a fresh provider call; a response is never replayed.
- `retry_tier` MUST NOT be forwarded as a request kwarg; it is consumed only by
  `finalize_chat_params()`.

## Retry Reasoning Escalation Channel (MUST)

Combat's validation-failure escalation (`GPT5_USE_HIGH_REASONING_ON_RETRY`) must survive
migration, so `retry_tier` is a first-class `llm.call()` parameter:
`retry_tier: Optional[str] = None`, values `"high"` / `"retry"`. The facade passes it to
`finalize_chat_params()`, which applies the GPT-5 reasoning profile for the task family and
raises reasoning effort to high. It is never placed in passthrough `**kwargs`; the OpenAI
SDK would reject the unknown field. Parity target: direct-OpenAI GPT-5 kwargs from
`finalize_chat_params(..., retry_tier="high")` must reproduce the legacy
`get_chat_completion_params(<task>, ..., retry_tier="high")` reasoning kwargs for that task
family.

## Client-Level Timeout Ownership (MUST)

`model_config.py` defines `API_TIMEOUT_SECONDS = 120` and
`API_CONNECT_TIMEOUT_SECONDS = 10`. Both chat client constructors in
`utils/ai_client_factory.py` apply:

```python
httpx.Timeout(API_TIMEOUT_SECONDS, connect=API_CONNECT_TIMEOUT_SECONDS)
```

Rationale: the OpenAI SDK default is 600 seconds, which is unusable for interactive play;
combat validation payloads can be large (46K+ characters observed). One constructor-level
bound replaces per-call timeout arguments. Combat's existing per-call timeout work is
superseded by this bound, but `core/managers/combat_manager.py` is not edited here; the
later migration verifies coverage from the client. `httpx` is already a transitive
dependency of the `openai` SDK, so no new third-party dependency is introduced.

SHOULD: add a short comment at each constructor noting ownership, so future call-site
authors do not add parallel timeout arguments.

## Usage Stats Ownership and Thread Safety (MUST)

- Module-level `_usage_stats` dict guarded by a module-level `threading.Lock`; the Flask +
  SocketIO web server is multi-threaded, following the `pc_manager.py` stats-lock pattern.
- Tracked counters: `prompt_tokens`, `cached_tokens`, `completion_tokens`,
  `total_cost_usd`, `calls`, `errors`, `fallbacks`, plus `by_model` and `by_task` token
  maps.
- Cost math: `fresh = prompt - cached`, then
  `fresh * prompt_rate + cached * cache_read_rate + completion * completion_rate`,
  normalized per 1K tokens using the resolved tier `price_per_1k`; when `cache_read` is
  absent, cached tokens cost at the prompt rate.
- `get_usage_stats()` returns a lock-held copy (no internal references), rounds cost, and
  uses stable keys; `reset_usage_stats()` clears counters for session start.
- Router stats stay separate from `utils/llm_usage_tracker.py`, which continues to own
  DALL-E cost-only events; they are not merged in this change.
- Provider responses without usage metadata MUST NOT fail the call or corrupt counters.

## Bake-Off Gate Design (MUST)

`scripts/benchmark_model_profiles.py` scores profile tiers on fixed production-shaped
fixtures and is the evidence artifact for gate G2.

- Provider-free default: bundled fixtures plus a fake transport; zero network requests and
  no API key required. The provider-free path runs in CI.
- `--live` opt-in: requires explicit flag plus OpenRouter configuration; fails with a clear
  message when configuration is absent; never runs in CI.
- Fixtures cover: narrator turn (DM note plus world state), combat batch validation,
  encounter JSON update, and summary compression.
- Reported per candidate: narration quality rubric, JSON-validity rate, latency p50/p90,
  throughput, token usage, cache-read hit rate, and cost per call.
- Gate criterion: `production-2026-09` narrator and combat tiers must match or beat the
  configured `gpt-5.6-luna` baseline on JSON-validity rate at lower cost before any
  call-site migration is authorized.

## Combat Interleave (MUST)

- `core/managers/combat_manager.py` MUST NOT be edited or migrated by this change.
- Combat Tier 1 migration (`core/combat/*` named stages) follows
  `combat-manager-decomposition`.
- Combat's per-call timeouts are superseded by the client-level bound defined here, but the
  combat file keeps its current timeout code until its migration change removes it.
- The later migration change MUST pass `retry_tier="high"` on validation-failure retries to
  preserve escalation parity.

## Rollback

Config-only:

1. Runtime already uses `LLM_PROVIDER = "openai"`; no activation to undo.
2. Nothing imports `utils/llm_router.py` outside its own tests, so the module can be left
   unreferenced.
3. `COMPLEX_TASKS` keeps the `THINKING_ENABLED_TASKS` alias, and deprecated constants are
   retained, so reverting `model_config.py` changes is safe and non-breaking.
4. The client-level timeout is the only behavioral change touching an existing helper. If
   it must be reverted, restore the constructor default; the router stores no state that
   requires cleanup.

## Open Questions

None outstanding. Resolved during authoring:

- `decide()` failure shape: raise `GameLLMError` (the plan's reference stub) while
  documenting the decisions status as `unavailable`; Jev fallback semantics only matter
  once the primitive exists.
- Config metadata file: not required; validation passes with proposal, design, specs, and
  tasks only (matches the sibling `combat-latency-baseline` change).
- Usage stats reset wiring into `main.py` / `web_interface.py` startup: deferred to the
  migration change, because no runtime path calls the router yet.
