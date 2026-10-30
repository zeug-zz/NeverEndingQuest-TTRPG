# Current status banner (2026-10-23)

Current status: **IN_PROGRESS**. Task 6.4 and task 6.5 remain unchecked. The
historical BLOCKED records and incident text below are preserved verbatim; this
banner and the dated recovery addendum supersede only their former current-status
claims. See `reports/goal-recovery-2026-10-23.md` for reconciled goal and bundle
evidence. No G4 matrix completion or waiver is claimed.

# Task 6.4 - Primary-Owned G4 Live Verification

Status: **BLOCKED before execution**. The primary has not run any of the four
G4 live cases. Task 6.4 remains unchecked; task 6.5 remains unchecked. No live
PASS is recorded, and no gate or coverage waiver is granted.

## Blocking prerequisite

Owner confirmation that the exposed OpenAI key documented in the task-6.1
incident has been rotated is outstanding. No credential value was copied,
inspected, or recorded here. Live execution may resume only after that owner
confirmation and authorization to resume the goal, followed by a fresh tooling
recheck, primary preflight, and all four actual captures/reviews.

## Required live cases and acceptance evidence

The four required keys are `narrator-dialogue-travel:p1`,
`narrator-dialogue-travel:p4`, `combat-smoke:p1`, and `combat-smoke:p4`. The
narrator path observes startup CA01 separately, then five adjacent narrator
turns reaching CA02, CA03, CA03/Mira, CA02, and CA01. P4 switches to Merisiel
for Mira. The combat fixture must be the seeded Goblin case, not a random
encounter:

| Case | Required roster / fixture | Bounds |
|---|---|---|
| Narrator P1 | Acheron | 6 inputs / 8 controls; each turn <=300 seconds; health reads <=3 |
| Narrator P4 | Acheron, Merisiel, Kira, Vitreol; Merisiel active for Mira | 6 inputs / 9 controls; each turn <=300 seconds; health reads <=3 |
| Combat P1 | Acheron vs seeded Goblin (`capture_one_pc`) | 5 inputs / 7 controls; each turn <=300 seconds; health reads <=3 |
| Combat P4 | Acheron, Merisiel, Kira, Vitreol vs seeded Goblin Alpha and Goblin Beta (`capture_mp`) | 22 inputs / 35 controls; each turn <=300 seconds; health reads <=3 |

Each case requires complete real bundles and checks, actual OpenAI receipts,
truthful model and cost provenance (including actual zero, estimated, or
unpriced cost as applicable), persisted state projections, and actual backend
NPC output distinguished from echo. Receipts must establish actual task/model,
retry/fallback, usage, and cost observations; unexpected fallback blocks PASS.
Every expected/observed assertion and the complete bundle must be reviewed.
Any missing receipt/data, mismatch, timeout, exceeded cap, or failed check
prevents PASS. No declaration, synthetic bundle, mock, or exit code substitutes
for live evidence.

## Pre-execution record

- Verdict: **BLOCKED** for each of the four required keys; execution was not
  authorized because key-rotation confirmation is outstanding.
- Bundles: NONE. No live run directory or capture bundle was created.
- Counts: no live input, control, health-read, provider-attempt, or receipt
  counts are asserted.
- No server, live call, prepare/restore, sandbox mutation, or reserved run
  directory was used. No credentials or configuration were inspected.
- No baseline or historical incident was rewritten. The task-6.1 credential
  exposure history and the prior task-6.2/6.3 correction records remain intact.
- The read-only G3 compatibility audit recorded in the task-6.3 report is not
  G4 evidence and does not satisfy or waive this task.

Only the primary may resume this task after the stated prerequisite, tooling
recheck, and preflight. Task 6.5 final verification is still pending.

## Primary-owned resume and preflight addendum

- The BLOCKED status and outstanding-prerequisite statements above describe the
  historical pre-execution state. The task-6.1 exposure history remains
  historical and unchanged.
- The owner explicitly confirmed: "key rotated; resume goal". The primary then
  invoked `/resume_goal`; the goal is active. No credential value was inspected
  or recorded, and no credential restoration is claimed.
- Current status: **IN_PROGRESS - preflight**. Task 6.4 remains unchecked. No
  live PASS is recorded, and no capture bundles exist yet.
- Fresh primary guarded preflight: `scripts.test_capture_drive` PASS (61 tests),
  with an EMPTY configuration before load, shared fatal guards, and post-run
  assertions that guarded state remained untouched. Strict CORE validation
  PASS. Port 8360 has no listener.
- The primary will run and review all four required cases using the exact
  rosters, fixtures, bounds, and evidence path specified above and in the live
  verification spec. No actual capture has occurred yet; no live verdict is
  claimed by this preflight record.

## Tooling import correction addendum

The authorized primary `--gate g4 --party 1 --scenario
narrator-dialogue-travel --prepare` preflight succeeded, but stdout began with
`[UpdateCharacterInfo] Creating OpenAI client for chat` before sandbox copying.
The four protected root hashes were recorded at
`tmp/router-rollout/g4/preflight-1792358694080.json`. No server or capture was
started. This is evidence of unnecessary production runtime/SDK initialization
during tooling import, not an observed HTTP request or newly exposed key. The
credential value was neither observed nor exposed; logger-write outcome and
constructor arguments were not observed. The owner's prior rotation
confirmation remains valid; no new key leak is asserted.

