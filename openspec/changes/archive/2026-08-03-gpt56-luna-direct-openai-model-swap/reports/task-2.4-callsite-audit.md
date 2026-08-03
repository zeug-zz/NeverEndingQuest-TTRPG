# Task 2.4 Direct-OpenAI Callsite Audit for gpt-5.6-luna

Timestamp (UTC): 2026-08-03T04:20:00Z
Change: gpt56-luna-direct-openai-model-swap
Task: 2.4 Audit direct-OpenAI call sites using the changed constants; minimally route only blocking GPT-5.6 calls through the shared helper, preserving non-GPT-5 temperature behavior and leaving unrelated low-traffic migration work deferred.

## 1. Method

- Scanned all Python Chat Completions call sites (`chat.completions.create`) across the repository.
- For each site, statically resolved the model source: direct `model_config`/`config` constant (now `gpt-5.6-luna` after task 1.2), `get_chat_model_name()` (returns `DM_MAIN_MODEL` = `gpt-5.6-luna` on the direct-OpenAI path), or `get_model_config(task, MODEL)` (returns the changed constant on the non-OpenRouter path).
- Flagged legacy GPT-5-incompatible sampling fields: `temperature=` or `top_p=` passed to the request without the shared `get_chat_completion_params()` helper.
- Classified each flagged site as active high-value runtime path vs. lower-traffic/toolkit path.
- Decision rule applied: edit only if static evidence shows (a) active high-value path, (b) model resolves from the changed GPT-5 constants, (c) legacy fields present without helper, (d) the helper swap preserves both the direct-OpenAI and existing OpenRouter request shapes exactly. Otherwise document as deferred rather than guess.

No live provider/API calls were made. All checks are provider-free source inspection plus `.venv/bin/python` assertions against the shared helper.

## 2. Inventory (flagged sites: changed GPT-5 constant + legacy sampling field, no helper)

