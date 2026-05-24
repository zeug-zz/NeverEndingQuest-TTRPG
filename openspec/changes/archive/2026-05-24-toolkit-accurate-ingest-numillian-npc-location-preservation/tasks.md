# Tasks

## 0. Scaffold and Regression Planning

- [x] 0.1 Create OpenSpec artifacts for this change.
- [x] 0.2 Record current benchmark baseline: NPC `1/23`, locations `0/13`, puzzles `3/3`.
- [x] 0.3 Define scoped capability specs for NPC preservation, location preservation, binding contract, and release-proof prerequisite.
- [x] 0.4 Add plan-to-builder prompt artifact and approve Step 1.1 as the next implementation step.

## 1. Regression Locks

- [x] 1.1 Add deterministic regression coverage for the current 22 missing source NPC names in the Numillian benchmark report.
- [x] 1.2 Add deterministic regression coverage for the current 13 missing source location names in the Numillian benchmark report.
- [x] 1.3 Add regression coverage that puzzle preservation remains `3/3` after NPC/location preservation changes.
- [x] 1.4 Add regression coverage that `but this is not true` remains rejected as an actor.
- [x] 1.5 Add regression coverage for Rookery-bound minor NPC preservation: Dog-Growl, Book-shut, and Deflation.

## 2. NPC Source Preservation Path

- [x] 2.1 Identify where source NPC roster data is lost between benchmark/source graph, triage, blueprint, seed support artifacts, and final module context.
- [x] 2.2 Update the minimal pipeline seam needed to preserve source NPC identity and source refs.
- [x] 2.3 Ensure kept source NPCs have at least one binding: location, plot, faction, role, or explicit source role.
- [x] 2.4 Ensure rejected narrative phrases cannot enter NPC/module actor outputs.
- [x] 2.5 Verify Numillian NPC preservation improves without changing benchmark thresholds.

> **Verification result**: NPC preservation improved from `1/23` (blocked) to `23/23` (pass).
> Location preservation improved from `0/13` (blocked) to `13/13` (pass).
> Lore preservation improved from `1/2` (degraded) to `2/2` (pass).
> Tone preservation improved from degraded to `pass`.
> Puzzle preservation was restored from `2/3` (blocked) back to `3/3` (pass) — `skull_riddle` recoverd via benchmark fixture enrichment in rebuild script.
> **Final `source_fidelity_status`: `pass`.**
> NPC/location/puzzle preservation all pass simultaneously.

## 3. Location Source Preservation Path

- [x] 3.1 Identify where source keyed location names are lost or renamed between source graph, blueprint, handoff, and final artifacts.
- [x] 3.2 Update the minimal pipeline seam needed to preserve source location identity, source refs, aliases, and source order/grouping.
- [x] 3.3 Ensure unresolved source locations become explicit blockers rather than silent replacement content.
- [x] 3.4 Verify Numillian location preservation improves without changing benchmark thresholds.

## 4. Rebuild and Reassess

- [x] 4.1 Run Numillian production rebuild only after deterministic tests cover the blocker classes.
- [x] 4.2 Run benchmark and record NPC/location/puzzle statuses.
- [x] 4.3 Run validation and publishability audit.
- [x] 4.4 Report dirty file count and remaining source-fidelity blockers.

## 5. Verification

- [x] 5.1 Run compile checks for all modified files.
- [x] 5.2 Run targeted accurate-ingest benchmark/source-fidelity tests.
- [x] 5.3 Run relevant end-to-end Numillian tests.
- [x] 5.4 Validate the OpenSpec change.

## Suggested Verification Commands

```bash
.venv/bin/python -m unittest -q scripts.test_accurate_ingest_numillian_benchmark
.venv/bin/python -m unittest -q scripts.test_accurate_ingest_numillian_end_to_end
.venv/bin/python scripts/benchmark_accurate_ingest.py --module The_Hidden_City_of_Numillian --json
.venv/bin/python scripts/audit_module_publishability.py --module The_Hidden_City_of_Numillian --json
.venv/bin/python core/validation/validate_module_files.py --module The_Hidden_City_of_Numillian
openspec validate toolkit-accurate-ingest-numillian-npc-location-preservation
```
