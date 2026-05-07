# Accurate Homebrew Ingest: Source-Faithful Multi-Pass Pipeline

**Status:** Active roadmap - Phase 1 complete via `toolkit-accurate-ingest-source-graph`
**Updated:** 2026-05-08
**Target:** Fix the 95% fidelity loss between original adventure markdown/PDF sources and ingested NEQ modules, as observed with `The_Hidden_City_of_Numillian`.

---

## Executive Summary

The current Module Builder uploader loses adventure fidelity because it compresses an entire markdown/PDF source into one flat normalized packet, then asks the existing `ModuleBuilder` to re-expand that summary into a full module. The builder currently receives too little source truth, so it invents new plot topology, drops named NPCs and keyed locations, rewrites puzzles, and replaces source tone with generic adventure defaults.

This plan replaces the one-shot normalizer with a source-faithful multi-pass ingest pipeline:

```text
Source MD/PDF
  -> deterministic source graph extraction
  -> section-bounded LLM fact extraction
  -> identity/topology synthesis
  -> canonical builder blueprint
  -> adversarial fidelity verification and repair loop
  -> packet/blueprint-driven module build
  -> build-time fidelity gates
  -> optional narrative enrichment placeholder pass
  -> final source fidelity report
```

Core principle:

> Python mechanically extracts and verifies source truth. LLMs classify, enrich, and repair within evidence bounds. The builder formats the adventure; it must not replace it.

---

## Problem

### Numillian Case Study

Original MD (`Local_Docs/modules/hombrew/modules/The Hidden City of Numillian.md`, 250 lines):

- 20 named NPCs with distinct personalities and roles, including Wayne the crooked-toothed innkeeper, Belrik Dumma-dhur the duergar assassin, Irene Laughing-Eyes the cat wizard, Dog-Growl, Book-shut, and Deflation the kenku composers.
- 13 specific locations with map-key entries, including Charion Tamer, Shuluth's Tomb, The Rookery, Grove, Brooksteps Inn, Wizard's Tower, Art Gallery, and Temple of Broance.
- A tight character-driven plot: Gatepact lore -> Trial at the Door -> skull riddle -> flooding room puzzle -> kill-the-dog mindscape test -> City of the Mind -> protect Kobe.

Ingested module (`modules/The_Hidden_City_of_Numillian/`):

- 2 of 20 NPCs survive, and both are heavily re-characterized.
- 0 of 13 source locations survive by original name.
- Original plot is replaced by an 18-beat ward-network conspiracy thriller.
- Source tone shifts from lush quirky character-driven fantasy to generic conspiracy thriller.

Approximate shared DNA: 3-5%.

### Root Cause

Current readable-source upload path has three compression and reinvention points:

```text
Markdown/PDF source
  -> one LLM call: normalize everything into flat JSON
  -> normalized_packet with short arrays and 3-7 line builder_narrative
  -> ModuleBuilder.build_module(builder_narrative)
  -> many LLM calls expand from summary, not source truth
  -> output module with invented structure
```

Observed causes:

1. **Normalizer overload:** GPT 5.4 Mini High is asked to read a full adventure, classify all content, preserve every entity, infer structure, and emit a schema-valid packet in one call.
2. **Flat packet schema:** `locations`, `npc_seeds`, and `plot_progression` preserve names at best, not source evidence, puzzle rules, clue chains, location bindings, relationship edges, or plot topology.
3. **Lossy builder handoff:** `builder_narrative` is currently expected to be concise. The builder receives a summary, then creatively fills missing details.
4. **No fidelity repair loop:** Current checks validate packet presence and build readiness, not whether source NPCs, locations, puzzles, and plot beats survived.
5. **No build-time source lock:** Even if normalization preserves names, later `ModuleBuilder` stages can rename, relocate, omit, or overwrite source material.

### Current Code Seams

The implementation should target these existing seams first:

- `utils/toolkit_homebrew_normalizer.py`
  - `normalize_homebrew_upload(...)` currently performs the single LLM call.
  - `_build_builder_narrative(...)` currently returns model-supplied concise prose or a fallback summary.
- `prompts/toolkit/homebrew_upload_normalization_prompt.txt`
  - Current prompt asks for one flat JSON object.
- `utils/toolkit_homebrew_upload_contract.py`
  - `build_normalized_packet_placeholder(...)` and `validate_review_packet(...)` define the current packet artifact contract.
- `web/extensions/toolkit_homebrew_packet_builder.py`
  - `_read_builder_narrative(...)` and `_execute_module_builder(...)` hand the prose narrative to `ModuleBuilder.build_module(...)`.
- `core/generators/module_builder.py`
  - `build_module(initial_concept)` and `ModuleGenerator.generate_module(...)` still operate as concept-to-module generators.

---

## Target Architecture

### Canonical Artifact Chain

Readable-source workspaces should persist a richer chain of reviewable artifacts:

