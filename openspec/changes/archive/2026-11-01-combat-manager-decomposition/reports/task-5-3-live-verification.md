# Task 5.3 - G3 Live Verification and Focused Failure Correction

Status: **G3 FAIL on the primary-owned 1-PC and 4-PC smoke runs. Task 5.3 remains unchecked; no live rerun was performed by this builder.**

## Parent-owned first-run evidence

- Run bundle: `tmp/router-rollout/g3/20261016T043910Z-smoke-p1/`.
- Scenario/party: `combat-smoke`, 1-PC (`Acheron`); 4 steps, 6 control requests,
  0 timeouts, 78 trace records, and 14 provider trace events (7 generation plus
  7 validation calls, as reported by the primary).
- The deterministic Goblin damage operation applied correctly: encounter HP
  changed from 20 to 18, matching 2 damage.
- The validated enemy response requested Acheron HP 20 to 12. The actual
  character persistence update failed schema validation because the fixture
  lacked required `character_role`; authoritative Acheron HP remained 20. The
  server log records the validation rejection and the consolidated-update
  failure. The prior report marked `accepted_logical_batch_once` PASS, but that
  reports batch/completion eligibility, not successful mechanical application.
  This is an attributable G3 FAIL, not a successful smoke or bake-off metric.
- The primary reports the server stopped, owned PID group 8360 cleared, and
  protected root hash unchanged. Raw diagnostics remain in the run bundle.

## Parent-owned 4-PC smoke evidence before the named-fixture correction

- Run bundle reported by the primary: `tmp/router-rollout/g3/20261016T053257.539138Z-combat-smoke-p4-f8a29394.19steps32controls0timeouts340records`.
- Parent-reported run counts: 19 steps, 32 control requests, 0 timeouts, and 340
  trace records. This is an attributable **G3 FAIL**, not evidence of a product
  policy defect. Correction to the prior builder note: the bundle is present at
  `tmp/router-rollout/g3/20261016T053257.539138Z-combat-smoke-p4-f8a29394/`;
  the earlier check used an incorrect directory name with the counts appended.
  Its `primary-review.json`, manifest, checks, report, trace, transcript,
  server log, and snapshots were read-only inspected and left unchanged.
- Vitreol's validated ammunition operation failed because `crossbow bolt` was
  not present in the named seed. Despite that failed ammunition operation, the
  separate character HP apply persisted Vitreol from 20 to 15; the other named
  characters remained at 20 HP. This confirms the character apply and
  trace-destination correction are working, but does not erase the ammunition
  failure.
- Kira exhausted three generations. The fixture's `nearest goblin` wording did
  not provide spatial evidence that could resolve the target; validators then
  conflicted between choosing and clarifying. This is recorded as a
  fixture-context deficiency, not a reason to reinterpret or change product
  policy, prompts, validators, or retry behavior.
- This section records the parent failure before any fixture correction. The
  primary's bundle/review data remain primary-owned and are not rewritten here.

## Focused correction implemented

- A separate focused compatibility fix routes `CombatCompressor.compress` through
  `get_chat_completion_params("compression", self.model,
  temperature_override=0.3)`. Before the fix, the direct `gpt-6-luna` SDK request
  kwargs were `model="gpt-6-luna"`, the unchanged two-message prompt, and
  `temperature=0.3`; that sampling field is rejected by the direct Luna API.
  After the fix, captured SDK kwargs retain `model="gpt-6-luna"` and the same
  messages, and carry `reasoning_effort="low"` plus `verbosity="low"`, with no
  `temperature` or `top_p`. The returned factory model key is removed before
  expansion, leaving the explicit `model=self.model` as the sole model argument.
  Focused provider-free tests also exercise legacy GPT-5 sampling omission,
  non-reasoning legacy temperature behavior, OpenRouter extension envelopes,
  and one-attempt error return of the original input. This corrects the API
  compatibility defect only; it does not revise the first-run G3 FAIL or
  substitute for the primary's required live rerun and remaining G3 matrix.

- Named PC character records are now full records composed only of fields
  accepted by the unchanged `schemas/char_schema.json`. They retain HP 20/20,
  AC 14, seeded initiative and zeroed death saves; ability defaults are explicit
  10s, XP is explicitly 0, and schema-valid empty equipment/features/slots are
  present. No `resources_known` property is serialized. Bare legacy fixture
  payload generation and the bare seeder path remain unchanged.
- Fixture tests validate named PC records for every named profile and party
  shape, and validate the seeded allied NPC/party/encounter records against their
  real schemas. No installed character file is read.
- The persistence owner now emits `ENABLE_COMBAT_TURN_TRACE`-gated observations
  of actual character and encounter apply returns, failures, operation/target
  metadata, returned encounter state, and character state already read by the
  existing synchronization path. The existing order, return values, failure
  handling and read behavior are unchanged; there is no update replay or new
  default trace write.
- Evidence evaluation includes a required `mechanical_apply_outcomes` check.
  Any observed false/exceptional application fails the check and prevents
  automated READY/PASS even when response validation and eligible-batch checks
  pass. This does not turn prose into mechanical evidence.
- Unambiguous applied `hp_delta` operations are reconciled against canonical
  before/after snapshot HP for the named character or encounter creature. If the
  corresponding canonical values are unavailable, evidence is BLOCKED; no result
  is inferred from narration.

## Verification performed by this builder

All commands were provider-free and used `OPENSPEC_TELEMETRY=0 DO_NOT_TRACK=1`
with project-local `TMPDIR="$PWD/tmp"` and `PYTHONPYCACHEPREFIX="$PWD/tmp/pycache"`.

- `scripts.test_capture_drive` -> 28 tests PASS. Includes all named PC profile /
  party schema validation, seeded allied-NPC/party/encounter schema validation,
  unchanged bare fixture checks, and a regression where validation and logical
  batch completion pass but a false character-update result forces automated
  FAIL.
- `scripts.test_combat_persistence_phase_stages` -> 11 tests PASS. New test
  applies Acheron HP 20 to 12 once through `apply_final_character_updates` with a
  fake persister, and checks success plus the already-read persisted HP in gated
  trace observations.
- `scripts.test_combat_latency_baseline` -> 24 tests PASS (separate process).
- `scripts.test_update_encounter_ops_runtime` -> 4 tests PASS (separate process).
- `scripts.test_combat_surrender_exit_flow` -> 4 tests PASS (separate process).
- `scripts.test_combat_runtime_prompt_authority` -> 7 tests PASS (separate process).
- `scripts.test_combat_expanded_deterministic_guards_contract` -> 16 tests PASS.
- `scripts.test_combat_decomposition_contract` -> 9 tests PASS; includes the
  static prompt parity assertions.
- `py_compile` of the six changed Python modules -> PASS.

No live server, API/provider call, prepare, installed-tree/root write, cleanup,
or full owner loop was run. The prior 5.1/5.2 checks remain historical evidence;
they were not rerun here. The full 627-test 5.2 set was not rerun. The primary
must rerun the affected live 1-PC case and complete the rest of the required G3
matrix before recording any final G3 verdict. Task 5.3 stays unchecked.

## Parent-owned second-run evidence and focused instrumentation correction

- Second run bundle: `tmp/router-rollout/g3/20261016T050604Z-smoke-p1-rerun/`.
  This remains a primary-owned **G3 FAIL**, separate from and in addition to the
  first-run failure above; neither run bundle nor its diagnostics were repaired
  or rewritten by this correction.
- In this run, the valid named-PC deterministic operation applied Acheron's HP
  20 to 12 successfully. The subsequent `combat_apply_persisted_state`
  observation appended trace JSONL bytes to the character JSON file, and a
  later reader failed with `ExtraDataJSON`.
- Root cause: `trace_combat_observation` forwarded observation metadata with
  `**fields` into `emit_trace_event`, whose legitimate lower-level `path`
  parameter selects the output destination. The persistence caller supplied
  `path` intending state-file provenance, so the metadata was interpreted as
  trace-output routing.
