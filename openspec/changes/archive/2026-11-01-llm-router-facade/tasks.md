# LLM Router Facade - Tasks

Scope boundary (binding, not checklist items):

- No production call site is migrated or edited to `llm.call()`; router Phase 2 owns that.
- `core/managers/combat_manager.py` is NOT touched. Combat Tier 1 migration follows
  `combat-manager-decomposition` (combat plan section 3.1, router decision R1); this
  change only defines the client-level timeout bound and `retry_tier` channel it consumes.
- `LLM_PROVIDER` stays `"openai"`; OpenRouter activation is a later change.
- Active direct-OpenAI chat assignments are intentionally refreshed to `gpt-6-luna`;
  no other model substitution or prompt change is authorized here.
- `llm.decide()` stays a fail-closed stub; Jev is not implemented here.
- ASCII-only output; no new third-party dependencies (`httpx` ships with the `openai` SDK).

## 1. Config Prep (`model_config.py`)

- [x] 1.1 Add `production-auto`, `titan-auto`, and `openai/fallback` profiles; both Auto tiers use `openrouter/auto` with empty default params/provider/pricing, `DEFAULT_PROFILE` is concrete Auto, `ACTIVE_PROFILE` selects `production-auto`, and `titan_cycle` selects `titan-auto`. Add configurable `OPENAI_FALLBACK_MODEL = "gpt-6-luna"` for both fallback tiers and refresh active direct-OpenAI chat assignments to it without introducing `gpt-5.4-nano`. (trace: llm-model-profile-routing, llm-factory-param-finalization)
  - Verify: `.venv/bin/python -m py_compile model_config.py` and `.venv/bin/python -c "import model_config as m; assert {'production-auto','titan-auto','openai/fallback'} <= set(m.MODEL_PROFILES); assert m.OPENAI_FALLBACK_MODEL == 'gpt-6-luna'; assert m.DEFAULT_PROFILE['complex']['model'] == 'openrouter/auto'; assert all(m.MODEL_PROFILES[p][t]['model'] == 'openrouter/auto' for p in ('production-auto','titan-auto') for t in ('complex','simple')); print('profiles ok')"`; inspect the active chat assignments for approved-model consistency.
  - Verified by parent: profiles/assertions, AST single-fallback references, compile, and diff-check all PASS; no 1.2+ tasks are marked complete.
- [x] 1.2 Rename `THINKING_ENABLED_TASKS` to `COMPLEX_TASKS`, retain `THINKING_ENABLED_TASKS = COMPLEX_TASKS` as a backward-compatible alias, and add deprecation comments to `OPENROUTER_STRATEGY`, `OPENROUTER_FULL_MODEL`, `OPENROUTER_MINI_MODEL`, and `OPENROUTER_CHAT_MODEL` naming their replacements. (trace: llm-model-profile-routing)
  - Verified by parent: alias identity/membership, compile, and diff checks all PASS; no later task is marked complete.
- [x] 1.3 Add `API_TIMEOUT_SECONDS = 120` and `API_CONNECT_TIMEOUT_SECONDS = 10` to `model_config.py` with ownership comments. (trace: llm-factory-param-finalization)
  - Verify: `.venv/bin/python -m py_compile model_config.py` and `.venv/bin/python -c "import model_config as m; assert m.API_TIMEOUT_SECONDS == 120; assert m.API_CONNECT_TIMEOUT_SECONDS == 10; print('timeouts ok')"`
  - Verified by parent: timeout values 120/10, compile/diff, and direct-OpenAI provider posture all PASS.

## 2. Provider-Free Test Foundation (`scripts/test_llm_router.py`)

- [x] 2.1 Create `scripts/test_llm_router.py` as a stdlib `unittest` suite with a provider tripwire that fails any test which constructs a provider client or performs network I/O. (trace: llm-router-facade-api)
  - Verify: `.venv/bin/python scripts/test_llm_router.py`
  - Verified by parent: five provider-tripwire tests pass; compile and scoped diff checks pass. Config contract tests are present but task 2.2 remains unchecked pending router resolution.
- [x] 2.2 Add config-level tests for independent narrator/combat/Titan overrides, concrete Auto defaults for unknown/missing profiles, `gpt-6-luna` on both fallback tiers, isolation of vendor overrides from direct OpenAI, optional `auto-router` plugin settings, and the `COMPLEX_TASKS` alias. (trace: llm-model-profile-routing)
   - Verify: `.venv/bin/python scripts/test_llm_router.py`
   - Verified by parent: 11 config-level tests/diff checks pass; runtime resolution scenarios are owned by task 4.1 and are not claimed by config checks.
## 3. Factory Prep (`utils/ai_client_factory.py`)