| Artifact | Purpose |
|---|---|
| `source_manifest.json` | Mechanical heading/table/location/entity extraction from the source. |
| `source_graph.json` | Canonical source truth graph with evidence spans and criticality. |
| `section_extractions/*.json` | Per-section LLM fact extraction payloads. |
| `identity_resolution_report.json` | Alias, duplicate, and entity-type adjudication. |
| `plot_topology_report.json` | Plot beats, clue chains, puzzle chains, dependencies, endings. |
| `normalized_packet.json` | Existing review packet, enriched with source graph references. |
| `builder_blueprint.json` | Source-locked build plan for areas, locations, NPCs, plot, encounters, and tone. |
| `normalization_fidelity_report.json` | Source graph vs normalized packet fidelity diff. |
| `builder_input.json` | Builder handoff including blueprint identity and lock settings. |
| `build_fidelity_report.json` | Stage-by-stage source preservation checks after build. |
| `narrative_enrichment_plan.json` | Optional post-build enrichment strategy placeholder. |
| `source_fidelity_report.json` | Final rollup for review, publication, and regression benchmarks. |

### Source Truth Hierarchy

1. **Source text evidence wins:** A name, puzzle, location, or plot beat with source evidence must not be renamed or replaced silently.
2. **Python source graph wins over LLM summaries:** The LLM may classify or enrich source atoms, but not drop them.
3. **Builder blueprint wins over creative defaults:** Builder stages must consume the blueprint and report deviations.
4. **Enrichment is additive:** Later narrative enrichment may deepen interpretation but must not overwrite source plot, NPC roles, keyed locations, puzzles, or endings.

---

## Source Graph Contract

The initial plan's `source_manifest` should be expanded into a `source_graph` with typed, evidence-backed atoms.

### Source Atom Shape

Every source atom should include:

```json
{
  "id": "stable_source_atom_id",
  "type": "npc|location|plot_beat|puzzle|clue|encounter|item|faction|tone_marker|rule",
  "name": "canonical source name if applicable",
  "summary": "short source-grounded summary",
  "source_refs": [
    {
      "source_path": "...",
      "section": "Map Key > 1. Brooksteps Inn",
      "line_start": 120,
      "line_end": 136,
      "excerpt": "short evidence excerpt"
    }
  ],
  "criticality": "required|major|minor|ambiguous|ignore",
  "confidence": "high|medium|low"
}
```

### Required Atom Types

#### Locations

Capture:

- Original map key number or source heading.
- Original name.
- Parent area or section.
- Description excerpt.
- NPCs present or mentioned.
- Monsters/hazards/traps/checks.
- Treasure/items.
- Exits/connectivity hints.
- Puzzle or clue references.

#### NPCs

Capture:

- Canonical name as written.
- Aliases and title variants.
- Role or function.
- Personality cues.
- Faction or relationship ties.
- Location bindings.
- Dialogue cues or quoted lines.
- Quest function.
- Whether the NPC is scene-present, lore-only, hidden, hostile, allied, or ambiguous.

#### Plot Beats

Capture:

- Beat title.
- Trigger.
- Required location/NPC/item.
- Outcome.
- Next beat or dependency.
- Failure state where present.
- Whether the beat is optional, mainline, climax, or epilogue.

#### Puzzles and Trials

Capture:

- Setup.
- Player-facing prompt.
- Rules.
- Solution.
- Failure consequences.
- Rewards/unlocks.
- Required clue dependencies.

This is critical for Numillian because the Trial at the Door is the adventure's spine.

#### Clues

Capture:

- Clue text or paraphrase.
- Where it appears.
- What it reveals.
- Which plot/puzzle it supports.
- Whether it is mandatory or redundant.

#### Encounters and Monsters

Capture:

- Source monster/NPC names.
- Encounter purpose.
- Location.
- Tactics if stated.
- Whether the encounter is avoidable, social, puzzle-linked, or mandatory.

#### Tone Markers

Capture:

- Source style descriptors.
- Repeated motifs.
- Weird/quirky/horror/comedic/cosmic/etc. signals.
- Representative source phrases.

Tone markers are necessary to prevent Numillian-style replacement of quirky character-driven fantasy with generic thriller prose.

### Criticality Classification

Do not blindly force every proper noun into the module. Add a deterministic plus LLM-assisted criticality pass:

| Criticality | Meaning | Build Rule |
|---|---|---|
| `required` | Main locations, named active NPCs, core plot beats, puzzles, core items. | Must appear in output or block build. |
| `major` | Important factions, recurring entities, important optional locations. | Must appear or require explicit review waiver. |
| `minor` | Flavor names, one-line references, optional color. | May be compressed, but omissions reported. |
| `ambiguous` | Unclear identity or function. | Human review or repair pass needed. |
| `ignore` | Author names, rules terms, false positives. | Excluded from fidelity gate. |

---

## Multi-Pass LLM Strategy

GPT 5.4 Mini High should not be asked to perform full extraction, synthesis, and schema emission in one prompt. Use several bounded calls.

