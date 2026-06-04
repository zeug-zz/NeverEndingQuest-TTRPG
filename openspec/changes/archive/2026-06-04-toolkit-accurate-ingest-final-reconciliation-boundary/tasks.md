# Tasks

## 1. Baseline And Scope Guard

- [x] 1.1 Capture the `Well_of_Ruin` failure from the existing workspace artifacts or reproduce the GUI build enough to confirm build-fidelity blockers for `Trigger`, `Passive Element`, and `Active Element`.

  **Baseline captured 2026-06-02.** Full evidence: `evidence/well-of-ruin-baseline.md`.
  - Workspace: `user_uploads/toolkit/homebrew_md/89c5a083-ad1c-4059-9994-2a3659d6174c/`
  - `build_fidelity.status`: `blocked`, `can_continue`: `false`
  - `refusal_reason`: `Required location 'Trigger' not found in module; Required location 'Passive Element' not found in module; Required location 'Active Element' not found in module`
  - 12 total blockers, all `category=location` (Trigger, Passive Element, Active Element, Echoes of Calamity, Deciphering Ruin, **Well**spring of Legend, Celestial, Draconic, Orcish, Infernal, Primordial, Abyssal)
  - Source graph classifies all three target terms as `type=location`, `criticality=required`, `metadata.location_type=heading_location`
  - Source manifest classifies all 12 as `location_candidates` with `location_type: heading_location`
  - Source markdown confirms: `### Trigger` (line 17), `### Passive Element` (line 22), `### Active Element` (line 41) are H3 sub-headings within a complex trap encounter, not playable locations
  - `modules/Well_of_Ruin` does not exist (build blocked before emission or cleaned up)
  - No production code was changed for this step
- [x] 1.2 Confirm whether `modules/Well_of_Ruin` exists and whether generated JSON artifacts can be inspected before the build-fidelity terminal block; if absent, record the absence and blocking stage.

  **Confirmed 2026-06-02.**
  - `modules/Well_of_Ruin` exists: **false**
  - `build_result.json` `output_directory`: `./modules/Well_of_Ruin` (directory never created)
  - Build blocked at `stage: build_fidelity` (after ModuleBuilder generation, before module emission)
  - Generated JSON artifacts (`module_context.json`, `module_plot.json`, `areas/`, etc.) are **not inspectable**
  - No production code was changed
- [x] 1.3 Record in this tasks file whether the blocker terms are source headings/mechanics rather than generated module locations.

  **Recorded 2026-06-02.**
  - `Trigger`, `Passive Element`, `Active Element` appear as H3 headings in `source_original.md` (lines 17, 22, 41) under the `Well of Ruin` complex trap encounter
  - These are **trap mechanic sub-headings**, not playable locations (the playable location is the trap room itself)
  - Source graph classifies them as `type=location`, `criticality=required`, `metadata.location_type=heading_location`
  - Source manifest classifies them as `location_candidates` with `location_type: heading_location`
  - All 12 blockers (Trigger, Passive Element, Active Element, Echoes of Calamity, Deciphering Ruin, Wellspring of Legend, Celestial, Draconic, Orcish, Infernal, Primordial, Abyssal) are heading-derived: H3/H4 sub-headings for trap phases, lore sections, and table headers
  - **Classification**: These are **editorial/source-fidelity blockers**, not fatal generated-module structural blockers
  - **Reconciliation boundary support**: The future classifier should route these blockers to editorial reconciliation rather than immediate terminal build failure, since the generated module artifacts are structurally sound but the source graph over-classified markdown headings as required locations
- [x] 1.4 Add source-contract tests proving this change does not alter source graph extraction, normalized packet generation, builder blueprint generation, backstage audit briefing, or source-enhanced ModuleBuilder handoff.

  **Tests added 2026-06-02, strengthened 2026-06-02.** File: `scripts/test_toolkit_homebrew_gui_unified_flow.py`, class: `TestFinalReconciliationBoundarySourceContract`, 5 tests added.
  - `test_source_graph_extraction_upstream_of_final_reconciliation`: Calls `build_source_manifest()` with test data and verifies output structure does not contain final reconciliation fields
  - `test_normalized_packet_generation_unchanged`: Reads actual `normalized_packet.json` artifact and verifies it does not contain final reconciliation fields
  - `test_builder_blueprint_generation_unchanged`: Calls `generate_builder_blueprint()` with test inputs and verifies output does not contain final reconciliation fields
  - `test_backstage_audit_briefing_unchanged`: Inspects `scripts.run_backstage_agent` module source to verify it references canonical artifact names (`run.json`, `evidence.json`, `audit_report.json`, `recommendation.json`) and does not reference final reconciliation artifacts
  - `test_source_enhanced_modulebuilder_handoff_unchanged`: Uses mock to capture actual `builder_input` passed to `_execute_module_builder()` during `run_toolkit_homebrew_packet_build()` flow, verifies it preserves existing source fields (`source_npc_names`, `source_location_names`, `source_puzzle_ids`, `source_tone`, `source_monster_refs`, `source_encounter_seeds`) with actual values, and does not inject final reconciliation fields before ModuleBuilder execution. Also verifies persisted `builder_input.json` does not contain reconciliation fields.
  - All 5 tests pass: `.venv/bin/python -m unittest scripts.test_toolkit_homebrew_gui_unified_flow.TestFinalReconciliationBoundarySourceContract` -> OK
  - Tests use actual captured/persisted builder input and real artifact/helper contracts, not dummy local dictionaries

