# Design

## Context

See `proposal.md` for scope and `specs/` for acceptance contracts. Source-checked inventory and task mapping are in `reports/core-chat-inventory.md`. The existing facade owns task/profile resolution, fallback, and local usage statistics; factory-created chat clients use configured total/connect timeouts of 120/10 seconds. SDK retries are explicitly disabled by the router at `LLMRouter._disable_sdk_retries`, not by the factory. The router currently exposes local stats getters/reset only; this migration does not create a router-backed `/usage` UI or merge router stats into legacy usage, Debug, session, or rolling-week ledgers.

The core remains direct OpenAI (`LLM_PROVIDER = "openai"`). Existing main response empty-completion recovery uses `EMPTY_RESPONSE_RETRY_LIMIT = 2`, meaning at most three empty SDK responses per provider. Caller-owned validation/semantic loops and all transport receipt accounting remain distinct from this empty-response retry policy.

## Goals / Non-Goals

**Goals:**

- Move the inventoried 15 semantic operations to `llm.call()` while preserving nonterminal prompts, parsing, callbacks, state/action flow, returns, and caller semantic retry limits.
- Make terminal quota, refusal, and content-filter results explicit so no caller broad catch or semantic loop retries, falls back, assumes validity, or applies actions.
- Bridge optional per-call receipts to existing usage/log/trace consumers and reset only router/fallback session state once per runtime launch.
- Extend the existing Capture_Arena gate selector with the fixed, bounded G4 evidence contract while leaving G3 defaults and G5 latency scripts intact.

**Non-Goals:**

- Compression-engine transport/performance, action-prediction transport, other generators/utilities, media, Jev, Titan runtime, provider activation, `/usage` UI, and broad refactoring of `main.py` or `process_action`.
- Removing dormant helpers, changing gameplay mechanics, or modifying root-authored campaign/Bu files.

## Decisions

### 1. Facade is the only migrated transport boundary

**MUST:** Every operation in the inventory calls `llm.call(task=<mapped legacy ID>, messages=...)`; migrated callers no longer own SDK clients, model literals, transport/fallback clients, or timeout kwargs. Factory-created clients remain the only source of the existing configured 120-second total and 10-second connect timeout. The router is the owner that enforces SDK retries as zero through `LLMRouter._disable_sdk_retries`.

**MUST:** Use the task IDs from the inventory: `dm_main`, `dm_validation`, `summaries`, `combat_main`, `combat_validation`, `combat_summary`, `compression`, and `updates`. The direct initiative tracker maps to `combat_main`; the core-owned round summary maps to `compression`. An optional validated route-only simple/complex tier hint may preserve `get_ai_response()` choice, but it is not an SDK kwarg, does not replace task policy, and cannot override an explicit `TASK_OVERRIDES` model.

**MUST:** Keep `json_output=False` for migrated callers with their own parsing/validation. Preserve all nonterminal prompt bytes/order, parse behavior, callbacks, returns, and existing semantic retry bounds. Do not expand scope into broad `main.py`/`process_action` decomposition. All functions in `core/combat/` remain at most 600 lines and compatibility shims under 100 lines; this is an audit constraint, not authorization to refactor unrelated giant functions.

Simplest alternative considered: leave caller fallback/retry code around `llm.call()`. Rejected because that leaves model/transport ownership split, allows duplicate fallback/retry, and makes terminal outcomes pass through generic exception paths. Facade-only transport with caller-owned nonterminal semantic loops is the minimal seam.

### 2. Main empty-response recovery has a per-provider bound and one shared fallback bound

**MUST:** The optional `empty_retry_limit` policy is off by default, enabled only for ordinary `get_ai_response()` text calls, and rejected with `json_output=True`. Reuse `classify_chat_completion`, `EmptyProviderResponseError`, `EMPTY_RESPONSE_RETRY_LIMIT=2`, and the existing router error classifier. Do not wrap the router with `request_chat_completion_with_recovery` or nest empty recovery with facade JSON retry.

**MUST:** For empty SDK responses, the preferred provider may produce at most three responses (two retries); the single allowed fallback provider receives its own fresh bound of at most three responses. A call has at most one provider transition and at most six SDK invocations total. The shared fallback-used state and total-call cap never reset; only the per-provider empty-response counter starts fresh on the one permitted fallback. Every received response, including empty or malformed JSON text, is counted and observed once.

**MUST:** Client-construction failures are pre-attempt failures, not responses. SDK transport errors receive an error receipt and follow only the existing bounded transient fallback decision; they do not invoke empty-response retries. No more than one fallback transition or six SDK invocations may occur across response and transport errors. Quota/billing, refusal, and content-filter outcomes stop immediately and bypass all fallback/outer retry paths.

