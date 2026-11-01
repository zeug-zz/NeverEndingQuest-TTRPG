# LLM Router Facade (Router Phase 0 + Phase 1)

## Why

Production chat traffic is spread across roughly 107 call sites in 57 files. Model
selection lives in scattered constants, the factory's Kimi-era `thinking` shapes are
inconsistent (`extra_body` regression documented in the router plan), no cache-aware
usage accounting exists, and there is no repeatable way to score candidate models before
trusting them. The fork runs direct OpenAI (`LLM_PROVIDER = "openai"`); the owner has
approved `gpt-6-luna` as the preferred OpenAI model and `openrouter/auto` as the
configurable narrator, combat, and Titan target.

This change lands the router plan's Phase 0 (config and factory prep) and Phase 1 (thin
facade plus bake-off harness) as one reviewable, non-live slice. Consumer migration stays
in later changes (router Phase 2).

Owner decisions recorded 2026-10-13: `gpt-5.4-nano` is deprecated and MUST NOT be
introduced; the live bake-off is accepted as successfully completed by owner
attestation. No benchmark measurements or provider execution are claimed by this
planning update. Implementation verification remains required.

## What Changes

MUST:

- Add tiered `MODEL_PROFILES`, `DEFAULT_PROFILE`, and `ACTIVE_PROFILE` to
  `model_config.py`, with `production-auto`, `titan-auto`, and `openai/fallback`.
  Both Auto profile tiers select `openrouter/auto`; both fallback tiers select
  configurable `OPENAI_FALLBACK_MODEL = "gpt-6-luna"`. `TASK_OVERRIDES` keeps
  narrator, combat, and Titan independently configurable without call-site edits.
- Refresh active direct-OpenAI chat model assignments in `model_config.py` to
  `gpt-6-luna` as the explicitly approved model change. Preserve task policy,
  prompt bytes, and legacy helper contracts apart from that model refresh and
  the client timeout bound.
- Rename `THINKING_ENABLED_TASKS` to `COMPLEX_TASKS` (same task list) and retain
  `THINKING_ENABLED_TASKS` as a backward-compatible alias during the transition.
- Mark `OPENROUTER_STRATEGY`, `OPENROUTER_FULL_MODEL`, `OPENROUTER_MINI_MODEL`, and
  `OPENROUTER_CHAT_MODEL`-as-model-ID as deprecated, without removing them.
- Normalize `extra_body` to the nested SDK-compatible shape in every `get_model_config()`
  path so no code path can emit a top-level `thinking` keyword.
- Add task-aware `finalize_chat_params(model, params=None, temperature=None,
  is_openrouter=False, retry_tier=None, *, task_id)` as the single assembler for
  chat kwargs: portable profile params, direct-OpenAI reasoning-family policy
  for GPT-5 compatibility and `gpt-6-luna`, and retry reasoning escalation.
- Resolve unknown OpenRouter profiles to the concrete Auto default, never to a
  profile label as a model ID; direct OpenAI always uses its fallback profile.
- Add `API_TIMEOUT_SECONDS` / `API_CONNECT_TIMEOUT_SECONDS` and apply
  `httpx.Timeout(...)` to both chat client constructors, giving every future call site one
  client-level timeout bound.
- Add `utils/llm_router.py` exposing `llm.call()` (profile-tier routing, error
  classification, bounded JSON retry, cache-aware thread-safe usage stats) and a
  fail-closed `llm.decide()` stub.
- Add a provider-free test suite `scripts/test_llm_router.py` and a bake-off harness
  `scripts/benchmark_model_profiles.py` whose default path makes zero provider calls.
- Track the actual response model and provider-reported cost for Auto calls;
  missing pricing is explicitly unpriced rather than fabricated from Auto rates.

MUST NOT:

- Migrate, import, or edit any production call site to use `llm.call()`.
- Implement the Jev decisions primitive or wire `llm.decide()` to any provider.
- Activate OpenRouter; `LLM_PROVIDER` stays `"openai"` in this change.
- Touch image or speech generation surfaces.
- Change gameplay mechanics, state persistence, or any prompt bytes.

