# Tasks

## 0. Scaffold And Planning

- [x] 0.1 Update `plans/accurate-ingest-fix.md` to mark ModuleBuilder handoff archived and identify `toolkit-accurate-ingest-backstage-audit-mvp` as next.
- [x] 0.2 Create OpenSpec proposal, design, tasks, delta specs, and initial builder prompt.
- [x] 0.3 Validate OpenSpec scaffold.
> `openspec validate toolkit-accurate-ingest-backstage-audit-mvp` -> valid.

## 1. Read-Only Audit Foundation

- [x] 1.1 Add deterministic artifact discovery/parsing helpers and tests for accurate-ingest audit inputs.
> Files: `utils/accurate_ingest_backstage_audit.py` (new, ~160 lines), `scripts/test_accurate_ingest_backstage_audit.py` (new, ~300 lines, 17 tests).
> Verification: py_compile -> PASS, 17/17 tests PASS, `openspec validate` -> valid.
- [x] 1.2 Add report-disagreement and domain-finding builder for source-fidelity, build-fidelity, validation, readiness, semantic publishability, and artifact-presence domains.
> Functions: `build_audit_findings()`, `_find_artifact_by_key()`, `_severity_for_status()`, `_build_artifact_presence_findings()`, `_build_domain_status_finding()`, `_build_validation_finding()`, `_build_report_consistency_findings()`.
> Verification: py_compile -> PASS, 27/27 tests PASS, `openspec validate` -> valid.
- [x] 1.3 Add a narrow CLI entrypoint for `accurate-ingest-audit --module <slug>` that writes runtime audit artifacts.
> File: `scripts/run_backstage_agent.py` (new, ~210 lines).
> Functions: `make_task_id()`, `write_json_atomic()`, `counts_by_severity()`, `collect_evidence_refs()`, `build_recommendation()`, `run_accurate_ingest_audit()`, `main()`.
> Verification: py_compile -> PASS, `--help` -> PASS, `--module nonexistent_module` -> exits 1 with clear error, smoke audit against Numillian -> 4 JSON files written, 27/27 backstage audit tests PASS, `openspec validate` -> valid.
- [x] 1.4 Add mutation-safety tests that hash module artifacts before and after an audit run.
> New class: `TestBackstageAgentCliMutationSafety` (2 methods: `test_cli_runner_does_not_mutate_module`, `test_missing_module_produces_error_output`).
> Verification: py_compile -> PASS, 29/29 tests PASS, `openspec validate` -> valid.

## 2. Script Parity And Evidence Commands

- [x] 2.1 Add optional read-only benchmark command collection in JSON mode without persisting refreshed reports.
> Functions: `run_benchmark_command()`, `_parse_json_stdout()`, `_compact_benchmark_summary()`, `_preview_text()`. CLI flag: `--include-benchmark-command`. Default disabled; enabled runs `benchmark_accurate_ingest.py --module --json --out <run_dir>/command_outputs/benchmark`.
> Tests: `TestBackstageAgentBenchmarkCommand` (4 methods: disabled default, enabled benchmark evidence, command argument/runtime-out contract, invalid JSON warning finding).
> Verification: py_compile -> PASS, 33/33 tests PASS, `openspec validate` -> valid, smoke audit with `--include-benchmark-command` against Numillian -> exit_code=0 stdout_parse_status=ok parsed_summary present.
- [x] 2.2 Add optional read-only publishability command collection in JSON mode without persisting refreshed reports.
> Functions: `run_publishability_command()`, `_compact_publishability_summary()`. CLI flag: `--include-publishability-command`. Both flags can be enabled simultaneously; evidence stored under `evidence.json.commands.{benchmark,publishability}`.
> Tests: `TestBackstageAgentPublishabilityCommand` (5 methods: disabled default, enabled evidence, command args contract, both commands enabled, invalid JSON warning finding).
> Verification: py_compile -> PASS, 38/38 tests PASS, `openspec validate` -> valid, smoke audit with both flags against Numillian -> benchmark exit_code=0 parse=ok, publishability exit_code=1 parse=ok, both compact summaries present.
- [x] 2.3 Capture command stdout parse status, exit code, and compact summaries as evidence.
> Tests: `TestParseJsonStdout` (5 methods: valid JSON object, blank, empty, malformed, JSON array rejected), `TestPreviewText` (4 methods: short, long capped, exact limit, default limit), `TestBackstageAgentCommandEvidenceContract` (6 methods: benchmark exact evidence shape, benchmark parsed_summary compact, benchmark fail evidence_refs, publishability exact evidence shape, publishability parsed_summary compact, publishability fail evidence_refs).
> Verification: py_compile -> PASS, 53/53 tests PASS, `openspec validate` -> valid.
- [x] 2.4 Ensure command failures become findings and never silently downgrade deterministic failures to pass.
> Functions: `_build_command_findings()`. Tests: `TestBackstageAgentCommandFailureFindings` (6 methods: benchmark nonzero exit blocker, publishability nonzero exit blocker, timeout blocker, parse-only warning, success no finding, recommendation not no_action when blocker).
> Updated existing tests: `test_invalid_json_stdout_produces_blocker_finding` (benchmark), `test_invalid_json_produces_blocker` (publishability).
> Verification: py_compile -> PASS, 59/59 tests PASS, `openspec validate` -> valid.

