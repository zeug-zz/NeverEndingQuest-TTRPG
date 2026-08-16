# Build-Path Chat Completions Call Site Inventory

Task 1.1 baseline for `toolkit-gpt5-build-path-compatibility`.

- Inventoried: 2026-08-03
- Refreshed: 2026-08-03 (task 2.1) - normalizer call sites N1-N5 migrated
  from DIRECT to HELPER routing; line numbers and routing legend updated
  below. All other in-scope rows are unchanged and remain DIRECT.
- Refreshed: 2026-08-03 (task 2.2) - ModuleBuilder generator call sites
  B1-B3 and G1-G10 migrated from DIRECT to HELPER routing; line numbers,
  routing legend, and helper-routed file set updated below. Remaining
  in-scope rows (S1, C1, M1-M3) were pending the next migration tasks.
- Refreshed: 2026-08-03 (task 2.3) - S1/C1 and build/publication-adjacent
  sites A1, A2, A4, A7, and A9 migrated to HELPER routing. Stage-local
  provider diagnostics were added. A3, A5, A6, and A8 remain DIRECT by
  explicit call-graph exclusion.
- Refreshed: 2026-08-03 (task 3.1) - Markdown enrichment call sites M1-M3
  migrated from DIRECT to HELPER routing with task id `summaries` (profile
  verified as medium-medium in the task 4.1 refresh note below). Line
  numbers, routing legend, and helper-routed file set updated
  below. Every in-scope priority call site is now HELPER-routed.
- Refreshed: 2026-08-03 (task 3.2) - Forbidden-legacy-parameter audit.
  Re-audited every priority create block (N1-N5, B1-B3, G1-G10, S1, C1,
  M1-M3) and every traced included adjacent block (A1, A2, A4, A7, A9)
  for direct `top_p`, direct `temperature=` kwargs, and direct
  `**...get("extra_body")` spreads. Result: NONE remain in any priority or
  traced included block; all sampling intent flows through the shared helper
  (inline spread). The only direct
  `temperature=` in the traced adjacent file set is at the excluded
  interactive blocks A5 (web/web_interface.py:4767) and A6
  (web/web_interface.py:2535), which retain their legacy shape by explicit
  call-graph exclusion. Absence is now durable via
  `scripts/test_build_path_forbidden_params.py` (task 3.2 source contract +
  fixture-based final-kwargs capture per priority task id). No production
  edits were required by this audit.
- Refreshed: 2026-08-03 (task 4.1) - Profile claim correction for M1-M3.
  Task 4.1 aggregate contract tests verified the ACTUAL resolver output for
  the `summaries` task id: `_resolve_gpt5_chat_profile("summaries")` does
  NOT match the `"summary"` substring branch (the id is plural and lacks the
  `y`), so M1-M3 resolve the default medium/medium branch on direct GPT-5,
  not the low/medium summary branch. The table and text below are corrected
  to the verified behavior; the resolver (utils/ai_client_factory.py) and
  call sites are unchanged. The summary-family low/medium branch remains
  reachable via `adventure_summary` and similar ids.
- Scope: priority build-time Chat Completions call sites in Homebrew
  normalization, ModuleBuilder and its generators, spatial/classification
  toolkit calls, and Markdown/publication-adjacent calls, as named by
  proposal.md and design.md.
- Verification: source-contract test
  `scripts/test_build_call_site_inventory.py` (change-local, provider-free)
  plus repository searches documented below. Line numbers are asserted by
  the test and are accurate as of the refresh date.
- Parameter authority reference: `get_chat_completion_params(task_id,
  original_openai_model, temperature_override=..., retry_tier=...)` in
  `utils/ai_client_factory.py` (line 532). GPT-5-family direct-OpenAI
  requests omit `temperature`/`top_p` unless `GPT5_INCLUDE_LEGACY_TEMPERATURE`
  is enabled (default False) and receive `reasoning_effort`/`verbosity`
  resolved from the task id. OpenRouter requests retain model, temperature,
  and `extra_body` thinking fields.

