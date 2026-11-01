# Task 1.1 - Guarded Baseline Contracts

Status: implementation evidence for primary verification; task checkbox remains
unchecked. This records the legacy baseline only. Current direct, fallback, and
helper-mediated transports are expected at this stage; no migration or live G4
claim is made.

## Coverage added

- `scripts/test_core_chat_inventory_contract.py` reads the current owner AST,
  asserts all 15 operation names, then derives observed task IDs from the
  task-bearing helper calls nested under actual request-boundary expressions.
  The direct initiative tracker is explicitly different: its current SDK
  request has `model=DM_MAIN_MODEL` and no task-bearing helper; `combat_main` is
  the planned migration mapping, not a current task field. The inventory also
  checks both timeout-omitted/explicit-timeout startup helper forms, both resume
  edges, the three turn request families, and the distinct primary/fallback
  action-handler client edges.
- `scripts/test_core_chat_request_contracts.py` executes 25 current-source
  provider-boundary expressions spanning all 15 operations and all documented
  call variants, with fake clients and explicit fake parameter dependencies.
  The actual `request_chat_completion_with_recovery` implementation executes
  the four main narrator edges; the actual `_startup_provider_call` AST helper
  executes both resume variants. It fails on any unresolved name instead of
  allowing the selected expression to fall into a generic owner fallback.
- Producer-level execution uses current selected AST functions/blocks, not
  copied application implementations: both dormant main helpers, starting
  location analysis, NPC movement, and the finite location-transition branch
  from `process_action` run with fake dependencies. These check parsed returns,
  actual fake SDK messages/task params, response tracking/API callback order,
  fallback selection, transition history append/save order, and the dormant
  helper no-call short-circuit. Other main/action/summary/initiative paths are
  executed at their current provider-boundary AST expression (including actual
  inline message-list construction where present); their caller-level return
  behavior is checked through selected actual source parser/return expressions
  (main narrator content, validator tuple, summary formatting, combat summary
  parse/return, initiative marker result), rather than by invoking top-level
  owner loops.
- Request-contract execution supplies test messages/prompts only to the
  transport-boundary probes. To prevent those fixtures from masking source
  edits, immutable AST SHA-256 goldens now cover prompt/message construction
  statements and the `messages` expression at each operation's request edge
  for all 15 owners. The selected AST deliberately excludes SDK/observer
  transport kwargs. Bootstrap initial-scene, initiative tracker, and upstream
  `core/combat/prompts.py` context/prompt builder helpers are included
  explicitly. Fixed SHA-256 goldens also cover the combat startup, combat
  validation, and initiative tracker prompt assets. Final digest correction:
  legacy code may have several transport branches carrying the same canonical
  message expression (notably the four `get_ai_response()` recovery edges).
  The previous digest retained those identical expressions, so consolidating
  transport branches during migration would change the golden despite identical
  prompt construction. The canonical digest now recognizes `llm.call` and
  `dependencies.llm_call`, deduplicates only identical canonical message ASTs
  in first-seen order, and retains distinct expressions and all assembly AST.
  AST-only tests prove transport replacement/duplicate collapse invariance and
  sensitivity to message literal, role, or assembly changes. Production source
  and fixtures were unchanged for this correction; constants below were
  regenerated once under the corrected algorithm.
- SHA-256 message fixtures in the tests freeze byte-sensitive current messages
  from the executed main dormant helpers, action starting-location and movement
  functions, transition branch, plus the inline current module-summary and
  combat-round-summary request lists. The primary/fallback variants use the
  same captured message digest where current source shares the message object.
- Ordinary `main.py::get_ai_response` is asserted as four calls to
  `request_chat_completion_with_recovery` across the two model-family branches,
  with each using the `dm_main` parameter mapping. The test also checks the
  source-defined empty retry limit of two. The existing
  `scripts.test_provider_empty_response_retry` suite executes the actual
  recovery helper against scripted fake clients and covers its response,
  refusal/filter, and retry behavior. No duplicate recovery implementation was
  introduced.