Provider-free tests cover preferred-provider three-empty exhaustion followed by fallback success, preferred-three plus fallback-three exhaustion, one fallback only, error/constructor bounds, terminal outcomes, exact receipt counts, and unchanged default behavior. Controlled failure coverage is fake transport only.

Simplest alternative considered: one global empty-response counter that carries the preferred count into fallback. Rejected because legacy recovery applies the same bounded empty-response retry to each provider; a fresh fallback response budget preserves that contract while the one-transition flag and six-invocation cap keep the whole call bounded.

### 3. Terminal results bypass caller broad catches and mutations

**MUST:** Quota uses only the existing router classifier; refusal/content-filter use explicit typed router terminal categories compatible with `GameLLMError`. Those outcomes short-circuit before any legacy broad catch, caller fallback, validation/semantic retry, fail-open-to-valid path, or action/application stage. Preserve current nonterminal retry/fail-open behavior and public return shape; terminal results must never produce valid/accepted output or mutate gameplay state. Do not introduce string-based quota heuristics.

**MUST:** For `process_action` location-transition narration, the terminal boundary begins only after the deterministic location commit, traveling-follower synchronization, transition-marker append, and pre-narration conversation-history save have completed. Those already-committed effects remain; terminal quota/refusal/content-filter SHALL NOT roll them back or replay them. The terminal result SHALL make one SDK attempt and stop before fallback/retry, assistant narration append/save, transition-success publication, or any further action/state mutation. This exception describes the ordering boundary for this owner only; it does not change the behavior or decision/mutation contract of other owners.

The explicit handling boundary must cover `main.py` validation and ordinary narrator loops, combat bootstrap/turn/combat validation, and all three action-handler owners. Tests inject a single quota SDK error and prove zero fallback, zero semantic retry, and zero action/state mutations after each owner's boundary. For location-transition narration, retain the deterministic pre-narration commit/synchronization/marker/history save while proving no post-boundary effects; do not roll back or replay those effects. Separate rejection cases prove refusal/filter also do not reach later application paths.

### 4. Observer and runtime accounting stay per-call and separate

The optional router observer receives immutable per-attempt receipt metadata plus trusted observer-only access to the raw SDK response. Each actual SDK invocation emits exactly one response/error receipt; client-construction failures are distinguished. Metadata includes call/attempt IDs, task, tier/profile, retry/fallback state, selected transport provider versus optional observed upstream provider, requested/resolved model, token/cache usage, reported cost including actual zero, estimated/unpriced provenance/completeness, and elapsed time when available. Return value and router-local stats snapshot are materialized before observer execution; invoke outside stats locks and isolate ordinary observer exceptions. No observer means no observer-specific I/O or client construction.

A minimal adapter bridges receipts to existing `get_global_tracker().track`/`track_response`, applicable API logs, and opt-in combat provider trace. Remove migrated manual duplicates only after tests prove one event per response. Error receipts do not fabricate usage. Router-local stats remain a distinct programmatic view; this phase does not add `/usage` UI, create another accounting framework, or aggregate router counts into legacy tracker/Debug session/week totals. Preserve actual zero, label estimates estimated, and mark missing cost unpriced/incomplete. G4 reports only its core migrated accounting subset.

Fresh runtime launch, not new campaign creation, is the session boundary. A minimal shared begin-runtime-session helper resets router-local session stats and the existing factory fallback-notification state once at each launch hook: CLI `main.main()` at `main.py:8730` before setup/first core call, and web `web.web_interface.run_game_loop()` at `web/web_interface.py:4503` before file hydration/first core call. Do not call it from `main_game_loop()`: save restore returns `restart` from `action_handler.py:3419` and recursively enters `main_game_loop()` from `main.py:8402`; that is not a runtime launch. Do not reset on turn, validator, save, load, or resume, and never reset the rolling-week ledger. No registry/global session framework is introduced.

Simplest alternative considered: process-global last-response storage or a broad session registry. Rejected because response association races across concurrent calls and state becomes harder to test. The per-call observer plus two narrow launch-hook calls is sufficient.

### 5. G4 tooling retains exact capture limits and isolates sandbox fixtures

Add only `--gate g3|g4`, with G3 remaining the default and its raw 18-key compatibility unchanged. G4 writes to `tmp/router-rollout/g4/<run-id>/` and requires four keys: `narrator-dialogue-travel:p1`, `narrator-dialogue-travel:p4`, `combat-smoke:p1`, `combat-smoke:p4`.

