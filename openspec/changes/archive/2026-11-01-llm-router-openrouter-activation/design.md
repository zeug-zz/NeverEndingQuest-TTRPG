# Design

## Context

The shared router and production chat call-site migrations are in place; Build 7 activates the already-selected OpenRouter Auto posture. G7 is a hard predecessor: the current primary verdict is BLOCKED on network access, so this design separates provider-free implementation and capture-tool work from the later production-default flip and live G9 execution.

## Goals / Non-Goals

### Goals

- Reuse the shared factory/router, task profile configuration, and Capture_Arena pipeline as the implementation seams.
- Make response-derived model/provider/cost provenance auditable without changing session/week UI accounting owned by Build 8.
- Ensure every G9 live row can be tied to a unique run identity and actual sandbox artifacts, while leaving the verdict to the primary.

### Non-Goals

- No second router, capture runner, cost ledger, Titan runtime, or production feature-flag system.
- No image/audio selection, Jev promotion, mode-flag removal, or UI usage-accounting merge.

## Decisions

### 1. Keep activation in existing configuration and routing seams

After the primary records G7 PASS, set `LLM_PROVIDER` to `openrouter` and `ACTIVE_PROFILE` to `production-auto` in the existing runtime configuration. Retain independent profile selection for `dm_main`, `combat_main`, and `titan_cycle`; do not make Titan configuration create an application call path or scheduler. Before G7 PASS, the checked-in production posture remains unchanged.

The simplest alternative, changing only a shared provider default and allowing tasks to inherit one profile, is rejected because it couples narrator, combat, and Titan selection and obscures the explicit rollback posture.

### 2. Make task-family sampling explicit and factory-owned

Add a `TASK_POLICY_SAMPLING` map keyed by every production facade task identifier, including dependency-injected task constants. Each task declares a reasoning-family policy and a non-reasoning-family policy. The reasoning entry identifies the family and leaves `temperature`/`top_p` absent; the non-reasoning entry contains an explicit numeric `temperature` and may define `top_p` only when the task has an explicit retained value. Factory finalization omits sampling controls for a known reasoning model and applies the task's non-reasoning values otherwise; `openrouter/auto` uses the latter because its downstream family is unknown before transport. Missing or malformed task policy is a configuration error before client construction or transport, not a global-default lookup.

Policy source and precedence: use the existing `TASK_TEMPERATURES` value when a task has one. For other tasks, use the most common effective pre-G6 caller temperature, resolving old factory defaults first and choosing the lower value on a tie. Keep task policy authoritative over request-level temperature/top-p kwargs; this deliberately accepts the pre-existing caller deltas below instead of allowing one facade task to emit different Auto sampling by call site. The selected non-reasoning temperatures are:

| Temperature | Tasks |
| --- | --- |
| `0.0` | `npc_name_canonicalizer` |
| `0.1` | `character_validator`, `dm_validation`, `location_compression`, `npc_builder`, `storage_processor` |
| `0.3` | `combat_validation`, `compression`, `parse_module_params`, `prompt_sanitizer`, `validation` |
| `0.4` | `dm_mini` |
| `0.6` | `update_plot_hooks` |
| `0.7` | `action_prediction`, `builders`, `combat_main`, `dm_main`, `encounter_update`, `level_up`, `location_generator`, `module_generator`, `monster_builder`, `plot_generator`, `plot_update`, `safety_review`, `toolkit_adaptation_author`, `toolkit_adaptation_convergence`, `toolkit_adaptation_semantic_auditor`, `toolkit_final_reconciliation`, `travel_narration`, `unify_plots`, `updates` |
| `0.8` | `adventure_summary`, `combat_summary`, `generate_area_description`, `generate_area_name`, `generate_thematic_names`, `location_generator_batch`, `location_summarizer`, `summaries` |

