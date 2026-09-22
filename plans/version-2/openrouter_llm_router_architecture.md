# OpenRouter LLM Router Architecture Plan

## Executive Summary

**Objective:** Centralize ~170 LLM call sites across 68 files behind a single `llm.call()` interface, and add a second typed primitive (`llm.decide()`) for System One decisions. The router is a thin facade over the existing `ai_client_factory.py` infrastructure, adding profile-based model routing, provider preferences, cost tracking, and JSON retry logic.

**Status:** PLANNING PHASE - v4.0 model refresh complete; Phase 0/1 ready to implement once the workspace baseline is clean.

**Timeline:** 8-11 days total
- Phase 0: Config & Factory Prep (1 day) - `MODEL_PROFILES` v4, reasoning-effort params, `extra_body` normalization
- Phase 1: Router Facade + bake-off harness (2 days)
- Phase 2: Callsite Migration (4-6 days)
- Phase 3: Cleanup & Polish (1-2 days)

**Foundation:** `ai_client_factory.py` already provides provider selection, model routing, fallback logic, and the GPT-5-safe chat params shim (`get_chat_completion_params`, used by 39 files). This plan builds on that - it does not replace it.

**Five OpenRouter surfaces, not one:** OpenRouter is no longer a single chat surface. Model catalogs are separate: Text (446), Image (52), Speech (18), Video (29), Transcription (21), Embeddings (37), Rerank (7), Decisions (1), Audio (4). This plan covers chat (Phase 1-3), decisions (gated, see Jev sections), and image + speech (Phase 4). Video is available but deferred.

**Current Priority:** The codebase runs direct OpenAI (`LLM_PROVIDER = "openai"`). Router work begins only after the fork/workspace baseline is clean and the tracker build is stable. All OpenRouter behavior is opt-in; the OpenAI path must remain behavior-neutral for testers.

**Updated sequencing note (2026-03-16):** The post-gametest narrative-sovereignty continuation now has priority over router work. See `plans/version-2/narrative-sovereignty-post-gametest.md`. The recommended order is: stable OpenAI gametest baseline -> event-ledger/prompt-reset continuation -> OpenRouter router re-architecture.

**Jev decisions integration (2026-09-21):** The router gains a second primitive alongside generative chat: `llm.decide()` for System One typed decisions (`typesafe/jev-1.13` via the OpenRouter Decisions API). This is additive and runtime-neutral while the codebase remains on OpenAI (`LLM_PROVIDER = "openai"`). The Phase 0 eval spike ran 2026-09-21 and did **not** clear the promotion gate for the action predictor, so the primitive foundation stays deferred pending a question-decomposition pass. See "Decisions Primitive (System One / Jev)" and "Jev Decisions Integration (Workstreams A/B/C)".

**Combat refactor interleave (2026-09-21):** Owner-approved sequencing with `plans/version-2/combat-manager-refactor.md` (section 3.1 there): combat Phase 0 latency baseline -> this plan's Phase 0/1 -> combat Phase 1 decomposition (`core/combat/`) -> this plan's Phase 2 Tier 1 migration for the combat trio + `main.py` + `action_handler.py` -> combat Phase 2 latency hot path -> remaining router tiers. Consequences: `combat_manager.py` migrates as named stage calls instead of edits inside a 2,492-line function; combat's per-call timeouts are superseded by the Phase 0 client-level `httpx.Timeout`; and combat's validation-failure reasoning escalation must survive migration via an explicit `retry_tier` channel through `finalize_chat_params()`. Execution mapping onto OpenSpec changes and gates: `plans/combat-openrouter-alignment.md`.

## Titan v2 Alignment Stub

- Umbrella reference: `plans/version-2/titan-integration.md`
- Retune status: Pending (Titan task profile not yet added)
- Last tagged: 2026-09-21
- Retune focus: dedicated Titan task routing to the `background-titan` profile (price-first provider sort, `max_price` ceiling, isolated budgets, fail-open behavior)


---

## Current State Analysis

### Codebase Audit (2026-09-21)

| Metric | Count |
|--------|-------|
| Production `chat.completions.create` call sites | **107** |
| Production files with chat calls | **57** |
| Files using `ai_client_factory` (any helper) | **39** |
| Files using `get_chat_completion_params()` (GPT-5-safe shim) | **28** |
| Files still instantiating raw `OpenAI()` | **22** |
| Test/tooling files with chat calls (excluded from migration) | **26** |
| Files using `images.generate()` (image scope) | **4** |
| Files using `create_tts_client()` (speech scope) | **1** |

Production counts exclude `scripts/**` and `openspec/**`. A raw grep counts 170 call sites across 68 files, but 26 of those files are provider-tripwire tests, fixtures, and the retired `scripts/migrate_to_openrouter.py` - they must not be migrated. Counts overlap (one file can use several helpers).

The February 2026 audit measured 82 call sites across 44 files; production traffic has grown since, driven by the journal/diary MVP (`core/memory/*`), toolkit adaptation (`utils/toolkit_*`, `web/extensions/toolkit_*`), and the GPT-5.6 Luna swap that moved 28 files onto the `get_chat_completion_params()` shim.

### Migration State

| State | Description |
|-------|-------------|
| **Shim-migrated** (28 files) | Use `get_chat_completion_params()`; model family and sampling params resolve centrally |
| **Factory-partial** (11 files) | Use `create_chat_client()` / `get_model_config()` but still build params or model strings by hand |
| **Unmigrated** (22 files) | Raw `OpenAI(api_key=...)` + hardcoded model constants |
| **Non-chat** (5 files) | Image generation (4) and TTS (1); Phase 4 scope with dedicated OpenRouter catalogs |
| **Test/tooling** (26 files) | Tripwire tests, fixtures, and one retired migration script; excluded from migration. Delete the retired script in Phase 3. |

### Existing Infrastructure (What We Keep)

Working and tested in `ai_client_factory.py`:

- `create_chat_client(use_fallback)` - Creates the provider-appropriate client
- `_get_actual_provider()` - Single source of truth for provider detection
- `get_model_config(task_id, model)` - Task-based model resolution
- `get_chat_completion_params(task_id, model, ...)` - GPT-5-safe flat kwargs used by 39 files
- `handle_provider_error()` - Fallback detection and user notification
- `get_fallback_notification()` - User-facing fallback message

Working and tested in `model_config.py`:

- `COMPLEX_TASKS` (currently named `THINKING_ENABLED_TASKS`) - Task complexity classification
- `TASK_TEMPERATURES` - Per-task temperature settings
- `TASK_OVERRIDES` - Per-task model override mechanism
- `OPENROUTER_STRATEGY` / `OPENROUTER_FULL_MODEL` / `OPENROUTER_MINI_MODEL` - Legacy model selection (to be deprecated)

### Known Bug: `extra_body` Shape Inconsistency in Factory

**Must fix in `ai_client_factory.py` before any OpenRouter traffic.**

`get_model_config()` returns inconsistent shapes for `extra_body` depending on the code path:

| Path | `extra_body` value | After `params.update(extra_body)` |
|------|-------------------|-----------------------------------|
| TASK_OVERRIDES | `{"extra_body": {"thinking": {"type": "enabled"}}}` | Adds `extra_body` as a named kwarg (correct for the SDK) |
| TIER 1 / TIER 2 strategies | `{"thinking": {"type": "enabled"}}` | Adds `thinking` as a top-level kwarg (invalid) |
| OpenAI / fallback | `{}` | No extra kwargs |

Only the TASK_OVERRIDES shape is valid for the OpenAI Python SDK. The flat TIER 1 shape produces `TypeError: Completions.create() got an unexpected keyword argument 'thinking'`.

**This bug has never manifested** because `LLM_PROVIDER` defaults to `"openai"`, so `get_model_config()` returns `extra_body: {}` and the OpenRouter paths have never been exercised. Note the bug now propagates through `get_chat_completion_params()`, which does `params.update(model_config.get("extra_body") or {})`.

**Short-term fix (Phase 0):** Normalize all paths to the nested `{"extra_body": {...}}` shape.

**Long-term fix (this plan):** The router bypasses `get_model_config()` for param generation. v4 `MODEL_PROFILES` supply `params` and `provider` blocks directly per tier; `get_chat_completion_params()` remains for unmigrated files until Phase 2 completes.

### What's Missing (What the Router Adds)

1. **Unified call interface** - Callers manually create clients, build params, extract content, and handle errors
2. **Profile-based model routing** - No `MODEL_PROFILES`; model selection is scattered across constants
3. **Provider-preference routing** - No use of OpenRouter `sort`/latency/throughput/quantization/max-price controls
4. **Cost tracking** - No token, cache-read, or cost accounting for chat calls
5. **JSON retry logic** - No structured output parsing with retry
6. **Thread-safe statistics** - Existing `_fallback_status` lacks thread safety
7. **Typed decisions primitive** - `llm.decide()` for System One (gated; see Jev sections)
8. **Image and speech surfaces** - Dedicated OpenRouter catalogs/APIs not yet integrated (Phase 4)
9. **Model bake-off harness** - No repeatable way to score candidate models on real prompts

---

## Architecture Overview

### Design Principle: Facade Over Factory

```
Callers (68 files)
       |
       v
  llm_router.py            <-- NEW: Thin facade
  - call()                      Unified chat interface
  - decide()                    Typed decisions (gated; see Jev sections)
  - _get_profile_and_tier()     Profile-based routing (model-agnostic)
  - provider preferences        sort / latency / price / quantization / max_price
  - cost tracking               Thread-safe usage stats incl. cache reads
  - JSON retry                  3-attempt structured output parsing
  - error classification        Hard stop on quota, retry on transient
       |
       v
  ai_client_factory.py     <-- EXISTING: Infrastructure
  - create_chat_client()        Provider-agnostic client creation
  - get_chat_completion_params()  GPT-5-safe params (kept for unmigrated files)
  - _get_actual_provider()      Provider detection
  - handle_provider_error()     Fallback logic
       |
       v
  model_config.py          <-- EXISTING + NEW: Configuration
  - MODEL_PROFILES v4           Per-tier model + params + provider + pricing (NEW)
  - COMPLEX_TASKS               Task complexity classification (renamed)
  - TASK_TEMPERATURES           Per-task temperature
  - TASK_OVERRIDES              Per-task profile/model override
```

### Consumer Interface

```python
from utils.llm_router import llm

# Simple text response
result = llm.call(task="dm_main", messages=prompt)

# With temperature override
result = llm.call(task="combat_main", messages=prompt, temperature=0.5)

# Structured JSON output with retry
data = llm.call(task="encounter_update", messages=prompt, json_output=True)

# Typed decisions (gated primitive; see Decisions Primitive section)
decision = llm.decide(task="ego_drift", state=text, questions={...})

# Check cost so far (chat + decisions, incl. cache reads)
stats = llm.get_usage_stats()
```

Model choices are validated with a harness rather than by reputation:

```bash
# Score candidate models on a fixed prompt suite (provider-free by default)
.venv/bin/python scripts/benchmark_model_profiles.py --profile production-2026-09
.venv/bin/python scripts/benchmark_model_profiles.py --profile production-2026-09 --live
```

### Model Agnosticism via Profiles (v4.0, 2026-09-21)

**Core principle:** The router must not be locked to any specific model. Models, prices, and providers change monthly. Swapping the active model set must be config-only.

**Problem (v4):** models differ along three axes the old two-field profile could not express:
1. **Capability params** - reasoning effort replaces the retired Kimi `thinking` toggle
2. **Provider behavior** - the same model can be 0.38s/111tps or 0.90s/29tps depending on provider, at 3x price difference
3. **Economics** - cache-read pricing can be 60% below prompt pricing, which matters because NEQ resends large system prompts every turn

**Solution: tiered `MODEL_PROFILES` v4.** Each profile has a `complex` and `simple` tier, and each tier carries its own model, params, provider preferences, and pricing:

```python
PROFILE = {
    "complex": {
        "model": "deepseek/deepseek-v4-flash-0731",
        "params": {"reasoning": {"effort": "medium"}},
        "provider": {"sort": {"by": "throughput"},
                     "preferred_max_latency": {"p90": 1.5},
                     "quantizations": ["fp8"]},
        "price_per_1k": {"prompt": 0.00004, "completion": 0.00016, "cache_read": 0.000016},
    },
    "simple": {
        "model": "z-ai/glm-5.3-flash",
        "params": {"reasoning": {"effort": "low"}},
        "provider": {"sort": {"by": "price"}},
        "price_per_1k": {"prompt": 0.00009, "completion": 0.0003},
    },
    "supports_json_mode": True,
    "max_context": 1_310_720,
}
```

**Confirmed profiles (verified against live OpenRouter catalogs, 2026-09-21):**

