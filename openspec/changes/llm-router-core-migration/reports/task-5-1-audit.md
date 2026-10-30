# Task 5.1 - Core Chat Inventory and Parity Audit

Status: primary-reviewed task 5.1 software/source evidence PASS. The focused
audit covers all 15/15 inventoried semantic operations; 19/25 change tasks are
checked. This is not a repository-wide zero-SDK claim and does not claim live
G4, full-owner-loop, full 705-test baseline, or full-goal completion.

## Exact 15-operation re-inventory

The fresh AST inventory checks the same 15 semantic owners and task mappings as
`reports/core-chat-inventory.md`. It observes 17 facade call expressions and 18
request edges: the bootstrap resume owner invokes the shared `_startup_provider_call`
helper at two source edges, while that helper contains one facade request. The
25 pre-migration primary/fallback/helper SDK variants are collapsed to those
facade-owned routes; no caller retains an SDK call, direct `OpenAI` constructor,
or `create_chat_client` call inside an inventoried semantic owner/helper.

| Semantic operation | Source owner / route expression | Task | Current transport variant evidence |
|---|---|---|---|
| 1 | `main.py::generate_arrival_narration` | `dm_main` | One facade call; formerly one direct SDK request. Dormant helper retained. |
| 2 | `main.py::generate_seamless_transition_narration` | `dm_main` | One facade call; formerly one direct SDK request. Dormant helper retained. |
| 3 | `main.py::validate_ai_response` | `dm_validation` | One facade call inside the unchanged three-attempt nonterminal validation loop. |
| 4 | `main.py::generate_module_summary` | `summaries` | One facade call; former preferred/fallback transports now router-owned. |
| 5 | `main.py::get_ai_response` | `dm_main` | One facade call; former four raw-recovery helper edges collapsed; optional empty retry remains limit 2, three responses/provider, one transition, six SDK invocations maximum. |
| 6 | `core/combat/bootstrap.py::_run_resume_narrative` | `combat_main` | Two owner call edges use `_startup_provider_call`; both former timeout-omitted/explicit-timeout helper variants now share its one facade call. |
| 7 | `core/combat/bootstrap.py::_run_initial_scene_generation` | `combat_main` | One facade call in the existing three-attempt nonterminal stage loop. |
| 8 | `core/combat/turn.py::run_combat_provider_retry_stage` | `combat_main` | Three facade call expressions retain the three GPT-family/ordinary parameter branches and existing high-reasoning retry condition. |
| 9 | `core/combat/validation.py::validate_combat_response` | `combat_validation` | One facade call in the existing five-attempt nonterminal validation loop. |
| 10 | `core/combat/combat_manager.py::summarize_dialogue` | `combat_summary` | One facade call; former preferred/fallback transports now router-owned. |
| 11 | `core/combat/combat_manager.py::generate_combat_round_summary` | `compression` | One facade call; core-owned summary remains in scope, distinct from compression engine transport. |
| 12 | `core/combat/initiative_tracker_ai.py::generate_live_initiative_tracker` | `combat_main` | One facade call; direct SDK constructor and request removed from the semantic owner. |
| 13 | `core/ai/action_handler.py::_ai_analyze_starting_location` | `dm_validation` | One facade call; former preferred/fallback transports now router-owned. |
| 14 | `core/ai/action_handler.py::process_action` transition narration branch | `dm_main` | One facade call in the transition narration branch; unrelated process-action behavior is not reworked. |
| 15 | `core/ai/action_handler.py::get_ai_npc_movement_decision` | `updates` | One facade call; former preferred/fallback transports now router-owned. |

The source contract asserts 15 named operations and the exact task set
(`dm_main`, `dm_validation`, `summaries`, `combat_main`, `combat_validation`,
`combat_summary`, `compression`, `updates`). For every route it verifies the
literal task, `json_output=False`, absence of caller model/timeout kwargs, and
zero caller SDK call/constructor/factory construction. The bootstrap resume
helper invocation edges and helper body are checked independently. The
request-contract suite still executes all 18 current routed request edges with
fake router/SDK seams and retains the pre-migration message-assembly AST
goldens and fixed prompt-asset hashes; no literal golden or fixture proof was
rewritten.

## Caller parity and negative contracts retained

The audit only repointed stale SDK-source expectations to the actual facade
request seam and fake factory/SDK seams. Existing coverage remains active for:

- Prompt/message bytes and role/order: all 15 source assembly digests and
  prompt assets, plus request event message digests.
- Parser/result contracts: narration text and JSON extraction, validation
  tuple/attempt behavior, summary formatting/parsing, marker-based initiative
  `str | None`, starting-location tuple, transition action boundary, and NPC
  movement decision/`None` shape.