- The owner now names that observation metadata `state_path`. The observation
  wrapper defensively relabels any legacy/future `path` metadata as
  `legacy_path_metadata`; only `emit_trace_event` retains its explicit output
  path API. The default-off gate and all state/persistence behavior remain
  unchanged. The malformed owned file is retained at
  `tmp/router-rollout/g3/20261016T050604Z-smoke-p1-rerun/retained-malformed-acheron.json`;
  it was not repaired or removed. The primary reported the server stopped,
  owned PID group 8360 cleared, and no further live run is authorized for this
  builder.

- Focused provider-free verification for this instrumentation correction:
  `scripts.test_combat_trace_observation_writer` -> 1 PASS using a real default
  trace writer in a unique project-local temporary CWD, an owned schema-valid
  Acheron JSON record, the persistence owner's actual state reader, and legacy
  metadata targets shaped as a state file, stdout, database, and redirect JSONL.
  The Acheron bytes remained identical; the trace metadata retained
  `state_path` and each `legacy_path_metadata`; only
  `debug/combat_turn_trace.jsonl` was appended; none of the supplied metadata
  targets was created. The regression does not mock `emit_trace_event`.
- Fresh focused suites, each in its own process with `OPENSPEC_TELEMETRY=0
  DO_NOT_TRACK=1`, passed: Capture_Arena driver 28, combat latency baseline 24,
  phase integrity 14, persistence phase stages 11, lifecycle/decomposition
  contract 34, prompt/decomposition contract 9, runtime prompt authority 7,
  and C5 regression 59. The new real-writer regression was run separately.
- `py_compile` of both changed implementation modules and the new regression
  test passed; `scripts/check_ascii_compliance.py --summary-only` scanned 1,131
  files with zero violations; scoped `git diff --check` passed; the AST limit
  check found no combat function over 600 lines and confirmed the shim remains
  17 lines; `OPENSPEC_TELEMETRY=0 DO_NOT_TRACK=1 openspec validate
  combat-manager-decomposition --strict` passed.
- These code-level checks do not change either primary G3 FAIL, repair the
  retained malformed file, or mark Task 5.3 checked. No G3 PASS is claimed.

## Named fixture correction for the parent 4-PC smoke failure

- Updated only the named fixture path in `scripts/combat_latency_fixtures.py`.
  The fixed legacy `_character_payload`, bare fixture seeds, and latency command
  strings are unchanged. Named PCs carry schema-valid `equipment` records:
  Acheron/Merisiel have the declared training blade, Kira a shortsword, and
  Vitreol a light crossbow plus `ammunition: [{name: "crossbow bolts",
  quantity: 3, description: ...}]`. This uses the existing
  `schemas/char_schema.json` field shapes; no installed character records,
  schema, ability, or new field were added. Fixture gear is setup data, not a
  gameplay/equipment feature.
- The focused test validates all named PC records for both party shapes and all
  named profiles against the actual character schema. It invokes the existing
  pure `_apply_character_ops_deterministic` helper with the real
  `inventory_remove` operation whose item is the singular `crossbow bolt`;
  existing name normalization resolves it against the stored plural
  `crossbow bolts`. The asserted quantities are 3 -> 2 -> 1 -> 0, then the
  fourth removal fails closed with the helper's actual "cannot remove
  ammunition not present" result and unchanged state. No always-success stub is
  used; the module's client factory is replaced before import with a dummy
  object, and the surrounding test's SDK/network/write tripwires remain armed.
- Named smoke facts are generated per party shape and stored in the named
  profile's seed identity and encounter `encounterSummary`. A 1-PC seed names
  only Acheron and Goblin. A 4-PC seed states Goblin Alpha is the nearest goblin
  to Kira and within reach, Goblin Beta is farther from Kira, and Vitreol
  targets Beta. Both allied/inactive variants add only their seeded Blairen and
  defeated Inactive Goblin facts; the latter is expressly excluded from active
  hostile/nearest-target eligibility. Inspection confirmed this supported field reaches the
  actual encounter prompt: `core/combat/bootstrap.py` writes
  `dependencies.filter_encounter(encounter_data)` into "Encounter Details", and
  `core/combat/combat_manager.py::filter_encounter_for_system_prompt` retains
  `encounterSummary`; `core/combat/turn.py` refreshes that same filtered
  context from the current encounter. The validation path receives the same
  encounter object (`core/combat/validation.py` calls its injected
  `truth_pack_builder(..., encounter_data)`); the existing truth pack uses its
  creature roster as the allowlist and does not create a geometry/resolver
  policy. No fact was placed only in an unprojected field. Neither driver input
  wording, prompts, validators, model behavior, nor retry policy changed.
- Parent failure counts and actual HP outcomes above remain recorded as the
  pre-correction G3 FAIL. This builder did not run a live matrix, server,
  `--prepare`, full owner loop, or change any parent-owned bundle/review data.

## Verification performed for this correction

All provider-free commands used `OPENSPEC_TELEMETRY=0 DO_NOT_TRACK=1`; commands
that may use Python temporary directories set `TMPDIR=tmp` so scratch stays
inside the project. The first capture-suite attempt without that setting was
blocked by the existing write-outside-`tmp/` tripwire and by its assertion that
the named smoke seed remained empty; the assertion was updated for the intended
named-only identity facts and the suite was rerun under project-local `TMPDIR`.

- `scripts.test_capture_drive` -> 30 tests PASS (includes all named PC schema
  cases, the unchanged bare script contract, all 1/4-PC profile seeds through
  the actual seeder with a fake writer, projected context facts, exact evidence
  profile-contract positive/negative checks, forged seed/party rejection, and
  the real ammunition operation sequence).
- Separate processes PASS: expanded deterministic guards 16; combat latency
  baseline 24; runtime prompt authority 7; combat decomposition/source contract
  9; combat-manager decomposition/facade source contract 34. The previous
  focused persistence (11), encounter ops (4), surrender/exit (4), and multi-PC
  facade (73) checks remain as already-recorded evidence.
- `py_compile` on the fixture, seeder, evidence helper, and focused test files
  -> PASS.
- `scripts/check_ascii_compliance.py --summary-only` -> 1,132 files scanned,
  zero violations. Scoped `git diff --check` -> PASS.
- `OPENSPEC_TELEMETRY=0 DO_NOT_TRACK=1 openspec validate
  combat-manager-decomposition --strict` -> valid.
- No live run was attempted, no G3 PASS is claimed, and Task 5.3 remains
  unchecked. Primary-owned rerun and full matrix verdict remain required.

## Initiative-gate observation timing correction

- The primary-owned 1-PC and 4-PC initiative snapshots establish the expected
  mechanics independently of trace telemetry: `/init 21` is rejected without
  changing state; the subsequent `/init 18` against DM 8 resolves to
  `pcGroup`, clears `awaitingPcGroupRoll`, and leaves
  `openingEnemyBatchPending=False`. The 4-PC DM 8 / PC 8 tie resolves to
  `dmGroup`, clears `awaitingPcGroupRoll`, and leaves
  `openingEnemyBatchPending=True`. The existing individual-PC mechanical PASS
  remains retained; the earlier trace event is not evidence of the actual
  accepted transition because it was emitted before the controller applied it.
- `core/combat/turn.py` now emits rejected initiative observations after the
  pure calculation, preserving unchanged before/after state. Accepted
  observations are emitted only after the existing encounter/manager patch and
  both existing persistence calls, at the legacy controller point before
  opening batch processing. Their `after` values come from actual encounter
  state, `expected_winner` remains separate from actual `after.winner`, and the
  eligible non-PC cohort is read from the manager after application. No
  mechanics, mutation, persistence, SDK, or default-off trace policy was moved
  or added.
- Focused test `test_initiative_gate_observations_follow_applied_state` invokes
  the real `run_input_phase_gate` and pure `handle_group_initiative_gate` with
  fake manager/IO/save boundaries and an observation recorder that snapshots
  actual encounter state at emission. It checks invalid-state invariance,
  PC-win post-patch state and persistence order, and DM-tie post-patch pending
  marker state before invoking the actual opening-batch completion helper and
  verifying the later persisted marker clear.
- Verification with `OPENSPEC_TELEMETRY=0 DO_NOT_TRACK=1` and project-local
  `TMPDIR=tmp PYTHONPYCACHEPREFIX=tmp/pycache`: focused decomposition/observation
  contract 35 PASS; Capture_Arena driver 30 PASS; phase integrity 14 PASS;
  combat decomposition/source coordinator parity and static prompt checks 9
  PASS; `py_compile` PASS; ASCII compliance 1,132 files, zero violations;
  scoped `git diff --check` PASS; `openspec validate
  combat-manager-decomposition --strict` valid. The function-size audit found
  no combat function over 600 lines and retained the 17-line shim.