The source-level correction is limited to moving the fixture module's eager
MultiPCCombatManager and CombatUserMessageCompressor imports into the provider-
free fixture-exercise functions that need them. The manager import chain
reached the DM-note/update-character owner; the compressor path reaches its
factory seam only during explicit fixture instrumentation. Seeder, driver,
evidence, profile and seed-builder imports/help now have fresh-process guards
which assert no owner import, SDK construction, network access, config.py read,
or outside write. This does not rerun prepare/restore, start a server, create a
live bundle, or assign any G4 verdict. Task 6.4 remains unchecked and requires
the primary's independent live rerun after this tooling correction.

Verification after the correction: guarded `scripts.test_capture_drive` PASS
(62 tests), guarded `scripts.test_runtime_area_hydration` PASS (14), guarded
`scripts.test_combat_latency_baseline` PASS (24), receipt adapter PASS (15),
and the five facade suites PASS in separate processes (88 router, 6 benchmark,
10 GPT-5.4, 6 mini shim, 41 Luna contract). Core inventory and request contract
suites also pass separately (14 and 17). The strict fresh-process import/help
case passes with zero tripwire calls and confirms prohibited runtime owners
remain absent; scoped compile, ASCII (zero violations), strict OpenSpec
validation, and `git diff --check` pass. The baseline, hydration, capture,
adapter, facade, inventory, and request results are software/tooling evidence
only. No live capture, prepare/restore rerun, server, credential use, live
bundle, or task-6.4 verdict was produced by this correction.

## Focused retry: actual CLI failure and regression correction

The primary subsequently reran actual root CLI `--prepare`; its first stdout
line again was `[UpdateCharacterInfo] Creating OpenAI client for chat`, before
the `[COPY]` status output. No server or capture started. This observed SDK
construction log precedes the copy-status output; no HTTP request was observed,
and no credential value was observed or exposed. This does not establish a new
key exposure. The prior owner rotation confirmation remains valid. The earlier
62-test PASS and statement that import/help was safe are retained as chronology
but do not establish actual CLI or seed-path safety: that run used EMPTY config
and did not execute the actual `__main__` path or `_seed_party()`.

Read-only source review traced the missing edge: the seeder imported
`utils.module_path_manager` at module scope, which initializes the global
`utils.enhanced_logger.GameLogger`/root file handlers. `_seed_party()` then
called `ModulePathManager.get_character_unified_path()`; its
`format_filename()` imports `updates.update_character_info.normalize_character_name`,
whose module scope calls `create_chat_client()`. The seeder now avoids importing
that manager and uses a fixed-roster-only character filename projection; its
optional injected path-manager contract remains. No product/runtime files or
general schema/path mechanics changed.

The replacement fresh-process test runs actual seeder, driver, and evidence
scripts through `runpy` as `__main__` with `--help`, then tests both top-level
and package fixture namespaces and seed builders in fresh processes. A
NONEMPTY dummy sentinel key plus needed config fixture fields prevents the
empty-key branch from hiding construction. Both multiplayer/debug flag
combinations are covered. SDK construction, networking, root rotating-log
construction, private root `config.py` reads, and outside writes are guarded
before application imports; runtime update/NPC/compressor owners must remain
absent. The child asserts zero guard trips. Focused capture tests (62) and
baseline tests (24) pass after this correction; that evidence is limited to the
tested import/help/pure-builder paths. The strict import regression itself
passed seven separate child processes (three `__main__ --help` entrypoints and
four seed-builder processes for the 2x2 multiplayer/debug flags); its final
rerun after adding direct `io.open_code`/`os.open` private-config denials also
passed. No prepare/restore or live operation was run by the builder. The
primary must separately decide whether to rerun actual prepare; task 6.4 remains
unchecked and no live PASS is claimed.

## Primary-supplied actual narrator P1 failure and tooling correction

Primary supplied the retained bundle
`tmp/router-rollout/g4/20261018T-g4-narrator-p1-1792358694080/` for the first
actual G4 case. The capture itself completed five inputs, seven controls, two
read-only health observations, zero gameplay timeouts, and 16 actual core
OpenAI `gpt-6-luna` receipts; all observed receipts have `fallback=false` and
explicit unpriced cost. Persisted locations were CA02, CA03, CA03, CA02, CA01,
and Warden Mira's actual response was observed. The offline evaluator correctly
returned FAIL for `narrator_input_echo_transcript_mismatch:1..5`: socket
transcript rows contain `type=user-input author=Acheron content=...`, while the
evaluator previously expected a row without author metadata. The retained
transcript bytes are unchanged. The outer context tool RPC timed out, but the
capture driver itself completed in 102.4 seconds and its retained manifest says
timeouts=0; the RPC timeout is monitoring uncertainty, not a driver turn
timeout, unknown CLI exit, or G4 pass.

The tooling correction parses only the exact allowlisted socket-record shape,
then compares the actor and complete content exactly. Wrong-author, wrong-
content, echo-only lookalike, and wrong event-type fixtures are rejected. G4
checks are now scenario-owned: narrator runs explicitly mark combat-only
encounter/mechanics/batch checks N/A and non-required, and require source-backed
narrator route/actor, Mira-backend, roster and trace observations. Combat G4
checks remain required. The offline evaluator rejects any failed or blocked
REQUIRED check and verifies the narrator applicability contract; it does not
waive degraded runs or weaken receipt/backend requirements. G3's raw 18-key
matrix, default behavior, and bare latency behavior are unchanged.

