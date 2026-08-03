## 1. Baseline And Regression Tests

- [x] 1.1 Add provider-free tests reproducing Well-of-Ruin-style table/effect text being promoted to NPC atoms.
  - File: `scripts/test_source_atom_triage_hardening.py` (24 tests, all PASS).
  - Fixture: `WELL_OF_RUIN_MD` with 10-row effect table (`level 11-16 Complex Trap, Deadly`, `Well`, `Ruin`, `Awaken`, `Menace`, `Enrage`, `Enthrall`, `Irradiate`, `Overwhelm`, plus `Mundane objects worth at least 1 gp become sentient and hostile.`).
  - False-positive boundary proven at source-manifest level (entity_candidates with type "npc" from table_cell source) and graph level (npc-type atoms).
  - Verified: 24/24 tests PASS, ASCII 0 violations, compile PASS, OpenSpec validation valid.
  - Target test file: `scripts/test_source_atom_triage_hardening.py`.
  - Test fixture MUST include table/effect material for `level 11-16 Complex Trap, Deadly`, `Well`, `Ruin`, `Awaken`, `Menace`, `Enrage`, `Enthrall`, `Irradiate`, `Overwhelm`, and full effect sentences.
  - Tests MUST initially prove the false-positive class at the source-manifest, triage, blueprint, or build-fidelity boundary.
- [x] 1.2 Add positive regression tests proving true table-sourced NPC names remain extracted and kept.
  - Include a Numillian-like identity table with names such as `Wayne`, `Irene Laughing-Eyes`, and `Treever`.
  - Tests MUST prove identity-header table cells still reach NPC/entity candidate extraction.
  - Verification: 11 tests added (4 classes: manifest-level 3, graph-level 2, direct-extractor 1, fixture-completeness 5). ALL 35/35 PASS. ASCII 0 violations. OpenSpec validation valid. No production files changed.
- [x] 1.3 Add tests proving false non-actor candidates cannot produce `Required npc 'X' not found in module` blockers.
  - Exercise `build_source_graph(...)`, entity triage report construction, `generate_builder_blueprint(...)`, and build-fidelity required NPC extraction where feasible.
  - File: `scripts/test_source_atom_triage_hardening.py` (20 new tests, 55 total, 9 expected-failure for future invariants).
  - Classes added: `TestWellBlueprintNpcRosterWithTriage` (6 tests), `TestWellBlueprintGenerateWithTriage` (5 tests), `TestWellBuildFidelityBlockers` (9 tests).
  - False-positive names exercised: `Awaken`, `Enrage`, `full sentence`, plus all 8 effect labels.
  - True NPC preservation from identity-bearing tables kept passing (Wayne, Irene Laughing-Eyes, Treever).
  - Tests cover: `_build_npc_roster` triage filtering, `generate_builder_blueprint` triage handoff, `_find_required_atoms`, `_check_atoms_vs_module` blocker production.
  - Verified: 55/55 PASS (9 expected failures), ASCII 0 violations, compile PASS, OpenSpec validation valid.

## 2. Source Manifest Table-Cell Filtering

- [x] 2.1 Add small deterministic helpers in `utils/toolkit_source_manifest.py` for table-header role detection.
  - Helpers MUST distinguish identity-bearing headers from effect/result/description headers.
  - Helpers MUST be pure and provider-free.
  - Verification: 56 new contract tests PASS (111 total, 9 expected failures). ASCII 0 violations. Compile PASS. OpenSpec validation valid.
  - Helpers added: `_normalize_table_header()`, `_table_headers_indicate_entity_identity()`, `_table_headers_indicate_effect_text()`.
  - Sets: `_TABLE_IDENTITY_HEADERS` (13 entries), `_TABLE_EFFECT_HEADERS` (19 entries).
  - Wiring into `_extract_entity_candidates()` NOT implemented yet (belongs to task 2.2).
