# LLM Router Facade - Tasks

Scope boundary (binding, not checklist items):

- No production call site is migrated or edited to `llm.call()`; router Phase 2 owns that.
- `core/managers/combat_manager.py` is NOT touched. Combat Tier 1 migration follows
  `combat-manager-decomposition` (combat plan section 3.1, router decision R1); this
  change only defines the client-level timeout bound and `retry_tier` channel it consumes.
- `LLM_PROVIDER` stays `"openai"`; OpenRouter activation is a later change.
- `llm.decide()` stays a fail-closed stub; Jev is not implemented here.
- ASCII-only output; no new third-party dependencies (`httpx` ships with the `openai` SDK).

## 1. Config Prep (`model_config.py`)

- [ ] 1.1 Add the five confirmed v4 profiles (`production-2026-09`, `validation-split`, `economy`, `background-titan`, `openai/fallback`), `DEFAULT_PROFILE` (with `None` tier models), and `ACTIVE_PROFILE` to `model_config.py`, keeping the plan's tier shape (`model`, `params`, `provider`, `price_per_1k`) plus `supports_json_mode` / `max_context`. (trace: llm-model-profile-routing)
  - Verify: `.venv/bin/python -m py_compile model_config.py` and `.venv/bin/python -c "import model_config as m; ks=set(m.MODEL_PROFILES); assert {'production-2026-09','validation-split','economy','background-titan','openai/fallback'} <= ks; assert all('complex' in p and 'simple' in p for p in m.MODEL_PROFILES.values()); assert m.DEFAULT_PROFILE['complex']['model'] is None; print('profiles ok')"`
- [ ] 1.2 Rename `THINKING_ENABLED_TASKS` to `COMPLEX_TASKS`, retain `THINKING_ENABLED_TASKS = COMPLEX_TASKS` as a backward-compatible alias, and add deprecation comments to `OPENROUTER_STRATEGY`, `OPENROUTER_FULL_MODEL`, `OPENROUTER_MINI_MODEL`, and `OPENROUTER_CHAT_MODEL` naming their replacements. (trace: llm-model-profile-routing)
  - Verify: `.venv/bin/python -m py_compile model_config.py` and `.venv/bin/python -c "import model_config as m; assert m.COMPLEX_TASKS == m.THINKING_ENABLED_TASKS; assert 'dm_main' in m.COMPLEX_TASKS; print('alias ok')"`
- [ ] 1.3 Add `API_TIMEOUT_SECONDS = 120` and `API_CONNECT_TIMEOUT_SECONDS = 10` to `model_config.py` with ownership comments. (trace: llm-factory-param-finalization)
  - Verify: `.venv/bin/python -m py_compile model_config.py` and `.venv/bin/python -c "import model_config as m; assert m.API_TIMEOUT_SECONDS == 120; assert m.API_CONNECT_TIMEOUT_SECONDS == 10; print('timeouts ok')"`

## 2. Provider-Free Test Foundation (`scripts/test_llm_router.py`)

- [ ] 2.1 Create `scripts/test_llm_router.py` as a stdlib `unittest` suite with a provider tripwire that fails any test which constructs a provider client or performs network I/O. (trace: llm-router-facade-api)
  - Verify: `.venv/bin/python scripts/test_llm_router.py`
- [ ] 2.2 Add config-level tests: known-profile tier resolution (`production-2026-09` complex/simple models and provider sort), `DEFAULT_PROFILE` fallback for an unknown profile key, `background-titan` price sort plus `max_price` ceiling, and the `COMPLEX_TASKS` alias. (trace: llm-model-profile-routing)
  - Verify: `.venv/bin/python scripts/test_llm_router.py`

## 3. Factory Prep (`utils/ai_client_factory.py`)

- [ ] 3.1 Normalize `extra_body` to the nested SDK-compatible shape `{"extra_body": {...}}` on every `get_model_config()` path (TASK_OVERRIDES, strategy tiers, direct OpenAI) so `params.update(extra_body)` can never emit a top-level `thinking` kwarg; add tests for strategy-path nesting, override-path consistency, and empty direct-OpenAI output. (trace: llm-factory-param-finalization)
  - Verify: `.venv/bin/python scripts/test_llm_router.py`
- [ ] 3.2 Add `finalize_chat_params(model, params=None, temperature=None, is_openrouter=False, retry_tier=None)` to `utils/ai_client_factory.py`: OpenRouter keeps profile params plus temperature, direct-OpenAI GPT-5 omits temperature and applies the GPT-5 reasoning profile, other OpenAI models keep platform temperature, and `retry_tier` is consumed (never forwarded). Add tests proving GPT-5 temperature omission, OpenRouter temperature retention, high-retry reasoning parity with `get_chat_completion_params(..., retry_tier="high")`, and absence of `retry_tier` in output kwargs. (trace: llm-factory-param-finalization)
  - Verify: `.venv/bin/python scripts/test_llm_router.py`
- [ ] 3.3 Apply `httpx.Timeout(API_TIMEOUT_SECONDS, connect=API_CONNECT_TIMEOUT_SECONDS)` to both chat client constructors in `create_chat_client()`, preserving the OpenRouter base URL and default headers; add tests asserting both constructed clients carry the configured total and connect timeout values. (trace: llm-factory-param-finalization)
  - Verify: `.venv/bin/python scripts/test_llm_router.py`