Routing legend:

- DIRECT: call site constructs `chat.completions.create(...)` kwargs itself
  (may use `get_model_config` for the model, but not the shared helper).
- HELPER: call site spreads `**get_chat_completion_params(...)`.
- Model source: the constant or resolution expression passed to the factory.

## 1. In-scope priority call sites (23 helper-routed)

### 1.1 Homebrew normalization - utils/toolkit_homebrew_normalizer.py

All five call sites live inside `normalize_homebrew_upload()` (the
accurate-ingest multipass + legacy one-shot + fidelity repair pipeline) and
are HELPER (migrated in task 2.1). All use task id `builders` with model
source `get_model_config("builders", DM_MAIN_MODEL)` for model reporting and
spread `**get_chat_completion_params("builders", DM_MAIN_MODEL,
temperature_override=...)` for the create call. Sampling fields are
helper-resolved: direct GPT-5 requests omit legacy `temperature`/`top_p` and
carry the `builders` medium/medium profile; non-GPT-5 and OpenRouter retain
the configured temperature (OpenRouter also keeps `extra_body` thinking
fields). `timeout` remains a direct non-sampling kwarg on each create call.

| ID | File:Line | Function / identifier | Task ID / GPT-5 profile | Model source | Timeout | Sampling fields |
|----|-----------|----------------------|------------------------|--------------|---------|-----------------|
| N1 | utils/toolkit_homebrew_normalizer.py:476 | normalize_homebrew_upload - section extraction | builders / medium-medium | get_model_config("builders", DM_MAIN_MODEL) | 90 | helper-resolved; override config temp (default 0.2); GPT-5 omits temperature/top_p |
| N2 | utils/toolkit_homebrew_normalizer.py:553 | normalize_homebrew_upload - identity adjudication | builders / medium-medium | get_model_config("builders", DM_MAIN_MODEL) | 90 | helper-resolved; override config temp (default 0.2); GPT-5 omits temperature/top_p |
| N3 | utils/toolkit_homebrew_normalizer.py:644 | normalize_homebrew_upload - plot topology synthesis | builders / medium-medium | get_model_config("builders", DM_MAIN_MODEL) | 90 | helper-resolved; override config temp (default 0.2); GPT-5 omits temperature/top_p |
| N4 | utils/toolkit_homebrew_normalizer.py:764 | normalize_homebrew_upload - legacy one-shot normalization | builders / medium-medium | get_model_config("builders", DM_MAIN_MODEL) | 120 | helper-resolved; override config temp (default 0.3); GPT-5 omits temperature/top_p |
| N5 | utils/toolkit_homebrew_normalizer.py:905 | normalize_homebrew_upload - fidelity repair | builders / medium-medium | get_model_config("builders", DM_MAIN_MODEL) | 90 | helper-resolved; override config temp (default 0.2); GPT-5 omits temperature/top_p |

### 1.2 ModuleBuilder - core/generators/module_builder.py

All three call sites are HELPER (migrated in task 2.2). Each spreads
`**get_chat_completion_params(task_id, MODEL_SOURCE, temperature_override=...)`
and keeps `messages` and `response_format` as direct non-sampling kwargs.
Sampling fields are helper-resolved: direct GPT-5 requests omit legacy
`temperature`/`top_p` and carry the recorded task profile; non-GPT-5 and
OpenRouter retain the recorded temperature intent (OpenRouter also keeps
`extra_body` thinking fields). No `timeout` is set (unchanged).