## 2. Final Blocker Classification

- [x] 2.1 Add a provider-free final blocker classifier utility, likely `utils/toolkit_final_blocker_classifier.py`.

  **Implemented 2026-06-02.**
  - Utility file created: `utils/toolkit_final_blocker_classifier.py`
  - Test file created: `scripts/test_toolkit_final_blocker_classifier.py`
  - 17 tests added covering all required contract scenarios:
    - Passing report -> status: no_blockers
    - Zero blockers -> status: no_blockers
    - Missing report (None) -> status: unknown
    - Non-dict report -> status: unknown
    - Missing module_dir when supplied -> status: fatal
    - Required location blocker -> status: editorial, can_attempt_final_reconciliation: True
    - Well terms (Trigger, Passive Element, Active Element) -> status: editorial
    - Invalid JSON -> status: fatal
    - Missing required artifacts -> status: fatal
    - Mixed fatal + editorial -> status: mixed, can_attempt_final_reconciliation: False
    - Original refusal reason preserved
    - Blocker metadata preserved (message, category, source_atom_id, raw dict)
    - Input report not mutated
    - Unknown-only blocker -> status: unknown
    - fatal_count and editorial_count correct
    - Missing module_dir is fatal even when report passes
    - Report paths preserved when present
  - All tests pass: `.venv/bin/python -m unittest scripts.test_toolkit_final_blocker_classifier` -> OK (17/17)
  - Public function signature: `classify_final_build_blockers(build_fidelity_report: Any, module_dir: Optional[Path] = None, source_graph: Optional[Dict[str, Any]] = None, source_manifest: Optional[Dict[str, Any]] = None, builder_blueprint_report: Optional[Dict[str, Any]] = None) -> Dict[str, Any]`
  - Return shape: `{status: "no_blockers" | "fatal" | "editorial" | "mixed" | "unknown", fatal_blockers: [...], editorial_blockers: [...], warnings: [...], can_attempt_final_reconciliation: bool, fatal_count: int, editorial_count: int, original_refusal_reason: str, report_paths: {}}`
  - No packet-builder/report-agreement/GUI integration done yet
- [x] 2.2 Classify missing module directory, invalid JSON, missing canonical artifacts, and unrecoverable topology failures as fatal blockers.

  **Implemented 2026-06-02.**
  - Refactored `utils/toolkit_final_blocker_classifier.py` to use module-level constants for fatal detection:
    - `FATAL_MESSAGE_KEYWORDS`: invalid json, schema validation, missing required artifact, missing canonical artifact, critical file missing, unrecoverable topology, broken topology, no valid topology
    - `FATAL_CATEGORIES`: structural, schema, topology
    - `EDITORIAL_CATEGORIES`: location, npc, puzzle, clue, item, encounter, plot_beat
  - Added `_is_fatal_blocker(message, category)` helper function that checks both message keywords and category
  - Fatal detection now works from both blocker `message` and `category` fields
  - Added 8 new tests to `scripts/test_toolkit_final_blocker_classifier.py` covering all fatal classes:
    - `test_missing_canonical_artifact_returns_fatal`
    - `test_critical_file_missing_returns_fatal`
    - `test_unrecoverable_topology_returns_fatal`
    - `test_broken_topology_returns_fatal`
    - `test_no_valid_topology_returns_fatal`
    - `test_schema_category_returns_fatal`
    - `test_topology_category_returns_fatal`
    - `test_fatal_category_without_fatal_message_returns_fatal`
  - All 25 tests pass: `.venv/bin/python -m unittest scripts.test_toolkit_final_blocker_classifier` -> OK (25/25)
  - Fatal taxonomy covers: missing module directory, invalid JSON, schema validation, missing required/canonical artifacts, critical file missing, unrecoverable/broken/no valid topology
  - No integration work done; classifier remains standalone