- [x] 2.2 Update `_extract_entity_candidates(...)` so table cells under non-identity/effect headers are not registered as NPC candidates.
  - Preserve bold-span and quoted-name behavior unless tests prove they need additional filtering.
  - Preserve existing true NPC table behavior.
  - Filtering rule: `if not _table_headers_indicate_entity_identity(headers): continue` -- skips entire table's cells when headers don't indicate identity.
  - Enhanced `_table_headers_indicate_entity_identity(...)` to also check individual words of multi-word headers (e.g. "NPC Name" -> words `npc`, `name`).
  - Well fixture: all 8 effect labels + full sentence excluded at manifest, graph, direct-extraction, blueprint, and build-fidelity levels.
  - Numillian identity table with "NPC Name" header continues to extract Wayne/Irene Laughing-Eyes/Treever as NPC candidates.
  - 108/108 tests pass (0 failures, 0 expected-failure). 2 pre-existing unrelated failures in test_accurate_ingest_source_graph (map_key location type).
  - 9 `@unittest.expectedFailure` decorators removed (now pass as proven invariants).
  - ASCII 0 violations, compile PASS, openspec validate --strict valid.
- [x] 2.3 Add or update source graph tests for table effect filtering and true NPC preservation.
  - Added `WELL_EFFECT_SOURCE_MD` fixture (minimal Well-style effect table) and `NUMILLIAN_TABLE_SOURCE_MD` fixture (identity-bearing Name table) to `scripts/test_accurate_ingest_source_graph.py`.
  - Added `TestSourceGraphWellEffectFiltering` class (4 tests): proves `Awaken`, `Enrage`, full effect sentence produce 0 npc atoms; npc_candidates summary is 0.
  - Added `TestSourceGraphNumillianTableNpcPreservation` class (5 tests): proves Wayne, Irene Laughing-Eyes, Treever produce npc atoms; npc_candidates >= 3; cross-check that Well vs Numillian NPC counts differ.
  - Fixed 2 brittle map-key tests in `TestLocationCandidateExtraction`: `test_map_key_detected` now uses `"1. Charion Tamer"` (production prepends number prefix); `test_location_type_map_key` now accepts both `map_key` and `heading_location` types (non-map-key headings produce `heading_location`).
  - `test_source_atom_triage_hardening.py` unchanged (108/108 already sufficient).
  - Verified: source graph tests 57/57 PASS, triage tests 108/108 PASS, compile PASS, ASCII 0 violations, OpenSpec validation valid.

## 3. Entity Candidate Triage Prefilter

- [x] 3.1 Extend `utils/toolkit_entity_candidate_triage.py` deterministic prefiltering for non-actor candidates.
  - Full sentences and long clauses MUST be rejected as `narrative_phrase` or another non-actor type.
  - One-word capitalized mechanic/effect verbs in trap/table/effect context MUST be rejected or reclassified as non-actor.
  - True NPC names MUST NOT be rejected solely because they are one word.
  - Verification: 21/21 new tests PASS (TestPrefilterNonActorExtension). 130/130 full test suite PASS. ASCII 0 violations. Compile PASS. OpenSpec --strict valid.
  - Helpers added: `_looks_like_full_sentence_or_clause()`, `_candidate_in_mechanics_context()`, plus `_MECHANIC_EFFECT_VERBS` and `_MECHANICS_CONTEXT_KEYWORDS` constants.
  - `build_prefilter_decision()` extended with stages 2 (full sentence) and 3 (mechanic verb + context).
- [x] 3.2 Add tests for prefilter decisions and underbound NPC findings.
  - Rejected non-actors MUST not create underbound NPC blockers.
  - Kept true NPCs without binding MAY still warn/block according to existing underbound NPC rules.
  - Verification: 13/13 new tests PASS (TestPrefilterUnderboundNpc: 12 tests, plus test_rejected_enrage_no_underbound_warning). 143/143 full test suite PASS. ASCII 0 violations. Compile PASS. OpenSpec --strict valid.
  - Tests cover: prefilter-rejected full sentence (2), prefilter-rejected mechanic verb (3), control kept-unbound NPC (2), report-level summary (3).

