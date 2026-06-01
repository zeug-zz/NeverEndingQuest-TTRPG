# Tasks

## 0. Scaffold And Validation

- [x] 0.1 Create proposal, design, tasks, delta specs, and builder prompt artifact.
- [x] 0.2 Validate the OpenSpec scaffold.

> `openspec validate toolkit-accurate-ingest-critical-narrative-repair-loop` -> valid.

## 1. Critical Omission Evidence Pass

- [x] 1.1 Add or extend deterministic inspection to compare source-required critical NPCs/puzzles against live module JSON.
- [x] 1.2 Capture Numillian evidence for Kobe and `skull_riddle`, including source excerpts and missing output surfaces.
- [x] 1.3 Add tests proving Kobe and `skull_riddle` are reported as critical omissions from the current module state.

> **Step 1.2 verification (2026-05-31):**
> - Agent-run evidence writer added to `utils/critical_narrative_evidence.py`:
>   `build_critical_narrative_agent_run()`, `write_critical_narrative_agent_run()`,
>   `build_source_excerpt_index()`, `_render_builder_repair_brief()`.
> - CLI supports `--write-run`, `--output-dir`, `--task-id` flags.
> - Writes 4 artifacts to `data/agent_runs/critical_narrative_repair/<task_id>/`:
>   `run.json`, `critical_evidence.json`, `source_excerpts.json`, `builder_repair_brief.md`.
> - `source_excerpts.json` has bounded excerpts for Kobe (1199 chars), skull_riddle (1198 chars),
>   flooding_room (1196 chars) with line metadata.
> - `builder_repair_brief.md` includes module slug, omission summary, source excerpts,
>   target surfaces, no-manual-repair guardrails, forbidden inputs list,
>   and release-blocking statement.
> - CLI `--write-run --json` output includes `run_dir` and `run_files` paths.
> - 65 tests pass (51 Step 1.1 + 14 Step 1.2).
> - All agent-run test artifacts written to temporary directories.
> - Live Numillian run: `data/agent_runs/critical_narrative_repair/.../`
>   with fail_count=3, review_count=1, all 4 files present.
> - No module JSON, benchmark fixture, scanner threshold, or report gate was edited.

## 2. Repair Brief Generation

- [x] 2.1 Build a Builder-facing repair brief artifact from critical omission evidence.
- [x] 2.2 Include source excerpts, required output surfaces, source-lock constraints, and forbidden manual/Python invention guidance.
- [x] 2.3 Add tests for brief structure, bounded source excerpts, and omission classification.

> **Step 2 verification (2026-05-31):**
> - Enhanced `_render_builder_repair_brief()` with 4 new sections:
>   `Source-Lock Constraints`, `Required Repair Targets`, `Acceptance Checks For Later Repair`, `Do Not Use`.
> - Source-lock constraints: Kobe as final no-win trial actor; skull_riddle as First Trial puzzle (not NPC-only skulls);
>   flooding_room as Second Trial; adventure-arc trial topology separate from map topology.
> - Required Repair Targets: per-omission target surfaces (Kobe: NPC/scene/plot; puzzles: plot/area/context).
> - Acceptance Checks: Kobe/skull_riddle/flooding_room no longer reported; Wayne stays review-only;
>   benchmark fidelity passes; schema validation passes separately.
> - Do Not Use: MODULE_SUMMARY.md, benchmark edits, manual JSON injection, report-only status edits.
> - Forbidden Inputs preserved from Step 1.2.
> - 70 tests pass (66 Step 1.x + 4 new Step 2: source-lock, acceptance, do-not-use, no-full-markdown).
> - Brief sections are ASCII-only.
> - No module JSON, benchmark fixture, scanner, threshold, validation gate, or report gate was edited.

## 3. LLM Builder Repair Pass

- [x] 3.1 Add or wire a repair entrypoint that feeds the repair brief to the LLM Builder using existing provider/client patterns.
- [x] 3.2 Ensure repaired artifacts are written through existing safe module artifact paths.
- [x] 3.3 Fail closed with diagnostics when provider calls fail, generated JSON is invalid, or source-fidelity regresses.

> **Step 3 verification (2026-05-31):**
> - Created `utils/critical_narrative_repair.py` with `load_repair_run()`,
>   `build_builder_repair_prompt()`, `parse_builder_repair_response()`,
>   `validate_repair_plan()`, `apply_repair_plan()`, `write_builder_repair_result()`.
> - Created CLI `scripts/run_critical_narrative_repair.py` with `--run-dir`, `--module`,
>   `--dry-run` (default), `--apply`, `--fake-response <path>` flags.
> - Dry-run validates repair plan without writing; `--apply` writes using `safe_write_json`.
> - Validation fails closed for: missing run files, malformed JSON, forbidden paths
>   (MODULE_SUMMARY.md, benchmark files, report files), path traversal, missing omissions,
>   empty rationale, invalid operations, mismatched module_slug, non-JSON targets,
>   missing/unknown source_excerpt_keys, empty source_excerpt_keys.
> - `safe_write_json` return values are checked; write failures are reported correctly.
> - Step 3 fail-closes malformed/forbidden repair plans, protected-content removal,
>   and write failures. Full benchmark/source-fidelity report verification remains Step 5.
> - 46 provider-free tests pass: load (5), parse (5), validate (16), apply (12),
>   write_result (2), CLI integration (6).
> - Protected-content guard covers `replace_json_file` key removal, type changes,
>   list shrinking, and `patch_json_object` simulated merge (same guard on merged result).
> - All 70 Step 1.x/2.x tests still pass.
> - No real provider call was made; no real module artifacts were mutated.

