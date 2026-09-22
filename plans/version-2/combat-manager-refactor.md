# Combat Manager Refactor Plan (v2) - Latency First, Multi-PC Primary

Status: DRAFT - owner review in progress (interleave approved 2026-09-21; no implementation work until the amended plan is approved)
Priority: High (combat responsiveness is a product requirement, not a nice-to-have)
Date: 2026-09-21
Owner: Combat systems + tabletop mode
Supersedes: 2026-02-26 revision of this file (its scope is completed or obsolete; see section 3)
Related: `adrs/0031-independent-development-fork.md`, `adrs/0032-single-tabletop-runtime.md`, `plans/archive/upstream-merge-0826.md`,
`plans/version-2/openrouter_llm_router_architecture.md` (interlock: section 3.1)

---

## 1) Objective

Execute a full structural refactor of the combat runtime so that:

1. **Latency drops materially.** Tabletop combat must feel fast paced. One facilitator
   enters actions for several PCs in real time; every avoidable provider call, file write,
   and history rescan is felt at the table. Latency is the primary success metric of
   this plan.
2. **Multi-PC (TABLETOP MODE) combat is the primary beneficiary.** Every phase must
   comply with, enable, and actively optimise multi-PC combat - not merely avoid
   breaking it. A 1-PC party remains compatible through shims (ADR-0032).
3. **Structure becomes navigable.** `core/managers/combat_manager.py` (5,457 lines) and
   `core/managers/multi_pc_combat.py` (2,751 lines) become a `core/combat/` package with
   explicit stage boundaries, one session state object, and one per-turn commit path.
4. **No gameplay rules change.** Prompt text stays byte-identical through the
   decomposition phase. Phase markers, death-save gates, initiative gates, roster
   integrity, and enemy-batch semantics are preserved exactly.

### 1.1 Latency targets (provisional - ratify after Phase 0 baseline)

| Metric | Provisional target |
|---|---|
| PC action turnaround (p50), LLM path | <= 8 s |
| PC action turnaround (p50), deterministic fast path | < 1 s |
| Enemy batch (`/end`, all enemies) p50 | <= 15 s |
| Provider calls per uncontested PC action | <= 2, then <= 1 |
| Provider calls per enemy batch | 1 |
| File writes per combat turn | <= 3 |
| Per-round latency (4 PCs + enemy batch) | improve >= 30% vs baseline |

Targets are provisional because no trustworthy baseline exists yet. Phase 0 measures
first; the owner ratifies or adjusts targets before Phase 2 proceeds.

---

## 2) Upstream position (already adjudicated)

The fork's upstream relationship is closed for routine synchronization per ADR-0031, and
the final upstream review ledger (`plans/archive/upstream-merge-0826.md`, closed
2026-09-21) already classified the relevant upstream combat work.

- Reviewed window: 524 upstream commits (2026-08-05 through 2026-09-20).
- Explicitly left behind: agentic combat/referee, NPC voice/episodic memory, Responses
  API/headless transport, provider liveness/keepalive orchestration, and the crash-safe
  transaction coordinator.
- Reason recorded: upstream and fork have incompatible runtime, state-authority,
  provider, UI, memory, combat, and publication architectures and authority boundaries.
- Ported upstream items were unrelated to combat (legacy UI output encoding, transient
  empty provider response recovery).

Therefore this plan uses upstream combat work as **concepts only**, never as a merge or
cherry-pick source. Concepts worth mining, expressed as fork-native work:

1. Code-owned round advancement (the LLM narrates; code advances rounds).
2. Staged commit discipline: characters first, encounter commit last, applied IDs and
   turn receipts, idempotent replay on resume.
3. One provider call per committed actor window as the structural baseline (fork form:
   PC action window and enemy batch window).
4. Provider liveness basics: keepalive, cancellation propagation, complete timeouts.

No upstream branch is fetched or merged. The `upstream` remote remains read-only
historical reference per ADR-0031.

---

## 3) Relationship to the previous revision (2026-02-26)

The previous revision targeted "builder reliability + merge safety". Its stated
prerequisite, `tt-combat-manager-hardening-only`, is complete
(`openspec/changes/archive/2026-03-09-tt-combat-manager-hardening-only`), and one of its
main asks already exists: `/init` gate isolation via `_handle_group_initiative_gate()`
(`core/managers/combat_manager.py:1647`).