| ID | File:Line | Function / identifier | Task ID / GPT-5 profile | Model source | Timeout | Sampling fields |
|----|-----------|----------------------|------------------------|--------------|---------|-----------------|
| B1 | core/generators/module_builder.py:693 | ModuleBuilder.unify_plots | unify_plots / medium-medium | DM_MAIN_MODEL (via helper) | none | helper-resolved; override 0.7; response_format json_object; GPT-5 omits temperature/top_p |
| B2 | core/generators/module_builder.py:957 | ModuleBuilder._generate_enhanced_plot_hooks | update_plot_hooks / medium-medium | DM_MAIN_MODEL (via helper) | none | helper-resolved; override 0.6; response_format json_object; GPT-5 omits temperature/top_p |
| B3 | core/generators/module_builder.py:1463 | parse_narrative_to_module_params (module-level function) | parse_module_params / medium-medium | config.DM_SUMMARIZATION_MODEL (via helper) | none | helper-resolved; override 0.3; GPT-5 omits temperature/top_p |

Note: B2 previously referenced a `model_config` variable that was never
defined in `_generate_enhanced_plot_hooks` scope (latent NameError); the
migration makes the call site self-contained by importing the helper next to
the existing function-local `from config import DM_MAIN_MODEL` import.

### 1.3 ModuleBuilder generators (core/generators)

All call sites below are HELPER (migrated in task 2.2). Each spreads
`**get_chat_completion_params(task_id, MODEL_SOURCE, temperature_override=...)`
and keeps `messages` (and `response_format` where present) as direct
non-sampling kwargs. Sampling fields are helper-resolved: direct GPT-5
requests omit legacy `temperature`/`top_p` and carry the recorded task
profile (medium-medium unless noted); non-GPT-5 and OpenRouter retain the
recorded temperature intent (OpenRouter also keeps `extra_body` thinking
fields). No `timeout` is set (unchanged).

| ID | File:Line | Function / identifier | Task ID / GPT-5 profile | Model source | Timeout | Sampling fields |
|----|-----------|----------------------|------------------------|--------------|---------|-----------------|
| G1 | core/generators/module_generator.py:526 | ModuleGenerator.generate_field | module_generator / medium-medium | DM_MAIN_MODEL (via helper) | none | helper-resolved; override 0.7; GPT-5 omits temperature/top_p |
| G2 | core/generators/area_generator.py:180 | MapLayoutGenerator.generate_thematic_names | generate_thematic_names / medium-medium | DM_MAIN_MODEL (via helper) | none | helper-resolved; override 0.8; GPT-5 omits temperature/top_p |
| G3 | core/generators/area_generator.py:546 | AreaGenerator.generate_area_name_and_description | generate_area_name / medium-medium | DM_MAIN_MODEL (via helper) | none | helper-resolved; override 0.8; response_format json_object; GPT-5 omits temperature/top_p |
| G4 | core/generators/area_generator.py:731 | AreaGenerator.generate_area_description | generate_area_description / medium-medium | DM_MAIN_MODEL (via helper) | none | helper-resolved; override 0.8; GPT-5 omits temperature/top_p |
| G5 | core/generators/plot_generator.py:349 | PlotGenerator.generate_field | plot_generator / medium-medium | DM_MAIN_MODEL (via helper) | none | helper-resolved; override 0.7; GPT-5 omits temperature/top_p |
| G6 | core/generators/plot_generator.py:468 | PlotGenerator.generate_plot_structure | plot_generator / medium-medium | DM_MAIN_MODEL (via helper) | none | helper-resolved; override 0.8; response_format json_object; GPT-5 omits temperature/top_p |
| G7 | core/generators/location_generator.py:461 | LocationGenerator.generate_field | location_generator / medium-medium | DM_MAIN_MODEL (via helper) | none | helper-resolved; override 0.7; GPT-5 omits temperature/top_p |
| G8 | core/generators/location_generator.py:607 | LocationGenerator.generate_location_batch | location_generator_batch / medium-medium | DM_MAIN_MODEL (via helper) | none | helper-resolved; override 0.8; response_format json_object; GPT-5 omits temperature/top_p |
| G9 | core/generators/npc_builder.py:123 | generate_npc | npc_builder / medium-medium | NPC_BUILDER_MODEL (via helper) | none | helper-resolved; override 0.7; GPT-5 omits temperature/top_p |
| G10 | core/generators/monster_builder.py:249 | generate_monster | monster_builder / medium-medium | config.MONSTER_BUILDER_MODEL (via helper) | none | helper-resolved; override 0.7; GPT-5 omits temperature/top_p |

