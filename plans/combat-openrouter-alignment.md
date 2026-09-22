# Combat x OpenRouter Alignment Plan (Dev Path + OpenSpec Outline)

Status: ACTIVE COORDINATION PLAN - implementation not started; two owner decisions open (D1, A1)
Date: 2026-09-21
Owner: Combat systems + tabletop mode / LLM platform
Inputs:

- `plans/version-2/combat-manager-refactor.md` (2026-09-21 revision, section 3.1 interlock)
- `plans/version-2/openrouter_llm_router_architecture.md` (v4.1 interlock amendment)

Authority: `AGENTS.md` governs repo-wide rules; the two input plans govern change-specific
scope and targets. Once an OpenSpec change is authored, that change's artifacts become the
authoritative contract for its scope and override plan detail where they conflict. This
document is the execution/coordination layer that maps plan phases onto OpenSpec changes
and gates; it does not restate either plan. Keep it consistent with both inputs when either
is amended.

---

## 1) Purpose

1. Give every unit of work an OpenSpec change ID, an owner plan, a position in the
   execution order, and a measurable gate.
2. Keep the two plans from stepping on the same files in the wrong order
   (`combat_manager.py`, `core/ai/combat_compression_engine.py`, `main.py`,
   `core/ai/action_handler.py`, `ai_client_factory.py`, `model_config.py`).
3. Define the telemetry that proves each phase moved a ratified metric.
4. Keep the decision-primitive (Jev) track gated and out of Phases 0-3; only seams are
   provisioned here.

Non-goals: no new gameplay rules, no prompt rewrites, no upstream sync, no Jev
implementation authorization, no announcement of OpenRouter activation timing beyond the
recommendation in section 6.

---

## 2) Decisions ledger

### 2.1 Settled

| ID | Decision | Recorded |
|---|---|---|
| D2 | Latency targets provisional in Phase 0, ratified before Phase 2 | combat plan section 12 |
| D3 | NL fast-path canary in Phase 2; timeout ownership delegated to the router client | combat plan section 12 |
| D4 | Author all five combat artifacts first (amended by AO: baseline-first, then batch the remaining four after G1) | combat plan section 12; owner 2026-09-21 |
| D6 | Decision seams folded into owning phases (no separate pre-Jev change) | combat plan section 12 |
| R1 | `combat_manager.py` Tier 1 migration follows `combat-manager-decomposition` | router plan decisions log |
| R2 | Combat per-call timeouts superseded by Phase 0 client-level `httpx.Timeout` | router plan decisions log |
| R3 | `retry_tier` is a first-class `call()` parameter (combat escalation parity) | router plan decisions log |
| D1 | Combat package location: `core/combat/` + `core/combat/multi_pc/` with shims at the old `core/managers/` paths | Owner 2026-09-21, alignment review |
| AO | Combat artifact authoring order (option b): author `combat-latency-baseline` first, reach G1, then batch-author the remaining four with ratified targets | Owner 2026-09-21, alignment review |
| S1 | Single tabletop runtime: minimum party is one PC; SP terminology retired (ADR-0032) | Owner 2026-09-21, `adrs/0032-single-tabletop-runtime.md` |

### 2.2 Open - must resolve before the dependent artifact is authored

| ID | Decision | Needed before | Recommendation |
|---|---|---|---|
| A1 | When to flip `LLM_PROVIDER = "openrouter"` | `llm-router-openrouter-activation` | Activate only after all chat call sites are migrated AND the combat hot path is measured on OpenAI; otherwise activation confounds the ratified latency baseline. Owner may pull this earlier for cost reasons, accepting that combat latency targets are then measured on the OpenRouter stack instead |
| A2 | Router migration change split | `llm-router-core-migration` artifacts | Two changes: Tier 1 core (`llm-router-core-migration`) and tiers 2-4 (`llm-router-remaining-callsite-migration`). Tier 1 carries the 1-PC party and multi-PC party smoke burden alone and gets its own rollback boundary |
| A3 | Jev decomposition eval rerun timing | `jev-decisions-primitive` (gated) | Run after `combat-latency-hot-path` lands so the validator-residual classifier has a measurable residual to target |

---

## 3) Dev path (execution order)

Execution order is the interleave approved in `combat-manager-refactor.md` section 3.1.
Every step ends with its gate; a failed gate blocks the next step, not the whole path.