Kept from the previous revision:

- Tiny-slice, behavior-preserving extraction.
- Explicit helper contracts instead of closure/global reliance.
- Compile checks after each slice; stable log lines for diff-based comparison.
- 1-PC party and multi-PC party behavior-equivalence gates.

Dropped or superseded:

- The "merge safety / upstream-facing maintainability" premise (ADR-0031 retired
  upstream synchronization).
- The "defer to v2 after test build" framing (combat latency is now an active product
  requirement).
- Scope that stopped at helper extraction and never addressed latency or multi-PC
  throughput.

Disposition of this file: replacing the old content in place; no separate archive copy is
needed because this section records the delta. The old revision remains in git history.

### 3.1) Interlock with the LLM router plan (approved 2026-09-21)

`plans/version-2/openrouter_llm_router_architecture.md` changes how every combat
provider call is made: its Phase 2 Tier 1 migrates the 9 `combat_manager.py` call sites
to `llm.call()`, one task id per call site. The two plans share a file, so their order is
fixed by owner decision (2026-09-21) as follows. The execution mapping onto OpenSpec
changes and gates is tracked in `plans/combat-openrouter-alignment.md`.

| Step | Work | Change owner |
|---|---|---|
| 1 | Combat Phase 0 latency baseline and turn trace | this plan |
| 2 | Router Phase 0 (config/factory) + Phase 1 (facade, bake-off) | router plan |
| 3 | Combat Phase 1 decomposition into `core/combat/` | this plan |
| 4 | Router Phase 2 Tier 1 migration: combat trio, `main.py`, `action_handler.py` | router plan |
| 5 | Combat Phase 2 latency hot path | this plan |
| 6 | Router Phase 2 remaining tiers + Phase 3 cleanup | router plan |
| 7 | Combat Phase 3 hardening (may overlap step 6) | this plan |

Three consequences are folded into the phases below:

1. **Timeout ownership moves to the router.** Combat Phase 2 no longer adds per-call
   `timeout=` arguments; the router's Phase 0 client-level `httpx.Timeout` in
   `create_chat_client()` binds every call. Combat Phase 2 verifies coverage instead of
   forking a second timeout path.
2. **Decomposition precedes migration.** The router migrates named stage calls instead of
   editing inside a 2,492-line function, which is the cheapest risk reduction for the
   router's highest-traffic Tier 1 target.
3. **The baseline is captured before the model swap.** Phase 0 measures the current
   OpenAI stack; a baseline taken after the router/model change would confound model and
   structure.

**Decision-primitive (Jev) position.** The router's `llm.decide()` primitive is gated:
the Phase 0 eval failed its promotion gate (0.677/0.704 agreement, 23-29% false-negative
rate) and the primitive is not authorized. This plan therefore provisions only the seams
a future `jev-combat-validator-residual` or PC-action classifier would plug into:
Phase 0 decision trace events, the Phase 1 PC-action decision seam
(`core/combat/decisions.py`), and the Phase 2 `decide_validation_routing()` function. No
Jev code, config, or dependency enters these phases.

---

## 4) Current state diagnosis (evidence)

Measured during reconnaissance on 2026-09-21.

### 4.1 Structure

| Finding | Evidence |
|---|---|
| Mega-function | `_run_combat_simulation_internal` = 2,492 lines (`combat_manager.py:2929-5421`) |
| Main loop | `while True` = ~1,730 lines (`combat_manager.py:3690-5420`) |
| Loop complexity | 35 `continue`, 22 `break`, 24 `if multi_pc_manager` branches, 5 `encounter_data =` rebinds |
| Procedural shape | 51 top-level functions, zero state class (one exception class at line 499) |
| MP class shape | `multi_pc_combat.py`: `CombatStateManager` (264), `TurnQueueManager` (509), `MultiPCCombatManager` (835), total 2,751 lines |
| Import surface | Only ~10 non-test files import the combat modules, so a package move with shims is cheap |

### 4.2 Latency and waste (static audit)

