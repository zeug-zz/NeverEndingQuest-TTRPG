# Tasks: Phase 2 LLM-Assisted Narrative Classification

## 1. Foundation — Classification Engine

- [x] 1.1 Create `web/extensions/toolkit_llm_classification.py` with module docstring, imports, and `ENABLE_LLM_CLASSIFICATION` feature-flag read from `model_config.py`.
- [x] 1.2 Add `ENABLE_LLM_CLASSIFICATION = True` constant to `model_config.py` with docstring explaining it gates advisory LLM classification in the toolkit build path.
- [x] 1.3 Implement `ClassificationCache` class: load/save `modules/<slug>/llm_classification_cache.json`, content-hash keys via `sha256(authored_text)`, `get()` and `set()` with module-slug-scoped namespacing, fail-open on missing/malformed cache files.
- [x] 1.4 Implement `build_entity_classification_batch(ambiguous_entities, area_contexts) -> List[Dict]` — collects entity name + surrounding prose + room context for each ambiguous entity into a batch payload.
- [x] 1.5 Implement `build_destination_classification_batch(ambiguous_phrases, area_contexts) -> List[Dict]` — collects unresolved destination phrases + surrounding prose + room context.
- [x] 1.6 Implement `build_npc_visibility_batch(ambiguous_npcs, area_contexts) -> List[Dict]` — collects NPC mentions with unclear visibility + surrounding prose.

### Validation Gate 1
- [x] `python3 -m py_compile web/extensions/toolkit_llm_classification.py` passes
- [x] `python3 -m py_compile model_config.py` passes
- [x] `ClassificationCache` loads/saves/retrieves correctly in temp-dir test

## 2. LLM Classification Calls (DP1-3)

- [x] 2.1 Implement `call_llm_classify_entities(batch) -> Dict[str, str]` — sends entity batch to LLM, returns `{entity_name: label}` mapping. System prompt: "You classify ambiguous adventure entities into three categories: combatant (real monster), scene_illusion (illusion/dressing), narrator_flavor (prose-only). Return JSON: {\"classifications\": {\"entity_name\": \"label\", ...}}."
- [x] 2.2 Implement `call_llm_classify_destinations(batch) -> Dict[str, str]` — sends destination batch to LLM. System prompt for `canonical_alias` / `quest_objective` / `evocative_prose`.
- [x] 2.3 Implement `call_llm_classify_npc_visibility(batch) -> Dict[str, str]` — sends NPC batch to LLM. System prompt for `visible` / `hidden_reveal` / `lore_only`.
- [x] 2.4 Implement shared `_validate_classification_labels(raw_labels, allowed_enum, default_label) -> Dict[str, str]` — validates every LLM label against allowed enum, falls back unknown labels to `default_label`, logs warnings for each fallback.
- [x] 2.5 Implement shared `_call_llm_with_fallback(system_prompt, user_prompt, response_format="json_object") -> Optional[Dict]` — wraps `create_chat_client(use_fallback=True)`, `get_model_config("dm_validation", DM_VALIDATION_MODEL)`, fail-open on any exception, structured output via `response_format`.
- [x] 2.6 Wire cache check before each LLM call: `ClassificationCache.get()` → if hit, skip LLM call; if miss, call LLM and `ClassificationCache.set()`.

### Validation Gate 2
- [x] LLM calls return valid JSON with correct enum keys
- [x] `_validate_classification_labels` rejects "ghost_type" (invalid) → default
- [x] Cache hit avoids LLM call; cache miss triggers call
- [x] API failure returns `None` → caller uses defaults
- [x] `python3 -m py_compile web/extensions/toolkit_llm_classification.py` passes

## 3. Ambiguity Detection (Deterministic Pre-Filter)

- [x] 3.1 Implement `detect_ambiguous_entities(module_dir) -> List[Dict]` — scans monster references in area files, excludes bestiary-matched entries, excludes BU-file references, returns only entities that failed bestiary lookup with surrounding prose context.
- [x] 3.2 Implement `detect_ambiguous_destinations(module_dir) -> List[Dict]` — scans destination phrases from semantic authority extraction, excludes phrases that resolve to known area IDs or aliases, returns unresolved phrases with context.
- [x] 3.3 Implement `detect_ambiguous_npc_visibility(module_dir) -> List[Dict]` — scans NPC mentions from area descriptions, excludes NPCs with explicit `visible_location_ids` or `reveal_authority`, returns mentions with ambiguous visibility and context.
- [x] 3.4 Implement `run_llm_classification_pass(module_dir) -> Dict` — orchestrator that: (a) runs all three detectors, (b) checks cache for each domain, (c) calls LLM for uncached batches, (d) validates labels, (e) returns structured classification results.