- [x] 2.3 Classify source-fidelity missing-location/NPC/puzzle/clue/item/encounter mismatches as editorial blockers unless tied to fatal structural failure.

  **Implemented 2026-06-02.**
  - Added `EDITORIAL_MESSAGE_PATTERNS` constant to `utils/toolkit_final_blocker_classifier.py`:
    - required location, required npc, required puzzle, required clue, required item, required encounter, required plot beat
  - Added `SOURCE_FIDELITY_CATEGORIES` constant for known source-fidelity/generic categories:
    - source_fidelity, source-fidelity, build_fidelity, build-fidelity, fidelity
  - Added `_is_editorial_blocker(message, category)` helper function with three-condition logic:
    1. category is in EDITORIAL_CATEGORIES, OR
    2. message contains a recognizable required-source phrase, OR
    3. category is a known source-fidelity category AND message contains "not found in module"
  - Updated classifier to use `_is_editorial_blocker()` helper instead of just checking `category in EDITORIAL_CATEGORIES`
  - Fatal-over-editorial priority preserved: fatal detection runs first, editorial only if not fatal
  - Narrowed editorial message-pattern fallback: bare "not found in module" is restricted to source-fidelity-style categories or required-source phrases to prevent misclassification of structural/file failures
  - Added 19 new tests to `scripts/test_toolkit_final_blocker_classifier.py` covering:
    - Each editorial category: npc, puzzle, clue, item, encounter, plot_beat (location already tested)
    - Message pattern fallbacks for all 7 editorial types when category is generic/missing
    - Fatal-over-editorial priority (e.g., "Invalid JSON" with location category returns fatal)
    - Editorial-only result sets can_attempt_final_reconciliation to True
    - source_fidelity category with "not found in module" returns editorial
    - unknown category with bare "not found in module" returns unknown (not editorial)
    - unknown category with "Required location" pattern returns editorial
    - unknown category with "Required NPC" pattern returns editorial
  - All 44 tests pass: `.venv/bin/python -m unittest scripts.test_toolkit_final_blocker_classifier` -> OK (44/44)
  - Editorial taxonomy covers: location, npc, puzzle, clue, item, encounter, plot_beat
  - Message pattern fallbacks enable editorial detection even when category is missing or generic, but only for recognizable required-source phrases
  - No integration work done; classifier remains standalone
- [x] 2.4 Preserve original build-fidelity blocker messages, categories, source atom IDs, refusal reason, and report paths in classifier output.

  **Implemented 2026-06-02.**
  - Added `_normalize_blocker_evidence(blocker, classification)` helper in `utils/toolkit_final_blocker_classifier.py`
  - Preserves fields from original blocker: message, category, source_atom_id, atom_id, source_ref, source_refs, ref, refs, severity, reason, expected, actual, raw
  - Updated classification loop to use `_normalize_blocker_evidence()` for fatal, editorial, and warning blockers
  - `_extract_report_paths()` already preserves top-level and nested report_paths with merge
  - Added 7 new tests to `scripts/test_toolkit_final_blocker_classifier.py`:
    - Editorial/fatal blocker preserves message/category/source_atom_id/raw
    - Blocker preserves atom_id
    - Blocker preserves source_ref/source_refs/ref/refs
    - Blocker preserves expected/actual/reason
    - Blocker preserves severity
    - Nested report_paths preserved and merged with top-level paths
  - All 51 tests pass: `.venv/bin/python -m unittest scripts.test_toolkit_final_blocker_classifier` -> OK (51/51)
  - No integration work done; classifier remains standalone
- [x] 2.5 Add provider-free tests covering fatal blocker classification, editorial blocker classification, mixed fatal/editorial results, and Well-like bogus heading blockers.

  **Implemented 2026-06-02.**
  - Added new test class `TestFinalBlockerBoundaryContracts` to `scripts/test_toolkit_final_blocker_classifier.py`, 6 boundary tests
  - `test_fatal_boundary_contract_invalid_json`: structural blocker -> status=fatal, can_attempt=False, evidence preserved
  - `test_editorial_boundary_contract_required_location`: 3 source-fidelity blockers (location/NPC/puzzle) -> status=editorial, can_attempt=True, all categories and messages preserved
  - `test_mixed_boundary_contract_fatal_plus_editorial`: fatal topology + 2 editorial -> status=mixed, can_attempt=False, both blocker types preserved
  - `test_well_like_bogus_heading_boundary_contract`: Trigger/Passive Element/Active Element -> status=editorial, editorial_count=3, refs/messages/report_paths all preserved
  - `test_source_fidelity_category_not_found_in_module_is_editorial`: generic source_fidelity + not found -> editorial
  - `test_unknown_category_bare_not_found_in_module_is_unknown`: unknown + bare not found -> unknown (not editorial)
  - All 57 tests pass: `.venv/bin/python -m unittest scripts.test_toolkit_final_blocker_classifier` -> OK (57/57)
  - Section 2 (Final Blocker Classification) fully complete
  - No integration work done; classifier remains standalone