### Pass A: Section-Bounded Fact Extraction

Input:

- One section or chunk.
- Local heading path.
- Mechanical extraction hints from Python.

Output:

- Facts only.
- No module schema conversion.
- Every fact carries source evidence.

Rules:

- Low temperature.
- JSON only.
- No invented connective tissue.
- If unsure, emit `ambiguous`.

### Pass B: Entity and Alias Adjudication

Input:

- All extracted NPC/location/item/faction candidates.
- Evidence snippets.

Output:

- Canonical identity table.
- Alias table.
- Duplicate merges.
- Entity type classification.
- Criticality recommendation.

Rules:

- Merge only with evidence.
- Preserve original display names.
- Flag ambiguous merges for review.

### Pass C: Plot and Puzzle Topology Synthesis

Input:

- Plot-related atoms.
- Location atoms.
- Puzzle/clue atoms.

Output:

- Plot DAG.
- Mainline sequence.
- Optional side quests.
- Trial/puzzle dependency chain.
- Ending/failure states.

Rules:

- Preserve source order when no stronger dependency is stated.
- Do not invent new major plotlines.
- Missing transitions become assumptions, not facts.

### Pass D: Normalized Packet Synthesis

Input:

- Source graph.
- Identity report.
- Plot topology report.

Output:

- Current `normalized_packet.json` contract.
- Source graph IDs embedded in packet entries where possible.
- Warnings for any schema compression.

Rules:

- The packet is a review artifact, not the source of truth.
- Do not collapse required source locations or NPCs without reporting the merge.

### Pass E: Adversarial Fidelity Verification

Input:

- Source graph.
- Normalized packet.
- Builder blueprint.

Output:

- Missing required atoms.
- Renames.
- Unsupported additions.
- Tone drift.
- Plot topology drift.
- Puzzle/clue omissions.

Rules:

- Treat unsupported major inventions as violations.
- Treat dropped source puzzles as blockers.
- Produce repair instructions grouped by category.

### Pass F: Targeted Repair

Input:

- Failed fidelity categories.
- Relevant source graph subset.
- Current packet/blueprint subset.

Output:

- Patch payload for only the failed category.

Rules:

- Do not re-run full normalization unless source graph construction failed.
- Keep repair loops bounded, for example max 2 automatic attempts.
- If still failing, require human review.

---

## Builder Blueprint

The current `builder_narrative` should not remain the only handoff. Add `builder_blueprint.json` as the source-locked build plan.

### Blueprint Shape

```json
{
  "blueprint_version": "source_faithful_builder_blueprint.v1",
  "source_hash": "...",
  "module": {
    "title": "The Hidden City of Numillian",
    "tone_profile": {},
    "summary": "source-grounded summary"
  },
  "area_plan": [],
  "location_roster": [],
  "npc_roster": [],
  "plot_graph": [],
  "puzzle_graph": [],
  "clue_graph": [],
  "encounter_plan": [],
  "item_roster": [],
  "source_lock": {
    "canonical_names_locked": true,
    "invented_major_entities_forbidden": true,
    "required_atom_omission_blocks_build": true
  }
}
```

### Short-Term Handoff

Serialize the blueprint into `builder_narrative.md` with hard source locks:

```text
SOURCE-FAITHFUL BUILD LOCK
- Use the following exact source locations.
- Use the following exact source NPC names.
- Preserve the plot topology and puzzle rules.
- Do not invent replacement factions, major villains, or alternate plotlines.
```

This is the smallest implementation path because `ModuleBuilder.build_module(...)` already accepts text.

### Medium-Term Handoff

Add packet-aware seeding into the builder:

- Derive `moduleName`, `mainPlot`, `worldMap`, factions, and timeline from blueprint.
- Pass these as `custom_values` into `ModuleGenerator.generate_module(...)` where safe.
- Generate areas/locations from the source location roster instead of freeform area expansion.

### Long-Term Handoff

Add a deterministic module materializer for source-faithful builds:

- Build area skeletons from source location roster.
- Place source NPCs deterministically.
- Populate plot and side quest shells from plot graph.
- Use LLM only for field prose, not for structure discovery.

This long-term path is the most faithful but should be staged after the source graph and fidelity verifier are stable.

---

## Fidelity Verification Contract

### Metrics

Use weighted category fidelity instead of only NPC/location counts.

| Category | Target | Blocker Threshold |
|---|---:|---:|
| Required NPC coverage | 100% | Any required NPC missing |
| Required location coverage | 100% | Any map-key/source location missing |
| Plot beat coverage | 90-100% | Any mainline beat missing |
| Puzzle/trial coverage | 100% | Any source puzzle/trial missing |
| Clue coverage | 90%+ | Any mandatory clue missing |
| Encounter source coverage | 90%+ | Major encounter missing or replaced |
| Item/key coverage | 95%+ | Required key/item missing |
| Unsupported major inventions | 0 | Any invented major plot/faction/villain |
| Tone preservation | review warning | Tone markers absent or contradicted |