SHOULD:

- Keep new code in the router, factory, and config seams named above; avoid host-file
  edits outside `model_config.py` and `utils/ai_client_factory.py`.

## Non-Goals

- MUST NOT migrate any call site to `llm.call()` (router Phase 2). In particular,
  `core/managers/combat_manager.py` is untouched; its Tier 1 migration follows
  `combat-manager-decomposition` (combat plan section 3.1, router decision R1).
- MUST NOT implement Jev (`utils/jev_client.py`, decision tasks, telemetry). The Phase 0
  decomposition gate did not pass, so `llm.decide()` remains an unavailable stub.
- MUST NOT change image, speech, or video surfaces (router Phase 4).
- MUST NOT flip `LLM_PROVIDER` to `"openrouter"`; activation is the later
  `llm-router-openrouter-activation` change.
- MUST NOT add third-party dependencies; timeout work uses `httpx`, already supplied by
  the `openai` SDK.
- MUST NOT remove deprecated constants or helpers in this change; cleanup is a later
  router phase.

## Capabilities

### New Capabilities

- `llm-router-facade-api`: Defines the facade consumer contract (`call()`, gated
  `decide()`), provider error classification and fallback outcomes, cache-aware
  thread-safe actual-model/cost statistics, and the provider-free harness. Justification: gate
  G2 and every later migrated call site depend on this single behavioral contract.
- `llm-model-profile-routing`: Defines the Auto profile data model, safe unknown-profile
  degradation, global and per-task selection, model-agnostic complexity classification, and
  per-tier provider preferences. Justification: model swaps must be config-only, which is
  only true if the profile schema and resolution rules are normative.
- `llm-factory-param-finalization`: Defines factory-side param finalization (normalized
  `extra_body`, task-aware reasoning-family policy, `retry_tier` escalation parity) and client-level
  timeout ownership. Justification: the facade delegates provider quirks to the factory, so
  the factory boundary needs its own requirements to stay testable and behavior-neutral.

Capability budget: exactly three, one spec file each. Provider preferences and usage
telemetry are folded into the profile-routing and facade-api capabilities; no fourth
capability is justified because the objective defines no additional contract surface
(`openspec/config.yaml` capability budget).

### Modified Capabilities

- None.

## Impact

- Affected code: `model_config.py`, `utils/ai_client_factory.py`, `utils/llm_router.py`
  (new), `scripts/test_llm_router.py` (new), `scripts/benchmark_model_profiles.py` (new).
- Compatibility impact (1-PC party and multi-PC party, ADR-0032): no runtime consumer is
  edited or migrated; both party shapes retain the direct-OpenAI transport with
  the approved `gpt-6-luna` model refresh. The
  regression floor for this change is the provider-free suite plus the existing
  factory-contract suites; gameplay smoke is unchanged because no runtime path changes.
- Provider outage/quota behavior: quota or billing errors hard-stop with `GameLLMError`
  and a recovery message; transient failures (timeout, connection, 429, 502, 503, 504,
  overload) retry once against the `openai/fallback` profile using a direct OpenAI client;
  a failed fallback re-raises. Recovery path is config-only: the runtime stays on
  `LLM_PROVIDER = "openai"`, and nothing imports the router until later changes do.
- Rollback: config-only. Revert `ACTIVE_PROFILE`/profiles to the previous constants,
  leave `LLM_PROVIDER = "openai"`, and stop importing `utils/llm_router.py`; no runtime
  code path depends on the facade in this change.
- G2 has two parts: live candidate acceptance is owner-attested PASS (2026-10-13);
  factory/router contract, approved-model, and provider-free harness checks are
  still pending. Do not rerun the accepted bake-off as a prerequisite. Activation
  still requires live 1-PC and multi-PC smoke, actual-model cost measurement,
  and rollback verification in `llm-router-openrouter-activation`.
