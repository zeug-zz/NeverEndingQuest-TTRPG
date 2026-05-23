# Tasks

## 0. Scaffold and Regression Locks

- [x] 0.1 Create OpenSpec artifacts for this change.
- [x] 0.2 Add regression test for punctuation-normalized build-fidelity matching.
- [x] 0.3 Add regression test documenting that `but this is not true` must not be emitted as NPC/actor.
- [x] 0.4 Add regression test documenting current benchmark blockers for `skull_riddle` and `kill_the_dog_mindscape`.
- [x] 0.5 Audit scaffold against `plans/accurate-ingest-fix.md` and revise bridge-fix scope to reuse existing topology/triage artifacts.

## 1. Punctuation-Normalized Build Fidelity

- [x] 1.1 Add trailing markdown/table punctuation stripping to `_normalize_name()` in `utils/toolkit_build_fidelity.py`.
- [x] 1.2 Verify `_normalize_name("Red Skull:")` matches `_normalize_name("Red Skull")`.
- [x] 1.3 Verify all existing build-fidelity tests pass.
- [x] 1.4 Verify distinct names remain distinct after normalization.

## 2. Puzzle Preservation in Synthetic Blueprint

- [x] 2.1 Load `plot_topology_report.json` in the Numillian rebuild path before synthetic fallback.
- [x] 2.2 Update `_build_synthetic_blueprint_from_packet()` or a helper to accept topology/packet puzzle sources.
- [x] 2.3 Populate `puzzle_graph` from `plot_topology_report.puzzle_chains`, `plot_topology_report.trials`, or normalized packet puzzle fields without inventing content.
- [x] 2.4 Update `coverage["puzzles_in_blueprint"]` to match populated `puzzle_graph`.
- [x] 2.5 Log or record warning when topology and packet puzzle data are absent.
- [x] 2.6 Verify `skull_riddle` and `kill_the_dog_mindscape` appear in benchmark output after rebuild.

## 3. Prose Phrase Actor Filtering

- [x] 3.1 Load `entity_candidate_triage_report.json` in the synthetic fallback path when available.
- [x] 3.2 Exclude synthetic NPC roster entries rejected by triage or adjudicated as non-actors.
- [x] 3.3 Apply existing `utils.toolkit_entity_candidate_triage` narrative-phrase prefilter only when no triage decision exists.
- [x] 3.4 Record filtered candidates in synthetic blueprint warnings or metadata for auditability.
- [x] 3.5 Verify legitimate NPCs (Dog-Growl, Book-shut, Deflation, Alms-plate) remain unaffected.
- [x] 3.6 Verify `but this is not true` does not appear in `module_context.json`, `npcs_seed.json`, or semantic references after rebuild.

## 4. Rebuild and Reassess

- [x] 4.1 Run Numillian production rebuild.
- [ ] 4.2 Run benchmark and confirm `source_fidelity_status` is no longer blocked.
- [x] 4.3 Run validation and publishability audit.
- [x] 4.4 Report dirty file count and reassess publication readiness.

## 5. Verification

- [x] 5.1 Run compile checks for all modified files.
- [x] 5.2 Run targeted regression tests.
- [x] 5.3 Run relevant accurate-ingest and publishability tests.
- [x] 5.4 Validate the OpenSpec change.

## Suggested Verification Commands

```bash
.venv/bin/python -m py_compile utils/toolkit_build_fidelity.py scripts/rebuild_numillian_accurate_ingest.py
.venv/bin/python -m unittest -q scripts.test_toolkit_build_fidelity
.venv/bin/python -m unittest -q scripts.test_toolkit_entity_candidate_triage
.venv/bin/python -m unittest -q scripts.test_toolkit_blueprint_enrichment_patches
.venv/bin/python -m unittest -q scripts.test_accurate_ingest_numillian_benchmark
.venv/bin/python -m unittest -q scripts.test_accurate_ingest_numillian_end_to_end
.venv/bin/python scripts/rebuild_numillian_accurate_ingest.py --json
.venv/bin/python scripts/benchmark_accurate_ingest.py --module The_Hidden_City_of_Numillian --json
.venv/bin/python scripts/audit_module_publishability.py --module The_Hidden_City_of_Numillian --json
.venv/bin/python core/validation/validate_module_files.py --module The_Hidden_City_of_Numillian
openspec validate toolkit-accurate-ingest-numillian-source-fidelity-fix
```
