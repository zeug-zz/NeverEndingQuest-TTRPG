# Capture Arena - Gameplay UX Capture Rig (Tiers 1-5)

Status: ACTIVE - bounded rollout capture prerequisites approved; broader tiers remain planning
Date: 2026-10-14
Owner: Dev tooling / gameplay QA
Related:

- `.opencode/skills/neq-capture-arena/SKILL.md` - the runbook/skill (primary socket path + browser appendix)
- `openspec/changes/archive/2026-09-22-combat-latency-baseline/` - completed rig and G1 baseline
- `openspec/changes/combat-manager-decomposition/` - required bounded G3 scenario/evidence tasks
- `plans/combat-openrouter-alignment.md` - primary-owned G3/G4/G5/G7/G9/G10 matrix; candidate bake-off already accepted
- `plans/version-2/openrouter_llm_router_architecture.md` - model/stack decisions the rig can measure
- `adrs/0032-single-tabletop-runtime.md`, `adrs/0031-independent-development-fork.md`

This document describes what the rig can do today, then outlines five open-ended
extension tiers. The intent is that future v2 test scenarios (encumbrance checks,
Titan/Chaos weather, spell use, Jev decisions) are authored as scenario data and
expectations, not as new test infrastructure.

The owner-approved 2026-10-14 workflow update promotes only the small scenario/
assertion subset needed for the current rollout. It does not approve full Tiers
1-5, new gameplay, a Titan runtime, Jev, browser instrumentation or a new runner.
The rollout is paused until the owner resumes it; this documentation change is
not implementation of those capture tasks and contains no new live verdicts.

---

## 1) Current capabilities (built and verified 2026-09-22)

### 1.1 Components

| Component | Path | Role |
|---|---|---|
| Capture module | `modules/Capture_Arena/` | Tiny validated arena: CA01 Waystone Gate (start), CA02 Training Pit (Goblin group), CA03 Reliquary Alcove (Warden Mira NPC, shrine/offering-bowl features, DC-annotated locked cellar door), CA04 Supply Cellar |
| Sandbox seeder | `scripts/seed_combat_capture.py` | Lean ~52 MB copy at `tmp/combat_capture/`, `--prepare`/`--restore`, `--party 4\|1`; patches sandbox `WEB_PORT = 8360` and `ENABLE_COMBAT_TURN_TRACE = True`; seeds party, character files, resumable encounter (`worldConditions.activeCombatEncounter`); installed tree hash-verified untouched |
| Capture driver | `scripts/capture_drive.py` | Socket-driven: `start_game`, `user_input` with `character`, `POST /api/party/set_active`; per-turn completion = first new `game_output` then processing-aware quiet window; `/init` fallback; transcript logging; trace preservation |
| Trace writer | `utils/combat_latency_trace.py` | Opt-in (`ENABLE_COMBAT_TURN_TRACE`, default OFF), fail-open, thread-safe bounded JSONL at `debug/combat_turn_trace.jsonl` |
| Combat instrumentation | `core/managers/combat_manager.py`, `core/managers/multi_pc_combat.py`, `core/ai/combat_compression_engine.py`, `core/ai/combat_compressor.py` | Provider sites, stage timings, decision events, compression cache events, file operations, turn/mode context |
| Report | `scripts/combat_latency_report.py` | Provider-free CLI: input summary, stage timings, provider by site, compression hit rate, file operations, decisions, fixture summaries |
| Skill/runbook | `.opencode/skills/neq-capture-arena/SKILL.md` | Preconditions, port discipline, scenario scripts, preserve/report/teardown steps, extension points, browser alternative appendix |

### 1.2 Verified evidence (G1 baseline)

| Capture | Trace | Records | Steps | Timeouts | Elapsed |
|---|---|---|---|---|---|
| 4-PC party, 3 rounds + enemy batch | `tmp/combat_baseline_mp.jsonl` | 266 | 19 | 0 | 188.1 s |
| 1-PC party, 1 round + enemy phase | `tmp/combat_baseline_one_pc.jsonl` | 69 | 4 | 0 | 75.6 s |

Numbers and target assessment are recorded in
`openspec/changes/archive/2026-09-22-combat-latency-baseline/design.md`
(Gate G1 Baseline). Preserve these historical files and model identity; new
captures use unique `tmp/router-rollout/<gate>/<run-id>/` directories.

### 1.3 Skill coverage vs current gaps

The skill describes execution and acceptance; the current default driver alone
does not cover the G3 contract. These gaps define future tiers, with only the
bounded required rollout subset promoted below:

| Gap | Reality today |
|---|---|
| Trace coverage | Combat-only; narrator/travel/dialogue turns produce transcripts with no stage/provider rows ("degraded evidence") |
| Scenario format | Fixed step lists inside `capture_drive.py::run_scenario()`; no external scenario data |
| Assertions | Capture + report only; no pass/fail of gameplay properties |
| Seeds | Party size + combat encounter; `worldConditions.weather` exists but is not parameterized |
| Client UX | Render/TTS/input affordance not measured; browser automation currently blocked by the session sandbox |