The accepted pre-G6 per-caller deltas are: `dm_main` (`0.8` versus its `TASK_TEMPERATURES` value `0.7`); `summaries` (`0.6`, `0.3`, and `0.7` versus its factory value `0.8`); `updates` (`0.3` and `0.2` versus its factory value `0.7`); `dm_mini` (`0.8` and `0.7` versus the selected `0.4`); `compression` (`0.1` at a narrative-compression caller versus the required `0.3`); `dm_validation` (`0.2` versus its factory value `0.1`); `plot_generator` (`0.8` versus the selected `0.7`); and `npc_builder` (`0.7` versus the selected `0.1`, the lower of the tied caller values). For `compression`, retain `top_p = 1.0`, the only pre-G6 task caller value; omit `top_p` for every other non-reasoning task. Keep existing task-specific reasoning effort/verbosity behavior unchanged. Tests derive coverage from production facade call sites so a newly added task cannot bypass policy review.

The simplest alternative, reusing `TASK_TEMPERATURES` or applying one global sampling pair, is rejected because neither expresses reasoning-family omission and per-task Auto behavior together.

### 3. Reuse the existing bounded fallback and direct client

Classified transient OpenRouter transport errors use the existing single-fallback tier to direct OpenAI `gpt-6-luna`. The direct request is finalized by the existing factory path and excludes OpenRouter preferences, plugins, and other provider-specific fields. Quota and billing failures remain terminal. Provider-free tests inject fake clients and assert both attempt count and outgoing request shape.

The simplest alternative, retrying Auto or adding a second fallback tier, is rejected because it can repeat the same transport failure and exceed the approved recovery bound.

### 4. Extend router-local accounting; do not merge UI ledgers

Use the existing router response/usage observation seam to retain requested model, response-resolved model, transport provider, response-reported upstream provider when available, usage completeness, cost amount, cost provenance, and cost completeness. A finite non-negative provider-reported cost (including zero) is actual and is counted once. Estimate only when a concrete resolved model has a verified configured rate; otherwise record the response as unpriced and incomplete while retaining known token and cost subtotals. Never estimate against `openrouter/auto` or borrow a different model's rate.

Keep these observations in the existing router statistics/receipts. Do not fold them into session/week UI totals in this build; that reconciliation belongs to Build 8. The simplest alternative, a blended Auto price estimate, is rejected because the selected model is not known before response and the estimate would hide incomplete cost coverage.

### 5. Extend the existing Capture_Arena tooling for G9

Add G9 profiles to the existing fixture registry and extend `scripts/seed_combat_capture.py`, `scripts/capture_drive.py`, `scripts/capture_evidence.py`, and their focused provider-free tests. Do not add another driver. The fixed live row keys are:

- `narrator-auto:p1`, `narrator-auto:p4`
- `combat-auto:p1`, `combat-auto:p4`
- `transport-failure:p1`, `transport-failure:p4`
- `preferred-openai-rollback:p1`, `preferred-openai-rollback:p4`

Every row has a unique run directory under `tmp/router-rollout/g9/<run-id>/`. The response receipt and run manifest bind the row to party/seed identity, worktree/model configuration, actual response model/provider observations, and reported/estimated/unpriced cost completeness. The failure rows retain evidence of the injected OpenRouter transport failure and the single direct `gpt-6-luna` response. Rollback rows record the operator posture change, exactly one restart, and the subsequent direct `gpt-6-luna` response.

The evaluator checks row inventory, identity consistency, live response receipts, transcripts, owned-server logs, and the state artifacts required by each scenario. Missing response-derived facts stay unknown; fake-transport results are labeled non-live. The evaluator may report only `READY_FOR_PRIMARY_REVIEW`, never a G9 verdict. The simplest alternative, treating provider-free fixtures or process exit status as a live pass, is rejected because the G9 contract requires primary-reviewed provider-backed evidence.

### 6. Separate software readiness from the G7-gated activation

Sampling/accounting implementation, provider-free tests, and G9 tooling can be prepared while G7 is blocked, provided production defaults are not flipped and no live G9 server is started. The production default change and primary-owned live matrix follow a recorded G7 PASS. Use the existing isolated capture procedure: real copy at `tmp/combat_capture/`, port 8360, repository virtual environment, `NEQ_OPEN_BROWSER=0`, and evidence preservation before teardown. Rollout-only flags remain off outside that sandbox. No live Titan capture is performed.