The primary also supplied an out-of-scope observation in the retained server
log: the location-summary API returned HTTP 400 for unsupported
`temperature=0.8`. This is recorded as a phase-5 callsite follow-up, not fixed
here and not represented as core-live success; product summary correction is
outside this patch scope pending approval. Primary positively verified and
stopped owned server group 81260/listener 81264. Port 8360 was subsequently
empty; the sandbox state was preserved. Four protected root hashes were
unchanged. The failed raw bundle, earlier incident chronology, and report
history remain intact; no raw bundle/log/state was modified.

## Attributable 6.3 acceptance correction

The 6.3 record above is retained. This narrow follow-up makes source-grounded
G4 transcript checks author-aware and enforces retained per-run REQUIRED-check
applicability/results during offline evaluation. It does not alter profile
coverage, limits, receipt requirements, G3 behavior, production behavior, or
the prior acceptance evidence. This correction is tooling-only and does not
produce a PASS for any actual G4 case.

## Primary-supplied actual combat P1 receipt blocker and focused tooling correction

The primary supplied the retained, read-only bundle
`tmp/router-rollout/g4/g4-combat-p1-1792360745994/`. It records four gameplay
inputs, six controls, two read-only health observations, zero timeouts, and all
13 REQUIRED mechanics checks PASS. Its trace contains 17 provider rows: 16
actual core receipt rows with paired `call_id`/`attempt_id`, task, provider,
model, and outcome data, plus one legacy `site="combat_compression"` event
without task, call/attempt identity, provider, model, outcome, or cost fields.
The prior projector returned BLOCKED with
`invalid_or_duplicate_receipt_identity`; the bundle and all of its bytes remain
unchanged and its status remains BLOCKED.

Source audit establishes the narrow exclusion: the exact site is emitted in
`core/ai/combat_compression_engine.py` after its direct
`self.client.chat.completions.create(...)` call via
`trace_provider_call("combat_compression", ...)`. This owner is outside the
15 semantic operations in `reports/core-chat-inventory.md`; those owners and
their task/site receipts remain core accounting. No broader legacy-site
allowlist was inferred. The unmigrated direct compressor is retained as a
classified, separate legacy provider observation, not a routed SDK attempt.

The focused collector change keeps every provider trace row positioned and
assigned to exactly one startup/step span. It returns core receipts separately
from legacy observations and reconciles their sum against the raw provider-row
counter. The legacy record preserves its raw metadata and byte position/line
plus paired step, and labels provider, model, and cost as unknown; it receives
no task or fabricated attempt/call identity. Only the audited legacy shape for
the exact `combat_compression` site is accepted. Partial/core identities,
core-task spoofing under that site, malformed compression counters, unknown or
mismatched sites, duplicate coverage, and unpaired rows remain BLOCKED.
G3 raw-18/default/bare-latency/profile/step/SDK-parameter/runtime contracts
are unchanged.

Read-only projection of the retained combat P1 trace through the corrected
collector returns 16 core receipts (8 `combat_main`, 8 `combat_validation`) plus
one `combat_compression` legacy observation, for 17/17 provider rows. The
legacy observation pairs to step 4 and retains unknown provider/model/cost
labels without IDs. Trace parsing and step-snapshot loading report no errors.
This is a projection-only tooling check: the retained manifest's original
`BLOCKED` status and all raw bytes remain unchanged; it is not a rewrite,
backfill, candidate readiness, or live verdict.

The real mixed-stream test uses `LLMRouter` with fake SDK transport, the real
legacy receipt adapter and JSONL trace writer, and the writer's
`trace_provider_call` compression-event shape. It verifies core-versus-legacy
count reconciliation, startup and step byte-span pairing, preserved legacy
metadata, and explicit unknown provenance. Full synthetic combat-smoke P1/P4
driver cases now also include a real-writer-shaped legacy compression row;
they remain marked synthetic and `live_eligible=false`. Synthetic coverage
does not update or backfill the retained bundle and is not live eligibility.

The following historical primary reviews remain as recorded:
`g4-narrator-p1-1792360319245` PASS and
`g4-narrator-p4-1792360530876` PASS. Because source identity is strict, the
tooling change requires fresh primary-owned matrix captures after tooling
verification; it does not confer a current four-key matrix PASS. G4 remains
incomplete, the actual combat P1 bundle remains BLOCKED, and no accounting
claim is made for the unmigrated phase-5 compressor beyond this classified
observation.

## Focused provider-free receipt-tooling verification

Separate guarded provider-free processes passed after the correction:

| Suite/check | Result |
|---|---:|
| `scripts.test_capture_drive` | PASS, 63 tests; guarded before runtime-owner imports |
| `scripts.test_runtime_area_hydration` | PASS, 14 tests; fatal process tripwires and dummy sentinel config |
| `scripts.test_combat_latency_baseline` | PASS, 24 tests; fatal process tripwires and dummy sentinel config |
| `scripts.test_llm_runtime_receipt_adapter` | PASS, 15 tests; fatal process tripwires and dummy sentinel config |
| `scripts.test_llm_router` | PASS, 88 tests; fatal process tripwires and dummy sentinel config |
| `scripts.test_benchmark_model_profiles` | PASS, 6 tests; fatal process tripwires and dummy sentinel config |
| `scripts.test_gpt54_chat_params_contract` | PASS, 10 tests; fatal process tripwires and dummy sentinel config |
| `scripts.test_gpt54_mini_chat_params_shim` | PASS, 6 tests; fatal process tripwires and dummy sentinel config |
| `scripts.test_gpt56_luna_direct_openai_contract` | PASS, 41 tests; fatal process tripwires and dummy sentinel config |
| `scripts.test_core_chat_inventory_contract` | PASS, 14 tests; process tripwires armed before imports; its expected-tripwire cases perform their own untouched-state assertions before invoking test sentinels |
| `scripts.test_core_chat_request_contracts` | PASS, 17 tests; fatal process tripwires and dummy sentinel config |
| Scoped `py_compile` for capture evidence/driver/test | PASS; cache prefix `tmp/g4-receipt-focus-pycache` |
| `python3 scripts/check_ascii_compliance.py --summary-only` | PASS, 1,148 files scanned / 0 violations |
| `OPENSPEC_TELEMETRY=0 DO_NOT_TRACK=1 openspec validate llm-router-core-migration --strict` | PASS |
| Scoped trailing-whitespace scan of the four changed files | PASS, none |