## 3. Audit Report And Recommendation Contract

- [x] 3.1 Emit `run.json`, `evidence.json`, `audit_report.json`, and `recommendation.json` to a runtime-only output directory.
> New class: `TestBackstageAgentRuntimeOutputContract` (8 methods: `test_default_output_path_under_data_agent_runs`, `test_four_top_level_json_files_written`, `test_command_outputs_not_created_without_command_flags`, `test_four_files_with_command_flags_no_module_mutation`, `test_task_id_consistent_across_report_files`, `test_run_json_metadata_fields`, `test_no_output_files_under_module_directory`, `test_no_module_path_in_output_file_relative_paths`).
> The `run_accurate_ingest_audit()` function already writes the four JSON files to `<output_dir>/<task_id>/`. Default base is `DEFAULT_OUTPUT_BASE = "data/agent_runs/accurate_ingest_audit"`. `run.json.output_dir` equals the actual run path. `run.json.module_path` equals the resolved module path. `run.json.task_id`, `audit_report.json.task_id`, and `recommendation.json.task_id` all match. No files are ever written under `modules/<slug>/`. No module files are mutated.
> Verification: py_compile -> PASS, 67/67 tests PASS, `openspec validate` -> valid.
- [x] 3.2 Add report schema tests for evidence references, grouped findings, report consistency summary, and next-step recommendation.
> Functions added: `_group_findings_by_domain()`, `_build_report_consistency_summary()` in `run_backstage_agent.py`. Audit payload extended with `grouped_findings`, `report_consistency_summary`, `next_step_recommendation` fields.
> New class: `TestBackstageAgentReportSchema` (9 methods: `test_grouped_findings_contains_all_findings_exactly_once`, `test_grouped_findings_domain_keys_match_finding_domains`, `test_report_consistency_summary_present_when_disagreement`, `test_report_consistency_summary_empty_when_all_pass`, `test_next_step_recommendation_matches_recommendation_json`, `test_next_step_recommendation_structure`, `test_evidence_refs_resolve_to_artifact_keys`, `test_finding_evidence_keys_appear_in_evidence_refs`, `test_command_evidence_refs_resolve_to_command_entries`).
> Verification: py_compile -> PASS, 76/76 tests PASS, `openspec validate` -> valid.
- [x] 3.3 Add `.gitignore` protection for generated `data/agent_runs/` artifacts if the implementation writes there.
> Added `data/agent_runs/` at `.gitignore:44` under the existing `data/` runtime entries. No unignore overrides exist for this path.
> Verification: `git check-ignore -v data/agent_runs/accurate_ingest_audit/some_task_id/run.json` -> `.gitignore:44:data/agent_runs/` (no `!` prefix). `openspec validate` -> valid.
- [x] 3.4 Add Numillian-oriented fixture coverage for source-fidelity pass plus stale toolkit/publishability failure disagreement.
> New class: `TestBackstageAgentNumillianFixture` (2 methods: `test_numillian_disagreement_report_consistency`, `test_numillian_fixture_no_module_mutation`).
> Uses temp fixture with source-fidelity pass and stale/failing toolkit report. Asserts report_consistency finding, `recommended_action="investigate_disagreement"`, `report_consistency_summary.count > 0`, `next_step_recommendation.recommended_action` matching. Asserts no fixture files mutated and no new files under `modules/Test_Numillian/`.
> Verification: py_compile -> PASS, 78/78 tests PASS, `openspec validate` -> valid.

## 4. Final Verification

- [x] 4.1 Run compile checks for modified Python files.
> `.venv/bin/python -m py_compile scripts/run_backstage_agent.py utils/accurate_ingest_backstage_audit.py scripts/test_accurate_ingest_backstage_audit.py` -> PASS.
- [x] 4.2 Run targeted backstage audit tests.
> `.venv/bin/python -m unittest -q scripts.test_accurate_ingest_backstage_audit` -> 78/78 PASS.
- [x] 4.3 Run existing accurate-ingest/publishability tests touched by the implementation.
> `.venv/bin/python -m unittest -q scripts.test_audit_module_publishability` -> 26/26 PASS.
- [x] 4.4 Validate OpenSpec change.
> `openspec validate toolkit-accurate-ingest-backstage-audit-mvp` -> valid.

## Suggested Verification Commands

```bash
.venv/bin/python -m py_compile scripts/run_backstage_agent.py utils/accurate_ingest_backstage_audit.py scripts/test_accurate_ingest_backstage_audit.py
.venv/bin/python -m unittest -q scripts.test_accurate_ingest_backstage_audit
.venv/bin/python -m unittest -q scripts.test_audit_module_publishability
openspec validate toolkit-accurate-ingest-backstage-audit-mvp
```
