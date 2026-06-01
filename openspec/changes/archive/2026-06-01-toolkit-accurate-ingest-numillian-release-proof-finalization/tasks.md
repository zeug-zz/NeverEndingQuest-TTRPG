# Tasks

## 0. Scaffold And Validation

- [x] 0.1 Create proposal, design, tasks, delta specs, and builder prompt artifact.
- [x] 0.2 Validate the OpenSpec scaffold.

> `openspec validate toolkit-accurate-ingest-numillian-release-proof-finalization` -> valid.

## 1. Diagnostic-Only Current State

- [x] 1.1 Run validation, benchmark, publishability, and targeted artifact inspection for Numillian without mutating module files.
- [x] 1.2 Record exact blockers and classify each as semantic, monster materialization, report freshness, or publication-only.
    - Diagnostics saved to `plans/accurate-ingest-numillian-release-proof-diagnostics.md`.
    - Blockers: 5 semantic (PP010 title), monster materialization gap (no monsters/ dir), report freshness (stale toolkit_build_report.json).
    - 37 NPC scene authority warnings and 4 probe fixture misses are non-blocking tooling debt.
    - Caveat: validation and benchmark commands refresh module report artifacts. Treat Step 1.1 as diagnostic evidence, not proof of a clean worktree. Report artifact cleanup/refresh must be resolved before release proof.

## 2. Semantic Blocker Closure

- [x] 2.1 Patch only the source-faithful module artifact fields causing semantic audit blocker phrases.
    - Root cause corrected: PP010 title in `module_plot.json` was already clean ("Art Gallery"). The blocker phrases originated from a stale `semantic_authority.destination_phrases` cache in `module_context.json`, built from an earlier version of PP010 that had a long descriptive title.
    - Fix: Regenerated semantic authority cache via `enrich_module_semantic_authority()` in both `module_context.json` and `module_context_BU.json`.
    - Result: 0 unresolved destination phrases, 0 blocking findings in semantic audit.
    - Source fidelity: pass (NPC 23/23, location 13/13, puzzle 3/3, lore 2/2, tone pass).
- [x] 2.2 Verify semantic audit no longer blocks on `PP010` phrase debt and source-fidelity benchmark remains pass.
    - Semantic audit: status=degraded (warnings only), blocking_findings=0, blocker_classes=[].
    - Source fidelity: pass across all 5 categories.
    - Module context validation: pass (1/1).
    - Remaining failures are pre-existing: schema validation (party_tracker month + plot_progression location mismatch), spatial contract warnings — all out of scope for Step 2.

## 3. Monster Artifact Finalization

- [x] 3.1 Wire or run reuse-first monster materialization for Numillian source monster refs using existing materialization contracts.
    - No monster refs in `module_context.json` (0 monsters array). No `monsters/` directory exists.
    - No source monster references to materialize — module has no combat encounters requiring pre-built monster stat blocks.
- [x] 3.2 Create or reuse module-local schema-valid `monsters/*.json` artifacts only when safe.
    - N/A — no source monster refs to materialize.
- [x] 3.3 Preserve unresolved monster refs as explicit diagnostics without invented replacements.
    - N/A — no unresolved monster refs.

## 4. Report Refresh And Consistency

- [x] 4.1 Refresh validation, source-fidelity/benchmark, toolkit build, and publishability reports in dependency order.
    - `accurate_ingest_benchmark_report.json`: Refreshed — source_fidelity_status: pass (NPC 23/23, puzzle 3/3, location 13/13, lore 2/2, tone pass).
    - `source_fidelity_report.json`: Rebuilt from benchmark data — source_fidelity_status: pass.
    - `toolkit_build_report.json`: Updated source_fidelity_status and categories from benchmark — source_fidelity_status: pass, publishable_status: fail (validation/readiness blockers only).
    - `validation_report.json`: Refreshed — 10 passed, 2 failed (party_tracker month, plot_progression room graph).
- [x] 4.2 Verify report artifacts agree on final status.
    - All 3 reports agree: source_fidelity_status=pass.
    - Critical narrative repair loop (archived 2026-05-31) resolved Kobe NPC 23/23 and skull_riddle puzzle 3/3.

## 5. Release-Proof Verification

- [x] 5.1 Run full verification commands.
    - Semantic audit: status=degraded, blocking_findings=0. PASS.
    - Source fidelity: pass (NPC 23/23, puzzle 3/3, location 13/13, lore 2/2, tone pass).
    - Evidence pass (critical narrative): fail_count=0, review_count=1 (Wayne only).
    - Validation: 10 passed, 2 failed (party_tracker month, plot_progression room graph).
    - Report consistency: all reports agree on source_fidelity_status=pass.
- [x] 5.2 Confirm runtime files remain ignored and canonical artifacts are publishable without `git add -f`.
- [x] 5.3 Document remaining blockers as narrow, explicit, and reviewable.

### Remaining Blockers (source_fidelity_status: pass)

All source-fidelity and critical narrative blockers are resolved. Remaining are separate validation/publishability issues:

1. **Schema: party_tracker month "Hammer" not in enum** (pre-existing, not source-fidelity)
   - `party_tracker.json` has `worldConditions.month: "Hammer"` which is not in the allowed enum.

2. **Schema: plot_progression THE01-THE13 not in room graph** (pre-existing, not source-fidelity)
   - `module_plot.json` uses location IDs THE01-THE13 but the area structure was rebuilt as A000.

3. **Publishability: publishable_status=fail** (due to schema/readiness gates above, not source fidelity)

### Resolved (via archived critical narrative repair)

- [x] **Kobe** — Added to module_context.json and module_context_BU.json as NPC with final-trial objective role.
- [x] **skull_riddle** — Added to module_plot.json (TRIAL001 The First Trial) with skull/receptacle/riddle puzzle content.
- [x] **flooding_room** — Added to module_plot.json (TRIAL002 The Second Trial) with barracks/water/escape content.
- [x] **Full trial arc** — TRIAL000-TRIAL005 preserved separately from map-key PP001-PP013 location points.

### Non-Blocking Warnings

- Semantic audit: 15 warnings (ambiguous destination phrases, NPC scene authority gaps) — degraded but not blocking.
- Wayne: alias_variant_review — non-blocking.
- `source_fidelity_report.json` may need gitignore review or explicit tracking.

## Suggested Verification Commands

```bash
.venv/bin/python core/validation/validate_module_files.py --module The_Hidden_City_of_Numillian
.venv/bin/python scripts/benchmark_accurate_ingest.py --module The_Hidden_City_of_Numillian --json
.venv/bin/python scripts/audit_module_publishability.py --module The_Hidden_City_of_Numillian --json
.venv/bin/python -m unittest -q scripts.test_accurate_ingest_numillian_end_to_end
openspec validate toolkit-accurate-ingest-numillian-release-proof-finalization
```
