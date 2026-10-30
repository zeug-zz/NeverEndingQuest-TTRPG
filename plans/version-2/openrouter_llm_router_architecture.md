# OpenRouter LLM Router Architecture Plan

Version: 5.0 - Auto routing and accelerated build handoff
Updated: 2026-10-13
Status: READY FOR IMPLEMENTATION via `openspec/changes/llm-router-facade`

## 1. Objective And Authority

Centralize production chat behind `llm.call()` with configurable model profiles,
bounded provider recovery, JSON retry, and accurate usage accounting. Narrator,
combat, and Titan default to `openrouter/auto` so downstream model selection is
maintained by OpenRouter rather than a fixed local model roster.

`AGENTS.md` governs repository constraints. Active OpenSpec artifacts govern their
change scope. `plans/combat-openrouter-alignment.md` owns the eight-change execution
sequence; `plans/version-2/combat-manager-refactor.md` owns combat architecture and
latency targets. This plan replaces the obsolete v4 fixed-model examples and
reference implementation; implement the current contracts, not historical snippets.

### Owner Decisions (2026-10-13)

- Preferred direct-OpenAI chat model: `gpt-6-luna`, configurable through
  `OPENAI_FALLBACK_MODEL`. `gpt-5.4-nano` is deprecated and MUST NOT be introduced.
- Narrator, combat, and Titan targets: configurable `openrouter/auto` defaults,
  independently overrideable per task. No periodic local model-catalog updates.
- Live bake-off: accepted as successfully completed by owner attestation.
  No report or numerical measurements were supplied; do not fabricate them.
- Complete the eight-change sequence through `llm-router-cleanup`. Preserve the
  combat decomposition/migration interleave and move directly to the next change
  after its required checks pass.
- Images/audio remain separately configurable follow-on work. Candidate choices
  are made from current catalogs when that work is implemented, not pinned here.

## 2. Starting State And Completed Evidence

The inspected runtime still uses `LLM_PROVIDER = "openai"` and active chat model
assignments to `gpt-5.6-luna`. `utils/ai_client_factory.py` exists;
`utils/llm_router.py` does not. Factory helpers already provide provider detection,
fallback notification, and task-specific GPT-5 parameter policy. One OpenRouter
strategy path still returns a flat `thinking` mapping incompatible with SDK kwargs.

The September 2026 inventory counted 107 production chat sites across 57 files;
these are planning estimates, not acceptance thresholds. Re-inventory production
calls when authoring migration artifacts, excluding test/tooling calls. Some files
mix chat and image work, so classify by operation, not just filename.

`combat-latency-baseline` is completed and archived at
`openspec/changes/archive/2026-09-22-combat-latency-baseline/`. Its design records
G1 satisfied and targets ratified. Preserve that original OpenAI/model-labelled
evidence. The approved `gpt-6-luna` refresh changes model identity: capture a current
pre-optimization reference inside the hot-path change before same-model latency
comparisons. This is not a new prerequisite change or a repeated candidate bake-off.

Live candidate acceptance is PASS by the 2026-10-13 owner instruction, "Consider
live bake-off completed successfully." G2 implementation checks are still pending.

## 3. Architecture And Ownership (MUST)

```text
production caller
    |
    v
utils/llm_router.py          task/profile selection, bounded retries, stats
    |
    v
utils/ai_client_factory.py   clients, task-aware parameter finalization, timeouts
    |
    v
model_config.py             profiles, defaults, task overrides, policy data
```

- Router MUST NOT build provider clients or mutate gameplay/persistence state.
- Factory MUST own provider-specific request shape and reasoning/sampling policy.
- Config MUST remain data. Model changes MUST require config edits only.
- Python remains mechanical authority; prompts and action contracts remain intact.
- A 1-PC party is the regression floor; multi-PC coverage remains required at
  shared runtime integration points. No new party-size or mode gates.
- `llm.decide()` remains an unavailable stub. No Jev runtime promotion is part of
  this build. The existing action predictor migrates as ordinary chat instead.

Simplest alternative considered: extend the factory into an all-purpose router.
Rejected because client/parameter ownership and retry/accounting orchestration
would become conflated. A thin facade retains the existing tested factory seam.

## 4. Config Contract