- Callback/tracking behavior: observer messages/labels/order, once-per-response
  receipt accounting, trace/API logger/tracker ordering, and usage gates.
- Retry behavior: main empty-response 2-retry/provider bound, shared fallback
  and six-invocation cap, validator 3/5 nonterminal attempt limits, startup
  initial-scene attempts, and combat retry prompt/tier/attempt semantics.
- Terminal outcomes: quota/refusal/content-filter short-circuit coverage,
  owner fallback/retry bypass, and no post-boundary action/state admission.
- Source-level exclusions: no nested raw-SDK recovery around facade calls;
  no dormant transition-helper deletion; no direct SDK usage in an inventoried
  semantic owner or its request helper.

The test assertion in
`scripts.test_authoritative_transition_inventory_runtime_reset` now checks the
AST expression shape and evaluates its precedence cases: nested
`response_data.error_message` wins, `result.error_message` is the fallback, and
the exact existing default string remains `Unknown error in action processing`.
This is formatting-independent and does not change `main.py`.

## Direct SDK and exclusion boundary

An AST sweep of `main.py`, `core/`, `utils/`, `updates/`, and `tools/` found no
direct SDK request or construction in any of the 15 semantic owners (including
`_startup_provider_call`). This is deliberately **not** a repository-wide
zero-SDK claim. The direct SDK/factory sites below remain outside this task:

- Router/recovery/factory infrastructure: `utils/llm_router.py::LLMRouter.call`
  is the intended SDK transport owner; `utils/provider_response_recovery.py::request_chat_completion_with_recovery`
  remains a raw-SDK legacy helper but has no call edge from migrated owners;
  `utils/ai_client_factory.py::{create_chat_client, create_image_client, create_tts_client}`
  remain factory responsibilities. Module-level client creation in `main.py`
  and `core/combat/combat_manager.py` is not an inventoried semantic request.
- Excluded compression/action-prediction: `core/ai/combat_compression_engine.py::compress`,
  `core/ai/incremental_compression.py::compress_messages`,
  `utils/compression/location_compressor.py::compress_location`,
  `utils/compression/ai_narrative_compressor_agentic.py::compress_with_ai`, and
  `utils/action_predictor.py::predict_actions_required`. The included core round
  summary remains `generate_combat_round_summary`, not these engines.
- Excluded diary/story/manager/summary and transition utilities:
  `core/memory/players_diary.py::{_generate_markdown_from_prompt}`;
  `core/memory/session_diary.py::{_generate_rebuild_chapter_summary,_generate_checkpoint_summary}`;
  `core/memory/story_so_far_compiler.py::_generate_story_text_with_llm`;
  `core/ai/{cumulative_summary,transition_validator,adv_summary}.py` AI owners;
  `core/managers/{storage_processor,level_up_manager,campaign_manager}.py` AI
  owners; plus `utils/{npc_reconciler,npc_name_canonicalizer,reconcile_location_state,
  quest_player_formatter,startup_wizard,character_creation_audit,spatial_contract}.py`
  and `updates/{plot_update,update_encounter,update_character_effects,update_character_info}.py`.
- Excluded generators/toolkit: direct call owners in
  `core/generators/{location_generator,module_stitcher,module_builder,module_generator,
  npc_builder,monster_builder,plot_generator,area_generator,location_summarizer}.py`,
  `core/toolkit/{monster_generator,npc_generator}.py`, and
  `utils/{toolkit_llm_final_reconciliation,toolkit_adaptation_author,
  toolkit_adaptation_auditor,toolkit_homebrew_normalizer,bestiary_updater,
  prompt_sanitizer}.py` remain outside this inventory.
- Media, Jev decision, Titan runtime, optional resolver/mode-flag/runtime
  surfaces, and other phase-5/6 utilities remain explicit exclusions from the
  proposal/design. This task does not migrate, execute, or claim a global audit
  of those systems. No unrelated compression, generator, media, Jev, Titan, or
  mode-flag code was edited.

The retained dormant helper `utils/provider_response_recovery.py` and the two
dormant main narration helpers are source-asserted as retained; only the main
helpers' semantic calls are routed. No direct SDK constructor/call was removed
from an excluded operation to make the inventory appear globally clean.

## Guarded follower suite and historical caveat

`scripts.test_scene_follower_transition_sync` now arms the shared fatal
constructor/network/BaseException/outside-write tripwires before production
imports, pins `TMPDIR` to repository `tmp/`, and has a discovered test assert
that the tripwires remain untouched. Read-only source inspection found its lazy
`scene_follower_state.normalize_scene_follower_entity_id` import reaches
`updates.update_character_info`, whose module body constructs a client. The
test now supplies only a temporary inert `config` fixture and a fail-closed
factory client before that import; the fake client's request method raises a
`BaseException` sentinel, and the suite asserts no request was attempted. The
follower synchronization, storage, and DM Note behavior under assertion remain
real. Temporary fixtures use `TMPDIR=tmp`; no historical runtime artifact or
key was inspected or cleaned.

