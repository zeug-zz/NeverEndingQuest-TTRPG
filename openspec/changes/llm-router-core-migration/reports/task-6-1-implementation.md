# Task 6.1 - Fixed G4 Profile and Sandbox Preparation

Status: task 6.1 implementation and primary guarded provider-free verification
complete. Overall change accounting is 21/25 tasks checked, 15/15 inventoried
chat operations routed, and tasks 6.2-6.5 remain pending. This report does not
claim any G4 live capture or later G4 tooling task.

## Scope implemented

- Added the fixed `--gate g3|g4` selector to the existing capture driver and
  seeder, with G3 as the default. G3 continues to resolve through its existing
  profile builder. Bare latency invocation behavior is unchanged. Invalid gate,
  party, scenario, branch, and phase combinations fail during preflight before
  sandbox or transport side effects.
- G4 currently accepts only the fixed `narrator-dialogue-travel` and
  `combat-smoke` profiles. The driver rejects G4 capture execution before
  transport with an explicit task-6.2 deferral; G4 execution/evidence work was
  not pulled into this task.
- Narrator profile: five fixed turns at CA01, CA02, CA03, Mira's shrine
  question, and return through CA02 to CA01. P1 actor is Acheron; P4 switches to
  Merisiel for the Mira turn. Metadata declares max 6 inputs, 8 P1 / 9 P4
  controls, 300 seconds per turn, and a separate maximum of 3 health reads.
  The health read counter is independent of gameplay controls and rejects a
  fourth read before calling the fake transport.
- Combat profile reuses the fixed seed builder: P1 party Acheron vs `Goblin`
  (`capture_one_pc`); P4 Acheron/Merisiel/Kira/Vitreol vs `Goblin Alpha` and
  `Goblin Beta` (`capture_mp`). It declares the existing 5-input/7-control and
  22-input/35-control limits, 300 seconds per turn, and 3 health reads. No
  randomized encounter substitute was added.
- G4 narrator sandbox preparation transforms only the sandbox copies of
  `modules/Capture_Arena/areas/CTR001_BU.json` and `CTR001.json`. Both copies
  receive the same peaceful CA02 text and empty `monsters` list; plot/context
  files are not changed. The narrator party starts at CA01 with an empty
  `activeCombatEncounter` and no encounter file. G3 seeding is unchanged.
- The authored CA03 area NPC is Warden Mira. The actual narrator context path
  is `main.main_game_loop()` -> `update_conversation_history()` before
  `get_ai_response()`. `core/ai/conversation_utils.py` reads the selected area
  from `ModulePathManager.get_area_path(currentAreaId)`, selects the matching
  `currentLocationId`, and appends the full location dictionary (excluding only
  `adventureSummary`) as the `Current Location` system message. Its `npcs`
  array, including Mira's name and description, therefore reaches narrator
  context without a persisted character record. The separate validation
  projection in `main.py::create_module_validation_context` also reads
  location `npcs`; `extract_npcs_from_area` is only that validation reader,
  not the basis of the narrator-path claim. Tests assert the source call order,
  extraction and authored CA03 content, and that the narrator seed has no
  `npc_characters` payload. No Mira character/PC file or media is seeded.
  Source anchors: `utils/location_path_finder.py:206-223,394-397` binds each
  graph node's `data` to the full authored location; `main.py:7321-7325` obtains
  the current node, `main.py:6459` refreshes history before the narrator loop,
  and `main.py:8055-8059` sends narrator input; after each result
  `main.py:8567-8569` refreshes it again. The concrete area-file read,
  `currentLocationId` selection, and full current-location system-message
  projection are `core/ai/conversation_utils.py:897-940`. Mira is authored at
  `modules/Capture_Arena/areas/CTR001.json:97-103`.

## Concrete verification

Primary fresh verification reran all three suites in separate processes. Each
runner installed an empty-credential config fixture before `unittest` loaded the
suite, armed the shared `scripts.core_chat_test_safety.arm_process_tripwires()`
before test-module/runtime-owner imports, and called `assert_untouched` after
completion. The capture suite's discovered safety test also calls
`assert_untouched`. Config supplies only the source-confirmed
`MULTIPLAYER_MODE` / `TABLETOP_DEBUG_VERBOSE` settings;
  unknown config reads raise a `BaseException` sentinel. The capture harness no
  longer imports all of `core.combat.combat_manager` or
  `updates.update_character_info`: it compiles the actual complete selected