| Step | Change | Owner plan | Gate to exit |
|---|---|---|---|
| 0 | Workspace baseline clean (D1 confirmed 2026-09-21) | - | G0 |
| 1 | `combat-latency-baseline` | combat Phase 0 | G1 |
| 2 | `llm-router-facade` | router Phase 0/1 | G2 |
| 3 | `combat-manager-decomposition` | combat Phase 1 | G3 |
| 4 | `llm-router-core-migration` | router Phase 2 Tier 1 | G4 |
| 5 | `combat-latency-hot-path` | combat Phase 2 | G5 |
| 6 | `llm-router-remaining-callsite-migration` | router Phase 2 Tiers 2-4 | G6 |
| 7 | `combat-turn-commit-and-receipts` | combat Phase 3a | G7 |
| 8 | `combat-typed-resolver-expansion` (optional) | combat Phase 3b | G8 |
| 9 | `llm-router-openrouter-activation` | router rollout (A1) | G9 |
| 10 | `llm-router-cleanup` | router Phase 3 | G10 |
| J1+ | Jev track (`jev-*`, gated) | router Workstream C | J-gate |

Notes:

- Steps 6 and 7 may overlap (different files); step 6 must not migrate
  `core/ai/combat_compression_engine.py` until step 5 has finished the compression
  rework and the file's final shape is known.
- Step 8 is optional and may be deferred without blocking steps 9-10.
- Jev track changes are not part of this build path until their gates pass (section 8).

Deferred governance note: the party-size dual-check gates and `MULTIPLAYER_MODE` removal are owned by the future `tt-single-runtime-unification` change per ADR-0032; they are not in this build path and must not be edited opportunistically.

### 3.1 Gate definitions

| Gate | Requirement | Evidence |
|---|---|---|
| G0 | D1 confirmed (2026-09-21); working tree baseline clean for the touched files | Owner decision recorded in section 2; `git status` clean for the change scope |
| G1 | Baseline captured on the OpenAI stack; targets ratified or adjusted | `debug/combat_turn_trace.jsonl` + `scripts/combat_latency_report.py` output recorded in the change |
| G2 | Facade is behavior-neutral on `LLM_PROVIDER = "openai"`; bake-off gate clears (narrator/combat match or beat `gpt-5.6-luna` on JSON validity at lower cost) | `scripts/test_llm_router.py`, OpenAI parity smoke, `scripts/benchmark_model_profiles.py` report |
| G3 | All combat suites green; prompts byte-identical (diff-verified); shims in place; 1-PC party and multi-PC party smoke pass | Suite commands (section 5.3) + prompt diff + smoke |
| G4 | 9 combat call sites + `main.py` + `action_handler.py` migrated; timeout coverage verified from the client; retry escalation parity; 1-PC party and multi-PC party smoke pass | Router-parity tests + combat suites + timeout assertion test |
| G5 | Ratified targets met on the fixed MP smoke; provider-call budgets met; validation-skip and NL hit rates reported | `combat_latency_report.py` + router usage stats |
| G6 | Tiers 2-4 migrated; provider-tripwire and contract suites unaffected | `scripts/test_gpt54*` suites + compile + smoke |
| G7 | Crash/restart mid-turn converges with no duplicate mechanics | Idempotence test + resume replay suites |
| G8 | Deterministic resolver coverage for attack/damage/save (if pursued) | Resolver tests + C5 regression |
| G9 | OpenRouter live posture smoke + cost measurement + documented rollback | Bake-off report + live smoke + usage stats |
| G10 | Dead code/config removed; `/usage` works; docs synced; full session test | Full session smoke + `openspec validate --specs` |
| J-gate | Decomposition eval clears agreement >= 0.95 and FN <= 0.05 | Jev eval report; owner authorization recorded |

---

## 4) OpenSpec change outline

Authoring convention for every change below:

- `openspec/changes/<change-id>/proposal.md` - problem, objective, non-goals, rollout
  risk, fallback, 1-PC party and multi-PC party compatibility impact, provider-outage behavior where LLM plumbing
  is touched (per `openspec/config.yaml`).
- `openspec/changes/<change-id>/design.md` - architecture boundaries, state authority,
  thread safety, sequencing, rollback.
- `openspec/changes/<change-id>/specs/<capability>/spec.md` - delta specs. Capability
  names below are proposals; finalize during authoring.
- `openspec/changes/<change-id>/tasks.md` - small verifiable tasks with concrete file
  targets and verification per task.
- Author with the `openspec-propose` / `openspec-new-change` / `openspec-ff-change`
  skills; implement with `openspec-apply-change`; close with `openspec-verify-change`;
  archive with `openspec-archive-change` after `openspec validate <change> --strict`
  passes and specs sync.