Three profiles are sufficient: `production-auto`, `titan-auto`, `openai/fallback`.
Each carries complex/simple tiers with `model`, `params`, `provider`, and
`price_per_1k`. Optional capability hints do not claim a universal context size
or guaranteed structured-output support across every downstream Auto model.

Illustrative defaults (implementation belongs to the facade change):

```python
OPENAI_FALLBACK_MODEL = "gpt-6-luna"
ACTIVE_PROFILE = "production-auto"

# Each profile has both complex and simple tiers.
# production-auto / titan-auto tier defaults:
# {"model": "openrouter/auto", "params": {}, "provider": {}, "price_per_1k": {}}
# openai/fallback tier defaults:
# {"model": OPENAI_FALLBACK_MODEL, "params": {}, "provider": {}, "price_per_1k": {}}

TASK_OVERRIDES = {
    "titan_cycle": {"profile": "titan-auto"},
}
# dm_main / combat_main inherit production-auto and can be overridden separately.
```

MUST:

1. `DEFAULT_PROFILE` is concrete `production-auto`, not a model-less profile.
2. Unknown/missing OpenRouter profile or model resolves to `openrouter/auto`.
   A profile key is never used as a model ID.
3. On OpenRouter, explicit task model override wins; otherwise task profile wins;
   otherwise active profile wins. Explicit models do not inherit another model's
   profile params or static price estimate.
4. Direct OpenAI and automatic fallback always resolve `openai/fallback` and
   `OPENAI_FALLBACK_MODEL`; OpenRouter overrides do not redirect that client.
5. Rename `THINKING_ENABLED_TASKS` to `COMPLEX_TASKS`, keeping the alias until
   cleanup. Complexity classifies tasks, not support for model-specific features.
6. Optional Auto policy is profile data, using documented `auto-router` plugin
   settings under `extra_body.plugins`. Defaults have no fixed allowed-model list
   or unrequested price ceiling. Provider preferences are also optional config.
7. Default Auto calls receive no direct-OpenAI `reasoning_effort`/`verbosity` or
   legacy Kimi `thinking` fields. Portable settings are opt-in profile params.
8. Titan routing configuration provisions a task seam; it does not implement Titan
   scheduling, EGO/RATIO, or a new background runtime.

OpenRouter Auto chooses the downstream model. It does not guarantee the cheapest
possible model or a fixed provider; observe the returned model and actual cost.

## 5. Factory And Facade Contracts

```python
llm.call(task, messages, json_output=False, temperature=None,
         max_tokens=None, retry_tier=None, **kwargs)

finalize_chat_params(model, params=None, temperature=None,
                     is_openrouter=False, retry_tier=None, *, task_id)
```

- `task_id` and `retry_tier` are internal inputs, never SDK kwargs.
- Text calls return assistant text. JSON calls return a dictionary; malformed or
  non-object JSON receives at most three fresh attempts, then `LLMJSONError`.
- The factory merges OpenRouter reasoning/provider/plugins under SDK-compatible
  `extra_body`; legacy factory paths must never emit top-level `thinking`.
- The factory retains legacy GPT-5 behavior and explicitly supports `gpt-6-luna`
  with existing task-family reasoning/verbosity policy. Narrator/combat, validation,
  compression, and summaries retain their distinct policy; direct-OpenAI retry
  escalation still honors high reasoning. Legacy sampling controls are omitted by
  default for the supported reasoning families. Live activation verifies accepted
  request shape; do not infer compatibility merely from a model prefix.
- Both chat clients use `httpx.Timeout(120, connect=10)` through shared config.
  No new dependency; no competing per-call timeout path after migration.
- Quota/billing exhaustion raises `GameLLMError`; transient failures get at most one
  direct-OpenAI fallback per call; fallback exhaustion/unclassified errors raise.
- Existing legacy helpers remain importable during migration. Same-task/same-model
  policy stays compatible; `gpt-6-luna` config refresh and timeout ownership are
  intentional changes, not claimed to be behavior-neutral.
- Facade phase refreshes active OpenAI chat assignments in `model_config.py` only;
  it does not migrate consumers or activate OpenRouter.

## 6. Usage And Observability

MUST:

- Record requested model and resolved `response.model` separately. Aggregate
  `by_model` under the actual downstream model, or explicit unknown-model bucket.
- Prefer finite non-negative response `usage.cost` in USD, including actual zero.
  Never also add a static estimate for the same response.