- `scripts/core_chat_test_safety.py` arms a `BaseException` fatal sentinel for
  OpenAI construction, requests/httpx clients and request/send methods, urllib,
  HTTP(S), and sockets before the selected focused suites import owners. Its
  mutation guards cover writes, mkdir/makedirs, unlink/remove/rmdir,
  rename/replace (both paths), link/symlink, chmod/chown/utime/truncate,
  `shutil.rmtree`, copy/copy2/copyfile/copytree/copymode/copystat, and move;
  only project-local `tmp/` is writable. File mutations supplied with
  `dir_fd`/`src_dir_fd`/`dst_dir_fd` are rejected fail-closed; hardlink source
  validation resolves the final symlink target. Self-tests use nonexistent
  outside paths, a read-only outside directory descriptor, a temporary `tmp/`
  symlink escaping to a nonexistent target, both directions of mixed
  inside/outside renames/links, and a hardlink symlink escape, then assert no
  outside target was created. The
  logger file sink is replaced with `NullHandler` before owner imports.
- Facade and combat contracts execute existing router/factory and named combat
  stage dependency seams. In particular the combat suites retain prompt,
  output/return, trace/usage, retry, callback, and handoff assertions; the
  extraction boundary is used instead of running top-level main/game/combat
  loops.

## Operation and variant inventory

| Owner | Operations | Current source variants asserted |
|---|---:|---|
| `main.py` | 5 | arrival 1 direct SDK; seamless transition 1 direct SDK; validator 1 direct SDK; summary 2 direct (preferred/fallback); ordinary narrator 4 helper calls across two model-family branches |
| `core/combat/bootstrap.py` | 2 | resume calls helper twice; helper contains timeout-omitted and explicit-timeout SDK variants; initial-scene 1 direct SDK call |
| `core/combat/turn.py` | 1 | 3 direct SDK branches: high-reasoning GPT-family retry, ordinary GPT-family, and other-family explicit timeout |
| `core/combat/validation.py` | 1 | 1 direct SDK call |
| `core/combat/combat_manager.py` | 2 | dialogue summary 1 direct call; round summary 1 direct call |
| `core/combat/initiative_tracker_ai.py` | 1 | direct `OpenAI(...)` construction and 1 SDK call |
| `core/ai/action_handler.py` | 3 | each operation has preferred and fallback direct SDK calls, with an explicit fallback-client constructor |

The 25 expressions were actually evaluated: 9 main (including four helper
requests), 3 bootstrap, 3 combat-turn, 1 combat-validation, 2 combat summaries,
1 initiative tracker, and 6 action-handler variants. Thus the matrix is not a
call-count-only inventory; task fields/parameters are observed by the fake
provider seam, except the expressly documented direct initiative legacy model.

The distinction between planned task mapping and observed legacy source is
preserved: the initiative tracker is planned for `combat_main`, but its current
direct SDK call has only `DM_MAIN_MODEL` and no task/helper field. The other 14
operations expose the documented legacy task through their current parameter
helper calls. The AST and asset expected values below are immutable literals in
`scripts/test_core_chat_request_contracts.py`; tests do not derive expected
values from the live source.

| Owner operation | Prompt/message assembly AST SHA-256 |
|---|---|
| `main.py::generate_arrival_narration` | `9650ca4b181021a39070328def7e2d331e520b0fa465bca6908d38dd2f89fa7e` |
| `main.py::generate_seamless_transition_narration` | `fc66061146a6be70d8c1e86d36254dd8417d50f5d87035c7e046e190598a459f` |
| `main.py::validate_ai_response` | `0cec84235d2b4d98572658a58a3fc3b46fa5ca7e1edfe7a08af81779d2a20549` |
| `main.py::generate_module_summary` | `9ef25df209c313f762d9a4376f26f3af16f1f1287dbc35fd3a1f34a04cac69d4` |
| `main.py::get_ai_response` | `bf523ca98a02930bd5f029e8457d1759f77579020f4a20f5df25b499997ea0d8` |
| `core/combat/bootstrap.py::_run_resume_narrative` | `d9099b0213f0e48979a1b3e7969bf6e4fad18851ce17b3f1cbcd38b99102a635` |
| `core/combat/bootstrap.py::_run_initial_scene_generation` + `_build_initial_scene_prompt` | `0ba65f88cd13a2682dc86228ebe5c6f9db0ef31634f8eb22ecee3759c570780d` |
| `core/combat/turn.py::run_combat_provider_retry_stage` + `core/combat/prompts.py::assemble_combat_context` / `assemble_combat_prompt` | `5a1d176134b13274b99ef7289c0802be7cf31a3bbf83b6da939e8a783a7a4547` |
| `core/combat/validation.py::validate_combat_response` | `89cae998836feccb96a14a8adb1e3bb40bcd0d12204f536ef28fd9c611b9ee48` |
| `core/combat/combat_manager.py::summarize_dialogue` | `17ce65e820abfc829d133d5ae90a0db3ef9fcb61242378973c020f93e27994b4` |
| `core/combat/combat_manager.py::generate_combat_round_summary` | `7decbcf854b892139d6060d3b53f9c1f717df7f4b3682089c4972c721b521f4a` |
| `core/combat/initiative_tracker_ai.py::generate_live_initiative_tracker` + `create_initiative_prompt` | `f68aef2f99636ddcf64292d4b13b07ee9b51a75b642a1b2926179a497602a9a6` |
| `core/ai/action_handler.py::_ai_analyze_starting_location` | `d35bf17e581c9f9a4ae48b95fc7b1f0e86ea2943c84e4583d6aeac4fad4c24e8` |
| `core/ai/action_handler.py::process_action` transition block | `dcf6ab5ab021b73b44d0f1d77812083140232080dbbce51815d6412a7acf3dec` |
| `core/ai/action_handler.py::get_ai_npc_movement_decision` | `cdd81c5e06e85c05fb7e9e8e5d98311a3977741bb6da540b1c292c75412d6a3a` |