No `git diff --check` was run because this handoff explicitly prohibited Git
operations. All scratch/cache output used project-relative `tmp/`; no absolute
`/tmp/` path was used. No raw bundle, state, transcript, server log, historical
review, production route, SDK behavior, or live eligibility was changed. No
server, API/provider, prepare/restore, campaign, credential/private config, or
reserved live sandbox was accessed. Synthetic full combat P1/P4 bundles remain
synthetic and ineligible; fresh primary-owned matrix captures and review are
still required after tooling identity changed.

## Guarded real-package import-fixture correction

The next strict guarded pre-live 41-module baseline reached its combat-manager
contract module after the earlier C5 (60 tests) and action-predictor (5 tests)
passes. Its prior 35 assertions had six setup/import errors: importing the real
legacy/package aliases reached `updates.update_character_info`, whose
module-level `create_chat_client()` attempted the actual `OpenAI` constructor
and correctly tripped the shared fatal SDK guard. This was an import-fixture
failure, not a production semantic assertion failure. No SDK client was
constructed, no request/network operation occurred, and no credential or
private configuration value was observed.

Only `scripts/test_combat_manager_decomposition_contract.py` changed. The test
module now arms `arm_process_tripwires()` before owner imports and denies reads
of root `config.py` and `party_tracker.json` via `builtins.open`, `io.open`, and
`os.open`. Its dummy `config` module is built only from public `model_config`
constants plus nonempty dummy key sentinels. Before importing the actual
package and compatibility aliases, it patches only
`utils.ai_client_factory.create_chat_client` to return a known inert client;
the inert completion `create` raises `TripwireFailure`, and all shared SDK,
network, and write guards stay armed. No production owner module, package
alias, class, callback, session/thread logic, or tested function is replaced.
The original 35 package-identity, lifecycle, thread, source-binding, and
behavior assertions are retained, with one sentinel test proving private-read
denials, no inert-client requests, and untouched process tripwires.

The actual owner/alias imports are bounded to a unique `tmp/` current directory
only during import, then the original repository CWD is restored before any
test or source-path assertion runs. The import fixture is stopped after the
suite, then only its own scratch directory is cleaned. Two lazy-import child
process tests independently arm the shared guards, private-read denials, dummy
config, and inert factory seam before project imports; their own import-only CWD
directories are removed on child exit. Neither child assumes parent-process
patches are inherited.

Guarded rerun: `scripts.test_combat_manager_decomposition_contract` PASS (36
tests: 35 retained plus one safety proof; 0 errors, 0 failures). The import
factory seam was called 5 times during real owner imports; the known inert
client observed 0 completion requests. All shared fatal SDK/network/write
tripwires had 0 calls. The three deliberate read probes were denied exactly as
expected: `builtins.open` for root `config.py`, `io.open` for root
`party_tracker.json`, and `os.open` for root `config.py`; there were no private
root reads during imports/tests. Actual package alias and source-path assertions
passed with repository CWD restored, and all test-created worker threads were
joined by their original cases before fixture restoration.

Scoped `py_compile` PASS with
`PYTHONPYCACHEPREFIX=tmp/task-6-4-combat-contract-pycache`; strict ASCII and
trailing-whitespace scan of the changed test and this report PASS (88,603 bytes,
zero non-ASCII bytes, zero trailing whitespace). The subprocesses made no API
or network calls and touched no protected root configuration/runtime files.
Only unique project-relative `tmp/` scratch/cache paths were used. This repairs
the provider-free baseline harness prerequisite only: it is not a live capture,
does not authorize server/prepare/restore/campaign/config access, does not
change any G4 verdict, and does not complete task 6.4 or the later task 6.5
baseline.

## Focused C5 pre-live harness correction

The primary pre-live 41-baseline rerun stopped at its first module, C5:
54 tests passed, then `TestC4Hardening.setUpClass` failed before its five tests
because the strict dummy config fixture omitted `COMBAT_MAIN_MODEL`. That
fixture-setup error did not itself show an SDK or read-guard hit; it is not
evidence of unsafe SDK execution. The historical 705/41 software baseline
claims above are retained and are not retroactively restated as current
guarded-run evidence.

Only `scripts/c5_regression_combat.py` changed for the harness fix. Its C4
validator loader no longer imports the full combat runtime owner or installs
fake OpenAI calls and global module stubs. It parses the actual
`core/combat/combat_manager.py` source and executes the unchanged actual
`validate_combatant_integrity` function together with its complete pure helper
closure: `_collect_authoritative_combat_roster`,
`_normalize_combatant_name`, and `_name_matches_authoritative_roster`. The
loader verifies all four source definitions are present and preserves the
public four-parameter function signature. Existing tests continue to pass
explicit in-memory `encounter_data`, `multi_pc_manager`, and
`party_tracker_data` fixtures; no root party/config fixture is read, and no
integrity, roster, or normalization behavior is replaced. The 59 pre-existing
C5 assertions and source-golden checks were not rewritten or weakened.