- [x] 3.1 Normalize `extra_body` to the nested SDK-compatible shape `{"extra_body": {...}}` on every `get_model_config()` path (TASK_OVERRIDES, strategy tiers, direct OpenAI) so `params.update(extra_body)` can never emit a top-level `thinking` kwarg; add tests for strategy-path nesting, override-path consistency, and empty direct-OpenAI output. (trace: llm-factory-param-finalization)
  - Verify: `.venv/bin/python scripts/test_llm_router.py`
  - Verified by parent: primary 3.1 path PASS (14 tests); reviewed the one-line strategy nesting fix, compile, and diff checks.
- [x] 3.2 Add `finalize_chat_params(model, params=None, temperature=None, is_openrouter=False, retry_tier=None, *, task_id)`: preserve legacy GPT-5 support, explicitly support `gpt-6-luna` with existing task-family reasoning/verbosity and sampling omission, consume task/retry context, and merge portable Auto params/provider/plugins under SDK-compatible `extra_body`. Add tests for narrator/validation/compression/summary policy, high-retry parity, OpenRouter parameter isolation, and absence of `task_id`/`retry_tier` in outgoing kwargs. (trace: llm-factory-param-finalization)
  - Verify: `.venv/bin/python scripts/test_llm_router.py`
  - Verified by parent: correction PASS; 22 router tests + 16 legacy tests, including finalizer SDK signature, extension/context stripping, captured summary policies, compile, and diff checks.
- [x] 3.3 Apply `httpx.Timeout(API_TIMEOUT_SECONDS, connect=API_CONNECT_TIMEOUT_SECONDS)` to both chat client constructors in `create_chat_client()`, preserving the OpenRouter base URL and default headers; add tests asserting both constructed clients carry the configured total and connect timeout values. (trace: llm-factory-param-finalization)
  - Verify: `.venv/bin/python scripts/test_llm_router.py`
  - Verified by parent: 24 router tests pass; both constructors use total timeout 120/connect timeout 10, and OpenRouter URL/default headers are preserved. No production consumer changes were introduced by this task.
- [x] 3.4 Confirm existing factory consumers still compile and same-task/same-legacy-model shim output is preserved, with the explicit `gpt-6-luna` config refresh and client timeout exceptions documented. Update active-model fixtures where necessary without weakening legacy policy assertions. (trace: llm-factory-param-finalization)
   - Verify: compile the production factory-consumer inventory with `.venv/bin/python`; run `.venv/bin/python -m unittest -q scripts.test_gpt54_chat_params_contract scripts.test_gpt54_mini_chat_params_shim scripts.test_gpt56_luna_direct_openai_contract` after updating active-model fixtures while retaining legacy-family coverage.
   - Verified by parent: primary 3.4 PASS (37 factory-consumer compile checks, 57 contract tests); retained legacy display assertions and approved `gpt-6-luna`/timeout exceptions without weakening policy coverage.

## 4. Router Facade (`utils/llm_router.py`)

- [x] 4.1 Create `utils/llm_router.py` with exceptions, the `llm` singleton, and profile resolution: explicit OpenRouter task model/profile overrides, concrete Auto default, fallback always `OPENAI_FALLBACK_MODEL`, and no vendor override/provider/plugin leakage into direct OpenAI. Never send profile labels as model IDs. (trace: llm-router-facade-api, llm-model-profile-routing)
  - Verify: `.venv/bin/python -m py_compile utils/llm_router.py` and `.venv/bin/python scripts/test_llm_router.py`
   - Verified by parent: primary router suite PASS (36 tests; 93 including factory contracts), including detached default mappings, profile-label model safety, direct-OpenAI fallback isolation, and fallback-rate contract coverage. Task 4.3 remains unchecked.
- [x] 4.2 Implement `llm.call(task, messages, json_output=False, temperature=None, max_tokens=None, retry_tier=None, **kwargs)` with error classification (quota/billing hard stop), one bounded fallback to the `openai/fallback` profile through a direct OpenAI client, JSON retry up to three fresh attempts, and fallback notification through the existing factory path; add fake-transport tests for quota, transient fallback, fallback exhaustion, and JSON retry exhaustion. (trace: llm-router-facade-api)
   - Verify: `.venv/bin/python scripts/test_llm_router.py`
   - Verified by parent: primary 4.2 PASS (49 router tests); factory contract suite PASS (57 tests) after SDK-shape/provider-propagation review, one fallback/shared JSON retry budget of at most four transports, and single/reset fallback notification plus quota task/model coverage.
- [x] 4.3 Implement locked usage stats and isolated snapshots/resets: aggregate actual response models, prefer provider `usage.cost` once, retain cache-aware labelled estimates only when rates exist, expose `unpriced_calls`/`cost_complete` when cost is unavailable, and distinguish requested Auto from resolved model. Test actual zero cost, absent/invalid cost, unknown model, no double counting, missing usage, concurrent updates, and snapshot isolation. (trace: llm-router-facade-api)
   - Verify: `.venv/bin/python scripts/test_llm_router.py`
   - Verified by parent: usage accounting PASS (60 router tests); factory contracts PASS (57 tests); accounting error/fallback requested/resolved correctness reviewed. No later task is marked complete.
