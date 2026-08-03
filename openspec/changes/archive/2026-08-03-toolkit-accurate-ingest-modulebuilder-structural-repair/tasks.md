## 1. Baseline And Routing Tests

- [X] 1.1 Add provider-free tests that reproduce Well-of-Ruin-style structural failure categories from `validation_report.json` and assert they are fatal before final-editor routing.

  **Baseline structural-fatal category tests landed 2026-06-22.**

  - Extended `utils/toolkit_final_blocker_classifier.py`: added `reference_integrity`, `spatial_contract`, `party` to `FATAL_CATEGORIES`; added `not cardinally adjacent`, `expected monsters/`, `is not one of` to `FATAL_MESSAGE_KEYWORDS`. Minimal additive change, no removals or reorders.
  - New test file: `scripts/test_structural_blocker_routing.py` (16 tests across 4 classes):
    - `TestWellOfRuinStructuralCategories` (7 tests): category-based and message-keyword-based fatal classification for all three Well-of-Ruin structural categories; combined all-three report classifies as fatal.
    - `TestAcceptedReportCannotOverrideStructuralFailure` (2 tests): fatal classification blocks reconciliation eligibility even with accepted report on disk.
    - `TestEditorialBlockersStillUseReconciliation` (4 tests): editorial location/npc blockers remain editorial; editorial-only report can attempt reconciliation; mixed structural+editorial is fatal.
    - `TestWellOfRuinValidationReportFixture` (3 tests): live fixture tests reading `modules/Well_of_Ruin/validation_report.json` and asserting reference_integrity, spatial_contract, and party errors all classify as fatal.
  - Verification: 73/73 PASS (16 new + 57 existing classifier tests). ASCII 0 violations.
- [X] 1.2 Add tests proving an accepted `final_reconciliation_report.json` on disk cannot override current reference-integrity, spatial-contract, or party validation failures.

  **Accepted-report-override routing tests landed 2026-06-22.**

  - Added `TestAcceptedReportCannotOverrideStructuralRouting` (4 tests) to `scripts/test_structural_blocker_routing.py`.
  - Tests prove that an accepted `final_reconciliation_report.json` on disk cannot override fatal classification for `reference_integrity`, `spatial_contract`, `party`, or mixed structural+editorial.
  - All 4 tests assert: `status=blocked`, `stage=build_fidelity`, editor never invoked, persist never called, no reconciliation fields attached.
  - Verification: 20/20 PASS (16 from 1.1 + 4 new). No regression on `TestStep53FatalMixedGuard`.
- [X] 1.3 Add tests proving editorial-only blockers remain eligible for final-editor reconciliation after structural validation passes.

  **Editorial eligibility routing tests landed 2026-06-22.**

  - Added `TestEditorialEligibilityAfterStructuralPass` (5 tests) to `scripts/test_structural_blocker_routing.py`.
  - Tests prove editorial-only blockers (location, npc, puzzle) route to final-editor invocation; mixed structural+editorial is still fatal.
  - All editorial-eligible tests assert `mock_run_editor.assert_called_once()`; mixed test asserts `assert_not_called()`.
  - Verification: 25/25 PASS (20 from 1.1+1.2 + 5 new).

## 2. Monster Reference Closure

- [X] 2.1 Extract or adapt existing monster reference closure behavior from `core/generators/module_generator.py` into a reusable helper for accurate-ingest ModuleBuilder output.

  **Monster closure utility extracted 2026-06-22.**

  - New module: `utils/monster_reference_closure.py` with 7 standalone functions: `normalize_monster_name`, `get_active_area_files`, `collect_referenced_monsters`, `collect_existing_monster_slugs`, `materialize_missing_monsters`, `ensure_monster_reference_closure`, `_is_ambiguous_npc_like`.
  - NPC-like ambiguity detection added: flags names with NPC title patterns (Sir, Lord, Lady, etc.) in `ambiguous_npc_like` report field without blocking materialization.
  - New test file: `scripts/test_monster_reference_closure.py` (25 tests across 6 classes).
  - ModuleGenerator unmodified. Both paths coexist.
  - Verification: 25/25 PASS. ASCII 0 violations.
- [X] 2.2 Wire monster closure into the source-enhanced ModuleBuilder path before full-module validation and final blocker classification.

  **Monster closure wired into packet builder 2026-06-22.**

  - Inserted monster closure block in `web/extensions/toolkit_homebrew_packet_builder.py` after build completion, before fidelity gates.
  - Unresolved monster references block the build (`status=blocked`, `stage=monster_closure`) before fidelity or final-editor routing.
  - Closure exceptions fail open (validator catches missing monsters as reference_integrity failures).
  - Added `TestPacketBuilderMonsterClosureWiring` (4 tests) to `scripts/test_monster_reference_closure.py`.
  - Verification: 54/54 PASS (29 monster closure + 25 structural routing). ASCII 0 violations.