Before project-owner imports, C5 now arms the shared fatal process tripwires
for SDK construction, network operations, and outside writes, and installs
focused fatal denials for root `config.py` and `party_tracker.json` reads. Its
single additional safety case proves those root reads are denied, exercises
provider/network/outside-write denial hooks, and confirms no such tripwire was
invoked during the AST-backed validator load. This path does not use an
owner-import loop, `sys.settrace`, an SDK-class guard override, or a no-op fake
SDK call. The separate combat-manager package/lifecycle contract suite also
passed (35 tests), but emitted client-initialization diagnostics; that suite
is not relied upon as evidence for this pre-import safety proof.

Focused software verification: C5 PASS (60 tests: 59 existing plus one safety
case); `scripts.test_combat_canonical_validation_facts` PASS (3);
`scripts.test_combat_truth_pack` PASS (8); and
`scripts.test_combat_manager_decomposition_contract` PASS (35). Scoped
`py_compile` of C5 PASS using
`PYTHONPYCACHEPREFIX=tmp/c5-integrity-prelive-pycache`. These results are
focused software/tooling checks only. C5's guarded run made no API call. The
separate manager-suite client-initialization diagnostics are not treated as
evidence of provider/network activity or of its absence. No live capture,
server, prepare/restore, campaign/config value, or task-6.4 verdict is claimed.

## Focused action-predictor parameter-harness preflight correction

The strict pre-live 41-case first batch reported C5 PASS at 60 tests. The first
attempt to run the action-predictor parameter contract then stopped in its
fixture setup because `ACTION_PREDICTION_MODEL` was missing. After that fixture
was supplied, importing the actual `utils.action_predictor` module reached its
real SDK constructor at line 47 (`OpenAI(api_key=OPENAI_API_KEY)`) and was
blocked by the armed SDK-constructor tripwire before construction. The attempt
used no real key, made no network request, and inspected or exposed no secret.

Only `scripts/test_action_predictor_params_contract.py` changed. Its harness
now arms the shared SDK/network/outside-write tripwires and private root
`config.py`/`party_tracker.json` read denials before project-owner imports. It
loads the actual full `predict_actions_required` function and its actual prompt
constant through a bounded AST namespace, injects `ACTION_PREDICTION_MODEL`
from public `model_config.py`, and uses the actual
`utils.ai_client_factory.get_chat_completion_params` helper. The injected
client is inert: its unpatched `create` raises a fatal sentinel; only the
existing narrowly scoped response/error patches can call it. A complete dummy
config fixture copies public `model_config` constants and uses nonempty
`DUMMY_OPENAI_KEY` and `DUMMY_OPENROUTER_KEY` values. No production owner module
is stubbed, and no predictor/transport behavior is replaced. The four prior
parameter-contract tests and assertions remain; one focused guard-proof test
was added. The three optional neighboring parameter harnesses were inspected
and left unchanged.

Guarded software verification: `scripts.test_action_predictor_params_contract`
PASS (5 tests, including the one added guard proof);
`scripts.test_character_update_model_params` PASS (3 existing tests);
`scripts.test_character_validator_params` PASS (2 existing tests); and
`scripts.test_combat_compression_params` PASS (5 existing tests). All 14 prior
parameter-contract cases pass, with the new safety case bringing the aggregate
to 15. The action-predictor proof explicitly denies private config and party
tracker reads through `builtins.open`, `io.open`, and `os.open`; SDK, network,
and outside-write guards were untouched during loading and tests. The actual
SDK constructor was never called. Scoped `py_compile` PASS with cache prefix
`tmp/task-6-4-legacy-params-pycache`; scoped ASCII-Python and trailing-whitespace
checks PASS (zero violations across 607 lines). No product files, helper implementation,
request logic, prompt, or other harness was changed. These are provider-free
software checks only: no API/network/live call, server, prepare/restore,
campaign/config value, or task-6.4 verdict is claimed. The task remains
unchecked and subject to the outstanding primary-owned authorization and live
verification requirements above.

## Focused PC action parser baseline harness isolation

The guarded pre-live parser baseline initially reported 26 passing tests and two
setup errors. In `test_character_update_failure_returns_false` and
`test_encounter_update_failure_returns_false`, dotted `mock.patch` targets
imported `updates.update_character_info` and `updates.update_encounter`. Their
module initialization tried to construct OpenAI clients and correctly hit the
shared SDK-constructor guard. The tests intend to exercise the real
`apply_pc_phase_parse_result` orchestration's handling of updater failure, not
the updater implementations.

Only `scripts/test_combat_pc_action_parser.py` and this report changed. The two
failure tests now inject `ModuleType` dependencies for the exact
`update_character_info` and `update_encounter` functions through `sys.modules`;
the character updater returns `False` for its failure case, and the encounter
updater returns `False` for its failure case. The parser's actual
`apply_pc_phase_parse_result` owner and sequencing remain real. Assertions
verify the character updater's exact name, changes text, and ops arguments,
encounter updater invocation/non-invocation, false result, and absence of a
ledger write on failure. No full updater module, updater-created client, or
error-logger import is needed. The other 26 parser tests and all parser and
normalizer behavior are unchanged; no parser fake or weakened result,
mutation, or error assertion was introduced.

