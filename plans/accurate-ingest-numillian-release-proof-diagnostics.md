# Numillian Release-Proof Diagnostics (2026-05-26, updated 2026-06-01)

## Update Summary (2026-06-01)

The critical narrative repair loop (`toolkit-accurate-ingest-critical-narrative-repair-loop`, archived 2026-05-31) has resolved all source-fidelity blockers. Current state:

- Source fidelity: pass — NPC 23/23, puzzle 3/3, location 13/13, lore 2/2, tone pass.
- Semantic blockers: resolved (0 blocking findings, 0 unresolved destination phrases).
- Critical narrative: Kobe added as NPC (both live and BU context), skull_riddle and flooding_room added as trial plot content (both live and BU plot).
- Full trial arc (TRIAL000-TRIAL005) preserved separately from map-key PP001-PP013 location points.
- Evidence pass: fail_count=0, review_count=1 (Wayne review-only).

Remaining: validation/publishability blockers are separate schema issues, not critical narrative or source-fidelity.

## Playability Assessment (2026-06-01)

Simple answer: **No, The Hidden City of Numillian is not yet safe to play with library staff and patrons as a published NEQ-TTRPG module produced by the current GUI ingest pipeline.**

What is complete:

- The source-fidelity layer is now passing for Numillian: NPC 23/23, puzzle 3/3, location 13/13, lore 2/2, tone pass.
- The critical narrative repair loop proves the pipeline can detect and repair missing critical adventure content such as Kobe, `skull_riddle`, and `flooding_room` without weakening benchmarks or scanners.
- Source-fidelity reports now agree and no longer list Kobe or `skull_riddle` as missing.

What is not complete:

- The module still fails validation/publishability gates.
- `party_tracker.json` still contains an invalid calendar month (`Hammer`) for the current schema.
- `module_plot.json` still contains PP001-PP013 location references (`THE01`-`THE13`) that do not resolve against the emitted A000/A01-A18 room graph.
- The GUI accurate-ingest pipeline therefore still does not meet the actual product goal: input a 5e adventure narrative/PDF/MD and receive a playable, publishable NEQ-TTRPG module ready for gameplay testing.

Conclusion: **Accurate ingest source fidelity is repaired; playable publication closure is not complete.** The next change must target the full GUI Module Builder ingest pipeline contract: source fidelity pass, schema validation pass, plot/location graph pass, report agreement, publishability pass, catalog/registration readiness, and Start Game readiness without manual JSON repair.

## Commands Run (2026-06-01)

- `.venv/bin/python core/validation/validate_module_files.py --module The_Hidden_City_of_Numillian` -> 10/12 pass
- `.venv/bin/python scripts/benchmark_accurate_ingest.py --module The_Hidden_City_of_Numillian --json` -> pass
- `.venv/bin/python scripts/audit_module_publishability.py --module The_Hidden_City_of_Numillian --json` -> exit 1, blocked (schema/readiness only)
- `.venv/bin/python scripts/check_critical_narrative_evidence.py --module The_Hidden_City_of_Numillian --json` -> fail_count=0

## Current Truth After Critical Narrative Repair

| Gate | Current Status |
|------|----------------|
| semantic authority audit | degraded, 0 blocking findings |
| source-fidelity benchmark | **pass** (NPC 23/23, puzzle 3/3, location 13/13, lore 2/2, tone pass) |
| critical narrative evidence | **pass** (0 critical omissions, Wayne review-only) |
| report consistency | all reports agree on `source_fidelity_status=pass` |
| trial arc topology | 6-beat arc (TRIAL000-TRIAL005) in both live and BU plot |
| Kobe | present in module_context.json and module_context_BU.json |
| skull_riddle | present in module_plot.json TRIAL001 with puzzle content |
| flooding_room | present in module_plot.json TRIAL002 with puzzle content |
| validation | 10/12 pass; party month and plot location graph remain separate schema issues |
| publishability | fail (due to schema/readiness gates, not source fidelity) |

The previous `source_fidelity_report.json` and `toolkit_build_report.json` reported pass-state data from an earlier rebuild. Those reports were stale/inaccurate relative to the live module JSON.

## Worktree Caveat

The validation and benchmark commands refresh module report artifacts. This diagnostic pass should not be treated as a no-mutation proof.

Observed dirty tree includes existing Numillian artifact drift outside this diagnostic note: modified reports/module files, deleted older area/map/media placeholder artifacts, and untracked generated artifacts. Before final release proof, the next builder steps must distinguish intentional canonical Numillian finalization artifacts from stale or accidental runtime/generated drift.

## Current Statuses

> Historical initial snapshot. Superseded by "Current Truth After Refresh" above.

| Gate | Status |
|------|--------|
| validation | PASS (100%) |
| source-fidelity benchmark | pass (NPC 23/23, locations 13/13, puzzles 3/3, lore 2/2, tone pass) |
| ready_status | pass |
| publishable_status | fail |
| effective_publishable_status | blocked |
| source_fidelity_status | pass |
| toolkit_build_report | failed (stale -- shows publishable=fail) |

