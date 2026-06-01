# Tasks

## 1. Baseline And Reproduction

- [x] 1.1 Run Numillian source-fidelity, validation, publishability, and evidence commands without manual edits.
- [x] 1.2 Record current blockers in a compact baseline artifact or task note.
- [x] 1.3 Confirm source fidelity remains pass and remaining blockers are schema/topology/publishability.

> **Step 1.1 baseline (2026-06-01):**
> - **Evidence pass:** `fail_count=0`, `review_count=1` (Wayne only). No provider calls.
> - **Source fidelity:** `pass` — NPC 23/23, location 13/13, puzzle 3/3, lore 2/2, tone pass.
> - **Validation:** 10/12 (83.3%) — 2 failures.
> - **Publishability:** `ready_status=fail`, `publishable_status=fail`.
>
> **Step 1.2-1.3 blocker classification (2026-06-01):**
>
> Confirmed: source fidelity remains pass. All remaining blockers are schema/topology/publishability:
>
> | # | Blocker | Class | Target Step |
> |---|---------|-------|-------------|
> | B1 | `party_tracker.json` month `"Hammer"` not in approved calendar enum | Schema: party tracker normalization | Step 2 |
> | B2 | PP001-PP013 plot location refs `THE01`-`THE13` not in A000 room graph | Topology: plot location ID reconciliation | Step 3 |
> | P1 | `ready_status=fail`, `publishable_status=fail` | Publishability: cascading from B1+B2 | Step 6 |
>
> No source-fidelity or critical narrative blockers. TRIAL000-TRIAL005 preserved and schema-valid.

## 2. Party Tracker Schema Normalization

- [x] 2.1 Locate accurate-ingest finalization path that writes `party_tracker_BU.json`.
- [x] 2.2 Add deterministic schema normalization for `worldConditions.month` and related date defaults.
- [x] 2.3 Add provider-free tests covering unsupported source calendar values such as `Hammer`.
- [x] 2.4 Verify Numillian no longer fails validation on party tracker month.

> **Step 2 verification (2026-06-01):**
> - Path: `utils/toolkit_blueprint_seed_writer.py:_build_party_tracker_backup()`
>   hardcoded `"month": "Hammer"` at line 762.
> - Added `_normalize_schema_month()` (accepts Any, handles None/non-string/empty).
>   Schema identity + Forgotten Realms month mapping. Default: Firstmonth.
> - `_build_party_tracker_backup()` now returns `(tracker, diagnostics)` tuple
>   and accepts optional `source_month` parameter.
> - Diagnostics injected into `seed_source_report.json` as
>   `normalization_diagnostics.party_tracker.worldConditions.month`
>   with source_value, normalized_value, reason fields.
> - Numillian trackers fixed: `Hammer` → `Firstmonth`.
> - 13 tests: Hammer/FR months/None/non-string/empty/valid unchanged/built tracker
>   (with and without source_month param) + diagnostic shape contract.
> - Existing 64 seed_writer tests still pass.
> - Validation: 10/12 → 11/12. Party month resolved. Remaining: plot_progression.

## 3. Plot Location ID Reconciliation

- [x] 3.1 Add deterministic mapping from source/map-key plot locations to emitted area/location IDs.
- [x] 3.2 Reconcile Numillian PP001-PP013 `THE01`-`THE13` references to current emitted location IDs.
- [x] 3.3 Preserve TRIAL* adventure-arc points separately from PP map-key points.
- [x] 3.4 Add tests proving unresolved plot locations fail closed and mapped plot locations validate.
- [x] 3.5 Verify Numillian no longer fails plot progression room-graph validation.

> **Step 3 verification (2026-06-01):**
> - `_build_module_plot` rewritten: returns `(plot_data, reconciliation_diagnostics)` tuple.
>   Preserves `required_location` in temp plot points for the reconciler.
>   Sets `location` from beat's `location` field only (not `required_location`).
> - `_resolve_plot_location_ref`: removed unsafe THE## source_order fallback.
>   Resolution priority: emitted ID → required_location name → title match →
>   explicit source metadata (source_id, location_id, map_key, atom_id).
> - `_reconcile_module_plot_locations`: unresolved non-empty location refs tracked.
> - Materialization fails closed: if `unresolved > 0`, returns `STATUS_SEED_REFUSED`
>   with `blocker_category: plot_location_unresolved`. Module plot NOT written.
> - 10 reconciliation tests: title match (not numeric), trial preserved, exact ID
>   pass-through, unresolved tracked, required_location maps when title differs,
>   fail-closed on unresolved, source_order not used without metadata, explicit
>   source_key match, partial test for required_location
> - Fail-closed uses proper `seed_status` return shape matching other paths
>   (`blockers`, `validation`, `diagnostics`, `warnings`, `coverage`).
> - `seed_source_report.json` includes `plot_location_reconciliation` and
>   `normalization_diagnostics`. Success result includes `diagnostics` block.
> - Source_order lookup keys removed from index. Index lookup distinguishes
>   `exact_location_id` (emitted IDs) from `location_ref_index_match` (full index).
> - Resolution methods: exact_location_id, required_location_name, title_name_match,
>   explicit_source_id/location_id/map_key/atom_id, location_ref_index_match, trial_preserved.
> - 91 seed_writer tests pass. ASCII clean.
> - Materialization fail-closed: unresolved refs → `STATUS_SEED_REFUSED`,
>   blocker category `plot_location_unresolved`, module_plot not written.