### Severity Classes

| Severity | Meaning | Result |
|---|---|---|
| `blocker` | Required source structure is missing or replaced. | Build cannot proceed without repair or waiver. |
| `major` | Important source element is distorted, renamed, or relocated. | Requires repair or explicit review approval. |
| `minor` | Flavor element omitted or weakly represented. | Warning only. |
| `info` | Supported inference or harmless compression. | Audit note. |

### Fidelity Report Shape

```json
{
  "status": "pass|degraded|failed",
  "score": 0.0,
  "category_scores": {
    "required_npcs": 1.0,
    "locations": 1.0,
    "plot_beats": 0.95,
    "puzzles": 1.0,
    "tone": 0.75
  },
  "blockers": [],
  "major_findings": [],
  "minor_findings": [],
  "unsupported_additions": [],
  "repair_recommendations": []
}
```

---

## Narrative Enrichment Placeholder Pass

Narrative enrichment must be separated from source-fidelity ingest. It runs only after the source-faithful build passes structural fidelity gates.

### Purpose

Prepare a future enrichment pass that can apply strategies from:

- `plans/ancients-lab-narrative-enhancement.md`
- `plans/deepvault-narrative-enhancement.md`

without letting enrichment replace source truth.

### Supported Enrichment Profiles

| Profile | Use Case | State Requirement |
|---|---|---|
| `none` | Default source-faithful build only. | None |
| `three_stance_single_turn` | Deepvault-style thematic ambiguity safe for GPT 5.4 Mini High and no cross-turn tracking. | None |
| `five_playline_stateful` | Ancients Lab-style playline emergence and ending families. | Requires explicit module design support and/or future state tracking. |
| `custom` | User-authored enrichment profile. | Defined by profile |

### Eligible Fields

Only existing text fields should be modified by enrichment unless a later OpenSpec change explicitly changes schemas:

- `module_context.json` NPC `description`, `role`, `faction`.
- `module_context.json` continuity entry summaries.
- `module_plot_BU.json` `mainObjective`.
- `module_plot_BU.json` plot point `description` and `plotImpact`.
- `module_plot_BU.json` side quest `description` and `plotImpact`.
- Area `*_BU.json` `areaDescription`.
- Area `*_BU.json` location `description`, `dmInstructions`, `adventureSummary`, and existing `plotHooks` strings.

### Enrichment Guardrails

- Preserve original source plot, NPC roles, location names, puzzle rules, and endings.
- Add thematic interpretation only where source material supports it or where the user explicitly requests a transformative rewrite.
- Keep runtime harness limits in mind:
  - GPT 5.4 Mini High receives bounded context.
  - `dmInstructions` are per-location and are the safest delivery surface.
  - Single-turn narrator behavior cannot reliably count long-term playline dominance unless Python records it.
- Enrichment report must distinguish:
  - source-preserving enrichment,
  - source-ambiguous enrichment,
  - source-transformative enrichment.

---

## Phased Implementation Plan

### Phase 0: Baseline and Benchmark Harness

**Goal:** Capture measurable before/after fidelity using Numillian and at least one additional markdown/PDF fixture.

Tasks:

1. Add `scripts/benchmark_accurate_ingest.py` with fixture-driven dry-run mode.
2. Define benchmark expected rosters for Numillian:
   - 20 named NPCs.
   - 13 source locations.
   - Gatepact lore.
   - Trial at the Door sequence.
   - City of the Mind and Kobe objective.
3. Capture current baseline report from existing pipeline.
4. Store expected-source fixtures in test-safe form.
5. Add a benchmark summary format suitable for CI or manual regression.

Acceptance:

- Benchmark script can report current fidelity without changing modules.
- Numillian baseline demonstrates the existing loss clearly.

Suggested tests:

- `scripts/test_accurate_ingest_benchmark.py`

---

### Phase 1: Deterministic Source Manifest and Source Graph Foundation

**Goal:** Mechanically extract as much source structure as possible before any LLM call.

New file:

- `utils/toolkit_source_manifest.py`

Core functions:

```python
def build_source_manifest(source_text: str, source_path: str = "") -> Dict[str, Any]:
    """Extract headings, tables, bold spans, map-key locations, and source spans."""

def build_source_graph(source_text: str, source_path: str = "") -> Dict[str, Any]:
    """Build typed source atoms with evidence refs and initial criticality."""
```

Mechanical extraction should include:

- Heading hierarchy with line ranges.
- Markdown table extraction.
- Map-key location parsing.
- Room-style location parsing.
- Bold and italic spans.
- Quoted names.
- Proper noun candidates.
- DC/check/trap/treasure patterns.
- Monster and encounter phrase candidates.
- Puzzle/trial section candidates.
- Tone marker candidates.

Update:

- `utils/toolkit_homebrew_normalizer.py` to build and persist `source_manifest.json` and `source_graph.json` before model calls.
- `utils/toolkit_homebrew_upload_contract.py` to add artifact path helpers and persistence helpers.