| Referenced prompt asset | SHA-256 |
|---|---|
| `prompts/combat/combat_sim_prompt.txt` | `148d4211474c9189ec54b43ee5fa39eb505a3d1a8d284d7d42581e25ccc7e54b` |
| `prompts/combat/combat_sim_prompt_multipc_compressed.txt` | `b31ad6960e340d8b05eb76849f983533044f503eb88cf82714beb6526412647e` |
| `prompts/initiative_tracker_compressed.txt` | `de4692d2cbaa6d9dbe0cb252a1f5554582888ac0cbfd13dbca3fcec3f21bad1d` |
| `prompts/combat/combat_validation_prompt.txt` | `ca12e479668a623b124efa7aa1777554e2ef25b169bf34240e6fc797f7eb486a` |
| `prompts/combat/combat_validation_prompt_compressed.txt` | `18ac9069aea90e5d5225e4f2c40420c051d19ee378387e8a32f2ebe99e9c2dda` |
| `prompts/combat/combat_validation_prompt_multipc_compressed.txt` | `7f905bd2902bc74780eb4f24705d80645d4c5d229f57fe6dda8d9c4f13f84812` |

| Semantic operation | Verification source actually executed | Remaining source-only evidence |
|---|---|---|
| Arrival narration | Full selected `generate_arrival_narration` AST function | None for request, parse, return, and API-log order in this seam |
| Seamless transition narration | Full selected function; includes no-call return and provider path | None for covered inputs |
| Main validation | Actual request-call expression, current `dm_validation` params, and actual passing tuple-return expression | Outer 3-attempt validation state is source checked, not run as main owner |
| Module summary | Both actual preferred/fallback call expressions; actual content-format and return expressions | Full persistence path not executed |
| Ordinary narrator (`get_ai_response`) | Four actual helper-call expressions; real empty-response recovery helper, branch/model arguments, content parse, and return expression | Full narrator preparation/response application loop not executed; fallback-client creation is an executed fake edge |
| Bootstrap resume | Actual `_startup_provider_call` function body and both resume edges; existing bootstrap fake suite executes the named startup seam | Full resume history/callback owner path is covered by existing suite, not re-run as a live owner |
| Initial scene | Actual request-call expression; existing bootstrap suite executes the real initial-scene dependency seam and retry contract | None beyond no full loop |
| Combat retry stage | All three request expressions; existing combat retry suite executes the real stage seam and retry/trace/usage handoff | None beyond owner-loop exclusion |
| Combat validation | Request expression; existing validation stage suite executes the actual validation owner seam and attempt/result contract | None beyond owner-loop exclusion |
| Dialogue summary | Actual provider request expression, task params, and JSON narration parser block | Summary persistence/final return path not executed |
| Round summary | Actual inline request, task params, and JSON parse/return expressions | Outer failure/persistence flow not executed |
| Initiative tracker | Actual SDK request, direct legacy model/no task field, and actual marker/return expressions | Debug export and full function orchestration not executed |
| Starting-location analysis | Full selected AST function, including preferred and fallback fake transports, parser tuple, tracking | None for selected input/result/fallback cases |
| Transition narration | Actual finite `process_action` transition `try` block, including primary/fallback, narration return, history append and save ordering | Rest of `process_action` intentionally not executed |
| NPC movement decision | Full selected AST function, including primary/fallback, JSON parse, decision return, tracking | None for selected input/result/fallback cases |