- [ ] 3.4 Confirm existing factory consumers still compile and the legacy params shim output is unchanged for the direct-OpenAI posture. (trace: llm-factory-param-finalization)
  - Verify: `for f in $(grep -rl "ai_client_factory" --include="*.py" core web utils main.py); do .venv/bin/python -m py_compile "$f" || exit 1; done; echo consumers-compile-ok` and `.venv/bin/python -m unittest -q scripts.test_gpt54_chat_params_contract scripts.test_gpt54_mini_chat_params_shim`

## 4. Router Facade (`utils/llm_router.py`)

- [ ] 4.1 Create `utils/llm_router.py` with `GameLLMError`, `LLMJSONError`, the module-level `llm` singleton, and `_resolve()` / `_resolve_fallback()` implementing the profile resolution flow (complex/simple tier, `TASK_OVERRIDES`, unknown-profile fallback, `openai/fallback` selection on direct OpenAI, provider block only on OpenRouter). (trace: llm-router-facade-api, llm-model-profile-routing)
  - Verify: `.venv/bin/python -m py_compile utils/llm_router.py` and `.venv/bin/python scripts/test_llm_router.py`
- [ ] 4.2 Implement `llm.call(task, messages, json_output=False, temperature=None, max_tokens=None, retry_tier=None, **kwargs)` with error classification (quota/billing hard stop), one bounded fallback to the `openai/fallback` profile through a direct OpenAI client, JSON retry up to three fresh attempts, and fallback notification through the existing factory path; add fake-transport tests for quota, transient fallback, fallback exhaustion, and JSON retry exhaustion. (trace: llm-router-facade-api)
  - Verify: `.venv/bin/python scripts/test_llm_router.py`
- [ ] 4.3 Implement cache-aware thread-safe usage stats (`_usage_lock`, token/cost counters, `by_model` / `by_task` maps, `llm.get_usage_stats()` copy, `llm.reset_usage_stats()`) with tests for cache-read cost separation, missing-usage responses, concurrent updates, and snapshot isolation. (trace: llm-router-facade-api)
  - Verify: `.venv/bin/python scripts/test_llm_router.py`
- [ ] 4.4 Implement the gated `llm.decide()` stub: no client creation, no provider call, raises `GameLLMError` documenting the decisions status `unavailable` and the pending decomposition gate; add a source-contract test asserting no production module imports or calls `llm.decide()`. (trace: llm-router-facade-api)
  - Verify: `.venv/bin/python scripts/test_llm_router.py`
- [ ] 4.5 Confirm router parity for the direct-OpenAI posture: `llm.call()` resolves the `openai/fallback` profile, attaches no `provider` field, and returns text or parsed JSON as contracted, using the fake transport only. (trace: llm-router-facade-api)
  - Verify: `.venv/bin/python scripts/test_llm_router.py`

## 5. Bake-Off Harness (`scripts/benchmark_model_profiles.py`)

- [ ] 5.1 Create `scripts/benchmark_model_profiles.py` with bundled fixtures (narrator turn, combat batch validation, encounter JSON update, summary compression) and a fake transport so the default run makes zero provider calls; report JSON-validity rate, latency p50/p90, throughput, token usage, cache-read rate, and cost per call per candidate. (trace: llm-router-facade-api)
  - Verify: `.venv/bin/python scripts/benchmark_model_profiles.py --profile production-2026-09` (must exit 0 without provider configuration)
- [ ] 5.2 Add the explicit `--live` opt-in that requires OpenRouter configuration, fails with a clear message when it is absent, and is never run by default or in CI; emit the gate verdict against the configured `gpt-5.6-luna` baseline (candidate must match or beat baseline JSON validity at lower cost). (trace: llm-router-facade-api)
  - Verify: `.venv/bin/python scripts/benchmark_model_profiles.py --profile production-2026-09 --help` shows `--live`, default run remains provider-free, and `.venv/bin/python scripts/test_llm_router.py` passes (no live path in CI).

## 6. Verification And Handoff

- [ ] 6.1 Run the full provider-free router suite and the factory contract suites as the behavior-neutral evidence set for the OpenAI posture and record the outputs. (trace: llm-router-facade-api)
  - Verify: `.venv/bin/python scripts/test_llm_router.py` and `.venv/bin/python -m unittest -q scripts.test_gpt54_chat_params_contract scripts.test_gpt54_mini_chat_params_shim`
- [ ] 6.2 Run ASCII compliance and syntax checks over the new and changed Python files. (trace: llm-router-facade-api)
  - Verify: `.venv/bin/python scripts/check_ascii_compliance.py --summary-only` (0 violations for the files authored here)
- [ ] 6.3 Confirm the scope boundary held: no migrated call sites and no combat edits. (trace: llm-router-facade-api)
  - Verify: `grep -c "llm.call(" core/managers/combat_manager.py main.py core/ai/action_handler.py` returns 0 for each file, and `git diff --stat -- core/managers/combat_manager.py` contains no changes authored by this change.
- [ ] 6.4 Run one manual `--live` bake-off for `production-2026-09` with a locally configured OpenRouter key (owner-run, never in CI) and record the gate verdict plus token/cost output as G2 evidence. (trace: llm-router-facade-api)
  - Verify: `.venv/bin/python scripts/benchmark_model_profiles.py --profile production-2026-09 --live` output recorded in the change task log; skip is acceptable only when OpenRouter configuration is unavailable, and the skip must be reported.
- [ ] 6.5 Validate the change scaffold and confirm the interleave handoff note (combat Tier 1 follows `combat-manager-decomposition`). (trace: llm-router-facade-api)
  - Verify: `openspec validate llm-router-facade --strict`
