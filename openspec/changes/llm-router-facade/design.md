# LLM Router Facade - Design

## Context

The router plan (`plans/version-2/openrouter_llm_router_architecture.md`, v5) defines a
thin facade over the existing `utils/ai_client_factory.py` infrastructure. This change
implements Phase 0 (config and factory prep) and Phase 1 (facade, unit tests, bake-off
harness) only. No call site is migrated, and `LLM_PROVIDER` stays `"openai"`.

Owner revision (2026-10-13): prefer `gpt-6-luna` for direct OpenAI, configure
`openrouter/auto` for narrator/combat/Titan, and accept the successful live bake-off
by owner attestation. The model refresh is intentional; the old blanket claim of
unchanged model selection is superseded. No live report or numerical result was
supplied with the attestation, so none is manufactured here.

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
  finalize_chat_params         explicit task_id + reasoning policy + retry_tier
  get_chat_completion_params   legacy shim, unchanged for existing consumers
  handle_provider_error        retryable classification + fallback notification state
        |
        v
model_config.py          CONFIGURATION DATA
  MODEL_PROFILES               production-auto, titan-auto, openai/fallback
  OPENAI_FALLBACK_MODEL        gpt-6-luna (configurable)
  COMPLEX_TASKS                model-agnostic complexity classification
  TASK_OVERRIDES               per-task profile or explicit model
  API_TIMEOUT_SECONDS          client-level timeout constants