The simplest alternative, running G9 opportunistically while G7 is blocked, is rejected because the Build 7 order and primary-owned gate contract prohibit bypassing the predecessor.

### Auto empty-content recovery and total request deadline (G9 corrections)

Evidence: G9 diagnostics g9diag-r3/r4/r7 and
`tmp/router-rollout/g9/adv-summary-diag-r1.log`. `openrouter/auto` resolved to reasoning models
that returned `finish_reason=stop` with `content=null` (output only in reasoning). Only `dm_main`
opts into empty-transient recovery, so other callers (for example `adventure_summary`) received
`None` and failed. Separately, non-streaming OpenRouter bodies deliver keep-alive chunks, so the
httpx per-operation read timeout never fires; `API_TIMEOUT_SECONDS` (documented as the total request
timeout) did not bound wall time, and startup and location transitions waited beyond the capture
caps.

MUST (A): When the resolved request model is `openrouter/auto`, the router applies the existing
bounded empty-transient recovery by default (`EMPTY_RESPONSE_RETRY_LIMIT=2`) to every task,
including `json_output=True`, with the same per-provider bound, one fallback transition, and
six-SDK-invocation cap per facade call (JSON retries included in that cap). An explicit
`empty_retry_limit` still overrides. Exhaustion raises `EmptyProviderResponseError`; the router
never returns `None` content to a caller. The direct-OpenAI posture keeps the core-migration default
(off unless opted in). Every response is still counted and observed once.

MUST (B): The factory owns a total wall-clock deadline per SDK attempt equal to
`API_TIMEOUT_SECONDS`, enforced at the HTTP transport so keep-alive body chunks cannot extend it.
Exceeding it raises a timeout transport error that follows the existing bounded transient-fallback
policy. Callers add no parallel per-call bounds.

Simplest alternative considered: patch each caller to tolerate `None` and add subprocess timeouts.
Rejected because Auto can return empty content for any task, so per-caller patches leave the facade
contract unsafe and the wall-time bug unfixed.

MUST (C): `llm.call` SHALL accept a keyword-only `json_contract: bool = False` signal. When true,
and the current attempt profile resolves to `openrouter/auto`, the router SHALL add
`response_format={"type":"json_object"}` unless the caller already supplied `response_format`.
The router SHALL return the raw response string; callers retain their parsing, validation, and
semantic retry bounds. `json_contract=False` requests and direct-OpenAI attempts, including an
Auto-to-direct fallback, SHALL receive no router-added JSON format. This JSON-contract change does
not alter prompt bytes, the prior Auto cost-tier behavior, or the model pool; the narrow
validator-only cost-tier exception is recorded below. A non-boolean `json_contract` value is
rejected before transport.

Evidence: G9 run `g9m5 narrator-auto:p1` observed Auto JSON-contract calls returning non-JSON prose
or incomplete JSON while callers parsed the raw strings; the current task IDs are shared with prose
callers (for example `dm_main` transition narration and `adventure_summary` prose summaries).

Simplest alternative considered: a task-ID JSON allowlist. Rejected because the inventory shows
`dm_main` has JSON callers (`main.py:5295`, `core/ai/transition_validator.py:170`) and prose callers
(`core/ai/action_handler.py:2315`, `utils/startup_wizard.py:1752`); `dm_validation` has JSON callers
(`main.py:2921`, `core/ai/action_handler.py:1178`) and prose callers (`core/managers/level_up_manager.py:255`,
`utils/npc_reconciler.py:81`); `adventure_summary` shares the JSON location update at
`core/ai/adv_summary.py:237` with prose summary calls at `core/ai/adv_summary.py:468` and
`core/ai/cumulative_summary.py:315,581`; and `combat_main` is shared by JSON combat turns and
prose initiative/enemy-narration callers. A task-ID rule would enable JSON mode for prose requests.

### Task 1.7 baseline: Validator requests use the Auto Router medium cost tier