### 4.1 Step 1 - `combat-latency-baseline` (combat Phase 0)

Objective: capture a trustworthy pre-router, pre-model-swap latency baseline and make
per-turn cost visible.

Scope in: opt-in per-turn trace, report script, fixed smoke fixtures. Scope out: any
behavior change, any prompt change, any timeout change.

Proposed delta specs:

- `combat-turn-trace-schema` - trace fields: provider calls by site with latency/tokens,
  compression calls and cache hit rate, file reads/writes, stage wall-clock timings,
  NL fast-path hit/miss.
- `combat-decision-trace-events` - `decision_point`, `decision_source`
  (`deterministic` | `llm_fallback` | `jev`), `decision_latency_ms`,
  `provider_call_avoided`.
- `combat-latency-smoke-fixtures` - MP 4 PCs x 3 rounds + 1 enemy batch; 1-PC party x 1 round.
- `combat-latency-report-script` - provider-free `scripts/combat_latency_report.py`.

Task outline: (1) trace writer + config gate; (2) instrument stages and provider sites;
(3) fixtures; (4) report script; (5) verify zero overhead when disabled.

Gate: G1.

### 4.2 Step 2 - `llm-router-facade` (router Phase 0 + 1)

Objective: config/factory prep plus the thin router facade and bake-off harness. No
consumer migration.

Scope in: `MODEL_PROFILES` v4, `COMPLEX_TASKS` rename, `extra_body` normalization,
`finalize_chat_params(retry_tier=...)`, client-level `httpx.Timeout`, `utils/llm_router.py`
with `call()` + gated `decide()` stub, cache-aware thread-safe stats, bake-off harness.
Scope out: any callsite migration, Jev implementation.

Proposed delta specs:

- `llm-router-facade-api` - `llm.call(task, messages, json_output, temperature,
  max_tokens, retry_tier)` contract; `decide()` fails closed until gated.
- `llm-model-profile-routing` - v4 tiers, `DEFAULT_PROFILE`, `ACTIVE_PROFILE`,
  `TASK_OVERRIDES`; unknown profile falls back without crashing.
- `llm-provider-preferences` - tier `provider` block passed as the OpenRouter `provider`
  request field.
- `llm-factory-param-finalization` - GPT-5 temperature policy; `retry_tier` escalation
  parity with the legacy shim; client-level timeout constants.
- `llm-router-usage-telemetry` - cache-aware cost tracking; thread-safe session stats.
- `llm-router-bakeoff-gate` - provider-free by default; `--live` mode; gate criteria.

Task outline: (1) `model_config.py` profiles + renames + deprecation comments; (2)
factory `extra_body` fix + `finalize_chat_params` + client timeout; (3) `llm_router.py`;
(4) unit tests; (5) bake-off harness + gate run; (6) OpenAI parity smoke; (7) one live
OpenRouter smoke call (facade only).

Gate: G2.

### 4.3 Step 3 - `combat-manager-decomposition` (combat Phase 1)

Blocked until D1 is confirmed.

Objective: behavior-preserving package move and loop decomposition. Prompts
byte-identical.

Scope in: `core/combat/` package (`session.py`, `turn.py`, `commands.py`,
`decisions.py`, `prompts.py`, `validation.py`, `persistence.py`, `narration.py`,
`multi_pc/*`), shims at old paths, 9-stage extraction, `CombatSession`, dead-code and
logging hygiene, decision-seam contract. Scope out: prompt edits, rule changes, latency
optimizations.

Proposed delta specs:

- `combat-package-boundary-and-shims` - `core/combat/` ownership; old paths are thin
  re-export shims with TABLETOP MODE markers.
- `combat-session-state-ownership` - one session object owns encounter, manager, history,
  active PC, phase; no mutable globals or literal history-index rewrites.
- `combat-turn-stage-decomposition` - the 9 named stages and their contracts; no single
  function > 600 lines.
- `combat-decision-seam-contract` - `declined` vs `unavailable` statuses; both fall
  through to the LLM path; provider-call budget assertions are upper bounds.
- `combat-code-hygiene-parity` - dead function removal, exception narrowing, logger
  conversion with stable diagnostic strings, `sys.exit(0)` audit.

Task outline: (1) package + shims; (2) session state; (3) stage extraction; (4) decision
seam; (5) cleanup slice; (6) repoint source-contract tests without weakening assertions;
(7) full suite + prompt diff + smoke.