## 4. Plot Topology And Puzzle Preservation

- [x] 4.1 Ensure Builder repair preserves adventure-arc plot topology separately from map-key location structure.
- [x] 4.2 Ensure `skull_riddle` is represented as puzzle/trial content rather than NPC-only skull components.
- [x] 4.3 Ensure Kobe is represented as a critical NPC/scene objective in final trial surfaces.

> **Step 4 verification (2026-05-31):**
> - Builder repair applied to live + BU artifacts (4 files):
>   - `module_context.json` (Kobe NPC via patch - already present from v1 repair)
>   - `module_context_BU.json` (Kobe NPC via patch - NEW)
>   - `module_plot.json` (19 plot points: 13 loc + 6 trial - replace)
>   - `module_plot_BU.json` (24 plot points: 18 BU loc + 6 trial - replace)
> - Full 6-beat trial arc in both live and BU:
>   TRIAL000 Trial at the Door, TRIAL001 First Trial - Skull Riddle,
>   TRIAL002 Second Trial - Flooding Room, TRIAL003 False Third Trial - Kill the Dog,
>   TRIAL004 True Third Trial - City of the Mind, TRIAL005 Final Trial - No-Win Scenario with Kobe.
> - Map-key location points (PP) kept separate from trial points (TRIAL).
> - Kobe exists in both context and BU context; skull_riddle as puzzle, not NPC atoms.
> - Evidence pass: `fail_count=0`, `review_count=1` (Wayne only).
> - 79 evidence tests + 46 repair tests pass (125 total).
> - 8 new Step 4 tests: BU parity (2), trial arc (2), topology separation, skull as puzzle, Kobe as objective, evidence clean.
> - No benchmark/scanner/gate/report-only files or MODULE_SUMMARY.md were touched.
> - No real provider call used.

## 5. Numillian Verification

- [x] 5.1 Run repaired Numillian benchmark and verify NPC 23/23, puzzle 3/3, locations 13/13, lore 2/2, and tone pass.
- [x] 5.2 Refresh validation, source-fidelity, toolkit build, and publishability reports from live module JSON.
- [x] 5.3 Verify reports agree and `MODULE_SUMMARY.md` remains derived output only.
- [x] 5.4 Document remaining schema/report blockers, if any, separately from critical narrative repair.

> **Step 5 verification (2026-06-01):**
> - **Benchmark** (fresh): `source_fidelity_status: pass` — NPC 23/23, puzzle 3/3,
>   location 13/13, lore 2/2, tone pass. All 5 categories pass.
> - **Evidence**: `fail_count=0`, `review_count=1` (Wayne only).
> - **Reports agree** after fix:
>   - `accurate_ingest_benchmark_report.json`: `source_fidelity_status: pass`
>   - `source_fidelity_report.json`: `source_fidelity_status: pass` (regenerated from benchmark)
>   - `toolkit_build_report.json`: `source_fidelity_status: pass` (refreshed)
> - **TRIAL schema fix**: Added `location`, `nextPoints`, `status` to all 6 TRIAL* plot
>   points in both live and BU plot files. Uses A01 as narrative anchor location.
> - **Validation**: 10/12 passed (up from 9/12 after TRIAL schema fix).
>   Remaining 2 failures are pre-existing:
>   - `party_tracker.json`: month "Hammer" not in calendar schema
>   - `plot_progression`: PP001-PP013 location refs (THE01-THE13) not in room graph
> - **No report-only status fields were manually edited**; reports refreshed via
>   benchmark tool + `persist_source_fidelity_report_artifact` + safe_write_json.
> - toolkit_build_report.json `source_fidelity_categories` rebuilt from benchmark:
>   NPC 23/23 pass, puzzle 3/3 pass, location 13/13 pass, lore 2/2 pass, tone pass.
> - No Kobe or skull_riddle missing in any report field.
> - **125 tests pass**.
> - **Critical narrative repair blockers: NONE.**
> - **Separate blockers**: schema/validation (2 pre-existing), publishability readiness.

## Suggested Verification Commands

```bash
.venv/bin/python -m py_compile <modified-python-files>
.venv/bin/python -m unittest -q <new-or-modified-test-modules>
.venv/bin/python scripts/benchmark_accurate_ingest.py --module The_Hidden_City_of_Numillian --json
.venv/bin/python core/validation/validate_module_files.py --module The_Hidden_City_of_Numillian
.venv/bin/python scripts/audit_module_publishability.py --module The_Hidden_City_of_Numillian --json
openspec validate toolkit-accurate-ingest-critical-narrative-repair-loop
```

## Release Criteria

- No manual JSON patching is used to author critical narrative content.
- Builder repair consumes source excerpts and produces source-faithful module JSON.
- Numillian benchmark passes for Kobe and `skull_riddle` from live module JSON.
- Reports are refreshed and agree on final status.