| # | File : callsite | Model source | Legacy fields | Helper used | Active-path classification | Action |
|---|---|---|---|---|---|---|
| 1 | `updates/update_encounter.py:487` | `get_model_config("encounter_update", ENCOUNTER_UPDATE_MODEL)` -> `gpt-5.6-luna` (direct) | `temperature=0.7` | No | HIGH - encounter updates during live combat (`combat_manager.py:5283`, `action_handler.py:2827`) | **FIXED** - routed through `get_chat_completion_params("encounter_update", ..., temperature_override=0.7)` |
| 2 | `updates/plot_update.py:207` | `get_model_config("plot_update", PLOT_UPDATE_MODEL)` -> `gpt-5.6-luna` (direct) | `temperature=0.7` | No | HIGH - plot updates during live play (`main.py:111`, `action_handler.py`) | **FIXED** - routed through `get_chat_completion_params("plot_update", ..., temperature_override=0.7)` |
| 3 | `core/ai/transition_validator.py:153,166` | `get_chat_model_name()` / `TRANSITION_VALIDATOR_MODEL` -> `gpt-5.6-luna` (direct) | `temperature=0.3` | No | HIGH - travel/transition validation on every location change | Deferred - OpenRouter branch currently sends model + temperature with NO `extra_body`/`thinking`; helper swap would change the OpenRouter request shape (adds `thinking` extra_body). Not safe to change without live OpenRouter validation; deferred per decision rule. |
| 4 | `updates/update_character_info.py:2668` | `get_model_for_character()` -> `get_chat_model_name()` / `NPC_INFO_UPDATE_MODEL` = `gpt-5.6-luna` | `temperature=0.7` | No | HIGH - AI character updates during live play/combat | Deferred - same OpenRouter-shape constraint as #3 (no `extra_body` today); helper swap would alter the OpenRouter request. Also touches the module-level `client` fallback path (line 3154) so the fix is not single-call-site. |
| 5 | `core/ai/incremental_compression.py:188` | `self.COMPRESSION_MODEL = get_chat_model_name()` -> `gpt-5.6-luna` | `temperature=0.3` | No | MEDIUM - location compression when context grows | Deferred - lower-traffic background compression; OR shape would change (no `extra_body` today). |
| 6 | `core/ai/combat_compression_engine.py:153` | `self.model = NARRATIVE_COMPRESSION_MODEL` -> `gpt-5.6-luna` | `temperature=0.3` | No | MEDIUM - combat history compression | Deferred - lower-traffic; OR shape would change. |
| 7 | `utils/compression/ai_narrative_compressor_agentic.py:230` | `NARRATIVE_COMPRESSION_MODEL` -> `gpt-5.6-luna` | `temperature=0.1`, `top_p=1` | No | LOW-MEDIUM - agentic narrative compressor | Deferred - lower-traffic; helper swap would change OR shape and legacy `top_p` semantics. |
| 8 | `utils/compression/location_compressor.py:138` | `LOCATION_COMPRESSION_MODEL` -> `gpt-5.6-luna` | `temperature=0.1` | No | MEDIUM - location data compression | Deferred - lower-traffic; OR shape would change. |
| 9 | `core/ai/cumulative_summary.py:319,592` | `get_model_config("adventure_summary", ADVENTURE_SUMMARY_MODEL)` -> `gpt-5.6-luna` | `temperature=0.8` | No | MEDIUM - session/adventure summaries | Deferred - lower-traffic summary path; pre-existing `extra_body` pass-through exists but summary paths are explicitly out of the minimal correction scope. |
| 10 | `core/ai/adv_summary.py:237,473` | `get_model_config("adventure_summary", ADVENTURE_SUMMARY_MODEL)` -> `gpt-5.6-luna` | `temperature=0.8` | No | MEDIUM - adventure summary generation | Deferred - same as #9. |
| 11 | `core/memory/session_diary.py:887,918,1508,1539` | `DM_SUMMARIZATION_MODEL` -> `gpt-5.6-luna` | `temperature=...` | No | MEDIUM-LOW - diary checkpoints | Deferred - lower-traffic diary path. |
| 12 | `core/memory/players_diary.py:309,346` | `DM_SUMMARIZATION_MODEL` -> `gpt-5.6-luna` | `temperature=...` | No | MEDIUM-LOW - players diary | Deferred - lower-traffic. |
| 13 | `core/memory/story_so_far_compiler.py:272,307` | `DM_SUMMARIZATION_MODEL` -> `gpt-5.6-luna` | `temperature=...` | No | LOW - story-so-far PDF | Deferred - lower-traffic. |
| 14 | `core/managers/campaign_manager.py:541,567` | `DM_SUMMARIZATION_MODEL`/`DM_SUMMARY_MODEL` -> `gpt-5.6-luna` | `temperature=0.6/0.3` | No | LOW - module summaries | Deferred - lower-traffic. |
| 15 | `web/web_interface.py:2529,4761` | `get_chat_model_name()` / `DM_MINI_MODEL` -> `gpt-5.6-luna` | `temperature=0.7/0.8` | No | LOW - toolkit/admin web endpoints | Deferred - toolkit; OR shape would change. |
| 16 | `web/web_interface.py:6025` | `get_model_config("npc_builder")` -> direct fallback `gpt-4.1-2025-04-14` (no original model passed) | `temperature=0.7` | No | LOW - toolkit MMG description gen | Out of scope - does not resolve from the changed GPT-5 constants on the direct path (uses fallback model). |
| 17 | `utils/prompt_sanitizer.py:33` | `DM_MINI_MODEL` -> `gpt-5.6-luna` | `temperature=0.3` | No | LOW - DALL-E failure recovery | Deferred - rare failure-only path; direct `OpenAI()` client (not factory) also needs `create_chat_client()`; unrelated migration. |
| 18 | Toolkit builders/validators (`core/generators/*`, `core/validation/*`, `utils/toolkit_*`, `utils/startup_wizard.py`, `utils/level_up.py`, `core/managers/level_up_manager.py`, `core/managers/storage_processor.py`, `core/managers/initiative_tracker_ai.py`, `utils/action_predictor.py`, `utils/npc_*`, `utils/bestiary_updater.py`, `utils/quest_player_formatter.py`, `utils/spatial_contract.py`, `utils/character_creation_audit.py`, `utils/reconcile_location_state.py`, `utils/npc_reconciler.py`, `web/extensions/toolkit_llm_classification.py`, `utils/toolkit_llm_final_reconciliation.py`, `utils/homebrewery_adventure_writer.py`, `updates/update_character_effects.py`) | changed constants via `get_model_config()`/direct import | `temperature=...` (some `max_tokens`) | No | LOW - offline module/toolkit creation, validation, level-up, bestiary, startup | Deferred - explicitly out of scope ("unrelated low-traffic migration work deferred"). |

## 3. Call sites already on the shared helper (no action needed)

All main-narrator, combat, and action-handler hot paths already use `get_chat_completion_params()` and were verified in tasks 2.1/2.2:

- `main.py:432, 539, 2938, 3653, 3674, 5345, 5367, 5411, 5434` - narrator/validation/summary helper usage
- `core/managers/combat_manager.py:1418, 1851, 2786, 3428, 3456, 3607, 4883, 4901, 4920` - combat validation/main/retry helper usage (incl. `retry_tier="high"` at 4885-4888)
- `core/ai/action_handler.py:1179, 1198, 2359, 2378, 4753, 4772` - narrator/validation helper usage