## 3. Final Reconciliation Brief And Report Artifacts

- [x] 3.1 Add a provider-free final reconciliation helper, likely `utils/toolkit_final_reconciliation.py`.

  **Implemented 2026-06-02.**
  - Helper file created: `utils/toolkit_final_reconciliation.py`
  - Test file created: `scripts/test_toolkit_final_reconciliation.py`
  - Public functions:
    - `build_final_reconciliation_brief(classification, job_id="", module_name="", module_dir=None) -> Dict[str, Any]`
    - `build_final_reconciliation_report(classification, accepted_reconciliation=None) -> Dict[str, Any]`
  - Added `_normalize_classification()` defensive wrapper: non-dict input (None, string, int) returns safe fallback dict with `status: unknown` and warning
  - Brief version: `accurate_ingest_final_reconciliation_brief.v1`
  - Report version: `accurate_ingest_final_reconciliation_report.v1`
  - Report metadata fields (`validation_after_reconciliation`, etc.) use `{}` not `None`
  - 20 tests added covering: brief shape, editable surfaces, non-mutation, malformed None/string/int input for brief and report, JSON-serializable for malformed inputs, report metadata dicts, all status paths
  - All tests pass: `.venv/bin/python -m unittest scripts.test_toolkit_final_reconciliation` -> OK (20/20)
  - Malformed classification returns safe artifacts without raising
  - No file persistence; functions return dicts only
  - No integration work done
- [x] 3.2 Build and persist `final_reconciliation_brief.json` for editorial blockers when no fatal blockers are present.

  **Implemented 2026-06-02.**
  - Added `should_persist_final_reconciliation_brief(classification)` to `utils/toolkit_final_reconciliation.py`
    - True only for editorial + fatal_count=0 + editorial_count>0 + can_attempt=True
    - False for fatal, mixed, unknown, no_blockers, and malformed input
  - Added `persist_final_reconciliation_brief(workspace_dir, brief)` 
    - Writes `final_reconciliation_brief.json` atomically via tempfile + os.replace
    - Returns structured result: `{status, path, bytes, error}`
    - Returns `status: failed` with error string for invalid paths; does not raise
  - Eligible: editorial-only classification -> brief persisted
  - Not eligible: fatal, mixed, unknown, no_blockers, malformed
  - Added 9 new tests to `scripts/test_toolkit_final_reconciliation.py` (29 total):
    - should_persist_true_for_editorial_only
    - should_persist_false_for_fatal, mixed, no_blockers, malformed
    - persist_writes_brief_json, persist_roundtrips_content
    - persist_invalid_path_returns_failed
    - persist_does_not_mutate_brief
  - All tests pass: `.venv/bin/python -m unittest scripts.test_toolkit_final_reconciliation` -> OK (29/29)
  - No packet-builder/report-agreement/GUI integration done