- This is a focused telemetry correction only. No live rerun, full owner loop,
  or final G3 evaluation was performed. The evidence has the stated telemetry
  limitation, and Task 5.3 remains unchecked with no final G3 PASS.

## Explicit-exit completion timing correction (builder tooling scope)

- The primary-owned bundle
  `tmp/router-rollout/g3/20261016T061551.063166Z-surrender-exit-p1-c5d5a8e6/`
  and its `primary-review.json` remain immutable. It records a **BLOCKED**
  explicit-exit observation: one `user-input` echo, 1.64 seconds of waiting,
  active encounter still `capture_one_pc`, and server activity in summary
  generation. It did not wait for the summary SDK call; it proves no product
  exit failure. No live rerun or bundle repair was performed here.
- Source inspection of `core/combat/commands.py` confirms `/end_combat` runs
  `summarize_dialogue`, clears `worldConditions.activeCombatEncounter`, saves
  `party_tracker.json`, writes chat history, loads player info, and returns the
  summary/player tuple. This path does not guarantee a backend narration
  `game_output`; the force-end system message is not proof of a completed
  narrator handoff. The owning `core/combat/turn.py` deterministic-command
  handoff propagates `control_action == "return"` as a `CombatNormalTurnResult`
  before reaching the normal LLM response path, confirming why the named
  capture needs a separately emitted ordinary narrator follow-up.
- The existing driver now retains all observed `game_output` events and their
  counts/types, while separately tracking backend outputs. For every scripted
  step, `user-input`, echo, generic system/startup, and exact-input events do
  not satisfy the backend-response completion gate. Idle status alone is not
  completion; backend response steps require a non-echo backend output plus
  the existing quiet/idle condition. The default latency inputs and ordering
  are unchanged.
- For the named `explicit-exit` branch only, the driver may finish a silent
  `/end_combat` after a bounded read-only canonical snapshot confirms a valid
  party tracker/roster, the selected encounter record, and a cleared active
  encounter, followed by idle/quiet status and a successful existing
  read-only `GET /api/party`. It then sends the declared ordinary yard-description
  follow-up and waits for an actual backend `narration` output. No follow-up is
  sent before that terminal predicate. The evidence records the completion
  criterion, canonical state identity/hash, actual event/output counts and
  types, the health response, and before/after state snapshots.
- The explicit-exit profile now declares two steps, four maximum controls
  (startup, active-PC selection, and two user inputs), and at most one
  exit-specific health read; read-only GET accounting remains separate from
  socket/active-PC controls. Surrender stays a separate branch with its
  existing input and normal backend-output completion. Expected profile seed,
  bounds, and identity checks were updated together.
- The required handoff evidence check accepts explicit exit only when the final
  step is the declared narrator follow-up, has backend output type `narration`,
  and the canonical after-run state is clear; the preceding echo/clear wait is
  not accepted as handoff evidence. For surrender it requires the actual
  surrender-step narrator output and canonical clear state. HP/XP snapshot
  reconciliation and server-health checks remain required.
- Fake-transport regressions emit an immediate echo with `is_processing=false`
  before delayed backend narration, and prove the driver waits for narration;
  echo-only input reaches the bounded timeout. A separate delayed explicit-exit
  fake clears canonical state after summary processing, then emits the ordinary
  narrator follow-up; the test verifies two sent steps/four controls, the one
  bounded health read, actual echo+narration accounting, clear state, and
  handoff criterion. Evidence tests reject echo-only handoff and accept the
  subsequent narration only with clear state. All test effects remain behind
  provider/network/write guards and project-local `tmp/` fixtures.
- These are driver/evidence/profile/test corrections only: no product combat,
  prompt, schema, model, retry, endpoint, or output behavior changed. The parent
  bundle and review remain untouched; Task 5.3 remains unchecked and G3 is not
  PASS. A primary-owned live rerun/matrix verdict is still required.
- Fresh provider-free verification (each unittest suite in its own process,
  with `OPENSPEC_TELEMETRY=0 DO_NOT_TRACK=1 TMPDIR=tmp
  PYTHONPYCACHEPREFIX=tmp/pycache`): `scripts.test_capture_drive` 32 PASS;
  expanded deterministic guards 16 PASS; combat latency baseline 24 PASS;
  surrender/exit flow 4 PASS; runtime prompt authority 7 PASS; combat
  decomposition/static prompt contract 9 PASS; encounter ops runtime 4 PASS;
  persistence phase stages 11 PASS. `py_compile` passed for the four touched
  Python files; ASCII compliance scanned 1,132 files with zero violations;
  scoped `git diff --check` and `openspec validate
  combat-manager-decomposition --strict` passed. No live server, API call,
  prepare, owner loop, or external write was run.

## Surrender-offer seed identity clarification

- The named `surrender-exit:surrender` seed now includes an explicit
  `encounter_context` in its profile identity and writes that exact fact to the
  existing `encounterSummary` projection: the last living hostile has
  voluntarily offered unconditional surrender, lowered its weapon, and awaits
  party acceptance. The one-PC case names only Goblin; the four-PC case names
  only Goblin Beta. The distinct `explicit-exit` seed/summary and bare latency
  baseline remain unchanged.
- The test calls the actual `_seed_party` seeder with a fake writer, then sends
  its captured encounter through `filter_encounter_for_system_prompt`. It
  verifies the projected offer fact, exact expected-profile identity (including
  rejection of a forged offer/context), and pre-action state: the last hostile
  remains alive at 20/20 HP without `Restrained`, the encounter remains active,
  the other four-PC hostile remains inactive, and seeded character XP remains
  zero. No surrender, restraint, exit, or reward is pre-applied.
- Provider-free verification with scoped `OPENSPEC_TELEMETRY=0
  DO_NOT_TRACK=1 TMPDIR=tmp PYTHONPYCACHEPREFIX=tmp/pycache`: Capture_Arena
  driver suite 33 PASS; surrender/exit focused suite 4 PASS; combat latency
  baseline 24 PASS; `openspec validate combat-manager-decomposition --strict`
  valid. No product implementation, prompt, validator, retry, model, or schema
   was changed. No live capture, sandbox preparation, owner loop, provider/API
   call, or cleanup was run. Task 5.3 remains unchecked; no G3 PASS is claimed.

## Parent-owned surrender/exit API-compatibility failure and focused producer fix

- Parent-owned bundle: `tmp/router-rollout/g3/20261016T065142.895997Z-surrender-exit-p1-0a1c1bb1/`.
  The primary reports valid encounter surrender, restraint, and clear state;
  HP was unchanged and exactly one 50-XP award was observed. However, the
  `updateCharacterInfo` prose persistence returned `False` after three direct
  OpenAI API 400 responses because the request supplied unsupported
  `temperature=0.7` to `gpt-6-luna`. Actual persisted XP remained 0. The checker
  correctly records this as FAIL. This is parent-owned evidence; the bundle
  and review were not changed, and no live builder rerun was performed.
- Focused producer correction: `updates/update_character_info.py` retains its
  selected client/model and task temperature but builds the SDK kwargs through
  `get_chat_completion_params("updates", model,
  temperature_override=TEMPERATURE)`. The factory owns the model key, avoiding
  duplicate `model` kwargs. For the approved direct `gpt-6-luna` model this
  yields the task's `reasoning_effort="low"` and `verbosity="low"`, and omits
  both `temperature` and `top_p`. Existing attempts after the first pass
  `retry_tier="retry"` to the factory, where it affects the reasoning profile
  only and is consumed rather than forwarded as an SDK kwarg. The retry count
  and loop/fallback flow, model resolver/source, client/provider selection,
  prompts, XP operation, and character mechanics are unchanged.
- Added `scripts/test_character_update_model_params.py`. It AST-selects the
  actual producer request kwargs expression and feeds those evaluated kwargs
  to a fake SDK recorder. The focused checks cover direct Luna and retry-tier
  consumption, legacy GPT-5, non-reasoning legacy temperature, and OpenRouter
  extension isolation; no production character, network call, server, or live
  campaign state is used.
  This source-component test does not execute the full character-owner loop or
  claim successful parent-bundle persistence.