Before parser/owner imports, the harness arms shared fatal SDK-constructor,
network, and outside-write tripwires, then denies private root `config.py` and
`party_tracker.json` reads through `builtins.open`, `io.open`, and `os.open`.
Configuration is a nonempty dummy module populated from public
`model_config.py` constants and dummy key sentinels; the private root config is
not loaded. Its guard-proof test verifies all six deliberate private-read
probes (three APIs for each file) are denied and shared SDK/network/write
tripwires remain untouched (zero calls). The two fixture dependencies are
limited to the updater functions needed by these exact failure assertions; no
broader parser or orchestration owner is replaced.

Verification: `scripts.test_combat_pc_action_parser` PASS (29 tests: the prior
28 plus one guard-proof test, zero failures/errors); related pure contracts
`scripts.test_combat_canonical_validation_facts` and
`scripts.test_combat_truth_pack` PASS (11 tests total); scoped `py_compile`
PASS using `PYTHONPYCACHEPREFIX=tmp/pc-action-parser-baseline-pycache`; strict
ASCII and trailing-whitespace checks PASS for the test and this report (2/2
ASCII files, zero trailing-whitespace lines). This is provider-free test
harness evidence only. No API/server/prepare/restore/campaign operation,
credential or private config value access, production parser change, or live
G4 verdict is claimed. No absolute `/tmp/` path or unrelated scratch cleanup
was used.

## Guarded pre-live baseline import-safety prerequisite

This is a narrow patch-only correction to the four import-blocked suites in
the read-only primary evidence file
`tmp/router-rollout/g4/prelive-baseline-20to41-v1.json`. That historical record
shows the `scripts.test_combat_resume_replay_guards` and
`scripts.test_update_encounter_ops_runtime` import-time `openai.OpenAI` trips,
the `scripts.test_combat_state_coherence_repair` owner-chain trip, and the
`scripts.test_multi_pc_combat` owner import reaching `combat_logs` creation.
Those are blocked imports, not product assertion failures. The reported
historical 705 assertions remain historical only and are not retrospectively
reclassified as guarded PASS evidence.

### Test-harness correction and retained behavior

- `scripts.test_combat_resume_replay_guards` now arms the shared fatal process
  guards before project imports. Replay helpers are the actual
  `_coerce_int`, `_normalize_name_key`, `_extract_expected_enemy_transitions`,
  and `_is_prepared_encounter_ops_replay` source definitions and their pure
  constant/helper closure, AST-compiled from `updates/update_encounter.py`;
  their existing replay/transition assertions are unchanged. The two existing
  historical-summary helper imports remain real. One guard-proof case was
  added.
- `scripts.test_combat_state_coherence_repair` installs a dummy `config` module
  made from public `model_config` constants plus nonempty dummy key sentinels
  before actual owner imports. It imports actual
  `core.managers.combat_manager`, the actual multi-PC compatibility module and
  classes, and the actual `_apply_character_ops_deterministic` implementation.
  Only the known unused import-time `utils.ai_client_factory.create_chat_client`
  seam is temporarily replaced by an inert client whose completion call raises
  the fatal sentinel. The shared SDK/network/write guards remain active. Imports
  run under this test's unique project-relative `tmp/` CWD only; the original
  CWD is restored before test execution. Its nine prior behavior assertions are
  retained; one guard-proof case was added.
- `scripts.test_multi_pc_combat` no longer installs fake OpenAI, updater,
  compressor, core-AI, or owner modules for integrity validation. Its real
  `core.managers.multi_pc_combat` imports/classes remain intact; the integrity
  check uses C5's established actual-source AST loader for the full validator
  and its pure helper closure. Its 73 prior behavioral assertions and normalizer,
  source-ownership, and class-identity checks remain; one guard-proof case was
  added. The two end-session cases isolate only the otherwise-unasserted
  persistence side effect by patching that manager instance's
  `persist_combat_changes`; the actual `end_combat_session` lifecycle and
  original ledger/manager cleanup assertions remain exercised.
- `scripts.test_update_encounter_ops_runtime` now arms all shared guards before
  importing the actual `updates.update_encounter.update_encounter` owner. Its
  config fixture is sourced from public `model_config` and includes nonempty
  dummy keys; only the known unused import-time chat-client factory seam is
  replaced with an inert client that fails fatally if asked to complete. The
  actual update, supported-op preparation/application, validation, and
  persistence paths remain exercised with the original unique project-`tmp/`
  fixture and explicit in-memory party-tracker file. All four prior behavior
  cases and assertions remain; one guard-proof case was added.

For all four suites, `arm_process_tripwires()` runs before production-owner
imports. Its shared fatal SDK-constructor, socket/network, and outside-write
guards remain armed. Direct root `config.py` and `party_tracker.json` read
probes through `builtins.open`, `io.open`, and `os.open` are denied by fatal
`BaseException` sentinels; dummy fixture values are not loaded from root
configuration or party data. No SDK-class override, empty-key fixture,
`None`-client fallback, broad production-module fake, route/model/prompt change,
or test-count waiver is used. The update-encounter runtime's fixture-bound
write guard additionally restricts runtime mutations to its unique owned
fixture directory and keeps the shared tripwires active.

### Guarded software verification

All four suites passed in separate processes, each with the shared fatal guards
and direct private-root read denials armed before project owner imports:

| Suite | Result |
|---|---:|
| `scripts.test_combat_resume_replay_guards` | PASS, 8 tests (7 retained + 1 safety proof) |
| `scripts.test_combat_state_coherence_repair` | PASS, 10 tests (9 retained + 1 safety proof) |
| `scripts.test_multi_pc_combat` | PASS, 74 tests (73 retained + 1 safety proof) |
| `scripts.test_update_encounter_ops_runtime` | PASS, 5 tests (4 retained + 1 safety proof) |

Related guarded checks also passed: C5 regression (60), combat-manager
decomposition/real-import fixture contract (36), and PC action parser plus
canonical-validation facts and truth-pack checks (40). Scoped `py_compile` of
the four changed tests passed using
`PYTHONPYCACHEPREFIX=tmp/task64-pycache`. Repository strict ASCII check passed
(1,148 files scanned, zero violations). The test run logs are under unique
project-relative paths `tmp/task64-*-guarded.log`; the C5, manager, parser, and
compile artifacts also use project-relative `tmp/` only. Scoped non-ASCII and
trailing-whitespace check passed for all four test files and this report, and
for the edited regions of the large multi-PC suite (zero issues).

### Limits and stop condition

These are guarded provider-free test-harness/software results only. The shared
tripwires were untouched during module loading and test execution; the safety
proof cases deliberately invoked the denial hooks and verified their fatal
sentinels. No real key/config value was read, no API/network request or server
was used, no prepare/restore or campaign operation occurred, no raw historical
bundle was opened or changed, and no live capture or G4 verdict was produced.
Task 6.4 remains unchecked and live-incomplete; task 6.5 remains pending. The
primary's independent live authorization, preflight, four captures, and review
requirements above remain unchanged. STOP here; this patch does not authorize
any live work.

## Dated recovery addendum (2026-10-23)

The preceding historical status, incident, failure, and BLOCKED statements are
retained verbatim. This addendum records newer independently verified evidence
and corrects only the stale progress checkpoint; it does not reopen or erase any
historical verdict.

- Goal recovery: the existing goal `1ee9341a-6823-4688-90fe-a22485ccf73f` from
  source session `ses_ecdcd4b80ffeTiY5Zeu1KVbcyK` was retained, with plan revision
  13 advanced to revision 14 by a plan operation. Its full objective, eight
  phases, ten completion criteria, completed evidence, and decisions were
  retained. No successor goal was needed. The cancelled predecessor
  `9d3345c5-2ae8-415e-b550-04c20f802d14` remains closed. Phase 1/G2 and phase 2/G3
  remain complete; phase 3/G4 is in progress; phases 4-8 remain pending. The
  revision-13 top summary is historical; this recovery amendment supersedes its
  stale progress/blocker description, not its completion criteria.
- The owner-confirmed key-rotation checkpoints `1792358464` and `1792358574`
  remain valid. No new confirmation was needed. No secret or credential value
  was accessed.
- Pre-live software evidence is 875 tests across 53 separate processes (758
  baseline and 117 affected), all with status 0, in
  `tmp/router-rollout/g4/prelive-baseline-final-first20.json`,
  `tmp/router-rollout/g4/prelive-baseline-final-last21.json`, and
  `tmp/router-rollout/g4/prelive-affected-extra.json`. This is pre-live evidence,
  not task 6.5 final verification; the historical 705-test count is unchanged.
- `g4-final-combat-p1-1792364191592` has primary review PASS for
  `combat-smoke:p1`: 4 inputs, 6 controls, 2 health reads; 6 core receipts and
  one separately classified legacy `combat_compression` observation. Its
  canonical combat round moved 1 to 2. `primary-review.json` records the case-
  only scope; the manifest records all 15 artifact hashes matching, recorded
  dirty-source files matching the worktree, and source digest
  `297d98ccdcbb17fb0b5ed96d74c1d6a848f21675d6be20a9cfc741d267c5165b`.
- `g4-final-combat-p4-1792364420538` has primary review PASS for
  `combat-smoke:p4`: 19 inputs, 32 controls, 2 health reads; 20 core receipts and
  6 separately classified legacy `combat_compression` observations. Its
  canonical combat round moved 1 to 2. Script labels r1/r2/r3 do not establish
  three canonical rounds. The primary review explicitly limits its PASS to this
  case and says the current-source narrator P1/P4 cases remain necessary. Its
  recorded artifact hashes and dirty-source files match; source digest is the
  same `297d98ccdcbb17fb0b5ed96d74c1d6a848f21675d6be20a9cfc741d267c5165b`.
- Earlier narrator primary reviews `g4-narrator-p1-1792360319245` and
  `g4-narrator-p4-1792360530876` remain historical PASS records, not current
  matrix evidence: their source digest
  `1e811baf9a11f6e41abf658b775bb64f96e445cd2792fc6eb42705e5a05a28b0` differs
  only in recorded `capture_drive`/evidence files. The strict same-source matrix
  cannot use them as current-source coverage.
- A current-source candidate exists at
  `tmp/router-rollout/g4/g4-final-narrator-p1-1792364780759`. Its manifest
  records 17 artifact hashes, all matching, source digest
  `297d98ccdcbb17fb0b5ed96d74c1d6a848f21675d6be20a9cfc741d267c5165b`, and
  5 inputs, 7 controls, 2 health reads, 16 core receipts, and no legacy
  observations. Its checks include the narrator route/actor and actual Mira
  backend response. However, it has no `primary-review.json` and
  `checks.json.primary_verdict` is `PENDING`; it is not promoted or represented
  as PASS. No matching current-source narrator P4 bundle is recorded.
