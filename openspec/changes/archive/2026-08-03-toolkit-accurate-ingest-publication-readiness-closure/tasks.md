# Tasks: Toolkit Accurate-Ingest Publication Readiness Closure

## Task 1 — Baseline Regression Tests

- [x] 1.1 Create `scripts/test_publishability_closure.py` with provider-free
      tempdir-backed tests that reproduce all 4 blocker classes:
  - Continuity missing: temp module_context without `continuity` +
    `module_continuity_audit.py --strict` fails.
  - Semantic missing: temp module_context without `semantic_authority` +
    `semantic authority audit` fails.
  - Sidecar missing: temp module slug with no sidecar +
    `find_latest_sidecar_for_slug()` returns None.
  - Media missing: temp module with monster JSON but no `media/monsters/*.jpg` +
    `check_monster_media()` returns `base=False`.

**Verification:** `.venv/bin/python -m unittest scripts.test_publishability_closure.TestBlockerReproduction`

## Task 2 — Continuity + Semantic Authority Finalization Helper

- [x] 2.1 Create `utils/toolkit_publishability_finalizer.py` with:
  - `finalize_module_publishability_metadata(module_slug, module_dir)` function.
  - Calls `_ensure_continuity_contract_keys()` and `enrich_continuity_cross_refs()`
    from `scripts/homebrew_ingest_dev`.
  - Calls `enrich_module_semantic_authority()` from `utils/module_semantic_authority`.
  - Atomically writes changes to `module_context.json` and BU mirror.
  - Returns `{"status": "success"|"degraded", "changed": bool, "errors": [...], "warnings": [...]}`.

- [x] 2.2 Tests:
  - `test_continuity_block_added_when_missing`
  - `test_semantic_authority_added_when_missing`
  - `test_noop_when_both_already_present`
  - `test_fail_open_missing_plot_file`
  - `test_bu_mirror_parity`

**Verification:** `.venv/bin/python -m unittest scripts.test_publishability_closure.TestContinuitySemanticFinalization`

## Task 3 — Ingest Sidecar Persistence Helper

- [x] 3.1 Add `persist_ingest_sidecar(module_slug, module_dir, status="success")`
      to `utils/toolkit_publishability_finalizer.py` or a new helper.
  - Builds sidecar payload with required sections.
  - Writes atomically to `modules/ingest/archive/<timestamp>_<slug>.result.json`.
  - Timestamp format: `YYYYMMDD_HHMMSS`.

- [x] 3.2 Tests:
  - `test_sidecar_written_after_finalize`
  - `test_sidecar_found_by_find_latest`
  - `test_sidecar_passes_require_success_audit`
  - `test_sidecar_idempotent_overwrite`

**Verification:** `.venv/bin/python -m unittest scripts.test_publishability_closure.TestIngestSidecarPersistence`

## Task 4 — Deterministic Monster Media Placeholder Closure

- [x] 4.1 Create `utils/module_monster_media_closure.py` with:
  - `MINIMAL_JPEG_BASE64` constant (pre-computed, valid JPEG, ~107 bytes).
  - `close_monster_base_media(module_dir)` function that:
    - Scans `monsters/*.json` for slug list.
    - Checks `media/monsters/<slug>.jpg` existence.
    - Writes placeholder JPEG for each missing slug.
    - Does not overwrite existing files.
    - Returns `{"created": int, "skipped": int, "errors": [...]}`.

- [x] 4.2 Tests:
  - `test_placeholders_created_for_missing_monsters`
  - `test_existing_media_preserved`
  - `test_placeholder_is_valid_jpeg`
  - `test_base_media_detected_as_present_after_closure`
  - `test_no_pillow_dependency`

**Verification:** `.venv/bin/python -m unittest scripts.test_publishability_closure.TestMonsterMediaClosure`

## Task 5 — Accurate-Ingest/Finisher Pipeline Integration

- [x] 5.1 Wire `finalize_module_publishability_metadata()` into the
      accurate-ingest ModuleBuilder finishing path (e.g., in
      `web/extensions/toolkit_homebrew_packet_builder.py` or
      `web/extensions/toolkit_module_finisher.py`).

- [x] 5.2 Wire `close_monster_base_media()` into the finishing path, after
      monster closure report stage.

- [x] 5.3 Wire `persist_ingest_sidecar()` into the finishing path, at the end
      of successful build stages.

- [x] 5.4 Tests (tempdir-backed, no server):
  - `test_finisher_adds_continuity`
  - `test_finisher_adds_semantic_authority`
  - `test_finisher_adds_sidecar`
  - `test_finisher_closes_monster_media`

**Verification:** `.venv/bin/python -m unittest scripts.test_publishability_closure.TestPipelineIntegration`

## Task 6 — Well_of_Ruin Remediation

- [x] 6.1 Apply `finalize_module_publishability_metadata()` to Well_of_Ruin
      module (continuity + semantic authority).
- [x] 6.2 Apply `close_monster_base_media()` to Well_of_Ruin module.
- [x] 6.3 Apply `persist_ingest_sidecar()` to Well_of_Ruin module.
- [x] 6.4 Verify all four blocker classes resolved:
  - `.venv/bin/python scripts/audit_module_publishability.py --module Well_of_Ruin --json` exits 0.
  - `.venv/bin/python core/validation/validate_module_files.py --module Well_of_Ruin` passes.
  - `.venv/bin/python scripts/homebrew_sidecar_audit.py --slug Well_of_Ruin --require-success` passes.

**Verification:** All three commands above exit 0.

## Task 7 — Full Regression

- [x] 7.1 Run all related test suites to confirm no regressions:
  - `.venv/bin/python -m unittest scripts.test_publishability_closure`
  - `.venv/bin/python -m unittest scripts.test_toolkit_module_build_publication_parity`
  - `.venv/bin/python -m unittest scripts.test_module_semantic_authority`
  - `.venv/bin/python -m unittest scripts.test_module_continuity_audit`

**Verification:** All test suites pass.