- If actual cost is absent, use only configured verified rates and label the
  result estimated. Cache-read tokens have their own rate when supplied.
- With neither cost nor rates, preserve token counts, increase `unpriced_calls`,
  set `cost_complete=False`, and describe totals as known-cost subtotals.
- Use a lock for stats updates/reads/reset; snapshots do not expose mutable state.
- Stats include prompt/cached/completion tokens, calls/errors/fallbacks, cost, and
  task/model breakdowns. Missing usage does not fail narration or mutation work.
- Later migration instruments each successful chat response exactly once. Cleanup
  reconciles router `/usage` with existing Debug session/week rollups; image/audio
  cost events continue through their current tracker without double counting.
- No new per-call pricing lookup HTTP request is needed: response cost is preferred,
  and absent prices are explicit. Credential values are never logged.

## 7. Benchmark And Acceptance

The facade still ships `scripts/benchmark_model_profiles.py` for repeatable future
comparisons. Default execution is provider-free with fake transport, labelled
synthetic. Fixtures cover narrator world/DM-note input, combat validation,
encounter updates, and summary compression. Report JSON validity, latency p50/p90,
throughput, token/cache usage, resolved model, and cost completeness.

`--live` is explicit opt-in, never CI/default execution. Future comparisons use
the configured Auto profile and preferred OpenAI reference. Missing provider config
fails clearly; fake metrics are not live evidence.

Candidate selection is already owner-attested PASS; a repeated live bake-off MUST
NOT block this rollout. G2 still requires implementation tests, factory compatibility
checks, and a working provider-free harness. G9 still requires actual live 1-PC and
multi-PC integration smoke, model/cost observation, and rollback verification.

Required gameplay captures are primary-orchestrator phase gates, not builder
completion claims. Follow the gate-specific G3/G4/G5/G7/G9/G10 matrix and evidence
contract in `plans/combat-openrouter-alignment.md` and the Capture_Arena skill.
Use a real sandbox copy on port 8360 and unique per-gate/run bundles under
`tmp/router-rollout/`; inspect transcript, trace, relevant persisted state and
expected/observed checks before teardown. Exit zero or degraded required evidence
does not establish PASS. Missing coverage/transport leaves the gate incomplete.
G9 captures MUST observe requested versus resolved models, actual provider/fallback,
cost provenance/completeness and live preferred-model rollback; fake Titan task
transport is distinct from those live narrator/combat checks. G10 includes `/usage`,
Debug session/week accounting and save/restart/resume. A paused rollout remains
paused during a separately requested guideline/artifact update.

## 8. Migration And Eight-Change Sequence

The completed G1 baseline is reused. The remaining required sequence is:

| Build | OpenSpec change | Exit gate |
|---|---|---|
| 1 | `llm-router-facade` | G2 implementation checks; live candidate acceptance already PASS |
| 2 | `combat-manager-decomposition` | G3 structure/shim/prompt parity and party smoke |
| 3 | `llm-router-core-migration` | G4 core routing, task policy, timeout/retry parity |
| 4 | `combat-latency-hot-path` | G5 comparable current-model latency/call budgets |
| 5 | `llm-router-remaining-callsite-migration` | G6 all remaining production chat routed |
| 6 | `combat-turn-commit-and-receipts` | G7 crash/restart idempotence |
| 7 | `llm-router-openrouter-activation` | G9 live Auto integration, accounting, rollback |
| 8 | `llm-router-cleanup` | G10 deprecated plumbing removed, usage/docs/session verified |

Artifacts for builds 2-8 are authored via OpenSpec before their implementation,
using the coordination plan's outlines and the settled owner decisions. Existing
facade artifacts are revised, not duplicated. After verification, record evidence
and proceed without an unnecessary new discovery/approval cycle. Real blockers
and changes outside this approved scope must still be reported.

The owning change MUST include its matrix coverage and any bounded rig extension
tasks before its implementation. G3 supplies named scenario/evidence prerequisites
through the existing seeder/driver/helpers; later changes reuse them and add only
their own required observations. Live verdicts and paths are recorded in OpenSpec
and the overall goal plan before a required predecessor gate is considered complete.