### Validation Gate 3
- [x] Known bestiary match ("wight") is excluded from entity ambiguity
- [x] Known area alias ("Inner Sanctum") is excluded from destination ambiguity
- [x] Explicitly visible NPC ("Thalen stands behind the bar") is excluded from visibility ambiguity
- [x] Unknown entity ("spectral servants") is included in ambiguity batch
- [x] `python3 -m py_compile web/extensions/toolkit_llm_classification.py` passes

## 4. Classification Apply (Python Gatekeeper)

- [x] 4.1 Implement `apply_entity_classifications(module_dir, classifications) -> Dict` — for each classified entity: `combatant` → no-op (already in monsters), `scene_illusion` → emit `sceneEntity` metadata in area file (additive, never removes from prose), `narrator_flavor` → remove from monsters[] if present, add `_reclassified: true` annotation.
- [x] 4.2 Implement `apply_destination_classifications(module_dir, classifications) -> Dict` — for each classified phrase: `canonical_alias` → add to location `aliases` array (deduped), `quest_objective` → no-op (stays in plot), `evocative_prose` → no-op (already prose-only). Regenerate semantic authority after apply.
- [x] 4.3 Implement `apply_npc_visibility_classifications(module_dir, classifications) -> Dict` — for each classified NPC: `visible` → populate `visible_location_ids`, `hidden_reveal` → populate `reveal_authority`, `lore_only` → no-op.
- [x] 4.4 Implement `persist_classification_metadata(module_dir, classifications)` — records provenance on every applied change (`provenance: "llm_classification"`, `classified_by: model_name`, `classified_at: ISO timestamp`).

### Validation Gate 4
- [x] `combatant` classification leaves entity in monsters[] unchanged
- [x] `scene_illusion` adds sceneEntity metadata without removing from prose
- [x] `narrator_flavor` removes from monsters[], annotates with `_reclassified`
- [x] `canonical_alias` adds to aliases[], deduped with existing aliases
- [x] `visible` populates `visible_location_ids` on NPC
- [x] Provenance metadata present on all applied transforms
- [x] `_BU` files never modified — changes only to live runtime files

## 5. Remdiation Proposals (DP4)

- [x] 5.1 Implement `build_remediation_proposal_batch(module_dir, blocker_report) -> List[Dict]` — converts publishability blocker classes into a structured prompt context (blocker type, affected entities/locations, validation error text).
- [x] 5.2 Implement `call_llm_remediation_proposals(batch) -> List[Dict]` — sends blocker context to LLM, returns list of proposals with `{transform_type, target, description, rationale}`. System prompt: "You propose concrete fixes for module publishability blockers. Available transform types: move_entity_to_scene_entity, add_canonical_alias, add_npc_visibility, suppress_from_monsters, suppress_from_travel_map, set_npc_reveal_authority."
- [x] 5.3 Implement `validate_remediation_proposals(module_dir, proposals) -> List[Dict]` — filters proposals through whitelist check + target-exists check + schema-safety check + no-BU-modification check. Returns only safe proposals with `safety: "pass"` or `safety: "warning:<reason>"`.
- [x] 5.4 Implement `apply_accepted_proposals(module_dir, accepted_proposals) -> Dict` — applies transforms that passed validation AND were accepted by the human author. Records provenance. Writes via atomic `safe_write_json()`.

### Validation Gate 5
- [x] Whitelisted transform (`move_entity_to_scene_entity`) passes validation
- [x] Unwhitelisted transform (`rewrite_location_description`) is rejected with warning
- [x] Transform targeting nonexistent entity is filtered out (safety: "fail:target_missing")
- [x] Only accepted proposals are applied — rejected ones leave no data changes

## 6. Finisher Integration

- [x] 6.1 Add `run_llm_classification_pass()` call to `toolkit_module_finisher.py` after deterministic enrichment but before publishability audit, guarded by `ENABLE_LLM_CLASSIFICATION` check.
- [x] 6.2 Store classification results in `toolkit_build_report.json` under `llm_classification` key with per-domain summaries (entity_count, destination_count, npc_count, classified_by, cache_hits).
- [x] 6.3 After classification apply, trigger publishability re-audit to capture the effect of applied transforms.
- [x] 6.4 After publishability re-audit, invoke `call_llm_remediation_proposals()` for residual blockers, store proposals in build report under `llm_remediation_proposals`.
- [x] 6.5 All classification and remediation steps SHALL be fail-open: any failure degrades gracefully with warnings, never blocks module build.