function bodies plus their AST-discovered literal helper closure into a test
  namespace, while the actual production functions remain the behavior under
  assertion. The update-module fake exports only those extracted pure functions;
  other imports fail closed. Its `find_character_file_fuzzy` reader is the
  actual source function operating on sandbox files. The compressor fixture
  patches `core.ai.combat_compression_engine.create_chat_client` at the exact
  symbol used by `CombatCompressor.__init__`, before constructing the compressor.
  It returns an inert client whose unexpected attribute/request access raises
  `BaseException`; the SDK constructor tripwire remains armed and unchanged.
  Existing compression miss/hit and trace assertions still execute.

Provider-free tests in `scripts.test_capture_drive` exercise the actual fixture
transform on a unique project-local `tmp/` copy, then call the production
`hydrate_missing_live_area_files_from_bu` helper to verify that restoring a
missing live area from the transformed BU preserves peaceful CA02. The tests
also validate the narrator input/history source path, authored Mira record,
party-specific G4 profiles, exact seeded combat roster/encounter IDs, no
startup combat, invalid-combination rejection, no Mira record/media write, and
the independent bounded health counter. The authored BU hash was checked
before and after the fixture test:

`modules/Capture_Arena/areas/CTR001_BU.json`
SHA-256: `4293cc1b65c5e18d36e0cb2830cd4933b6c89bd89bcb8a9927d0e3dfe908f0ed`

Commands and results (separate processes):

| Command | Result |
|---|---:|
| `OPENSPEC_TELEMETRY=0 DO_NOT_TRACK=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=tmp/task-6-1-pycache TMPDIR=tmp .venv/bin/python -m unittest -q scripts.test_capture_drive` | PASS, 55 tests |
| `OPENSPEC_TELEMETRY=0 DO_NOT_TRACK=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=tmp/task-6-1-pycache TMPDIR=tmp .venv/bin/python -c 'from scripts.core_chat_test_safety import arm_process_tripwires, TripwireFailure; tripwires=arm_process_tripwires(); import sys, unittest; from types import ModuleType; config=ModuleType("config"); config.OPENAI_API_KEY=""; config.OPENROUTER_API_KEY=""; config.MULTIPLAYER_MODE=True; config.TABLETOP_DEBUG_VERBOSE=False; config.__path__=[]; config.__getattr__=lambda name: (_ for _ in ()).throw(TripwireFailure("unexpected config attribute: "+name)); sys.modules["config"]=config; suite=unittest.defaultTestLoader.loadTestsFromName("scripts.test_runtime_area_hydration"); result=unittest.TextTestRunner(verbosity=0).run(suite); tripwires.assert_untouched(unittest.TestCase()); raise SystemExit(0 if result.wasSuccessful() else 1)'` | PASS, 14 tests |
| `OPENSPEC_TELEMETRY=0 DO_NOT_TRACK=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=tmp/task-6-1-pycache TMPDIR=tmp .venv/bin/python -c 'from scripts.core_chat_test_safety import arm_process_tripwires, TripwireFailure; tripwires=arm_process_tripwires(); import sys, unittest; from types import ModuleType; config=ModuleType("config"); config.OPENAI_API_KEY=""; config.OPENROUTER_API_KEY=""; config.MULTIPLAYER_MODE=True; config.TABLETOP_DEBUG_VERBOSE=False; config.__path__=[]; config.__getattr__=lambda name: (_ for _ in ()).throw(TripwireFailure("unexpected config attribute: "+name)); sys.modules["config"]=config; suite=unittest.defaultTestLoader.loadTestsFromName("scripts.test_combat_latency_baseline"); result=unittest.TextTestRunner(verbosity=0).run(suite); tripwires.assert_untouched(unittest.TestCase()); raise SystemExit(0 if result.wasSuccessful() else 1)'` | PASS, 24 tests |
| `OPENSPEC_TELEMETRY=0 DO_NOT_TRACK=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=tmp/task-6-1-pycache TMPDIR=tmp .venv/bin/python -m py_compile scripts/capture_drive.py scripts/combat_latency_fixtures.py scripts/seed_combat_capture.py scripts/test_capture_drive.py` | PASS |
| `python3 scripts/check_ascii_compliance.py --summary-only` | PASS, 0 violations |
| `OPENSPEC_TELEMETRY=0 DO_NOT_TRACK=1 openspec validate llm-router-core-migration --strict` | PASS |
| `git diff --check` | PASS |