| Finding | Evidence |
|---|---|
| LLM-backed per-message compression on every attempt | `CombatCompressor` uses `create_chat_client()` + `NARRATIVE_COMPRESSION_MODEL` (`core/ai/combat_compression_engine.py:101-153`); wrapped by `CombatUserMessageCompressor` with a 4-worker pool and a JSON cache file (`core/ai/combat_compressor.py:28-160`); invoked via `process_combat_conversation` on each combat attempt |
| Unconditional debug dumps per attempt | `combat_messages_to_api.json` (4879/4897/4916), `validation_messages_to_api.json` (1407), `debug/api_captures/combat_messages_to_api.json` (3424/3452/3603), `debug/debug_ai_response.json` (4943) |
| Incomplete timeout coverage | 6 `.create()` sites still lack `timeout=`: 1851, 2786, 3428, 3456, 4883, 4901 |
| Per-iteration encounter resync | `sync_active_encounter()` reads `party_tracker.json` twice, reads the encounter and character files, and writes the encounter back (`combat_manager.py:2060-2153`, called at loop top ~3709) |
| History mutation per turn | Literal-index rewrites of `conversation_history[2]`, `[3]`, `[4]` at 3147, 3151, 3153, 3161, 3729, 3744 |
| Duplicate persistence paths | 17 `save_json_file` + 9 `safe_write_json` call sites inside the loop body |
| Validation cost | 1 validation provider call per turn, up to 5 internal attempts; `should_skip_llm_validation` exists (`utils/validation_routing.py:292`) but is not wired into combat |
| Round compression cadence | `compress_old_combat_rounds` runs once per round boundary (5210) - correct cadence; the problem is the separate per-message compressor |

### 4.3 Code-quality debt (feeds Phase 1 cleanup)

| Finding | Evidence |
|---|---|
| Dead top-level functions | `load_monster_stats@465`, `write_debug_output@647`, `create_consolidation_prompt@693`, `merge_updates@1957` (name-based repo scan: zero references) |
| Possibly dead public API | `set_combat_callback@multi_pc_combat.py:2582` (verify against documented test/context-manager API before removal) |
| Error hygiene | 13 bare `except:` and 57 `except Exception:` in `combat_manager.py` |
| Logging | 116 `print()` calls in `combat_manager.py` |
| Global state | `global _active_combat_session_id` (combat_manager), `_active_combat_manager` / `_combat_callback` (multi_pc) |
| Risky exit path | `sys.exit(0)` at `combat_manager.py:4278` inside the combat loop region (verify intent; must not kill a library call path) |
| Duplicated narration logic | `_pick_template` in `utils/combat_pc_action_parser.py:82` mirrors template selection in `multi_pc_combat.py:106-135` |

### 4.4 Existing assets to build on

- Deterministic fast lane infrastructure: `COMBAT_FAST_DETERMINISTIC_NARRATION = True`
  (`model_config.py:52`, consumed at `multi_pc_combat.py:1356`).
- NL PC-phase parser ready but OFF: `COMBAT_PC_PHASE_NL_FAST_PATH = False`
  (`model_config.py:53`); parser at `utils/combat_pc_action_parser.py` (28 tests).
- Deterministic guards: `utils/combat_phase_integrity_precheck.py` (14 tests),
  `utils/deterministic_mechanics_precheck.py`.
- Validation routing helpers including the unused skip decision.
- Combat test surface: `test_multi_pc_combat.py` (74 tests), `c5_regression_combat.py`
  (59), `test_combat_pc_action_parser.py` (28), plus ~16 more combat/encounter suites.

---

## 5) Target architecture

### 5.1 Package layout (recommended)

```
core/combat/
  __init__.py        Public API re-exports (run_combat_simulation, validate_combatant_integrity, ...)
  session.py         CombatSession: encounter, multi_pc manager, history, active PC, phase
  turn.py            9 stage functions extracted from the 1,730-line loop
  commands.py        Deterministic fast lane: /init /end /att /dmg /pass /end_combat
  decisions.py       PC-action decision seam: shared hook contract (deterministic parser now, decision-primitive adapter later)
  prompts.py         Prompt selection and mtime-cached read_prompt_from_file
  validation.py      validate_combat_response + compact truth pack + phase-precheck glue
  persistence.py     Single per-turn commit path (characters staged, encounter written last)
  narration.py       Deterministic templates and LLM narration, shared with the NL parser
  multi_pc/
    __init__.py
    state.py         Combatant / PCCombatState / CombatStateManager
    turn_queue.py    TurnQueueManager
    manager.py       MultiPCCombatManager facade, lifecycle, accessors, event emit
    sync.py          From combat_state_sync.py (95 lines)
    dm_note.py       Head context, initiative tracker, party turn summary, ledger formatting
```