### Validation Gate 6
- [x] Finisher integration compiles without errors
- [x] `ENABLE_LLM_CLASSIFICATION=False` bypasses all LLM calls (deterministic-only path preserved)
- [x] `ENABLE_LLM_CLASSIFICATION=True` invokes classification in correct sequence
- [x] Classification results appear in `toolkit_build_report.json`
- [x] API failure produces build report with `llm_classification.status: "degraded"` and build still succeeds

## 7. GUI Review Panel

- [x] 7.1 Add classification review section to `web/templates/module_toolkit.html` — rendered only when `build_report.llm_classification` exists and `ENABLE_LLM_CLASSIFICATION=True`.
- [x] 7.2 Display entity classification results in a table: entity name, classified label (color-coded: green=combatant, blue=scene_illusion, gray=narrator_flavor), confidence (if LLM provides), accept/reject per-item toggle (default: accept all).
- [x] 7.3 Display destination classification results: phrase, label, per-item accept/reject.
- [x] 7.4 Display NPC visibility classification results: NPC name, label, per-item accept/reject.
- [x] 7.5 Add remediation proposals panel: list of proposals with transform type (human-readable), target, description, rationale, safety validation result, accept/reject buttons.
- [x] 7.6 Add "Apply Accepted" button that POSTs accepted classifications and proposals to a new route `POST /api/toolkit/apply_llm_classification`.
- [x] 7.7 Implement `POST /api/toolkit/apply_llm_classification` in `web/routes/toolkit_homebrew_routes.py` — receives accepted classifications and proposals, calls apply functions, returns updated build report with applied counts.

### Validation Gate 7
- [x] GUI panel renders only when classification data exists
- [x] Color-coded labels visually distinguish entity categories
- [x] Accept/reject toggles work per-item
- [x] "Apply Accepted" triggers POST, response shows applied counts
- [x] Rejected items do NOT modify module data
- [x] `node --check` on any modified JS (if inline in HTML, extract and validate)

## 8. Regression Coverage

- [x] 8.1 Add `scripts/test_phase2_llm_classification.py` with test fixtures for classification engine, ambiguity detection, label validation, cache behavior, and finisher integration.
- [x] 8.2 Test: bestiary-known entities bypass classification (no LLM call).
- [x] 8.3 Test: ambiguous entities trigger classification batch with correct context.
- [x] 8.4 Test: `_validate_classification_labels` rejects invalid labels and falls back to defaults.
- [x] 8.5 Test: cache hit returns stored classification without LLM call; cache miss triggers call.
- [x] 8.6 Test: API failure returns `None` and caller degrades to defaults without exception.
- [x] 8.7 Test: `combatant` entities pass readiness; `scene_illusion` entities do NOT trigger monster requirements.
- [x] 8.8 Test: `canonical_alias` adds to aliases; `evocative_prose` excluded from travel maps.
- [x] 8.9 Test: `visible` populates visibility arrays; `lore_only` excluded from probe checks.
- [x] 8.10 Test: whitelisted transforms pass validation; unwhitelisted transforms are rejected.
- [x] 8.11 Test: transform targeting nonexistent entity is filtered out with safety warning.
- [x] 8.12 Test: `ENABLE_LLM_CLASSIFICATION=False` bypasses all classification — build output identical to pre-Phase-2.
- [x] 8.13 Test: provenance metadata recorded on all applied transforms.

### Validation Gate 8
- [x] All regression tests pass: `python3 scripts/test_phase2_llm_classification.py`
- [x] Test coverage includes: positive, negative, fail-open, cache, and flag-gate scenarios
- [x] No tests depend on live LLM API (all LLM calls mocked or skipped)

## 9. Documentation

- [x] 9.1 Update `plans/module-uploader-2.md` — mark Phase 2 steps 19-21 as implemented, add Phase 2 implementation summary to "Recent Changes" section, update completion status.
- [x] 9.2 Update `AGENTS.md` — add Phase 2 LLM classification to "Recent Changes" summary with feature description, files created/modified, and verification results.
- [x] 9.3 Add `model_config.py` comment block documenting `ENABLE_LLM_CLASSIFICATION` purpose, scope, and rollback procedure.
- [x] 9.4 Add module docstring to `web/extensions/toolkit_llm_classification.py` documenting architecture, flow, and fail-open contracts.
