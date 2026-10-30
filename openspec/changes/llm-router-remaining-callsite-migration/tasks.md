# Tasks

## 1. Core Generator Batches

- [x] 1.1 Migrate `core/generators/area_generator.py`, `location_generator.py`, and `plot_generator.py` operations listed in `design.md`; preserve message construction and parsing, add fake-facade contract cases to `scripts/test_llm_router_remaining_callsite_contracts.py`, and verify with `.venv/bin/python scripts/test_llm_router_remaining_callsite_contracts.py`.
  Evidence (primary, 2026-10-26): area/location/plot -> llm.call; shared contract created. Tier: sonnet.
- [x] 1.2 Migrate `core/generators/module_builder.py` and `module_generator.py` operations listed in `design.md`; retain injected/model-resolution behavior only where it is not a provider transport seam, add focused provider-free cases, and verify the shared contract test plus `.venv/bin/python scripts/test_module_validation_cli.py`.
  Evidence (primary, 2026-10-26): module_builder/module_generator; module_validation_cli 12 OK. Tier: haiku (+1 retry).
- [x] 1.3 Migrate `core/generators/module_stitcher.py` and `location_summarizer.py`; preserve safety-failure and narration fallback behavior, add focused provider-free cases, and verify the shared contract test.
  Evidence (primary, 2026-10-26): module_stitcher/location_summarizer; fixed __init__ NameError on retry. Tier: haiku (+2 retries).
- [x] 1.4 Migrate `core/generators/monster_builder.py` and `npc_builder.py`; preserve generated output and existing failure behavior, add focused provider-free cases, and verify the shared contract test plus `.venv/bin/python scripts/test_monster_builder_output_directory.py`.
  Evidence (primary, 2026-10-26): monster/npc builder; test_monster_builder_output_directory 8 OK (mock retargeted); stale generator mocks in test_accurate_ingest_generator_source_locks (19) and test_toolkit_adaptation_builder_context (7) retargeted. Tier: haiku; mock retarget haiku->sonnet.

## 2. Core AI And Compression Batches

- [x] 2.1 Migrate `core/ai/adv_summary.py` and `cumulative_summary.py`; retain summary parsing, fallback, and persistence contracts, add provider-free request/return tests, and verify the shared contract test plus `.venv/bin/python scripts/test_adv_summary_location_name_fallback.py`.
  Evidence (primary, 2026-10-26): adv_summary/cumulative_summary; usage observer only (added trace_site removed); fallback test 2 OK. Tier: haiku (+2 retries).
- [x] 2.2 Migrate `core/ai/combat_compression_engine.py`, `incremental_compression.py`, and `transition_validator.py`; preserve bounded retries and transition fail-open behavior, add focused request/attempt tests, and verify the shared contract test plus `.venv/bin/python scripts/test_validation_compression_routing.py` and `.venv/bin/python scripts/test_transition_time_failopen.py`.
  Evidence (primary, 2026-10-26): compression/incremental/transition; capture_evidence/combat_latency_report accept router-shaped combat_compression while legacy bundles stay identical; transition fail-open 8 OK, compression routing 5 OK; test_combat_compression_params restored to 6 tests at the router boundary. Tier: sonnet.

## 3. Manager Batch

- [x] 3.1 Migrate `core/managers/campaign_manager.py`, `level_up_manager.py`, and `storage_processor.py`; preserve summary, validation, storage, and failure contracts, add provider-free owner tests, and verify the shared contract test plus `.venv/bin/python scripts/test_level_up_xp_invariants.py` and `.venv/bin/python scripts/test_levelup_json_web_output.py`.
  Evidence (primary, 2026-10-26): campaign export branch previously referenced nonexistent DM_SUMMARY_MODEL (always fell back) and now routes via `summaries` with deterministic fallback preserved (intentional behavior change); level_up_xp 6 OK, levelup_json 13 OK. Tier: haiku.

## 4. Memory And Diary Batch

- [x] 4.1 Migrate `core/memory/players_diary.py`, `session_diary.py`, and `story_so_far_compiler.py`; preserve branch ordering, output formats, retry/fallback behavior, and persistence, add provider-free branch and prompt-parity cases, and verify the shared contract test plus `.venv/bin/python scripts/test_players_diary_append_markdown.py`, `.venv/bin/python scripts/test_session_diary_rebuild.py`, and `.venv/bin/python scripts/test_story_so_far_pdf_mvp.py`.
  Evidence (primary, 2026-10-26): diaries/story compiler; three diary/PDF tests OK. Tier: haiku.