### 1.4 Spatial toolkit call

| ID | File:Line | Function / identifier | Task ID / GPT-5 profile | Model source | Timeout | Sampling fields |
|----|-----------|----------------------|------------------------|--------------|---------|-----------------|
| S1 | utils/spatial_contract.py:671 | _resolve_semantic_spatial_plan_with_llm | dm_validation / low-low | DM_VALIDATION_MODEL (via helper) | none | helper-resolved; override config temp (default 0.2); response_format json_object; GPT-5 omits temperature/top_p |

HELPER. Uses `get_chat_completion_params("dm_validation", DM_VALIDATION_MODEL,
temperature_override=...)`. Fail-open to the deterministic fallback plan, with
`provider_diagnostics.stage=toolkit_spatial.semantic_plan` on provider failure.

### 1.5 Classification toolkit call

| ID | File:Line | Function / identifier | Task ID / GPT-5 profile | Model source | Timeout | Sampling fields |
|----|-----------|----------------------|------------------------|--------------|---------|-----------------|
| C1 | web/extensions/toolkit_llm_classification.py:211 | ClassificationCache._call_llm_with_fallback | dm_validation / low-low | DM_VALIDATION_MODEL (via helper) | none | helper-resolved; override 0.2; response_format json_object; GPT-5 omits temperature/top_p |

HELPER. Single shared entry point for all toolkit LLM classification domains
(entity triage, destination phrases, NPC visibility, remediation proposals;
DP1-3). Provider failures retain domain stage IDs such as
`toolkit_classification.entity`; classification defaults/empty proposals remain
the existing fail-open fallback while the enclosing stage reports degraded.

### 1.6 Markdown / publication-adjacent calls - utils/homebrewery_adventure_writer.py

All three call sites are HELPER (migrated in task 3.1). Each spreads
`**get_chat_completion_params("summaries", DM_SUMMARIZATION_MODEL,
temperature_override=...)` and keeps `messages` and `max_completion_tokens`
as direct non-sampling kwargs. Task id `summaries` resolves to the default
medium/medium branch on the GPT-5 side (verified in task 4.1: the
`"summary"` substring branch does not match the plural id, so the
low-reasoning summary family is not applied here; see refresh note above).
Sampling fields are helper-resolved: direct GPT-5 requests omit legacy
`temperature`/`top_p` and carry the medium-medium profile; non-GPT-5 and
OpenRouter retain the recorded temperature intent (OpenRouter also keeps
`extra_body` thinking fields). The existing `DM_SUMMARIZATION_MODEL`
assignment is preserved unchanged. No `timeout` is set (unchanged).
Deterministic Markdown fallback remains intact: each `_llm_*` helper
returns `None` on provider error or unusable output, and the enclosing
section builders emit their existing deterministic content.

| ID | File:Line | Function / identifier | Task ID / GPT-5 profile | Model source | Timeout | Sampling fields |
|----|-----------|----------------------|------------------------|--------------|---------|-----------------|
| M1 | utils/homebrewery_adventure_writer.py:343 | _llm_intro_narrative | summaries / medium-medium | DM_SUMMARIZATION_MODEL (via helper) | none | helper-resolved; override 0.5; max_completion_tokens=800; GPT-5 omits temperature/top_p |
| M2 | utils/homebrewery_adventure_writer.py:430 | _llm_plot_hook | summaries / medium-medium | DM_SUMMARIZATION_MODEL (via helper) | none | helper-resolved; override 0.7; max_completion_tokens=250; GPT-5 omits temperature/top_p |
| M3 | utils/homebrewery_adventure_writer.py:670 | _llm_area_overview | summaries / medium-medium | DM_SUMMARIZATION_MODEL (via helper) | none | helper-resolved; override 0.6; max_completion_tokens=500; GPT-5 omits temperature/top_p |