### 5.2 Compatibility shims

Thin re-export modules remain at the old paths so runtime imports and tests keep
working during and after migration:

- `core/managers/combat_manager.py` -> `core/combat` public API
- `core/managers/multi_pc_combat.py` -> `core/combat.multi_pc`
- `core/managers/combat_state_sync.py` -> `core/combat.multi_pc.sync`

Shims carry `# TABLETOP MODE:` markers and a deprecation comment. Importers
(`core/ai/action_handler.py`, `main.py`, `module_debugger.py`) migrate incrementally;
tests may stay on the shim paths until their ownership moves.

### 5.3 What moves, what stays

- Moves into `core/combat/`: `initiative_tracker_ai.py` (referenced only by
  `combat_manager.py:4608`), the three combat manager modules above.
- Stays in `core/managers/`: `status_manager.py` (used by `core/ai/*`, `web/`, `main.py`,
  `utils/startup_wizard.py` and more), `storage_manager.py`, other non-combat managers.

### 5.4 Layout decision rationale

- Repo convention is `core/<domain>/` (`core/ai`, `core/memory`, `core/validation`);
  `core/managers/` is the cross-cutting bucket, not a home for a combat subsystem.
- Multi-PC combat is the fork's defining product surface; it should be a first-class
  domain package, not a nested manager namespace.
- ~10 importers total means shims fully absorb the move with zero runtime risk.
- Alternative considered: `core/managers/combat/` keeps the manager namespace but nests
  managers inside managers and leaves combat split across sibling files. Rejected as the
  weaker fit (see open decision D1).

---

## 6) Phase plan

Each phase becomes one OpenSpec change. All phases are latency-gated, not just
test-gated: every phase must show measured provider-call and p50 improvement (except
Phase 0/1, which establish measurement and structure). Execution order is interleaved
with the router plan per section 3.1; the combat-owned changes themselves stay in the
order below.

### Phase 0 - Latency baseline (`combat-latency-baseline`)

Deliverables:

- Gated per-turn trace (`debug/combat_turn_trace.jsonl`): provider calls by site with
  latency and tokens; compression calls and cache hit rate; file reads and writes;
  stage wall-clock timings; NL fast-path hit/miss.
- Decision events in the trace schema: `decision_point`, `decision_source`
  (`deterministic` | `llm_fallback` | `jev`), `decision_latency_ms`, and
  `provider_call_avoided`, so a future decision-primitive classifier can be evaluated in
  shadow mode without new instrumentation.
- Summary report script (provider-free) printing the tables used for target ratification.
- Fixed smoke fixtures: MP 4 PCs x 3 rounds + 1 enemy batch; 1-PC party x 1 round.

Exit criteria:

- Baseline captured and recorded in the change; latency targets ratified or adjusted by
  the owner.
- Trace is opt-in and adds no measurable overhead when disabled.

### Phase 1 - Decomposition and fortification (`combat-manager-decomposition`)

Behavior-preserving. No prompt changes. No rules changes.

Deliverables:

1. `core/combat/` package created with the layout in section 5; shims in place.
2. `_run_combat_simulation_internal` split into 9 stage functions: input/phase gate ->
   fast-lane commands -> PC-action decision seam -> head-context/prompt assembly ->
   provider call and retry ladder -> validation -> action apply and commit -> phase/turn
   transitions -> narration and output.
3. `CombatSession` owns encounter, manager, history, active PC, and phase; mutable
   globals and literal `conversation_history[N]` rewrites are removed (payload is built
   from state instead of mutated into history).
4. Cleanup slice:
   - remove the 4 dead functions; verify and remove `set_combat_callback` only if the
     documented test API does not need it;
   - replace bare `except:` with specific or `except Exception` plus logging;
   - convert combat `print()` telemetry to `enhanced_logger` (keep `[COMBAT_LOOP]`
     diagnostic strings stable where tests anchor on them);
   - dedupe narration template selection between the NL parser and the MP facade;
   - audit `sys.exit(0)` at line 4278 and replace with a structured exit result if it
     can terminate a library call path.