## Blockers by Class

> Historical initial classification. The semantic blocker is now resolved, and source-fidelity blocker detail has changed after report refresh.

### 1. Semantic (blocking publishability)

**Status 2026-05-31:** Resolved. The blocker phrases came from stale `semantic_authority.destination_phrases` cache, not from a live PP010 title patch target. Regenerating semantic authority for both `module_context.json` and `module_context_BU.json` removed the 5 false destination phrases.

**5 blocking findings** in `phase2_ambiguity_debt` class, all from `module_plot.json#plotPoints[PP010].title`.

Current title: `The final trial becomes a battle in which the party must protect Kobe and keep the Vault secret.`

The semantic authority audit extracts these as false destination phrases: `and keep`, `kobe and keep`, `must protect kobe and keep`, `party must protect kobe and keep`, `protect kobe and keep`.

Source-faithful fix: edit PP010 title to remove prose that triggers false destination extraction. The underlying content (protect Kobe, keep Vault secret) must be preserved in description/body but the title should be a short canonical plot label.

### 2. Monster Artifacts (not blocking yet, structural gap)

**Status 2026-05-31:** Not the active blocker in current live module state. `module_context.json` currently has 0 source monster refs, so monster materialization is N/A for this release-proof pass. If future Builder repair reintroduces explicit encounter seeds or monster refs, reuse-first materialization must run again.

`modules/The_Hidden_City_of_Numillian/monsters/` **does not exist**.

Source monster refs in normalized packet: Duergar, Alhoon, Illithid, Homunculus, Kenku, Druid, Were-possum, Were-trout, Were-bear, Nothic, Vampire, Charion.

toolkit_build_report reports: `monsters_generated: 0`, `encounters_planned: 5`.

Existing `utils/accurate_ingest_monster_materialization.py` has reuse-first resolution contract (50 tests) but is not wired into the production post-build pipeline for Numillian.

### 3. Report Freshness (blocking artifact)

**Status 2026-05-31:** Resolved as a freshness problem. All refreshed reports now agree, but they agree on `source_fidelity_status=blocked`, revealing actual missing critical content rather than a stale-report-only issue.

`toolkit_build_report.json` is stale -- status is `failed`, publishable= `fail`, but this reflects an old build, not current artifact state.

### 4. Non-Blocking Warnings (tooling debt)

- 37 NPC scene authority warnings (NPCs with no visible location or reveal bindings -- common for seed-writer modules, needs source context expansion)
- 4 semantic probe fixture misses (travel_probe, handoff_probe, hidden_npc_probe)
- 1 continuity warning (cross_module_refs is empty)

None of these block publishability currently.

## Recommended Next Patch Target (Step 2.1)

> Historical recommendation. Superseded by 2026-05-31 findings below.

**Smallest fix**: Edit PP010 title to a compact canonical label that preserves the plot meaning but does not generate false destination phrases.

Proposed title: `Protect Kobe and Seal the Vault`

This drops `"the final trial becomes a battle in which the party must"` (prose preamble that generates false destination tokens) while preserving the two core plot elements: protect Kobe, keep Vault secret. "and" is no longer a standalone fragment token.

## Critical Narrative Content Failure (2026-05-31)

> Historical diagnosis. Superseded by the archived `toolkit-accurate-ingest-critical-narrative-repair-loop` change. Kobe, `skull_riddle`, and `flooding_room` are now present in live and BU module artifacts, and source-fidelity reports pass. This section is retained only as root-cause history for the repair loop.

### Kobe

Source location: `Local_Docs/modules/hombrew/modules/The Hidden City of Numillian.md`, lines 131-158.

Kobe is the young girl visible on a flat-topped tower during the final no-win scenario. Shuluth instructs the party to bring Kobe to the Vault without revealing its location. If attackers reach Kobe first, they slay her. Completing the trial can require removing Kobe, the Vault, and the players from harm.

Current module failure:

> Resolved as of 2026-06-01.

- Kobe is listed in the benchmark fixture as a required source NPC.
- Kobe does not appear in `module_context.json` NPCs.
- Kobe does not appear in current area files or `module_plot.json`.
- This is not optional flavor; she is the final trial's human stakes and objective anchor.

Likely cause:

- Extractor/table bias. Kobe appears in critical prose, not in the formal Numillian NPC table. The current pipeline preserved table NPCs but failed to promote a prose-named critical actor into the canonical NPC/source-lock contract.

### skull_riddle

Source location: `Local_Docs/modules/hombrew/modules/The Hidden City of Numillian.md`, lines 40-75.

The first trial presents a skull riddle with three colored skulls, three receptacles, a trick phrase ("Here each skull lies"), incorrect-placement consequences, and a solution table.

Required preserved content:

- Puzzle id/concept: `skull_riddle`.
- Riddle inscription.
- Red, Blue, and Yellow Skull clues.
- Crown, alms plate, and book receptacles.
- Trick rule: each skull lies; place each skull in the receptacle the clue does not indicate.
- Correct placement: Red -> Book, Blue -> Alms-plate, Yellow -> Crown.
- Failure consequence: DC 15 Wisdom save or 2d8 psychic damage.

Current module failure:

> Resolved as of 2026-06-01.

- `skull_riddle` is listed in the benchmark fixture as a required puzzle.
- No occurrence of `skull` exists in current `module_plot.json` or `module_plot_BU.json`.
- The seed source report previously classified Red/Blue/Yellow Skull as NPC-like atoms instead of puzzle components.
- The generated plot is map-key shaped (`PP001: Charion Tamer`, `PP010: Art Gallery`) rather than adventure-arc shaped (Trial at the Door -> First Trial -> Second Trial -> False Third Trial -> True Third Trial -> No-win Scenario).

Likely cause:

- Puzzle-component misclassification plus plot-topology failure. The source's explicit trial structure was not preserved as plot progression, and the skull objects were treated as speaking NPCs instead of puzzle components.

## Architectural Conclusion

Manual JSON patching is the wrong fix. The failure belongs to the accurate-ingest pipeline:

- Python should provide deterministic breakdown, source excerpts, missing-critical-content diagnostics, and schema/source-fidelity gates.
- The LLM Builder/backstage assistant should use narrative reasoning to reconstruct a meaningful NEQ-TTRPG JSON analogue of the human-written adventure.
- The backstage auditor should detect that critical prose-named actors and explicit trial puzzles are missing and produce a repair brief for the Builder.
- The Builder should perform the source-faithful repair, not OpenCode/Python manually authoring Kobe or the skull riddle into JSON.

## OpenSpec Recommendation

> Historical recommendation. Completed and archived as `toolkit-accurate-ingest-critical-narrative-repair-loop`. The active successor work is now `toolkit-accurate-ingest-playable-publication-closure`, which targets schema/topology/publishability readiness for GUI Module Builder gameplay testing.

Create a successor OpenSpec change rather than archiving the current finalization as release-proof:

`toolkit-accurate-ingest-critical-narrative-repair-loop`

### Proposed Purpose

Add a deterministic backstage repair loop for critical narrative omissions discovered after accurate-ingest builds. The loop should package source excerpts, missing-critical-content evidence, and required output surfaces, then hand that repair brief to the LLM Builder for source-faithful regeneration or patching.

### Proposed Requirements

1. **Critical Prose Actor Detection**
   - Detect named actors appearing in critical objective/failure prose even when absent from NPC tables.
   - Kobe should be classified as `critical_npc` because she anchors the final trial objective and failure condition.

2. **Explicit Puzzle Structure Detection**
   - Detect headings such as "Trial", "Riddle", or mechanically structured puzzle blocks.
   - Preserve puzzle metadata and components separately from NPCs.
   - Red/Blue/Yellow Skull should be puzzle components, not standalone NPCs.

3. **Plot Topology Repair**
   - Ensure ModuleBuilder constructs plot progression from the adventure arc, not merely map-key locations.
   - Numillian plot should preserve the trial sequence and the no-win scenario.

4. **Backstage Repair Brief**
   - When benchmark/source-fidelity detects missing critical content, generate a compact Builder-facing repair brief with source excerpts and explicit missing items.
   - The brief must forbid manual/Python invention and require source-faithful Builder synthesis.

5. **LLM Builder Repair Pass**
   - Feed the repair brief and source excerpts to ModuleBuilder or an LLM Builder repair entrypoint.
   - Builder must repair `module_context`, plot/puzzle structures, and any required area/scene surfaces.

6. **Validation**
   - Re-run source-fidelity benchmark and publishability audit.
   - Expected Numillian gates after repair: NPC 23/23, puzzle 3/3, locations 13/13, lore 2/2, tone pass.

### Estimated Remaining Work

- Active OpenSpec changes currently left: 1 (`toolkit-accurate-ingest-numillian-release-proof-finalization`).
- Recommended additional scaffold: 1 (`toolkit-accurate-ingest-critical-narrative-repair-loop`).
- Estimated implementation time: 4-6 hours if existing builder/backstage hooks are reused.

## Release Readiness Assessment

Historical assessment before critical narrative repair:

- The first gate into Shuluth's mind is absent.
- The final trial's rescue objective is absent.

Current assessment after critical narrative repair:

- The first gate into Shuluth's mind is present as `skull_riddle` trial content.
- The final trial rescue objective is present through Kobe and the no-win scenario plot beat.
- Source fidelity passes from live module JSON.
- The module is still not gameplay-ready because validation/publishability fail on separate schema/topology issues.

The broader accurate-ingest architecture is close, but not release-ready. The remaining gap is now playable-publication closure: generated modules must pass source fidelity, schema validation, plot/location graph validation, report agreement, publishability, and Start Game readiness without manual JSON repair.