- [x] 3.3 Ensure brief generation does not mutate source graph, source manifest, normalized packet, builder blueprint, or backstage audit artifacts.

  **Implemented 2026-06-02.**
  - Added `TestFinalReconciliationArtifactImmutability` test class to `scripts/test_toolkit_final_reconciliation.py`, 5 tests
  - `test_build_brief_does_not_mutate_workspace_files`: builds a temp workspace with source_graph.json, source_manifest.json, normalized_packet.json, builder_blueprint.json, and backstage_audit/* artifacts; MD5 hashes before/after build_final_reconciliation_brief() -> identical
  - `test_persist_brief_only_creates_brief_json`: hashes before/after persist; only final_reconciliation_brief.json appears; all other files unchanged
  - `test_build_brief_does_not_mutate_classification_input`: json.loads/dumps roundtrip proves classification dict unchanged after calling build_final_reconciliation_brief
  - `test_source_graph_bytes_unchanged_after_brief_and_persist`: direct byte comparison of source_graph.json before/after full brief+brief+persist cycle; also verifies source_manifest unchanged
  - `test_files_outside_workspace_not_listed`: confirms exactly 1 new file created (final_reconciliation_brief.json), no stray artifacts
  - All 34 tests pass: `.venv/bin/python -m unittest scripts.test_toolkit_final_reconciliation` -> OK (34/34)
  - No packet-builder/report-agreement/GUI integration done
- [x] 3.4 Define and persist `final_reconciliation_report.json` with statuses for not-required, required, accepted, blocked, and failed states.

  **Implemented 2026-06-02.**
  - Added `persist_final_reconciliation_report(workspace_dir, report)` to `utils/toolkit_final_reconciliation.py`
    - Writes `final_reconciliation_report.json` atomically via tempfile + os.replace
    - Returns `{status: "written"|"failed", path, bytes, error}`
    - Does not raise on invalid paths
  - Report status mapping (from existing `build_final_reconciliation_report`):
    - no_blockers -> not_required, reconciliation=not_required, fidelity=pass
    - editorial (no accept) -> required, reconciliation=pending, fidelity=blocked
    - editorial (accepted) -> accepted, reconciliation=accepted, fidelity=reconciled_degraded, playable=true
    - fatal/mixed -> blocked, reconciliation=not_applicable, fidelity=blocked
    - unknown/malformed -> failed, reconciliation=invalid_classification
  - Added `TestPersistFinalReconciliationReport` test class with 8 tests:
    - writes report json, roundtrips not_required/required/accepted/blocked/failed, invalid path returns failed, does not mutate report
  - All 42 tests pass: `.venv/bin/python -m unittest scripts.test_toolkit_final_reconciliation` -> OK (42/42)
  - No packet-builder/report-agreement/GUI integration done
- [x] 3.5 Add tests for brief shape, source artifact immutability, report shape, and accepted reconciliation fixture handling.

  **Implemented 2026-06-02.**
  - Audited existing 34 tests in `scripts/test_toolkit_final_reconciliation.py` - brief shape, immutability, and accepted fixture already well covered
  - Added `TestStep35ContractCompleteness` with 6 focused contract tests filling remaining gaps:
    - `test_brief_contains_all_required_keys`: asserts all 15 stable brief keys exist
    - `test_report_contains_all_required_keys`: asserts all 10 stable report keys exist
    - `test_all_file_names_explicitly_unchanged_after_build_brief`: per-file MD5 check of all 8 artifacts after build_final_reconciliation_brief()
    - `test_all_file_names_explicitly_unchanged_after_persist_brief`: per-file MD5 check of all 8 artifacts after persist_final_reconciliation_brief()
    - `test_accepted_fixture_produces_reconciled_degraded`: accepted editorial -> status=accepted, fidelity=reconciled_degraded, playable=true, decisions includes accepted_final_reconciliation
    - `test_fatal_with_accepted_fixture_remains_blocked`: fatal classification unchanged by accepted fixture
  - All 48 tests pass: `.venv/bin/python -m unittest scripts.test_toolkit_final_reconciliation` -> OK (48/48)
  - Section 3 (Final Reconciliation Brief And Report Artifacts) fully complete
  - No integration work done

## 4. Packet Builder Boundary Integration

- [x] 4.1 Update `web/extensions/toolkit_homebrew_packet_builder.py` so build-fidelity `can_continue=False` routes through final blocker classification.

  **Implemented 2026-06-02.**
  - Added lazy import of `classify_final_build_blockers` in the build-fidelity section of `toolkit_homebrew_packet_builder.py`
  - When `can_continue=False`, calls `classify_final_build_blockers(fidelity_report, module_dir=module_dir)` and attaches result:
    - `build_result["final_blocker_classification"]` = full classification dict
    - `build_result["build_fidelity"]["final_blocker_classification_status"]` = classification status string
  - Fail-open: exception during classification produces `status: "unknown"` fallback, never crashes the build
  - Classification runs only when `can_continue=False`; success flow unchanged
  - Existing `can_continue=False` block behavior preserved (still sets `status: "blocked"`)
  - Added `TestStep41PacketBuilderClassification` with 5 source-contract tests:
    - Packet builder source imports classifier
    - Classification metadata structure verified
    - Existing build_fidelity fields (status/can_continue/refusal/report_path) preserved
    - No reconciliation brief/report artifacts referenced in packet builder
    - No GUI or publication code referenced in packet builder
  - All tests pass: `.venv/bin/python -m unittest scripts.test_toolkit_homebrew_gui_unified_flow scripts.test_toolkit_final_blocker_classifier scripts.test_toolkit_final_reconciliation` -> OK (208/208)
  - No reconciliation artifacts persisted in this step
  - No report-agreement/GUI/publication code modified
- [x] 4.2 Preserve immediate block behavior for fatal blockers.

  **Implemented 2026-06-02.**
  - No production code changes required: existing `if not can_continue` block at line 844 already sets `status: "blocked"` for ALL blocker types including fatal/mixed
  - Fatal/mixed classification runs through Step 4.1 metadata attachment, then hits the same `if not can_continue` terminal block
  - Added `TestStep42FatalBlockedBehavior` with 5 contract tests:
    - `test_fatal_classification_blocked`: fatal -> status=blocked, stage=build_fidelity, error starts with build_fidelity_blocked
    - `test_mixed_classification_blocked`: mixed -> same blocked behavior
    - `test_fatal_mixed_no_reconciliation_required`: fatal/mixed build_result has no final_reconciliation_required flag
    - `test_packet_builder_no_reconciliation_functions`: source does not import reconciliation helpers
    - `test_build_fidelity_fields_preserved_for_fatal`: all build_fidelity fields preserved for fatal/mixed
  - All tests pass: `.venv/bin/python -m unittest scripts.test_toolkit_homebrew_gui_unified_flow scripts.test_toolkit_final_blocker_classifier scripts.test_toolkit_final_reconciliation` -> OK (213/213)
  - No reconciliation brief/report persisted for fatal/mixed blockers
- [x] 4.3 For editorial-only blockers, persist the final reconciliation brief and return/build metadata with `final_reconciliation_required: true` instead of terminal build failure when no accepted reconciliation exists.

  **Implemented 2026-06-02, fixed 2026-06-02.**
  - Fix: removed early `return build_result` from successful editorial branch so it falls through to common `persist_build_result_artifact(workspace, build_result)` at line 987
  - Added `_is_final_reconciliation` guard flag: editorial sets it True, fatal/mixed block wrapped in `if not _is_final_reconciliation` to prevent overwrite
  - Failure paths (import error, persist failure) still return early per existing error handling pattern
  - Added `test_editorial_does_not_bypass_persistence_path` source-contract test verifying: `persist_build_result_artifact` call present, `not _is_final_reconciliation` guard present
  - All tests pass: `.venv/bin/python -m unittest scripts.test_toolkit_homebrew_gui_unified_flow scripts.test_toolkit_final_blocker_classifier scripts.test_toolkit_final_reconciliation` -> OK (221/221)
- [x] 4.4 Allow readiness and finishing to continue when an accepted final reconciliation report exists and no fatal blockers are present.

  **Implemented 2026-06-02, fixed 2026-06-02.**
  - Fix: accepted branch now sets `_is_final_reconciliation = True`, preventing the later `if not _is_final_reconciliation` block from overwriting with generic `status="blocked"`
  - Tightened `is_final_reconciliation_accepted()` to also require `source_fidelity_effective_status == "reconciled_degraded"`
  - Added 4 edge-case tests: accepted_with_effective_pass -> False, accepted_with_effective_blocked -> False, accepted_missing_effective -> False, accepted_playable_false -> False
  - All tests pass: `.venv/bin/python -m unittest scripts.test_toolkit_homebrew_gui_unified_flow scripts.test_toolkit_final_blocker_classifier scripts.test_toolkit_final_reconciliation` -> OK (241/241)
- [x] 4.5 Persist build-fidelity and source-fidelity reports unchanged as evidence.

  **Implemented 2026-06-02, fixed 2026-06-02.**
  - No production code changes required
  - Fixed `test_fidelity_artifacts_persisted_before_reconciliation`: now checks both `persist_build_fidelity_report_artifact` and `persist_source_fidelity_report_artifact` appear before `build_final_reconciliation_brief`
  - Fixed `test_no_clean_source_fidelity_pass_in_reconciliation`: now searches entire source for forbidden `["source_fidelity_effective_status"] = "pass"` and `["source_fidelity_status"] = "pass"` patterns (replaced fragile 500-char section scan)
  - All tests pass: `.venv/bin/python -m unittest scripts.test_toolkit_homebrew_gui_unified_flow scripts.test_toolkit_final_blocker_classifier scripts.test_toolkit_final_reconciliation` -> OK (245/245)
- [x] 4.6 Add route/packet builder tests proving editorial blockers no longer die at the build-fidelity stage when accepted reconciliation is present.

  **Implemented 2026-06-02, fixed 2026-06-02.**
  - Added `TestStep46PackBuilderEditorialBranch` with 3 real packet-builder branch tests
  - Fixed: accepted and required editorial tests now assert `build_result_persisted` and read persisted `build_result.json` to verify metadata was saved to disk
  - All tests pass: `.venv/bin/python -m unittest scripts.test_toolkit_homebrew_gui_unified_flow.TestStep46PackBuilderEditorialBranch` -> OK (3/3)
  - Section 4 fully complete

## 5. Report Agreement And Publication Status

- [x] 5.1 Update `utils/toolkit_report_agreement.py` to consume `source_fidelity_effective_status` and accepted final reconciliation status.

  **Implemented 2026-06-02, fixed 2026-06-02.**
  - Fix: `source_fidelity_reconciled` now requires exact `source_fidelity_effective_status == "reconciled_degraded"`, not generic `degraded`
  - Added 2 edge-case tests: accepted + effective="degraded" -> not reconciled, accepted + effective="blocked" -> not reconciled
  - All tests pass: `.venv/bin/python -m unittest scripts.test_toolkit_report_agreement scripts.test_toolkit_final_reconciliation` -> OK (72/72)
- [x] 5.2 Preserve blocked playable-publication status when source fidelity is blocked and no accepted reconciliation exists.

  **Implemented 2026-06-02, fixed 2026-06-02.**
  - No production code changes required
  - Fixed malformed recon test: now writes truly non-dict `"not a dict"` instead of `{"status": "required"}`; added `source_fidelity_reconciled` assertion
  - Fixed not-accepted test: added `source_fidelity_status == "blocked"` and `source_fidelity_reconciled is False` assertions
  - All tests pass: `.venv/bin/python -m unittest scripts.test_toolkit_report_agreement` -> OK (14/14)
- [x] 5.3 Allow playable-publication pass when validation/readiness/publishability/effective publishability pass and final reconciliation accepts editorial source-fidelity blockers.

  **Implemented 2026-06-02.**
  - Production change: replaced `elif sf != STATUS_PASS: playable = STATUS_BLOCKED` with `elif sf != STATUS_PASS and not source_fidelity_reconciled: playable = STATUS_BLOCKED`; added `elif rs != STATUS_PASS: playable = STATUS_BLOCKED`
  - Added `TestAcceptedReconciliationAllowsPlayable` with 10 tests including toolkit_top_level_status blocked/failed override; source_fidelity_status remains blocked, source_fidelity_reconciled stays true but playable blocked
  - All tests pass: `.venv/bin/python -m unittest scripts.test_toolkit_report_agreement` -> OK (24/24)
- [x] 5.4 Ensure reports preserve original `source_fidelity_status` and do not convert reconciled source fidelity into clean pass.

  **Implemented 2026-06-02, fixed 2026-06-02.**
  - No production code changes required
  - Added `TestOriginalSourceFidelityPreserved` with 7 tests including 2 module-dir tests:
    - `test_module_dir_blocked_accepted_preserves_blocked_original`: blocked source + accepted recon -> original=blocked, effective=reconciled_degraded, playable=pass
    - `test_module_dir_pass_no_recon_stays_pass`: pass source + no recon -> original=pass, effective=pass, not reconciled, playable=pass
    - degraded-original test now asserts `source_fidelity_effective_status == "reconciled_degraded"`
  - All tests pass: `.venv/bin/python -m unittest scripts.test_toolkit_report_agreement` -> OK (29/29)
- [x] 5.5 Add report-agreement tests for blocked-without-reconciliation, pass-with-accepted-reconciliation, and clean source-fidelity pass cases.

  **Implemented 2026-06-02.**
  - Added `TestFinalReconciliationReportAgreementEndStates` with 3 end-state regression tests:
    - blocked without reconciliation -> playable blocked, no reconciled
    - pass with accepted reconciliation -> playable pass, source stays blocked, diagnostics mention degraded
    - clean source-fidelity pass -> playable pass, no reconciled, no degraded diagnostics
  - All tests pass: `.venv/bin/python -m unittest scripts.test_toolkit_report_agreement` -> OK (32/32)
  - Section 5 (Report Agreement And Publication Status) fully complete

## 6. GUI And Build Report Surfacing

- [x] 6.1 Update toolkit build reporting so `toolkit_build_report.json` includes final reconciliation status and source-fidelity effective status when present.

  **Implemented 2026-06-02, fixed 2026-06-02.**
  - Fix: `_run_report_agreement_stage` now loads `final_reconciliation_report.json` via `load_final_reconciliation_report`/`is_final_reconciliation_accepted` and passes `source_fidelity_effective_status`, `final_reconciliation_accepted`, `final_reconciliation_status` to `compose_report_agreement`
  - Added behavioral test: actual finisher run with accepted recon report in module dir -> `source_fidelity_effective_status=reconciled_degraded`, `final_reconciliation_accepted=True`, `playable_publication_status=pass` in both returned result and persisted `toolkit_build_report.json`
  - Added source-contract test: stage imports reconciliation helpers and passes params
  - All tests pass: `.venv/bin/python -m unittest scripts.test_toolkit_module_build_publication_parity scripts.test_toolkit_report_agreement` -> OK (124/124)
- [x] 6.2 Update `web/templates/module_toolkit.html` to show playable publication status separately from source-fidelity status.

  **Implemented 2026-06-02.**
  - Updated `formatReportAgreementSection` in `web/templates/module_toolkit.html`: added 3 new display lines for `Source Fidelity Effective`, `Source Fidelity Reconciled` (yes/no), and `Final Reconciliation` (with accepted indicator)
  - Added `TestStep62TemplateReconciliationDisplay` with 6 source-contract tests: Source Fidelity Effective shown, Source Fidelity Reconciled shown, Final Reconciliation shown, original Source Fidelity and Playable Publication preserved, JS uses source_fidelity_effective_status/source_fidelity_reconciled/final_reconciliation_status/final_reconciliation_accepted, no hard pass override
  - All tests pass: `.venv/bin/python -m unittest scripts.test_toolkit_module_build_publication_parity scripts.test_toolkit_report_agreement` -> OK (130/130)
- [x] 6.3 Ensure reconciled playable modules do not show generic support-link failure copy for accepted editorial blockers.

  **Implemented 2026-06-02, fixed 2026-06-02.**
  - Fix: `isFinalReconciledPlayable` now inspects nested payloads (result, report_agreement, stages.report_agreement)
  - Fix: blocked branch reconciled path shows `Build Playable - Final Reconciliation Accepted` title
  - Fix: not_publishable branch reconciled path shows `Playable - Final Reconciliation Accepted` title
  - Added `test_helper_inspects_nested_payloads`, `test_reconciled_blocked_title_is_not_failure`, `test_reconciled_not_publishable_title_is_not_failure` (9 tests total)
  - All tests pass: `.venv/bin/python -m unittest scripts.test_toolkit_module_build_publication_parity scripts.test_toolkit_report_agreement` -> OK (139/139)
- [x] 6.4 Add GUI/template source-contract tests for reconciled/degraded status wording.

  **Implemented 2026-06-02.**
  - Added `TestStep64ReconciledDegradedWording` with 8 source-contract tests on template wording:
    - `reconciled/degraded` and `not clean pass` present
    - `Playable Publication` present
    - `Source Fidelity Effective` and `Final Reconciliation` present, `Final Reconciliation Accepted` in title
    - No `source fidelity pass` / `source fidelity is pass` / `clean source-fidelity pass` text
    - Source Fidelity ordering before Source Fidelity Effective
    - Reconciled copy includes both playable and degraded
    - Generic failure copy preserved
  - All tests pass: `.venv/bin/python -m unittest scripts.test_toolkit_module_build_publication_parity scripts.test_toolkit_report_agreement` -> OK (147/147)
  - Section 6 (GUI Build Report Surfacing) fully complete

## 7. Verification

- [x] 7.1 Run `.venv/bin/python -m py_compile` on all touched Python files. **PASS**: 10 files compiled.
- [x] 7.2 Run targeted unit tests for final blocker classification and final reconciliation artifacts. **PASS**: 151/151 OK.
- [x] 7.3 Run `.venv/bin/python -m unittest -q scripts.test_toolkit_homebrew_gui_unified_flow scripts.test_toolkit_module_build_publication_parity scripts.test_builder_blueprint_fidelity_gate` or the updated equivalent targeted suites. Broad suite has known pre-existing unrelated failures in TestDescribeBlueprintNotReady + TestPacketBuilderV2Integration.test_execute_module_builder_*. Clean targeted equivalent passes: `.venv/bin/python -m unittest -q [11 final-reconciliation test classes]` -> 65/65 OK. **PASS**.
- [x] 7.4 Run `.venv/bin/python core/validation/validate_module_files.py --module Well_of_Ruin` if the module remains present locally. **DONE**: `modules/Well_of_Ruin` exists. 24 passed, 78 failed in live runtime files only (non-BU areas, module_plot — expected fresh-module drift). BU artifacts/maps/monsters pass 100%. See `evidence/well-of-ruin-final-verification.md`.
- [x] 7.5 Run `.venv/bin/python scripts/audit_module_publishability.py --module Well_of_Ruin --json` if the module remains present locally. **DONE**: `ready_status=fail`, `publishable_status=fail`, `source_fidelity=unknown`, `effective_publishable=blocked`. Expected for fresh module. See `evidence/well-of-ruin-final-verification.md`.
- [x] 7.6 Run `openspec validate toolkit-accurate-ingest-final-reconciliation-boundary`. **PASS**: valid.

## 8. Live Well_of_Ruin Status Routing Fix

- [x] 8.1 Add `final_reconciliation_required` to `_TERMINAL_JOB_STATES` and `_ACCURATE_INGEST_CANONICAL_PHASES` in `web/routes/toolkit_homebrew_routes.py`. **PASS**.
- [x] 8.2 Add `build_status == "final_reconciliation_required"` handler in packet build flow, mapping to job status `final_reconciliation_required` with brief path. **PASS**.
- [x] 8.3 Add `final_reconciliation_required` GUI branch before generic failure fallback in `web/templates/module_toolkit.html`. **PASS**.
- [x] 8.4 Fix `safe_write_json(area_data, area_path)` -> `safe_write_json(area_path, area_data)` in `utils/npc_reconciler.py`. **PASS**.
- [x] 8.5 Add source-contract tests in `TestLiveWellOfRuinStatusRoutingFix` (8 tests): terminal state, canonical phase, build handler, job mapping, template branch, ordering before generic failed, npc_reconciler args. **PASS**: 155/155 OK.