These send no legacy `temperature`/`top_p` for GPT-5-family models and are not re-audited beyond the earlier task reports.

## 4. Runtime corrections applied (minimal, helper-routed)

### 4.1 `updates/update_encounter.py`

- Import changed: `get_model_config` -> `get_chat_completion_params` (line 25).
- Call site (line ~487): replaced
  `model=config["model"], **config.get("extra_body", {}), temperature=TEMPERATURE`
  with
  `**get_chat_completion_params("encounter_update", ENCOUNTER_UPDATE_MODEL, temperature_override=TEMPERATURE)`.

### 4.2 `updates/plot_update.py`

- Import changed: `get_model_config` -> `get_chat_completion_params` (line 24).
- Call site (line ~207): replaced the same `get_model_config` + `temperature` construction with
  `**get_chat_completion_params("plot_update", PLOT_UPDATE_MODEL, temperature_override=TEMPERATURE)`.

### Why these two and only these two

1. Active high-value runtime paths: encounter updates run during live combat; plot updates run during live play. Both are exercised by the normal game loop (not toolkit/offline).
2. Model statically resolves to `gpt-5.6-luna` on the direct-OpenAI path from the changed constants.
3. Both previously sent `temperature=0.7` without the helper - a blocking violation of the GPT-5 request contract (GPT-5-family requires `reasoning_effort`/`verbosity`, no legacy sampling).
4. Both already passed `**config.get("extra_body", {})` on the OpenRouter branch, so the helper swap reproduces the pre-existing OpenRouter request shape exactly (verified provider-free below). Non-GPT-5 direct temperature behavior is preserved via `temperature_override`.

## 5. Provider-free verification

Commands (`.venv/bin/python`, no credentials, no provider calls):

```bash
.venv/bin/python -m py_compile updates/update_encounter.py updates/plot_update.py
```

Result: `COMPILE PASS`

```bash
.venv/bin/python -c "from utils.ai_client_factory import get_chat_completion_params; ... assertions ..."
```

Results:

```
DIRECT GPT-5.6 OK: {'model': 'gpt-5.6-luna', 'reasoning_effort': 'medium', 'verbosity': 'medium'}
DIRECT NON-GPT-5 OK: {'model': 'gpt-4.1-2025-04-14', 'temperature': 0.7}
OPENROUTER SHAPE OK: {'model': 'moonshotai/kimi-k2.5', 'temperature': 0.7, 'thinking': {'type': 'disabled'}}
ALL BRANCH ASSERTIONS PASS
```

- Direct OpenAI GPT-5.6 branch: `model=gpt-5.6-luna` + `reasoning_effort`/`verbosity`; no `temperature`, no `top_p`.
- Direct OpenAI non-GPT-5 branch: `temperature` preserved via `temperature_override`.
- OpenRouter branch: identical to the pre-edit shape for both edited call sites (verified `pre == post` for `encounter_update` and `plot_update`).

```
OR SHAPE IDENTICAL encounter_update: {'model': 'moonshotai/kimi-k2.5', 'temperature': 0.7, 'thinking': {'type': 'disabled'}}
OR SHAPE IDENTICAL plot_update: {'model': 'moonshotai/kimi-k2.5', 'temperature': 0.7, 'thinking': {'type': 'disabled'}}
PASS
```

No remaining `get_model_config` references in either edited file.

## 6. Deferred items (documented, not guessed)

- `core/ai/transition_validator.py` and `updates/update_character_info.py` remain on legacy `temperature` for GPT-5 on the direct path. Both are active high-value paths, but their current OpenRouter requests send model + temperature with NO `thinking`/`extra_body`. Routing them through the helper would change the OpenRouter request shape (adds `thinking`), which the change scope forbids modifying without live OpenRouter verification. Deferred to a follow-up that either provider-branches the call or validates the OR shape change live.
- All compression, summary, diary, toolkit, validator, and offline builder sites remain unchanged (low-traffic migration work, explicitly out of scope for this change).
- `web/web_interface.py:6025` is out of scope because it does not resolve from the changed GPT-5 constants on the direct path.
- Live blocking proof (provider rejection of `temperature` with `gpt-5.6-luna`) remains a task 4.x smoke item; the deferred direct-path sites should be re-checked after the live smoke if Luna rejects legacy sampling.

## 7. Conclusion

Task 2.4 audit complete. Two blocking high-value direct-OpenAI GPT-5.6 call sites (`updates/update_encounter.py`, `updates/plot_update.py`) were minimally routed through the existing shared helper, preserving non-GPT-5 temperature behavior and the existing OpenRouter request shape. All other flagged sites are documented as deferred with rationale; no broad migration, no `model_config.py`/display/prompt/OpenRouter changes, no test-file changes (deferred to task 3.x), and no live provider calls were made.