- The Task 5.3 live gate remains **FAIL / unchecked** pending primary-owned
  rerun and completion of the required G3 matrix. This narrow API-compatibility
  correction is not a G3 PASS and does not revise the original bundle.

## Goblin Alpha phase-precheck diagnostic correction

- The parent-owned 4-PC smoke log establishes that a later-turn response was
  rejected by the forbidden-actor phase precheck for Goblin Alpha. The run
  bundle records a diagnostic match for `GoblinAlpha` / `attack` with the
  bounded window fragment `tacks Goblin Alpha...Her attack roll is required...`;
  Goblin Beta is also named in a `takes no action...Pause for Vitreol attack
  roll` fragment. These fragments support the false-attribution concern, but
  are not presented here as the complete raw rejected payload.
- Added a read-only diagnostic emitted only when
  `ENABLE_COMBAT_TURN_TRACE` is enabled and the existing forbidden-actor
  precheck rejects. It records phase, forbidden names, bounded attempt identity,
  structured action types with actor and target fields separated, and the exact
  bounded matched-name/window/verb excerpt from plan, narration, changes, or
  reason. Existing trace/report handling retains the diagnostic observation as
  an ordinary combat observation. No prompt, retry, model, guard matcher,
  validation policy, or `final_response_validation_truth` evidence was changed.
- The focused regression preserves the genuine forbidden-actor failure return
  unchanged while showing that an actor/target-ambiguous response's original
  near-name window and verb are described without claiming grammatical
  classification. This correction was diagnostic only at that point; the
  focused attribution correction below changes only the classifier's false
  positive handling and retains strict genuine-actor rejection.

## Focused actor-attribution correction

- The bounded classifier now rejects only a forbidden name followed directly
  by a supported action verb in the same clause, with a small fixed allowance
  for `then`, `now`, `quickly`, `immediately`, or `finally`. It also preserves
  the explicit modal-plan form `Have <name> <verb>`. It does not treat an attack
  roll/bonus noun, a target name after another actor's verb, a later unrelated
  verb within 64 characters, `takes no action`, or `does not attack` as the
  named actor acting. Ambiguous/nonmatching syntax remains fail-open.
- The diagnostic uses the exact same classifier and matched verb as the actual
  phase decision; it no longer independently searches the old broad proximity
  window. Structured `characterName` fields remain excluded; action `changes`
  and `reason` prose remains eligible under the same attribution rule.
- Reconstructed regression response text in tests is authored test data, not a
  claim that it reproduces the bundle's complete raw payload. Tests retain the
  true Goblin Scout attack rejection, modal-plan rejection, target/attack-roll
  and negation pass cases, diagnostic parity, and `updateCharacterInfo` /
  `updateEncounter` descriptive prose with Goblin Alpha as a target.
- This is an offline deterministic classifier fix only: the precheck stays in
  place, false/early-return validation behavior is unchanged, and no phase
  policy, prompt, LLM flow, retry, schema, resolver, or external service was
  added. Task 5.3 remains unchecked; no G3 PASS is claimed.
- Focused provider-free verification with `OPENSPEC_TELEMETRY=0
  DO_NOT_TRACK=1 TMPDIR=tmp PYTHONPYCACHEPREFIX=tmp/pycache`: phase integrity
  18 PASS, Capture_Arena driver 33 PASS, combat validation stage 8 PASS,
  combat validation routing 11 PASS, and combat decomposition/static prompt
  contract 9 PASS. These are separate test processes. No live run, server,
  provider/API call, prepare, owner loop, or outside write was performed.

## Blairen attack-data fixture correction

- The primary-owned bundle `tmp/router-rollout/g3/20261016T110223.294446Z-combat-smoke-allied-inactive-p1-92399ecd/`
  reports the allied/inactive 1-PC smoke enemy batch failed 5/5. The bundle
  identifies Blairen's missing attack bonus/damage as the fixture cause; the
  failed run bundle remains primary-owned and was not modified.
- The named allied-NPC profile now calls a Blairen-only payload builder. Blairen
  is seeded with an equipped longsword, simple/martial weapon proficiency, and
  one melee `attacksAndSpellcasting` record: +3 to hit, 1d8 + 1 slashing. The
  fields and required attack record shape are existing `char_schema.json`
  properties. The generic NPC builder remains unarmed; because named PCs inherit
  that generic base, the fix does not add these mechanics to PCs. The bare
  `_character_payload` and latency command/default seed remain unchanged.
- The provider-free regression seeds the named allied/inactive profile through
  `_seed_party` for both 1-PC and 4-PC parties, validates Blairen against the
  real character schema, and passes the persisted record through the actual
  `format_npc_for_combat` generation projection and `get_npc_attacks` preroll
  reader. Both expose the longsword, proficiency and attack; the read-only
  prompt projection leaves the seeded record unchanged. It also checks the
  defeated inactive enemy stays excluded by the existing seed contract.
- This changes named fixture data and focused tests only. No prompt, validator,
  combat mechanic, enemy-batch requirement, outcome, retry, provider behavior,
  or default latency input changed. No live capture or verdict was produced;
  Task 5.3 remains unchecked and G3 has no PASS claim.
- Provider-free verification (`OPENSPEC_TELEMETRY=0 DO_NOT_TRACK=1`,
  `TMPDIR=tmp`, `PYTHONPYCACHEPREFIX=tmp/pycache`):
  `scripts.test_capture_drive` -> 34 PASS (the prior 33 plus the named attack
  projection regression); `scripts.test_combat_latency_baseline` -> 24 PASS;
  `scripts.test_combat_bootstrap` -> 24 PASS. The capture suite's existing
  schema and fixture checks cover both party profiles and the unchanged bare
  latency seed. `py_compile` passed for the fixture, seeder and capture test;
  ASCII compliance scanned 1,133 files with zero violations;
  `git diff --check` passed; strict OpenSpec validation reported the change
  valid. Test logs were transiently written under `tmp/` and removed. No live
  run, provider/API call, sandbox prepare, owner loop, or outside write occurred.

## Primary-owned smoke verdict correction: 4-PC pass and allied 1-PC failures

This section adds the primary's later run verdicts; it does not replace or
reinterpret the earlier failures and incidents above.

- **4-PC `combat-smoke` - PASS for this bounded case only.** The primary review
  at `tmp/router-rollout/g3/20261016T100351.896367Z-combat-smoke-p4-a06e1a60/primary-review.json`
  records 19 input steps, 32 controls, 0 timeouts, and all required checks
  passing. Its scope explicitly excludes a complete G3 claim.
- **Allied/inactive 1-PC before the Blairen mechanics correction - FAIL.** The
  primary review at
  `tmp/router-rollout/g3/20261016T110223.294446Z-combat-smoke-allied-inactive-p1-92399ecd/primary-review.json`
  records the expected eligible Blairen/Goblin batch was not accepted and that
  five enemy-batch generations were rejected while Blairen's attack bonus and
  damage were unavailable in the fixture.
- **Allied/inactive 1-PC after the Blairen mechanics correction - FAIL.** The
  primary review at
  `tmp/router-rollout/g3/20261016T111137.037824Z-combat-smoke-allied-inactive-p1-0bebfaf6/primary-review.json`
  records that Blairen's +3 longsword mechanics were available and used as
  intended, but the enemy response exhausted 5/5 validation attempts. No
  eligible Blairen/Goblin batch was accepted; mechanics availability is not a
  passing outcome or proof that the correction fixed the projection/validation
  failure.
- The accompanying
  `validation-diagnostic.json` records a validator treating candidate
  `touchedChanges` text proposing Acheron HP 20->12 as if that damage were
  already committed. The truth pack still reported Acheron HP 20. Feedback
  therefore mislabeled the proposed change as committed, and subsequent
  candidate feedback followed that incorrect premise. The diagnostic does not
  establish that the first candidate was otherwise valid; it notes a concern
  about a second Goblin attack. The final rejected response nevertheless left
  actual Acheron HP at 17, as shown in the after-run snapshot; that mutation and
  round advancement do not make the response accepted or the gate PASS.