Acceptance:

- Numillian source graph captures 18+ NPC candidates and 13 location candidates before LLM involvement.
- Trial-related sections are identified as plot/puzzle candidates.
- Every source atom has line/section evidence.

Suggested tests:

- `scripts/test_source_manifest_headings.py`
- `scripts/test_source_manifest_tables.py`
- `scripts/test_source_manifest_locations.py`
- `scripts/test_source_manifest_entities.py`
- `scripts/test_source_graph_integration.py`

---

### Phase 2: Section-Bounded LLM Extraction

**Goal:** Replace one full-source LLM call with evidence-bounded section extraction.

New file:

- `utils/toolkit_source_extraction.py`

New prompt files:

- `prompts/toolkit/source_section_extraction_prompt.txt`
- `prompts/toolkit/source_identity_adjudication_prompt.txt`
- `prompts/toolkit/source_plot_topology_prompt.txt`

Tasks:

1. Split source into extraction units using heading hierarchy.
2. Include each section's mechanical manifest hints.
3. Run low-temperature extraction per section.
4. Persist per-section extraction artifacts.
5. Merge section extractions into `source_graph.json`.
6. Fail open to mechanical-only graph if provider fails, but mark status degraded.

Prompt contract:

- Return JSON only.
- Extract facts only from supplied section.
- Carry source evidence.
- Use `ambiguous` rather than guessing.
- Do not emit module-ready prose.

Acceptance:

- Source sections can be extracted independently.
- Provider failure for one section does not destroy all extraction work.
- Numillian NPC/location/puzzle coverage improves over mechanical-only graph.

Suggested tests:

- `scripts/test_source_section_extraction_contract.py`
- `scripts/test_source_extraction_merge.py`

---

### Phase 3: Identity Resolution, Criticality, and Plot Topology

**Goal:** Convert raw candidates into a clean adventure source graph.

New file:

- `utils/toolkit_source_graph_synthesis.py`

Tasks:

1. Resolve aliases and duplicate entities.
2. Classify entity types.
3. Assign criticality.
4. Build NPC-location bindings.
5. Build plot beat dependencies.
6. Build puzzle and clue chains.
7. Detect source contradictions and ambiguous identities.
8. Persist:
   - `identity_resolution_report.json`
   - `plot_topology_report.json`

Criticality heuristics:

- Any numbered map-key location is `required` unless marked optional/lore-only.
- Any named NPC in an NPC table, quest text, dialogue, or location entry is `required` or `major`.
- Any source-defined puzzle/trial is `required`.
- Any title/section plot beat is `required` or `major`.
- Proper-noun-only one-offs default to `ambiguous` or `minor`.

Acceptance:

- Numillian distinguishes source-critical NPCs from false-positive proper nouns.
- Trial at the Door is represented as a puzzle chain, not flattened into a summary.
- Identity report exposes ambiguous merges for review.

Suggested tests:

- `scripts/test_source_identity_resolution.py`
- `scripts/test_source_criticality.py`
- `scripts/test_source_plot_topology.py`

---

### Phase 4: Normalized Packet v2 and Builder Blueprint Generation

**Goal:** Preserve compatibility with existing review packet while adding a source-locked builder blueprint.

New file:

- `utils/toolkit_builder_blueprint.py`

Tasks:

1. Generate `normalized_packet.json` from source graph rather than directly from raw LLM response.
2. Add optional source graph references to packet entries.
3. Generate `builder_blueprint.json` from source graph.
4. Generate expanded `builder_narrative.md` from blueprint.
5. Persist artifact metadata in normalization report.

Update:

- `utils/toolkit_homebrew_normalizer.py`
  - Replace single `_build_normalized_packet(...)` dependency with source graph synthesis.
  - Keep backward-compatible fallback for old behavior behind a flag.
- `prompts/toolkit/homebrew_upload_normalization_prompt.txt`
  - Convert to legacy fallback prompt or split into new prompts.
- `web/extensions/toolkit_homebrew_packet_builder.py`
  - Read `builder_blueprint.json` when present.
  - Include blueprint identity in `builder_input.json`.

Acceptance:

- Existing review packet still validates.
- Blueprint includes all required source locations and NPCs.
- Builder narrative includes exact source rosters and plot topology, not just a 3-7 line summary.

Suggested tests:

- `scripts/test_builder_blueprint_generation.py`
- `scripts/test_builder_narrative_source_lock.py`
- `scripts/test_normalized_packet_source_refs.py`

---

### Phase 5: Normalization Fidelity Verifier and Repair Loop

**Goal:** Block low-fidelity normalization before builder invocation.

New file:

- `utils/toolkit_fidelity_verifier.py`

Core functions:

```python
def verify_normalization_fidelity(source_graph: Dict[str, Any], packet: Dict[str, Any], blueprint: Dict[str, Any]) -> Dict[str, Any]:
    """Compare source graph against packet and blueprint."""

def build_repair_request(fidelity_report: Dict[str, Any], source_graph: Dict[str, Any]) -> Dict[str, Any]:
    """Build targeted repair payload for failed categories."""
```

Tasks:

1. Compare required NPCs, locations, plot beats, puzzles, clues, encounters, items, and tone markers.
2. Detect renames by source ID, alias table, and normalized names.
3. Detect unsupported major additions.
4. Produce `normalization_fidelity_report.json`.
5. Run targeted repair loop for blockers and major findings.
6. Require human review if automatic repair fails.

Repair loop rules:

- Max 2 automatic repair attempts.
- Repair one category at a time.
- Never ask the model to re-normalize the full source unless source graph is invalid.
- Persist every repair attempt.

Acceptance:

- Missing required source NPC/location/puzzle blocks build.
- Unsupported replacement plotline blocks build.
- Numillian cannot proceed if the Trial at the Door is missing.

Suggested tests:

- `scripts/test_normalization_fidelity_check.py`
- `scripts/test_fidelity_repair_loop.py`
- `scripts/test_unsupported_invention_detection.py`

---

### Phase 6: Review UI Fidelity Panel

**Goal:** Make source fidelity visible before the user approves build.

Update:

- `web/routes/toolkit_homebrew_routes.py`
- `web/templates/module_toolkit.html`
- `utils/toolkit_homebrew_upload_contract.py`

Review UI should show:

- Required NPC coverage.
- Required location coverage.
- Plot beat coverage.
- Puzzle/trial coverage.
- Clue coverage.
- Unsupported additions.
- Ambiguous entities.
- Repair history.
- Waiver-required findings.

Actions:

- `Approve build` only when no blockers remain.
- `Run repair` for degraded categories.
- `Approve with waiver` for major/minor issues only, never blockers by default.
- `Abort`.

Acceptance:

- Existing review approval cannot bypass blocker omissions in accurate-ingest mode.
- User can see exactly which source elements were preserved or lost.

Suggested tests:

- `scripts/test_toolkit_review_fidelity_contract.py`
- `scripts/test_toolkit_homebrew_readiness_gate.py` extensions.

---

### Phase 7: Blueprint-Aware Builder Handoff

**Goal:** Stop `ModuleBuilder` from replacing source structure.

Tasks:

1. Update `web/extensions/toolkit_homebrew_packet_builder.py` to include blueprint path and source lock settings in `builder_input.json`.
2. Short-term: pass expanded blueprint narrative to `ModuleBuilder.build_module(...)`.
3. Add builder prompt/source-lock language wherever module generation fields are created.
4. Add post-stage audit hooks after overview, area, location, plot, and NPC reconciliation stages.
5. Persist `build_fidelity_report.json`.

Short-term builder narrative must include:

- Exact NPC roster with roles and source locations.
- Exact location roster grouped into areas.
- Plot beat sequence.
- Puzzle/trial rules.
- Clue graph.
- Encounter plan.
- Tone profile.
- Explicit forbidden inventions.

Medium-term builder changes:

- Seed `ModuleGenerator.generate_module(...)` with `custom_values` derived from blueprint.
- Use blueprint world map to reduce creative area invention.
- Use blueprint location roster to constrain area/location generation.

Acceptance:

- Builder input contains source lock data.
- Generated module preserves all required source locations by name or approved mapped equivalent.
- Generated plot keeps source plot topology.

Suggested tests:

- `scripts/test_packet_builder_blueprint_handoff.py`
- `scripts/test_build_fidelity_stage_gates.py`

---

### Phase 8: Build-Time Fidelity Gates

**Goal:** Detect fidelity loss during module construction, not after publication.

New file:

- `utils/toolkit_build_fidelity.py`

Stage gates:

1. **Module overview gate:** title, tone, main objective, antagonist, acts.
2. **Area gate:** all blueprint areas present; no replacement area set.
3. **Location gate:** required location roster covered; approved merges documented.
4. **NPC gate:** required NPC roster covered; no source NPC renamed without alias mapping.
5. **Plot gate:** mainline plot beats covered; source puzzles preserved.
6. **Encounter gate:** source encounters and monsters represented or reviewed.
7. **Tone gate:** source tone markers represented in descriptions/dmInstructions.

Acceptance:

- A build that drops required source locations fails readiness.
- A build that invents a replacement central plot fails source fidelity.
- Reports identify the exact stage where fidelity was lost.

Suggested tests:

- `scripts/test_toolkit_build_fidelity.py`
- `scripts/test_toolkit_module_build_publication_parity.py` extensions.

---

### Phase 9: Narrative Enrichment Placeholder Pass

**Goal:** Reserve an explicit post-build extension point for Ancients Lab and Deepvault-style enrichment without mixing it into source extraction.

New file:

- `utils/toolkit_narrative_enrichment_plan.py`

New prompt placeholders:

- `prompts/toolkit/narrative_enrichment_profile_prompt.txt`
- `prompts/toolkit/narrative_enrichment_field_patch_prompt.txt`

Tasks:

1. Add enrichment profile selection to the build/report artifacts.
2. Default to `none`.
3. Generate `narrative_enrichment_plan.json` only after source fidelity passes.
4. Include field budgets and eligible field list.
5. Include profile scaffolds:
   - `three_stance_single_turn` from Deepvault lessons.
   - `five_playline_stateful` from Ancients Lab lessons.
6. Do not auto-apply enrichment in the first implementation unless explicitly enabled.

Acceptance:

- Accurate ingest can complete without enrichment.
- Enrichment profile can be reviewed as a separate artifact.
- Enrichment cannot reduce source fidelity score.

Suggested tests:

- `scripts/test_narrative_enrichment_plan_contract.py`
- `scripts/test_narrative_enrichment_source_lock.py`

---

### Phase 10: Deterministic Path Expansion

**Goal:** Let structured markdown bypass LLM normalization when possible.

Update:

- `core/importers/homebrewery_importer.py`

Tasks:

1. Generalize room parsing into content block parsing.
2. Support heading styles:
   - `## Room N: Title`
   - `### N. Location Name`
   - `### N - Location Name`
   - `#### N. Sub-location`
3. Convert map-key location blocks into importer-compatible location objects.
4. Preserve source graph artifacts even for deterministic path.
5. Fall back to multi-pass LLM path only when deterministic parsing is insufficient.

Acceptance:

- Numillian-style map-key structure is recognized mechanically.
- Deterministic importer no longer silently skips non-`Room N` structures.

Suggested tests:

- `scripts/test_content_blocks_fallback.py`
- `scripts/test_homebrewery_importer_map_key_locations.py`

---

### Phase 11: Final Benchmark and Publication Gate Integration

**Goal:** Make accurate ingest measurable and enforceable.

Tasks:

1. Run Numillian through the new path.
2. Compare final module against source graph.
3. Add source fidelity status to toolkit readiness/build reports.
4. Add publication warnings for source-fidelity degraded modules.
5. Document operator workflow.

Acceptance for Numillian:

- 20/20 named source NPCs either represented or intentionally classified minor/unused with review note.
- 13/13 source locations preserved by original name or approved exact mapping.
- Trial at the Door structure preserved, including skull riddle, flooding room puzzle, and kill-the-dog mindscape test.
- Gatepact lore represented in module objective/plot.
- Kobe protection objective preserved.
- No ward-network conspiracy replacement unless source explicitly supports it.
- Tone report confirms quirky character-driven hidden city, not generic conspiracy thriller.

Suggested tests:

- `scripts/test_accurate_ingest_numillian_benchmark.py`
- `scripts/test_audit_module_publishability.py` extensions.

---

## Feature Flags and Rollout

Add model/config flags rather than replacing the old path immediately:

```python
ENABLE_ACCURATE_INGEST_SOURCE_GRAPH = True
ENABLE_ACCURATE_INGEST_MULTI_PASS = True
ENABLE_ACCURATE_INGEST_REPAIR_LOOP = True
ENABLE_ACCURATE_INGEST_BLUEPRINT_HANDOFF = True
ENABLE_ACCURATE_INGEST_ENRICHMENT_PLACEHOLDER = True
ACCURATE_INGEST_MAX_REPAIR_ATTEMPTS = 2
```

Rollout:

1. Source graph generation on by default for readable uploads.
2. Multi-pass extraction behind accurate-ingest flag.
3. Fidelity report visible but warning-only initially.
4. Blocker enforcement enabled after Numillian benchmark passes.
5. Blueprint handoff enabled after builder-stage audit tests pass.
6. Enrichment placeholder remains artifact-only until separately approved.

---

## Files To Create

| File | Purpose |
|---|---|
| `utils/toolkit_source_manifest.py` | Mechanical source manifest and source graph extraction. |
| `utils/toolkit_source_extraction.py` | Section-bounded LLM extraction orchestration. |
| `utils/toolkit_source_graph_synthesis.py` | Identity, criticality, and plot topology synthesis. |
| `utils/toolkit_builder_blueprint.py` | Blueprint generation and narrative serialization. |
| `utils/toolkit_fidelity_verifier.py` | Normalization fidelity comparison and repair request generation. |
| `utils/toolkit_build_fidelity.py` | Build-time source preservation audits. |
| `utils/toolkit_narrative_enrichment_plan.py` | Enrichment profile placeholder and field budget planning. |
| `prompts/toolkit/source_section_extraction_prompt.txt` | Section extraction prompt. |
| `prompts/toolkit/source_identity_adjudication_prompt.txt` | Alias/entity adjudication prompt. |
| `prompts/toolkit/source_plot_topology_prompt.txt` | Plot and puzzle topology prompt. |
| `prompts/toolkit/narrative_enrichment_profile_prompt.txt` | Future enrichment profile prompt. |
| `scripts/benchmark_accurate_ingest.py` | Benchmark runner for source fidelity fixtures. |