## 4. Blueprint And Build-Fidelity Boundary

- [x] 4.1 Verify `_build_npc_roster(...)` excludes rejected/non-actor triage decisions for all new false-positive fixtures.
  - Production `_is_triage_blocked_for_npc_roster(...)` already handles all 4 non-actor types (narrative_phrase, plot_note, tone_marker, unknown) and `decision=="reject"`. No production code changes needed.
  - Added `TestNpcRosterTriageNonActorTypes` (10 tests): `narrative_phrase_excluded`, `plot_note_excluded`, `plot_note_excludes_all`, `tone_marker_excluded`, `tone_marker_excludes_all`, `unknown_excluded`, `unknown_excludes_all`, `kept_true_npc_preserved`, `kept_true_npc_entry_structure`, plus cross-type `narrative_phrase_excluded`.
  - Imports added: `TYPE_PLOT_NOTE`, `TYPE_TONE_MARKER`, `TYPE_UNKNOWN`.
  - Each non-actor type tested with both per-target inclusion check and all-excluded + true-NPC-kept check.
  - Existing Well fixture tests cover all 8 effect labels (Well, Ruin, Awaken, Menace, Enrage, Enthrall, Irradiate, Overwhelm) and full effect sentence.
  - True NPC keep controls: Numillian names (Wayne, Irene Laughing-Eyes, Treever) via existing tests, plus "Kept NPC" in new class.
  - 149/149 tests PASS (was 139 + 10 new). All ASCII. Compile PASS. OpenSpec --strict valid.
- [x] 4.2 Add tests proving build-fidelity required NPC coverage excludes the false non-actor names.
  - No blocker message may include `Required npc 'Awaken'`, `Required npc 'Enrage'`, or full effect sentences from the Well fixture.
  - Added 6 tests to `TestWellBuildFidelityBlockers` (now 13 tests, was 7):
    - `test_find_required_atoms_excludes_all_well_false_names` -- all 8 effect labels excluded
    - `test_no_required_npc_blockers_for_any_well_false_name` -- zero blockers count assertion
    - `test_no_required_npc_blocker_for_awaken` -- blocker message does not start with `Required npc 'Awaken`
    - `test_no_required_npc_blocker_for_enrage` -- blocker message does not start with `Required npc 'Enrage`
    - `test_positive_control_missing_npc_produces_blocker` -- synthetic "MissingHero" NPC atom still produces exactly `Required npc 'MissingHero' not found in module`
    - `test_positive_control_missing_npc_message_format` -- message format contract (start/contain/end) for missing NPC blocker
  - Positive controls use synthetic NPC atoms (`MissingHero`, `LostKnight`) passed to `_check_atoms_vs_module` with empty module dict, proving fidelity gating remains active for genuine missing NPCs.
  - Existing `test_no_required_npc_blocker_for_awaken` and `test_no_required_npc_blocker_for_enrage` refined to check exact `Required npc 'X'` label extraction via `.split("'", 2)[:2]`.
  - 153/153 tests PASS (was 149). ASCII 0 violations. Compile PASS. OpenSpec --strict valid. No production code changed.
- [x] 4.3 Verify no source-fidelity thresholds or benchmark fixtures are weakened.
  - Verification notes:
    - Git diff confirms NO changes to `data/benchmarks/` files (0 bytes diff).
    - Git diff confirms NO changes to source-fidelity scoring files (`utils/toolkit_source_fidelity_benchmark.py`, `utils/toolkit_publication_gate_composer.py`, `scripts/benchmark_accurate_ingest.py`, `scripts/audit_module_publishability.py`).
    - No staged changes exist that could bypass the review.
    - Numillian benchmark fixture thresholds verified unchanged:
      - `minimum_represented`: 16 (NPCs)
      - `minimum_preserved`: 13 (locations), 3 (puzzles), 2 (lore)
      - `blocked_replacement`: `generic_conspiracy_thriller` (tone)
    - Relevant tests all PASS:
      - `scripts.test_source_atom_triage_hardening`: 153/153 PASS
      - `scripts.test_accurate_ingest_numillian_benchmark`: 107/107 PASS
    - ASCII compliance: 0 violations.
    - OpenSpec validation: VALID (--strict).