- The latest after-run snapshot records Acheron 17, Goblin 18, Blairen 12,
  Inactive Goblin 0, round 2. This is the observed final state, not an accepted
  batch result.
- **G3 remains incomplete and Task 5.3 remains unchecked.** The 4-PC smoke PASS
  is one case only. Allied 4-PC and resume/replay pairs, plus the refresh and
  18-key aggregate, remain pending. Task 5.4 also remains unchecked. Stop for
  primary guidance on any validation-authority correction versus the G3
  byte-parity constraint; no prompt waiver or acceptance-criteria change is
  authorized by these reports. No overall G3 PASS is claimed.

## Approved validation-context correction and narrow parity exception

The owner separately approved an artifact amendment for the specific validation-
context authority defect described above. The evidence is the primary-owned bundle
`tmp/router-rollout/g3/20261016T111137.037824Z-combat-smoke-allied-inactive-p1-0bebfaf6/`;
its `primary-review.json` and `validation-diagnostic.json` are read-only evidence
and remain unchanged. The diagnostic establishes that candidate `touchedChanges`
proposing Acheron HP 20->12 were treated as committed while the truth pack still
reported HP 20. It does not establish that the candidate was otherwise valid. The
initial failed candidate containing two Goblin attacks remains unproven otherwise.

Approved correction boundary: dynamic validation context and strictly necessary
explanatory validation instructions only. Committed Python state must remain
separate from uncommitted candidate changes/operations. Candidate-derived
`touchedChanges` and candidate claims of `ALREADY_APPLIED` are not proof and must
not enter the authoritative truth pack; independently established genuine prior
applied events remain trusted. This is a narrow exception to extraction dynamic-
context byte parity only. Static assets, unrelated dynamic prompt/context bytes,
and extraction parity outside this named correction remain unchanged. Frozen
baseline goldens/history are not wholesale rewritten. Schema, public returns,
mechanics, physical execution/mutation/persistence/publication order, retries,
provider-call behavior, and fail-open policies are unchanged. No G7 behavior is
implemented.

At the time of this historical planning amendment, Task 4.5 was introduced as
unchecked. It is now checked with the software-only PASS and evidence recorded
in `tasks.md` and `reports/task-4-5-implementation.md`; this report does not
reopen or revise that completed task. Its guarded coverage includes
before/after payload tests; `HP20proposed-8` not already applied;
`actualcommitted12` and `replaystillblocked`; PC/ally/both-party/ops-only/
inventory/no-mutation cases; and the actual validation-call payload with fatal
SDK/network/outside-write tripwires. Tests prove unrelated prompt bytes stay
unchanged. All 18 G3 required strict-reject checks remain unaffected; failed
bundles remain FAIL; affected live cases require primary-owned reruns. Tasks 5.3
and 5.4 remain unchecked, completed work is not reopened, and the eight-phase
rollout and its gates are unchanged. This artifact amendment is not product/test
implementation, a live rerun, or a G3 PASS.

## Later primary-owned allied/inactive 1-PC failure: canonical attack facts absent

- Latest bundle: `tmp/router-rollout/g3/20261016T172935.595209Z-combat-smoke-allied-inactive-p1-38096c35/`.
  Its `primary-review.json` records **FAIL**: 4 steps, 6 controls, no timeouts or
  caps, final round 2, and HP Acheron 20, Goblin 18, Blairen 12, Inactive Goblin
  0. `final_response_validation_truth` failed after 5/5 rejections; no eligible
  ally/enemy batch was accepted. The evidence does not establish a G3 PASS.
- This failure is distinct from Task 4.5 and does not reopen or invalidate its
  software-only PASS. The review says the proposed/committed boundary is present;
  direct inspection of the actual validation request found no canonical
  `attackBonus`, `attacksAndSpellcasting`, or scimitar mechanics data, only
  preroll names/values. Validation rejected Blairen +3 and Goblin +4 attacks and
  damage modifiers as unknown. Candidate bonuses are not evidence of canonical
  authority, and no candidate acceptance is inferred.
- Planning amendment only: add unchecked Task 4.6 before the final gates to hand
  bounded, read-only canonical non-PC attack/stat facts from the existing
  generation sources into the dynamic validation payload, with identity and
  provenance. Reuse already-loaded maps when clean, otherwise existing NPC
  state/template and monster path/loaders. Unknown, missing, stale, or malformed
  data remain explicitly unknown; candidate/preroll text never becomes
  authoritative. Do not create new resolver/context frameworks, alter generation
  prompt bytes, mutate/persist context, or change callbacks, retries, policy,
  publication/persistence/G7, fail-open behavior, or the 18 strict live keys.
- Required guarded coverage includes actual canonical input through the actual
  fake validation payload for PC1/4 and ally/enemy identity; unavailable or
  malformed facts; no candidate override; deep no-mutation; legacy callback and
  patch behavior; generation byte parity and frozen assets. After focused gates,
  the primary owns the affected live rerun. The original bundle/review remains
  unchanged, Task 5.3 stays unchecked, all prior FAIL verdicts remain, and no
   acceptance waiver or G3 PASS is claimed.

## Focused evidence-checker correction (2026-10-16)

- The latest primary-owned bundle remains
  `tmp/router-rollout/g3/20261016T175906.044794Z-combat-smoke-allied-inactive-p4-146142c8/`
  and its recorded verdict remains **BLOCKED**. This correction did not rerun a
  live capture or revise its primary review.
- `observed_checks` now initializes the canonical before/after selected-encounter
  snapshots before reconciling applied encounter-domain `hp_delta` operations.
  It still reconciles by the explicit encounter operation creature identity and
  preserves exact match, mismatch, missing-row, and ambiguous-row outcomes;
  it does not infer actors from damage targets or skip encounter operations.
- Provider-free regression coverage exercises the real `observed_checks` on
  encounter-domain ally damage for both 1-PC and 4-PC party shapes, including an
  exact positive, expected-delta mismatch (**FAIL**), and missing or duplicate
  canonical ally rows (**BLOCKED**). These are synthetic unit-test expectations,
  not live acceptance evidence or a reconstructed PASS.
- Tasks 5.3 and 5.4 remain unchecked. Earlier BLOCKED/FAIL reviews and the
  primary-owned verification boundary are unchanged; no G3 PASS is claimed.

## Character-validator parameter correction note (2026-10-17)

- The supplied `tmp/router-rollout/g3/20261016T180820.039042Z-combat-smoke-allied-inactive-p4-fe3b7936/server.log:1239` records a character-validation API 400 because the direct `gpt-6-luna` request supplied unsupported `temperature=0.1` (the endpoint accepts only its default value). This is a producer-parameter compatibility failure, not gameplay-gate evidence.
- The focused correction routes the existing character-validator requests through `get_chat_completion_params("validation", CHARACTER_VALIDATOR_MODEL, temperature_override=0.1)`. Direct Luna sampling controls are omitted by the shared factory policy; the 0.1 override remains for legacy models. Original retry-loop request parameters remain unchanged across attempts; no retry tier is added.
- Provider-free fake-client assertions cover the actual armor-class, inventory, combined/batched, and currency-consolidation producers. They preserve request messages and retry attempt counts, assert the helper receives no invented retry tier on retries, and cover usage tracking. This correction note does not amend the prior bundle or primary review, and does not mark task 5.3 or 5.4 checked or claim a G3 PASS.

## Planning-artifact reconciliation for primary review 180820

- The read-only primary review at
  `tmp/router-rollout/g3/20261016T180820.039042Z-combat-smoke-allied-inactive-p4-fe3b7936/primary-review.json`
  records **FAIL** for the 4-PC allied/inactive combat-smoke case (19 steps,
  32 controls, no timeout/cap, no accepted non-PC batch). The evidence checker
  compared expected encounter damage `-4` with aggregate Goblin Alpha delta
  `-16`; six successful deterministic damage operations of 2 explain the other
  `-12`, but the evidence lacks causal-span linkage to exclude double counting.
  The review also independently records failed final validation and failed
  mechanical application evidence; neither is waived by the checker correction.
- The earlier read-only `175906` primary review remains **BLOCKED**: the evidence
  producer crashed before complete checks/report artifacts, so no product outcome
  was adjudicated. Neither primary bundle/review was modified or reconstructed.