```python
# model_config.py

MODEL_PROFILES = {
    # ================================================================
    # PRIMARY: latency-first narrator/combat, resilient economy utility
    # ================================================================
    "production-2026-09": {
        "complex": {
            "model": "deepseek/deepseek-v4-flash-0731",  # 0.38s P50 / 111 tps on Baseten
            "params": {"reasoning": {"effort": "medium"}},
            "provider": {
                "sort": {"by": "throughput"},
                "preferred_max_latency": {"p90": 1.5},
                "quantizations": ["fp8"],
            },
            "price_per_1k": {"prompt": 0.00004, "completion": 0.00016, "cache_read": 0.000016},
        },
        "simple": {
            "model": "z-ai/glm-5.3-flash",  # 31 providers; resilient fallback pool
            "params": {"reasoning": {"effort": "low"}},
            "provider": {"sort": {"by": "price"}},
            "price_per_1k": {"prompt": 0.00009, "completion": 0.0003},
        },
        "supports_json_mode": True,
        "max_context": 1_310_720,
    },

    # ================================================================
    # VALIDATION: newer reasoning for gates, flash fallback
    # Measure deepseek-v4.1-flash against v4-flash-0731 in the harness
    # before promoting; it is ~7.5x the input price.
    # ================================================================
    "validation-split": {
        "complex": {
            "model": "deepseek/deepseek-v4.1-flash",
            "params": {"reasoning": {"effort": "high"}},
            "provider": {"sort": {"by": "throughput"}},
            "price_per_1k": {"prompt": 0.0003, "completion": 0.0012, "cache_read": 0.000006},
        },
        "simple": {
            "model": "deepseek/deepseek-v4-flash-0731",
            "params": {"reasoning": {"effort": "low"}},
            "provider": {"sort": {"by": "throughput"}},
            "price_per_1k": {"prompt": 0.00004, "completion": 0.00016, "cache_read": 0.000016},
        },
        "supports_json_mode": True,
        "max_context": 1_048_576,
    },

    # ================================================================
    # ECONOMY: cheapest viable classification and utility work
    # qwen3.7-flash is a single-provider model; keep allow_fallbacks
    # for the simple tier pointed at GLM.
    # ================================================================
    "economy": {
        "complex": {
            "model": "z-ai/glm-5.3-flash",
            "params": {"reasoning": {"effort": "low"}},
            "provider": {"sort": {"by": "price"}},
            "price_per_1k": {"prompt": 0.00009, "completion": 0.0003},
        },
        "simple": {
            "model": "qwen/qwen3.7-flash",
            "params": {},
            "provider": {"sort": {"by": "price"}},
            "price_per_1k": {"prompt": 0.00003, "completion": 0.00013},
        },
        "supports_json_mode": True,
        "max_context": 1_310_720,
    },

    # ================================================================
    # BACKGROUND / TITAN: price-first, cost ceiling, slow is acceptable
    # The :floor shortcut is equivalent to sort by price; using the
    # explicit provider block keeps the ceiling and quantization policy.
    # ================================================================
    "background-titan": {
        "complex": {
            "model": "deepseek/deepseek-v4-flash-0731",
            "params": {"reasoning": {"effort": "low"}},
            "provider": {
                "sort": {"by": "price"},
                "max_price": {"prompt": 0.00015, "completion": 0.0006},
                "allow_fallbacks": True,
            },
            "price_per_1k": {"prompt": 0.00004, "completion": 0.00016, "cache_read": 0.000016},
        },
        "simple": {
            "model": "z-ai/glm-flash-latest",
            "params": {},
            "provider": {"sort": {"by": "price"}},
            "price_per_1k": {"prompt": 0.000075, "completion": 0.00025},
        },
        "supports_json_mode": True,
        "max_context": 1_310_720,
    },

    # ================================================================
    # FALLBACK: direct OpenAI, current generation.
    # Used automatically on OpenRouter failure. Not an operating mode.
    # ================================================================
    "openai/fallback": {
        "complex": {
            "model": "gpt-5.6-luna",
            "params": {},
            "provider": {},
            "price_per_1k": {"prompt": 0.0002, "completion": 0.0012},
        },
        "simple": {
            "model": "gpt-5.4-nano",
            "params": {},
            "provider": {},
            "price_per_1k": {"prompt": 0.0002, "completion": 0.00125},
        },
        "supports_json_mode": True,
        "max_context": 1_050_000,
    },
}

# Default profile for unknown models - vanilla behavior, no special params
DEFAULT_PROFILE = {
    "complex": {"model": None, "params": {}, "provider": {}, "price_per_1k": {"prompt": 0.002, "completion": 0.002}},
    "simple": {"model": None, "params": {}, "provider": {}, "price_per_1k": {"prompt": 0.002, "completion": 0.002}},
    "supports_json_mode": True,
    "max_context": 128_000,
}
```

**Router logic:**

```python
profile = MODEL_PROFILES.get(ACTIVE_PROFILE, DEFAULT_PROFILE)
is_complex = task in COMPLEX_TASKS
tier = profile["complex"] if is_complex else profile["simple"]

api_params = {"model": tier["model"] or configured_model}
api_params.update(tier.get("params") or {})
provider_prefs = dict(tier.get("provider") or {})  # sent as the "provider" request field
```

**This handles all patterns:**

| Profile | complex model | simple model | complex params | provider posture |
|---------|--------------|-------------|----------------|------------------|
| production-2026-09 | deepseek-v4-flash-0731 | glm-5.3-flash | reasoning=medium | throughput + p90 latency for narrator; price for utility |
| validation-split | deepseek-v4.1-flash | deepseek-v4-flash-0731 | reasoning=high | throughput |
| economy | glm-5.3-flash | qwen3.7-flash | reasoning=low | price |
| background-titan | deepseek-v4-flash-0731 | glm-flash-latest | reasoning=low | price + max_price ceiling |
| openai/fallback | gpt-5.6-luna | gpt-5.4-nano | (none) | direct OpenAI |
| (unknown model) | (configured) | (configured) | (none) | (none) |

**Config workflow:**

```python
# Activate a different profile set globally
ACTIVE_PROFILE = "production-2026-09"     # narrator/combat latency-first
ACTIVE_PROFILE = "validation-split"       # stronger reasoning for gates
ACTIVE_PROFILE = "economy"                # cheapest viable for a test run

# Per-task override (existing mechanism, points at a profile or model)
TASK_OVERRIDES = {
    "npc_builder": {"profile": "validation-split"},
    "action_prediction": {"profile": "economy"},
    "titan_cycle": {"profile": "background-titan"},
}

# Create your own hybrid
MODEL_PROFILES["my-custom-mix"] = {
    "complex": {"model": "anthropic/claude-opus-5", "params": {}, "provider": {}, "price_per_1k": {"prompt": 0.005, "completion": 0.025}},
    "simple":  {"model": "z-ai/glm-5.3-flash", "params": {}, "provider": {"sort": {"by": "price"}}, "price_per_1k": {"prompt": 0.00009, "completion": 0.0003}},
    "supports_json_mode": True,
    "max_context": 1_000_000,
}
ACTIVE_PROFILE = "my-custom-mix"
```

**Three levels of control:**

1. **Global:** Change `ACTIVE_PROFILE` - affects all tasks
2. **Per-task:** Add to `TASK_OVERRIDES` - affects one task, can point to a profile or model
3. **Per-profile:** Edit or create a profile - define any mix of models, params, providers, pricing

**Rename: `THINKING_ENABLED_TASKS` -> `COMPLEX_TASKS`**

The list classifies tasks by reasoning demand, not by any model-specific feature. "Complex" means "needs deeper reasoning" - the profile expresses it:
- DeepSeek/GLM/Gemini: `reasoning.effort` raised
- OpenAI: routes to `gpt-5.6-luna` instead of `gpt-5.4-nano`
- Unknown model: same model, no special params (still works, just not optimized)

**Deprecations (Phase 0):**

| Deprecated | Replaced By |
|------------|-------------|
| `OPENROUTER_STRATEGY` | `MODEL_PROFILES` v4 tier definitions |
| `OPENROUTER_FULL_MODEL` | `profile["complex"]["model"]` |
| `OPENROUTER_MINI_MODEL` | `profile["simple"]["model"]` |
| `OPENROUTER_CHAT_MODEL` as a model ID | `ACTIVE_PROFILE` (kept as a deprecated alias during transition) |
| `THINKING_ENABLED_TASKS` | `COMPLEX_TASKS` (same list, renamed) |
| Kimi `thinking` extra_body shapes | tier `params.reasoning.effort` |

**Phase 0 verification items (facts to pin, not decisions):**

- Exact reasoning param shape per family (`reasoning: {effort}` vs flat `reasoning_effort`); the endpoints list both, so verify against live calls.
- `preferred_max_latency` / `preferred_min_throughput` acceptance and behavior with cached prompts.
- `max_price` object shape for the background profile ceiling.
- Per-model `:batch` discounts before using batch for Titans - DeepSeek's batch rate is *higher* than its base rate; Gemini/OpenAI batch is 50% off.

### Provider Detection

Uses `LLM_PROVIDER` from `model_config.py` (via `_get_actual_provider()` in the factory). Does NOT depend on `MULTIPLAYER_MODE` - this aligns with the single-runtime decision (ADR-0032): provider selection is independent of party size.

**Primary operating mode:** `LLM_PROVIDER = "openrouter"` — all chat models accessed through OpenRouter, selected by `ACTIVE_PROFILE`.

**Fallback safety net:** `LLM_PROVIDER = "openai"` or missing OpenRouter key — direct OpenAI using the `openai/fallback` profile (`gpt-5.6-luna` for complex, `gpt-5.4-nano` for simple). This is also today's production posture, so the router must be behavior-neutral when this profile is active.

**Automatic fallback:** when a call fails on OpenRouter (503, rate limit, timeout), the router retries once with the `openai/fallback` profile and a direct OpenAI client, then reports the fallback to the UI. Transparent to callers.

### Provider Preferences (OpenRouter routing controls)

Each profile tier can carry a `provider` block, sent as the OpenRouter `provider` request field:

| Control | Purpose |
|---------|---------|
| `sort: {"by": "price" \| "throughput" \| "latency"}` | Route by cost or performance; disables default load balancing |
| `preferred_max_latency: {"p90": 1.5}` | Deprioritize endpoints slower than 1.5s p90 (narrator posture) |
| `preferred_min_throughput: {...}` | Deprioritize low-throughput endpoints |
| `quantizations: ["fp8"]` | Keep generator quality consistent across providers |
| `max_price: {"prompt": ..., "completion": ...}` | Hard cost ceiling (background/Titan posture) |
| `only` / `ignore` | Allow/deny specific provider slugs |
| `allow_fallbacks` | Availability safety net across the 20-30 providers per model |

Shortcuts `:floor` (cheapest endpoint) and `:nitro` (fastest endpoint) still exist and are equivalent to coarse `sort` settings. Prefer explicit `provider` blocks so latency floors, quantization policy, and price ceilings travel with the profile.

**Why this matters for NEQ:** `deepseek/deepseek-v4-flash-0731` spans 29 providers from $0.06 to $0.22 input, with measured 0.38s/111tps (Baseten, CoreWeave) versus 0.90s/29tps (DeepInfra). Narrator turns want the fast tail; Titan cycles want the cheap tail. Same model, two postures, no code change.

### Prompt Caching and Session Stickiness

NEQ resends large system prompts and DM notes every turn, so cache-read pricing is a first-class cost lever:

- DeepSeek cache reads are `$0.016/M` versus `$0.04/M` prompt price (60% cheaper).
- OpenRouter provider-sticky routing keeps a conversation on one provider, which is what makes cache hits possible; supply a stable `session_id` per campaign/session in router calls.
- The router's cost tracker must record `input_cache_read` tokens separately from fresh prompt tokens, otherwise session costs are overstated.

### Catalogs and API Surfaces

OpenRouter is several catalogs, not one chat surface. The router maps each to a dedicated client when that phase lands:

| Catalog | Size | API | Client | Status |
|---------|------|-----|--------|--------|
| Text | 446 | `POST /api/v1/chat/completions` | `create_chat_client()` | Phase 1-3 |
| Image | 52 | `POST /api/v1/images` (base64 or SSE) | `create_image_client()` | Phase 4 |
| Speech | 18 | `POST /api/v1/audio/speech` (OpenAI-shaped) | `create_tts_client()` retarget | Phase 4 |
| Decisions | 1 | `POST /api/alpha/decisions` (OpenRouter) | `utils/jev_client.py` | Gated |
| Video | 29 | submit + poll job API | deferred | Deferred |

**Note:** OpenAI's TTS models (`tts-1`, `gpt-4o-mini-tts`) are **not** in OpenRouter's speech catalog — verified 2026-09-21. Routing TTS through OpenRouter means adopting that catalog's voices (Fish Audio, MAI-Voice, Qwen TTS, Deepgram, MiniMax), not keeping OpenAI voices.

**Auto-router** (`openrouter/auto` with `cost_tier`) is available but non-deterministic per turn. It conflicts with validation contracts that assume stable model behavior; keep it to experiment tiers only.