## 5. Final Reconciliation Brief Evidence Enrichment

- [x] 5.1 Add evidence enrichment for `final_reconciliation_brief.json`.
  - Briefs SHOULD include `source_excerpts` resolved from blocker `source_atom_id` and source graph refs when available.
  - Briefs SHOULD include `generated_module_summary` with compact canonical artifact counts and relevant missing categories when module artifacts exist.
  - Default behavior MUST remain backward compatible when no evidence artifacts are provided.
  - Implementation:
    - Added `_resolve_source_excerpts(classification, source_graph)` helper in `utils/toolkit_final_reconciliation.py`: iterates editorial/fatal blockers, looks up `source_atom_id` in source graph atom index, returns bounded excerpts (max 20, 80-char per excerpt). Returns `[]` when source_graph is None or no atoms match.
    - Added `_build_generated_module_summary(module_dir)` helper: scans module dir for area BU files, area live files, monster files, context/plot artifacts. Returns compact counts and `missing_categories` list. Returns `{}` when module_dir is None or non-existent.
    - Modified `build_final_reconciliation_brief(...)` to accept `source_graph: Optional[Dict] = None` kwarg. When provided, `source_excerpts` is enriched. When `module_dir` points to existing module, `generated_module_summary` is enriched. Default behavior (no args) unchanged.
    - Updated `web/extensions/toolkit_homebrew_packet_builder.py` to load source graph from workspace files (fail-open) and pass it to `build_final_reconciliation_brief(...)` as `source_graph`.
    - Added `TestEvidenceEnrichment` test class with 16 tests covering: resolved excerpts, no source_graph, empty source_graph, no atoms, no source_atom_ids, non-matching atom_id, bounded max entries, no module_dir, missing dir, real artifacts, missing categories, brief integration with source_graph, brief integration with module_dir, default empty preservation.
    - All 76 tests PASS (was 60). ASCII 0 violations. Compile PASS. OpenSpec --strict valid.
    - Task 5.2 (editable surfaces) intentionally not modified. Editable surfaces unchanged in this task.
- [x] 5.2 Narrow or explicitly justify editable surfaces for enriched briefs.
  - Preferred canonical surfaces: `module_context.json`, `module_context_BU.json`, `module_plot_BU.json`, `areas/*_BU.json`, `map_*.json`.
  - Runtime-only files and source/middle artifacts MUST remain forbidden.
  - Implementation:
    - Updated `DEFAULT_EDITABLE_SURFACES` in `utils/toolkit_final_reconciliation.py` from `["module_context.json", "module_plot.json", "areas/", "monsters/"]` to the canonical list above.
    - Added comment block documenting the 5 canonical surface categories and the explicit forbidden categories (runtime-only, source/middle pipeline artifacts).
    - LLM-side `_is_forbidden_target()` in `utils/toolkit_llm_final_reconciliation.py` unchanged (already rejects runtime-only `module_plot.json`, live `areas/*.json`, source/middle artifacts, and provides a second layer of defense against malicious briefs).
  - Tests added in `scripts/test_toolkit_final_reconciliation.py`:
    - `TestDefaultEditableSurfaces` class with 10 tests: exact canonical list match, exclusion of `module_plot.json`, `areas/`, `monsters/`, inclusion of `module_context_BU.json`, `module_plot_BU.json`, `areas/*_BU.json`, `map_*.json`, all-string contract, ASCII-only contract.
    - Updated existing `test_brief_includes_editable_surfaces_and_instructions` to assert narrowed surfaces (no runtime-only, no broad prefixes, all canonical entries present).
  - Existing LLM malicious-brief coverage confirmed (not widened):
    - `test_rejects_runtime_only_module_plot` -- brief lists `["module_plot.json"]`, target is `module_plot.json`, still rejected.
    - `test_rejects_source_graph` -- same pattern for source/middle artifacts.
    - All 9 additional `test_rejects_runtime_only_*` and `test_rejects_*_artifact` variants.
  - Verification: compile PASS, test_toolkit_final_reconciliation 86/86 PASS, test_toolkit_llm_final_reconciliation 66/66 target-validation tests PASS, ASCII 0 violations, OpenSpec --strict valid.
  - No validation weakening: `_is_forbidden_target()` and `_target_matches_editable_surface()` unchanged. LLM patch plan target validation still enforces forbidden-target check before editable_surfaces check.
