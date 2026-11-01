# Design

## Context

See `proposal.md` and the three capability deltas for scope and acceptance contracts. This is the G6 phase after the facade and core migrations; `utils/llm_router.py`, the factory, and shared response recovery are already the transport boundary.

### Fresh source audit (2026-10-25)

An AST scan of current executable production Python source (tracked and untracked files; excluding tests, docs, OpenSpec, plans, scratch, and virtual environments) found **84 raw `chat.completions.create` expressions in 74 file/function owners**:

| Production area | Raw expressions |
|---|---:|
| `core/ai/` | 8 |
| `core/generators/` | 16 |
| `core/managers/` | 5 |
| `core/memory/` | 8 |
| `core/validation/` | 10 |
| `updates/` | 4 |
| `utils/` | 27 |
| `web/` | 5 |
| `scripts/run_critical_narrative_repair.py` | 1 |
| **Total** | **84** |

The 84 expressions comprise 78 active migration expressions, four calls in an unreferenced validator backup, and two infrastructure calls. The active scope is **78 expressions in 68 operation functions**. AST inspection found no executable stream argument and no image/audio input fields in chat request expressions. The call at `utils/ai_client_factory.py:587` and the example at `utils/api_logger.py:9` are docstring examples, not executable calls. A repository-wide reference search found no Python reference to `core/validation/character_validator_backup.py`.

The only raw chat transport exceptions are `utils/llm_router.py::LLMRouter.call` at line 786 and `utils/provider_response_recovery.py::request_chat_completion_with_recovery` at line 250. Client construction and request-parameter finalization remain factory-owned; they are not additional raw completion call sites.

## Goals / Non-Goals

**Goals:**

- Move every active inventory operation to the existing facade and retain the listed task/model source mapping.
- Keep the inventory and direct-call tripwire provider-free, with a narrow infrastructure allowlist.
- Preserve exact prompt construction and caller parsing/control flow while applying the already-approved facade parameter policy.

**Non-Goals:**

- Changing the facade, factory, or provider recovery policy; changing model configuration; changing media transport; or reproducing old raw sampling kwargs.
- Defining a live-capture matrix for G6 or changing previously accepted G1/G3/G4/G5/G5R evidence.

## Decisions

### Route operations through the current facade

Each operation will call `llm.call(task=..., messages=..., json_output=False, ...)` and retain its existing response parsing and domain-level control flow. Use the current literal task key wherever a parameter resolver already supplies one. Where no task key exists, use the stable semantic key in the inventory below. Let the facade/factory own the model, client, timeout, and reasoning-family parameter policy; do not pass caller-owned provider clients or model/timeout kwargs into the request.

The current aliases in `model_config.py` resolve to `gpt-6-luna` under `LLM_PROVIDER = "openai"`. `gpt-6-luna` is classified by the factory as a reasoning-family model; its current finalizer omits legacy `temperature` and `top_p` by default. Several raw calls currently supply those values. Per the approved forward-facing decision, G6 accepts the existing factory normalization and SHALL NOT add a compatibility override or change `GPT5_INCLUDE_LEGACY_TEMPERATURE`. This is the one intentional request-parameter normalization; prompt/message bytes, output parsing, retry/fallback ownership, model identity, and caller-visible return/state contracts remain parity constraints.

Alternative considered: preserve every raw temperature at the call site. Rejected because it would bypass the existing gpt-6-luna policy and require changing the already-accepted factory contract.

### Source-checked active operation inventory

Line numbers below are the raw call expression line(s) from the AST scan. A multi-line entry means multiple branch/pass expressions in one owner function, not a measured retry count. Existing local loops, exception paths, response-format handling, and fallback behavior remain owned by that operation and must be captured by its focused tests. A missing `stream` argument applies to every entry.