Gate: G3.

### 4.4 Step 4 - `llm-router-core-migration` (router Phase 2 Tier 1)

Objective: migrate the 9 combat call sites (now named stages), `main.py` (5), and
`core/ai/action_handler.py` (6) to `llm.call()`. Remove the legacy per-call timeout
arguments (client bound replaces them) and preserve `retry_tier` escalation.

Scope in: `core/combat/*`, `main.py`, `core/ai/action_handler.py`. Scope out: image/TTS,
tests/fixtures, `utils/action_predictor.py` (reserved for `llm.decide`).

Proposed delta specs:

- `llm-router-combat-task-mapping` - 9 combat sites to task ids
  (`combat_main`, `combat_validation`, `combat_summary`, `combat_dialogue_summary`,
  `narrative_compression` as applicable post-rework).
- `llm-router-core-callsite-parity` - migrated calls preserve prompt bytes, temperature
  policy, JSON handling, and fallback notifications.
- `llm-router-timeout-coverage-from-client` - every combat provider call bound by the
  client default or explicit timeout; no parallel per-call timeout path.
- `llm-router-retry-tier-preservation` - validation-failure reasoning escalation parity
  through `finalize_chat_params(retry_tier=...)`.

Task outline: (1) migrate combat stages; (2) remove legacy timeout args; (3) migrate
`main.py`; (4) migrate `action_handler.py`; (5) contract/regression tests; (6) 1-PC party and multi-PC party
smoke.

Gate: G4.

### 4.5 Step 5 - `combat-latency-hot-path` (combat Phase 2)

Objective: land the deterministic latency wins measured against the ratified baseline.

Scope in: compression rework, validation-skip wiring via `decide_validation_routing()`,
head-context memoization, encounter sync once per turn, debug capture gating, NL
fast-path canary, retry-shape domain policy. Scope out: timeouts (router-owned),
declarative effects/condition lifecycle.

Proposed delta specs:

- `combat-compression-round-boundary` - per-message LLM compression removed; round-boundary
  compression retained; deterministic truncation for stale rounds; cache deleted or
  hash-validated once unused.
- `combat-validation-skip-routing` - `decide_validation_routing() -> (skip, reason)`;
  retry ladder capped for deterministic-failure classes; reserved `jev_*` reason names.
- `combat-prompt-context-memoization` - memoized formatter keys; no stale-context reuse.
- `combat-encounter-sync-once-per-turn` - single guarded sync; no redundant
  `party_tracker.json` reads; write-on-change.
- `combat-nl-fast-path-canary` - hit/miss/false-positive telemetry; automatic LLM
  fallback on any parse miss; parse miss vs decision `unavailable` distinguished.
- `combat-debug-capture-gating` - per-attempt JSON dumps behind the debug flag; no CWD
  artifact writes.

Task outline: (1) compression rework; (2) validation skip; (3) memoization; (4) sync
guard; (5) debug gating; (6) NL canary + narration expansion; (7) retry-shape policy;
(8) measurement against G1 baseline.

Gate: G5.

### 4.6 Step 6 - `llm-router-remaining-callsite-migration` (router Phase 2 Tiers 2-4)

Objective: migrate the remaining production chat callsite files (tiers 2-4) after the
combat runtime has settled. Exclude `core/ai/combat_compression_engine.py` until step 5
completes.

Scope in: tiers 2-4 file lists from the router plan. Scope out: tier 1 (done),
provider-safety infrastructure, image/TTS, tests/fixtures.

Proposed delta specs:

- `llm-router-tier-migration-parity` - per-file compile + smoke after each tier.
- `llm-router-compression-callsite-ownership` - compression-engine call sites migrate
  only after the combat rework; no double migration.
- `llm-router-provider-tripwire-preservation` - `scripts/**` provider-tripwire and
  contract suites stay intact.

Task outline: tier 2 (10 files) -> tier 3 (12 files) -> tier 4 (29 files), each with
compile + smoke; remove legacy imports per file.

Gate: G6.

### 4.7 Step 7 - `combat-turn-commit-and-receipts` (combat Phase 3a)

Objective: single commit path and idempotent resume; code-owned round advancement.

Proposed delta specs:

- `combat-single-commit-path` - characters staged, encounter written last; 3 writes/turn
  ceiling respected.
- `combat-turn-receipts-idempotency` - applied IDs and receipts make replay a no-op.
- `combat-code-owned-round-advancement` - `roundStartsWith`/opening-batch flags are the
  sole authority; prose cannot advance rounds.