```

Ownership rules:

- The router MUST NOT build provider clients or invent sampling rules; it resolves
  configuration and delegates kwargs assembly to the factory.
- The factory MUST own provider quirks (reasoning-family sampling omission, task profiles,
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

## Direct OpenAI Compatibility And Model Refresh (MUST)

With `LLM_PROVIDER = "openai"`:

- Resolution selects `openai/fallback` regardless of `ACTIVE_PROFILE` or OpenRouter
  task overrides. Both tiers use `OPENAI_FALLBACK_MODEL = "gpt-6-luna"`.
- Refresh active direct-OpenAI chat assignments in `model_config.py` to that model;
  do not introduce deprecated `gpt-5.4-nano`. Image/audio assignments are separate.
- Preserve current task-specific reasoning/verbosity policy and legacy GPT-5 support.
  Extend reasoning-family detection explicitly to `gpt-6-luna`; do not assume the
  old `gpt-5` prefix detector covers the preferred model.
- No OpenRouter provider, plugins, reasoning extensions, or vendor model slug may
  be sent to a direct-OpenAI client.
- Existing factory helpers retain signatures and same-task/same-model legacy
  output contracts; the approved model refresh and timeout bound are explicit exceptions.
- No production module imports `utils/llm_router.py`; the facade is only exercised by its
  provider-free tests until later migration changes.

The regression floor is the provider-free router suite plus the existing factory contract
suites (`scripts/test_gpt54_chat_params_contract.py`,
`scripts/test_gpt54_mini_chat_params_shim.py`). Gameplay smoke is deferred to the first
migration change because no consumer routing changes here. The intentional model
config refresh is verified by focused model/policy fixtures, not described as an
unchanged runtime model.

The facade model refresh changes the provider/model identity of future captures.
Keep archived G1 evidence labelled with its original `gpt-5.6-luna` model; G5 must
capture a current `gpt-6-luna` pre-optimization reference under the same fixtures
before making like-for-like latency claims. This is part of the existing hot-path
change, not another change or another candidate bake-off.

## Profile Resolution Flow

1. Read `COMPLEX_TASKS`, `ACTIVE_PROFILE`, `TASK_OVERRIDES`, `TASK_TEMPERATURES`, and
   `MODEL_PROFILES` / `DEFAULT_PROFILE` from `model_config`.
2. Determine the actual provider via the factory's `_get_actual_provider()`.
   - OpenRouter: profile key = `TASK_OVERRIDES[task]["profile"]` if present, else
     `ACTIVE_PROFILE`.
    - Direct OpenAI: profile key = `"openai/fallback"`; OpenRouter overrides do not apply.
3. Look up the profile; an unknown OpenRouter key resolves to concrete
   `DEFAULT_PROFILE`, equivalent to `production-auto`.
4. Select the `complex` tier when the task is in `COMPLEX_TASKS`, otherwise `simple`.
5. On OpenRouter, explicit `TASK_OVERRIDES[task]["model"]` wins; else tier model;
   else `openrouter/auto`. On direct OpenAI, always use `OPENAI_FALLBACK_MODEL`.
   Never send a profile label as a model ID. Explicit model overrides do not
   inherit another model's tier params or price estimate.
6. Attach the tier `provider` block only on OpenRouter calls; attach tier pricing for usage
   accounting.
7. Fallback resolution (`_resolve_fallback`) always uses the `openai/fallback` profile and
    is used with a direct OpenAI client.

### Auto Profiles (MUST)

- `production-auto` and `titan-auto` use `openrouter/auto` for both tiers, with
  empty params, provider preferences, and static pricing by default.
- `ACTIVE_PROFILE = "production-auto"`; `TASK_OVERRIDES["titan_cycle"]` selects
  `titan-auto`. `dm_main` and `combat_main` remain independently overrideable.
- Tier shape: `model`, `params`, `provider`, `price_per_1k`. Optional context/JSON
  capability hints must not claim one fixed context size for all Auto outputs.
- Optional documented Auto settings use
  `params={"plugins": [{"id": "auto-router", ...}]}` and are finalized under
  `extra_body.plugins`. No default fixed allowlist or local catalog-refresh loop.
- Do not inject direct-OpenAI `reasoning_effort`/`verbosity` or legacy Kimi
  `thinking` into Auto. Only explicitly configured portable settings are sent.
- Auto selects a downstream model; it is not a contractual promise to select
  the cheapest possible model. Returned model/cost make that selection visible.
- Configuring Titan's task does not implement a new Titan runtime or scheduler.

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
`finalize_chat_params(..., task_id=task)`, which applies the direct-OpenAI reasoning profile for the task family and
raises reasoning effort to high. It is never placed in passthrough `**kwargs`; the OpenAI
SDK would reject the unknown field. Signature:
`finalize_chat_params(model, params=None, temperature=None, is_openrouter=False,
retry_tier=None, *, task_id)`.
`task_id` is required factory context and never a provider kwarg. Legacy GPT-5 kwargs from
`finalize_chat_params(..., retry_tier="high")` must reproduce the legacy
`get_chat_completion_params(<task>, ..., retry_tier="high")` reasoning kwargs for that task
family.

The same task-family policy applies to `gpt-6-luna`. OpenRouter Auto receives no
direct-OpenAI escalation fields; any optional reasoning setting must use the
documented portable OpenRouter extension. Finalization must merge extensions
under one `extra_body` without overwriting provider/plugin settings.

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
- Record requested model and actual `response.model` separately; aggregate
  `by_model` under the actual selected model, or an explicit unknown bucket.
- Prefer finite non-negative provider `usage.cost` in USD, including zero, and
  add it once. Do not calculate a second static estimate for the same response.
- Estimated cost math, only when actual cost is missing and verified rates exist:
  `fresh = prompt - cached`, then
  `fresh * prompt_rate + cached * cache_read_rate + completion * completion_rate`,
  normalized per 1K tokens using the resolved tier `price_per_1k`; when `cache_read` is
  absent, cached tokens cost at the prompt rate.
- Auto has no fixed per-token rate. With neither actual cost nor verified rates,
  increment `unpriced_calls`, set `cost_complete=False`, and expose the known-cost
  subtotal without calling the request free. Cost provenance is actual/estimated/unpriced.
- `get_usage_stats()` returns a lock-held copy (no internal references), rounds cost, and
  uses stable keys; `reset_usage_stats()` clears counters for session start.
- Router stats stay separate from `utils/llm_usage_tracker.py`, which continues to own
  image/audio and existing cost events. Later migration MUST avoid double-counting
  chat events; cleanup MUST reconcile session/week totals and `/usage` presentation.
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
- Default profile: `production-auto`; optional future live comparisons use
  configurable `gpt-6-luna` as the direct-OpenAI reference and record Auto's actual
  resolved models, reported cost, and cost completeness.
- Live candidate acceptance: owner-attested PASS on 2026-10-13 ("Consider live
  bake-off completed successfully"). No mandatory rerun, no invented measurements.
- G2 implementation acceptance remains pending until router/factory parity,
  approved model configuration, and provider-free harness checks pass. Fake
  transport metrics are labelled synthetic and never substitute for live evidence.
- Activation's live gameplay/transport smoke and rollback checks remain required;
  they verify integration, not repeat candidate selection.

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
4. Restore prior chat model assignments if rolling back the approved model refresh;
   restore the client constructor timeout only if rolling back that separate bound.
   Do not silently relabel old baseline captures as `gpt-6-luna` measurements.

## Open Questions

None outstanding. Resolved during authoring:

- Task context is explicit in the finalizer, unknown profiles have a concrete Auto
  default, and direct-OpenAI resolution is isolated from OpenRouter overrides.
- Preferred OpenAI model, Auto targets, and live candidate acceptance are settled
  by the owner revision on 2026-10-13.

- `decide()` failure shape: raise `GameLLMError` (the plan's reference stub) while
  documenting the decisions status as `unavailable`; Jev fallback semantics only matter
  once the primitive exists.
- Config metadata file: not required; validation passes with proposal, design, specs, and
  tasks only (matches the sibling `combat-latency-baseline` change).
- Usage stats reset wiring into `main.py` / `web_interface.py` startup: deferred to the
  migration change, because no runtime path calls the router yet.