- Planning-only Tasks 4.7 and 4.8 were added unchecked before the final gates.
  Task 4.7 requires per-step trace byte boundaries and actual JSONL source
  positions, unique causal linkage/reconciliation, and strict FAIL/BLOCKED
  handling. Task 4.8 documents the existing equipment/ammunition container rule
  and permits only bounded, existing-trace-gated rejection diagnostics. It does
  not authorize heuristic routing changes: the goal-prose mirror rejection is
  not proven to be an attacker-victim false positive, and the latest review does
  not include the raw rejected body. All 18 live strict-rejection checks remain
  unchanged. Tasks 4.5/4.6 remain checked; Tasks 5.3/5.4 remain unchecked.
- The character-validator parameter/helper compatibility correction is retained
  separately (including the source helper import at
  `core/validation/character_validator.py:71`, builder's 26 related checks, and
  prior 35 capture / 10 validation-stage related checks). This is not a full
  migration, a live rerun, or a G3 PASS.
- This section reconciles planning only. No live run, API/provider call,
  preparation, gameplay, or primary-owned evidence change was performed.

## Primary-owned current-key refresh and linked replay evidence (2026-10-17)

This records the primary's later read-only audit and reviews. It does not rewrite
any run artifact, backfill invalid evidence, waive a required key, or establish
the final G3 verdict.

- The current 18-key audit selected five fresh keys as ready: the allied/inactive
  4-PC case below and the complete/replay phases of both 1-PC and 4-PC resume
  chains. Thirteen older keys still require fresh captures because they lack
  required `trace_start` offsets, profile metadata, or causal linkage, or because
  current derived checks disagree. The older smoke-1 `invalid_profile` key also
  remains invalid. Historical individual PASS reviews are not retroactively
  converted: in particular, the primary PASS at
  `tmp/router-rollout/g3/20261016T175525.952653Z-combat-smoke-allied-inactive-p1-9ebcd887/primary-review.json`
  remains an individual historical PASS but is not a ready current key because
  it lacks the required Task 4.7 offsets. No backfill or retrospective change
  was made to that bundle or review.
- **Allied/inactive 4-PC combat-smoke - individual PASS.** The primary review at
  `tmp/router-rollout/g3/20261016T191039.250097Z-combat-smoke-allied-inactive-p4-2ec66837/primary-review.json`
  records 19 steps, 32 controls, zero timeouts/caps, and all current required
  checks passing. The accepted cohort was Blairen, Goblin Alpha, and Goblin
  Beta; inactive Goblin did not act. Narration reported Blairen missed Alpha,
  Alpha missed, and Beta hit Vitreol. Six source-linked deterministic `/dmg 2`
  effects reconciled Alpha 20 to 8; Vitreol's structured damage reconciled
  20 to 13 once through the canonical character/encounter mirror. Other PCs
  remained at 20 HP, Blairen at 12, Beta at 20, inactive enemy at 0; ammunition
  remained 3, XP remained 0, and there were no unexplained HP mutations, failed
  applies, failed final validations, or runtime errors. This is one refreshed
  key only, not an overall G3 PASS.
- **1-PC resume/replay chain - linked PASS.** The completed phase review at
  `tmp/router-rollout/g3/20261016T191844.167472Z-resume-replay-p1-a23a253d/primary-review.json`
  and replay review at
  `tmp/router-rollout/g3/20261016T191933.922266Z-resume-replay-p1-0b12e85b/primary-review.json`
  share chain `g3-p1-20261016-replay-v2`. The declared Acheron attack applied
  Goblin HP 20 to 19 once; replay restarted the same retained sandbox without
  prepare or gameplay inputs, retained state/history/identity, and did not
  duplicate HP, resources, or rewards. Both phases had zero timeouts and their
  current required checks passed. The existing `evaluate_matrix` evaluated the
  actual pair and resolved raw replay-link checks from locally BLOCKED to PASS
  only after the offline pair join; raw artifacts were not rewritten.
- **4-PC resume/replay chain - linked PASS.** The completed phase review at
  `tmp/router-rollout/g3/20261016T192159.127695Z-resume-replay-p4-ae543f63/primary-review.json`
  and replay review at
  `tmp/router-rollout/g3/20261016T192305.093490Z-resume-replay-p4-827518ce/primary-review.json`
  share chain `g3-p4-20261016-replay-v1`. Goblin Alpha moved 20 to 19 once;
  Goblin Beta and all PCs remained at 20. Replay restarted without prepare or
  gameplay inputs, retained state/history/identity, and produced no duplicate
  effects or rewards. Both phases had zero timeouts and their current required
  checks passed. The primary's offline join of the actual pair resolved the raw
  replay-link checks to PASS; raw artifacts remain unchanged.
- The earlier `191716` 1-PC complete chain remains BLOCKED and is excluded: its
  primary declaration expected damage 2 while the approved scenario declared
  damage 1. That is a declaration mismatch, not a product failure. The later
  correctly declared chain above passed. Neither replay pair used prepare
  between phases.
- The historical 18-key audit failures/blocks remain retained. Tasks 4.5 through
  4.8 remain checked with their existing software-primary evidence; Tasks 5.3
  and 5.4 remain unchecked. The next work is fresh primary captures for the 13
  keys that still lack current required evidence, followed by the primary's
  full matrix evaluation. No final G3 PASS, waiver, or acceptance-criteria change
  is recorded here.

## Primary-owned 4-PC accepted-surrender cap and budget reconciliation (2026-10-16)

- The primary review at
  `tmp/router-rollout/g3/20261016T221457.493858Z-surrender-exit-p4-79ae8967/primary-review.json`
  records **FAIL**. The existing one-input/three-control capture reached its
  declared 150-second turn cap at 151.19 seconds while the event stream was
  active. The review records the encounter still active, Goblin Beta defeated,
  all PC HP unchanged, only Acheron and Merisiel at 25 XP, Kira and Vitreol at
  0 XP, and logical batch completion missing. The expected full-surrender,
  clear-state, normal-handoff and exact-once 25-XP-per-PC assertions remain
  unmet. The review, transcript, server log and other primary-owned artifacts
  are retained unchanged.
- The transcript explicitly logs `turn cap reached with the event stream still
  active` and records the 151.19-second duration, `timed_out=no`, cap reached,
  and the unchanged 1-input/3-control profile. The server log ends after Kira's
  third serial XP prose update has started: its final change says 25 XP, character
  update processing begins, and the log reaches `Attempt 1 of 3`. It does not show
  completion of that update. This is a cap-limited in-flight capture, not a quiet
  or echo bug, and it does not establish that Kira's persistence ultimately
  failed after a completed backend response.
- For the next **freshly seeded full 4-PC accepted-surrender capture only**,
  predeclare a 300-second capture-only turn budget for the same one input, three
  controls, and unchanged full assertion set. The additional bounded time is for
  the four serial prose XP updates and summary. The 150-second default remains
  for every other case; production factory timeouts/retries, G5 targets and
  default latency scripts remain unchanged. This is not a waiver: preserve the
  prior 150-second FAIL, do not resume its partially processed fixture, and treat
  any required timeout/cap or failed assertion at 300 seconds as non-PASS.
- This is a budget/documentation reconciliation only. No new capture was run,
  no primary evidence was changed, no G3 PASS or goal-criteria change is claimed,
  and Tasks 5.3 and 5.4 remain unchecked.

## Primary-owned 1-PC smoke timeout and named fail-stop correction (2026-10-17)

- Primary review `tmp/router-rollout/g3/20261016T222759.252451Z-combat-smoke-p1-8a01bf24/primary-review.json`
  remains **FAIL**. The transcript records step 3 timing out after 150 seconds
  while `is_processing=True`, followed by the legacy step 4 `/end`; step 4 then
  reached its 150-second cap while another retry was in flight. The server log
  records the valid free-text step's fourth retry and eventual output at about
  237 seconds. This is a delayed but valid backend path, not a reason to weaken
  the verdict. The step 3/4 trace observations correctly report
  `idle_not_observed`; their offsets must remain unavailable until idle is
  observed.