Transparent to callers: `llm.call()` works identically regardless of provider or routing posture.

### Decisions Primitive (System One / Jev)

Chat models generate text; System One models evaluate typed questions against a `state` and return structured answers. Jev (`typesafe/jev-1.13`) is the first model in this class and is exposed on OpenRouter through a **separate Decisions API**, not the OpenAI-compatible chat endpoint. Chat completions SDKs cannot call it.

**Consumer interface - a sibling primitive, not a task profile:**

```python
# Generative chat (unchanged)
result = llm.call(task="dm_main", messages=prompt)

# Typed decisions (new)
decision = llm.decide(
    task="action_prediction",
    state=user_input,
    questions={
        "action_required": {
            "type": "noul",
            "instructions": "Does this game input require the narrator to emit a state-changing action, per the criteria?",
            "criteria": {
                "true": "Input commits to or reports a tracked state change.",
                "false": "Pure dialogue, lore question, description request, or formulaic rest.",
            },
        },
    },
)
# -> {"status": "ok", "task": "action_prediction", "answers": {"action_required": {"noul": 0.97}}, "usage": {...}}
```

**Design constraints:**

| Constraint | Consequence |
|---|---|
| Jev exposes no sampling parameters (`supported_parameters: []`) | Never place it in `MODEL_PROFILES`; no temperature/top_p/thinking handling. |
| Modality is `text->decisions` | Never route it through `create_chat_client()` or `llm.call()`. |
| No text generation | Callers get no rationale. Log `probabilities`/`confidence`; use `Choice` criteria to classify failure modes instead of asking for prose. |
| Documented context rot | Send the minimal scoped `state` per decision, never the full DM Note. |
| Noul returns only P(yes) | Thresholds are per-task config constants tuned on an eval set, not per-answer confidence. |
| Weak numeric interpolation | Never ask Jev to compute or interpolate numbers; Python computes those. |

**Fallback semantics:** a failed or low-confidence Jev call returns `status` of `unavailable` / `rate_limited` / `low_confidence` and the **caller** falls back to the existing chat or deterministic path. Never fall back to another Jev model, and never treat an upstream failure as a negative answer.

**Provider path:** `POST https://openrouter.ai/api/alpha/decisions` with `model: typesafe/jev-1.13`. The `alpha` path is an isolated risk: all request/response shape handling lives in one adapter (`utils/jev_client.py`, Workstream C). Direct TypeSafe (`POST https://api.typesafe.ai/v1/systemone`) stays behind the same interface as an alternative transport.

**Cost/telemetry:** $0.042/M input tokens, output free. Log input tokens, latency, per-question answers and probabilities with each call; reuse the cost-only event pattern from the DALL-E instrumentation (`utils/llm_usage_tracker.py`).

**Guardrail:** if Python can compute the fact, do not ask Jev. Deterministic guard modules stay authoritative; Jev only fills the non-computable semantic middle.

---

## Implementation

### Phase 1: Router Facade (1-2 days)

**Create `utils/llm_router.py` (~280 lines):**

```python
"""
LLM Router - Unified, model-agnostic interface for all AI calls.
Thin facade over ai_client_factory infrastructure.
Uses MODEL_PROFILES v4 for model, params, provider, and cost selection.
"""

import json
from threading import Lock
from typing import Dict, List, Any, Optional, Union

from utils.enhanced_logger import debug, info, warning, error
from utils.ai_client_factory import (
    create_chat_client,
    finalize_chat_params,
    handle_provider_error,
)


# ============================================================================
# Exceptions
# ============================================================================

class GameLLMError(Exception):
    """AI provider cannot fulfill requests. Game cannot continue."""
    pass

class LLMJSONError(Exception):
    """LLM returned content that could not be parsed as JSON."""
    pass


# ============================================================================
# Cost Tracking (Thread-Safe, cache-aware)
# ============================================================================

_usage_lock = Lock()
_usage_stats = {
    "prompt_tokens": 0,
    "cached_tokens": 0,
    "completion_tokens": 0,
    "total_cost_usd": 0.0,
    "calls": 0,
    "errors": 0,
    "fallbacks": 0,
    "by_model": {},
    "by_task": {},
}


# ============================================================================
# Router Class
# ============================================================================

class LLMRouter:
    """
    Unified, model-agnostic LLM call interface.

    Resolves a profile tier (complex/simple) per task, then delegates final
    param assembly to the factory's GPT-5-aware finalizer. Adds: cost tracking
    (including cache reads), JSON retry, and provider error classification.
    """

    MAX_JSON_RETRIES = 3

    def _resolve(self, task: str) -> Dict[str, Any]:
        """Resolve profile tier, model, params, provider prefs, and pricing."""
        from model_config import (
            MODEL_PROFILES, DEFAULT_PROFILE, ACTIVE_PROFILE, COMPLEX_TASKS,
            TASK_TEMPERATURES, TASK_OVERRIDES,
        )
        from utils.ai_client_factory import _get_actual_provider

        _, is_openrouter = _get_actual_provider()
        is_complex = task in COMPLEX_TASKS
        override = TASK_OVERRIDES.get(task, {})

        profile_key = ACTIVE_PROFILE if is_openrouter else "openai/fallback"
        profile_key = override.get("profile", profile_key)
        profile = MODEL_PROFILES.get(profile_key, DEFAULT_PROFILE)

        tier_name = "complex" if is_complex else "simple"
        tier = profile.get(tier_name, {})
        explicit_model = override.get("model")

        return {
            "profile_key": profile_key,
            "tier_name": tier_name,
            "model": explicit_model or tier.get("model") or profile_key,
            "params": {} if explicit_model else dict(tier.get("params") or {}),
            "provider": dict(tier.get("provider") or {}) if is_openrouter else {},
            "price": dict(tier.get("price_per_1k") or {}),
            "temperature": TASK_TEMPERATURES.get(task),
            "is_openrouter": is_openrouter,
        }

    def _resolve_fallback(self, is_complex: bool) -> Dict[str, Any]:
        """Resolve the fallback tier (always direct OpenAI)."""
        from model_config import MODEL_PROFILES, DEFAULT_PROFILE

        profile = MODEL_PROFILES.get("openai/fallback", DEFAULT_PROFILE)
        tier = profile.get("complex" if is_complex else "simple", {})
        return {
            "model": tier.get("model") or "gpt-5.6-luna",
            "params": dict(tier.get("params") or {}),
            "price": dict(tier.get("price_per_1k") or {}),
        }

    def call(
        self,
        task: str,
        messages: List[Dict[str, str]],
        json_output: bool = False,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        retry_tier: Optional[str] = None,
        **kwargs
    ) -> Union[str, Dict[str, Any]]:
        """
        Make an LLM call with automatic routing, tracking, and error handling.

        json_output=True returns a parsed dict and retries on parse failure.
        Raises GameLLMError on quota/billing errors and LLMJSONError after
        JSON retries are exhausted.
        """
        resolved = self._resolve(task)
        is_complex = resolved["tier_name"] == "complex"
        client = create_chat_client(use_fallback=False)

        api_params = finalize_chat_params(
            model=resolved["model"],
            params=resolved["params"],
            temperature=temperature if temperature is not None else resolved["temperature"],
            is_openrouter=resolved["is_openrouter"],
            retry_tier=retry_tier,
        )
        api_params["messages"] = messages
        if resolved["provider"]:
            api_params["provider"] = resolved["provider"]
        if max_tokens is not None:
            api_params["max_tokens"] = max_tokens
        if json_output:
            api_params["response_format"] = {"type": "json_object"}
        api_params.update(kwargs)

        last_error = None
        used_fallback = False

        for attempt in range(self.MAX_JSON_RETRIES if json_output else 1):
            try:
                response = client.chat.completions.create(**api_params)
                content = response.choices[0].message.content
                self._track_usage(response, task, api_params["model"], resolved["price"])
                if json_output:
                    return self._parse_json(content, task)
                return content

            except Exception as e:
                last_error = e

                if self._is_quota_error(e):
                    self._track_error(task)
                    raise GameLLMError(
                        f"AI provider quota/billing error for task '{task}': {e}\n"
                        f"Model: {api_params['model']}\n"
                        f"The game cannot continue without AI access.\n\n"
                        f"Options:\n"
                        f"1. Check your provider account balance\n"
                        f"2. Set LLM_PROVIDER = 'openai' in model_config.py\n"
                        f"3. Set ACTIVE_PROFILE to a cheaper profile in model_config.py\n"
                        f"4. Add a TASK_OVERRIDES entry for this task"
                    )

                if self._is_retryable(e) and not used_fallback:
                    used_fallback = True
                    self._track_fallback(task)
                    handle_provider_error(e, context=task)

                    fb = self._resolve_fallback(is_complex)
                    api_params.pop("provider", None)
                    api_params = finalize_chat_params(
                        model=fb["model"],
                        params=fb["params"],
                        temperature=None,  # GPT-5 family: no legacy sampling
                        is_openrouter=False,
                        retry_tier=retry_tier,
                    )
                    api_params["messages"] = messages
                    if json_output:
                        api_params["response_format"] = {"type": "json_object"}
                    if max_tokens is not None:
                        api_params["max_tokens"] = max_tokens
                    api_params.update(kwargs)

                    client = create_chat_client(use_fallback=True)
                    resolved["price"] = fb["price"]
                    info(f"Fallback to {fb['model']} for task {task}: {e}", category="ai_provider")
                    continue

                if json_output and attempt < self.MAX_JSON_RETRIES - 1:
                    warning(f"JSON parse failed for {task} (attempt {attempt + 1}): {e}", category="ai_provider")
                    continue

                self._track_error(task)
                raise

        self._track_error(task)
        if json_output and last_error:
            raise LLMJSONError(
                f"Failed to get valid JSON for task '{task}' after "
                f"{self.MAX_JSON_RETRIES} attempts: {last_error}"
            )
        raise last_error

    def decide(self, task: str, state: str, questions: Dict[str, Any], **kwargs):
        """Typed decisions primitive (System One / Jev). Not implemented yet.

        Gated behind a passing decomposition eval. See "Decisions Primitive
        (System One / Jev)" and "Jev Decisions Integration (Workstreams A/B/C)".
        """
        raise GameLLMError(
            "llm.decide is not implemented. The decisions primitive is gated "
            "pending the Phase 0 decomposition gate (see router plan)."
        )

    # ------------------------------------------------------------------
    # JSON Parsing
    # ------------------------------------------------------------------

    def _parse_json(self, content: str, task: str) -> Dict[str, Any]:
        """Parse LLM response as JSON. Raises json.JSONDecodeError on failure."""
        if not content or not content.strip():
            raise json.JSONDecodeError("Empty response", content or "", 0)
        text = content.strip()
        if text.startswith("```"):
            lines = [l for l in text.split("\n") if not l.strip().startswith("```")]
            text = "\n".join(lines)
        return json.loads(text)

    # ------------------------------------------------------------------
    # Error Classification
    # ------------------------------------------------------------------

    @staticmethod
    def _is_quota_error(e: Exception) -> bool:
        msg = str(e).lower()
        return any(term in msg for term in [
            'quota', 'billing', 'payment', 'insufficient_quota',
            'exceeded your current usage', 'account balance'
        ])

    @staticmethod
    def _is_retryable(e: Exception) -> bool:
        msg = str(e).lower()
        return any(term in msg for term in [
            'rate limit', 'timeout', 'connection', '503', '502', '504',
            'overloaded', 'unavailable', 'internal server error', '429',
            'bad gateway'
        ])

    # ------------------------------------------------------------------
    # Usage Tracking (Thread-Safe, cache-aware)
    # ------------------------------------------------------------------

    @staticmethod
    def _track_usage(response, task: str, model: str, price: Dict[str, float]):
        usage = getattr(response, 'usage', None)
        if not usage:
            return

        prompt = getattr(usage, 'prompt_tokens', 0) or 0
        completion = getattr(usage, 'completion_tokens', 0) or 0
        details = getattr(usage, 'prompt_tokens_details', None)
        cached = getattr(details, 'cached_tokens', 0) if details else 0
        fresh = max(0, prompt - cached)

        prompt_rate = price.get("prompt", 0.002)
        cache_rate = price.get("cache_read", prompt_rate)
        completion_rate = price.get("completion", 0.002)
        cost = (fresh * prompt_rate + cached * cache_rate + completion * completion_rate) / 1000

        with _usage_lock:
            _usage_stats["prompt_tokens"] += prompt
            _usage_stats["cached_tokens"] += cached
            _usage_stats["completion_tokens"] += completion
            _usage_stats["total_cost_usd"] += cost
            _usage_stats["calls"] += 1
            _usage_stats["by_model"][model] = _usage_stats["by_model"].get(model, 0) + prompt + completion
            _usage_stats["by_task"][task] = _usage_stats["by_task"].get(task, 0) + prompt + completion

        debug(
            f"LLM: {task} | {model} | prompt={prompt} (cached={cached}) "
            f"completion={completion} | ${cost:.4f}",
            category="ai_provider",
        )

    @staticmethod
    def _track_error(task: str):
        with _usage_lock:
            _usage_stats["errors"] += 1

    @staticmethod
    def _track_fallback(task: str):
        with _usage_lock:
            _usage_stats["fallbacks"] += 1

    # ------------------------------------------------------------------
    # Public Stats API
    # ------------------------------------------------------------------

    @staticmethod
    def get_usage_stats() -> Dict[str, Any]:
        """Get current session usage statistics (thread-safe copy)."""
        with _usage_lock:
            return {
                "prompt_tokens": _usage_stats["prompt_tokens"],
                "cached_tokens": _usage_stats["cached_tokens"],
                "completion_tokens": _usage_stats["completion_tokens"],
                "total_cost_usd": round(_usage_stats["total_cost_usd"], 4),
                "total_calls": _usage_stats["calls"],
                "total_errors": _usage_stats["errors"],
                "total_fallbacks": _usage_stats["fallbacks"],
                "by_model": dict(_usage_stats["by_model"]),
                "by_task": dict(_usage_stats["by_task"]),
            }

    @staticmethod
    def reset_usage_stats():
        """Reset statistics. Call at game/session start."""
        with _usage_lock:
            _usage_stats.update({
                "prompt_tokens": 0,
                "cached_tokens": 0,
                "completion_tokens": 0,
                "total_cost_usd": 0.0,
                "calls": 0,
                "errors": 0,
                "fallbacks": 0,
                "by_model": {},
                "by_task": {},
            })
        debug("LLM usage stats reset", category="ai_provider")