Narrator coverage is five fixed turns across CA01 -> CA02 -> CA03, ask Mira the shrine question, then return via CA02 -> CA01; P4 includes the specified switch to Merisiel. P1 limits are 6 inputs/8 controls; P4 limits are 6 inputs/9 controls. Include initial start and active-PC switch in controls. Apply the predeclared 300-second narrator-turn capture cap. Read-only health observations have a separate explicit bound and count.

Combat uses the deterministic seeded fixture, not a random encounter: P1 remains 5 inputs/7 controls and P4 remains 22 inputs/35 controls, both with a 300-second capture-only cap. Never claim a random encounter proves the seeded Goblin Alpha case.

The CA02 authored scenario auto-starts 2-4 goblins. In the sandbox copy, transform `tmp/combat_capture/modules/Capture_Arena/areas/CTR001_BU.json` and corresponding `CTR001.json` live-area inputs consistently; transform copied plot/context only if fixture consistency requires it. Prepare both so the seeder and later `initialize_game_files_from_bu` hydration produce the same peaceful scene. Leave repository/root-authored BU data unchanged; do not patch a running server or add magic flags. Use CA03's authored Mira area NPC. Inspect the actual runtime NPC reader first; if it requires persisted NPC data, seed a canonical schema-valid NPC record (including its actual required fields) without an unnecessary PC character file or media generation.

G4 tooling SHALL add allowlisted read-only projections for `currentLocation` and `currentLocationId`; these are proposed additions to the G4 evidence allowlist, not claims that the current rig already exposes them. Compare them with source-derived expected room IDs and persisted party/active-PC state. Distinguish actual backend NPC response from input echo. Provider/model/task/retry/fallback/usage observations come from real router receipts, not declared configuration; unknown cost remains explicit. Any timeout, cap, missing receipt/data, mismatch, or echo-only completion is named FAIL/BLOCKED and stops queued inputs. The primary, not the builder, executes/reviews the four live keys after focused tests. No forced live fallback; live Auto/fallback/rollback belongs to G9.

Simplest alternative considered: separate live harness or change G3 defaults. Rejected because separate tooling duplicates the existing rig and changing G3 behavior risks compatibility; a gate selector plus distinct G4 root isolates the new coverage.

## Risks / Trade-offs

- [Risk] Empty or transport recovery multiplies caller loops -> 3 response attempts/provider, one fallback transition, total six SDK invocation cap, terminal short-circuit, and receipt-count assertions.
- [Risk] Terminal result is swallowed by a broad caller catch -> explicit typed terminal handling at every scoped owner and fake tests proving zero retries/fallbacks/mutations.
- [Risk] Receipt observer changes response/accounting or misassociates concurrent calls -> immutable per-call IDs, observer outside stats lock, isolated exceptions, concurrency tests.
- [Risk] Runtime reset runs on restore/turn or clears weekly history -> two launch hooks only, restore recursion excluded, AST ordering tests, weekly ledger sentinel.
- [Risk] G4 false PASS from hostile sandbox hydration, echo, or wrong limits/seed -> consistent fixture transforms of the copied `CTR001_BU.json` and `CTR001.json`, exact budgets, newly allowlisted persisted projections, receipt checks, and fail-stop negatives.

## Migration Plan

1. Add guarded provider-free tests and baseline contracts for exact inventory, task mapping, prompt bytes, retry budgets, and return/callback parity.
2. Add receipt observer and typed terminal outcomes, then optional main-only per-provider empty recovery with shared one-fallback/six-invocation limits.
3. Add minimal legacy adapter and the two runtime launch hooks; test normal launch ordering and restore recursion exclusion.
4. Migrate `main.py` helpers/validator/get_ai_response/summary in isolated tasks; migrate combat stages and initiative tracker; migrate each action-handler operation separately.
5. Re-inventory all variants; run affected baseline suites plus new tests; audit every `core/combat/` function <=600 and shims <100 without unrelated main/process_action refactoring.
6. Add fixed G4 profile/fixture transforms, then driver/receipt collection, then offline matrix/negative checks as separate tasks. Only after those pass does the primary run and judge the four G4 captures.

Rollback is source-level and stays direct OpenAI: revert the scoped caller integrations and receipt adapter while retaining prior facade/factory work. G4 tooling changes can be reverted independently without altering the default G3 path or retained evidence.

## Open Questions

None. Retry budgets, terminal handling, launch hooks, evidence projections, fixture transforms, bounds, and primary ownership are specified here and in the delta specs.