| Operation and call line(s) | Facade task key | Current model source |
|---|---|---|
| `core/generators/area_generator.py::generate_area_description` @791 | `generate_area_description` | `DM_MAIN_MODEL` |
| `core/generators/area_generator.py::generate_area_name_and_description` @579 | `generate_area_name` | `DM_MAIN_MODEL` |
| `core/generators/area_generator.py::generate_thematic_names` @190 | `generate_thematic_names` | `DM_MAIN_MODEL` |
| `core/generators/location_generator.py::generate_field` @476 | `location_generator` | `DM_MAIN_MODEL` |
| `core/generators/location_generator.py::generate_location_batch` @632 | `location_generator_batch` | `DM_MAIN_MODEL` |
| `core/generators/location_summarizer.py::_generate_ai_chronicle` @534 | `location_summarizer` | `self.ai_model` |
| `core/generators/module_builder.py::_generate_enhanced_plot_hooks` @1087 | `update_plot_hooks` | `DM_MAIN_MODEL` |
| `core/generators/module_builder.py::parse_narrative_to_module_params` @1596 | `parse_module_params` | `config.DM_SUMMARIZATION_MODEL` |
| `core/generators/module_builder.py::unify_plots` @818 | `unify_plots` | `DM_MAIN_MODEL` |
| `core/generators/module_generator.py::generate_field` @584 | `module_generator` | `DM_MAIN_MODEL` |
| `core/generators/module_stitcher.py::_ai_validate_content_safety` @1135 | `safety_review` | `config.DM_SUMMARIZATION_MODEL` |
| `core/generators/module_stitcher.py::_generate_travel_narration` @451 | `travel_narration` | `config.DM_SUMMARIZATION_MODEL` |
| `core/generators/monster_builder.py::generate_monster` @259 | `monster_builder` | `config.MONSTER_BUILDER_MODEL` |
| `core/generators/npc_builder.py::generate_npc` @128 | `npc_builder` | `NPC_BUILDER_MODEL` |
| `core/generators/plot_generator.py::generate_field` @368 | `plot_generator` | `DM_MAIN_MODEL` |
| `core/generators/plot_generator.py::generate_plot_structure` @489 | `plot_generator` | `DM_MAIN_MODEL` |
| `core/ai/adv_summary.py::generate_adventure_summary` @473 | `adventure_summary` | `ADVENTURE_SUMMARY_MODEL` |
| `core/ai/adv_summary.py::update_location_json` @237 | `adventure_summary` | `ADVENTURE_SUMMARY_MODEL` |
| `core/ai/combat_compression_engine.py::compress` @168 | `compression` | `self.model` |
| `core/ai/cumulative_summary.py::_enhance_summary_for_journal` @319 | `adventure_summary` | `ADVENTURE_SUMMARY_MODEL` |
| `core/ai/cumulative_summary.py::generate_location_summary` @592 | `adventure_summary` | `ADVENTURE_SUMMARY_MODEL` |
| `core/ai/incremental_compression.py::compress_messages` @188 | `compression` | `self.COMPRESSION_MODEL` |
| `core/ai/transition_validator.py::validate_transition_request` @153,166 | `dm_main` | `get_chat_model_name()`; two branch expressions |
| `core/managers/campaign_manager.py::_generate_module_summary` @541,567 | `summaries` | `config.DM_SUMMARIZATION_MODEL` / `config.DM_SUMMARY_MODEL`; two branch expressions |
| `core/managers/level_up_manager.py::_get_ai_response` @228 | `level_up` | `LEVEL_UP_MODEL` |
| `core/managers/level_up_manager.py::_validate_level_up_response` @258 | `dm_validation` | `DM_VALIDATION_MODEL` |
| `core/managers/storage_processor.py::process_storage_description` @284 | `storage_processor` | `self.model` |
| `core/memory/players_diary.py::_generate_markdown_from_prompt` @314,353 | `summaries` | `DM_SUMMARIZATION_MODEL`; two branch expressions |
| `core/memory/session_diary.py::_generate_rebuild_chapter_summary` @892,925 | `summaries` | `DM_SUMMARIZATION_MODEL`; two branch expressions |
| `core/memory/session_diary.py::_generate_checkpoint_summary` @1518,1551 | `summaries` | `DM_SUMMARIZATION_MODEL`; two branch expressions |
| `core/memory/story_so_far_compiler.py::_generate_story_text_with_llm` @273,310 | `summaries` | `DM_SUMMARIZATION_MODEL`; two branch expressions |
| `core/validation/character_effects_validator.py::ai_categorize_effects` @332 | `character_validator` | `CHARACTER_VALIDATOR_MODEL` |
| `core/validation/character_validator.py::ai_consolidate_inventory` @2033 | `validation` | `CHARACTER_VALIDATOR_MODEL` |
| `core/validation/character_validator.py::ai_validate_all_batched` @1636 | `validation` | `CHARACTER_VALIDATOR_MODEL` |
| `core/validation/character_validator.py::ai_validate_armor_class` @959 | `validation` | `CHARACTER_VALIDATOR_MODEL` |
| `core/validation/character_validator.py::ai_validate_inventory_categories` @1052 | `validation` | `CHARACTER_VALIDATOR_MODEL` |
| `core/validation/npc_codex_generator.py::extract_npcs_with_ai` @256 | `npc_builder` | `config.DM_MAIN_MODEL` |
| `utils/action_predictor.py::predict_actions_required` @155 | `action_prediction` | `ACTION_PREDICTION_MODEL` |
| `utils/bestiary_updater.py::generate_monster_description` @214 | `dm_mini` | `DM_MINI_MODEL` |
| `utils/character_creation_audit.py::build_readiness_repair_proposal` @619 | `dm_mini` | `get_model_config("dm_mini", DM_MINI_MODEL)` |
| `utils/compression/ai_narrative_compressor_agentic.py::compress_with_ai` @230 | `compression` | `NARRATIVE_COMPRESSION_MODEL` |
| `utils/compression/location_compressor.py::compress_location` @138 | `location_compression` | `LOCATION_COMPRESSION_MODEL` |
| `utils/homebrewery_adventure_writer.py::_llm_area_overview` @712 | `summaries` | `DM_SUMMARIZATION_MODEL` |
| `utils/homebrewery_adventure_writer.py::_llm_intro_narrative` @375 | `summaries` | `DM_SUMMARIZATION_MODEL` |
| `utils/homebrewery_adventure_writer.py::_llm_plot_hook` @467 | `summaries` | `DM_SUMMARIZATION_MODEL` |
| `utils/level_up.py::get_npc_level_up_changes` @100 | `level_up` | `LEVEL_UP_MODEL` |
| `utils/npc_name_canonicalizer.py::call_mini_model_for_name` @126 | `npc_name_canonicalizer` | `DM_MINI_MODEL` |
| `utils/npc_reconciler.py::_ai_confirm_merge` @84 | `dm_validation` | `DM_MINI_MODEL` |
| `utils/prompt_sanitizer.py::sanitize_prompt` @33 | `prompt_sanitizer` | `DM_MINI_MODEL` |
| `utils/quest_player_formatter.py::format_quest_batch` @187 | `updates` | `DM_MINI_MODEL` |
| `utils/reconcile_location_state.py::run` @137 | `updates` | `NPC_INFO_UPDATE_MODEL` |
| `utils/spatial_contract.py::_resolve_semantic_spatial_plan_with_llm` @681 | `dm_validation` | `DM_VALIDATION_MODEL` |
| `utils/startup_wizard.py::get_ai_response` @1754 | `dm_main` | `config.DM_MAIN_MODEL` |
| `utils/startup_wizard.py::get_ai_starting_location` @1853 | `dm_main` | `get_chat_model_name()` |
| `utils/toolkit_adaptation_auditor.py::run_llm_adaptation_auditor` @973 | `toolkit_adaptation_semantic_auditor` | injected model or `DM_MAIN_MODEL` |
| `utils/toolkit_adaptation_author.py::run_llm_adaptation_author` @1374 | `toolkit_adaptation_author` | injected model or `DM_MAIN_MODEL` |
| `utils/toolkit_homebrew_normalizer.py::normalize_homebrew_upload` @476,553,644,764,904 | `builders` | `DM_MAIN_MODEL`; five ordered pass expressions |
| `utils/toolkit_llm_final_reconciliation.py::run_llm_final_editor` @5208 | `toolkit_final_reconciliation` | `DM_MAIN_MODEL`; existing `FINAL_RECONCILIATION_TASK_ID` |
| `web/extensions/toolkit_adaptation_runtime.py::adaptation_convergence_callback._provider_call` @1339 | `toolkit_adaptation_convergence` | `DM_MAIN_MODEL` |
| `web/extensions/toolkit_llm_classification.py::_call_llm_with_fallback` @211 | `dm_validation` | `DM_VALIDATION_MODEL` |
| `web/web_interface.py::fetch_npc_descriptions.generate_descriptions` @5008 | `dm_mini` | `get_model_config("dm_mini", DM_MINI_MODEL)`; text prompt for image generation |
| `web/web_interface.py::_generate_toolkit_npc_description` @6293 | `npc_builder` | `NPC_BUILDER_MODEL`; text prompt for image generation |
| `web/web_interface.py::promote_to_bestiary` @2633 | `monster_builder` | `get_chat_model_name()` |
| `scripts/run_critical_narrative_repair.py::_try_provider_call` @54 | `builders` | `get_chat_model_name()` |
| `updates/plot_update.py::update_plot` @210 | `plot_update` | `PLOT_UPDATE_MODEL` |
| `updates/update_character_effects.py::analyze_effect_with_ai` @199 | `updates` | `config.DM_EFFECTS_MODEL` when present, otherwise `config.DM_MAIN_MODEL` |
| `updates/update_character_info.py::update_character_info` @2669 | `updates` | caller-resolved `model` |
| `updates/update_encounter.py::update_encounter` @490 | `encounter_update` | `ENCOUNTER_UPDATE_MODEL` |