- The named driver now fail-stops on the first step timeout or active-stream
  cap. It raises the existing driver error only after writing the step's after
  snapshot; the existing `finally` path preserves partial trace, snapshots,
  transcript, report, checks, and manifest, while returning nonzero. Named
  smoke scenarios may explicitly use 300 seconds for both party shapes and
  smoke variants; default remains 150. The temporary helper permits 300 only
  for these smoke cases or the previously declared 4-PC surrender branch and
  uses the same bound for its recorded driver budget and deadline. Inputs/order,
  5/7 and 22/35 limits, checks, bare latency behavior, product behavior, factory
  policy, G5 thresholds, and required failure semantics are unchanged.
- This implementation note is before any primary new run. No live rerun was
  performed; the original run bundle and **FAIL** verdict remain unchanged.
  Task 5.3 remains unchecked, and no G3 PASS or acceptance waiver is claimed.

## Canonical test isolation follow-up (2026-10-17)

- Removed `test_disposable_helper_timeout_policy_and_budget_are_ast_only` from
  `scripts/test_capture_drive.py`: that canonical suite must run from a clean
  checkout and cannot require ignored `tmp/run_g3_case.py`. The named timeout/
  cap integration regression remains in the canonical suite, as do the existing
  all-scenario 1-PC/4-PC fake-transport coverage and bare legacy 4-PC ordering
  assertion.
- Kept disposable-wrapper AST/budget validation as a manual primary-side check,
  separate from shipped tests. Command executed from repository root:

  ```sh
  PYTHONPATH=. .venv/bin/python -c 'import ast,argparse,math; from pathlib import Path; p=Path("tmp/run_g3_case.py"); m=ast.parse(p.read_text()); names={"_positive_timeout","_turn_timeout_allowed","_driver_budget_seconds"}; ns={"argparse":argparse,"math":math,"DEFAULT_TURN_TIMEOUT":150.0,"MAX_TURN_TIMEOUT":600.0,"Optional":__import__("typing").Optional}; exec(compile(ast.Module(body=[n for n in m.body if isinstance(n,ast.FunctionDef) and n.name in names],type_ignores=[]),str(p),"exec"),ns); exec("def rejects(fn,value):\n try: fn(value)\n except argparse.ArgumentTypeError: return True\n return False",ns); allow=ns["_turn_timeout_allowed"]; assert all(allow(party,case,None,300.0) for party in (1,4) for case in ("combat-smoke","combat-smoke-allied-inactive")); assert allow(4,"surrender-exit","surrender",300.0) and not allow(1,"surrender-exit","surrender",300.0) and not allow(4,"initiative-pc",None,300.0); assert all(not allow(1,"combat-smoke",None,value) for value in (float("nan"),float("inf"),151.0,299.0,600.0)); assert all(ns["rejects"](ns["_positive_timeout"],value) for value in ("nan","inf","0","-1","601")); assert all(ns["_driver_budget_seconds"](steps,300.0)==expected for steps,expected in ((5,1690.0),(22,6790.0))); main=next(n for n in m.body if isinstance(n,ast.FunctionDef) and n.name=="main"); calls=[n for n in ast.walk(main) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=="_driver_budget_seconds"]; assert len(calls)==2 and all(ast.unparse(n.args[1])=="args.turn_timeout" for n in calls); src=ast.get_source_segment(p.read_text(),main); assert "\"turn_seconds\": args.turn_timeout" in src and "\"--turn-timeout\", _timeout_text(args.turn_timeout)" in src; print("disposable helper AST budget checks passed")'
  ```

- No helper-policy copy, product/controller change, or acceptance change was
  introduced. Verification with `OPENSPEC_TELEMETRY=0 DO_NOT_TRACK=1`,
  `TMPDIR=tmp`, and `PYTHONPYCACHEPREFIX=tmp/pycache`: `scripts.test_capture_drive`
  -> 48 PASS; `scripts.test_combat_latency_baseline` -> 24 PASS; `py_compile`
  passed for `scripts/capture_drive.py` and `scripts/test_capture_drive.py`;
  ASCII compliance scanned 1,135 files with zero violations; scoped
  `git diff --check` passed; strict OpenSpec validation reported the change
  valid. The separate disposable-wrapper AST/budget command above passed.

## Planning-artifact correction for primary review 225308 (2026-10-17)

- Primary review `tmp/router-rollout/g3/20261016T225308.339122Z-combat-smoke-allied-inactive-p1-efaad448/primary-review.json`
  remains **FAIL**. The actual report records two rejected changes:
  `Goblin takes 7 damage, HP 18->11. Blairen hits Goblin. Goblin misses Acheron.`
  and `Goblin takes 7 damage, HP 18->11. Goblin's scimitar attack against
  Acheron misses.` Both were rejected because `_changes_text_targets_non_enemy`
  finds a non-enemy name anywhere in the prose plus a mutation pattern anywhere,
  regardless of recipient/clause. This proves this precise routing false positive;
  it does not prove either candidate otherwise valid. The same review reports
  that the validator expected a post-batch PC prompt while Guard 2 rejected any
  such prompt solely from pre-response `ENEMY_PHASE`/pending-actor state.
- The actual `report.json` rejection records retain the changes verbatim but show
  nested operations as `[truncated]` by the real trace writer. Operation identity,
  creature and delta are therefore unknown from this diagnostic and are not
  reconstructed or claimed. The separate actual apply trace is not used to
  upgrade either rejected candidate to acceptance.
- Planning-only Task 4.9 is added unchecked before final gates. Its scope is
  limited to canonical target/recipient- and clause-aware prose classification;
  preserving genuine PC/allied mutation rejection (including cross-sentence HP)
  and strict structured-operation checks; allowing Guard 2 to defer only a
  code-identified complete NPC batch at the exact `Enemies turn.` input seam to
  the existing mandatory full semantic validator; and flattening the existing
  bounded trace diagnostic operation fields for the real writer. Candidate
  completion flags are not trusted, and deferral cannot accept/apply or advance
  phase/round. False semantic feedback and skipped-actor/invalid-round/premature
  PC-action cases remain rejection tests. No new mechanic, schema, resolver,
  service, public callback shape, order, retry/fail-open change, or generation
  byte change is authorized.
- All 18 G3 strict-rejection criteria and the `225308` FAIL remain unchanged;
  prior rejected-response effects are not acceptance evidence. Tasks 4.5-4.8
  remain checked, Task 4.9 is unchecked, and Tasks 5.3/5.4 remain unchecked.
  Source-backed named-smoke/surrender 300-second exceptions and the default
  150-second capture budget remain unchanged. No live rerun or G3 PASS is
  claimed; the primary retains ownership of the affected rerun and full matrix.

## Focused G3 HP-ledger evidence review: 233336 BLOCKED (2026-10-17)

- Reviewed, without modifying, the primary-owned bundle
  `tmp/router-rollout/g3/20261016T233336.702287Z-combat-smoke-allied-inactive-p1-095f0f9f/`
  including `primary-review.json`, `checks.json`, `report.json`, `trace.jsonl`,
  and step 4 before/after snapshots. The review confirms accepted cohort
  `[Blairen, Goblin]`, zero timeouts/caps, final validation PASS, causal linkage
  PASS, and the sole recorded HP-ledger blocker
  `structured_operation_payload_missing`; the bundle and review remain
  untouched.
- Step 4 has captured trace offsets 9258 -> 23090. Source-positioned successful
  apply records are: `update_encounter` / encounter target `capture_one_pc` at
  [16042,18589), with `ops: null`; `update_character_info_prose` / character
  target Blairen at [18589,18945); and `update_character_info_ops` / character
  target Acheron with `hp_delta -7` at [20024,20389). Canonical step snapshots
  show Blairen character and encounter HP 12 -> 12 and Acheron character and
  encounter HP 20 -> 13. The check ledger attributes one logical Acheron -7
  mirror effect; separate earlier step evidence accounts for the Goblin -2.
- The Blairen prose event individually meets the proposed zero-HP proof shape:
  unique complete position in step 4, successful exact `character` operation
  and target, exactly one successful Blairen character apply in that step, valid
  canonical before/after HP 12/12, and the persisted-state observation also
  identifies Blairen at HP 12. No text-intent inference is needed.
