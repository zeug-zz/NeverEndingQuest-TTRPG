# Design: Numillian NPC and Location Preservation

## Overview

This change closes the next structural source-fidelity gap after the narrow Numillian bridge fix. The bridge fix made punctuation-safe matching, puzzle preservation, and prose-phrase filtering work. Current benchmark output still shows that the generated module does not preserve source NPC and location rosters in benchmark-visible artifacts.

The design keeps the existing ModuleBuilder orchestration as the creative engine. Python owns source identity preservation, benchmark visibility, source refs, and explicit blocker reporting.

## Current Benchmark Baseline

The current production benchmark report records:

- `source_fidelity_status`: `blocked`
- `npc_preservation`: `blocked`, score `0.043478260869565216`, actual `1/23`
- `location_preservation`: `blocked`, score `0`, actual `0/13`
- `puzzle_preservation`: `pass`, actual `3/3`
- `lore_preservation`: `degraded`, actual `1/2`
- `tone_preservation`: `degraded`

This change targets NPC and location preservation only. Lore/tone may be observed but SHOULD NOT expand the scope unless directly required to preserve NPC/location source identity.

## Capability 1: NPC Preservation

### Root Cause

Source NPCs can be extracted or present in benchmark expectations but fail to appear in final module artifacts or appear without enough source-binding metadata. Some real minor NPCs, such as Dog-Growl, Book-shut, and Deflation, can be underbound even when their source text clearly identifies them as Rookery residents.

### Design

- Build deterministic tests that enumerate the current missing source NPC names from the benchmark fixture/report.
- Preserve source NPC names through the source graph, triage report, builder blueprint, seed support artifacts, and final module context where applicable.
- Require kept source NPC entries to carry source refs and at least one binding category: location, plot, faction, role, or explicit source role.
- Do not promote narrative phrases into NPCs to inflate preservation counts.

### Acceptance

- Regression tests capture the current `1/23` blocker.
- Pipeline fixes improve benchmark-visible NPC preservation without weakening benchmark thresholds.
- `but this is not true` remains filtered out.

## Capability 2: Location Preservation

### Root Cause

Source keyed locations can be lost or renamed during blueprint/materialization/build handoff. Numillian currently reports `0/13` benchmark source locations found, which means final artifacts do not expose the original keyed location names or approved aliases in the form the benchmark expects.

### Design

- Build deterministic tests that enumerate the 13 current missing source location names.
- Preserve source location names, aliases, source refs, source order, and source grouping in blueprint/handoff artifacts.
- Ensure final module artifacts expose source location identity in benchmark-visible fields without using `MODULE_SUMMARY.md` as repair input.
- If a source location cannot be placed, record an explicit unresolved location blocker instead of silently replacing it.

### Acceptance

- Regression tests capture the current `0/13` blocker.
- Pipeline fixes improve benchmark-visible location preservation without changing benchmark thresholds.
- Source names remain stable unless an alias map is explicit and tested.

## Capability 3: NPC/Location Binding Contract

### Root Cause

Name-only preservation is insufficient. Accurate ingest must preserve source meaning enough for ModuleBuilder to create playable content without drifting into a replacement adventure.

### Design

- NPCs SHOULD be bound to source locations when source text provides that relationship.
- Locations SHOULD carry associated NPC/monster/item/clue/puzzle hints when available.
- Underbound source entities SHOULD become warnings or blockers based on criticality.
- Binding data SHOULD feed source-enhanced ModuleBuilder handoff and build-fidelity diagnostics.

### Acceptance

- Dog-Growl, Book-shut, and Deflation can be tested as preserved Rookery-bound NPCs.
- The source location roster can be tested as source-ref-bearing keyed locations, not generic generated areas.

## Capability 4: Release-Proof Prerequisite

### Design

`toolkit-accurate-ingest-numillian-release-proof` should remain deferred until this preservation slice either:

1. Makes NPC and location preservation pass/degraded according to benchmark expectations, or
2. Produces explicit narrow blockers that are reviewable and not hidden by publishability gates.

### Acceptance

- Release-proof cannot claim readiness while benchmark status is blocked by NPC/location preservation.
- Puzzle preservation remains protected during NPC/location fixes.

## Rollback

Revert individual source propagation or matching changes if they regress non-Numillian accurate-ingest fixtures. Do not remove regression tests that document the current blocker classes unless replaced by stronger tests.

## Observability

Reports SHOULD include counts for source NPCs and locations preserved, missing, aliased, unresolved, and rejected. Rejected candidate reports SHOULD distinguish narrative phrases from real source entities.