Task 1.7's completed baseline kept `openrouter/auto`, the model pool, fallback model, and all
non-validator request settings unchanged. Under that baseline, configured validator tasks received
the OpenRouter `auto-router` plugin with `cost_tier: "medium"` only when the request model was
exactly `openrouter/auto`; every other task kept the implicit default (no cost setting, equivalent
to the low band), and direct-OpenAI requests including fallbacks received no plugin. The medium
tier is a routing band, not a model or price ceiling, and was selected after G9 observed
`dm_validation` receive narrator-shaped JSON twice in the default low band.

The production response-validator task IDs are `dm_validation`, `combat_validation`, `validation`,
`character_validator`, `safety_review`, and `toolkit_adaptation_semantic_auditor`. Do not classify
`transition_agent` as a router task: transition validation calls the shared `dm_main` task, which
also serves narration; Task 1.7 kept `dm_main` on the default tier, a baseline superseded by
the approved `dm_main` Auto extension below. The final reconciliation/editor, prompt sanitizer,
and generation tasks are not response validators.

Validate configured tier values against OpenRouter's supported values (`low`, `medium`, `high`,
`xhigh`, `max`) before client construction or transport. Merge the generated plugin with existing
profile/request plugins without duplicating `auto-router`; when the caller already supplied an
`auto-router` plugin, preserve that caller-owned entry. Do not pin models, add allowed/excluded model
lists, use the beta router plugin, or change the fallback model. The simplest alternative, applying
medium globally or pinning a known validator model, is rejected because it changes unrelated task
routing or freezes Auto's model selection.

Task 1.7 verified this original validator-only policy: `dm_main` was treated as a non-validator and
kept the implicit default tier. The approved extension below supersedes that default for all
`dm_main` requests using `openrouter/auto`, including JSON-contract narrator calls; it does not
revise Task 1.7's completed validation evidence or the configured response-validator task inventory.

### Approved extension: all `dm_main` Auto requests

Keep the configured response-validator tasks on the existing `medium` Auto Router cost tier. In
addition, every request using task `dm_main` SHALL use that same tier when its request model is
exactly `openrouter/auto`, including both prose narration and `json_contract=True` narrator calls.
Do not gate this task-level tier on `json_contract`, response format, or prose/JSON mode. Task
1.6's call-site evidence identifies JSON-contract `dm_main` callers, so those calls are included.
Other non-validator task IDs retain the implicit default tier.

This is only a cost-tier selection change: retain `openrouter/auto`, the existing model pool,
validator configuration, and plugin-merge behavior. Direct-OpenAI requests and the existing
OpenRouter-to-direct fallback continue to omit generated Auto Router plugins and provider-specific
settings. Do not change the G9 row inventory, party shapes, execution bounds, G7 prerequisite,
evidence requirements, sandbox restrictions, or primary-owned verdict process.

## Risks / Trade-offs

- [OpenRouter Auto can return a resolved model with no usable rate or cost] -> Keep that call explicitly unpriced and cost-incomplete; do not synthesize a blended estimate.
- [A live provider/network outage can block G7 or G9] -> Preserve tooling/software progress, report the exact gate blocker, and leave the live gate incomplete rather than substituting fake evidence.
- [Task inventory can grow after policies are authored] -> Test exact coverage against the production task registry and fail closed before transport for missing entries.

## Migration Plan

1. Add and provider-free test task sampling, router accounting, bounded fallback, and G9 capture/evidence support while retaining current production defaults.
2. Require the primary's G7 PASS record. If G7 is not PASS, stop before production activation and live execution.
3. Change the approved provider/profile defaults to OpenRouter Auto, verify focused software checks, then run the primary-owned eight-row G9 matrix in the isolated sandbox.
4. Preserve the G9 evidence bundle before teardown. The primary records PASS, FAIL, or BLOCKED with evidence references. Demonstrate rollback by restoring direct OpenAI `gpt-6-luna` and restarting the sandbox server once; do not change prompts or gameplay mechanics.

## Open Questions

None. Provider selection, task boundaries, G7 sequencing, required G9 coverage, and Build 8 accounting ownership are already settled by the approved rollout plan.