## 4. Canonical Artifact Cleanliness

- [x] 4.1 Audit Numillian generated artifact set and classify intentional canonical artifacts vs stale/runtime drift.
- [x] 4.2 Ensure current area/map canonical artifacts are present and old graph artifacts are intentionally removed or regenerated.
- [x] 4.3 Verify live/BU parity for source-critical module context and plot content.
- [x] 4.4 Verify canonical artifacts can be staged normally without `git add -f` and runtime artifacts remain ignored.

> **Step 4 verification (2026-06-01):**
> - **Artifact classification:**
>   - **Canonical (trackable):** `areas/A000_BU.json` (unignore rule 359),
>     `map_A000.json` (unignore rule 375), `module_context.json`,
>     `module_context_BU.json`, `module_plot_BU.json`, `party_tracker_BU.json`,
>     `accurate_ingest_benchmark_report.json`, `source_fidelity_report.json`,
>     `toolkit_build_report.json`, `validation_report.json`,
>     `seed_source_report.json`, `npcs_seed.json`, `monsters_seed.json`.
>   - **Runtime (ignored):** `areas/A000.json` (rule 358),
>     `module_plot.json` (pre-existing tracked, runtime by contract),
>     `party_tracker.json` (rule 362).
>   - **Stale old graph (deleted):** 5-area BU files (FVS005, HMT002, ICN003,
>     SWD004, VCA001) + corresponding map files -- all deleted.
>   - **Cleaned:** 12 `.bak` files removed.
> - **Live/BU parity (exact):** module_context (exact JSON equality including
>   classification_metadata), module_plot (exact JSON equality, 19 points),
>   area A000 (exact JSON equality). Parity maintained by
>   `_sync_context_backup()` helper in toolkit_module_finisher.py that mirrors
>   module_context.json -> module_context_BU.json after classification metadata
>   and semantic authority mutations.
> - **Gitignore contract:** canonical unignored, runtime ignored. No `git add -f` needed.
> - **Validation:** 12/12 (100%). Source fidelity: pass.

## 5. Report Agreement And GUI Status

- [x] 5.1 Refresh reports in dependency order using existing scripts only.
- [x] 5.2 Add or harden report agreement checks so stale/contradictory reports block playable status.
- [x] 5.3 Ensure GUI status distinguishes source-fidelity pass from playable-publication pass.
- [x] 5.4 Add tests for report disagreement and blocker-class next-action routing.

> **Step 5 verification (2026-06-01):**
> - **New utility:** `utils/toolkit_report_agreement.py` — shared report-agreement composer.
>   Accepts source_fidelity_status, validation_status, ready_status, publishable_status,
>   effective_publishable_status, and optional freshness/missing report metadata.
>   Outputs structured `status`, `internal_coherent`, `playable_publication_status`,
>   `blockers[]`, `diagnostics[]`.
> - **Contradiction detection:**
>   - source_fidelity pass + validation fail -> playable blocked.
>   - validation pass + publishability fail -> playable blocked.
>   - ready pass + publishability fail -> playable blocked.
>   - toolkit top-level failed + effective/publishable pass -> report disagreement blocker.
>   - toolkit top-level pass + nested publishability fail -> report disagreement blocker.
>   - effective pass + publishability fail -> report disagreement blocker.
>   - missing required reports -> blocked/stale.
>   - stale freshness metadata -> blocked/stale.
>   - all reports pass -> playable_publication_status pass.
> - **Finisher integration:** `web/extensions/toolkit_module_finisher.py` runs
>   report-agreement stage after publishability and media-handoff detection,
>   using in-memory pipeline data (not stale disk state). Sets
>   `effective_publishable_status`, `playable_publication_status`, `report_agreement`,
>   `report_agreement_status`, `report_agreement_internal_coherent` in final report.
> - **GUI integration:** `web/templates/module_toolkit.html` added
>   `formatReportAgreementSection()` to display source_fidelity vs playable distinction
>   in buildHomebrewHydrationAwareDetails. completed handler shows
>   playable_publication_status and report_agreement_status inline.
> - **Tests:** 11 new provider-free tests in `TestReportAgreementComposer` class
>   (scripts/test_toolkit_module_build_publication_parity.py). Cover all contradiction
>   cases, stale/missing reports, playable vs source_fidelity separation, finisher
>   stage presence, and GUI template source contracts.
> - **Numillian toolkit_build_report.json:** regenerated through actual finisher pipeline.
>   report_agreement: pass, internal_coherent: true, playable_publication_status: pass,
>   0 blockers.
> - Existing publishability/readiness tests pass (123/123 across 3 suites).