Follow-up audit corrected the safety assertion lifecycle: the earlier
`TestFollowerImportSafety` class had only `tearDownClass`, so unittest did not
discover it as a test case, and its class-level `TestCase` assertion calls were
not valid bound assertions. A real test method now asserts the fake request
list is empty and calls `_TRIPWIRES.assert_untouched(self)`. Both config and
factory patchers register `unittest.addModuleCleanup` immediately after start;
restoration therefore does not depend on test-class order or successful
assertions. The existing 13 behavior tests remain unchanged; this suite now
contains 14 discovered tests.

The initial guarded rerun attempt before the inert dependency seam was in place
failed closed when the OpenAI constructor tripwire fired; it did not pass and
is not counted. After the narrow fake/config seam was installed, the original
13 behavior tests passed. The corrected 14-test run additionally executes the
real import-safety test and confirms all tripwires were untouched. The earlier
unguarded run and its uncertainty are preserved unchanged in
`reports/task-4-2-implementation.md`; this safe rerun does not retroactively
reclassify that run or investigate its possible credential/log side effects.
The follow-up software safety issue is closed by the corrected guarded suite,
but uncertainty about the earlier unsafe 13-test run remains; no restorative
or cleanup claim is made.

## Verification

All 20 commands ran in separate processes with
`OPENSPEC_TELEMETRY=0 DO_NOT_TRACK=1 PYTHONDONTWRITEBYTECODE=1 TMPDIR=tmp`
and `PYTHONPYCACHEPREFIX=tmp/task-5-1-pycache`. Each focused suite completed;
the total is 326 passing test executions, not the historical 705-test combat
baseline.

| Focused suite | Result |
|---|---:|
| `scripts.test_npc_movement_router_migration` | 6 passed |
| `scripts.test_transition_router_migration` | 5 passed |
| `scripts.test_starting_location_router_migration` | 7 passed |
| `scripts.test_initiative_tracker_router_migration` | 7 passed |
| `scripts.test_combat_summary_router_migration` | 6 passed |
| `scripts.test_combat_bootstrap` | 29 passed |
| `scripts.test_combat_retry_stage` | 15 passed |
| `scripts.test_combat_validation_stage` | 17 passed |
| `scripts.test_combat_validation_routing` | 11 passed |
| `scripts.test_core_chat_inventory_contract` | 14 passed |
| `scripts.test_core_chat_request_contracts` | 17 passed |
| `scripts.test_llm_runtime_receipt_adapter` | 15 passed |
| `scripts.test_llm_runtime_launch_reset` | 3 passed |
| `scripts/test_llm_router.py` | 88 passed |
| `scripts.test_benchmark_model_profiles` | 6 passed |
| `scripts.test_gpt54_chat_params_contract` | 10 passed |
| `scripts.test_gpt54_mini_chat_params_shim` | 6 passed |
| `scripts.test_gpt56_luna_direct_openai_contract` | 41 passed |
| `scripts.test_authoritative_transition_inventory_runtime_reset` | 9 passed |
| `scripts.test_scene_follower_transition_sync` | 14 passed |
| **Total** | **326 passed across 20 processes** |

Additional checks:

- Scoped Python compilation of the changed test sources passed with the cache
  prefix under `tmp/task-5-1-pycache`.
- `python3 scripts/check_ascii_compliance.py --summary-only` passed with zero
  violations.
- `OPENSPEC_TELEMETRY=0 DO_NOT_TRACK=1 openspec validate llm-router-core-migration --strict` passed.
- `git diff --check` passed, and a separate trailing-whitespace check covered
  the new untracked report/test sources.
- Current prompt goldens, report history, and unrelated worktree changes were
  not regenerated or cleaned. No facade baseline rerun outside the five listed
  facade suites, full 705-test baseline, full owner loop, `sys.settrace`, live
  provider, server, or campaign was run.

Primary review: PASS for the scoped software audit, including the fresh 15-route
source inventory, absence of an unscoped global-zero claim, unchanged goldens,
precise AST error-precedence assertions, guarded follower config/factory
fixture and denied-request seam, discovered 14th safety test, and guaranteed
module cleanups. Follow-up software closure does not erase uncertainty from the
earlier unsafe 13-test run. G4 and final 705-test verification remain pending;
there is no live or full-goal completion claim.

Scratch used: `tmp/task-5-1-pycache`; suite fixtures from the follower test
landed under repository `tmp/`. No live API, server, campaign, secret, or
runtime artifact investigation was performed. Task 5.1 is checked for planner
verification only.
