# Builder Prompt - Deepseek V4

Use this prompt for Deepseek V4 to implement the change step by step.

```markdown
Implement OpenSpec `toolkit-accurate-ingest-playable-publication-closure`.

Mission:
The user needs to know that when they input Numillian or any other 5e adventure narrative/PDF/MD into the web GUI Module Builder accurate-ingest pipeline, the output is a playable, publishable NEQ-TTRPG module suitable for library staff and patrons. Source fidelity alone is not enough. Final success is full validation of the GUI Module Builder ingest pipeline ready for gameplay testing.

Hard constraints:
- Use `.venv/bin/python` for Python commands.
- Do not weaken source-fidelity benchmarks, scanners, validation gates, publishability gates, or thresholds.
- Do not use `MODULE_SUMMARY.md` as source input.
- Do not manually edit report-only status fields to force pass.
- Do not hand-patch Numillian as the success path. Fix the pipeline/post-build deterministic normalizers so future GUI ingests benefit.
- Keep source-fidelity repair utilities intact.
- Mark tasks complete only after verification.
- Do not archive until all Step 6 success criteria pass.

Current known Numillian state:
- Source fidelity passes.
- Critical narrative evidence passes.
- Validation fails on party month `Hammer` and PP001-PP013 location refs `THE01`-`THE13` not resolving against the A000/A01-A18 room graph.
- Publishability fails because validation/readiness gates fail.

Implementation sequence:

1. Baseline reproduction
   - Run evidence, benchmark, validation, and publishability commands.
   - Record exact blockers in `tasks.md`.
   - Confirm source fidelity remains pass before changing anything.

2. Party tracker schema normalization
   - Find the accurate-ingest/finalizer path that writes `party_tracker_BU.json`.
   - Add deterministic schema-normalization for `worldConditions.month` and related date defaults.
   - Add tests with unsupported calendar values such as `Hammer`.
   - Verify Numillian validation no longer fails on month enum.

3. Plot/location ID reconciliation
   - Find where ModuleBuilder/seed writer/finalizer emits plot point `location` refs.
   - Add a deterministic reconciliation pass that maps source/map-key IDs to actual emitted location IDs.
   - For Numillian, reconcile PP001-PP013 from `THE01`-`THE13` to the actual A000/A01-A18 graph without deleting the trial arc.
   - Add tests proving unresolved mappings fail closed and resolved mappings pass.
   - Verify plot progression validation no longer reports room graph errors.

4. Canonical artifact cleanliness
   - Audit the generated Numillian artifact set.
   - Decide which deleted old area/map artifacts are intentional stale graph cleanup and which are accidental.
   - Ensure current canonical area/map artifacts are complete, live/BU parity is correct, and runtime files remain ignored.
   - Verify canonical artifacts can be staged without `git add -f`.

5. Report agreement and GUI status
   - Refresh reports in dependency order: validation -> benchmark/source fidelity -> toolkit build -> publishability.
   - Add/harden code so stale contradictory report categories block playable status.
   - Ensure GUI status says not playable when any gate fails, even if source fidelity passes.
   - Add tests for report disagreement and next-action blocker routing.

6. End-to-end success verification
   - Run:
     `.venv/bin/python scripts/check_critical_narrative_evidence.py --module The_Hidden_City_of_Numillian --json`
     `.venv/bin/python scripts/benchmark_accurate_ingest.py --module The_Hidden_City_of_Numillian --json`
     `.venv/bin/python core/validation/validate_module_files.py --module The_Hidden_City_of_Numillian`
     `.venv/bin/python scripts/audit_module_publishability.py --module The_Hidden_City_of_Numillian --json`
     `openspec validate toolkit-accurate-ingest-playable-publication-closure`
   - Final success requires source fidelity pass, validation 100% pass, publishability pass, report agreement, and GUI/playable status ready for gameplay testing.

Report after each step:
- Files changed.
- Commands run and results.
- Whether any report/status was manually edited.
- Current blocker class, if any.
- Whether Step 6 final success criteria are met.
```