Task outline: (1) commit path; (2) receipts + replay guards; (3) round advancement
consolidation; (4) crash/restart convergence test.

Gate: G7.

### 4.8 Step 8 - `combat-typed-resolver-expansion` (combat Phase 3b, optional)

Objective: typed deterministic resolver breadth (attack, damage, save), reusing the NL
parser and precheck infrastructure, including safe enemy-batch coverage.

Proposed delta specs: `combat-deterministic-resolver-attack-damage-save`,
`combat-enemy-batch-deterministic-coverage`.

Gate: G8.

### 4.9 Step 9 - `llm-router-openrouter-activation` (A1)

Objective: flip the operating posture to OpenRouter under a gated, reversible change.

Scope in: `ACTIVE_PROFILE` selection, `LLM_PROVIDER = "openrouter"`, cost/latency
measurement, rollback procedure. Scope out: image/speech catalogs (Phase 4 version of
the router plan remains separate).

Proposed delta specs:

- `llm-router-openrouter-posture` - provider flip is config-only and reversible; OpenAI
  remains the automatic fallback.
- `llm-router-activation-rollback` - documented rollback to `LLM_PROVIDER = "openai"`
  within one restart.
- `llm-router-activation-cost-report` - session/week cost measured before and after.

Task outline: (1) bake-off update; (2) flip in a dev session; (3) measure latency/cost
against the OpenAI baseline; (4) 1-PC party and multi-PC party smoke; (5) document rollback; (6) owner sign-off.

Gate: G9.

### 4.10 Step 10 - `llm-router-cleanup` (router Phase 3)

Objective: remove dead code and deprecated config, add `/usage`, sync docs.

Proposed delta specs: `llm-router-dead-code-removal`,
`llm-router-deprecated-config-removal`, `llm-router-usage-command`,
`llm-router-documentation-sync`.

Gate: G10.

---

## 5) Cross-cutting build conventions

### 5.1 Interpreter and hygiene

- Use `.venv/bin/python` for all runtime, test, and dependency-sensitive commands.
- ASCII-only Python output (`python3 scripts/check_ascii_compliance.py --summary-only`).
- Atomic JSON writes for game state (`safe_read_json` / `safe_write_json`).
- `# TABLETOP MODE:` markers on host edits; extensions in separate modules.
- 1-PC party compatibility is a hard gate for every change (ADR-0032).

### 5.2 Git

- One branch per change with a `feature/` or `fix/` prefix; push to `origin` explicitly.
- No auto-commit and no auto-push from automated runs; owner commits.
- Never touch upstream; never create PRs against upstream.

### 5.3 Verification commands (shared)

```bash
# Combat suites (every combat-touching change)
.venv/bin/python -m unittest -q scripts.test_multi_pc_combat
.venv/bin/python -m unittest -q scripts.c5_regression_combat
.venv/bin/python -m unittest -q scripts.test_combat_pc_action_parser
.venv/bin/python -m unittest -q scripts.test_combat_phase_integrity_precheck

# Router (new; every router-touching change)
.venv/bin/python scripts/test_llm_router.py
.venv/bin/python scripts/benchmark_model_profiles.py --profile production-2026-09

# Combat measurement
.venv/bin/python scripts/combat_latency_report.py --trace debug/combat_turn_trace.jsonl

# OpenSpec
openspec validate <change-id> --strict
openspec validate --specs
```

Web smoke uses the `neq-playwright-smoke` skill or a manual `run_web.py` pass; the
combat smoke fixture (MP 4 PCs x 3 rounds + enemy batch) is the latency gate artifact.

### 5.4 Artifact authoring order

- Combat changes: author `combat-latency-baseline` first and execute it to G1. Then
  batch-author the remaining four combat artifacts (`combat-manager-decomposition`,
  `combat-latency-hot-path`, `combat-turn-commit-and-receipts`,
  `combat-typed-resolver-expansion`) so ratified targets land in their tasks
  (option b, decided 2026-09-21).
- Router changes: author each change just-in-time before its step, because the bake-off
  and activation decisions (A1) may change profile details.

---

## 6) Activation timing recommendation (A1)

Recommended: activate OpenRouter at step 9, after tiers 2-4 migration and after the
combat hot path is measured. Rationale: the Phase 0 baseline and the G5 latency gate are
measured on the OpenAI stack; flipping providers earlier confounds structure and model
attribution, and makes the ratified targets non-comparable. If cost pressure requires
earlier activation, record that the latency targets were measured on OpenRouter instead,
and re-ratify.