## 5. Validation Batch

- [x] 5.1 Migrate active operations in `core/validation/character_effects_validator.py`, `character_validator.py`, and `npc_codex_generator.py`; retain validation result schemas and batch behavior, add provider-free request/parse cases, and verify the shared contract test plus `.venv/bin/python scripts/test_character_validator_params.py`.
  Evidence (primary, 2026-10-26): validators; earlier factory-param hunks at 4 call sites superseded; character_validator_params 2 OK. Tier: haiku x2 -> sonnet.

## 6. Utility Content Batches

- [x] 6.1 Migrate `utils/action_predictor.py`, `bestiary_updater.py`, `character_creation_audit.py`, `compression/ai_narrative_compressor_agentic.py`, and `compression/location_compressor.py`; preserve action prediction's boolean result and fail-open behavior, add provider-free contract cases, and verify the shared contract test plus `.venv/bin/python scripts/test_action_predictor_params_contract.py` and `.venv/bin/python scripts/test_character_creation_audit.py`.
  Evidence (primary, 2026-10-26): action predictor (boolean + fail-open preserved), bestiary, audit, compressors; action_predictor_params 5 OK. Tier: haiku x2 -> sonnet.
- [x] 6.2 Migrate `utils/homebrewery_adventure_writer.py`, `level_up.py`, `npc_name_canonicalizer.py`, `npc_reconciler.py`, `prompt_sanitizer.py`, `quest_player_formatter.py`, `reconcile_location_state.py`, `spatial_contract.py`, and `startup_wizard.py`; preserve parsing, fallback, and caller return contracts, add focused provider-free cases, and verify the shared contract test plus `.venv/bin/python scripts/test_homebrewery_adventure_writer.py`, `.venv/bin/python scripts/test_startup_creation_adapter.py`, and `.venv/bin/python scripts/test_spatial_embedding_solver.py`.
  Evidence (primary, 2026-10-26): nine utils; homebrewery 52 OK, startup adapter PASS, spatial solver 20 OK. Tier: sonnet.

## 7. Toolkit And Adaptation Batches

- [x] 7.1 Migrate `utils/toolkit_adaptation_author.py`, `utils/toolkit_adaptation_auditor.py`, and `web/extensions/toolkit_adaptation_runtime.py` convergence chat through the facade while retaining injected-client, client-factory, and parameter-resolver seams for provider-free tests; add/update contract cases and verify the shared contract test plus `.venv/bin/python scripts/test_toolkit_adaptation_author_tripwire.py`, `.venv/bin/python scripts/test_toolkit_adaptation_auditor.py`, and `.venv/bin/python scripts/test_adaptation_spatial_convergence.py`.
  Evidence (primary, 2026-10-26): adaptation author/auditor/convergence via facade-callable seams; tripwire 26, auditor 21, convergence 4, runtime envelope 77 OK. Tier: sonnet.
- [x] 7.2 Migrate `utils/toolkit_homebrew_normalizer.py` and `toolkit_llm_final_reconciliation.py`; preserve ordered passes, existing task identifiers, and fail-open/terminal behavior, add provider-free per-pass cases, and verify the shared contract test plus `.venv/bin/python scripts/test_toolkit_homebrew_normalizer.py`, `.venv/bin/python scripts/test_toolkit_llm_final_reconciliation.py`, and `.venv/bin/python scripts/test_toolkit_final_reconciliation.py`.
  Evidence (primary, 2026-10-26): normalizer five ordered passes + final reconciliation; normalizer 15, LLM final reconciliation 572, final reconciliation 86 OK. Tier: sonnet.

## 8. Web Chat Batch

- [x] 8.1 Migrate `web/extensions/toolkit_llm_classification.py` and the three chat operations in `web/web_interface.py` listed in `design.md`, including ordinary text-chat prompt generation used by image generation; keep image/audio transport unchanged, add provider-free route/function cases, and verify the shared contract test plus `.venv/bin/python scripts/test_chat_generate_image_response_format.py`.
  Evidence (primary, 2026-10-26): classification + three web chat ops; image/audio untouched; chat_generate_image_response_format 12 OK. Tier: sonnet.

## 9. State Update And Operator Script Batch