# Module-level singleton
llm = LLMRouter()
```

**Phase 0 factory addition - `finalize_chat_params()`:** the router resolves the profile, then delegates provider-specific sampling rules to the factory so GPT-5 quirks live in one place:

```python
def finalize_chat_params(model, params=None, temperature=None, is_openrouter=False, retry_tier=None):
    """Assemble chat completion kwargs for a resolved model.

    - OpenRouter: profile params + temperature as provided
    - Direct OpenAI GPT-5 family: omit temperature (rejected), apply reasoning profile
    - Other direct OpenAI models: platform temperature
    - retry_tier ("high" / "retry"): reasoning escalation for retry attempts. Required
      to preserve combat's GPT5_USE_HIGH_REASONING_ON_RETRY escalation across migration
      (see combat-manager-refactor.md section 3.1).
    """
```

**Retry escalation:** `retry_tier` is an explicit `call()` parameter, not a passthrough
kwarg - leave it out of `**kwargs`, because the OpenAI SDK would reject the unknown
field. Combat passes `retry_tier="high"` on validation-failure retries.

**Update `model_config.py`:** Add `MODEL_PROFILES` v4, `DEFAULT_PROFILE`, `ACTIVE_PROFILE`, and rename `THINKING_ENABLED_TASKS` to `COMPLEX_TASKS`. Deprecate `OPENROUTER_STRATEGY`, `OPENROUTER_FULL_MODEL`, `OPENROUTER_MINI_MODEL`, and `OPENROUTER_CHAT_MODEL`-as-model-ID (keep as aliases during transition). See Model Agnosticism section above for the full config.

**No new dependencies.** Uses `json.loads()` for structured output, not Pydantic. `temperature` is optional per task and is dropped automatically for direct-OpenAI GPT-5 models.

---

### Phase 2: File Migration (4-6 days)

#### Migration Pattern

```python
# BEFORE (unmigrated - 22 production files):
from openai import OpenAI
from config import OPENAI_API_KEY
from model_config import DM_MAIN_MODEL

client = OpenAI(api_key=OPENAI_API_KEY)
response = client.chat.completions.create(
    model=DM_MAIN_MODEL, temperature=0.7, messages=prompt
)
result = response.choices[0].message.content

# BEFORE (factory-partial - 11 production files):
from utils.ai_client_factory import create_chat_client
from model_config import DM_MAIN_MODEL

client = create_chat_client()
response = client.chat.completions.create(
    model=DM_MAIN_MODEL, temperature=0.7, messages=prompt
)
result = response.choices[0].message.content

# AFTER (target state):
from utils.llm_router import llm