Primary rerun total: 93 guarded tests (55 capture + 14 hydration + 24 baseline)
across three separate processes. Strict validation, ASCII/whitespace, scoped
diff, and no-ignored-cleanup checks passed. The focused suites are provider-free;
their results do not establish G4 execution or live behavior.

The earlier builder run (`52/14/24`) used local open/network guards only and
is historical, not guarded PASS evidence. The primary's first shared-guarded
attempt was blocked before test execution at the module-scope
`core/combat/combat_manager.py:402` call
`os.makedirs("combat_logs", exist_ok=True)`; the process mkdir guard blocked
that call before any outside write. In a later guarded 24-test attempt, the
compressor fixture reached its imported `create_chat_client` alias before the
fixture-level factory seam was added. The SDK-constructor tripwire blocked
client construction; no HTTP request was observed. The configured credential
was passed as a constructor argument to the mocked constructor, and the then
current `assert_untouched` failure diagnostic exposed mock call arguments. This
incident is recorded without reproducing or inspecting the value/output. It is
a credential-access and failure-output exposure: the owner should rotate the
credential before any live run. No live use, credential value, prior file
effect, cleanup, or restoration is claimed. `assert_untouched` now reports only
tripwire name and count. A synthetic sentinel test verifies the secret-like
argument is absent from diagnostic text while the `BaseException` guard still
fails; it creates no real client and does not reset process tripwire history.
The current separate guarded runs report zero process-tripwire calls for the
capture, hydration, and baseline suites; the one call in the redaction test is
isolated synthetic evidence, not a process guard call.

## Boundaries and remaining work

- No `--prepare` or `--restore` was run; no sandbox under the reserved
  `tmp/combat_capture/` was created, modified, or removed. The transform/hydration
  check used only a unique temporary fixture tree below project `tmp/`.
- No live capture, server, campaign, key, API/provider/SDK, or actual runtime
  reader import requiring credentials was exercised. No root-authored BU file,
  product code, prompts, models, default G3 route, raw 18-key format, or
  standalone latency script was changed.
- The prior builder capture-suite imports happened before shared mkdir guards;
  a root `combat_logs/` mkdir may have been attempted. Whether any prior-run
  filesystem effect occurred is unknown, and possible configuration/credential
  reads from those earlier imports were not investigated. No cleanup,
  restoration, or no-prior-effect claim is made.
- Task 6.2 remains pending: G4 socket/receipt collection and evidence
  projections. Task 6.3 remains pending: four-key offline matrix/negative
  evaluation. Task 6.4 remains primary-owned and pending: fresh live captures.
  Task 6.5 remains pending: final full verification. G4 execution is
  intentionally unavailable until its task-6.2 prerequisites exist.
- Scratch/cache used: `tmp/task-6-1-pycache` and unique temporary fixture trees
  under project `tmp/`; no report artifacts or fixture copies were left outside
  project `tmp/`.

## Attributable follow-up correction (task 6.3)

Primary source review found that the earlier accepted profile sequence described
an initial CA01 narration followed by CA02/CA03/Mira and one return input to
CA01. That sequence did not observe the required return through CA02; the final
input wording was not evidence that the intermediate persisted location was
reached. The task-6.3 correction changes only the fixed G4 profile: startup's
persisted CA01 opening is observed before gameplay, followed by five adjacent
input turns with persisted expected rooms CA02, CA03, CA03 (Mira), CA02, CA01.
P4 actors are Acheron, Acheron, Merisiel, Merisiel, Merisiel; the active-PC
switch is at the Mira turn. Existing 6/8 and 6/9 input/control bounds, 300-second
turn cap, separate health-read bound, source-authored room identities, G3
behavior, and all other 6.1 scope remain unchanged. This correction is recorded
without rewriting the original 6.1 implementation history or relaxing
acceptance. No live run or owner-key inspection/rotation was performed.