5. Source-contract tests repointed to the new modules (approved; never weaken
   assertions, only relocate their anchors).
6. Decision-seam contract: `core/combat/decisions.py` owns the single hook between the
   fast lane and prompt assembly. Its result status distinguishes `declined` (decided
   not a PC action) from `unavailable` (no decision available); both fall through to the
   LLM path today while remaining distinct in telemetry. Provider-call budget assertions
   are upper bounds (`<=`), never exact equality.

Exit criteria:

- All combat suites green: `test_multi_pc_combat` (74), `c5_regression_combat` (59),
  `test_combat_pc_action_parser` (28), `test_combat_phase_integrity_precheck` (14), and
  the remaining combat/encounter suites (~16 files).
- Prompt text byte-identical (diff-verified).
- 1-PC party and multi-PC party smoke pass; phase markers, death saves, initiative gate, roster integrity,
  enemy batch, surrender/exit, and resume replay all verified.
- Line counts: `combat_manager.py` shim < 100 lines; no single function > 600 lines.
- Decision-seam status contract asserted in tests (`declined` vs `unavailable`), with
  provider-call budgets written as upper bounds.

### Phase 2 - Latency hot path (`combat-latency-hot-path`)

Ordered by expected latency win. Item 8 is owner-confirmed in scope; item 1 is amended to
verification because timeout ownership moves to the router (section 3.1).

1. **Verify timeout coverage (amended 2026-09-21).** Per-call `timeout=` additions are
   superseded by the router's Phase 0 client-level `httpx.Timeout` in
   `create_chat_client()` (section 3.1). Phase 2 verifies every combat provider call is
   bound by the client default or an explicit timeout, and removes the three legacy
   `COMBAT_API_TIMEOUT_SECONDS` arguments during router migration. Do not fork a second
   timeout path; if the router change has not landed when this phase starts, treat that
   as a blocker for the phase, not a reason to duplicate it.
2. **Compression rework.** Remove per-message, per-attempt LLM compression.
   Compress completed rounds once at the round boundary; deterministic truncation for
   rounds older than the retention window; keep the LLM round compression only for the
   boundary round. Preserve or delete the now-unneeded message cache deliberately
   (cache corruption history argues for deleting it once unused).
3. **Gate debug dumps.** All per-attempt JSON dumps behind the debug flag; remove the
   CWD `combat_messages_to_api.json` write.
4. **Wire validation skip.** Use `should_skip_llm_validation` plus expanded
   deterministic-mechanics-only coverage; cap the validation retry ladder (5 -> 2) for
   deterministic-failure classes. Implement as one named function
   (`decide_validation_routing() -> (skip, reason)`) in `core/combat/validation.py` with
   telemetry passthrough. This is the designated insertion point for a future
   decision-primitive residual classifier; namespace future reasons (`jev_residual_ok`,
   `jev_unavailable_fallback`, `jev_low_confidence`) so the contract shape does not
   change later.
5. **Head-context/DM-note caching.** Memoize formatted strings keyed on
   (round, phase, active PC, encounter revision) for `format_multi_pc_head_context`,
   `format_initiative_tracker`, `format_party_turn_summary`,
   `format_pc_context_for_prompt`, and the PC phase ledger.
6. **Encounter sync once per turn.** Guard `sync_active_encounter` to one call per turn,
   remove duplicate `party_tracker.json` reads, and write the encounter only when state
   actually changed.
7. **Provider retry shape (amended 2026-09-21).** Connection reuse is already provided
   by the shared factory client, and provider/fallback retry plus latency logging move to
   the router (section 3.1). Combat retains the domain policy only: reasoning escalation
   conditional on validation failure class, passed through the router's
   `retry_tier`/reasoning override (router plan `finalize_chat_params`) so escalation
   parity survives migration.
8. **Canary the PC-phase NL fast path.** Enable `COMBAT_PC_PHASE_NL_FAST_PATH` in MP with
   telemetry (parse hit, miss, false-positive, fallback to LLM), expand deterministic
   narration to cover parsed actions (attack, heal, magic missile, movement), and keep
   automatic LLM fallback on any parse miss. A parseable PC action should complete
   without a provider call. The seam is `core/combat/decisions.py`; telemetry must
   distinguish a parse miss from a decision `unavailable`.