### 1.7 Deferred external adaptation caller

R1 (`utils/toolkit_llm_final_reconciliation.py`) belongs to the later
adaptation work and is absent from this clean baseline. It is intentionally
deferred and is not included in the isolated priority count, helper set, or
task-id assertions. No adaptation-only file is added here.

## 2. Adjacent observed call sites (not named by proposal/design; flag for sweep decision)

Observed during the repository search. They can run during build-time
normalization/publication (task 2.3 wording) but are not part of the original
priority named set. Recorded so nothing is silently omitted. Task 2.3 includes
A1, A2, A4, A7, and A9 after call-graph tracing; A3, A5, A6, and A8 remain
explicitly excluded for the reasons in the table.

| ID | File:Line | Function / identifier | Task ID | Model source | Timeout | Sampling fields | Route | Note |
|----|-----------|----------------------|---------|--------------|---------|-----------------|-------|------|
| A1 | core/generators/module_stitcher.py:451 | ModuleStitcher._generate_travel_narration | travel_narration | config.DM_SUMMARIZATION_MODEL (via helper) | none | helper-resolved; override 0.8; GPT-5 omits temperature/top_p | HELPER | Included: `_run_registry_stage()` calls `ModuleStitcher.integrate_module()` during toolkit post-build finishing; fallback remains degraded and stage-tagged. |
| A2 | core/generators/module_stitcher.py:1136 | ModuleStitcher._ai_validate_content_safety | safety_review | config.DM_SUMMARIZATION_MODEL (via helper) | none | helper-resolved; override 0.1; GPT-5 omits temperature/top_p | HELPER | Included: registry integration invokes safety validation during publication; existing fail-open safety result remains, while registry stage reports provider degradation. |
| A3 | core/generators/location_summarizer.py:534 | LocationSummarizer._generate_ai_chronicle | location_summarizer | get_model_config("location_summarizer", self.ai_model) | none | temperature=0.8; max_tokens=650 | DIRECT | Excluded: runtime narrator location chronicle; no build/finisher/publication caller. |
| A4 | web/web_interface.py:5827 | toolkit NPC description helper | npc_builder | NPC_BUILDER_MODEL (via helper) | none | helper-resolved; override config temp (default 0.7); max_tokens=300; GPT-5 omits temperature/top_p | HELPER | Included: `generate_unified_assets` toolkit asset-generation path; provider failure preserves deterministic description but marks completion degraded with stage identity. |
| A5 | web/web_interface.py:4762 | portrait prompt generation | dm_mini | get_model_config("dm_mini", DM_MINI_MODEL) | none | temperature=0.8 | DIRECT | Excluded: interactive portrait endpoint; not part of build normalization/publication or toolkit asset/report generation. |
| A6 | web/web_interface.py:2530 | promote_to_bestiary | none (no task id) | get_chat_model_name() (no get_model_config) | none | temperature=0.7 | DIRECT | Excluded: interactive bestiary promotion endpoint; no build/finisher caller. |
| A7 | utils/npc_reconciler.py:71 | NpcReconciler._ai_confirm_merge | dm_validation / low-low | DM_MINI_MODEL (via helper) | none | helper-resolved; override 0.0; max_tokens=1; GPT-5 omits temperature/top_p | HELPER | Included: `ModuleBuilder.build_module()` invokes NPC reconciliation before validation/backup publication. Provider failure safely declines merge and records stage. |
| A8 | utils/npc_name_canonicalizer.py:126 | call_mini_model_for_name | none (no build task) | DM_MINI_MODEL (raw constant) | none | temperature=0.0; max_tokens=20 | DIRECT | Excluded: repository callers are companion-memory runtime code only; no build/publication caller was found. |
| A9 | scripts/run_critical_narrative_repair.py:54 | _try_provider_call | builders (nearest repair profile) | get_chat_model_name() (via helper) | 120 | helper-resolved; override 0.2; GPT-5 omits temperature/top_p | HELPER | Included: explicit accurate-ingest critical narrative repair CLI; provider failure remains fail-closed and writes `provider_stage`. |