result = llm.call(task="dm_main", messages=prompt)
# Model, profile params, provider preferences, temperature policy,
# cost tracking, and error handling - all automatic
```

#### Priority Order

Production files only - test/tooling files are never migrated. Counts re-measured 2026-09-21 (`rg -c 'chat\.completions\.create' --type py -g '!scripts/**' -g '!openspec/**'`).

**Tier 1: Core Game Loop (Day 1-2) - Highest traffic, highest risk**

| File | Calls | Current State | Notes |
|------|-------|---------------|-------|
| `core/managers/combat_manager.py` | 9 | Partial (factory client, hardcoded model constants) | Highest call count; validates every combat batch. Sequencing: migrate after `combat-manager-decomposition` lands so calls are named stage calls (combat plan section 3.1) |
| `core/ai/action_handler.py` | 6 | Partial (inline factory imports, manual fallback) | Complex fallback chains |
| `main.py` | 5 | Partial (factory client, hardcoded models) | Includes `generate_module_summary()`; migrate as `task="summaries"` |

**Tier 2: Already Factory-Migrated (Day 2-3) - Lowest risk, just simplify**

| File | Calls | Current State | Notes |
|------|-------|---------------|-------|
| `core/ai/adv_summary.py` | 2 | Shim (`get_chat_completion_params`) | Simplify to `llm.call()` |
| `core/ai/cumulative_summary.py` | 2 | Shim | Simplify to `llm.call()` |
| `core/ai/transition_validator.py` | 2 | Partial | Travel validation gate |
| `utils/startup_wizard.py` | 2 | Shim | Character creation interview |
| `web/web_interface.py` | 3 chat | Partial | Chat calls only; image/TTS stay Phase 4 |
| `core/ai/combat_compression_engine.py` | 1 | Shim | |
| `core/ai/incremental_compression.py` | 1 | Shim | |
| `updates/plot_update.py` | 1 | Shim | |
| `updates/update_encounter.py` | 1 | Shim | |
| `updates/update_character_info.py` | 1 | Partial (manual fallback) | |

**Tier 3: Generators + Memory/Diary (Day 3-4) - Medium risk, consistent patterns**

| File | Calls | Notes |
|------|-------|-------|
| `core/generators/module_builder.py` | 3 | Multiple `OpenAI()` instantiations |
| `core/generators/area_generator.py` | 3 | Module-level client |
| `core/generators/location_generator.py` | 2 | Module-level client |
| `core/generators/plot_generator.py` | 2 | Module-level client |
| `core/generators/module_stitcher.py` | 2 | `__init__` client |
| `core/generators/npc_builder.py` | 1 | |
| `core/generators/monster_builder.py` | 1 | |
| `core/generators/location_summarizer.py` | 1 | `__init__` client |
| `core/generators/module_generator.py` | 1 | |
| `core/memory/session_diary.py` | 4 | Journal diary MVP; narration summaries |
| `core/memory/players_diary.py` | 2 | |
| `core/memory/story_so_far_compiler.py` | 2 | Story PDF compilation |

**Tier 4: Toolkit, Validation, Utilities (Day 4-6) - Low risk, simple patterns**

| File | Calls | Notes |
|------|-------|-------|
| `utils/toolkit_homebrew_normalizer.py` | 5 | Toolkit adaptation pipeline |
| `core/validation/character_validator.py` | 4 | Same model + low temperature |
| `core/validation/character_validator_backup.py` | 4 | Identical to above; delete if unused during cleanup |
| `utils/homebrewery_adventure_writer.py` | 3 | Overview/plot-hook generation |
| `utils/toolkit_llm_final_reconciliation.py` | 2 | |
| `core/managers/campaign_manager.py` | 2 | |
| `core/managers/level_up_manager.py` | 2 | |
| One-call files (22) | 1 each | `core/validation/character_effects_validator.py`, `core/validation/npc_codex_generator.py`, `core/managers/initiative_tracker_ai.py`, `core/managers/status_manager.py`, `core/managers/storage_processor.py`, `updates/update_character_effects.py`, `utils/api_logger.py`, `utils/bestiary_updater.py`, `utils/character_creation_audit.py`, `utils/level_up.py`, `utils/npc_name_canonicalizer.py`, `utils/npc_reconciler.py`, `utils/prompt_sanitizer.py`, `utils/quest_player_formatter.py`, `utils/reconcile_location_state.py`, `utils/spatial_contract.py`, `utils/toolkit_adaptation_auditor.py`, `utils/toolkit_adaptation_author.py`, `utils/compression/location_compressor.py`, `utils/compression/ai_narrative_compressor_agentic.py`, `web/extensions/toolkit_adaptation_runtime.py`, `web/extensions/toolkit_llm_classification.py` |

**Excluded from migration:**

- `utils/action_predictor.py` - migrates to `llm.decide` (Jev), not `llm.call`; deferred until the decomposition gate passes.
- `utils/ai_client_factory.py`, `utils/provider_response_recovery.py` - provider-safety infrastructure. Integrate with the router; do not route them through the facade.
- `core/toolkit/npc_generator.py`, `core/toolkit/monster_generator.py` - image-only services (`images.generate()`), Phase 4.
- All `scripts/**` and `openspec/**` chat calls - provider-tripwire tests and fixtures; never migrated. Delete `scripts/migrate_to_openrouter.py` in Phase 3.

#### Task ID Assignment

Each call site needs a `task` parameter. Effects reference the `production-2026-09` profile; other profiles remap both tiers without code changes.

| Original Model Constant | Task ID | Complex? | Effect (production-2026-09) |
|--------------------------|---------|----------|------------------------------|
| `DM_MAIN_MODEL` | `dm_main` | Yes | complex tier: `deepseek/deepseek-v4-flash-0731` + reasoning medium + throughput/latency provider prefs |
| `DM_VALIDATION_MODEL` | `dm_validation` | Yes | complex tier: `deepseek-v4-flash-0731` (validation-split profile swaps in `deepseek-v4.1-flash`) |
| `COMBAT_MAIN_MODEL` | `combat_main` | Yes | complex tier: narrator model, latency-first |
| `COMBAT_DIALOGUE_SUMMARY_MODEL` | `combat_dialogue_summary` | No | simple tier: `z-ai/glm-5.3-flash`, price-first |
| `DM_MINI_MODEL` | `dm_mini` | No | simple tier |
| `DM_FULL_MODEL` | `dm_full` | Yes | complex tier |
| `DM_SUMMARIZATION_MODEL` | `summaries` | No | simple tier |
| `ADVENTURE_SUMMARY_MODEL` | `adventure_summary` | No | simple tier |
| `PLOT_UPDATE_MODEL` | `plot_update` | No | simple tier |
| `PLAYER_INFO_UPDATE_MODEL` | `player_info_update` | No | simple tier |
| `NPC_INFO_UPDATE_MODEL` | `npc_info_update` | No | simple tier |
| `ENCOUNTER_UPDATE_MODEL` | `encounter_update` | No | simple tier |
| `CHARACTER_VALIDATOR_MODEL` | `character_validator` | Yes | complex tier |
| `NPC_BUILDER_MODEL` | `npc_builder` | Yes | complex tier |
| `MONSTER_BUILDER_MODEL` | `monster_builder` | Yes | complex tier |
| `LEVEL_UP_MODEL` | `level_up` | Yes | complex tier |
| `TRANSITION_VALIDATOR_MODEL` | `transition_validation` | No | simple tier (consider `economy` profile override) |
| `ACTION_PREDICTION_MODEL` | `action_prediction` | Yes | Deferred decisions target (`llm.decide`); until promotion use an `economy`-profile override. |
| `NARRATIVE_COMPRESSION_MODEL` | `narrative_compression` | No | simple tier |
| `LOCATION_COMPRESSION_MODEL` | `location_compression` | Yes | complex tier |

---

### Phase 3: Cleanup & Polish (1-2 days)

#### 1. Remove Dead Code from `ai_client_factory.py`

These functions have zero consumers (verified 2026-09-21) - delete in Phase 0:

- `get_model_for_task()` - never imported
- `is_thinking_enabled()` - never imported
- `get_task_complexity()` - never imported

These functions will have zero consumers after full migration - delete them then:

- `get_chat_model_name()` - replaced by profile-based routing; 9 live consumers until Phase 2 completes
- `get_model_display_name()` - only used by `get_chat_model_name()` consumers
- `get_model_config()` - replaced by `MODEL_PROFILES` tier resolution in the router. `get_chat_completion_params()` remains until the last unmigrated file is done.

Keep:

- `create_chat_client()` - used by router for client creation
- `finalize_chat_params()` - NEW in Phase 0; owns GPT-5-family sampling rules
- `_get_actual_provider()` - used by router for provider detection
- `handle_provider_error()` / `get_fallback_notification()` - used by router and web UI
- `reset_fallback_status()` / `get_provider_status()` - diagnostics
- `create_image_client()` / `create_tts_client()` - Phase 4 (image/speech catalogs)

#### 1b. Remove Deprecated Config from `model_config.py`

After full migration, these are replaced by `MODEL_PROFILES` v4:

- `OPENROUTER_STRATEGY` - replaced by profile tiers
- `OPENROUTER_FULL_MODEL` - replaced by `profile["complex"]["model"]`
- `OPENROUTER_MINI_MODEL` - replaced by `profile["simple"]["model"]`
- `OPENROUTER_CHAT_MODEL` - replaced by `ACTIVE_PROFILE` (keep as a deprecated alias during transition)
- `THINKING_ENABLED_TASKS` alias - keep only `COMPLEX_TASKS`

#### 1c. Remove Retired Tooling

- `scripts/migrate_to_openrouter.py` - one-shot migration tool from the abandoned first attempt; zero consumers, superseded by this plan.
- `core/validation/character_validator_backup.py` - confirm unused, then delete.

#### 2. Remove Legacy Imports from Migrated Files

After migration, each file should have only:
```python
from utils.llm_router import llm
```

Remove from each migrated file:
- `from openai import OpenAI`
- `from config import OPENAI_API_KEY`
- `from model_config import DM_MAIN_MODEL` (and all other model constants)
- `from utils.ai_client_factory import create_chat_client, get_chat_model_name, ...`
- Module-level `client = OpenAI(...)` or `client = create_chat_client()`

Exception: Files that use model constants for non-LLM purposes (logging, display) may keep those imports.

#### 3. Add Usage Reporting

Add `/usage` command to game interface:

```python
# In main.py or web_interface.py
from utils.llm_router import llm

def handle_usage_command():
    stats = llm.get_usage_stats()
    return (
        f"LLM Usage This Session:\n"
        f"  Calls: {stats['total_calls']}\n"
        f"  Prompt tokens: {stats['prompt_tokens']:,} (cached: {stats['cached_tokens']:,})\n"
        f"  Completion tokens: {stats['completion_tokens']:,}\n"
        f"  Cost: ${stats['total_cost_usd']:.4f}\n"
        f"  Errors: {stats['total_errors']}\n"
        f"  Fallbacks: {stats['total_fallbacks']}\n"
        f"\nBy Task:\n"
        + "\n".join(f"  {t}: {n:,} tokens" for t, n in sorted(
            stats['by_task'].items(), key=lambda x: -x[1]))
    )
```

#### 4. Update Documentation

- Update AGENTS.md "OpenRouter Integration" section to reflect the router pattern and v4 profiles
- Remove references to `get_chat_model_name()` pattern
- Add migration pattern documentation
- Record the model-refresh cadence: profiles carry dated model IDs (`deepseek-v4-flash-0731`), reviewed quarterly or when a materially better model lands

---

## Jev Decisions Integration (Workstreams A/B/C)

System One / Jev is integrated in three workstreams. Only A and B are authorized while the runtime remains on OpenAI. C is gated behind the router facade **and** a passing Phase 0 gate.

### Workstream A - Plan amendment (this document)

Status: complete (2026-09-21). Deliverables: Decisions Primitive section, migration-table amendment for `utils/action_predictor.py`, task-ID amendment for `action_prediction`, the Decisions Log entries, and the Workstream C "Later: utils" surface below.

### Workstream B - Phase 0 eval spike (runtime-independent)

Status: complete (2026-09-21). Committed artifacts:

| Artifact | Purpose |
|---|---|
| `scripts/extract_jev_eval_set.py` | Builds the labeled eval set from `modules/conversation_history/conversation_history.json` and `debug/quality_control/rejected_narrator_turns.jsonl` |
| `scripts/spike_jev_decisions.py` | Runs the Noul question in `fixture`, `baseline`, and `live` modes; emits the gate report |
| `scripts/test_jev_decision_spike.py` | 52 provider-free tests |
| `scripts/test_action_predictor_params_contract.py` | 4 provider-free tests (regression for the bug found by the spike) |

Runtime-local outputs (gitignored under `debug/jev/`): `eval_set.jsonl`, `phase0_report_full.json`, `phase0_report_tail.json`, `phase0_report_baseline.json`.

**Eval set:** 71 cases (37 strong labels from accepted history pairs, 34 weak labels from rejected attempts), 26 positive / 45 negative, 20 duplicates removed.

**Question asked (single Noul):** "Does this game input require the narrator to emit a state-changing game action (any action other than updateTime), per the criteria?"

**Measured results (2026-09-21):**

| Arm | Evaluated | Agreement @0.5 | FN rate | FP rate | P50 latency | Input tokens | Est. cost / 1k decisions |
|---|---|---|---|---|---|---|---|
| Incumbent GPT predictor (params fixed) | 71/71 | 0.592 | 7.7% | 60.0% | 1402 ms | 162k (estimated) | $0.096 (estimated) |
| Jev, full state | 68/71 (3 transient 5xx) | 0.677 | 29.2% | 34.1% | 377 ms | 95.3k (measured) | $0.059 |
| Jev, player-tail state | 71/71 | 0.704 | 23.1% | 33.3% | 382 ms | 33.8k (measured) | $0.020 |

**Gate: FAIL.** Targets were agreement >= 0.95 and FN rate <= 0.05. No arm cleared them, so promotion of `utils/action_predictor.py` to `llm.decide` is **not authorized**.

**What the spike established:**

1. The OpenRouter Decisions API integration works; request/response shape confirmed against `typesafe/jev-1.13`.
2. Jev is ~3.7x faster and ~2.5-5x cheaper per decision than the incumbent chat call, with measured token usage (the incumbent's is estimated).
3. Error profiles differ materially: Jev has fewer false positives but more false negatives. For model routing, FN is the costly error - Jev currently leaks 6-7 of 26 positives per 71 turns.
4. State scoping (player-tail) improves agreement ~3 points, cuts FN ~6 points, and cuts tokens ~65% - consistent with documented context rot, but not outcome-changing.
5. A single Noul question cannot represent this decision. The missed positives are narrator-initiated or subtle mechanics (`requestRoll`, `updatePartyNPCs`, `moveBackgroundNPC`, `updatePartyTracker`), none of which read as "state-changing" from input text alone.
6. Transient upstream instability was observed on the alpha endpoint: one burst produced 44/71 HTTP 529/503 errors. Any future decisions path needs retry/backoff honoring `retry-after`, and must treat upstream failure as `unavailable`, never as a negative answer.

**Discovered production bug (fixed in this workstream):** `utils/action_predictor.py` passed `temperature=0.1` directly to the direct-OpenAI GPT-5.6 Luna endpoint, which rejects the parameter. Every prediction silently fell through to the conservative `requires_actions=True` fallback, so intelligent routing has been routing every turn to the full model since the Luna swap. Fixed by routing through `get_chat_completion_params("action_prediction", ...)`.

**Recommended next experiment (not authorized yet):** decompose the decision into 3-6 atomic Noul questions (movement, combat initiation, inventory, party membership, quest progression, roll request) and OR the answers in code; label from accepted history pairs only; add a small adjudicated gold subset to separate label noise from model error. Re-run the gate before creating `jev-decisions-primitive`.

### Workstream C - Runtime promotion (deferred, gated)

Order of work once authorized:

1. `llm-router-facade` (fresh change) - chat facade per this plan's Phase 0/1.
2. `jev-decisions-primitive` - `utils/jev_client.py` + `llm.decide()` + config + telemetry + fail-open + provider-free tests. **Not authorized until the decomposition gate passes.**
3. `jev-action-predictor-promotion` - shadow mode first, then confidence-gated live with chat fallback, behind `ENABLE_JEV_ACTION_PREDICTION`.
4. Later, one change each: `jev-narrator-validator-shadow`, `jev-combat-validator-residual`, `jev-ego-drift-classifier`.

### Later: utils and config surface (implementation detail)

| File | Change |
|---|---|
| `utils/jev_client.py` (new) | Single versioned adapter. `decide(state, questions, model) -> {status, answers, usage}`; statuses `ok` / `unavailable` / `rate_limited` / `invalid_response`; OpenRouter Decisions transport now, direct `/v1/systemone` behind the same interface later; retry/backoff honoring `retry-after`; never mutates game state; never logs credentials. |
| `utils/llm_router.py` (new) | Add `decide(task, state, questions, **kwargs)` as a sibling to `call()`. Consult a decisions-task config map, not `MODEL_PROFILES`. Track state tokens, latency, per-question answers and probabilities. No JSON retry (there is no free text to repair). |
| `model_config.py` | Add `JEV_MODEL = "typesafe/jev-1.13"`, `JEV_PROVIDER = "openrouter"`, `ENABLE_JEV_ACTION_PREDICTION = False`, `JEV_ACTION_PREDICTION_CONFIDENCE_MIN = 0.90`, and a `DECISION_TASKS` map mirroring `COMPLEX_TASKS`. |
| `utils/action_predictor.py` | Route the decision through `llm.decide` behind the flag. Shadow mode logs both answers without changing routing. On `unavailable` or a probability below the confidence minimum, fall back to the chat predictor. Preserve the `{requires_actions, reason, confidence}` return contract (`reason` becomes telemetry-style text; `confidence` maps from probability buckets). Caller at `main.py:5110` unchanged. |
| `utils/llm_usage_tracker.py` | Reuse the cost-only event pattern from the DALL-E instrumentation for Jev decisions (input tokens only; output free). |

---

## Error Handling

### Error Classification

| Error Type | Action | Example |
|------------|--------|---------|
| **Quota/Billing** | Hard stop — raise `GameLLMError` | "exceeded your current usage limit" |
| **Transient** | Retry with fallback model | 429 rate limit, 503, timeout, connection error |
| **JSON Parse** | Retry LLM call (up to 3 attempts) | Invalid JSON in structured output |
| **Other** | Re-raise to caller | Unexpected API errors |

### Hard Stop Display

Scenario: rate-limit or upstream failure exhaustion. Note the fallback is automatic for transient errors; this state only appears when both the primary profile and the OpenAI fallback fail.

```
[CRITICAL ERROR]
AI provider quota/billing error for task 'dm_main': ...

The game cannot continue without AI access.

Options:
1. Check your OpenRouter account balance
2. Set LLM_PROVIDER = "openai" in model_config.py
3. Set ACTIVE_PROFILE to a cheaper profile in model_config.py
4. Add a TASK_OVERRIDES entry for this task
```

---

## Testing Strategy

### Unit Tests (No API calls)

```python
# scripts/test_llm_router.py

def test_error_classification():
    """Verify error types are correctly classified."""
    router = LLMRouter()
    assert router._is_quota_error(Exception("exceeded your current usage limit"))
    assert router._is_quota_error(Exception("insufficient_quota"))
    assert not router._is_quota_error(Exception("connection timeout"))
    assert router._is_retryable(Exception("rate limit exceeded"))
    assert router._is_retryable(Exception("503 Service Unavailable"))
    assert not router._is_retryable(Exception("invalid api key"))

def test_json_parsing():
    """Verify JSON extraction handles edge cases."""
    router = LLMRouter()
    assert router._parse_json('{"key": "value"}', "test") == {"key": "value"}
    assert router._parse_json('```json\n{"key": "value"}\n```', "test") == {"key": "value"}

def test_usage_tracking_is_cache_aware():
    """Verify stats track fresh, cached, and completion tokens separately."""
    LLMRouter.reset_usage_stats()
    stats = LLMRouter.get_usage_stats()
    assert stats["calls"] == 0
    assert stats["cached_tokens"] == 0
    # Feed a fake response with prompt_tokens_details.cached_tokens and verify
    # cost math uses cache_read rate instead of the fresh prompt rate.

def test_profile_tier_resolution():
    """Verify v4 tier lookup for known profiles and unknown models."""
    from model_config import MODEL_PROFILES, DEFAULT_PROFILE
    profile = MODEL_PROFILES["production-2026-09"]
    assert profile["complex"]["model"] == "deepseek/deepseek-v4-flash-0731"
    assert profile["complex"]["provider"]["sort"]["by"] == "throughput"
    assert profile["simple"]["model"] == "z-ai/glm-5.3-flash"
    assert MODEL_PROFILES.get("unknown/model", DEFAULT_PROFILE) == DEFAULT_PROFILE
    assert DEFAULT_PROFILE["complex"]["params"] == {}

def test_background_profile_has_price_ceiling():
    """Titan posture must carry a max_price ceiling and price sort."""
    from model_config import MODEL_PROFILES
    bg = MODEL_PROFILES["background-titan"]
    assert bg["complex"]["provider"]["sort"]["by"] == "price"
    assert "max_price" in bg["complex"]["provider"]

def test_finalize_chat_params_gpt5_temperature_policy():
    """Direct OpenAI GPT-5 models omit temperature; OpenRouter keeps it."""
    params = finalize_chat_params("gpt-5.6-luna", temperature=0.7, is_openrouter=False)
    assert "temperature" not in params
    params = finalize_chat_params("deepseek/deepseek-v4-flash-0731", temperature=0.7, is_openrouter=True)
    assert params["temperature"] == 0.7

def test_decide_stub_is_gated():
    """llm.decide must fail closed until the Jev gate passes."""
    try:
        llm.decide(task="ego_drift", state="x", questions={})
        assert False, "expected GameLLMError"
    except GameLLMError as exc:
        assert "not implemented" in str(exc)
```

### Bake-Off Harness (Phase 0/1 deliverable)

`scripts/benchmark_model_profiles.py` scores candidate models on a fixed production-shaped prompt suite:

- Provider-free by default (fixtures + a fake transport); `--live` runs real calls.
- Per candidate model: narration quality score (LLM-judged rubric), JSON-validity rate, latency p50/p90, throughput, token usage, cache-read hit rate, and cost per call.
- Ships with fixtures covering: narrator turn (DM note + world state), combat batch validation, encounter JSON update, and summary compression.
- Gate: `production-2026-09` narrator and combat choices must beat or match the current `gpt-5.6-luna` baseline on JSON-validity rate, at lower cost, before callsites migrate.

### Manual Testing Checklist

- [ ] `llm.call(task="dm_main", messages=[...])` returns narration text
- [ ] `llm.call(task="dm_main", messages=[...], json_output=True)` returns a parsed dict
- [ ] Fallback triggers when OpenRouter returns 503; fallback request carries no `temperature` (GPT-5 family)
- [ ] `GameLLMError` raised on quota error
- [ ] `llm.get_usage_stats()` reports prompt, cached, and completion tokens separately
- [ ] Works with `LLM_PROVIDER = "openai"` - behavior matches today's build exactly
- [ ] Works with `LLM_PROVIDER = "openrouter"` and `ACTIVE_PROFILE = "production-2026-09"`
- [ ] Provider prefs appear on the wire (`provider.sort`, latency floor; verify with debug logging)
- [ ] Profile swap: change `ACTIVE_PROFILE`, restart, verify new models selected
- [ ] Unknown profile: set `ACTIVE_PROFILE` to a nonexistent key, verify DEFAULT_PROFILE applies without crash
- [ ] `TASK_OVERRIDES` with `"profile"` redirects a single task
- [ ] `llm.decide()` raises the gated message

---

## Migration Checklist

### Phase 0: Config & Factory Prep (Prerequisite)
- [ ] Add `MODEL_PROFILES` v4, `DEFAULT_PROFILE`, `ACTIVE_PROFILE` to `model_config.py`
- [ ] Rename `THINKING_ENABLED_TASKS` to `COMPLEX_TASKS` (keep alias for backward compat)
- [ ] Mark `OPENROUTER_STRATEGY`, `OPENROUTER_FULL_MODEL`, `OPENROUTER_MINI_MODEL`, `OPENROUTER_CHAT_MODEL` as deprecated in comments
- [ ] Normalize `extra_body` shape in `ai_client_factory.py` `get_model_config()` (blocker until the router takes over param generation)
- [ ] Add `finalize_chat_params()` (GPT-5 temperature policy + profile params + `retry_tier` escalation)
- [ ] Verify `finalize_chat_params(retry_tier="high")` reproduces the legacy `get_chat_completion_params("combat_validation", ..., retry_tier="high")` kwargs (combat retry parity)
- [ ] Add `API_TIMEOUT_SECONDS` / `API_CONNECT_TIMEOUT_SECONDS` to `model_config.py` and `timeout=httpx.Timeout(...)` to both client constructors in `ai_client_factory.py` (combat plan section 3.1 depends on this client-level bound)
- [ ] Delete zero-consumer functions: `get_model_for_task`, `is_thinking_enabled`, `get_task_complexity`
- [ ] Verify reasoning param shape live (`reasoning: {effort}` vs `reasoning_effort`) and record the result
- [ ] Verify `preferred_max_latency`, `preferred_min_throughput`, and `max_price` are accepted
- [ ] Verify 39 factory-consuming production files still compile after changes

### Phase 1: Router Facade
- [ ] Create `utils/llm_router.py` (call, decide stub, cache-aware stats)
- [ ] Profile-tier resolution via `_resolve()` / `_resolve_fallback()`
- [ ] Write unit tests (error classification, JSON parsing, stats, profile tiers, finalize params, decide stub)
- [ ] Build `scripts/benchmark_model_profiles.py` with fixtures; run the bake-off gate
- [ ] OpenAI parity smoke with `LLM_PROVIDER = "openai"`
- [ ] OpenRouter live smoke with `ACTIVE_PROFILE = "production-2026-09"` (one small call)
- [ ] Verify cost tracking uses tier pricing including `cache_read`

### Phase 2: File Migration (54 files / 104 chat call sites -> `llm.call()`)
- [ ] Tier 1: 3 files / 20 calls (`combat_manager.py`, `action_handler.py`, `main.py`); `combat_manager.py` runs only after `combat-manager-decomposition` (combat plan section 3.1)
- [ ] Tier 2: 10 already-factory-migrated files / 16 calls
- [ ] Tier 3: 12 generator and memory/diary files / 24 calls
- [ ] Tier 4: 29 toolkit/validation/utility files / 44 calls
- [ ] Add `llm.reset_usage_stats()` to `main.py` startup (terminal mode)
- [ ] Add `llm.reset_usage_stats()` to `web_interface.py` server start (web mode)
- [ ] Verify each file compiles (`python -m py_compile`)
- [ ] In-game smoke test after each tier
- [ ] Excluded and unchanged: `action_predictor.py` (decide target), `ai_client_factory.py`, `provider_response_recovery.py`, image/TTS files, tests/fixtures

### Phase 3: Cleanup
- [ ] Delete dead code from `ai_client_factory.py` (see cleanup list)
- [ ] Delete `scripts/migrate_to_openrouter.py` and `core/validation/character_validator_backup.py` if unused
- [ ] Remove deprecated config (`OPENROUTER_STRATEGY`, `OPENROUTER_FULL_MODEL`, `OPENROUTER_MINI_MODEL`, `OPENROUTER_CHAT_MODEL`, `THINKING_ENABLED_TASKS` alias)
- [ ] Remove legacy imports from migrated files
- [ ] Add `/usage` command
- [ ] Update AGENTS.md
- [ ] Final in-game test (full session)

### Phase 4: Image and Speech Catalogs (follow-on change)
- [ ] Image: `meta/muse-image` primary ($0.01/image) + `krea/krea-2-large` premium ($0.06/image) via `POST /api/v1/images`
- [ ] Speech: retarget `create_tts_client()` to `POST /api/v1/audio/speech`; bake off Fish S2.1 Pro vs MAI-Voice-2-Flash vs Qwen TTS Flash (free tiers first, human listen before cutover)
- [ ] Confirm reference-image support and per-image cost with a probe before committing portrait prewarm budgets
- [ ] Keep image generation async/prewarm-only (41-74s per image at quality tiers)

---

## Future Considerations

### Per-Task Model Experimentation

With `MODEL_PROFILES` in place, testing different models for different tasks requires no code changes:

**Redirect a single task to a different profile:**
```python
TASK_OVERRIDES = {
    "combat_main": {"profile": "validation-split"},  # Stronger reasoning for combat gates
}
```

**Redirect a single task to a specific model (bypass profile):**
```python
TASK_OVERRIDES = {
    "encounter_update": {"model": "qwen/qwen3.7-flash"},  # Cheapest JSON model
}
```

**Add a new model to test (v4 shape):**
```python
MODEL_PROFILES["experiment/next-gen"] = {
    "complex": {
        "model": "vendor/model-name",
        "params": {},
        "provider": {"sort": {"by": "throughput"}},
        "price_per_1k": {"prompt": 0.0001, "completion": 0.0004},
    },
    "simple": {"model": "z-ai/glm-5.3-flash", "params": {}, "provider": {}, "price_per_1k": {}},
    "supports_json_mode": True,
    "max_context": 1_000_000,
}
ACTIVE_PROFILE = "experiment/next-gen"  # Switch globally
```

No code changes in any of these scenarios. No router modifications. No factory updates.

### Async Support (Deferred)

Not needed yet. Flask + SocketIO uses synchronous request handling. If the web server migrates to async (FastAPI, etc.), add `call_async()` at that time. Note that Titan/background cycles would benefit from async or thread-pool execution when that runtime lands.

### Prompt Caching and Cache-Aware Costing (Phase 1)

NEQ resends large system prompts and DM notes every turn. Provider-side prompt caching is now a first-class cost lever rather than a deferred idea:

- DeepSeek cache reads are `$0.016/M` versus `$0.04/M` fresh prompt price (60% cheaper).
- Provider-sticky routing is what makes cache hits possible; sessions should carry a stable `session_id` so a conversation stays on one provider.
- The router's cost tracker records `input_cache_read` tokens separately from fresh prompt tokens (already specified in the Phase 1 reference implementation).
- The bake-off harness reports cache hit rate per candidate so cache economics are part of model selection.

### Image and Speech Catalogs (Phase 4)

**Image generation** moves off direct DALL-E to the OpenRouter Images API (`POST /api/v1/images`):

| Role | Model | Price | Notes |
|------|-------|-------|-------|
| Primary portraits/NPCs/monsters | `meta/muse-image` | $0.01/image | Reference-image conditioning, reasons before rendering, text rendering |
| Premium hero/cover art | `krea/krea-2-large` | $0.06/image | Photoreal/artistic character, style references and moodboards |
| Iteration fallback | `krea/krea-2-medium-turbo` | from $0.015/image | Speed-focused variant if Muse is unavailable |
| Alternatives | `bytedance-seed/seedream-5-0-pro` ($0.045), `qwen/qwen-image-3-pro` ($0.04, 4 reference images), `microsoft/mai-image-2.6-flash` (up to 5 references) | - | Evaluate only if the primary/premium pair underperforms on character consistency |

All image generation is async/prewarm-only: measured P50 end-to-end latency is 41s (Krea 2 Large) to 74s (Qwen Image 3 Pro). Per-image cost for token-priced models must be probed before committing portrait-prewarm budgets.

**Speech/TTS** moves to the OpenRouter speech catalog (`POST /api/v1/audio/speech`, OpenAI-shaped request):

| Role | Model | Price | Notes |
|------|-------|-------|-------|
| Primary candidate | `fish-audio/s2.1-pro` | $15/M UTF-8 bytes | Expressive narration, multi-speaker dialogue, natural-language style/emotion controls |
| Low-latency candidate | `microsoft/mai-voice-2-flash` | $15/M chars | 24kHz, 15 languages, tone/delivery control |
| Budget candidate | `qwen/qwen-audio-3.0-tts-flash` | $15/M chars | DashScope synthesizer |
| Dev/testing | `deepgram/flux-tts:free`, `fish-audio/s2.1-pro-free:free` | $0 | Prototype the pipeline before paid cutover |

Bake-off before cutover: the DM's audible identity changes, so include a human listen on representative narration plus a multi-speaker dialogue sample. OpenAI TTS models are not available through OpenRouter, so the existing `tts-1` voices cannot be retained on this path.

### Video Generation (Deferred)

OpenRouter exposes 29 video models with a submit-and-poll job API (text-to-video, image-to-video, reference-guided, webhooks). The repo's `VIDEO_PROVIDER` remains `"none"`; revisit only if scene video becomes a product requirement.

### Additional OpenAI-Compatible Providers (Deferred)

The factory's `create_chat_client()` already works by setting `base_url` + API key on the standard OpenAI Python SDK. Adding support for other OpenAI-compatible providers (local Ollama, Azure OpenAI, Together.ai, etc.) would mean:

1. Add a new `LLM_PROVIDER` option (e.g., `"ollama"`, `"azure"`)
2. Configure its `base_url` and API key in `config.py`
3. Add a `MODEL_PROFILES` entry for whatever models it serves
4. No router changes needed — it already uses profiles, not provider-specific logic

OpenAI-direct is already in place as the fallback and could become a first-class provider option (alongside OpenRouter) with minimal changes to `_get_actual_provider()`.

### API Timeout Protection & Escalating User Feedback (Router-Level)

**Context:** On 2026-02-09, combat validation hung indefinitely waiting for an OpenAI API response. The SDK default timeout is 600s (10 minutes). No timeout is set on any of the 85 `client.chat.completions.create()` call sites or on any `OpenAI()` constructor in the codebase. The user saw a static "Validating combat actions..." placeholder with no escalation or timeout recovery.

**Interim fix (pre-router):** A combat-specific timeout + escalating status timer will be applied directly to `combat_manager.py` for the current OpenAI-based TT build. See "Combat-Specific Timeout Fix" section below.

**Router-level fix (this plan):** When the router centralizes all 85 call sites behind `llm.call()`, timeout protection and user feedback become automatic for every LLM call, not just combat.

#### Client-Level Timeout

Apply `httpx.Timeout` on the `OpenAI()` constructor in `ai_client_factory.py`. This gives one configuration point for all call sites:

```python
import httpx

# In create_chat_client():
client = OpenAI(
    api_key=api_key,
    base_url=base_url,
    timeout=httpx.Timeout(API_TIMEOUT_SECONDS, connect=API_CONNECT_TIMEOUT_SECONDS),
)
```

**Configuration constants** (add to `model_config.py`):
```python
API_TIMEOUT_SECONDS = 120      # Total request timeout (read + write + pool)
API_CONNECT_TIMEOUT_SECONDS = 10  # TCP connection timeout only
```

**Rationale for 120s:**
- OpenAI SDK default is 600s (absurd for interactive gameplay)
- Combat validation prompts can be large (46K+ chars observed) and slow models need time
- 120s is generous enough for complex prompts over OpenRouter, short enough to not lose players
- On timeout: triggers existing `handle_provider_error()` fallback to OpenAI

#### Escalating Status Timer (StatusTimer Context Manager)

A context manager that runs a background thread, escalating the status message while a blocking API call runs. Uses the existing `status_manager.update_status()` pipeline -- no frontend changes needed.

```python
# In core/managers/status_manager.py or utils/status_timer.py

from contextlib import contextmanager
from threading import Thread, Event

DEFAULT_ESCALATION_SCHEDULE = [
    (0,  None),                                  # Keep caller's initial message
    (10, "Still processing, please wait..."),     # Reassurance
    (30, "Response taking longer than usual..."), # Honesty
    (60, "Waiting for AI provider ({elapsed}s)..."),  # Transparency with elapsed time
]

@contextmanager
def status_timer(initial_message, schedule=None, update_fn=None):
    """
    Escalate status messages while a blocking operation runs.
    
    Usage:
        status_manager.update_status("Validating combat actions...", is_processing=True)
        with status_timer("Validating combat actions...", update_fn=status_manager.update_status):
            result = client.chat.completions.create(...)
        # Timer auto-cancels on exit
    """
    ...
```

**Integration in router's `call()` method:**

```python
def call(self, task, messages, status_callback=None, **kwargs):
    # If caller provided a status callback, wrap the API call in a timer
    if status_callback:
        with status_timer(f"Processing {task}...", update_fn=status_callback):
            response = client.chat.completions.create(**api_params)
    else:
        response = client.chat.completions.create(**api_params)
```

This way combat_manager can pass `status_manager.update_status` as the callback, while non-interactive callers (generators, validators) skip the timer entirely.

#### Implementation Checklist (Router Phase)

- [ ] Add `API_TIMEOUT_SECONDS` and `API_CONNECT_TIMEOUT_SECONDS` to `model_config.py`
- [ ] Add `timeout=httpx.Timeout(...)` to both client constructors in `ai_client_factory.py`
- [ ] Create `StatusTimer` context manager
- [ ] Add optional `status_callback` parameter to `llm.call()`
- [ ] Update combat_manager migration (Phase 2 Tier 1) to pass status callback
- [ ] Test timeout triggers fallback correctly
- [ ] Test escalating messages appear in UI during slow responses

---

### Combat-Specific Timeout Fix (Pre-Router, Current Build)

**Target:** `core/managers/combat_manager.py` -- the two blocking API calls in the combat retry loop (generation ~3581, validation ~849).

**Scope:** Surgical fix for the active OpenAI-based TT build, to be superseded by the router-level solution.

**Interlock (2026-09-21):** This pre-router fix is now satisfied by the Phase 0 client-level `httpx.Timeout` in this plan. The combat refactor no longer adds per-call timeouts for the remaining 6 sites; it verifies coverage and removes the legacy per-call arguments during migration (see `plans/version-2/combat-manager-refactor.md` section 3.1).

**Changes:**
1. **`model_config.py`** -- Add `COMBAT_API_TIMEOUT_SECONDS = 120` constant
2. **`core/managers/combat_manager.py`** -- Add `timeout=COMBAT_API_TIMEOUT_SECONDS` to the two combat API calls + the initial scene validation call
3. **`core/managers/status_manager.py`** -- Add `StatusTimer` context manager (reusable, same code the router will use later)
4. **`core/managers/combat_manager.py`** -- Wrap blocking API calls in `status_timer()` using existing `status_manager.update_status` callback

**Escalation schedule for combat:**
```
0-10s:   (keep initial message, e.g., "Combat AI processing your action...")
10-30s:  "Still processing, please wait..."
30-60s:  "Response taking longer than usual..."
60-120s: "Waiting for AI provider ({elapsed}s)..."
120s:    httpx.TimeoutException -> caught by retry loop, next attempt
```

**On timeout in combat retry loop:**
- The `httpx.TimeoutException` is caught by the existing `except Exception as e` at line ~3766
- The retry loop increments attempt counter and tries again (up to `max_retries = 5`)
- If all retries timeout, the existing fail-open behavior applies (line ~3763: "Max retries exceeded, using last response")

**Merge path:** When the router migration reaches combat_manager.py (Phase 2 Tier 1), the `timeout=` parameter is removed from direct API calls (router handles it via client-level timeout), and the `status_timer()` wrapping moves to use `llm.call(status_callback=...)` instead.

### Latency Tracking (Deferred)

Add wall-clock timing per call to `_track_usage()`. Useful for identifying slow models or degraded provider performance. Simple addition when needed:

```python
import time
start = time.monotonic()
response = client.chat.completions.create(**api_params)
elapsed = time.monotonic() - start
# Add to stats: _usage_stats["latency_by_task"][task].append(elapsed)
```

### Combat Prompt Optimization for Multi-Model Routing (Deferred)

**Context:** Audit of `prompts/combat/combat_sim_prompt_multipc_compressed.txt` (2026-02-09; model references updated 2026-09-21 for v4 profiles) identified prompt architecture issues that are tolerable on a single large model but cause problems once narration and mechanics split across models. These changes are deferred until the router facade lands.

**Prerequisite:** Prompt issues P1-P5, P7-P8 from the existing build should be fixed first (see AGENTS.md "MultiPCCombatManager Bug Fixes" section for the audit report). The fixes below build on that foundation.

#### P10: Prompt Splitting Strategy for Multi-Model Routing

**Problem:** The combat prompt is monolithic (576 lines, ~3500 tokens). All directives are loaded as `conversation_history[0]` regardless of model. Creative models don't need `@PREROLLS`/`@ATTACK_RESOLUTION` math rules. Mechanical models don't need `@NARRATION_STYLE`/`@FLAVOR` sensory quotas.

**Solution:** Split the prompt template into directive groups that the router selects based on model capability:

| Group | Directives | Tokens | Required By |
|-------|-----------|--------|-------------|
| **Core** (always included) | `@ROLE`, `@SOURCE_OF_TRUTH`, `@OUTPUT_CONTRACT`, `@ROUTING_RULES`, `@ACTIONS`, `@ROUND_RULES`, `@RESPONSE_SCHEMA`, `@VALIDATORS`, `@CRITICAL_CONSTRAINTS`, `@INPUT_CHANNELS`, `@PRIORITY_ORDER`, `@PHASE_MODEL` (new), `@TEXT_FILTER` | ~1500 | ALL models |
| **Narration** (creative models) | `@NARRATION_STYLE`, `@FLAVOR`, `@NARRATION`, `@TURN_CONTROL_ENHANCEMENTS`, `@NAME_POLICY`, `@EDGE_CASES` | ~600 | Narrator tier (`production-2026-09` complex: deepseek-v4-flash-0731) |
| **Mechanics** (mechanical models) | `@PREROLLS`, `@ATTACK_RESOLUTION`, `@SAVE_PAUSE`, `@DEATH_GATE`, `@COMBAT_ACTION_PROTOCOL`, `@PLAYER_DICE`, `@PLAYER_ACTION_RESOLUTION`, `@SPELL_EFFECTS_TRACKING`, `@ROUND_ADVANCEMENT` | ~800 | Utility tier (glm-5.3-flash, qwen3.7-flash) |
| **Multi-PC** (MP-only) | `@SPLIT_PARTY_GUIDANCE`, `@HOLDING`, `@PHASE_MODEL` (new), multi-PC rules from `@ROUND_FLOW`/`@STOP_RULES` | ~400 | All models in MP mode |
| **Examples** (optional priming) | `@MICRO_EXAMPLES`, `@USER_PROMPT_TEMPLATE` | ~800 | Creative models only |

**Implementation approach:**

```python
# prompts/combat/ directory structure:
# combat_core.txt           -- Core directive group (~1500 tokens)
# combat_narration.txt      -- Narration directive group (~600 tokens)
# combat_mechanics.txt      -- Mechanics directive group (~800 tokens)
# combat_multipc.txt        -- Multi-PC directive group (~400 tokens)
# combat_examples.txt       -- Examples directive group (~800 tokens)

# In combat_manager.py prompt loading:
def _build_combat_prompt(is_multipc: bool, model_profile: dict) -> str:
    """Assemble combat prompt from directive groups based on model capability."""
    sections = [read_prompt("combat/combat_core.txt")]
    
    # Model capability determines which groups to include
    if model_profile.get("narration_capable", True):
        sections.append(read_prompt("combat/combat_narration.txt"))
    if model_profile.get("mechanics_capable", True):
        sections.append(read_prompt("combat/combat_mechanics.txt"))
    if is_multipc:
        sections.append(read_prompt("combat/combat_multipc.txt"))
    if model_profile.get("needs_examples", True):
        sections.append(read_prompt("combat/combat_examples.txt"))
    
    return "\n\n".join(sections)
```

**MODEL_PROFILES extension:**

```python
MODEL_PROFILES = {
    "production-2026-09": {
        # ... v4 tiers ...
        "narration_capable": True,    # deepseek-v4-flash-0731 narrates
        "mechanics_capable": True,    # and handles mechanics
        "needs_examples": False,      # follows schema without priming
    },
    "economy": {
        # ... v4 tiers ...
        "narration_capable": False,   # glm-5.3-flash is JSON-focused
        "mechanics_capable": True,    # handles math well
        "needs_examples": True,       # needs format priming
    },
}
```

**Token savings per model tier:**

| Model Tier | Current | After Split | Savings |
|-----------|---------|-------------|---------|
| Narrator profile (full prompt) | ~3500 | ~3500 | 0 (keep all) |
| Narrator-only (no mechanics group) | ~3500 | ~2900 | ~600 |
| Utility-only (no narration/examples) | ~3500 | ~2300 | ~1200 |
| Core only (cheap classification models) | ~3500 | ~1500 | ~2000 |

**Migration path:** Start with the monolithic prompt (current). When the router is implemented and a second model is added, split the file. No code changes needed in the prompt itself -- just file splitting.

#### P5: Active PC Identity Redundancy Tiers

**Problem:** Active PC identity is communicated 7-8 times per turn. Full redundancy costs ~200-300 tokens. Creative models need reinforcement to maintain character consistency. Mechanical models only need the authoritative source.

**Solution:** Two tiers controlled by model profile:

| Tier | Sources Kept | Tokens | For Models |
|------|-------------|--------|------------|
| **Full** (current) | All 7-8 sources | ~300 | Narrator tier (deepseek-v4-flash-0731) |
| **Minimal** | Live Tracker `[>]` + REQUIRED RESPONSE box only | ~80 | Utility tier (glm-5.3-flash, qwen3.7-flash) |

**Implementation:** In `combat_manager.py`, the `multi_pc_context` block (lines 3483-3503) becomes conditional:

```python
if multi_pc_manager:
    if model_profile.get("narration_capable", True):
        # Full context: phase state + party summary + PC override
        multi_pc_context = f"""=== COMBAT PHASE STATE ===
CURRENT_PHASE: {current_phase}
...
{multi_pc_manager.format_party_turn_summary()}
{multi_pc_manager.format_pc_context_for_prompt(active_pc)}"""
    else:
        # Minimal context: phase state only (tracker [>] provides identity)
        multi_pc_context = f"""=== COMBAT PHASE STATE ===
CURRENT_PHASE: {current_phase}
PC_PHASE_COMPLETE: {multi_pc_manager.pc_phase_complete}"""
```

**Prerequisite:** P10 (prompt splitting) should be implemented first so model capabilities are available at prompt assembly time.

#### P11: Plain-Text Alternative for `get_required_response_prompt()`

**Problem:** Box-drawing characters (`╔═╗║╠╣╚╝`) in the REQUIRED RESPONSE prompt work well with the narrator model but may confuse smaller utility models. The characters are not in cp1252 but are safe because they only flow through API JSON, never stdout. However, some models may waste tokens parsing visual structure or fail to extract content from boxes.

**Solution:** Create a `get_required_response_prompt_simple()` method on the facade that uses `@`-directive style:

```python
def get_required_response_prompt_simple(self) -> str:
    """Plain-text version of required response prompt for non-GPT models."""
    if self._turns.pc_phase_complete:
        pending = self.get_remaining_enemies_for_round()
        pc_names = list(self._state.pc_states.keys())
        return f"""@REQUIRED_RESPONSE={{
  phase: "ENEMY_PHASE",
  pc_phase_complete: true,
  resolve_in_order: {pending},
  forbidden_actors: {pc_names},
  rules: [
    "Resolve ALL listed enemies/NPCs in order",
    "NEVER narrate actions for forbidden PCs",
    "Stop after last enemy acts",
    "Return JSON: plan, narration, combat_round, actions"
  ]
}}"""
    # ... PC_PHASE equivalent ...
```

**Selection in combat_manager.py:**

```python
if model_profile.get("prefers_structured_prompts", False):
    required_response = multi_pc_manager.get_required_response_prompt_simple()
else:
    required_response = multi_pc_manager.get_required_response_prompt()
```

**MODEL_PROFILES extension:**

```python
"economy": {
    # ... v4 tiers ...
    "prefers_structured_prompts": True,  # Use @-directive style, not box art
},
```

#### P6/P12: Conditional Examples and Template

**Problem:** `@USER_PROMPT_TEMPLATE` (~400 tokens) and `@MICRO_EXAMPLES` (~400 tokens) serve as few-shot priming for the narrator model but are wasted on models that follow schemas directly.

**Solution:** Move both to the `combat_examples.txt` directive group (see P10). Only loaded when `model_profile.get("needs_examples", True)` is set.

**No implementation changes needed beyond P10's file splitting.**

#### Implementation Checklist (Prompt Optimization)

All items below are deferred until after the router is implemented and a second model is tested:

- [ ] P10: Split `combat_sim_prompt_multipc_compressed.txt` into 5 directive group files
- [ ] P10: Add `narration_capable`, `mechanics_capable`, `needs_examples` fields to MODEL_PROFILES
- [ ] P10: Update combat_manager.py prompt loading to use `_build_combat_prompt()`
- [ ] P5: Add redundancy tier logic to `multi_pc_context` assembly in combat_manager.py
- [ ] P11: Create `get_required_response_prompt_simple()` on MultiPCCombatManager
- [ ] P11: Add `prefers_structured_prompts` field to MODEL_PROFILES
- [ ] P6/P12: Move `@USER_PROMPT_TEMPLATE` and `@MICRO_EXAMPLES` to `combat_examples.txt`
- [ ] Regression test: Full combat session on the `openai/fallback` profile with split prompts (must produce identical behavior to the current build)
- [ ] A/B test: Compare combat quality on the utility tier (glm-5.3-flash) with full prompt vs minimal prompt

---

## Decisions Log

| Decision | Rationale |
|----------|-----------|
| **Thin facade over existing factory** | The factory holds tested provider-selection and fallback infrastructure. The router adds interface + tracking; it doesn't reimplement provider logic. |
| **Task-based routing, not capability-based** | `COMPLEX_TASKS` + `TASK_TEMPERATURES` map 1:1 to call sites. Capability buckets (creative/mechanics/structured) are too coarse — combat is both narrative and mechanical. |
| **Model-agnostic via MODEL_PROFILES v4** | No model lock-in. Tiers define model + params + provider preferences + pricing. Swapping models is a config-only change; unknown profiles get DEFAULT_PROFILE (vanilla behavior, no crash). |
| **COMPLEX_TASKS replaces THINKING_ENABLED_TASKS** | Task complexity is model-agnostic. "Complex" means "needs deeper reasoning" — the profile expresses it (`reasoning.effort` for DeepSeek/GLM, a larger model for OpenAI fallback). |
| **Per-tier provider preferences** | The same model can be 0.38s/111tps or 0.90s/29tps depending on provider and price. Narrator tiers sort by throughput with a latency floor; background tiers sort by price with a ceiling. |
| **`LLM_PROVIDER` not `MULTIPLAYER_MODE`** | Aligns with the single-runtime direction (ADR-0032). Provider selection is independent of party runtime and party size. |
| **`json.loads()` not Pydantic** | Codebase has zero Pydantic usage. Adding a dependency for structured output validation is premature. |
| **Thread-safe stats with `Lock`** | Flask + SocketIO is multi-threaded. Follows pattern from `pc_manager.py` (`_stats_lock`). |
| **Model refresh 2026-09** | Narrator/combat: `deepseek/deepseek-v4-flash-0731` ($0.04/$0.16, 0.38s P50 / 111 tps on fast providers, 29 providers). Utility: `z-ai/glm-5.3-flash` (31 providers). Validation: `deepseek/deepseek-v4.1-flash` pending bake-off. Classification: `qwen/qwen3.7-flash`. Fallback: `gpt-5.6-luna` / `gpt-5.4-nano`. |
| **Model choices are gated by a bake-off, not reputation** | `scripts/benchmark_model_profiles.py` scores candidates on production-shaped prompts for JSON validity, latency, throughput, cache rate, and cost before migration. |
| **Image: Muse primary, Krea 2 Large premium** | `meta/muse-image` at $0.01/image with reference conditioning handles bulk portraits; `krea/krea-2-large` at $0.06/image handles hero art. Image work is async/prewarm-only (41s+ per image) and single-provider models carry availability risk with Krea Medium Turbo as fallback. |
| **Speech: switch to the OpenRouter catalog** | OpenAI TTS models are not available through OpenRouter (verified 2026-09-21). `/api/v1/audio/speech` is OpenAI-shaped, so `create_tts_client()` retargets cleanly; bake off Fish S2.1 Pro / MAI-Voice-2-Flash / Qwen TTS Flash with a human listen before cutover. |
| **Background/Titan posture is price-first** | `background-titan` sorts by price with a `max_price` ceiling; `:floor` is equivalent. Verify per-model batch discounts before using `:batch` for background work (DeepSeek's batch rate is higher than its base rate). |
| **Hybrid profiles are first-class** | Profile tiers can point at different providers (`production-2026-09`: DeepSeek narrator + GLM utility). All models in a profile must be reachable through the same client (OpenRouter). |
| **OpenRouter is the primary mode, OpenAI-direct is the safety net** | Game is designed to run on OpenRouter for model flexibility. OpenAI-direct exists for fallback when OpenRouter is unavailable, not as an equal operating mode. |
| **Toolkit image files excluded from migration** | `npc_generator.py` and `monster_generator.py` use `images.generate()` only — zero chat completions. They belong to the Phase 4 image catalog scope, not router migration. |
| **Cache-aware cost tracking from day one** | DeepSeek cache reads are 60% cheaper than fresh prompt tokens and NEQ resends large system prompts every turn. Flat-rate tracking would overstate session cost. |
| **Router keeps its own session stats** | Router stats are per-session and thread-safe. Image-cost events continue to use `utils/llm_usage_tracker.py` (the DALL-E instrumentation pattern); the two are not merged. |
| **JSON retry kept in Phase 1** | LLM output is non-deterministic — retrying the same call may produce valid JSON when the first didn't. The retry makes a fresh API call each iteration, not a no-op replay. |
| **Fix factory `extra_body` before router** | Inconsistent shapes between TIER 1 and TASK_OVERRIDES paths would cause TypeError on OpenRouter. Must normalize before router can consume it. Blocker for Phase 1. |
| **Combat migration follows decomposition (2026-09-21)** | `combat_manager.py` Tier 1 migration runs after `combat-manager-decomposition` so the 9 call sites become named stage calls; the interleave is recorded in the combat plan section 3.1. |
| **Combat timeout delegation (2026-09-21)** | Combat's per-call timeout work is superseded by this plan's Phase 0 client-level `httpx.Timeout`; the combat plan verifies coverage instead of adding parallel per-call args. |
| **`retry_tier` is a first-class `call()` parameter** | Combat's validation-failure reasoning escalation must survive migration; `retry_tier` is consumed by `finalize_chat_params()` and never left in passthrough kwargs (the SDK would reject it). |
| **Deferred until TT build ships** | Testers waiting for OpenAI-based Tabletop Mode fork. OpenRouter migration is a post-ship enhancement, not a blocker. |
| **Decisions primitive is separate from chat task-routing** | Jev is `text->decisions`: no chat client, no `MODEL_PROFILES` entry (no sampling params), no temperature. Adding it as a `task` would break the router's task-routing contract, so `llm.decide()` is a sibling primitive. |
| **Jev is never authority; upstream failure is never a negative answer** | Typed answers are consumed by Python. Jev never mutates state, and its fallback is the existing chat/deterministic path, not another Jev model. A 429/503/timeout returns `unavailable` so the caller falls back rather than treating failure as "false". |
| **`action_predictor.py` migrates once** | It is a `llm.decide` target, not an `llm.call` target, so the router migration table and Jev promotion cannot migrate the same call site twice. |
| **Jev action-predictor promotion is gated on measured agreement, not availability** | Phase 0 measured 0.677/0.704 agreement (FAIL vs 0.95 target, FN rate 23-29% vs 5% target). The primitive is deferred pending atomic question decomposition; do not create `jev-decisions-primitive` on capability novelty alone. |
| **Agent instructions may live in `AGENTS.md`; implementation detail belongs in this plan** | The Jev workstream detail, eval results, and utils surface stay here so the always-loaded agent guide does not grow with project history. |

---

## Session Start Prompt

**For implementation session:**

"Implement Phase 0 + Phase 1 of the LLM Router from /plans/version-2/openrouter_llm_router_architecture.md (v4.0).

Phase 0 (config & factory prep):
- Add MODEL_PROFILES v4, DEFAULT_PROFILE, and ACTIVE_PROFILE to model_config.py (see Model Agnosticism section for the five confirmed profiles: production-2026-09, validation-split, economy, background-titan, openai/fallback)
- Rename THINKING_ENABLED_TASKS to COMPLEX_TASKS (keep alias: THINKING_ENABLED_TASKS = COMPLEX_TASKS for backward compat)
- Mark OPENROUTER_STRATEGY, OPENROUTER_FULL_MODEL, OPENROUTER_MINI_MODEL, OPENROUTER_CHAT_MODEL as deprecated in comments
- Fix extra_body shape inconsistency in ai_client_factory.py get_model_config() (normalize to {"extra_body": {...}} shape)
- Add finalize_chat_params(model, params, temperature, is_openrouter) for GPT-5 temperature policy
- Delete zero-consumer functions: get_model_for_task, is_thinking_enabled, get_task_complexity
- Verify reasoning-effort param shape and provider-preference acceptance against live OpenRouter calls; record results
- Verify the 39 factory-consuming production files still compile

Phase 1 (router):
- Create utils/llm_router.py per the Phase 1 reference code block
- LLMRouter with call(), decide() stub, cache-aware thread-safe stats
- _resolve() / _resolve_fallback() resolve v4 profile tiers (model + params + provider + price)
- Provider preferences passed as the OpenRouter `provider` request field
- On fallback: switch to the openai/fallback profile (model + params change together, no temperature)
- JSON retry logic (3 attempts, strip markdown fences)
- Error classification: GameLLMError for quota, retry+fallback for transient
- Module-level singleton: llm = LLMRouter()

Also build scripts/benchmark_model_profiles.py (provider-free by default, --live for real calls) and run the bake-off gate: production-2026-09 narrator/combat must match or beat the gpt-5.6-luna baseline on JSON validity at lower cost.

Write unit tests in scripts/test_llm_router.py for: error classification, JSON parsing, cache-aware stats, profile-tier resolution (known/unknown/background ceiling/TASK_OVERRIDES), finalize_chat_params GPT-5 policy, and the decide() stub.

Use the Phase 1 code block in the plan as the implementation reference.

Do NOT migrate any consumer files yet.

Jev decisions: do NOT implement in this session. `utils/action_predictor.py` must not be migrated to `llm.call`; it is reserved for `llm.decide` once the decomposition gate passes. See 'Jev Decisions Integration (Workstreams A/B/C)'."

---

**Last Updated:** 2026-09-21
**Status:** PLANNING - v4.0 model refresh complete; Phase 0/1 ready once the workspace baseline is clean (Jev decisions primitive remains gated by the decomposition eval). Interleaved with the combat manager refactor per the 2026-09-21 note above.
**Revision:** v4.1 - 2026-09-21 combat interlock amendment: interleaved execution order with `combat-manager-refactor.md`, `combat_manager.py` Tier 1 sequencing, combat timeout delegation to the client-level `httpx.Timeout`, and the `retry_tier` escalation channel in `finalize_chat_params()` / `call()`. v4.0 - September 2026 model refresh: five OpenRouter API surfaces documented; `MODEL_PROFILES` v4 with per-tier provider preferences, reasoning effort, and cache-aware pricing; confirmed production models (DeepSeek/GLM/Qwen); image and speech catalog plans (Muse/Krea, OpenRouter speech bake-off); refreshed production audit (107 call sites / 57 files, 54 files to migrate); bake-off harness added to Phase 0/1; Jev sections preserved and gated