---

## 2) Design principles (keep it generic)

1. **Scenario data over code.** Future tests are scenario packs (inputs, seed
   profile, expectations), not driver edits.
2. **One driver, one trace, one report.** Extend event types and report
   sections; never fork parallel infrastructure.
3. **Test-first contracts.** A v2 feature (encumbrance, weather, spells, Jev)
   ships with its scenario + expectations as part of its acceptance.
4. **Observational only.** Zero product behavior change; the same opt-in,
   fail-open, zero-overhead-when-off contract as the combat trace.
5. **Sandbox discipline.** Everything under `tmp/`; port 8360 only; installed
   tree hash-verified untouched; never touch port 8357 or the user's campaign.
6. **Nondeterminism-aware assertions.** Property and threshold checks with
   tolerances; LLM output varies.
7. **Evidence honesty.** Degraded captures are labeled; results are never
   fabricated or extrapolated.

---

## 3) Extension tiers

### Approved rollout subset - before G3

Implement decomposition tasks 4.3 and 4.4 through the existing seeder/driver and
fixture/report helpers, with provider-free tooling tests. Add bounded named
`combat-smoke`, `initiative-pc`, `initiative-dm-tie`, `death-save`,
`surrender-exit` (two separate branches) and `resume-replay` cases for 1-PC/4-PC
parties. Wrong-actor death-save coverage applies to 4-PC; declare applicability
before execution. Preserve default fixed latency scripts for G5 comparability.
Scenario IDs/options are requirements, not already-implemented CLI features.

Capture initial/final sandbox state and check Python-owned effects, legal actors,
phase/round markers and no-duplicate replay. Preserve a manifest, transcript,
server log, trace/report, state snapshots and required-check results in each run
directory before teardown. Record scenario/seed/source-worktree and transport
identity, bounds and actual counts. Primary review produces PASS/FAIL/BLOCKED;
driver/report exit zero, timeout warnings or missing required evidence cannot PASS.
Do not copy credential/config values into evidence or call mocks live evidence.

The primary orchestrator runs and judges live captures after focused tests;
builders implement tooling/fixes only. Later G4/G5/G7/G9/G10 coverage is defined in
the alignment matrix and authored into each owning change before implementation.
Reuse this rig instead of creating a parallel runner or adding an extra rollout
phase. Completed G1 and owner-attested candidate selection remain accepted.

Broader external scenario formats, generalized narrator traces, optional LLM
judges, client metrics and matrix/CI orchestration remain unapproved future tiers.

### Tier 1 - Data-driven scenario packs

Current: scenarios are hard-coded in the driver.

Target: scenario files (for example `scripts/capture_scenarios/*.json`)
containing:

- `seed`: party size, starting location/area, world conditions (weather, time),
  inventory/load profiles, NPC presence toggles, encounter on/off.
- `turns`: ordered entries of `input` + `character` (+ optional `expect_hint`).
- `expect`: assertion hooks consumed by Tier 3.

The seeder accepts a scenario/profile id or patch file; the driver accepts
`--scenario <file>` and defaults to the existing combat pack for backward
compatibility.

Sketch:

```json
{
  "id": "travel-encumbrance-heavy",
  "seed": {"party": 1, "area": "CTR001", "location": "CA01",
           "conditions": {"weather": "Heavy Rain"}},
  "turns": [
    {"input": "travel to the Reliquary Alcove", "character": "Acheron"},
    {"input": "continue", "character": "Acheron"}
  ],
  "expect": [{"type": "state_delta", "path": "worldConditions.time", "changed": true}]
}
```

Enables: travel, weather, dialogue, skill-check, rest, and level-up scenarios
without touching driver code.

### Tier 2 - Generalized session trace

Current: combat-only trace; transcripts only for everything else.

Target: a session trace covering the narrator path under the same contract:

- Turn boundary events (`turn_start` / `turn_end`) and turn class (combat,
  travel, dialogue, check, rest, level-up).
- Narrator provider sites: `dm_main`, `dm_validation`, transition validation,
  summarizers.
- Action-handler stage timings and file operations.
- The report gains turn-class sections so every surface gets p50/p90 and
  provider-call counts.

Constraints: hot-path safety (opt-in, fail-open, no measurable work when off);
no prompt or routing changes.

Enables: UX/latency budgets per gameplay surface and provider-avoidance counts
per turn class - the measurement basis for travel/rest/dialogue optimizations.

### Tier 3 - Gameplay property assertions

Target: per-scenario expectations evaluated from three sources:

1. Transcript patterns (bounded substring/regex checks on observed output).
2. Post-run state deltas in the sandbox (`party_tracker.json`,
   `module_plot.json`, journal, character files, `worldConditions`).
3. Optional rubric/LLM-judge conformance checks for narrative quality
   (cost-capped, opt-in per scenario).

Assertion families (open-ended examples, not commitments):

- Mechanical invariants: encumbrance counted once per PC/NPC; travel time
  reflects load and forced march; spell slots and HP bookkeeping stay coherent.