- The next 6.4 action is for the primary to inspect the preserved narrator P1
  candidate before deciding whether to rerun, then complete current-source
  narrator P4 and the primary four-key matrix review. Only after that should
  task 6.5 and later phases proceed. This documentation recovery did not run
  live work, prepare/restore, a server, credential inspection, or tests, and it
  does not declare G4 complete. The phase-5 `temperature=0.8` location-summary
  follow-up and legacy compression provenance uncertainty remain open.

## Primary review and P4 stop condition addendum (2026-10-23)

This later addendum appends to, and does not overwrite, the preceding recovery
record. The retained narrator P1 candidate has now been inspected by the
primary, who wrote the exclusive new
`tmp/router-rollout/g4/g4-final-narrator-p1-1792364780759/primary-review.json`.
It records `narrator-dialogue-travel:p1` as **PASS**, case-only, with all 17
manifest artifact hashes and recorded source hashes verified; the raw artifact
bytes were unchanged.

The primary reviewed the transcript, all before/after and per-step snapshots,
all 16 core receipts, and server diagnostics. The review records PASS for the
six persisted startup/route locations and Acheron actor/roster, Warden Mira's
actual backend response distinct from the user echo, unchanged Acheron record
hash `5d9792c37d5a6ffdbf875409ea332bfd9ca8e4f0b04bf5bf7ca215de615348ff`, empty
active encounter and no resource/reward mutation, bounds of 5 inputs / 7
controls / 2 health reads with zero timeouts or caps, and 16 uniquely paired
OpenAI `gpt-6-luna` core receipts with complete usage, no fallback, and cost
explicitly labeled unpriced. The review retains a semantic correction on step 5.
Unmigrated phase-5 HTTP 400 diagnostics for transition-validator `temperature`
0.3, adventure summary 0.8, and quest formatter 0.3 remain excluded follow-ups;
no successful operation claim is made for those paths.

Current-source primary-reviewed cases are now combat-smoke P1/P4 and
narrator-dialogue-travel P1. G4 remains incomplete because current-source
narrator P4 is missing, and task 6.5 remains unchecked.

Before P4 preparation, the primary observed listener PID 77348 on port 8360.
`lsof` positively tied both PIDs 77345 and 77348 to cwd `tmp/combat_capture`
and stdout/stderr
`tmp/router-rollout/g4/server-g4-final-narrator-p1-1792364780759.log`. The
primary attempted TERM only for these positively owned processes; both attempts
were denied with `operation not permitted`. `ps` metadata inspection was also
denied. No retry, broader kill, permission widening, port-8357 access,
prepare/restore, server start, live/network operation, or credential access is
authorized by this patch. The next step requires the owner to stop the retained
capture processes before P4 work can continue.

The owner clarified that Nono has a diagnostic path bug that can strip leading
directories and report invented root paths. `nono why` for the exact intended
repository report path and for `/bin/python` returned ALLOWED; no new filesystem
grant was requested. This clarification does not change the process-ownership
stop condition or authorize retrying termination. The original restrictions
remain in force. No gate or coverage waiver is granted.

## Narrator P4 capture and G4 matrix review (2026-10-23)

The owner stopped stale PIDs 77345 and 77348; port 8360 was observed free before preparation. `--gate g4 --party 4 --scenario narrator-dialogue-travel --prepare` passed, and the installed tree remained unchanged. The capture-only server was started from `tmp/combat_capture` with `NEQ_OPEN_BROWSER=0`, using the `run_web.main()` entry on port 8360.

Declared expectations were roster Acheron/Merisiel/Kira/Vitreol; actors Acheron, Acheron, then Merisiel three times; locations CA01 startup followed by CA02, CA03, CA03, CA02, CA01; no more than 6 inputs, 9 controls, 3 health reads, and 300 seconds per turn; a backend Mira reply; and OpenAI with no fallback. Observed: 5 steps, 8 controls, 2 health reads, 0 timeouts, and 152.6 seconds; all locations and actors PASS; Mira reply PASS; 16 core receipts equal 16 trace rows, all `openai`/`gpt-6-luna`/fallback false, with cost `unpriced_unknown`; four character-record hashes unchanged across 12 snapshots; and 17 artifact hashes verified. The source `relevant_dirty_sha256` equals narrator P1.

The driver printed `automated_status=BLOCKED` in-run, the same pattern as narrator P1, while the post-run offline evaluator on the retained bundle was READY with no problems. Retained phase-5 HTTP 400 temperature diagnostics (transition validator 0.3, adventure summary 0.8, quest formatter 0.3) are not claimed as successes. The owned server was stopped via TERM and `--restore` passed; the sandbox was removed and the installed tree was untouched.

The four same-source bundles each have primary PASS: narrator P1 `g4-final-narrator-p1-1792364780759`, narrator P4 `g4-final-narrator-p4-1792749441000`, combat P1 `g4-final-combat-p1-1792364191592`, and combat P4 `g4-final-combat-p4-1792364420538`. The matrix evaluator is READY_FOR_PRIMARY_REVIEW for 4/4 keys with no missing, duplicate, failed, or invalid entries. The primary matrix verdict is PASS in `tmp/router-rollout/g4/g4-final-matrix-review-1792749441000.json`; evaluator output is `tmp/router-rollout/g4/g4-final-matrix-1792749441000.json`. Task 6.4 is PASS and the G4 live portion is complete. Task 6.5 final verification remains pending, so G4 overall is NOT yet complete.