- STOP: that event is not the source of the current missing-payload blocker.
  The blocker is the separate successful `update_encounter` apply with
  `ops: null`. It is not an `update_character_info_prose` event; its `changes`
  report a shortbow hit against Acheron and the returned encounter state is
  truncated. The available evidence does not establish that this apply was a
  stable non-HP metadata-only update under the approved exact-target rule.
  Relaxing the blocker on the basis of Blairen's unchanged HP would leave the
  actual missing encounter operation unproved and risk masking an HP mutation.
  No source/test behavior change is therefore made; no default trust of prose,
  aggregate-only proof, double-count, or new parser is introduced.
- 5.3 remains unchecked and this bundle remains BLOCKED, not PASS. Required
  follow-up is primary-owner clarification/evidence for how to prove the
  `update_encounter` no-HP effect at this exact causal step without inferring
  intent or changing runtime instrumentation. This review did not run a live
  capture, alter raw artifacts, or waive any G3 criterion.

## Planning-only Task 4.10 correction for the 233336 HP-ledger blocker

- Correction to the initial hypothesis above, retained here rather than
  rewriting it: the `233336` blocker is solely the successful
  `update_encounter` operation with `ops: null` and depth-truncated returned
  state. It is not Blairen prose. Guard 4.9 NPC acceptance remains fixed; the
  captured HP context is Acheron 20 to 13 from structured `hp_delta: -7` with
  its character/encounter mirror, Goblin 20 to 18 from the PC deterministic
  `-2`, and Blairen unchanged at 12. Missing operation proof cannot be waived.
- Planning permits only bounded read-only HP evidence inside the existing
  opt-in `combat_apply_result` for the `updateEncounter` branch. The caller's
  already-loaded encounter is labelled preloaded context; bounded HP maps are
  copied before the call; the canonical updater return is labelled returned
  persisted state. The flat evidence includes before/after HP, status, counts,
  truncation and provenance within actual writer depth/byte bounds. Invalid,
  missing, duplicate or truncated actor identities stay explicitly incomplete,
  not defaulted. No provider call, resolver, cache, or framework is authorized.
  With tracing off, no payload-construction trace, extra I/O, or helper calls are
  permitted;
  the existing trace-on observation may carry the bounded HP metadata.
- The checker may clear an ops-absent block only for a positioned unique
  encounter operation whose complete projection proves zero HP delta and agrees
  with canonical pre-step state and prior causally proved writes, with no other
  ambiguous same-store writes. Conservative restriction is preferred to
  sequence inference. Non-zero-HP prose without structured expected ops,
  incomplete/mismatched projection, unknown target, or duplicate ambiguity
  remains BLOCKED; failed apply remains FAIL; unexplained overall mutation
  remains FAIL. Expected HP is not derived from observed state or prose
  mechanics. Mirror accounting and all 18 strict checks remain unchanged.
- Required provider-free proof follows a real persistence callback and real
  function fake updater through the real trace writer and actual parser/
  `observed_checks`; it covers zero-HP metadata updates, structured character
  HP deltas for distinct actors/mirror/PC deterministic damage, and the
  non-zero, absent, invalid, duplicate, provenance-mismatch, and failed-apply
  negatives. It proves pre-call capture survives an updater mutating its input
  and trace-off adds zero I/O/helper calls while preserving deep no-mutation,
  callback order, and generated bytes. Fatal SDK/network/`BaseException`
  tripwires precede imports and writes; generated paths stay under project-local
  `tmp/`.
- This is a planning-artifact amendment only: no product/test code, live rerun,
  or raw-bundle rewrite. The original `233336` bundle remains BLOCKED, its
  corrected initial hypothesis is retained, and fresh affected primary-owned
  live evidence is required after software tests. Tasks 5.3 and 5.4 remain
  unchecked; checked/unchecked task ranges, the named 300-second exceptions,
  bare 150-second bound, G5, and all live verdicts remain unchanged. Verification
  for this amendment is restricted to ASCII-scoped artifact diff review under
  `OPENSPEC_TELEMETRY=0 DO_NOT_TRACK=1`; stop at the exact Task 4.10 boundary.

## Shared named-capture timeout policy correction (2026-10-17)

- Corrected only the preflight/evaluator contract drift. The pure
  `capture_turn_timeout_allowed` policy in `scripts/combat_latency_fixtures.py`
  is now reused by `scripts/capture_drive.py` named preflight and
  `scripts/capture_evidence.py` offline evaluation. A finite positive timeout
  at or below 150 seconds remains valid; exactly 300 seconds is valid only for
  `combat-smoke` or `combat-smoke-allied-inactive` with party size 1 or 4, or
  `surrender-exit` / `surrender` with party size 4. Intermediate values above
  150, values above 300, booleans, non-finite values, zero, and negatives are
  invalid. The canonical driver default remains 150 seconds and the controller
  retains its documented 300-second capture argument.
- Read-only offline audit of the selected actual 18-key matrix after the policy
  correction found 18/18 required keys, no duplicates/missing/invalid bundles,
  zero integrity failures, and all derived cases `READY_FOR_PRIMARY_REVIEW`.
  The four affected actual bundles are 1-PC `combat-smoke`
  (`20261016T224949.279584Z-combat-smoke-p1-a64a13c5`), 4-PC `combat-smoke`
  (`20261017T000912.796320Z-combat-smoke-p4-0a797840`), 1-PC
  `combat-smoke-allied-inactive`
  (`20261017T000618.223619Z-combat-smoke-allied-inactive-p1-e264ebd2`), and
  4-PC accepted surrender
  (`20261016T222535.148297Z-surrender-exit-p4-fb9d3bdf`); each declares 300
  seconds. Raw bundles, manifests, reviews, and check files were not changed.
  This offline readiness result is not a primary G3 PASS: task 5.3 and 5.4 stay
  unchecked and only the primary owns the final verdict.
- Provider-free verification: `scripts.test_capture_drive` -> 49 PASS,
  `scripts.test_combat_latency_baseline` -> 24 PASS, `py_compile` for the three
  implementation files and focused test -> PASS, ASCII compliance -> 1,135
  files scanned / 0 violations, scoped `git diff --check` -> PASS, and strict
  OpenSpec validation -> valid. Coverage exercises real driver preflight and
  evaluator policy for legal/unauthorized 300, 175/301, invalid numeric values,
  default 150/short synthetic bounds, and confirms observed timeout/cap remains
  non-ready at a legal 300-second bound. No live run, provider, server, prepare,
  campaign/keys/goals, Git mutation, cleanup, or raw-evidence rewrite occurred.

## Final primary-owned G3 matrix verdict (2026-10-17)

- **Primary verdict: G3 PASS.** This is the primary orchestrator's final
  verdict, recorded from `tmp/router-rollout/g3-primary-matrix-20261017.json`;
  it is not a live run or an independent review by this builder.
- The selected matrix contains all 18 required keys: 1-PC/4-PC smoke,
  initiative-PC, initiative-DM-tie, death-save, separate accepted-surrender and
  explicit-exit branches, allied-NPC/inactive-enemy smoke, and completed-turn /
  replay phases for both party sizes, including the 4-PC wrong-actor death-save
  subcase. The aggregate reports 18 observed, 18 `READY_FOR_PRIMARY_REVIEW`,
  and empty missing, not-ready, failed, invalid-bundle, duplicate, and
  resume-chain-failure lists. Its evaluation SHA-256 is
  `09fef5cf4ed2a4e7df8ea26103b5526953f70dbd79af3096a3a0ffb9c75ba7f0`.
- The primary states every selected bundle has a primary-review PASS backed by
  actual output and state inspection. The primary's conditions record the
  scenario, party-shape, replay, server, and exact-once assertions; the declared
  capture-only 300-second exceptions apply only to named smoke and the 4-PC
  surrender case, while other/default bounds remain 150 seconds. This is not a
  timeout waiver or a change to production timeouts, retries, G5 thresholds, or
  acceptance criteria.
- Historical failures and blocked evidence remain preserved and are not
  retroactively converted: this includes earlier FAIL/BLOCKED bundles, the
  `233336` history and prior 150-second surrender failure. The primary aggregate
  also explicitly retains unsafe-harness 3.3 and root-fixture 3.6 uncertainty,
  reports actual final combat rounds honestly, and notes differing source
  digests as scoped correction chronology. No G4/G5/G7/G9/G10 or full-rollout
  completion claim is made. Raw run artifacts were not rewritten.