- [X] 2.3 Persist compatible monster closure diagnostics or `monster_closure_report.json` for accurate-ingest builds.

  **Closure report persistence verified 2026-06-22.**

  - Added `report_path` to `build_result["monster_closure"]` in packet builder.
  - `utils/monster_reference_closure.py` already writes all required fields (`timestamp`, `required`, `existing_before`, `generated`, `unresolved`, `details`, `ambiguous_npc_like`).
  - Added `TestMonsterClosureReportPersistence` (5 tests) to `scripts/test_monster_reference_closure.py`.
  - Verification: 34/34 PASS. ASCII 0 violations.
- [X] 2.4 Add regression tests for resolved monsters, unresolved required monsters, NPC-like ambiguous names, and existing ModuleGenerator parity.

  **Closure parity and regression tests landed 2026-06-22.**

  - Added `TestMonsterClosureParityAndRegression` (10 tests) to `scripts/test_monster_reference_closure.py`.
  - Parity: `normalize_monster_name`, `get_active_area_files`, `collect_referenced_monsters`, `collect_existing_monster_slugs` all match ModuleGenerator equivalents.
  - Regression: resolved, unresolved, NPC-like ambiguity flagging, creature type not flagged, ModuleGenerator still works.
  - Verification: 44/44 PASS. ModuleGenerator unmodified. ASCII 0 violations.

## 3. Spatial Repair

- [X] 3.1 Add or reuse a deterministic spatial repair helper that recomputes coordinates, cardinal adjacency, map links, and area connectivity from finalized location artifacts.

  **Spatial repair helper created 2026-06-22.**

  - New module: `utils/spatial_repair.py` with `repair_module_spatial(module_dir)` wrapping `remediate_module` with `force_relayout=True`.
  - Produces `spatial_repair_report.json` with `input_location_count`, `repaired_area_count`, `edge_count`, `unresolved_count`, `status`, `details`.
  - New test file: `scripts/test_spatial_repair.py` (8 tests: no areas, valid areas, invalid coordinates, report persistence, location ID preservation, determinism, edge counting, failed status).
  - Verification: 8/8 PASS. ASCII 0 violations.
- [X] 3.2 Wire spatial repair into the accurate-ingest ModuleBuilder path after location/connectivity generation and before full-module validation.

  **Spatial repair wired into packet builder 2026-06-22.**

  - Inserted spatial repair block in `web/extensions/toolkit_homebrew_packet_builder.py` after monster closure, before fidelity gates.
  - Failed spatial repair blocks build (`status=blocked`, `stage=spatial_repair`) before fidelity or final-editor routing.
  - Repair exceptions fail open (validator catches spatial contract failures).
  - Added `TestPacketBuilderSpatialRepairWiring` (4 tests) to `scripts/test_spatial_repair.py`.
  - Verification: 37/37 PASS (12 spatial repair + 25 structural routing). ASCII 0 violations.
- [X] 3.3 Persist compact spatial repair metadata with counts, unresolved diagnostics, and status.

  **Spatial repair report persistence verified 2026-06-22.**

  - Added `TestSpatialRepairReportPersistence` (5 tests) to `scripts/test_spatial_repair.py`.
  - Tests verify all required fields, error details on failure, report path in build result, status matching, and downstream loadability.
  - Verification: 23/23 PASS. ASCII 0 violations.
- [X] 3.4 Add regression tests for stale coordinate repair, source location identity preservation, and unsafe topology fail-closed behavior.

  **Spatial repair regression tests landed 2026-06-22.**

  - Added `TestSpatialRepairRegression` (6 tests) to `scripts/test_spatial_repair.py`.
  - Tests: stale coordinate repair, location identity preservation, unsafe topology fail-closed, no invented locations, both area+map files updated, idempotent on valid module.
  - Verification: 23/23 PASS. ASCII 0 violations.

## 4. Calendar Normalization

- [X] 4.1 Add build-time party calendar normalization for canonical party artifacts before final validation.

  **Calendar normalization utility created 2026-06-22.**

  - New module: `utils/calendar_normalization.py` with `normalize_party_calendar(module_dir)`.
  - Targets `party_tracker_BU.json` only (NOT runtime `party_tracker.json`).
  - Known invalid months (Hammer, Alturiak, etc.) normalized via `MONTH_CONVERSION`. Unknown invalid months fail closed.
  - Verification: 14/14 PASS. ASCII 0 violations.
- [X] 4.2 Remove or replace the invalid `"month": "Hammer"` generator prompt example.

  **Hammer references replaced 2026-06-22.**

  - `core/generators/module_builder.py:1073`: `"Hammer"` -> `"Firstmonth"`.
  - `core/generators/location_generator.py:310`: `"Hammer"` -> `"Firstmonth"`.
  - `utils/toolkit_blueprint_seed_writer.py:1027`: `else "Hammer"` -> `else "Firstmonth"`.
  - All marked with `# TABLETOP MODE:` comments. 3 files, 1 line each.