The ordinary narrator's SDK call is intentionally not counted as a literal
`.create()` inside `get_ai_response`: it is hidden behind
`request_chat_completion_with_recovery`. That helper's real source is included
in the AST assertion and its behavior is exercised by the existing fake-client
suite. This is a fresh current-source baseline, not a claim that the legacy
transports have already been removed.

## Verification evidence

Primary review: **SOFTWARE PASS** for the fatal SDK/client/network/BaseException/outside-write guards and the transport-independent literal prompt-baseline algorithm. Fresh focused verification passed 249 tests in 12 separate processes, with no ignored cleanup errors. This is not a rerun of the historical 705-test baseline and is not a G4/live PASS.

Each listed command ran in its own process with `PYTHONDONTWRITEBYTECODE=1`
and `TMPDIR=tmp`; outputs are retained under project-local `tmp/` for this
verification pass.

| Process | Result |
|---|---:|
| `scripts.test_core_chat_inventory_contract` | 9 passed |
| `scripts.test_core_chat_request_contracts` | 11 passed |
| `scripts.test_llm_router` | 68 passed |
| `scripts.test_benchmark_model_profiles` | 6 passed |
| `scripts.test_gpt54_chat_params_contract` | 10 passed |
| `scripts.test_gpt54_mini_chat_params_shim` | 6 passed |
| `scripts.test_gpt56_luna_direct_openai_contract` | 41 passed |
| `scripts.test_provider_empty_response_retry` | 37 passed |
| `scripts.test_combat_bootstrap` | 24 passed |
| `scripts.test_combat_retry_stage` | 11 passed |
| `scripts.test_combat_validation_stage` | 15 passed |
| `scripts.test_combat_validation_routing` | 11 passed |
| **Total** | **249 passed in 12 processes** |

The two new core-chat modules total 20 passing tests. The five facade suites
total 131 passing tests (68 + 6 + 10 + 6 + 41). The
705-test combat/decomposition result is retained as historical evidence in
`openspec/changes/combat-manager-decomposition/reports/task-5-4-final-verification.md`;
it was not rerun as part of this focused task. The focused current combat
subset above is 61 tests. No `main.main()`, `main_game_loop()`,
`run_combat_simulation()`, full owner loop, or `sys.settrace` was used.

Additional checks passed:

- `PYTHONPYCACHEPREFIX=tmp/core-chat-task-1-1-pycache .venv/bin/python -m py_compile` on the changed Python test/support modules.
- `python3 scripts/check_ascii_compliance.py --summary-only` - 1,138 files scanned, zero violations.
- `git diff --check` - passed.
- `OPENSPEC_TELEMETRY=0 DO_NOT_TRACK=1 openspec validate llm-router-core-migration --strict` - valid.

## Limitations

This task freezes the current source baseline before production migration.
Selected request expressions and source-AST prompt assembly goldens cover all
15 producers, while full function/block
execution is limited to the named small owners and the extracted transition
block; no full `main.py`, `process_action`, or combat loop is run. The historical
705-test report was not rerun, and this provider-free evidence is not a live G4
result.

## Post-baseline guard compatibility correction

The task 1.1 verification above is retained as historically verified; its
baseline result and scope are not being revised. A later task 1.6 verification
exposed a legitimate `TemporaryDirectory` cleanup failure in the shared
process-wide guard: fd-relative `os.unlink(name, dir_fd=owned_tmp_fd)` had been
rejected unconditionally. The guard correction records live `os.open` path
provenance (including read-only directory descriptors), validates the current
descriptor identity, and resolves mutation paths through known directory FDs.
It permits only resolved `tmp/` targets and keeps unknown/outside descriptors,
mixed-boundary rename/link calls, symlink escapes, and hardlink-source symlink
escapes denied. This is an attributable test-guard compatibility correction,
not a relaxation of outside-write protection. Task 1.6 remains unchecked for
planner verification; the original task 1.1 test result remains historical
evidence rather than a rerun claim.