Exit criteria:

- Ratified latency targets met on the fixed MP smoke (4 PCs x 3 rounds + enemy batch)
  and no 1-PC party regression.
- Provider calls per uncontested PC action reduced to the ratified target
  (provisional: <= 1 on the fast path, <= 2 on the LLM path).
- Validation skip rate and NL fast-path hit rate reported with telemetry.
- All combat suites still green.

### Phase 3 - Structural hardening (`combat-turn-commit-and-receipts`, optional `combat-typed-resolver-expansion`)

Behavior-reviewed (not byte-identical) hardening that locks in latency wins.

Deliverables:

1. Single commit path: stage events, write character files, then write the encounter
   last; persist turn receipts and applied IDs; make resume idempotent on replay
   (formalizes the existing resume replay guards).
2. Consolidate code-owned round advancement: existing round-start markers
   (`roundStartsWith`, opening-batch flags) become the single authority; the LLM
   narrates outcomes only.
3. Optional second change: typed deterministic resolver expansion for attack, damage,
   and save flows (reusing the NL parser, `deterministic_mechanics_precheck`, and rolls
   infrastructure), including enemy-batch coverage where safe.
4. Explicit non-goal: declarative effects/condition lifecycle is out of scope and would
   be its own future proposal.

Exit criteria:

- Crash/restart mid-turn converges with no duplicate mechanics (idempotence verified).
- Round advancement cannot be driven by prose.
- All suites green; 1-PC party and multi-PC party smoke pass.

---

## 7) Multi-PC compliance gate

Every phase closes against this gate. A phase fails if any item regresses.

Correctness invariants:

- Phase 1 initiative gate (`/init`) and `roundStartsWith` behavior.
- Opening enemy batch marker set/clear via both `/init` and round-start paths.
- Deterministic death-save gate (prompt, actor validation, roll resolution).
- Roster integrity: no duplicate PCs, no missing party members, PCs never DM actors.
- Enemy batch determinism and inactive-combatant filtering.
- Surrender/exit flow and combat-end handoff.
- Resume replay guards: no reapplied enemy damage, no duplicate rewards.

Latency gate:

- 4-PC smoke: per-phase measured improvement where the phase claims one; no phase may
  increase provider calls or per-turn file writes.
- Deterministic paths measured separately from LLM paths.

---

## 8) Verification commands

Compile and focused suites (use the venv interpreter per repo policy):

```bash
.venv/bin/python -m py_compile core/managers/combat_manager.py core/managers/multi_pc_combat.py \
  core/managers/combat_state_sync.py utils/combat_pc_action_parser.py \
  utils/combat_phase_integrity_precheck.py utils/deterministic_mechanics_precheck.py
.venv/bin/python -m unittest -q scripts.test_multi_pc_combat
.venv/bin/python -m unittest -q scripts.c5_regression_combat
.venv/bin/python -m unittest -q scripts.test_combat_pc_action_parser
.venv/bin/python -m unittest -q scripts.test_combat_phase_integrity_precheck
```

Baseline and trace (Phase 0 artifacts):

```bash
.venv/bin/python scripts/combat_latency_report.py --trace debug/combat_turn_trace.jsonl
```

Hygiene gates before commit:

```bash
python3 scripts/check_ascii_compliance.py --summary-only
git diff --check
```

OpenSpec validation per phase change:

```bash
openspec validate <change-name> --strict
```

---

## 9) Risks and mitigations

| Risk | Mitigation |
|---|---|
| NL fast path misattributes an action to the wrong PC | Strict actor matching, telemetry, automatic LLM fallback on any miss, canary rollout with false-positive reporting |
| Compression rework degrades narration quality | LLM compression retained for the boundary round; deterministic truncation only for stale rounds; compare narration fixtures before/after |
| Source-contract tests fail during the move | Pre-built migration matrix; repoint anchors deliberately; never weaken assertions |
| Validation skip lets a mechanical contradiction through | Skip only when deterministic prechecks pass on a purely-mechanical action set |
| Decomposition changes gameplay under MP phase pressure | Prompts byte-identical in Phase 1; MP compliance gate run every phase; small phase-scoped commits |
| Cache corruption in the compression cache | Delete the legacy caches once unused; any surviving cache is hash-keyed and validated on load |
| 1-PC party regression | Shims preserve every public path; 1-PC party smoke is a hard gate (ADR-0032) |
| Router slip delays timeout coverage | Section 3.1 delegates per-call timeouts to the router; if `llm-router-facade` has not landed when Phase 2 starts, escalate inside the router change rather than adding a parallel combat timeout path |
| Decision seams accrete Jev scope | Seams stay contract-only (status vocabulary, trace events, named functions); no Jev code, config, or dependency may enter Phases 0-3 |