- [X] 4.3 Add tests for known invalid month normalization, unknown invalid month fail-closed diagnostics, and runtime-only party tracker non-mutation.

  **Calendar normalization tests landed 2026-06-22.**

  - New test file: `scripts/test_calendar_normalization.py` (14 tests across 2 classes).
  - `TestCalendarNormalization` (11 tests): Hammer/Alturiak normalization, valid month skip, unknown invalid fail-closed, missing BU, runtime non-mutation, empty/missing/non-string month, invalid BU.
  - `TestPromptHammerRemoval` (3 tests): source-contract tests proving no `"Hammer"` in generator prompts/defaults.
  - Verification: 14/14 PASS. ASCII 0 violations.

## 5. Structural Blocker Integration

- [X] 5.1 Update packet-builder and blocker-classifier routing so fatal structural validation categories skip final-editor invocation.

  **Structural blocker routing integrated 2026-06-22.**

  - Wired calendar normalization into packet builder (monster -> spatial -> calendar -> fidelity chain).
  - Source-contract test verifies repair chain order.
  - Added `TestStructuralBlockerRoutingIntegration` (7 tests) to `scripts/test_structural_blocker_routing.py`.
  - Tests: calendar wiring, failed calendar blocks, exception fail-open, chain order, fatal skips editor, mixed skips editor, editorial reaches editor.
  - Verification: 32/32 PASS. ASCII 0 violations.
- [X] 5.2 Ensure structural failures produce clear blocked build metadata without `final_reconciliation_required`, `final_reconciliation_accepted`, or playable reconciled status.

  **Structural blocked metadata verified 2026-06-22.**

  - Added `TestStructuralFailureBlockedMetadata` (7 tests) to `scripts/test_structural_blocker_routing.py`.
  - Tests prove each structural block stage (monster_closure, spatial_repair, calendar_normalization, build_fidelity) produces clean blocked metadata with NO reconciliation fields.
  - Verification: 46/46 PASS. ASCII 0 violations.
- [X] 5.3 Preserve existing final-editor behavior for editorial-only blockers after structural validation passes.

  **Editorial behavior preservation verified 2026-06-22.**

  - Added `TestEditorialBehaviorPreserved` (4 tests) to `scripts/test_structural_blocker_routing.py`.
  - Tests prove editorial path still reaches editor after all repairs pass, can accept with reconciled_degraded, and has no structural blocker fields.
  - Verification: 46/46 PASS. ASCII 0 violations.
- [X] 5.4 Add GUI/report source-contract tests for structural blocked state wording if frontend status copy changes.

  **GUI/report source-contract tests landed 2026-06-22.**

  - Added `TestGuiReportSourceContract` (3 tests) to `scripts/test_structural_blocker_routing.py`.
  - Tests verify generic blocked handler in `module_toolkit.html`, reconciliation UI gated by `isFinalReconciledPlayable`, and `compose_report_agreement` does not claim playable for blocked status.
  - Verification: 46/46 PASS. ASCII 0 violations.

## 6. Verification

- [X] 6.1 Run `.venv/bin/python -m py_compile` on all touched Python files.

  **All 12 touched Python files compile clean 2026-06-22.** Files: `utils/toolkit_final_blocker_classifier.py`, `utils/monster_reference_closure.py`, `utils/spatial_repair.py`, `utils/calendar_normalization.py`, `web/extensions/toolkit_homebrew_packet_builder.py`, `core/generators/module_builder.py`, `core/generators/location_generator.py`, `utils/toolkit_blueprint_seed_writer.py`, and 4 test files.
- [X] 6.2 Run targeted monster closure, spatial repair, calendar normalization, packet-builder routing, final-editor routing, and report-agreement tests.

  **458 tests pass across all targeted suites 2026-06-22.** Breakdown: 278 targeted (structural routing + monster closure + spatial repair + calendar normalization + classifier + final reconciliation + report agreement), 18 final-editor regression, 162 publication parity. All OK.
- [X] 6.3 Run `.venv/bin/python core/validation/validate_module_files.py --module Well_of_Ruin` if the module artifact is present.

  **Well of Ruin still shows 86 pre-existing structural failures 2026-06-22.** This is expected: this change built the repair utilities and wired them into the packet builder, but did not rebuild Well of Ruin itself. The next build through the accurate-ingest pipeline will run the repair chain (monster closure -> spatial repair -> calendar normalization) before validation.
- [X] 6.4 Run `.venv/bin/python scripts/audit_module_publishability.py --module Well_of_Ruin --json` if the module artifact is present.

  **Well of Ruin publishability still blocked 2026-06-22.** Expected: module artifacts are unchanged. A rebuild through the accurate-ingest pipeline is needed to apply the structural repairs.
- [X] 6.5 Run `openspec validate toolkit-accurate-ingest-modulebuilder-structural-repair --strict`.

  **OpenSpec validate --strict -> VALID 2026-06-22.**

## SHOULD Guidance

- Keep this slice structural. Do not add new final-editor LLM decisions here.
- Prefer shared helper extraction over duplicated closure/repair code.
- Keep repair reports compact and provider-free.