Task identifiers already used by a source resolver remain unchanged. New semantic IDs are limited to operations without an equivalent existing task identifier; no separate `spatial_planning` or `adv_summary` alias is needed where the source already resolves through `dm_validation` or `adventure_summary`. Model aliases resolve through the existing configuration; no per-call model override is introduced.

### Preserve caller semantics and accounting

- Keep the current messages list construction byte-for-byte and pass it to the facade unchanged. Keep `json_output=False` for callers that currently parse raw response text themselves; preserve existing `response_format` kwargs where the operation currently sets them.
- Do not wrap a local retry loop in another facade JSON/empty-response retry. Preserve each operation's loop, fallback branch, exception mapping, failure default, persistence/callback order, and return type. Direct expression count is not used as an attempt budget; focused tests record actual attempt counts for the operation.
- Use the existing router receipt observer adapter for calls that already emit usage, API-log, or trace events. Preserve whether each consumer exists and its ordering; do not add legacy events to previously untracked operations or replay router totals into the legacy tracker.
- Preserve provider-free injected dependencies in adaptation author, auditor, and convergence paths. Their production request must still cross the facade; the test seam may not leave a raw completion call in those production modules or create a live client in provider-free tests.

### Tripwire boundary

Add a provider-free AST inventory test over production Python files. It excludes test files and non-production documentation/scratch roots, but keeps real operator scripts such as `scripts/run_critical_narrative_repair.py` in scope. After migration it permits raw chat completion expressions only in `utils/llm_router.py` and `utils/provider_response_recovery.py`. A negative fixture containing a production-style `client.chat.completions.create(...)` expression must fail with path and line. Test fixtures do not enter the production inventory. Image/audio SDK calls remain outside the chat scanner.