- Narrative conformance: weather referenced when conditions say rain; Titan or
  Chaos-driven weather changes surface in narration; spell effects described
  consistently with the resolved action.
- Flow gates: DC surfaced before resolution; `requestRoll` pauses and resumes.

Nondeterminism: property-based checks with tolerances; exact-text assertions
are forbidden unless the output is deterministic.

Enables: test-first acceptance contracts for v2 features.

### Tier 4 - Perceived-feedback / client UX metrics

Current: server-side only; the browser path is blocked in the session sandbox.

Target options:

- (a) A lightweight `client_metrics` socket channel: existing JS paths emit
  bounded UI timings (send-to-render latency, TTS onset, input re-enable, tab
  switch, portrait popup) into the same trace.
- (b) Browser automation via the documented playwright appendix when a
  browser-capable environment is available.

Enables: server latency and perceived feedback in one evidence stream, so
combat turns can be optimized for both speed and UX.

### Tier 5 - Matrix runs and CI posture

Target:

- Scenario x party size x model-stack matrices for the router bake-off and
  Titan/Chaos variants, with artifact comparison across report runs.
- A provider-free mock-transport mode for CI structure checks; real-latency
  gates stay owner-run with a per-run provider-call cap.

Enables: stack decisions backed by identical scripts, plus cheap structural
regression coverage in CI.

---

## 4) Future scenario candidates (open-ended)

| Candidate | Feature dependency | What the rig provides | Tiers |
|---|---|---|---|
| Encumbrance per PC/NPC (background Python check) | New v2 feature | Load-seeded scenarios, travel turn budgets, single-application state assertions | T1 + T3 |
| Titan/Chaos weather patterns (Chao) | Titan v2 / chaos gameplay-JSON modifications | Seeded conditions, narration conformance, travel-impact metrics | T1 + T3 |
| Spell use in combat | Combat refactor progression | Scripted cast turns (shape, upcast, slots), provider/decision metrics | T1 (extend the combat pack) |
| Jev checks (decision assist) | Jev gate + decisions primitive | Shadow-mode comparisons of decision sources and avoided provider calls on identical scripts | T2 + T3 + T5 |
| Rest / level-up / dialogue / skill checks | Existing behavior | Session turn classes and state assertions | T1 + T2 |

---

## 5) Boundaries and non-goals

- The rig measures and verifies; it does not implement gameplay features.
- No product behavior change, prompt edits, or new runtime dependencies.
- Not a real-provider latency gate in CI (cost and nondeterminism); mock mode
  is structure-only.
- Browser automation remains a documented alternative, not a requirement.
- Traces and evidence stay under `tmp/` (gitignored); durable numbers belong in
  OpenSpec changes, never in `reports/`.
- One send at a time; captures are bounded and scripted.

---

## 6) Activation path

1. Required rollout subset: bounded scenario/evidence support in
   `combat-manager-decomposition`, followed by primary G3 captures when the goal
   is active. Subsequent gates reuse the same rig and add their owning criteria.
   The remaining generalized Tier 1 + Tier 2 work may be proposed separately
   (working name `gameplay-ux-capture-rig`); it is not a prerequisite for this goal.
2. Tier 3 per scenario family as features land, using the test-first pattern.
3. Tier 4 as its own change (touches JS and hot paths; needs its own budget
   discussion).
4. Tier 5 may support optional future model comparisons and v2 work; the accepted
   router candidate bake-off is not a required rerun.
5. The skill (`neq-capture-arena`) remains the single runbook: each tier
   updates it instead of adding parallel test infrastructure.

### G10: usage accounting and primary-owned live review

The cleanup change adds a read-only `/usage` projection: it reports router
totals and existing session/rolling-week rollups without making a provider
request or changing gameplay state. Router receipts own chat response cost
provenance. Actual costs are counted once; estimates are included only when
verified against the concrete resolved model; otherwise observed chat tokens
remain while the event is marked unpriced and cost coverage incomplete. Existing
media events remain cost-only and do not add chat tokens. Debug `token_update`
adds actual/estimated subtotals, unpriced counts, and completeness to session and
week rollups while preserving existing token statistics and safe defaults for
older payloads.

G10 requires one bounded full-session capture for each 1-PC and 4-PC party,
including narration, combat, save, restart/resume, `/usage`, and Debug
session/week provenance. Preserve each evidence bundle under
`tmp/router-rollout/g10/<run-id>/` before teardown, with the isolated real copy
under `tmp/combat_capture/`, port 8360, `NEQ_OPEN_BROWSER=0`, and the repository
venv. Retain scenario/party/seed/worktree/model-provider identity, transcript,
owned-server log, state/save evidence, and expected-versus-observed checks.
Review resumed state for duplicate mechanics, rewards, or chat costs. The
provider-free evaluator reports readiness only; only the primary orchestrator
may record PASS, FAIL, or BLOCKED after evidence review. Exit status, degraded
or synthetic evidence, and builder results cannot establish PASS.