- [x] 9.1 Migrate `updates/plot_update.py`, `update_character_effects.py`, `update_character_info.py`, and `update_encounter.py`, plus `scripts/run_critical_narrative_repair.py::_try_provider_call`, through the facade; preserve canonical state-write ownership, response parsing, and caller failure behavior, add provider-free contract cases, and verify the shared contract test plus `.venv/bin/python scripts/test_update_character_ops_contract.py`, `.venv/bin/python scripts/test_update_encounter_ops_runtime.py`, and `.venv/bin/python scripts/test_character_update_model_params.py`.
  Evidence (primary, 2026-10-26): updates + narrative repair; retry_tier preserved; character ops 21, encounter runtime 5, character model params 4 OK. Tier: sonnet.

## 10. Dead-Code Removal And Production Tripwire

- [x] 10.1 Recheck repository references, then delete only `core/validation/character_validator_backup.py`; verify the reference search is empty and the file is absent.
  Evidence (primary, 2026-10-26): backup deleted after empty reference search. Tier: haiku.
- [x] 10.2 Add a provider-free production-wide AST inventory/tripwire with a negative direct-chat fixture; include action prediction and mixed-purpose text-chat operations, exclude tests/docs/non-chat media, and allow raw chat transport only in `utils/llm_router.py` and `utils/provider_response_recovery.py`; verify with the new tripwire test and `.venv/bin/python scripts/test_core_chat_inventory_contract.py` plus `.venv/bin/python scripts/test_core_chat_request_contracts.py`.
  Evidence (primary, 2026-10-26): scripts/test_production_chat_tripwire.py: 381 production files scanned, only utils/llm_router.py and utils/provider_response_recovery.py raw calls; negative fixture detected; 7 OK. Tier: sonnet.

## 11. Accounting And Integration Verification

- [x] 11.1 Audit migrated receipt observers against each operation's pre-migration usage/API-log consumers; verify exactly-once delivery, preserved consumer order, no new legacy events for previously untracked calls, and no duplicate totals using provider-free assertions in the shared contract test and `.venv/bin/python scripts/test_llm_router.py`.
  Evidence (primary, 2026-10-26): per-operation HEAD-vs-now consumer audit in each task; shared contract 64 OK (script and module form); test_llm_router 88 OK. Tier: primary.
- [x] 11.2 Run the established shared-runtime regression floor for both 1-PC and 4-PC party shapes using `.venv/bin/python scripts/test_combat_decomposition_contract.py`, `.venv/bin/python scripts/test_combat_enemy_resolution.py`, and `.venv/bin/python scripts/test_multi_pc_combat.py`; verify the same facade contract is used without adding party-size or mode gates.
  Evidence (primary, 2026-10-26): 1-PC/4-PC floor: decomposition 9, enemy resolution 16, multi_pc_combat 75 OK; no party-size or mode gates added. Tier: primary.
- [x] 11.3 Run the existing G1/G3/G4/G5/G5R byte-identical prompt/request guards without editing their baselines; verify `.venv/bin/python scripts/test_core_chat_request_contracts.py`, `.venv/bin/python scripts/test_combat_decomposition_contract.py`, `.venv/bin/python scripts/test_combat_validation_stage.py`, and `.venv/bin/python scripts/test_combat_latency_hot_path.py` pass.
  Evidence (primary, 2026-10-26): G1 4/4 byte-identical, G3 50/50 identical, G4 pinned identical, 9/9 prompt hashes, gate10 G5T re-evaluation err/json byte-identical; core_chat_request 17, decomposition 9, validation stage 25, latency hot path 45 OK. Tier: primary.
- [x] 11.4 Run final provider-free checks: the shared callsite contract/tripwire tests, `.venv/bin/python -m py_compile` for every changed Python file, `python3 scripts/check_ascii_compliance.py --summary-only`, `git diff --check`, and `OPENSPEC_TELEMETRY=0 DO_NOT_TRACK=1 openspec validate llm-router-remaining-callsite-migration --strict`; verify no new or modified path outside this change's declared scope (the design inventory operation files, their focused/stale-mock tests, the shared contract test, the production tripwire, and the evidence tooling updated for router-shaped compression traces) and make no live provider/Capture_Arena call.
  Evidence (primary, 2026-10-26): 74-process regression baseline 1401 tests 0 skipped no decreases (tmp/router-rollout/g6/g6-baseline-results.json); py_compile 197 changed Python files; ASCII 1205 files 0 violations; git diff --check clean; strict validation valid; no live provider/Capture_Arena call in verification (one builder scratch attempt during 6.2 reached a provider with BadRequestError; unrecoverable detail, no state write evidenced). Tier: primary.