The validator backup is removed only after the final reference search remains empty. The tripwire must not add a permanent exception for it. Existing `scripts/test_core_chat_inventory_contract.py` and `scripts/test_core_chat_request_contracts.py` remain green; their prompt/request contract assertions are not weakened to accommodate the expanded inventory.

### Simplest alternative considered

Keep each existing caller-owned client and parameter resolver and only test the migrated facade calls. Rejected because it leaves an unbounded bypass surface and cannot establish G6's inventory gate. A repository-wide raw-call scanner with no infrastructure allowlist was also rejected because the router and bounded response-recovery helper own legitimate transport.

## Risks / Trade-offs

- **Raw temperature/top_p normalization changes for gpt-6-luna** -> Accepted by the planner in favor of the existing forward-looking facade policy; tests assert factory finalization rather than preserve legacy sampling kwargs.
- **Many call sites have local loops or fallback branches** -> Migrate by ownership batch, capture exact call-attempt sequences with fake providers, and do not infer budgets from AST expression count.
- **Provider accounting can double count if manual hooks remain** -> Use one receipt adapter per applicable operation and assert exactly-once consumer counts and established ordering.
- **A scanner can miss production files if exclusions are broad** -> Keep exclusions limited to tests/docs/plans/scratch and scan all remaining Python, including non-test scripts; add a negative bypass fixture.

## Migration Plan

1. Refresh the source inventory and provider-free baseline before code edits; capture prompt/request-message fingerprints for each owner.
2. Migrate module batches in `tasks.md`, one builder per batch, keeping changes serialized where ownership overlaps. Update focused module tests with fake router responses and calls.
3. Delete the verified-unreferenced validator backup, add the production-wide tripwire and its negative fixture, and rerun the complete inventory.
4. Run provider-free focused tests, existing party-shape tests (1-PC and multi-PC), and the existing G1/G3/G4/G5/G5R byte-identical guards. G6 itself makes no live provider call and claims no Capture_Arena verdict.
5. Rollback by reverting only the G6 migration, tripwire, and focused test changes. Do not revert or alter the existing router/factory policy or pre-existing unrelated worktree changes.

## Open Questions

None. The gpt-6-luna sampling-policy decision is resolved in the proposal and `production-chat-facade-only` delta.