- [x] 4.4 Implement the gated `llm.decide()` stub: no client creation, no provider call, raises `GameLLMError` documenting the decisions status `unavailable` and the pending decomposition gate; add a source-contract test asserting no production module imports or calls `llm.decide()`. (trace: llm-router-facade-api)
   - Verify: `.venv/bin/python scripts/test_llm_router.py`
-   - Verified by parent: PASS (62 router tests); provider tripwire and usage snapshot remain untouched, and AST source scan finds no production router imports or `llm.decide()` calls. Task 4.5 remains unchecked.
- [x] 4.5 Confirm approved direct-OpenAI behavior: both task tiers resolve `gpt-6-luna`, task policy is preserved, no OpenRouter extensions are attached, and text/dictionary return contracts hold, using fake transport only. (trace: llm-router-facade-api)
   - Verify: `.venv/bin/python scripts/test_llm_router.py`
   - Verified by parent: direct-OpenAI fake-transport policy, text/dictionary contracts, immutable input, and retry-tier policy pass; task 5.1 remains unchecked.

## 5. Bake-Off Harness (`scripts/benchmark_model_profiles.py`)

- [x] 5.1 Create `scripts/benchmark_model_profiles.py` with bundled fixtures (narrator turn, combat batch validation, encounter JSON update, summary compression) and a fake transport so the default run makes zero provider calls; report JSON-validity rate, latency p50/p90, throughput, token usage, cache-read rate, and cost per call per candidate. (trace: llm-router-facade-api)
   - Verify: `.venv/bin/python scripts/benchmark_model_profiles.py --profile production-auto` (must exit 0 without provider configuration and label fake-transport metrics synthetic)
-   - Verified by parent: 68/68 provider-free router tests, cold provider tripwire, 12 synthetic fixture calls, and config/stats restoration on success and error all PASS. Default benchmark remains provider-free and synthetic.
- [x] 5.2 Add explicit `--live` opt-in for optional future comparisons, fail clearly when configuration is absent, use configurable `gpt-6-luna` as the OpenAI reference, and report actual Auto models/cost completeness. The owner-accepted bake-off is not a mandatory rerun. (trace: llm-router-facade-api)
  - Verify: `.venv/bin/python scripts/benchmark_model_profiles.py --profile production-auto --help` shows `--live`, default run remains provider-free, and `.venv/bin/python scripts/test_llm_router.py` passes (no live path in CI).
  - Verified by parent: suite 74 PASS (68 router tests + 6 live-orchestration provider-free tests); default synthetic JSON benchmark produced 3 candidates with 4 fixtures each and no network calls; `--help` exposes `--live`.

## 6. Verification And Handoff

- [x] 6.1 Run the full provider-free router suite and factory contract suites as evidence for the approved OpenAI model refresh, legacy policy compatibility, Auto routing, and cost accounting; record outputs. (trace: llm-router-facade-api)
  - Verify: `.venv/bin/python scripts/test_llm_router.py` and `.venv/bin/python -m unittest -q scripts.test_gpt54_chat_params_contract scripts.test_gpt54_mini_chat_params_shim`
  - Verified by parent: combined 5-suite run PASS, 131 tests total.
- [x] 6.2 Run ASCII compliance and syntax checks over the new and changed Python files. (trace: llm-router-facade-api)
  - Verify: `.venv/bin/python scripts/check_ascii_compliance.py --summary-only` (0 violations for the files authored here)
  - Verified by parent: compile checks passed for 8 changed/new Python files; repository ASCII scan covered 726 files with 0 violations.
- [x] 6.3 Confirm the scope boundary held: no migrated call sites and no combat edits. (trace: llm-router-facade-api)
  - Verify: `grep -c "llm.call(" core/managers/combat_manager.py main.py core/ai/action_handler.py` returns 0 for each file, and `git diff --stat -- core/managers/combat_manager.py` contains no changes authored by this change.
  - Verified by parent: `llm.call` counts are 0 in `combat_manager.py`, `main.py`, and `action_handler.py`; no authored combat, main, or action-handler diff exists.
- [x] 6.4 Record successful live candidate acceptance by owner attestation, without rerunning it or inventing token/cost/latency output. (trace: llm-router-facade-api)
  - Verified 2026-10-13: owner instruction, "Consider live bake-off completed successfully." This satisfies the live candidate-acceptance portion only; tasks 6.1-6.3/6.5 and activation smoke remain pending. No benchmark report or numerical measurements were supplied.
- [x] 6.5 Validate the change scaffold and confirm the interleave handoff note (combat Tier 1 follows `combat-manager-decomposition`). (trace: llm-router-facade-api)
  - Verify: `openspec validate llm-router-facade --strict`
  - Verified by parent: `openspec validate llm-router-facade --strict` exited 0; handoff explicitly keeps decomposition next before core migration.