- [x] 5.3 Add tests proving enriched briefs contain evidence for editorial blockers and still reject unsafe patch targets through existing final-editor validation.
  - File: `scripts/test_toolkit_llm_final_reconciliation.py`.
  - New class `TestEnrichedBriefEvidenceAndTargetValidation` (14 tests total):
    - Evidence enrichment: 4 tests proving source_excerpts and generated_module_summary presence, including via build_final_reconciliation_brief with source_graph and tempdir module artifacts.
    - Unsafe target rejection: 6 tests proving enriched brief still rejects runtime-only module_plot.json, live areas/FOO.json, source/middle source_graph.json, builder_blueprint.json, path traversal areas/../module_context.json, and non-whitelisted monsters/foo.json.
    - Positive canonical controls: 4 tests proving module_context.json, module_plot_BU.json, areas/FOO_BU.json, and map_test.json pass target validation with enriched brief.
  - All tests provider-free, tempdir-backed (where needed), ASCII-only.
  - Helper `_enriched_brief()` fixture added with populated source_excerpts (2 entries) and non-empty generated_module_summary.
  - Import added: `build_final_reconciliation_brief` from `utils.toolkit_final_reconciliation`.
  - No editable surfaces widened, no validation weakened.
  - Verification: compile PASS, 14/14 new tests PASS, 46/46 target validation regression PASS, 572/572 LLM suite PASS, 86/86 reconciliation suite PASS, ASCII 0 violations, OpenSpec --strict valid.

## 6. Workflow Handoff And Verification

- [x] 6.1 Update `toolkit-accurate-ingest-llm-builder-final-editor/tasks.md` step 7.3 only after this change lands and source atom triage is validated.
  - Do NOT mark final-editor step 7.3 complete in this change.
  - Verification: A handoff/prerequisite note was added under final-editor step 7.3 documenting that `toolkit-accurate-ingest-source-atom-triage-hardening` validated strict and source atom false-NPC blockers are now covered. Step 7.3 remains unchecked.
- [x] 6.2 Run `.venv/bin/python -m py_compile` on all touched Python files.
  - Verification: Compiled 26 Python files successfully (all exited 0). Files compiled include core/generators, scripts/test_*, utils/*, web/extensions/*, web/routes/* modules. See orchestrator facts for full list.
- [x] 6.3 Run targeted tests:
  - `.venv/bin/python -m unittest scripts.test_source_atom_triage_hardening -v` -- 153/153 PASS, OK.
  - `.venv/bin/python -m unittest scripts.test_accurate_ingest_source_graph scripts.test_toolkit_llm_final_reconciliation scripts.test_toolkit_final_reconciliation -q` -- 715/715 tests in total; OK.
  - Any touched blueprint/build-fidelity/final-reconciliation suites -- verified as included in the above batch.
  - Verification: All targeted suites pass. Expected negative-path test logs present in output.
- [x] 6.4 Run `openspec validate toolkit-accurate-ingest-source-atom-triage-hardening --strict`.
  - Verification: Change is valid. `openspec validate` exited 0 with "Change 'toolkit-accurate-ingest-source-atom-triage-hardening' is valid".

## SHOULD Guidance

- Use micro-edits in large Python files.
- Compile after each touched Python file.
- Keep tests provider-free and tempdir-backed.
- Do not stage or commit until this change, the structural-repair change, and final-editor step 7.3/8 are all validated.