Scope note: A4 previously called `get_model_config("npc_builder")` without
an original model argument, which defaulted direct-provider resolution to the
generic fallback model. The migration passes the existing
`NPC_BUILDER_MODEL` assignment to the shared helper, preserving the intended
assignment while fixing the GPT-5 request boundary.

## 3. Provider-free toolkit helpers (negative inventory)

Files in the toolkit/build path with NO `chat.completions.create` call
(verified by repository search; deterministic helpers only):

- utils/toolkit_blueprint_enrichment.py,
  utils/toolkit_blueprint_seed_writer.py, utils/toolkit_build_fidelity.py,
  utils/toolkit_builder_blueprint.py, utils/toolkit_entity_candidate_triage.py,
  utils/toolkit_final_blocker_classifier.py,
  utils/toolkit_homebrew_pdf_adapter.py, utils/toolkit_homebrew_upload_contract.py,
  utils/toolkit_narrative_enrichment_plan.py, utils/toolkit_normalization_fidelity.py,
  utils/toolkit_publication_gate_composer.py,
  utils/toolkit_report_agreement.py, utils/toolkit_source_extraction.py,
  utils/toolkit_source_fidelity_benchmark.py, utils/toolkit_source_graph_synthesis.py,
  utils/toolkit_source_manifest.py,
- web/extensions/toolkit_homebrew_fidelity_review.py,
  web/extensions/toolkit_homebrew_packet_builder.py,
  web/extensions/toolkit_homebrew_readiness_gate.py,
  web/extensions/toolkit_homebrew_rebuild_guard.py,
  web/extensions/toolkit_module_finisher.py

These are already provider-free or orchestrate the provider-backed helpers
listed above; they need no GPT-5 request-shape migration.

## 4. Search evidence

Repository search used to verify completeness (2026-08-03):

1. `rg -n "chat\\.completions\\.create" --glob "*.py"` (repo-wide) - 100+
   matches; used as the candidate superset.
2. `rg -n "completions\\.create|create_chat_client|get_chat_completion_params"`
   over utils/, core/generators/, scripts/, and web/ - enumerated every create
   call in the toolkit/spatial/classification area and adjacent candidates;
   the priority plus traced adjacent sites above matched.
3. `rg -n "get_chat_completion_params" --glob "*.py"` (repo-wide) - 87
   matches; confirms the helper is used by the priority reference, normalizer,
   ModuleBuilder generators, S1/C1, traced adjacent build/publication
   sites A1/A2/A4/A7/A9, and the Markdown writer M1-M3 since task 3.1.
   Excluded runtime/interactive candidates remain direct.
4. `rg -n "top_p" --glob "*.py"` - no `top_p` in any in-scope file (only
   out-of-scope runtime compression files).
5. Source-contract test `scripts/test_build_call_site_inventory.py`
   (provider-free): asserts the exact create-call line set per priority file,
   helper routing for migrated adjacent sites, explicit exclusion of runtime/
   interactive candidates, and no `top_p` in priority files.

Exact isolated priority count: 23 real call statements, all helper-routed:
normalizer N1-N5 since task 2.1, ModuleBuilder B1-B3 and generators G1-G10
since task 2.2, S1/C1 since task 2.3, and M1-M3 Markdown since task 3.1.
R1 belongs to the later adaptation work and is deferred/external to this
clean baseline.

Notable exclusions (explicitly not build-path, intentionally omitted from
the priority inventory): main.py / action_handler.py / combat_manager.py
(runtime narrator+combat; already covered by the GPT-5 runtime contract),
update_encounter.py / plot_update.py (already helper-routed), compression
and memory modules, validation modules, startup_wizard.py,
quest_player_formatter.py, reconcile_location_state.py,
character_creation_audit.py, bestiary_updater.py, level_up.py,
action_predictor.py, api_logger.py, prompt_sanitizer.py, update_character_info.py.