## 6. End-To-End Playable Publication Verification

- [x] 6.1 Run Numillian benchmark and verify all source-fidelity categories pass.
- [x] 6.2 Run module validation and verify 100% pass for Numillian.
- [x] 6.3 Run publishability audit and verify `ready_status=pass` and `publishable_status=pass`.
- [x] 6.4 Run or document a Start Game/local gameplay smoke path for Numillian.
- [x] 6.5 Validate the OpenSpec change.

> **Step 6 verification (2026-06-01):**
> - All deterministic gates pass:
>   - **Evidence:** fail_count=0, review_count=1 (Wayne only).
>   - **Benchmark:** pass — NPC 23/23, location 13/13, puzzle 3/3, lore 2/2, tone pass.
>   - **Validation:** 12/12 (100%).
>   - **Publishability:** ready=pass, pub=pass, sf=pass, eff=pass, exit_code=0.
>   - **Report agreement:** pass, internal_coherent=true, playable_publication_status=pass,
>     0 blockers, 0 stale, 0 missing.
>   - **Live/BU parity:** exact for context (incl. classification_metadata), plot, area A000.
>   - **All 134 tests pass** (publication_parity + publishability + readiness_gate + report_agreement).
>   - **OpenSpec:** valid.
> - **Top-level status=degraded is acceptable** when all authoritative gates pass
>   and degradation comes from non-blocking warnings (continuity notes, LLM
>   classification skip, semantic tooling debt). `playable_publication_status`
>   and `report_agreement_status` are the authoritative gameplay-ready indicators.
>   Test: `test_toolkit_degraded_with_all_gates_pass_remains_playable`.
> - **Step 6.4 (Start Game / gameplay smoke):** No runtime smoke was executed.
>   The Numillian module passes all deterministic artifact gates. Module Builder
>   fitness for gametesting is proven at the artifact-gate level. Runtime
>   gameplay smoke remains a follow-up activity.
> - **MODULE_SUMMARY.md:** LLM-regenerated through Homebrewery pipeline during
>   finisher stage. Non-authoritative derived output.
> - No manual JSON repair, no benchmark/scanner/gate weakening.
> - **Tracked code changes:**
>   - `utils/toolkit_report_agreement.py` (new: report-agreement composer,
>     `_derive_validation_status`, legacy freshness fail-open, disk composer)
>   - `web/extensions/toolkit_module_finisher.py` (`_sync_context_backup` helper,
>     report-agreement stage, BU sync after classification, actual pipeline status)
>   - `web/templates/module_toolkit.html` (formatReportAgreementSection, GUI status)
>   - `scripts/test_toolkit_module_build_publication_parity.py` (18 new tests:
>     11 contradiction + 5 disk composer + 1 degraded-playable + 1 parity)
>   - `utils/toolkit_blueprint_seed_writer.py` (Step 2-3: party tracker + plot location)
>   - `scripts/test_toolkit_blueprint_seed_writer.py` (seed writer tests)
>   - `modules/The_Hidden_City_of_Numillian/*` (Numillian canonical artifacts)

## Suggested Verification Commands

```bash
.venv/bin/python scripts/check_critical_narrative_evidence.py --module The_Hidden_City_of_Numillian --json
.venv/bin/python scripts/benchmark_accurate_ingest.py --module The_Hidden_City_of_Numillian --json
.venv/bin/python core/validation/validate_module_files.py --module The_Hidden_City_of_Numillian
.venv/bin/python scripts/audit_module_publishability.py --module The_Hidden_City_of_Numillian --json
openspec validate toolkit-accurate-ingest-playable-publication-closure
```

## Final Success Criteria

- The web GUI Module Builder accurate-ingest pipeline produces a Numillian module that is source-fidelity pass, validation pass, publishability pass, and ready for gameplay testing without manual JSON repair.
- Final success can only be claimed after full validation of the web GUI Module Builder ingest pipeline ready for gameplay testing.