---

## 10) Rollback strategy

- One OpenSpec change per phase; commit slices inside each phase.
- Phase 1 is structural only, so revert is safe by commit range.
- Phase 2 items are flag-independent except the NL fast path, which reverts by setting
  `COMBAT_PC_PHASE_NL_FAST_PATH = False`.
- Phase 3 receipts are additive fields; older encounter files keep loading (additive
  schema rule).

---

## 11) OpenSpec mapping and build order

Combat-owned changes in execution order (interleaved with router-plan changes per
section 3.1):

| Order | Change | Phase | Nature |
|---|---|---|---|
| 1 | `combat-latency-baseline` | 0 | Observability only |
| 2 | `combat-manager-decomposition` | 1 | Behavior-preserving move and extraction |
| 3 | `combat-latency-hot-path` | 2 | Latency engineering |
| 4 | `combat-turn-commit-and-receipts` | 3a | Reliability hardening |
| 5 | `combat-typed-resolver-expansion` | 3b (optional) | Deterministic resolver breadth |

Interleaved router-plan changes: `llm-router-facade` (router Phase 0/1) executes between
combat changes 1 and 2; the router's Phase 2 Tier 1 combat migration executes between
combat changes 2 and 3; the router's remaining migration executes alongside combat
changes 4-5.

Build order decision (D4, decided 2026-09-21): author all five combat OpenSpec artifacts
first, then execute in the sequence above with planner verification between phases.

Future Jev changes (`jev-decisions-primitive`, `jev-action-predictor-promotion`,
`jev-combat-validator-residual`) are owned by the router plan's Workstream C and remain
gated; they plug into the seams created here and are not part of this plan's build order.

---

## 12) Decisions and open items

| ID | Decision | Status |
|---|---|---|
| D1 | Package location | Recommended: `core/combat/` with `core/combat/multi_pc/` and shims at the old `core/managers/` paths. Alternative: `core/managers/combat/`. Pending owner confirmation. |
| D2 | Latency targets | Accepted (2026-09-21): provisional targets in section 1.1, ratified after the Phase 0 baseline. |
| D3 | Scope confirmations | Amended (2026-09-21): NL fast-path canary confirmed in Phase 2; per-call timeout completion delegated to the router's client-level timeout (section 3.1). |
| D4 | Build order | Decided (2026-09-21): author all five combat artifacts first, then execute in the interleaved order of section 3.1 with planner verification between phases. |
| D5 | Subagent execution | `openspec-builder-heavy` is manual-invocation-only; otherwise use the standard OpenSpec build loop with planner verification per task. |
| D6 | Decision-seam placement | Decided (2026-09-21): fold contract-level seams into the owning phases (Phase 0 trace events, Phase 1 `decisions.py`, Phase 2 `decide_validation_routing()`); no separate pre-Jev change. |

---

## 13) Acceptance criteria (plan level)

1. Latency targets ratified in Phase 0 are met on the fixed MP smoke at the end of
   Phase 2, with no provider-call or file-write regressions in any phase.
2. Multi-PC compliance gate passes at every phase close.
3. `core/combat/` package owns the combat runtime; old paths are thin shims; no single
   combat function exceeds 600 lines.
4. 1-PC party and multi-PC party smoke pass; prompts byte-identical through Phase 1.
5. All existing combat suites remain green throughout.
6. Upstream remains untouched and unmerged; only the four concepts in section 2 enter
   the fork, expressed as fork-native work.
7. The interleaved order in section 3.1 is followed; combat takes its provider timeout
   from the router client, and no Jev code, config, or dependency enters Phases 0-3.
