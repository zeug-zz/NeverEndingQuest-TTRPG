## 1. Input Loading And Validation

- [x] 1.1 Add audit-run artifact loader and task identity validator.
> Created `scripts/prepare_builder_from_backstage_audit.py` with `load_audit_run_artifacts(run_dir)` -- loads the four required audit artifacts (`run.json`, `evidence.json`, `audit_report.json`, `recommendation.json`), validates task identity consistency, returns structured dict with artifact data and source paths.
> Created `scripts/test_builder_audit_briefing.py` with `TestBuilderAuditBriefingLoader` (8 tests: valid load, missing artifact, missing directory, task ID mismatch, missing task_id field, metadata paths, malformed JSON, read-only).
> Verification: py_compile -> PASS, 8/8 tests PASS, `openspec validate` -> valid.
- [x] 1.2 Add missing-artifact and task-id mismatch tests.
> Covered in `scripts/test_builder_audit_briefing.py`: `test_missing_artifact_raises_error`, `test_missing_directory_raises_error`, `test_task_id_mismatch_raises_error`, `test_missing_task_id_field_raises_error`.
> Verification from Step 1.1: py_compile -> PASS, 8/8 tests PASS.

## 2. Builder Brief Output

- [x] 2.1 Emit `builder_brief.json` from a valid audit run directory.
> Added `build_builder_brief(loaded)` and `write_builder_brief_json(run_dir)` to `scripts/prepare_builder_from_backstage_audit.py`. Writes `builder_brief.json` atomically into the run directory with task_id, module_slug, recommended_action, reason, evidence_refs, finding_count, counts_by_severity, grouped_finding_counts, top_findings, report_consistency_summary, source_artifact_paths, and builder_lane.
> New test class: `TestBuilderAuditBriefingOutput` (13 tests: file creation, required fields, recommendation match, audit+recommendation evidence refs, report_consistency preserved, grouped counts, source paths, no markdown context, no files outside run dir, module files not mutated, builder_lane classified, bounded top-finding messages, read-back equality). Also `TestBuilderAuditBriefingGroupedFindingCounts` (4 tests: empty, single domain, multiple domains, empty list).
> Verification: py_compile -> PASS, 24/24 tests PASS, `openspec validate` -> valid.
- [x] 2.2 Emit `builder_prompt_context.md` from the same compact brief data.
> Added `build_builder_prompt_context(brief)` and `write_builder_prompt_context_md(run_dir)` to `scripts/prepare_builder_from_backstage_audit.py`. Reuses existing `builder_brief.json` if present; generates fresh brief from audit artifacts if absent. Markdown includes compact module summary, recommendation action/reason, classified builder lane, evidence refs, severity/domain counts, top findings, report-consistency summary, and advisory warning.
> New test class: `TestBuilderAuditBriefingPromptContext` (17 tests: file creation, module slug, module summary section, task ID, recommendation action, reason, classified builder lane, evidence refs, finding count, severity breakdown, domain breakdown, top findings, advisory warning, no files outside run dir, module not mutated, reuse existing brief, generate when absent). Also `TestBuilderAuditBriefingLaneText` (4 tests: None->pending, string passthrough, empty string, falsey non-None).
> Verification: py_compile -> PASS, 46/46 tests PASS, `openspec validate` -> valid.
- [x] 2.3 Add schema tests proving compact fields, evidence refs, grouped finding counts, and report-consistency summary are preserved.
> Added `TestBuilderAuditBriefingContractSchema` to `scripts/test_builder_audit_briefing.py` (18 tests: type/shape assertions for all compact fields, no raw findings/evidence lists in brief, no raw JSON or full findings array in markdown, markdown evidence refs match brief, report-consistency blocker count in markdown matches brief, grouped domain names appear in markdown, no raw artifact blocks in markdown, source artifact paths point to files).
> Verification: py_compile -> PASS, 64/64 tests PASS, `openspec validate` -> valid.

## 3. Safety And Routing

- [x] 3.1 Add deterministic builder-lane classification for audit recommendation actions.
> Added `classify_builder_lane(recommended_action, evidence_refs)` and `LANE_MAPPING` to `scripts/prepare_builder_from_backstage_audit.py`. Mappings: investigate_disagreement -> diagnose_reports, repair_artifacts -> repair_artifacts, openspec_work -> openspec_work, review_warnings -> review_warnings, no_action -> no_action. Unknown actions default to diagnose_reports. Returns dict with builder_lane, builder_lane_rationale, builder_lane_evidence_refs. `build_builder_brief()` now uses `classify_builder_lane` instead of hardcoded None. Markdown includes `Rationale:` line.
> New test class: `TestBuilderAuditBriefingLaneClassification` (14 tests: 5 known mapping tests, unknown action, empty action, rationale present, evidence refs present, evidence refs default empty, brief fields present, markdown includes lane + rationale, no extra files, no module mutation).
> Updated 3 impacted existing tests: `test_builder_lane_is_null` -> `test_builder_lane_is_classified`, `test_brief_builder_lane_is_none` -> `test_brief_builder_lane_is_known_lane`, `test_contains_builder_lane_pending` -> `test_contains_classified_lane`.
> Verification: py_compile -> PASS, 78/78 tests PASS, `openspec validate` -> valid.
- [x] 3.2 Add runtime-only output and module non-mutation tests.
> Added `TestBuilderAuditBriefingRuntimeOnly` to `scripts/test_builder_audit_briefing.py` (6 tests: brief writes only builder_brief.json, context writes only builder_prompt_context.md when brief exists, no outputs under module dir, SHA-256 hashes unchanged after brief writer, SHA-256 hashes unchanged after context writer, no new module report artifacts created).
> Verification: py_compile -> PASS, 84/84 tests PASS, `openspec validate` -> valid.
- [x] 3.3 Add no-provider/no-builder/no-refresh source-contract tests.
> Added `TestBuilderAuditBriefingNoMutatingWorkflows` to `scripts/test_builder_audit_briefing.py` (10 tests: no create_chat_client/OpenAI, no openrouter, no requests imports, no ModuleBuilder, no seed_writer, no benchmark_accurate_ingest, no audit_module_publishability, no readiness_repair/character_creation_audit, no media_generation/generate_and_save_portrait, no module_finisher/toolkit_module_finisher).
> Verification: py_compile -> PASS, 94/94 tests PASS, `openspec validate` -> valid.

## 4. Final Verification

- [x] 4.1 Run compile checks for modified Python files.
> `.venv/bin/python -m py_compile scripts/prepare_builder_from_backstage_audit.py scripts/test_builder_audit_briefing.py` -> PASS.
- [x] 4.2 Run targeted builder-brief tests.
> `.venv/bin/python -m unittest -q scripts.test_builder_audit_briefing` -> PASS (94/94).
- [x] 4.3 Run existing backstage audit tests for compatibility.
> `.venv/bin/python -m unittest -q scripts.test_accurate_ingest_backstage_audit` -> PASS (78/78).
- [x] 4.4 Validate OpenSpec change.
> `openspec validate toolkit-accurate-ingest-builder-audit-briefing` -> valid.