## Attributable tooling-import correction (G4 preflight)

After owner-confirmed key rotation and authorization to resume, the primary's
actual `--gate g4 --party 1 --scenario narrator-dialogue-travel --prepare`
command completed. Its stdout began with
`[UpdateCharacterInfo] Creating OpenAI client for chat` before the sandbox-copy
phase. The command's preflight recorded the four protected root hashes in
`tmp/router-rollout/g4/preflight-1792358694080.json`; no server or capture was
started. The output is evidence of runtime/SDK construction during a tooling
import path that did not require that runtime dependency, not evidence of an
HTTP request or a newly exposed key. No credential value was observed or
exposed. Constructor arguments and logger destinations were not observed, so
the logger-write outcome is uncertain. The prior rotation confirmation remains
valid; this record does not claim a new key leak or reverse prior rotation.

Source tracing identified eager module-scope imports in
`scripts/combat_latency_fixtures.py`: the legacy multi-PC manager import reaches
`utils.multi_pc_dm_note` and `updates.update_character_info`, and the compressor
import reaches `core.ai.combat_compression_engine` (whose actual factory seam
belongs inside provider-free instrumentation). Tool/profile imports therefore
pulled runtime owners despite no CLI need. The follow-up moves those production
imports into `_make_mp_manager()` and
`_exercise_compression_instrumentation()` only. G3/raw-18 seed and latency
contracts are unchanged. The fresh guarded import test confirms seeder, driver,
evidence, profile and seed-payload builder imports/help leave these runtime
owners unimported and do not invoke the guarded constructor/network/outside-write
surfaces. This correction is tooling-only and does not establish live readiness,
or G4 PASS; task 6.4 remains primary-owned and task 6.5 remains pending.

## Attributable focused-retry correction (actual CLI import path)

The primary reported that a subsequent actual root CLI `--prepare` again emitted
`[UpdateCharacterInfo] Creating OpenAI client for chat` as its first stdout
line, before the `[COPY]` status output. No server or capture was started.
This supersedes the previous tooling-import verification wording above: those
62 guarded tests used an EMPTY config fixture and did not execute the actual
`seed_combat_capture.py` `__main__` entrypoint or `_seed_party` path. A passing
result there did not establish actual CLI import/seed safety. This chronology
does not establish HTTP activity or lack of it, and does not establish a newly
exposed key; no credential value was observed or exposed.

Read-only source tracing found two seeder-side imports not covered by the prior
test. Importing `utils.module_path_manager` initializes `utils.enhanced_logger`'s
global `GameLogger` and its root file handlers. During seeding,
`_seed_party()` called `ModulePathManager.get_character_unified_path()`; that
reaches `format_filename()`, imports `updates.update_character_info` to obtain
`normalize_character_name`, and imports that owner's module-scope
`client = create_chat_client()`. The caller printed the observed
`UpdateCharacterInfo` message. The correction removes the module-scope manager
import and uses a filename projection limited to the capture tool's fixed PC and
Blairen roster; injected `path_manager` behavior remains available to existing
tests. It does not change runtime path rules or general character mechanics.

The new fresh-process regression uses `runpy.run_path(..., run_name="__main__")`
for the actual seeder, driver, and evidence `--help` entrypoints, plus both
`combat_latency_fixtures` namespaces and actual pure profile/seed-builder paths.
Each child has a NONEMPTY dummy sentinel config, both multiplayer/debug flag
combinations, a private-root-`config.py` read denial, and fatal SDK,
network, root-file-logger, and outside-write guards armed before application
imports. It asserts update/NPC/compressor owners remain absent and all guards
remain untouched. This proves only the tested import/help and pure-builder
boundaries; no `--prepare` rerun, restore, server, or live capture was run by
the builder. Prior actual preflight chronology remains intact and does not
become a live verdict.