G3's separately approved validation-context correction is limited to distinguishing
committed Python state from proposed candidate changes/operations and the strictly
necessary explanatory validation instructions. Candidate-derived `touchedChanges`
or candidate `ALREADY_APPLIED` claims are not proof; independently established
genuine prior applied events remain trusted. This is the sole narrow dynamic-
context parity exception: unrelated prompt/context bytes and extraction parity
remain mandatory. It does not implement G7 or change the eight-change sequence or
gates; the owning decomposition OpenSpec artifacts define its guarded tests and
the required primary reruns.

Combat decomposition MUST precede combat migration. Compression-engine migration
MUST follow its hot-path rework. Build 5 and build 6 can overlap only on independent
files under orchestrator ownership; overlapping implementation stays serialized.

### Production Inventory For Migration

- Core: post-decomposition combat stages, `main.py`, `core/ai/action_handler.py`.
- Existing factory consumers: summaries, transition validation, startup interviews,
  web chat, compression, plot/encounter/character updates.
- Generation: module/area/location/plot/NPC/monster builders and stitcher.
- Memory: session diary, players diary, story compiler.
- Toolkit/utilities: normalization/adaptation/audit/reconciliation/classification,
  Homebrewery prose, level-up, validation, prompts, inventory/spatial helpers.
- `utils/action_predictor.py`: migrate its current boolean-returning chat path to
  `llm.call(task="action_prediction", ...)` in build 5. Preserve its existing
  fail-open behavior; do not implement Jev or change predictor semantics.
- Mixed image services: migrate any chat/prompt-generation operations found by
  the inventory, leaving `images.generate` and speech operations separate.
- Exclude `scripts/**`/`openspec/**` provider fixtures and provider infrastructure
  itself. Test exclusions must not conceal production direct chat clients.

G6 completion requires a production operation inventory with no bypassing chat
clients or raw `.chat.completions.create` calls outside router/transport-owned
infrastructure. Remove unused backup validators rather than migrating dead code,
after confirming no references. Existing source-contract tests must be repointed
to named stages without weakening their behavioral assertions.

## 9. Cleanup And Completion

Cleanup removes deprecated selection constants, the `THINKING_ENABLED_TASKS` alias,
unused factory helpers after the import inventory proves them unreferenced, retired
migration tooling, and stale imports. Retain client construction, actual-provider
detection, parameter finalization, and fallback notification ownership.

Add `/usage` and reconcile displayed cost completeness/provenance with session/week
telemetry. Refresh AGENTS/operational documentation only for durable new behavior.
Verify OpenSpec changes/specs, full 1-PC and multi-PC session behavior, save/resume
receipts, configured Auto defaults, direct `gpt-6-luna` fallback, and rollback.

No automatic commit, push, archive, or destructive Git action belongs to this goal.
Archiving/spec sync can be performed separately when explicitly requested; later
change authoring may use verified predecessor deltas without requiring an archive.

## 10. Follow-On Scope

### Image And Audio

Separate follow-on OpenSpec work will configure image/audio providers and models
independently of chat. Select capable low-cost open-source candidates from the
current OpenRouter catalogs at implementation time. Verify image input/output,
portrait/reference support, audio format/voices, latency, and actual cost before
cutover. Do not embed a stale candidate roster, historical price list, or unverified
endpoint contract in this chat plan. Browser TTS remains its existing separate path.

### Jev, Titan Runtime, And Other Deferred Work

Jev remains gated by its existing decomposition evaluation and owner authorization;
its failed historical agreement/FN results are not superseded by the chat bake-off.
`llm.decide()` remains unavailable through cleanup. Ordinary chat migration includes
the action predictor, so Jev is no longer a dependency of complete chat routing.

Titan task configuration is included; new Titan scheduling/runtime and EGO/RATIO
implementation are not. Video, async redesign, and single-runtime flag removal are
separate initiatives. `combat-typed-resolver-expansion` remains optional and is not
part of the required eight-change goal.

## 11. Documentation References

OpenRouter documentation checked 2026-10-13 through Context7 `/openrouterteam/docs`:

- Auto Router: https://openrouter.ai/docs/guides/routing/routers/auto-router
- Usage Accounting: https://openrouter.ai/docs/guides/guides/usage-accounting

Auto is a virtual model slug; optional settings use plugin ID `auto-router`.
The response model reveals the actual selection and usage includes cost fields.
Refresh external API documentation during implementation where request syntax is
needed. Model preference/deprecation in this plan is the owner's decision, not an
independent claim that the planning agent tested those models.