---

## 7) Telemetry contract

| Layer | Artifact | Consumed by |
|---|---|---|
| Combat per-turn trace | `debug/combat_turn_trace.jsonl` (opt-in) | G1, G5, G7; decision-event shadow evaluation |
| Combat latency report | `scripts/combat_latency_report.py` output | Target ratification and phase gates |
| Router session stats | `llm.get_usage_stats()` (cache-aware) | G2, G4, G5, G9 cost/latency checks |
| Router per-call debug log | `enhanced_logger` category `ai_provider` | Provider/fallback diagnosis |
| Jev decisions (future) | cost-only events via `utils/llm_usage_tracker.py` pattern | J-gate evaluation |

Decision events must exist before any Jev shadow mode is attempted (D6/G1 deliverable).

---

## 8) Jev (decision primitive) track - gated

Not authorized. The Phase 0 eval did not clear the gate (0.677/0.704 agreement vs 0.95
target; FN 23-29% vs 5% target). The seams created by steps 1, 3, and 5 are the only
preparation permitted in this path.

| Change | Gate to start | Seam it uses |
|---|---|---|
| Decomposition eval rerun (A3) | after G5 | eval harness `scripts/spike_jev_decisions.py` |
| `jev-decisions-primitive` | J-gate pass + owner authorization | `utils/jev_client.py`, `llm.decide()`, `DECISION_TASKS` |
| `jev-action-predictor-promotion` | primitive landed | `utils/action_predictor.py` (shadow, then flag-gated) |
| `jev-combat-validator-residual` | primitive landed + G5 baseline | `decide_validation_routing()` in `core/combat/validation.py` |
| `jev-narrator-validator-shadow` | later | narrator validation path |
| `jev-ego-drift-classifier` | later | EGO workstream |

Hard rules for any Jev change: never route Jev through `create_chat_client()` or
`MODEL_PROFILES`; never treat upstream failure as a negative answer; never ask Jev to
compute numbers; fail open to the existing chat/deterministic path; record
probabilities/latency/input tokens per call.

---

## 9) Cross-plan risks

| Risk | Impact | Mitigation |
|---|---|---|
| Router slip delays timeout coverage (R2 delegation) | Unbounded combat hangs on 6 sites | G2 is a prerequisite for G3-G5; if the router slips, escalate in the router change - do not fork a combat timeout path |
| `core/ai/combat_compression_engine.py` owned by two plans | Double migration or accidental deletion | Step 5 settles the file first; step 6 migrates what remains (`llm-router-compression-callsite-ownership`) |
| Activation before G5 (A1 pulled early) | Latency targets non-comparable | Record and re-ratify targets on the OpenRouter stack |
| D1 unresolved | Blocks `combat-manager-decomposition` artifacts | Resolve at G0; do not start step 3 artifacts |
| Decision seams accrete Jev scope | Scope creep, unverified classifier behavior | Seams are contract-only; Jev changes carry their own gates and tests |
| Router facade behavior drift on OpenAI | Tester regression | G2 parity smoke plus existing GPT-5 contract suites on every router change |
| Prompt contract drift during decomposition | Combat behavior change | Byte-identical prompt diff at G3; replay fixtures |

---

## 10) Builder briefing template (per change)

When opening a build session for any change in section 4:

1. Name the change and its input plan section(s); restate the gate it must exit.
2. List the files in scope from this document's step entry, and only those.
3. Paste the verification command block (section 5.3) with the change-specific additions.
4. State the rollback: revert the commit range; flags (`COMBAT_PC_PHASE_NL_FAST_PATH`,
   debug trace gate) revert by config.
5. Remind: no prompt edits outside scope, no Jev code, 1-PC party smoke is a hard gate, ASCII
   compliance before commit.

---

## 11) Open items and resolutions

Resolved 2026-09-21:

1. D1 - `core/combat/` + `core/combat/multi_pc/` with shims at the old
   `core/managers/` paths (confirmed).
2. Authoring order - option (b): `combat-latency-baseline` first to G1, then batch the
   remaining four combat artifacts with ratified targets (confirmed).

Still open (needed before the dependent step, not before scaffolding):

3. A1 - confirm activation at step 9, or authorize earlier with re-ratified targets.
4. A2 - confirm the two-change split for router migration (needed before step 4 artifacts).
5. A3 - confirm the decomposition eval rerun happens after G5.