---

## Files To Modify

| File | Change |
|---|---|
| `utils/toolkit_homebrew_normalizer.py` | Build source graph, run multi-pass extraction, generate packet/blueprint, run fidelity verifier. |
| `utils/toolkit_homebrew_upload_contract.py` | Add artifact helpers, source fidelity report helpers, stronger review validation. |
| `web/extensions/toolkit_homebrew_packet_builder.py` | Read blueprint artifacts, include blueprint in builder input, persist build fidelity reports. |
| `web/routes/toolkit_homebrew_routes.py` | Surface fidelity reports and repair/waiver actions. |
| `web/templates/module_toolkit.html` | Add source fidelity review panel. |
| `core/importers/homebrewery_importer.py` | Generalized content block parser for map-key structures. |
| `core/generators/module_builder.py` | Add optional blueprint/source-lock awareness and stage audit hooks. |
| `core/generators/module_generator.py` | Seed generated module structure from blueprint/custom values where safe. |
| `prompts/toolkit/homebrew_upload_normalization_prompt.txt` | Retain as legacy fallback or reduce to packet synthesis prompt. |
| `model_config.py` | Add accurate ingest flags and repair attempt limits. |

---

## Test Plan

Minimum regression suites:

- `scripts/test_source_manifest_headings.py`
- `scripts/test_source_manifest_tables.py`
- `scripts/test_source_manifest_locations.py`
- `scripts/test_source_manifest_entities.py`
- `scripts/test_source_graph_integration.py`
- `scripts/test_source_section_extraction_contract.py`
- `scripts/test_source_identity_resolution.py`
- `scripts/test_source_criticality.py`
- `scripts/test_source_plot_topology.py`
- `scripts/test_builder_blueprint_generation.py`
- `scripts/test_builder_narrative_source_lock.py`
- `scripts/test_normalized_packet_source_refs.py`
- `scripts/test_normalization_fidelity_check.py`
- `scripts/test_fidelity_repair_loop.py`
- `scripts/test_unsupported_invention_detection.py`
- `scripts/test_toolkit_review_fidelity_contract.py`
- `scripts/test_packet_builder_blueprint_handoff.py`
- `scripts/test_build_fidelity_stage_gates.py`
- `scripts/test_toolkit_build_fidelity.py`
- `scripts/test_narrative_enrichment_plan_contract.py`
- `scripts/test_narrative_enrichment_source_lock.py`
- `scripts/test_content_blocks_fallback.py`
- `scripts/test_homebrewery_importer_map_key_locations.py`
- `scripts/test_accurate_ingest_numillian_benchmark.py`

Validation commands should use `.venv/bin/python` for dependency-sensitive paths.

---

## Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Token budget grows with source graph. | Section-bounded extraction and compact evidence excerpts. |
| False positive entity extraction pollutes module. | Criticality classification plus review UI. |
| Too many LLM calls increase latency/cost. | Cache section extraction by source hash and section hash. |
| GPT 5.4 Mini High still misses details. | Adversarial verifier and targeted repair loop. |
| Builder ignores source locks. | Blueprint-aware handoff plus build-time fidelity gates. |
| Enrichment rewrites source. | Enrichment runs only after source fidelity pass and cannot lower fidelity score. |
| Existing pipeline compatibility breaks. | Feature flags and legacy fallback path. |
| Review UI becomes overwhelming. | Show blocker summary first, with expandable detail tables. |

---

## Success Criteria

1. Numillian benchmark passes source-fidelity gates.
2. Required source NPCs and map-key locations are preserved by name or approved mapping.
3. Source puzzle/trial mechanics are preserved.
4. Unsupported replacement plotlines are blocked.
5. Builder receives a source-locked blueprint, not only a prose summary.
6. Build-time audits identify any stage that loses source material.
7. Narrative enrichment is available as a separate, source-preserving placeholder pass.
8. Existing deterministic ingest and legacy normalization paths remain available behind flags/fallbacks.

---

## OpenSpec Recommendation

This is too large for one implementation change. Split into OpenSpec changes:

1. `toolkit-accurate-ingest-source-graph`
   - Source manifest/source graph extraction and Numillian benchmark baseline.
2. `toolkit-accurate-ingest-multipass-normalization`
   - Section extraction, identity resolution, plot topology, packet synthesis.
3. `toolkit-accurate-ingest-fidelity-repair`
   - Fidelity verifier, repair loop, review UI blocker handling.
4. `toolkit-accurate-ingest-blueprint-builder-handoff`
   - Builder blueprint, source-locked narrative, builder input integration.
5. `toolkit-accurate-ingest-build-fidelity-gates`
   - Stage audits and final source fidelity report.
6. `toolkit-accurate-ingest-narrative-enrichment-placeholder`
   - Enrichment profile artifact and source-preserving guardrails.

Implement in that order. Do not start enrichment before source fidelity gates are reliable.
